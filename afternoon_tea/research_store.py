"""Versioned JSON checkpoints. Previous-day confirmation is never current confirmation."""
import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import os
from .data import create_data
from .master import dumps
from .validation import normalize, validate_data

STATUSES={'unresearched','confirmed','excluded','unresolved','failed'}

def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write(dumps(value));f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def area_for(master,label):
    hits=[a['no'] for a in master['areas'] if label in a['name'] or label in a['stations']]
    return hits[0] if len(hits)==1 else None

def create_queue(master):
    items=[]
    for a in master['areas']:
        for cat,g in a['cats'].items():
            for s in g['shops']:
                items.append({'id':s['id'],'name':s['name'],'kind':'master','area':a['no'],
                              'status':'unresearched','sources':{'ik':[],'tb':[],'tc':[]},'history':[]})
    for i,c in enumerate(master['candidates'],1):
        items.append({'id':f'candidate-{i:03}','name':c['name'],'kind':'candidate','area':area_for(master,c['area']),
                      'status':'unresearched','sources':{'ik':[],'tb':[],'tc':[]},'history':[]})
    assert len(items)==75 and len({x['id'] for x in items})==75
    return items

def new_state(master,day,previous=None):
    state={'version':1,'day':day,'master_sha256':master['source_sha256'],'items':create_queue(master),
           'data':create_data(master,day),'events':[], 'discovery':[],
           'areas':[{'no':a['no'],'name':a['name'],'stations':a['stations'],'discovery_status':'unresearched'} for a in master['areas']]}
    state['data']['metadata']['purpose']='research'
    if previous:
        for old_item in previous['items']:
            if old_item['kind']=='discovered':
                item=copy.deepcopy(old_item);item['status']='unresearched';state['items'].append(item)
        state['discovery']=copy.deepcopy(previous.get('discovery',[]))
        if 'seed_matcher_version' in previous:state['seed_matcher_version']=previous['seed_matcher_version']
        old={x['id']:x for x in previous['items']}
        for item in state['items']:
            if item['id'] in old:
                prior=old[item['id']];item['sources']=copy.deepcopy(prior['sources'])
                item['history']=copy.deepcopy(prior.get('history',[]))+[{'day':previous['day'],'status':prior['status'],'reason':prior.get('reason')}]
        state['previous_confirmed']={s['master_id']:s for a in previous['data']['areas'] for g in a['cats'].values() for s in g['shops'] if s['research']['status']=='confirmed'}
    return state

def load_state(directory,master,day):
    p=Path(directory)/'state.json'
    if not p.exists():return new_state(master,day)
    old=json.loads(p.read_text())
    if old.get('version')!=1 or old.get('master_sha256')!=master['source_sha256']:raise ValueError('state_schema_or_master_changed')
    expected={x['id'] for x in create_queue(master)};actual=[x['id'] for x in old['items']]
    if len(actual)!=len(set(actual)) or not expected<=set(actual):raise ValueError('incomplete_or_duplicate_queue')
    if old['day']>day:raise ValueError('cannot_resume_future_state')
    return old if old['day']==day else new_state(master,day,old)

def differences(state):
    current={s['master_id']:s for a in state['data']['areas'] for g in a['cats'].values() for s in g['shops'] if s['research']['status']=='confirmed'}
    previous=state.get('previous_confirmed',{})
    return [{'id':mid,'change':'new_current_confirmation' if mid not in previous else 'no_current_confirmation' if mid not in current else 'changed' if (previous[mid]['plans'],previous[mid]['links'])!=(current[mid]['plans'],current[mid]['links']) else 'unchanged'} for mid in sorted(set(previous)|set(current))]

def save_state(directory,state,master):
    if state['data']['generated']!=state['day'] or state['data']['period']['start']!=state['day']:raise ValueError('current_dataset_date_mismatch')
    unknown=[s['name'] for a in state['data']['areas'] for g in a['cats'].values() for s in g['shops'] if s['research']['status']!='confirmed']
    state['data']['notes']['status']='調査未完了。旧確認済みデータを今回確認に流用しない。未確認店舗：'+'／'.join(unknown)
    validate_data(state['data'],master)
    required={s['id'] for a in master['areas'] for g in a['cats'].values() for s in g['shops']}
    data_ids=[s.get('master_id') for a in state['data']['areas'] for g in a['cats'].values() for s in g['shops']]
    if set(data_ids)!=required or len(data_ids)!=len(required):raise ValueError('master_dataset_incomplete')
    if any(x['status'] not in STATUSES for x in state['items']):raise ValueError('invalid_queue_status')
    # Snapshot is saved first; a failed atomic state replacement preserves the previous state.
    atomic_json(Path(directory)/'runs'/state['day']/'snapshot.json',state)
    atomic_json(Path(directory)/'state.json',state)

def add_discovery(state,url,label,area,source,checked_at):
    from urllib.parse import urlsplit,urlunsplit
    from .read_only import check_url
    def canonical(u):
        check_url(u);parts=urlsplit(u)
        path=parts.path.rstrip('/')
        if parts.hostname in ('restaurant.ikyu.com','tabelog.com'):path+='/'
        host='tablecheck.com' if parts.hostname=='www.tablecheck.com' else parts.hostname
        return urlunsplit(('https',host,path,'',''))
    observed_url=url;key_url=canonical(url)
    all_urls={canonical(u) for x in state['items'] for values in x['sources'].values() for u in values}
    if key_url in all_urls:return False
    url=observed_url
    key='discovered-'+hashlib.sha256(key_url.encode()).hexdigest()[:16]
    if any(x['id']==key for x in state['items']):return False
    site='ik' if 'restaurant.ikyu.com/' in url else 'tb' if 'tabelog.com/' in url else 'tc'
    state['items'].append({'id':key,'kind':'discovered','name':label or url,'area':area,'status':'unresearched',
                           'sources':{k:([url] if k==site else []) for k in ('ik','tb','tc')},'history':[],
                           'discovered_from':{'url':source,'checked_at':checked_at},'identity_verified':False})
    return True

from contextlib import contextmanager
@contextmanager
def store_lock(directory):
    """Prevent overlapping local writers; kernel releases the lock on process exit."""
    import fcntl
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    with (directory/'.lock').open('a') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('another_research_process_holds_store_lock')
        try:yield
        finally:fcntl.flock(lock.fileno(),fcntl.LOCK_UN)
