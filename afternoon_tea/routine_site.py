"""Minimal static-site intake. No research quality gates and no reservation traffic."""
import argparse
import base64
import datetime as dt
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import time
import urllib.request
from urllib.error import HTTPError
from urllib.parse import urlsplit,unquote
from .read_only import NoRedirect

ROOT=Path(__file__).resolve().parents[1]
REPO='tsubasa0518/afternoon-tea'
SITE='https://tsubasa0518.github.io/afternoon-tea/'
ALLOWED={'site/index.html','site/research.json','site/search_failures.json'}
MAX_HTML=5_000_000
VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}

def require(ok,reason):
    if not ok:raise ValueError(reason)
def sha(value):return hashlib.sha256(value).hexdigest()
def json_bytes(value):return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
def scan(value):
    text=value.decode('utf-8')
    patterns=(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',r'\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-(?:ant-|proj-)[A-Za-z0-9_-]{12,}|AKIA[A-Z0-9]{16})',r'(?i)authorization\s*[:=]\s*[\"\x27]?bearer\s+\S+',r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',r'\b0[5789]0[- ]\d{4}[- ]\d{4}\b')
    require(not any(re.search(p,text) for p in patterns),'secret_or_personal_contact_detected')
    # Card-like values are checked without printing matched sensitive text.
    for raw in re.findall(r'(?<!\d)(?:\d[ -]?){13,19}(?!\d)',text):
        digits=re.sub(r'\D','',raw)
        if len(digits)<13:continue
        nums=[int(c) for c in digits[::-1]];total=sum((n*2-9 if n*2>9 else n*2) if i%2 else n for i,n in enumerate(nums))
        require(total%10!=0,'possible_payment_card_detected')
    return text

def resource(url,asset=False):
    if url.startswith('#'):return
    if asset and url.startswith(('data:image/png;base64,','data:image/jpeg;base64,','data:image/gif;base64,','data:image/webp;base64,')):return
    p=urlsplit(url)
    require(p.scheme=='https' and p.hostname and p.username is None and p.password is None,'unsafe_or_missing_resource')
    require(not any(c.isspace() for c in url) and '\\' not in url,'invalid_resource_url')
    require(not re.search(r'(?i)(?:[?&])(?:token|session(?:id)?|auth|password|booking_id)=',url),'session_in_resource')
    if asset:require(p.hostname in ('fonts.googleapis.com','fonts.gstatic.com'),'use_embedded_assets_or_google_fonts')

class StaticHTML(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.stack=[];self.seen=set();self.resources=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs);self.seen.add(tag)
        require(tag not in ('form','iframe','object','embed','base'),'active_form_or_embedded_content_forbidden')
        require(not any(k.lower().startswith('on') for k in attrs),'inline_event_handler_forbidden')
        if tag=='script':require(not attrs.get('src'),'external_script_forbidden')
        for key in ('href','src','poster'):
            if attrs.get(key):resource(attrs[key],asset=tag!='a');self.resources.append(attrs[key])
        require('srcset' not in attrs,'embed_images_without_srcset')
        if tag=='meta' and attrs.get('http-equiv','').lower()=='refresh':raise ValueError('automatic_navigation_forbidden')
        if tag not in VOID:self.stack.append(tag)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in VOID:self.handle_endtag(tag)
    def handle_endtag(self,tag):
        if tag in VOID:return
        require(bool(self.stack) and self.stack[-1]==tag,'unbalanced_html_tags')
        self.stack.pop()

def validate_html_bytes(value):
    require(0<len(value)<=MAX_HTML,'html_missing_empty_or_too_large')
    text=scan(value);parser=StaticHTML();parser.feed(text);parser.close()
    require(not parser.stack and {'html','head','body','title'}<=parser.seen,'html_document_incomplete')
    for target in re.findall(r'url\(\s*[\"\x27]?([^\)\"\x27]+)',text,re.I):resource(target.strip(),asset=True)
    # Inline script is allowed for static filters, but must not drive network/forms.
    require(not re.search(r'\b(?:fetch|XMLHttpRequest|WebSocket|sendBeacon|eval)\b|document\.cookie|(?:local|session)Storage',text),'network_or_session_script_forbidden')
    return {'bytes':len(value),'sha256':sha(value),'resources':parser.resources,'technical_validation':'passed'}

def validate_json(value, failures=False):
    require(len(value)<=2_000_000,'json_too_large');scan(value);data=json.loads(value)
    require(isinstance(data,dict) and data.get('schema_version')==1,'invalid_json_document')
    key='failures' if failures else 'shops'
    require(isinstance(data.get(key),list),'json_records_required')
    if data.get('generated_at') is not None:
        require(dt.datetime.fromisoformat(data['generated_at']).tzinfo is not None,'timestamp_timezone_required')
    if failures:
        statuses={'information_insufficient','access_denied','site_restriction','no_results','unresearched','confirmed'}
        for f in data['failures']:
            require(isinstance(f,dict) and {'name','area','checked_at','sources','reason','retry','status'}<=set(f),'failure_fields_missing')
            require(all(isinstance(f[k],str) and f[k].strip() for k in ('name','area','checked_at','reason')) and len(f['reason'])<=2000 and type(f['retry']) is bool,'invalid_failure_record')
            require(f['status'] in statuses,'invalid_search_status')
            require(dt.datetime.fromisoformat(f['checked_at']).tzinfo is not None,'timestamp_timezone_required')
            require(isinstance(f['sources'],list),'failure_sources_required')
            for u in f['sources']:resource(u)
    return data


def validate_site(files):
    require(set(files)==ALLOWED,'site_requires_exactly_three_files')
    report=validate_html_bytes(files['site/index.html'])
    research=validate_json(files['site/research.json'])
    failures=validate_json(files['site/search_failures.json'],True)
    # No counts, coverage, price completeness or old publication scores gate delivery.
    return {**report,'shops':len(research['shops']),'search_failures':len(failures['failures'])}

class API:
    def call(self,method,path,body=None):
        require(method in ('GET','POST','PUT') and path.startswith('/') and '..' not in path,'invalid_github_api_request')
        headers={'Accept':'application/vnd.github+json','User-Agent':'RoutineSiteDelivery'}
        token=os.environ.get('GH_TOKEN')
        if token:headers['Authorization']='Bearer '+token
        payload=json_bytes(body) if body is not None else None
        if payload:headers['Content-Type']='application/json'
        req=urllib.request.Request('https://api.github.com/repos/'+REPO+path,data=payload,headers=headers,method=method)
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=30) as r:
            raw=r.read();return json.loads(raw) if raw else None
    def get(self,path):return self.call('GET',path)
    def blob(self,blob_sha):
        require(bool(re.fullmatch('[0-9a-f]{40}',blob_sha)),'invalid_blob_sha')
        obj=self.get('/git/blobs/'+blob_sha);require(obj['encoding']=='base64' and obj['size']<=MAX_HTML,'blob_too_large')
        return base64.b64decode(''.join(obj['content'].split()),validate=True)
    def files(self,commit):
        require(bool(re.fullmatch('[0-9a-f]{40}',commit)),'invalid_commit_sha')
        tree=self.get('/git/trees/'+commit+'?recursive=1');require(not tree.get('truncated'),'truncated_tree')
        return {x['path']:x for x in tree['tree']}
    def read(self,commit,path):
        f=self.files(commit)[path];require(f['mode']=='100644' and f['type']=='blob','non_regular_file');return self.blob(f['sha'])
def intake(api,number,author,sleep=time.sleep):
    number=str(int(number));pr=api.get('/pulls/'+number)
    require(not pr['draft'] and pr['base']['ref']=='main' and pr['base']['repo']['full_name']==REPO and pr['head']['repo'] and pr['head']['repo']['full_name']==REPO and pr['head']['ref'].startswith('claude/') and pr['user']['login']==author and pr['title'].startswith('[weekly-site]'),'pr_not_a_trusted_routine')
    require(pr['state']=='open' or pr.get('merged') is True,'pr_closed_without_merge')
    require(1<=pr['changed_files']<=3,'routine_change_allowlist')
    changed=api.get('/pulls/'+number+'/files?per_page=100')
    require(len(changed)==pr['changed_files'] and len({f['filename'] for f in changed})==len(changed) and all(f['filename'] in ALLOWED and f['status'] in ('added','modified') for f in changed),'routine_change_allowlist')
    tree=api.files(pr['head']['sha']);files={}
    for path in ALLOWED:
        entry=tree.get(path,{})
        require(entry.get('mode')=='100644' and entry.get('type')=='blob','unsafe_pr_file')
        files[path]=api.blob(entry['sha'])
    report=validate_site(files)
    # The API checks the expected head atomically; never bypass branch protection.
    for attempt in range(10):
        latest=api.get('/pulls/'+number)
        require(latest['head']['sha']==pr['head']['sha'],'pr_head_changed')
        if latest.get('merged') is True:break
        require(latest['state']=='open','pr_no_longer_open')
        try:
            merged=api.call('PUT','/pulls/'+number+'/merge',{'sha':pr['head']['sha'],'merge_method':'squash'})
            require(merged.get('merged') is True,'merge_not_completed');break
        except HTTPError as e:
            if e.code!=405 or attempt==9:raise
            sleep(15)  # Required CI may still be running; no protection changes.
    # Explicit dispatch is supported even when GITHUB_TOKEN performed the merge.
    api.call('POST','/actions/workflows/publish-site.yml/dispatches',{'ref':'main'})
    return {**report,'pr':number,'dispatch':'requested'}


def prepare():
    base=ROOT/'.staging/routine-delivery';base.mkdir(parents=True,exist_ok=True)
    require(not base.is_symlink() and base.resolve().is_relative_to((ROOT/'.staging').resolve()),'unsafe_delivery_directory')
    files={p:(ROOT/p).read_bytes() for p in ALLOWED}
    require(all(not (ROOT/p).is_symlink() for p in ALLOWED),'site_symlink_forbidden')
    report=validate_site(files)
    # Snapshot the actually served page before changing it, for immediate rollback.
    with urllib.request.build_opener(NoRedirect()).open(urllib.request.Request(SITE,headers={'Cache-Control':'no-cache'}),timeout=30) as r:
        require(r.status==200,'cannot_snapshot_previous_site');previous=r.read(MAX_HTML+1)
    validate_html_bytes(previous)
    for directory,content in [('site',files['site/index.html']),('previous',previous)]:
        (base/directory).mkdir(exist_ok=True);(base/directory/'index.html').write_bytes(content)
    report.update(previous_html_sha256=sha(previous),source_commit=os.environ.get('SOURCE_COMMIT'),workflow_run_id=os.environ.get('GITHUB_RUN_ID'),url=SITE)
    (base/'report.json').write_bytes(json_bytes(report));return report


def verify_public(expected,attempts=6,opener=None,sleep=time.sleep):
    opener=opener or urllib.request.build_opener(NoRedirect());observations=[]
    for i in range(attempts):
        try:
            with opener.open(urllib.request.Request(SITE,headers={'Cache-Control':'no-cache'}),timeout=15) as r:
                raw=r.read(MAX_HTML+1);observations.append({'status':r.status,'sha256':sha(raw)})
                if r.status==200 and sha(raw)==expected:validate_html_bytes(raw);return observations
        except Exception as e:observations.append({'error':type(e).__name__})
        if i+1<attempts:sleep(10)
    raise ValueError('public_verification_failed:'+json.dumps(observations))


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=('validate','intake','prepare','verify','verify-rollback'));a=p.parse_args()
    if a.command=='validate':print(validate_site({p:(ROOT/p).read_bytes() for p in ALLOWED}))
    elif a.command=='intake':
        event=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text());print(intake(API(),event['number'],os.environ.get('ROUTINE_AUTHOR') or REPO.split('/')[0]))
    elif a.command=='prepare':print(prepare())
    else:
        base=ROOT/'.staging/routine-delivery';report=json.loads((base/'report.json').read_text())
        rollback=a.command=='verify-rollback';path=base/('previous' if rollback else 'site')/'index.html'
        expected=report['previous_html_sha256' if rollback else 'sha256']
        require(sha(path.read_bytes())==expected,'delivery_bytes_changed')
        observations=verify_public(expected)
        (base/('rollback.json' if rollback else 'public-verification.json')).write_bytes(json_bytes(observations))
if __name__=='__main__':main()
