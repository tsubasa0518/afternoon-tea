"""Fail-closed publication evidence checks. No network and no publishing."""
import datetime as dt
import hashlib
import json

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def area_metrics(areas):
    valid=(len(areas)==14 and {a.get('no') for a in areas}==set(range(1,15)) and
           all(a.get('discovery_status') in ('complete','incomplete','unresearched','unresolved') for a in areas))
    return {'valid':valid,'started_rate':sum(a.get('discovery_status') in ('complete','incomplete') for a in areas)/14,
            'completion_rate':sum(a.get('discovery_status')=='complete' for a in areas)/14}

def current_evidence(data,audit):
    try:
        run=audit['current_run'];start=dt.datetime.fromisoformat(run['started_at']);end=dt.datetime.fromisoformat(run['generated_at'])
        if not start.tzinfo or not end.tzinfo or start>end:return False
        day=dt.date.fromisoformat(data['generated'])
        if start.date()!=day or end.date()!=day:return False
        if data.get('metadata',{}).get('run_id')!=run['id'] or data['metadata'].get('generated_at')!=run['generated_at']:return False
        if not valid_communication(run['reservation_audit'],run['id']):return False
        shops=[s for a in data['areas'] for g in a['cats'].values() for s in g['shops'] if s['research']['status']=='confirmed']
        receipts=run['receipts']
        if not shops or len(receipts)!=len(shops):return False
        seen_evidence=set();seen_requests=set()
        events=run['reservation_audit']['events']
        for shop in shops:
            r=receipts[shop['master_id']]
            f=dt.datetime.fromisoformat(r['fetched_at']);v=dt.datetime.fromisoformat(r['verified_at'])
            if not f.tzinfo or not v.tzinfo or not start<=f<=v<=end:return False
            if r['master_id']!=shop['master_id'] or r['run_id']!=run['id'] or r['restored_from_previous'] is not False or r['shop_sha256']!=digest(shop):return False
            source=shop['links'][0]['url']
            if r['source_url']!=source or r['matches']!={'identity':True,'menu':True,'booking':True}:return False
            key=r['evidence_sha256'];rid=r['http_request_id']
            if key in seen_evidence or rid in seen_requests:return False
            seen_evidence.add(key);seen_requests.add(rid)
            evidence=run['evidence'][key]
            from .master import dumps
            if digest(evidence)!=key or hashlib.sha256(dumps(evidence).encode()).hexdigest()!=r['evidence_file_sha256']:return False
            if r['evidence_ref']!='evidence/'+r['evidence_file_sha256']+'.json':return False
            result=evidence['extraction']
            if evidence['item_id']!=shop['master_id'] or evidence['url']!=source or result.get('master_id')!=shop['master_id'] or result.get('status')!='confirmed' or result.get('sha256')!=r['page_sha256']:return False
            url_hash=hashlib.sha256(source.encode()).hexdigest()
            if not any(e['event']=='request' and e.get('request_id')==rid and e.get('resource',{}).get('url_sha256')==url_hash for e in events):return False
            if not any(e['event']=='response' and e.get('request_id')==rid and e.get('status')=='http_success' for e in events):return False
            if not any(e['event']=='document' and e.get('request_id')==rid and e.get('resource',{}).get('url_sha256')==url_hash and e.get('page_sha256')==r['page_sha256'] and e['at']==r['fetched_at'] for e in events):return False
        return run['reservation_audit']['complete'] is True and run['reservation_audit']['violations']==[]
    except (KeyError,ValueError,TypeError):return False


def valid_communication(audit,run_id):
    """Replay the journal, rather than trusting a self-reported complete boolean."""
    try:
        if audit['complete'] is not True or audit['run_id']!=run_id or audit['violations']!=[]:return False
        events=audit['events'];requests={};responses={};previous=None
        if not events or events[0]['event']!='begin':return False
        for i,row in enumerate(events):
            if row['seq']!=i or row['run_id']!=run_id or row['previous']!=previous:return False
            if digest({k:v for k,v in row.items() if k!='sha256'})!=row['sha256']:return False
            previous=row['sha256']
            if row['event'] not in ('begin','request','response','document','decision'):return False
            if row.get('violation') or row.get('status')=='forbidden':return False
            if row['event']=='request':
                rid=row['request_id']
                if rid in requests or row['method']!='GET':return False
                requests[rid]=row
            if row['event']=='response':
                rid=row['request_id']
                if rid not in requests or rid in responses or row.get('status') not in ('http_success','http_failed'):return False
                responses[rid]=row
        return len(requests)==audit['requests'] and set(requests)==set(responses) and previous==audit['chain_sha256']
    except (KeyError,TypeError,ValueError):return False
