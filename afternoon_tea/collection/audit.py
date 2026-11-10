"""Append-only, hash chained metadata journal; never stores headers/body/query values."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from afternoon_tea.processing.dates import JST
from afternoon_tea.common import digest


def identity(url):
    # Even rejected URLs must not leak credentials, queries or path/session values.
    from afternoon_tea.collection.transport import check_url
    try:
        check_url(url)
        p=urlsplit(url)
        return {'host':p.hostname,'path':p.path,'url_sha256':hashlib.sha256(url.encode()).hexdigest()}
    except (ValueError,RuntimeError):
        return {'host':None,'path':None,'url_sha256':hashlib.sha256(str(url).encode()).hexdigest()}


def kind(url):
    p=urlsplit(url).path
    return 'robots' if p=='/robots.txt' else 'listing' if p.startswith(('/t/','/area/','/s-tokyo/')) else 'plan' if '/plan' in p or '/party/' in p or p.endswith('/reserve') else 'store'


class CommunicationAudit:
    def __init__(self,run_id,path=None):
        self.run_id=run_id;self.path=Path(path) if path else None;self.events=[];self.pending=set();self.requests=0;self.failed=False;self.closed=False
        if self.path:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            # Never append onto another run's journal or silently overwrite it.
            with self.path.open('x',encoding='utf-8'):pass
        self.record('begin',scope='anonymous_ReadOnlyTransport_only')

    def record(self,event,**fields):
        if self.closed:raise RuntimeError('communication_audit_already_closed')
        row={'seq':len(self.events),'run_id':self.run_id,'at':dt.datetime.now(JST).isoformat(),'event':event,'previous':self.events[-1]['sha256'] if self.events else None,**fields}
        row['sha256']=digest(row)
        try:
            if self.path:
                with self.path.open('a',encoding='utf-8') as f:
                    f.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())
        except BaseException:
            self.failed=True;raise
        self.events.append(row);return row

    def begin(self,url,method):
        request_id=self.requests+1
        self.record('request',request_id=request_id,method=method,resource=identity(url),kind=kind(url))
        self.pending.add(request_id);self.requests+=1;return request_id

    def finish(self,request_id,status,http_status=None,reason=None):
        if request_id not in self.pending:self.failed=True;raise RuntimeError('untracked_http_result')
        self.record('response',request_id=request_id,status=status,http_status=http_status,reason=reason)
        self.pending.remove(request_id)

    def decision(self,url,reason,violation=False,method="GET"):
        self.record('decision',resource=identity(url),kind=kind(url),status='blocked' if violation else 'not_fetched',reason=reason,violation=violation,method=method)

    def snapshot(self,expected_requests=None):
        events=self.events;valid=not self.failed and not self.pending and (expected_requests is None or self.requests==expected_requests)
        try:
            if self.path:
                disk=[json.loads(x) for x in self.path.read_text().splitlines()]
                valid=valid and disk==events
            previous=None
            for i,row in enumerate(events):
                base={k:v for k,v in row.items() if k!='sha256'}
                valid=valid and row['seq']==i and row['run_id']==self.run_id and row['previous']==previous and row['sha256']==digest(base)
                previous=row['sha256']
        except (OSError,ValueError,KeyError,TypeError):valid=False
        violations=[e for e in events if e.get('violation') is True or e.get('status')=='forbidden']
        return {'complete':bool(valid),'violations':violations,'run_id':self.run_id,'requests':self.requests,'events':events,'chain_sha256':events[-1]['sha256'] if events else None,'scope':'anonymous_ReadOnlyTransport_only','operations_executed':0 if valid and not violations else None}
