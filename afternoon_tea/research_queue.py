"""Persistent bounded research of the 70 masters, 5 candidates, and discovered URLs."""
import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin,urlsplit
from .data import JST
from .master import ROOT,load_master,dumps
from .pipeline import protected_files,staging_directory,build
from .research import Browser
from .read_only import check_url,ForbiddenOperation
from .extraction import Document,first,extract,apply_page,match_master
from .research_store import load_state,save_state,atomic_json,add_discovery,differences,store_lock
from .validation import normalize

STORE=ROOT/'research_data'

def component(t):
    t=re.sub(r'（[^（）]*(?:F|階|ロビーラウンジ)[^（）]*）','',t)
    t=re.sub(r'\s*\d+F$','',t)
    return normalize(t)

def attach_seeds(state,html):
    """Old HTML supplies identity hints and URLs only, never current plan values."""
    if state.get('seed_matcher_version')!=2:
        for item in state['items']:
            if item['kind']!='discovered':
                if any(item['sources'].values()):item.setdefault('source_hint_history',[]).append({'sources':copy.deepcopy(item['sources']),'reason':'Seed matcher upgraded; hints are not verified facts'})
                item['sources']={k:[] for k in ('ik','tb','tc')}
        state['seed_matcher_version']=2
    root=Document(html).root
    for article in root.find('article'):
        name=first(article.find('h4'));lounge=first(article.find(cls='shop'))
        hits=[]
        for item in state['items']:
            if item['kind']=='discovered':continue
            parts=re.split('[（(]',item['name']);base=re.sub(r'\s*\d+F$','',parts[0])
            if lounge and len(parts)>1:
                if component(name)!=component(base):continue
                def venue_name(value):
                    value=re.sub(r'（[^（）]*(?:F|階)[^（）]*）','',value)
                    quoted=re.search(r'「([^」]+)」',value)
                    if quoted:return component(quoted.group(1))
                    value=re.sub(r'^(?:ロビーラウンジ|ティーラウンジ|ダイニング・カフェ|ラウンジバー|ラウンジ|カフェ)\s+(?=\S)','',value)
                    return component(value)
                if venue_name(lounge)==venue_name(parts[1].rstrip('）)')):hits.append(item)
            elif component(name)==component(item['name']) or component(name)==component(base):hits.append(item)
        if len(hits)!=1:continue
        for a in article.find('a'):
            u=a.attrs.get('href','');host=urlsplit(u).hostname
            if host=='restaurant.ikyu.com':u='https://restaurant.ikyu.com/'+urlsplit(u).path.strip('/').split('/')[0]+'/'
            if host in ('www.tablecheck.com','tablecheck.com'):u=u.replace('/en/','/ja/')
            try:check_url(u)
            except (ValueError,ForbiddenOperation):continue
            site='ik' if host=='restaurant.ikyu.com' else 'tb' if host=='tabelog.com' else 'tc'
            if u not in hits[0]['sources'][site]:hits[0]['sources'][site].append(u)


def public_links(raw,url):
    """Read document links only. Rejected action URLs are not requested."""
    root=Document(raw).root;result=[]
    for a in root.find('a'):
        u=urljoin(url,a.attrs.get('href',''))
        if u==url:continue
        try:check_url(u)
        except (ValueError,ForbiddenOperation):continue
        if re.search(r'/\d+/plan\d+',urlsplit(u).path):
            # A label must identify AT and one permitted meal; never inspect dinner plans.
            context=a;verified=False
            for _ in range(5):
                text=context.text
                plan_links=[n for n in context.find('a') if re.search(r'/\d+/plan\d+',n.attrs.get('href',''))]
                meal=re.match(r'^(ランチ|朝食|ディナー|ティー)(?:\s|$)',text)
                if len(text)<1800 and len(plan_links)<=1 and re.search(r'アフタヌーンティー|afternoon\s+tea',text,re.I) and meal:
                    verified=meal.group(1) in ('ランチ','朝食');break
                if not context.parent:break
                context=context.parent
            if not verified:continue
        if u not in [x[0] for x in result]:result.append((u,a.text))
    return result


def process(item,state,master,browser,directory,deadline):
    attempts=[];any_fetch=False;any_document=False;errors=[]
    for site in ('ik','tb','tc'):
        urls=list(item['sources'][site]);seen=set();records=[]
        if not urls:
            attempts.append({'site':site,'status':'unresolved','reason':'No verified discovery route/URL available; not evidence of absence'});continue
        for url in urls:
            if len(seen)>=4:break
            if time.monotonic()>=deadline:raise TimeoutError('time_budget')
            if url in seen:continue
            seen.add(url)
            fetched_this_page=False;candidate_data=None
            try:
                raw=browser.fetch(url);any_fetch=True;fetched_this_page=True
                if item['kind']=='master':
                    source=next(s for a in master['areas'] for g in a['cats'].values() for s in g['shops'] if s['id']==item['id'])
                    pre=extract(raw,url,state['day'])
                    if match_master(pre,source):
                        candidate_data=copy.deepcopy(state['data']);result=apply_page(candidate_data,master,raw,url)
                    else:
                        result=pre;result['reasons'].append('expected_master_identity_not_verified')
                else:result=extract(raw,url,state['day'])
                evidence={'url':url,'checked_at':dt.datetime.now(JST).isoformat(),'item_id':item['id'],'extraction':result}
                key=hashlib.sha256(dumps(evidence).encode()).hexdigest()
                atomic_json(Path(directory)/'evidence'/(key+'.json'),evidence)
                any_document=True
                if result['status']=='confirmed' and candidate_data is not None:state['data']=candidate_data
                records.append({'url':url,'fetch':'success','evidence':'evidence/'+key+'.json','result':result['status'],'reasons':result['reasons']})
                item['partial_attempts']=attempts+[{'site':site,'pages':records}]
                links=public_links(raw,url)
                # Only same-store links become follow-up plan documents.
                base=urlsplit(url).path.strip('/').split('/')[0]
                for target,label in links:
                    if site=='ik' and urlsplit(target).path.startswith('/'+base+'/plan') and target not in urls:urls.append(target)
                    if site=='tb' and urlsplit(target).path.startswith(urlsplit(url).path.split('/party')[0].rstrip('/')+'/party/') and 'アフタヌーンティー' in label and target not in urls:urls.append(target)
                    if site=='tc' and '/shops/' in target and target.endswith('/reserve') and target not in urls:
                        source_slug=re.fullmatch(r'/(?:ja|en)/(?:shops/)?([^/]+)(?:/reserve)?/?',urlsplit(url).path)
                        target_slug=re.fullmatch(r'/(?:ja|en)/shops/([^/]+)/reserve/?',urlsplit(target).path)
                        if source_slug and target_slug and source_slug.group(1)==target_slug.group(1):urls.append(target)
                    if 'アフタヌーンティー' in label:
                        state['discovery'].append({'area':item['area'],'url':target,'label':label,'source_url':url,'checked_at':evidence['checked_at'],'status':'unresearched'})
                if item['kind']!='master':
                    genre=result['identity'].get('ジャンル','')
                    spec=(ROOT/'research_spec.md').read_text()
                    banned=[v for line in spec.splitlines() if line.startswith('- ') and ('系：' in line or line.startswith('- その他：')) for v in line.split('：',1)[1].split('／')]
                    if any(g.strip() in banned for g in re.split('[、／/]',genre) if g.strip()):
                        item.update(status='excluded',reason='Observed excluded genre: '+genre,attempts=attempts+[{'site':site,'status':'excluded','pages':records}]);return
                if result['status']=='confirmed':
                    item.update(status='confirmed',reason='Public identity/menu/booking evidence verified');attempts.append({'site':site,'status':'confirmed','pages':records});item['attempts']=attempts;return
                if item['kind']=='master' and any(r in result['reasons'] for r in ('excluded_genre','known_rating_below_3')):
                    item.update(status='excluded',reason=';'.join(result['reasons']));attempts.append({'site':site,'status':'excluded','pages':records});item['attempts']=attempts;return
            except ForbiddenOperation:
                item['attempts']=attempts+[{'site':site,'status':'blocked','url':url}];raise
            except Exception as e:
                errors.append(str(e));records.append({'url':url,'fetch':'success' if fetched_this_page else 'failed','processing':'failed','reason':str(e)})
                if str(e)=='request_budget_exhausted':raise TimeoutError('request_budget')
        attempts.append({'site':site,'status':'unresolved' if any(r.get('fetch')=='success' for r in records) else 'failed','pages':records})
    item.update(status='unresolved' if any_document or not errors else 'failed',reason='No eligible current plan verified; '+('; '.join(dict.fromkeys(errors)) if errors else 'source discovery/identity/menu incomplete'),attempts=attempts)


def _run(limit=75,seconds=600,max_requests=180,directory=STORE,browser=None,retry=False):
    protected_files();master=load_master();now=dt.datetime.now(JST);state=load_state(directory,master,str(now.date()))
    if retry:
        for item in state['items']:
            if item['status'] in ('unresolved','failed'):item['status']='unresearched'
    attach_seeds(state,(ROOT/'docs/index.html').read_text())
    # Verified public URLs from Step 9 are discovery seeds only and are fetched again.
    for mid,u in [('master-070','https://www.tablecheck.com/ja/shops/hotel-chinzanso-tokyo-jardin/reserve'),('master-010','https://www.tablecheck.com/ja/shops/palacehoteltokyo-the-palace-lounge/reserve')]:
        item=next(x for x in state['items'] if x['id']==mid)
        if u not in item['sources']['tc']:item['sources']['tc'].append(u)
    browser=browser or Browser(delay=1,timeout=8,max_requests=max_requests)
    state.pop('stop_reason',None)
    deadline=time.monotonic()+seconds;done=0
    pending=[x for x in state['items'] if x['status']=='unresearched']
    pending.sort(key=lambda x:0 if x['id'] in ('master-070','master-010') else 1)
    save_state(directory,state,master)
    for item in pending[:limit]:
        if time.monotonic()>=deadline:
            state['stop_reason']='time_budget';save_state(directory,state,master);break
        try:process(item,state,master,browser,directory,deadline)
        except TimeoutError as e:state['stop_reason']=str(e);save_state(directory,state,master);break
        except ForbiddenOperation as e:
            state['stop_reason']='forbidden_operation';item.update(status='failed',reason=str(e));save_state(directory,state,master);break
        done+=1;item['checked_at']=dt.datetime.now(JST).isoformat()
        item['history'].append({'day':state['day'],'status':item['status'],'reason':item.get('reason'),'checked_at':item['checked_at']})
        state['events'].append({'id':item['id'],'status':item['status'],'checked_at':item['checked_at'],'attempts':copy.deepcopy(item.get('attempts',[]))})
        save_state(directory,state,master)
    # Current-page discoveries are separate queued candidates, not automatically confirmed shops.
    for found in list(state['discovery']):
        add_discovery(state,found['url'],found['label'],found['area'],found['source_url'],found['checked_at'])
    from .discovery import reconcile_areas
    reconcile_areas(state)
    for area in state['areas']:
        findings=[d for d in state['discovery'] if d['area']==area['no'] and d['checked_at'].startswith(state['day'])]
        if findings:
            area['discovery_status']='incomplete'
            area['reason']='Encountered public AT links; full station/area/hotel-opening searches remain incomplete'
    state['diff']=differences(state);state['last_run']={'processed':done,'requests':browser.count,'finished_at':dt.datetime.now(JST).isoformat(),'complete_coverage':False,'reservation_operations':0}
    save_state(directory,state,master)
    out=staging_directory()/('queue-'+now.strftime('%Y%m%dT%H%M%S%f'));out.mkdir()
    atomic_json(out/('data_'+state['day']+'.json'),state['data']);atomic_json(out/'audit.json',{k:v for k,v in state.items() if k!='data'})
    if any(x['status']=='confirmed' for x in state['items']):
        html=build(state['data'])
        atomic_json(out/'artifact.json',{'html_directory':str(html),'temporary':True})
        state['last_run']['html_validated']=True
        state['last_run']['cards']=sum(s['research']['status']=='confirmed' for a in state['data']['areas'] for g in a['cats'].values() for s in g['shops'])
    state.setdefault('runs',[]).append(copy.deepcopy(state['last_run']))
    atomic_json(Path(directory)/'runs'/state['day']/(now.strftime('%Y%m%dT%H%M%S%f')+'-audit.json'),{'historical':True,'day':state['day'],'run':state['last_run'],'items':[{'id':x['id'],'status':x['status'],'reason':x.get('reason'),'attempts':x.get('attempts',[])} for x in state['items']]})
    save_state(directory,state,master)
    return out,state

def run(limit=75,seconds=600,max_requests=180,directory=STORE,browser=None,retry=False):
    with store_lock(directory):return _run(limit,seconds,max_requests,directory,browser,retry)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--limit',type=int,default=75);p.add_argument('--seconds',type=int,default=600);p.add_argument('--max-requests',type=int,default=180);p.add_argument('--retry-unresolved',action='store_true');a=p.parse_args()
    if not 1<=a.limit<=300 or not 1<=a.seconds<=3600 or not 1<=a.max_requests<=600:p.error('bounded positive limits required')
    out,state=run(a.limit,a.seconds,a.max_requests,retry=a.retry_unresolved);print(dumps({'output':str(out),'run':state['last_run'],'counts':{k:sum(x['status']==k for x in state['items']) for k in ('unresearched','confirmed','excluded','unresolved','failed')}}))
