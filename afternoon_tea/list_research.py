"""List-first collection with durable checkpoints; fetched text is never a verified plan."""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import urlsplit

from .master import ROOT
from .official_research import collect
from .read_only import check_url, ForbiddenOperation
from .research import Browser
from .research_store import atomic_json

REFERENCE = ROOT / 'data/references/user_candidates_385.csv'
HEADERS = ['No','店名','最寄り駅','ジャンル','予約サイト','予約ページURL','備考']
TERMINAL = {'reviewed','excluded','information_insufficient','access_restricted'}


def reference(path=REFERENCE):
    raw=Path(path).read_bytes()
    reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    if reader.fieldnames != HEADERS: raise ValueError('candidate_columns_changed')
    rows=list(reader)
    if len(rows)!=385 or [r['No'] for r in rows] != [str(i) for i in range(1,386)]:
        raise ValueError('candidate_rows_missing_or_reordered')
    if any(None in r or any(v is None for v in r.values()) for r in rows):
        raise ValueError('malformed_candidate_row')
    return rows,hashlib.sha256(raw).hexdigest()


def initialize(research, checkpoint=None):
    rows,digest=reference()
    if checkpoint:
        if checkpoint.get('reference_sha256')!=digest: raise ValueError('reference_changed')
        if [r['no'] for r in checkpoint['rows']] != list(range(1,386)):
            raise ValueError('checkpoint_rows_missing')
        return checkpoint
    shops=research.get('shops',[])
    records=[]
    for row in rows:
        url=row['予約ページURL']
        # Only exact service venue IDs or exact normalized names are matches.
        def normalize(s): return ''.join(s.split()).casefold()
        hits=[]
        for shop in shops:
            sources=[shop.get('source_url','')]+[p.get('source_url','') for p in shop.get('plans',[])]
            if url.rstrip('/') in [s.rstrip('/') for s in sources if isinstance(s,str)] or normalize(row['店名'])==normalize(shop.get('name','')):
                hits.append(shop)
        records.append({'no':int(row['No']),'original':row,'matched_shop_id':hits[0].get('id') if len(hits)==1 else None,
                        'identity_status':'exact_match' if len(hits)==1 else 'needs_identity_review',
                        'status':'unresearched','attempts':[],'reviewed_sources':[]})
    return {'version':1,'reference_sha256':digest,'phase':'list','rows':records,'discovery':[],
            'publication_ready':False,'note':'Candidate rows, fetched pages and reviewed AT facts are distinct.'}


def list_traversed(campaign):
    return len(campaign['rows'])==385 and all(r['status'] in TERMINAL for r in campaign['rows'])


def run(campaign, directory, browser=None, limit=385):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    if browser is None:
        from .communication_audit import CommunicationAudit
        import uuid
        run_id=uuid.uuid4().hex
        browser=Browser(max_requests=150,audit=CommunicationAudit(run_id,directory/('audit-'+run_id+'.jsonl')))
    campaign['publication_ready']=False
    if any(r['status']=='interrupted' for r in campaign['rows']):
        campaign['stop_reason']='forbidden_operation'
        atomic_json(directory/'checkpoint.json',campaign)
        return campaign
    processed=0
    for row in campaign['rows']:
        if row['status']!='unresearched': continue
        if processed>=limit or browser.count>=browser.max_requests: break
        url=row['original']['予約ページURL'];stamp=dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            check_url(url) # never grant permission based on pasted text
            report=collect([{'id':str(row['no']),'url':url,'areas':[],'purpose':'existing','path_prefix':urlsplit(url).path.rstrip('/')+'/'}],[],
                           directory/str(row['no']),browser,seconds=90,max_depth=2)
            row['attempts'].append({'checked_at':stamp,'url':url,'pages':report['pages'],
                                    'errors':report['attempts'],'requests_total':browser.count})
            if report['stop_reason']=='forbidden_operation':
                row['status']='interrupted';campaign['stop_reason']='forbidden_operation'
                campaign['network_events']=browser.network_events
                campaign['communication_audit']=browser.communication_audit.snapshot()
                atomic_json(directory/'checkpoint.json',campaign)
                return campaign
            row['status']='awaiting_review' if report['pages'] else 'access_restricted'
            row['reason']='Read fetched documents and verify plan identity; no automatic confirmation.' if report['pages'] else 'No document retrieved. Check independent official sources before final disposition.'
        except ForbiddenOperation as error:
            row['status']='interrupted';row['reason']=str(error)
            campaign['stop_reason']='forbidden_operation'
            atomic_json(directory/'checkpoint.json',campaign)
            return campaign
        processed+=1
        atomic_json(directory/'checkpoint.json',campaign)
    campaign['stop_reason']='batch_finished'
    campaign['phase']='discovery' if list_traversed(campaign) else 'list'
    campaign['network_events']=browser.network_events
    atomic_json(directory/'checkpoint.json',campaign)
    return campaign


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT/'.staging/list-research')
    p.add_argument('--limit',type=int,default=385)
    args=p.parse_args()
    research=json.loads((ROOT/'site/research.json').read_text())
    saved=args.output/'checkpoint.json'
    failures=json.loads((ROOT/'site/search_failures.json').read_text())
    checkpoint=json.loads(saved.read_text()) if saved.exists() else failures.get('research_campaign')
    state=run(initialize(research,checkpoint),args.output,limit=args.limit)
    print(json.dumps({'processed':sum(r['status']!='unresearched' for r in state['rows']),
                      'statuses':{s:sum(r['status']==s for r in state['rows']) for s in {r['status'] for r in state['rows']}},
                      'phase':state['phase'],'stop_reason':state['stop_reason']},ensure_ascii=False))
    return 2 if state['stop_reason']=='forbidden_operation' else 0

if __name__=='__main__': raise SystemExit(main())
