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
        shops=[s for a in data['areas'] for g in a['cats'].values() for s in g['shops'] if s['research']['status']=='confirmed']
        receipts=run['receipts']
        if not shops or len(receipts)!=len(shops):return False
        for shop in shops:
            r=receipts[shop['master_id']]
            f=dt.datetime.fromisoformat(r['fetched_at']);v=dt.datetime.fromisoformat(r['verified_at'])
            if not f.tzinfo or not v.tzinfo or not start<=f<=v<=end:return False
            if r['run_id']!=run['id'] or r['restored_from_previous'] is not False or r['shop_sha256']!=digest(shop):return False
        return run['reservation_audit']['complete'] is True and run['reservation_audit']['violations']==[]
    except (KeyError,ValueError,TypeError):return False
