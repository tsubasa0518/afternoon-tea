import datetime as dt
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from afternoon_tea import routine_site as r
from test_list_research import completed_campaign

HTML=b'<!doctype html><html><head><title>AT</title><style>body{color:black}</style></head><body><p>Information unavailable</p></body></html>'
def files(n=0, failures=0):
    failure={'name':'Test only','area':'Test area','checked_at':'2026-11-07T07:17:00+09:00','sources':[],'reason':'Not retrieved','retry':True,'status':'unresearched'}
    return {'site/index.html':HTML,'site/research.json':r.json_bytes({'schema_version':1,'generated_at':None,'period':{'start':'2026-11-09','end':'2026-12-19'},'shops':[{'name':'Test only','price':None}]*n}), 'site/search_failures.json':r.json_bytes({'schema_version':1,'generated_at':None,'research_campaign':completed_campaign(),'failures':[failure]*failures})}

class FakeAPI:
    def __init__(self):
        self.pr={'state':'open','draft':False,'title':'[weekly-site] mock','changed_files':1,'user':{'login':'tsubasa0518'},'base':{'ref':'main','repo':{'full_name':r.REPO}},'head':{'repo':{'full_name':r.REPO},'ref':'claude/weekly-afternoon-tea-20261107','sha':'a'*40},'merged':False}
        self.changed=[{'filename':'site/index.html','status':'modified'}]
        self.content=files(2,76);self.calls=[];self.denied=False;self.comments=[];self.runs=[]
    def get(self,path):
        if '/comments?' in path:return copy.deepcopy(self.comments)
        if '/test-data.yml/runs?' in path:return {'workflow_runs':[{'id':1,'head_sha':self.pr['head']['sha'],'event':'pull_request','status':'completed','conclusion':'success'}]}
        if '/runs?' in path:return {'workflow_runs':copy.deepcopy(self.runs)}
        if '/files?' in path:return self.changed
        return copy.deepcopy(self.pr)
    def files(self,commit):return {p:{'mode':'100644','type':'blob','sha':p} for p in self.content}
    def blob(self,sha):return self.content[sha]
    def call(self,method,path,body):
        self.calls.append((method,path,body))
        if method=='PUT':
            if self.denied:raise HTTPError('https://api.github.com',405,'Protected',{},None)
            self.pr['merged']=True;self.pr['state']='closed';self.pr['merge_commit_sha']='c'*40;return {'merged':True,'sha':'c'*40}
        if path.endswith('/comments'):self.comments.append({'user':{'login':'github-actions[bot]'},'body':body['body']})
        return None

class RoutineSiteTests(unittest.TestCase):
    def setUp(self):
        patcher=patch('afternoon_tea.campaign_gate.current_day',return_value=dt.date(2026,11,9))
        patcher.start();self.addCleanup(patcher.stop)

    def test_two_shops_and_76_unresolved_are_publishable(self):
        result=r.validate_site(files(2,76));self.assertEqual(result['shops'],2);self.assertEqual(result['search_failures'],76)
    def test_zero_shops_normal_explanation_is_valid(self):
        f=files();f['site/index.html']=HTML.replace(b'Information unavailable','今週確認できた情報はありません'.encode());r.validate_site(f)
    def test_unknown_prices_and_incomplete_coverage_do_not_block(self):r.validate_site(files(2))
    def test_empty_or_broken_html_rejected(self):
        for html in (b'',b'<html><body>oops',b'<html><head><title>x</title></head><body></div></html>', b'<html><head><title>x</title></head><body></body></html>', b'<html></html><head><title>x</title></head><body>x</body>'):
            with self.assertRaises(ValueError):r.validate_html_bytes(html)
    def test_missing_json_or_extra_file_rejected(self):
        for key in r.ALLOWED:
            f=files();del f[key]
            with self.assertRaises(ValueError):r.validate_site(f)
        f=files();f['.github/workflows/evil.yml']=b'bad'
        with self.assertRaises(ValueError):r.validate_site(f)
    def test_invalid_json_rejected(self):
        f=files();f['site/research.json']=b'{'
        with self.assertRaises(ValueError):r.validate_site(f)
    def test_credentials_and_personal_contact_rejected(self):
        for value in ('ghp_'+'a'*36,'-----BEGIN PRIVATE KEY-----','person@example.test','090-1234-5678','4111 1111 1111 1111'):
            with self.assertRaises(ValueError):r.scan(value.encode())
    def test_duplicate_resource_and_handler_attributes_rejected(self):
        for insert in ('<script src="https://example.invalid/payload.js" src=""></script>', '<img src="https://example.invalid/a.png" src="">', '<button onclick="bad()" onclick="">x</button>', '<script src=""></script>'):
            with self.assertRaises(ValueError):r.validate_html_bytes(HTML.replace(b'</body>',insert.encode()+b'</body>'))
    def test_missing_assets_and_external_scripts_rejected(self):
        for insert in ('<img src="missing.png">','<script src="https://evil.example/x.js"></script>','<form></form>','<button onclick="x()">x</button>','<script>fetch("https://example.org")</script>'):
            with self.assertRaises(ValueError):r.validate_html_bytes(HTML.replace(b'</body>',insert.encode()+b'</body>'))
    def test_embedded_styles_and_filter_script_allowed(self):r.validate_html_bytes(HTML.replace(b'</body>',b'<script>document.querySelectorAll("p").forEach(p=>p.hidden=false);</script></body>'))
    def test_current_site_html_is_valid(self):
        r.validate_html_bytes((r.ROOT/'site/index.html').read_bytes())
    def test_merge_then_explicit_dispatch_with_expected_sha(self):
        api=FakeAPI();r.intake(api,1,'tsubasa0518');self.assertEqual([x[0] for x in api.calls],['PUT','POST','POST'])
        self.assertEqual(api.calls[0][2]['sha'],'a'*40);self.assertEqual(api.calls[1][1],'/actions/workflows/deploy.yml/dispatches')
        self.assertEqual(api.calls[1][2],{'ref':'main'})
    def test_already_merged_retry_dispatches_only_if_not_previously_requested(self):
        api=FakeAPI();api.pr.update(merged=True,state='closed');r.intake(api,1,'tsubasa0518');self.assertEqual(len(api.calls),2);self.assertTrue(all(c[0]=='POST' for c in api.calls))
    def test_untrusted_author_fork_branch_title_and_base_rejected(self):
        for mutate in (lambda p:p['user'].update(login='intruder'),lambda p:p['head']['repo'].update(full_name='intruder/fork'),lambda p:p['head'].update(ref='other/test'),lambda p:p.update(title='other title'),lambda p:p['base'].update(ref='develop')):
            api=FakeAPI();mutate(api.pr)
            with self.assertRaises(ValueError):r.intake(api,1,'tsubasa0518')
            self.assertFalse(api.calls)
    def test_workflow_change_or_deleted_file_rejected(self):
        for f in ({'filename':'.github/workflows/deploy.yml','status':'modified'},{'filename':'site/index.html','status':'removed'}):
            api=FakeAPI();api.changed=[f]
            with self.assertRaises(ValueError):r.intake(api,1,'tsubasa0518')
            self.assertFalse(api.calls)
    def test_symlink_pr_file_rejected(self):
        api=FakeAPI();tree=api.files('a');tree['site/index.html']['mode']='120000';api.files=lambda c:tree
        with self.assertRaises(ValueError):r.intake(api,1,'tsubasa0518')
    def test_protection_failure_never_dispatches_or_force_pushes(self):
        api=FakeAPI();api.denied=True
        with self.assertRaises(HTTPError):r.intake(api,1,'tsubasa0518',sleep=lambda s:None)
        self.assertEqual(len(api.calls),10);self.assertTrue(all(x[0]=='PUT' for x in api.calls))
    def test_changed_head_never_merges(self):
        api=FakeAPI();original=api.get;counter=[]
        def get(path):
            p=original(path)
            if '/files?' not in path:
                counter.append(1)
                if len(counter)>1:p['head']['sha']='b'*40
            return p
        api.get=get
        with self.assertRaises(ValueError):r.intake(api,1,'tsubasa0518')
        self.assertFalse(api.calls)
    def test_public_url_exact_hash_and_mismatch(self):
        class Response(io.BytesIO):status=200
        class Opener:
            def open(self,req,timeout):
                self.url=req.full_url;return Response(HTML)
        op=Opener();r.verify_public(r.sha(HTML),1,op);self.assertEqual(op.url,r.SITE)
        with self.assertRaises(ValueError):r.verify_public('0'*64,1,op)
    def test_prepare_is_offline_and_never_writes_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for path,value in files(2).items():
                (root/path).parent.mkdir(exist_ok=True);(root/path).write_bytes(value)
            with patch.object(r,'ROOT',root),patch.object(r.urllib.request,'build_opener') as network:report=r.prepare()
            network.assert_not_called()
            self.assertEqual((root/'.staging/routine-delivery/site/index.html').read_bytes(),HTML)
            self.assertEqual(report['sha256'],r.sha(HTML));self.assertFalse((root/'docs').exists())
    def test_weekly_two_then_zero_shops_replace_same_staging_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for count in (2,0):
                content=files(count,76)
                body=''.join('<article>Test-only shop '+str(i)+'</article>' for i in range(count)) if count else '今週確認できた情報はありません'
                content['site/index.html']=HTML.replace(b'<p>Information unavailable</p>',body.encode())
                for path,value in content.items():
                    (root/path).parent.mkdir(exist_ok=True);(root/path).write_bytes(value)
                with patch.object(r,'ROOT',root):report=r.prepare()
                self.assertEqual(report['shops'],count);self.assertEqual(report['search_failures'],76)
                self.assertEqual((root/'.staging/routine-delivery/site/index.html').read_bytes(),content['site/index.html'])
            self.assertIn('今週確認できた情報はありません',(root/'.staging/routine-delivery/site/index.html').read_text())
    def test_old_claude_prefix_is_not_an_authorized_weekly_branch(self):
        api=FakeAPI();api.pr['head']['ref']='claude/other-task'
        with self.assertRaisesRegex(ValueError,'pr_not_a_trusted_routine'):r.intake(api,1,'tsubasa0518')
        self.assertFalse(api.calls)
    def test_weekly_retry_branch_is_valid(self):
        api=FakeAPI();api.pr['head']['ref']='claude/weekly-afternoon-tea-20261107-retry'
        r.intake(api,1,'tsubasa0518');self.assertEqual(len(api.calls),3)
    def test_escaped_json_credentials_rejected(self):
        value=b'{"schema_version":1,"shops":[],"note":"gh\\u0070_'+b'a'*36+b'"}'
        with self.assertRaises(ValueError):r.validate_json(value)
    def test_non_standard_json_numbers_rejected(self):
        for value in (b'NaN',b'Infinity',b'-Infinity'):
            with self.assertRaises(ValueError):r.validate_json(b'{"schema_version":1,"shops":[],"value":'+value+b'}')
    def test_invalid_html_prevents_preparing_an_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);content=files();content['site/index.html']=b''
            for path,value in content.items():
                (root/path).parent.mkdir(exist_ok=True);(root/path).write_bytes(value)
            with patch.object(r,'ROOT',root),self.assertRaises(ValueError):r.prepare()
            self.assertFalse((root/'.staging/routine-delivery/site/index.html').exists())
    def test_workflow_is_trusted_and_single_publication_route(self):
        auto=(r.ROOT/'.github/workflows/auto-merge-weekly.yml').read_text();pub=(r.ROOT/'.github/workflows/deploy.yml').read_text()
        self.assertIn('pull_request_target:',auto);self.assertIn('ref: ${{ github.sha }}',auto);self.assertNotIn('pull_request.head.sha',auto)
        self.assertIn('actions: write',auto);self.assertNotIn('pages: write',auto)
        self.assertIn("if: github.ref == 'refs/heads/main'",pub);self.assertIn('group: github-pages',pub);self.assertIn('cancel-in-progress: false',pub);self.assertNotIn('publication_quality',pub)
        self.assertFalse((r.ROOT/'.github/workflows/publish-site.yml').exists());self.assertFalse((r.ROOT/'.github/workflows/auto-publish-weekly.yml').exists());self.assertIn("paths: ['site/**']",pub)
        self.assertIn("head.ref, 'claude/weekly-afternoon-tea-'",auto);self.assertNotIn('rollback',pub)
