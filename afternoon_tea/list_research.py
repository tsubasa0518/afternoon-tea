"""List-first campaigns with portable evidence, entity queues and explicit refresh."""
import argparse
import copy
import csv
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
import uuid
from .master import ROOT
from .official_research import links
from .read_only import check_url, ForbiddenOperation
from .research import Browser
from .research_store import atomic_json, store_lock
from .research_evidence import archive_acquired_text, restore_documents

REFERENCE=ROOT/'data/references/user_candidates_385.csv'
HEADERS=['No','店名','最寄り駅','ジャンル','予約サイト','予約ページURL','備考']
TERMINAL={'reviewed','excluded','information_insufficient','access_restricted'}
FRESH_DAYS=14


def current_day():
    from .data import JST
    return dt.datetime.now(JST).date()


def reference(path=REFERENCE):
    raw=Path(path).read_bytes();reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    if reader.fieldnames!=HEADERS:raise ValueError('candidate_columns_changed')
    rows=list(reader)
    if len(rows)!=385 or [r['No'] for r in rows]!=[str(i) for i in range(1,386)]:raise ValueError('candidate_rows_missing_or_reordered')
    if any(None in r or any(v is None for v in r.values()) for r in rows):raise ValueError('malformed_candidate_row')
    return rows,hashlib.sha256(raw).hexdigest()


def venue_key(url):
    """Service-specific identity; a store and its plan share one key."""
    if not isinstance(url,str):return None
    p=urlsplit(url);host=p.hostname
    if host=='restaurant.ikyu.com':match=re.fullmatch(r'/(\d+)(?:/plan\d+)?/?',p.path)
    elif host=='tabelog.com':match=re.fullmatch(r'/tokyo/(?:a\d+/)*(\d+)/(?:party/(?:\d+/)?)?',p.path)
    elif host in ('tablecheck.com','www.tablecheck.com'):match=re.fullmatch(r'/(?:ja|en)/(?:shops/)?([a-z0-9_-]+)(?:/reserve(?:/landing)?)?/?',p.path)
    else:return None
    return ('tablecheck.com' if host=='www.tablecheck.com' else host)+':'+match.group(1) if match else None


def entity_sources(entity):
    return list(dict.fromkeys(entity['urls']))


def initialize(research,checkpoint=None,day=None):
    rows,sha=reference();day=day or current_day();week=(day-dt.timedelta(days=day.weekday())).isoformat()
    if checkpoint:
        if checkpoint.get('reference_sha256')!=sha:raise ValueError('reference_changed')
        if [r.get('no') for r in checkpoint['rows']]!=list(range(1,386)):raise ValueError('checkpoint_rows_missing')
        if any(r.get('original')!=o for r,o in zip(checkpoint['rows'],rows)):raise ValueError('checkpoint_original_changed')
        if checkpoint.get('version')==2:
            if dt.date.fromisoformat(checkpoint['started_on'])>day:raise ValueError('future_campaign_checkpoint')
            if checkpoint['phase']!='complete' or checkpoint['week_key']==week:
                checkpoint['week_key']=week
                refresh_due(checkpoint,day)
                return checkpoint # unfinished campaigns survive week boundaries intact
        fresh=initialize(research,day=day)
        fresh['history']=copy.deepcopy(checkpoint.get('history',[]))+[{
            'campaign_id':checkpoint.get('campaign_id'),'week_key':checkpoint.get('week_key'),
            'rows':[{'no':r['no'],'status':r['status'],'reviewed_sources':r.get('reviewed_sources',[])} for r in checkpoint['rows']]}]
        for new,old in zip(fresh['rows'],checkpoint['rows']):
            if old['status']=='interrupted':new.update(copy.deepcopy(old))
        fresh['legacy_checkpoint']={k:copy.deepcopy(checkpoint[k]) for k in ('stop_reason','communication_audit','network_events') if k in checkpoint} if checkpoint.get('version')!=2 else None
        return fresh
    index={}
    for shop in research.get('shops',[]):
        urls=[shop.get('source_url')]+[p.get('source_url') for p in shop.get('plans',[])]
        for url in urls:
            key=venue_key(url)
            if key:index.setdefault(key,[]).append(shop)
    records=[];entities={}
    for row in rows:
        url=row['予約ページURL'];key=venue_key(url) or 'url:'+hashlib.sha256(url.encode()).hexdigest()
        hits={s['id']:s for s in index.get(key,[]) if s.get('id')}
        matched=next(iter(hits)) if len(hits)==1 else None
        entity=key # row identity is stable even when the public shop ID changes
        records.append({'no':int(row['No']),'original':row,'entity_id':entity,'matched_shop_id':matched,
                        'identity_status':'service_id_match' if matched else 'needs_identity_review',
                        'status':'unresearched','attempts':[],'reviewed_sources':[]})
        group=entities.setdefault(entity,{'rows':[],'urls':[],'queue':[],'seen':[],'documents':[]})
        group['rows'].append(int(row['No']))
        if url not in group['urls']:
            group['urls'].append(url);group['queue'].append({'url':url,'depth':0,'prefix':urlsplit(url).path.rstrip('/')+'/'})
    return {'version':2,'campaign_id':uuid.uuid4().hex,'started_on':day.isoformat(),'week_key':week,
            'reference_sha256':sha,'phase':'list','rows':records,'entities':entities,'documents':{},
            'audit_segments':{},'discovery':[],'publication_ready':False}


def refresh_due(campaign,day):
    """Keep initial traversal progress; refresh only expired reviewed evidence."""
    from .data import JST
    refreshed=set()
    for row in campaign['rows']:
        if row['status'] not in ('reviewed','excluded') or not row.get('reviewed_sources'):continue
        oldest=min(dt.datetime.fromisoformat(s['checked_at']).astimezone(JST).date() for s in row['reviewed_sources'])
        if oldest>=day-dt.timedelta(days=FRESH_DAYS):continue
        row.setdefault('history',[]).append({'status':row['status'],'reviewed_sources':copy.deepcopy(row['reviewed_sources'])})
        row.update(status='needs_refresh',reviewed_sources=[])
        entity_id=row['entity_id'];entity=campaign['entities'][entity_id]
        entity_id=entity.get('collection_alias',entity_id);entity=campaign['entities'][entity_id]
        if entity_id in refreshed:continue
        refreshed.add(entity_id)
        entity['queue']=[{'url':url,'depth':0,'prefix':urlsplit(url).path.rstrip('/')+'/'} for url in entity['urls']]
        entity['seen']=[]
    if refreshed:campaign['publication_ready']=False


def list_traversed(campaign):
    return len(campaign['rows'])==385 and all(r['status'] in TERMINAL for r in campaign['rows'])


def link_identity(campaign,left,right,sources):
    """Explicit reviewed cross-site match; never merge merely similar names."""
    from .research_evidence import validate_audit,source_document
    docs={k:v for a in campaign['audit_segments'].values() for k,v in validate_audit(a).items()}
    a=campaign['rows'][left-1];b=campaign['rows'][right-1]
    if a['no']!=left or b['no']!=right:raise ValueError('identity_row_missing')
    if a['entity_id']==b['entity_id']:return
    identity_texts=[]
    for row in (a,b):
        proof=next((s for s in sources if s.get('subject_id')==row['entity_id']),None)
        if not proof:raise ValueError('identity_evidence_missing')
        identity_texts.append(source_document(campaign,proof,row['entity_id'],docs))
    addresses=[s.get('verified_address') for s in sources]
    if not addresses or any(not v or v!=addresses[0] for v in addresses):raise ValueError('identity_address_mismatch')
    names=[s.get('verified_name') for s in sources]
    if len(sources)!=2 or not names[0] or names[0]!=names[1] or any(addresses[0] not in text or names[0] not in text for text in identity_texts):
        raise ValueError('identity_name_or_address_not_in_evidence')
    # Keep original evidence subjects intact; aliases are used only for collection grouping.
    target=campaign['entities'][a['entity_id']];other=campaign['entities'][b['entity_id']]
    target.setdefault('identity_links',[]).append({'entity_id':b['entity_id'],'sources':copy.deepcopy(sources)})
    other['collection_alias']=a['entity_id']
    for task in other['queue']:
        if task['url'] not in {t['url'] for t in target['queue']} and task['url'] not in target['seen']:target['queue'].append(task)
    target['urls']=list(dict.fromkeys(target['urls']+other['urls']))
    target['rows']=sorted(set(target['rows']+other['rows']))


def run(campaign,directory,browser=None,limit=385,seconds=600,clock=time.monotonic):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    # Restoring evidence precedes status-based skips and performs no HTTP.
    restore_documents(campaign,directory/'documents')
    if campaign.get('phase')=='complete' and campaign.get('publication_ready') is True:
        campaign['stop_reason']='already_collected'
        atomic_json(directory/'checkpoint.json',campaign)
        return campaign
    campaign['publication_ready']=False
    if campaign.get('stop_reason')=='evidence_or_storage_error':
        atomic_json(directory/'checkpoint.json',campaign)
        return campaign
    if any(r['status']=='interrupted' for r in campaign['rows']):
        campaign['stop_reason']='forbidden_operation';atomic_json(directory/'checkpoint.json',campaign);return campaign
    if campaign.get('version')!=2:raise ValueError('campaign_migration_required')
    if browser is None:
        from .communication_audit import CommunicationAudit
        run_id=uuid.uuid4().hex
        browser=Browser(max_requests=150,audit=CommunicationAudit(run_id,directory/('audit-'+run_id+'.jsonl')))
    deadline=clock()+seconds;processed=0;stop=None
    def save():
        snapshot=browser.communication_audit.snapshot(browser.count)
        campaign.setdefault('audit_segments',{})[snapshot['run_id']]=snapshot
        campaign.pop('communication_audit',None)
        campaign['latest_audit_id']=snapshot['run_id']
        atomic_json(directory/'checkpoint.json',campaign)
    ordered=sorted(campaign['entities'].items(),key=lambda item:all(campaign['rows'][no-1]['status']=='needs_refresh' for no in item[1]['rows']))
    save()
    for subject,entity in ordered:
        if entity.get('collection_alias'):continue
        members=[r for r in campaign['rows'] if r['entity_id']==subject or campaign['entities'][r['entity_id']].get('collection_alias')==subject]
        if not entity['queue']:continue
        if processed>=limit or clock()>=deadline or browser.count>=browser.max_requests:stop='budget_or_deadline';break
        processed+=1
        while entity['queue']:
            if clock()>=deadline or browser.count>=browser.max_requests:stop='budget_or_deadline';break
            task=entity['queue'][0];url=task['url']
            if url in entity['seen']:entity['queue'].pop(0);continue
            try:
                check_url(url,public_hosts=browser.transport.public_hosts)
                raw=browser.fetch(url)
                page,found,_,_=links(raw,url,browser.transport.public_hosts,task['prefix'])
                text='\n'.join(page.parts)
                key=archive_acquired_text(campaign,browser.communication_audit,subject,url,text,
                                          hashlib.sha256(raw.encode()).hexdigest(),browser.transport.public_hosts)
                checked_at=campaign['documents'][key]['checked_at']
                entity['documents'].append(key);entity['seen'].append(url);entity['queue'].pop(0)
                for member in members:
                    member['attempts'].append({'url':url,'checked_at':checked_at,'document_id':key})
                if task['depth']<2:
                    queued={t['url'] for t in entity['queue']}
                    for _,child,_ in found:
                        if child not in queued and child not in entity['seen']:
                            entity['queue'].append({'url':child,'depth':task['depth']+1,'prefix':task['prefix']});queued.add(child)
            except ForbiddenOperation as error:
                browser.communication_audit.decision(url,str(error),violation=True)
                for member in members:member.update(status='interrupted',reason=str(error))
                campaign['stop_reason']='forbidden_operation';save();return campaign
            except RuntimeError as error:
                if str(error)=='request_budget_exhausted':stop='budget_or_deadline';break
                if not str(error).startswith(('HTTP_','robots_','host_','access_','page_too_large','not_html','cross_host_redirect')):
                    campaign['stop_reason']='evidence_or_storage_error';save();raise
                entity['seen'].append(url);entity['queue'].pop(0)
                for member in members:member['attempts'].append({'url':url,'reason':str(error),'checked_at':dt.datetime.now(dt.timezone.utc).isoformat()})
            except (ValueError,OSError,KeyError):
                campaign['stop_reason']='evidence_or_storage_error';save();raise
            for member in members:
                member['status']='needs_collection' if entity['queue'] else 'awaiting_review' if entity['documents'] else 'access_restricted'
            save()
        if stop:break
    campaign['stop_reason']=stop or 'batch_finished'
    campaign['phase']='discovery' if list_traversed(campaign) else 'list'
    save();restore_documents(campaign,directory/'documents')
    return campaign


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT/'.staging/list-research');p.add_argument('--limit',type=int,default=385)
    p.add_argument('--seconds',type=float,default=600);args=p.parse_args()
    if args.limit<0 or args.seconds<=0:raise ValueError('invalid_collection_budget')
    with store_lock(args.output):
        research=json.loads((ROOT/'site/research.json').read_text());saved=args.output/'checkpoint.json'
        failures=json.loads((ROOT/'site/search_failures.json').read_text())
        checkpoint=json.loads(saved.read_text()) if saved.exists() else failures.get('research_campaign')
        state=run(initialize(research,checkpoint),args.output,limit=args.limit,seconds=args.seconds)
        print(json.dumps({'campaign_id':state['campaign_id'],'processed':sum(r['status']!='unresearched' for r in state['rows']),
                          'phase':state['phase'],'stop_reason':state['stop_reason']},ensure_ascii=False))
    return 2 if state['stop_reason']=='forbidden_operation' else 1 if state['stop_reason']=='evidence_or_storage_error' else 0

if __name__=='__main__':raise SystemExit(main())
