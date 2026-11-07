import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from afternoon_tea import routine_site as r

HTML=b'<!doctype html><html><head><title>AT</title><style>body{color:black}</style></head><body><p>Information unavailable</p></body></html>'
def files(n=0, failures=0):
    failure={'name':'Test only','area':'Test area','checked_at':'2026-11-07T07:17:00+09:00','sources':[],'reason':'Not retrieved','retry':True,'status':'unresearched'}
    return {'site/index.html':HTML,'site/research.json':r.json_bytes({'schema_version':1,'generated_at':None,'shops':[{'name':'Test only','price':None}]*n}), 'site/search_failures.json':r.json_bytes({'schema_version':1,'generated_at':None,'failures':[failure]*failures})}

class FakeAPI:
    def __init__(self):
        self.pr={'state':'open','draft':False,'title':'[weekly-site] mock','changed_files':1,'user':{'login':'tsubasa0518'},'base':{'ref':'main','repo':{'full_name':r.REPO}},'head':{'repo':{'full_name':r.REPO},'ref':'claude/test','sha':'a'*40},'merged':False}
        self.changed=[{'filename':'site/index.html','status':'modified'}]
        self.content=files(2,76);self.calls=[];self.denied=False
    def get(self,path):
        if '/files?' in path:return self.changed
        return copy.deepcopy(self.pr)
    def files(self,commit):return {p:{'mode':'100644','type':'blob','sha':p} for p in self.content}
    def blob(self,sha):return self.content[sha]
    def call(self,method,path,body):
        self.calls.append((method,path,body))
        if method=='PUT':
            if self.denied:raise HTTPError('https://api.github.com',405,'Protected',{},None)
            self.pr['merged']=True;self.pr['state']='closed';return {'merged':True}
        return None

class RoutineSiteTests(unittest.TestCase):
    def test_two_shops_and_76_unresolved_are_publishable(self):
        result=r.validate_site(files(2,76));self.assertEqual(result['shops'],2);self.assertEqual(result['search_failures'],76)
    def test_zero_shops_normal_explanation_is_valid(self):
        f=files();f['site/index.html']=HTML.replace(b'Information unavailable','今週は確認できた店舗情報がありません'.encode());r.validate_site(f)
    def test_unknown_prices_and_incomplete_coverage_do_not_block(self):r.validate_site(files(2))
    def test_empty_or_broken_html_rejected(self):
        for html in (b'',b'<html><body>oops',b'<html><head><title>x</title></head><body></div></html>'):
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
    def test_missing_assets_and_external_scripts_rejected(self):
        for insert in ('<img src="missing.png">','<script src="https://evil.example/x.js"></script>','<form></form>','<button onclick="x()">x</button>','<script>fetch("https://example.org")</script>'):
            with self.assertRaises(ValueError):r.validate_html_bytes(HTML.replace(b'</body>',insert.encode()+b'</body>'))
    def test_embedded_styles_and_filter_script_allowed(self):r.validate_html_bytes(HTML.replace(b'</body>',b'<script>document.querySelectorAll("p").forEach(p=>p.hidden=false);</script></body>'))
    def test_real_legacy_html_is_identical_and_valid(self):
        self.assertEqual((r.ROOT/'afternoon_tea_tokyo_2026-11-06.html').read_bytes(),(r.ROOT/'docs/index.html').read_bytes())
        r.validate_html_bytes((r.ROOT/'docs/index.html').read_bytes())
    def test_merge_then_explicit_dispatch_with_expected_sha(self):
        api=FakeAPI();r.intake(api,1,'tsubasa0518');self.assertEqual([x[0] for x in api.calls],['PUT','POST'])
        self.assertEqual(api.calls[0][2]['sha'],'a'*40);self.assertEqual(api.calls[1][1],'/actions/workflows/publish-site.yml/dispatches')
        self.assertEqual(api.calls[1][2],{'ref':'main'})
    def test_already_merged_rerun_dispatches_without_second_merge(self):
        api=FakeAPI();api.pr.update(merged=True,state='closed');r.intake(api,1,'tsubasa0518');self.assertEqual(len(api.calls),1);self.assertEqual(api.calls[0][0],'POST')
    def test_untrusted_author_fork_branch_title_and_base_rejected(self):
        for mutate in (lambda p:p['user'].update(login='intruder'),lambda p:p['head']['repo'].update(full_name='intruder/fork'),lambda p:p['head'].update(ref='other/test'),lambda p:p.update(title='other title'),lambda p:p['base'].update(ref='develop')):
            api=FakeAPI();mutate(api.pr)
            with self.assertRaises(ValueError):r.intake(api,1,'tsubasa0518')
            self.assertFalse(api.calls)
    def test_workflow_change_or_deleted_file_rejected(self):
        for f in ({'filename':'.github/workflows/publish-site.yml','status':'modified'},{'filename':'site/index.html','status':'removed'}):
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
    def test_prepare_preserves_previous_site_and_never_writes_docs(self):
        class Response(io.BytesIO):status=200
        class Opener:
            def open(self,*a,**k):return Response(HTML)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for path,value in files(2).items():
                (root/path).parent.mkdir(exist_ok=True);(root/path).write_bytes(value)
            with patch.object(r,'ROOT',root),patch.object(r.urllib.request,'build_opener',return_value=Opener()):report=r.prepare()
            self.assertEqual((root/'.staging/routine-delivery/previous/index.html').read_bytes(),HTML)
            self.assertEqual(report['sha256'],r.sha(HTML));self.assertFalse((root/'docs').exists())
    def test_workflow_is_trusted_and_single_publication_route(self):
        auto=(r.ROOT/'.github/workflows/auto-publish-weekly.yml').read_text();pub=(r.ROOT/'.github/workflows/publish-site.yml').read_text();old=(r.ROOT/'.github/workflows/deploy.yml').read_text()
        self.assertIn('pull_request_target:',auto);self.assertIn('ref: ${{ github.sha }}',auto);self.assertNotIn('pull_request.head.sha',auto)
        self.assertIn('actions: write',auto);self.assertNotIn('pages: write',auto)
        self.assertIn('group: github-pages',pub);self.assertIn('cancel-in-progress: false',pub);self.assertNotIn('publication_quality',pub)
        self.assertNotIn('deploy-pages@',old);self.assertNotIn('push:',old);self.assertIn("paths: ['site/**']",pub)
