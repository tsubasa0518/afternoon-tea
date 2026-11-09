"""Minimal static-site intake. No research quality gates and no reservation traffic."""
import argparse
import base64
from collections import Counter
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
from urllib.parse import urlsplit
from .read_only import NoRedirect

ROOT=Path(__file__).resolve().parents[1]
REPO='tsubasa0518/afternoon-tea'
SITE='https://tsubasa0518.github.io/afternoon-tea/'
BRANCH_PREFIX='claude/weekly-afternoon-tea-'
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
    # Complete digest/UUID tokens are identifiers, not embedded card numbers.
    digest_fields='sha256|text_sha256|page_sha256|previous|chain_sha256|reference_sha256|document_id|audit_id|url_sha256'
    card_text=re.sub(r'"(?:'+digest_fields+r')"\s*:\s*"[a-f0-9]{64}"','"digest":"[digest]"',text)
    # Document IDs also occur as complete JSON string values in reference arrays.
    card_text=re.sub(r'"(?:url:)?[a-f0-9]{64}"','"[document digest]"',card_text)
    card_text=re.sub(r'"(?:campaign_id|run_id)"\s*:\s*"[a-f0-9]{32}"','"run":"[id]"',card_text)
    for raw in re.findall(r'(?<!\d)(?:\d[ -]?){13,19}(?!\d)',card_text):
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
    def __init__(self):super().__init__(convert_charrefs=True);self.stack=[];self.seen=set();self.resources=[];self.body_text=[]
    def handle_starttag(self,tag,attrs):
        require(len({k for k,v in attrs})==len(attrs),'duplicate_html_attribute')
        attrs=dict(attrs)
        if tag in ('html','head','body','title'):
            require(tag not in self.seen,'duplicate_document_element')
            parent={'html':None,'head':'html','body':'html','title':'head'}[tag]
            require((self.stack[-1] if self.stack else None)==parent,'invalid_document_structure')
            if tag=='body':require('head' in self.seen,'missing_document_head')
        else:require(bool(self.stack),'element_outside_html')
        self.seen.add(tag)
        require(tag not in ('form','iframe','object','embed','base'),'active_form_or_embedded_content_forbidden')
        require(not any(k.lower().startswith('on') for k in attrs),'inline_event_handler_forbidden')
        if tag=='script':require('src' not in attrs,'external_script_forbidden')
        for key in ('href','src','poster'):
            if attrs.get(key):resource(attrs[key],asset=tag!='a');self.resources.append(attrs[key])
        require('srcset' not in attrs,'embed_images_without_srcset')
        if tag=='meta' and attrs.get('http-equiv','').lower()=='refresh':raise ValueError('automatic_navigation_forbidden')
        if tag not in VOID:self.stack.append(tag)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in VOID:self.handle_endtag(tag)
    def handle_data(self,data):
        if 'body' in self.stack and not set(self.stack)&{'script','style'}:self.body_text.append(data)
    def handle_endtag(self,tag):
        if tag in VOID:return
        require(bool(self.stack) and self.stack[-1]==tag,'unbalanced_html_tags')
        self.stack.pop()

def validate_html_bytes(value):
    require(0<len(value)<=MAX_HTML,'html_missing_empty_or_too_large')
    text=scan(value);parser=StaticHTML();parser.feed(text);parser.close()
    require(not parser.stack and {'html','head','body','title'}<=parser.seen,'html_document_incomplete')
    require(''.join(parser.body_text).strip(),'blank_page_forbidden')
    for target in re.findall(r'url\(\s*[\"\x27]?([^\)\"\x27]+)',text,re.I):resource(target.strip(),asset=True)
    # Inline script is allowed for static filters, but must not drive network/forms.
    require(not re.search(r'\b(?:fetch|XMLHttpRequest|WebSocket|sendBeacon|eval)\b|document\.cookie|(?:local|session)Storage',text),'network_or_session_script_forbidden')
    return {'bytes':len(value),'sha256':sha(value),'resources':parser.resources,'technical_validation':'passed'}

def validate_json(value, failures=False):
    require(len(value)<=2_000_000,'json_too_large');scan(value);data=json.loads(value,parse_constant=lambda x:require(False,'non_finite_json_number'))
    scan(json_bytes(data))
    require(isinstance(data,dict) and data.get('schema_version')==1,'invalid_json_document')
    key='failures' if failures else 'shops'
    require(isinstance(data.get(key),list),'json_records_required')
    if data.get('generated_at') is not None:
        require(dt.datetime.fromisoformat(data['generated_at']).tzinfo is not None,'timestamp_timezone_required')
    if not failures:
        from .country_themes import validate_country
        for shop in data['shops']:
            for plan in shop.get('plans', []):validate_country(plan)
    if failures:
        statuses={'information_insufficient','access_denied','site_restriction','no_results','unresearched','confirmed','excluded'}
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
    # Metrics are informational; never compare them with publication thresholds.
    counts=dict(Counter(f['status'] for f in failures['failures']))
    plans=sum(len(s.get('plans',[])) for s in research['shops']
              if isinstance(s,dict) and isinstance(s.get('plans',[]),list))
    unresearched_shops=sum(f['status']=='unresearched' and f.get('scope','shop')=='shop'
                          for f in failures['failures'])
    return {**report,'generated_at':research.get('generated_at'),'shops':len(research['shops']),
            'plans':plans,'search_failures':len(failures['failures']),
            'unresearched_shops':unresearched_shops,'search_statuses':counts}


def write_summary(stage,report):
    """Use existing Actions step summaries; do not add monitoring or merge conditions."""
    target=os.environ.get('GITHUB_STEP_SUMMARY')
    if not target:return
    rows=[('処理結果',stage)]
    if report:
        rows += [('調査データ生成日時',report.get('generated_at') or '未記録'),
                 ('掲載店舗数',report.get('shops',0)),('登録プラン数',report.get('plans',0)),
                 ('未調査店舗数',report.get('unresearched_shops',0))]
        labels={'unresearched':'未調査','information_insufficient':'情報不足',
                'access_denied':'アクセス拒否','site_restriction':'サイト側制限',
                'no_results':'検索結果なし','confirmed':'確認記録','excluded':'現在の根拠で対象外'}
        rows += [(label+'（レコード）',report.get('search_statuses',{}).get(key,0))
                 for key,label in labels.items()]
    def cell(value):return str(value).replace('|','\\|').replace('\n',' ').replace('\r',' ')
    lines=['\n### 週次サイト更新','','| 項目 | 結果 |','| --- | --- |']
    lines += ['| '+cell(k)+' | '+cell(v)+' |' for k,v in rows]
    lines.append('')
    if report.get('pr'):lines.append('PR: https://github.com/'+REPO+'/pull/'+str(int(report['pr'])))
    run=os.environ.get('GITHUB_RUN_ID')
    if run and run.isdigit():lines.append('実行: https://github.com/'+REPO+'/actions/runs/'+run)
    lines.append('公開URL: '+SITE)
    with open(target,'a',encoding='utf-8') as f:f.write('\n'.join(lines)+'\n')


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
def dispatch_publication(api, number, head_sha, merge_sha):
    """Serialized intake jobs deduplicate by a durable bot receipt and run SHA.

    A failed dispatch leaves no success receipt and can be retried. If dispatch
    succeeded but saving its receipt failed, the Actions run is the recovery proof.
    """
    marker='<!-- weekly-site-dispatch:'+head_sha+' -->'
    for page in range(1, 11):
        comments=api.get('/issues/'+number+'/comments?per_page=100&page='+str(page))
        require(isinstance(comments,list),'invalid_dispatch_receipts')
        if any(c.get('user',{}).get('login')=='github-actions[bot]' and c.get('body','').startswith(marker+'\n') for c in comments):
            return 'already_requested'
        if len(comments)<100:break
    else:raise ValueError('dispatch_receipt_pagination_limit')
    if merge_sha:
        runs=api.get('/actions/workflows/deploy.yml/runs?head_sha='+merge_sha+'&event=workflow_dispatch&per_page=100')
        require(isinstance(runs,dict) and isinstance(runs.get('workflow_runs'),list),'invalid_publication_history')
        if any(r.get('head_sha')==merge_sha and r.get('event')=='workflow_dispatch' for r in runs['workflow_runs']):
            return 'already_requested'
    api.call('POST','/actions/workflows/deploy.yml/dispatches',{'ref':'main'})
    api.call('POST','/issues/'+number+'/comments',{'body':marker+'\n検証済みheadのPages公開を要求しました。head: '+head_sha+' / merge: '+str(merge_sha)})
    return 'requested'


def technical_ci(api, head):
    runs=api.get('/actions/workflows/test-data.yml/runs?event=pull_request&head_sha='+head+'&per_page=100')['workflow_runs']
    runs=[r for r in runs if r.get('head_sha')==head and r.get('event')=='pull_request']
    if not runs:return 'pending'
    latest=max(runs,key=lambda r:(r['id'],r.get('run_attempt',1)))
    if latest.get('status')!='completed':return 'pending'
    return 'success' if latest.get('conclusion')=='success' else 'failed'


def intake(api,number,author,sleep=time.sleep):
    number=str(int(number));pr=api.get('/pulls/'+number)
    require(not pr['draft'] and pr['base']['ref']=='main' and pr['base']['repo']['full_name']==REPO and pr['head']['repo'] and pr['head']['repo']['full_name']==REPO and pr['head']['ref'].startswith(BRANCH_PREFIX) and pr['user']['login']==author and pr['title'].startswith('[weekly-site]'),'pr_not_a_trusted_routine')
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
    from .campaign_gate import publication_gate
    publication_gate(json.loads(files['site/research.json']),json.loads(files['site/search_failures.json']))
    # The API checks the expected head atomically; never bypass branch protection.
    for attempt in range(10):
        latest=api.get('/pulls/'+number)
        require(latest['head']['sha']==pr['head']['sha'],'pr_head_changed')
        if latest.get('merged') is True:
            merge_sha=latest.get('merge_commit_sha');break
        require(latest['state']=='open','pr_no_longer_open')
        ci=technical_ci(api,pr['head']['sha'])
        if ci!='success':
            return {**report,'pr':number,'merge':'ci_'+ci,'head_sha':pr['head']['sha']}
        require(latest.get('mergeable') is not False,'pr_merge_conflict')
        try:
            merged=api.call('PUT','/pulls/'+number+'/merge',{'sha':pr['head']['sha'],'merge_method':'squash'})
            require(merged.get('merged') is True,'merge_not_completed');merge_sha=merged.get('sha');break
        except HTTPError as e:
            if e.code!=405 or attempt==9:raise
            sleep(15)  # GitHub merge readiness/protection; CI was independently checked.
    # Explicit dispatch is supported even when GITHUB_TOKEN performed the merge.
    dispatch=dispatch_publication(api,number,pr['head']['sha'],merge_sha)
    return {**report,'pr':number,'dispatch':dispatch}


def prepare():
    base=ROOT/'.staging/routine-delivery';base.mkdir(parents=True,exist_ok=True)
    require(not base.is_symlink() and base.resolve().is_relative_to(ROOT.resolve()/'.staging'),'unsafe_delivery_directory')
    files={p:(ROOT/p).read_bytes() for p in ALLOWED}
    require(all(not (ROOT/p).is_symlink() for p in ALLOWED),'site_symlink_forbidden')
    report=validate_site(files)
    from .campaign_gate import publication_gate, retained_snapshot
    if retained_snapshot(files['site/research.json'],files['site/search_failures.json']):
        report['publication_basis']='retained_published_snapshot_2026-11-09'
    else:
        publication_gate(json.loads(files['site/research.json']),json.loads(files['site/search_failures.json']))
        report['publication_basis']='completed_research_campaign'
    (base/'site').mkdir(exist_ok=True)
    require(not (base/'site').is_symlink(),'unsafe_delivery_directory')
    (base/'site/index.html').write_bytes(files['site/index.html'])
    report.update(source_commit=os.environ.get('SOURCE_COMMIT'),workflow_run_id=os.environ.get('GITHUB_RUN_ID'),url=SITE)
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
    p=argparse.ArgumentParser();p.add_argument('command',choices=('validate','intake','prepare','verify'));a=p.parse_args()
    try:
        if a.command=='validate':print(validate_site({p:(ROOT/p).read_bytes() for p in ALLOWED}))
        elif a.command=='intake':
            event=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
            report=intake(API(),event['number'],os.environ.get('ROUTINE_AUTHOR') or REPO.split('/')[0])
            print(report);write_summary(report.get('merge','自動マージ成功・公開開始要求済み（公開結果はdeploy.ymlを確認）'),report)
            if report.get('merge')=='ci_failed':raise ValueError('latest_head_technical_ci_failed')
        elif a.command=='prepare':
            report=prepare();print(report);write_summary('HTML公開準備成功（デプロイ前）',report)
        else:
            base=ROOT/'.staging/routine-delivery';report=json.loads((base/'report.json').read_text())
            path=base/'site/index.html';expected=report['sha256']
            require(sha(path.read_bytes())==expected,'delivery_bytes_changed')
            observations=verify_public(expected)
            (base/'public-verification.json').write_bytes(json_bytes(observations))
            print({'public_verification':'passed','http':observations})
            write_summary('Pages公開確認成功（HTTP 200・HTML SHA-256一致）',report)
    except Exception:
        write_summary(a.command+'失敗。実行ログのエラーを確認してください。',{})
        raise
if __name__=='__main__':main()
