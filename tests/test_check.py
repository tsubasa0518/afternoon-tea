import os
import datetime as dt
import copy
import io
import json
import tempfile
import unittest
import afternoon_tea.check as r
import afternoon_tea.render as renderer
import ast
import importlib
import pkgutil
import subprocess
import sys
import afternoon_tea
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from afternoon_tea.fetch import ROOT
from afternoon_tea.build import review
from afternoon_tea.__main__ import parser
from afternoon_tea.render import render

HTML = b'<!doctype html><html><head><title>AT</title><style>body{color:black}</style></head><body><p>Information unavailable</p></body></html>'

def files(n=0):
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    return {'site/index.html': HTML,
            'site/research.json': r.json_bytes({'schema_version':1, 'generated_at':stamp,
                'period':__import__('afternoon_tea.build',fromlist=['period']).period(),
                'shops':[{'name':'Test only '+str(i), 'area_no':1,
                          'plans':[{'plan_name':'AT', 'checked_at':stamp, 'price_yen':None}]} for i in range(n)]})}

class FakeAPI:

    def __init__(self):
        self.pr = {'state': 'open',
             'draft': False,
             'title': '[weekly-site] mock',
             'changed_files': 1,
             'user': {'login': 'tsubasa0518'},
             'base': {'ref': 'main',
             'repo': {'full_name': r.REPO}},
             'head': {'repo': {'full_name': r.REPO},
             'ref': 'claude/weekly-afternoon-tea-20261107',
             'sha': 'a' * 40},
             'merged': False}
        self.changed = [{'filename': r.RESEARCH, 'status': 'modified'}]
        self.content = files(2)
        self.calls = []
        self.denied = False

    def get(self, path):
        if '/files?' in path:
            return self.changed
        if path.startswith('/pulls/'):
            return copy.deepcopy(self.pr)
        raise AssertionError('unexpected API read: '+path)

    def files(self, commit):
        return {p: {'mode': '100644', 'type': 'blob', 'sha': p} for p in self.content}

    def blob(self, sha):
        return self.content[sha]

    def call(self, method, path, body):
        self.calls.append((method, path, body))
        if method == 'PUT':
            if self.denied:
                raise HTTPError('https://api.github.com', 405, 'Protected', {}, None)
            self.pr['merged'] = True
            self.pr['state'] = 'closed'
            self.pr['merge_commit_sha'] = 'c' * 40
            return {'merged': True, 'sha': 'c' * 40}
        return None

class RoutineSiteTests(unittest.TestCase):

    def test_two_shops_and_76_unresolved_are_publishable(self):
        result = r.validate_site(files(2))
        self.assertEqual(result['shops'], 2)

    def test_zero_shops_normal_explanation_is_valid(self):
        f = files()
        f['site/index.html'] = HTML.replace(b'Information unavailable', '今週確認できた情報はありません'.encode())
        r.validate_site(f)

    def test_unknown_prices_and_incomplete_coverage_do_not_block(self):
        r.validate_site(files(2))

    def test_empty_or_broken_html_rejected(self):
        for html in (b'',
             b'<html><body>oops',
             b'<html><head><title>x</title></head><body></div></html>',
             b'<html><head><title>x</title></head><body></body></html>',
             b'<html></html><head><title>x</title></head><body>x</body>'):
            with self.assertRaises(ValueError):
                r.validate_html_bytes(html)

    def test_missing_json_or_extra_file_rejected(self):
        for key in r.ALLOWED:
            f = files()
            del f[key]
            with self.assertRaises(ValueError):
                r.validate_site(f)
        f = files()
        f['.github/workflows/evil.yml'] = b'bad'
        with self.assertRaises(ValueError):
            r.validate_site(f)

    def test_invalid_json_rejected(self):
        f = files()
        f['site/research.json'] = b'{'
        with self.assertRaises(ValueError):
            r.validate_site(f)

    def test_credentials_and_personal_contact_rejected(self):
        for value in ('ghp_' + 'a' * 36, '-----BEGIN PRIVATE KEY-----', 'person@example.test', '090-1234-5678', '4111 1111 1111 1111'):
            with self.assertRaises(ValueError):
                r.scan(value.encode())

    def test_duplicate_resource_and_handler_attributes_rejected(self):
        for insert in ('<script src="https://example.invalid/payload.js" src=""></script>',
             '<img src="https://example.invalid/a.png" src="">',
             '<button onclick="bad()" onclick="">x</button>',
             '<script src=""></script>'):
            with self.assertRaises(ValueError):
                r.validate_html_bytes(HTML.replace(b'</body>', insert.encode() + b'</body>'))

    def test_missing_assets_and_external_scripts_rejected(self):
        for insert in ('<img src="missing.png">',
             '<script src="https://evil.example/x.js"></script>',
             '<form></form>',
             '<button onclick="x()">x</button>',
             '<script>fetch("https://example.org")</script>'):
            with self.assertRaises(ValueError):
                r.validate_html_bytes(HTML.replace(b'</body>', insert.encode() + b'</body>'))

    def test_embedded_styles_and_filter_script_allowed(self):
        r.validate_html_bytes(HTML.replace(b'</body>', b'<script>document.querySelectorAll("p").forEach(p=>p.hidden=false);</script></body>'))

    def test_current_site_html_is_valid(self):
        r.validate_html_bytes(renderer.render(json.loads((r.ROOT / r.RESEARCH).read_text())).encode())

    def test_merge_only_with_expected_sha_and_no_dispatch(self):
        api = FakeAPI()
        r.intake(api, 1, 'tsubasa0518')
        self.assertEqual([x[0] for x in api.calls], ['PUT'])
        self.assertEqual(api.calls[0][2]['sha'], 'a' * 40)
        self.assertEqual(api.calls[0][2]['merge_method'],'merge')

    def test_already_merged_event_skips_without_writing_or_republishing(self):
        api = FakeAPI()
        api.pr.update(merged=True, state='closed')
        report=r.intake(api, 1, 'tsubasa0518')
        self.assertEqual(report['merge'],'already_merged')
        self.assertNotIn('commit',report)
        self.assertFalse(api.calls)

    def test_untrusted_author_fork_branch_title_and_base_rejected(self):
        for mutate in (lambda p: p['user'].update(login='intruder'),
             lambda p: p['head']['repo'].update(full_name='intruder/fork'),
             lambda p: p['head'].update(ref='other/test'),
             lambda p: p.update(title='other title'),
             lambda p: p['base'].update(ref='develop')):
            api = FakeAPI()
            mutate(api.pr)
            with self.assertRaises(ValueError):
                r.intake(api, 1, 'tsubasa0518')
            self.assertFalse(api.calls)

    def test_workflow_change_or_deleted_file_rejected(self):
        for f in ({'filename': '.github/workflows/deploy.yml', 'status': 'modified'}, {'filename': 'site/index.html', 'status': 'removed'}):
            api = FakeAPI()
            api.changed = [f]
            with self.assertRaises(ValueError):
                r.intake(api, 1, 'tsubasa0518')
            self.assertFalse(api.calls)

    def test_symlink_pr_file_rejected(self):
        api = FakeAPI()
        tree = api.files('a')
        tree[r.RESEARCH]['mode'] = '120000'
        api.files = lambda c: tree
        with self.assertRaises(ValueError):
            r.intake(api, 1, 'tsubasa0518')

    def test_protection_failure_never_dispatches_or_force_pushes(self):
        api = FakeAPI()
        api.denied = True
        with self.assertRaises(HTTPError):
            r.intake(api, 1, 'tsubasa0518')
        self.assertEqual(len(api.calls), 1)
        self.assertTrue(all((x[0] == 'PUT' for x in api.calls)))

    def test_changed_head_never_merges(self):
        api = FakeAPI()
        original = api.get
        counter = []

        def get(path):
            p = original(path)
            if '/files?' not in path:
                counter.append(1)
                if len(counter) > 1:
                    p['head']['sha'] = 'b' * 40
            return p
        api.get = get
        with self.assertRaises(ValueError):
            r.intake(api, 1, 'tsubasa0518')
        self.assertFalse(api.calls)

    def test_public_url_exact_hash_and_mismatch(self):

        class Response(io.BytesIO):
            status = 200

        class Opener:

            def open(self, req, timeout):
                self.url = req.full_url
                return Response(HTML)
        op = Opener()
        r.verify_public(r.sha(HTML), 1, op)
        self.assertEqual(op.url, r.SITE)
        with self.assertRaises(ValueError):
            r.verify_public('0' * 64, 1, op)

    def test_prepare_is_offline_and_never_writes_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for (path, value) in files(2).items():
                (root / path).parent.mkdir(exist_ok=True)
                (root / path).write_bytes(value)
            with patch.object(r, 'ROOT', root), patch.object(r.urllib.request, 'build_opener') as network:
                report = r.prepare()
            network.assert_not_called()
            self.assertEqual((root / '.staging/routine-delivery/site/index.html').read_bytes(),renderer.render(json.loads(files(2)[r.RESEARCH])).encode())
            self.assertEqual(report['sha256'],r.sha((root/'.staging/routine-delivery/site/index.html').read_bytes()))
            self.assertFalse((root / 'docs').exists())

    def test_weekly_two_then_zero_shops_replace_same_staging_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for count in (2, 0):
                content = files(count)
                body = ''.join(('<article>Test-only shop ' + str(i) + '</article>' for i in range(count))) if count else '今週確認できた情報はありません'
                content['site/index.html'] = HTML.replace(b'<p>Information unavailable</p>', body.encode())
                for (path, value) in content.items():
                    (root / path).parent.mkdir(exist_ok=True)
                    (root / path).write_bytes(value)
                with patch.object(r, 'ROOT', root):
                    report = r.prepare()
                self.assertEqual(report['shops'], count)
                self.assertEqual((root / '.staging/routine-delivery/site/index.html').read_bytes(),renderer.render(json.loads(content[r.RESEARCH])).encode())
            self.assertIn('今週は確認できた情報がありません', (root / '.staging/routine-delivery/site/index.html').read_text())

    def test_old_claude_prefix_is_not_an_authorized_weekly_branch(self):
        api = FakeAPI()
        api.pr['head']['ref'] = 'claude/other-task'
        with self.assertRaisesRegex(ValueError, 'pr_not_a_trusted_routine'):
            r.intake(api, 1, 'tsubasa0518')
        self.assertFalse(api.calls)

    def test_weekly_retry_branch_is_valid(self):
        api = FakeAPI()
        api.pr['head']['ref'] = 'claude/weekly-afternoon-tea-20261107-retry'
        r.intake(api, 1, 'tsubasa0518')
        self.assertEqual(len(api.calls), 1)

    def test_escaped_json_credentials_rejected(self):
        value = b'{"schema_version":1,"shops":[],"note":"gh\\u0070_' + b'a' * 36 + b'"}'
        with self.assertRaises(ValueError):
            r.validate_json(value)

    def test_non_standard_json_numbers_rejected(self):
        for value in (b'NaN', b'Infinity', b'-Infinity'):
            with self.assertRaises(ValueError):
                r.validate_json(b'{"schema_version":1,"shops":[],"value":' + value + b'}')

    def test_invalid_json_prevents_generating_an_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = files()
            content[r.RESEARCH] = b'{'
            for (path, value) in content.items():
                (root / path).parent.mkdir(exist_ok=True)
                (root / path).write_bytes(value)
            with patch.object(r, 'ROOT', root), self.assertRaises(ValueError):
                r.prepare()
            self.assertFalse((root / '.staging/routine-delivery/site/index.html').exists())


class ProductionTests(unittest.TestCase):

    def assert_saved_site(self, data, html):
        self.assertFalse(review(data)['errors'])
        checked = r.validate_json(r.json_bytes(data))
        for shop in checked['shops']:
            self.assertIsInstance(shop['name'], str)
            self.assertIn(shop.get('category'), (None, 'unknown', 'cafe', 'hotel', 'lux'))

            if shop.get('list_url'):
                r.resource(shop['list_url'])
            for p in shop['plans']:
                self.assertIsInstance(p['plan_name'], str)
                self.assertTrue(p.get('price_yen') is None or type(p['price_yen']) in (int, float))
                self.assertIsNotNone(dt.datetime.fromisoformat(p['checked_at']).tzinfo)
                for key in ('sweets', 'season'):
                    self.assertTrue(p.get(key) is None or isinstance(p[key], (str, list)))
                for key in ('weekday_available', 'weekend_available'):
                    self.assertTrue(p.get(key) is None or type(p[key]) is bool)
        self.assertEqual(renderer.render(data), html)
        return r.validate_site({'site/research.json':r.json_bytes(data),'site/index.html':html.encode()})

    def test_dynamic_data_and_reproducible_html(self):
        data = json.loads((ROOT / 'site/research.json').read_text())
        self.assert_saved_site(data, renderer.render(data))

    def test_new_shop_needs_only_plan_timestamp_not_shop_id_or_shop_timestamp(self):
        from tests.test_render import fixture
        from afternoon_tea.fetch import candidates
        data = fixture()
        shop = data['shops'][0]
        shop.pop('checked_at', None)
        shop.pop('id', None)
        shop['list_url'] = candidates()[0]['予約ページURL']
        shop.pop('source_url', None)
        shop['plans'][0]['checked_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        self.assertEqual(self.assert_saved_site(data, renderer.render(data))['shops'], 1)

    def test_zero_shops_have_no_timestamp_maximum_and_are_valid(self):
        from tests.test_render import fixture
        data = fixture(); data['shops'] = []
        self.assertEqual(self.assert_saved_site(data, renderer.render(data))['shops'], 0)

    def test_multiple_plans_not_truncated(self):
        from tests.test_render import fixture
        d = fixture()
        s = d['shops'][0]
        s['plans'] = [copy.deepcopy(s['plans'][0]) for _ in range(3)]
        for (i, p) in enumerate(s['plans']):
            p['plan_name'] = 'TEST ONLY plan ' + str(i)
        d['shops'] = [s]
        h = renderer.render(d)
        for i in range(3):
            self.assertIn('TEST ONLY plan ' + str(i), h)

URL = 'https://restaurant.ikyu.com/107408/'



class StructureTests(unittest.TestCase):

    def test_all_modules_import_and_only_one_executable_entry(self):
        for entry in pkgutil.walk_packages(afternoon_tea.__path__, afternoon_tea.__name__ + '.'):
            importlib.import_module(entry.name)
        guards = []
        for path in (ROOT / 'afternoon_tea').rglob('*.py'):
            for node in ast.parse(path.read_text()).body:
                if isinstance(node, ast.If) and '__name__' in ast.unparse(node.test):
                    guards.append(path.name)
        self.assertEqual(guards, ['__main__.py'])

    def test_every_subcommand_help_is_offline_and_successful(self):
        choices = next((a.choices for a in parser()._actions if isinstance(a, __import__('argparse')._SubParsersAction)))
        for command in choices:
            result = subprocess.run([sys.executable, '-m', 'afternoon_tea', command, '--help'], cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, (command, result.stderr))
            self.assertIn(command, result.stdout)

    def test_render_does_not_change_saved_json_and_is_reproducible(self):
        path=ROOT/r.RESEARCH
        before=path.read_bytes()
        data=json.loads(before)
        self.assertEqual(render(data),render(copy.deepcopy(data)))
        self.assertEqual(path.read_bytes(),before)

    def test_workflows_parse_and_call_existing_commands_only(self):
        import re
        choices = next((a.choices for a in parser()._actions if isinstance(a, __import__('argparse')._SubParsersAction)))
        called = set()
        for path in sorted((ROOT / '.github/workflows').glob('*.yml')):
            text = path.read_text()
            self.assertNotIn('\t', text, path.name)
            try:
                import yaml
            except ImportError:
                # Offline CI without PyYAML: keys and lists must still be well formed.
                for line in text.splitlines():
                    if line.strip() and not line.lstrip().startswith('#'):
                        self.assertEqual((len(line) - len(line.lstrip())) % 2, 0, (path.name, line))
            else:
                self.assertIn('jobs', yaml.safe_load(text), path.name)
            called |= set(re.findall(r'python3 -m afternoon_tea ([a-z-]+)', text))
        self.assertTrue(called)
        self.assertLessEqual(called, set(choices))

    def test_browser_is_optional_and_old_research_machinery_is_gone(self):
        import sys
        from unittest.mock import patch
        with patch.dict(sys.modules, {'playwright': None, 'playwright.sync_api': None}):
            importlib.reload(importlib.import_module('afternoon_tea.browser'))
        names = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if '.git' not in p.parts}
        for gone in ('site/search_failures.json', 'data/official_sources.json', 'data/references/user_candidates_385.csv',
                     'afternoon_tea/collection/campaign.py', 'afternoon_tea/collection/official.py'):
            self.assertNotIn(gone, names)
        source = '\n'.join(p.read_text() for p in (ROOT / 'afternoon_tea').rglob('*.py'))
        for word in ('bing.com', 'research_campaign =', 'collect-official', 'validate-campaign'):
            self.assertNotIn(word, source)


class BPlanStructureTests(unittest.TestCase):
    def test_flat_package_templates_and_four_test_modules(self):
        self.assertEqual({p.stem for p in (ROOT/'afternoon_tea').glob('*.py')},
                         {'__init__','__main__','fetch','browser','build','render','check'})
        self.assertEqual({p.name for p in (ROOT/'afternoon_tea/templates').iterdir()},
                         {'site.html','site.css','site.js'})
        self.assertEqual({p.name for p in (ROOT/'tests').glob('test_*.py')},
                         {'test_safety.py','test_build.py','test_render.py','test_check.py'})
        for folder in ('collection','processing','publication'):
            self.assertFalse((ROOT/'afternoon_tea'/folder).exists())
        self.assertFalse((ROOT/'data/store_master.json').exists())

    def test_areas_contain_only_numbers_names_and_stations(self):
        areas=json.loads((ROOT/'data/areas.json').read_text())['areas']
        self.assertEqual([a['no'] for a in areas],list(range(1,15)))
        for area in areas:
            self.assertEqual(set(area),{'no','name','stations'})
            self.assertTrue(isinstance(area['name'],str) and area['name'])
            self.assertTrue(area['stations'])
            self.assertTrue(all(isinstance(s,str) and s for s in area['stations']))

    def test_validator_does_not_fill_missing_plan_date_from_shop(self):
        data=json.loads(files(1)['site/research.json'])
        shop=data['shops'][0]
        shop['checked_at']=shop['plans'][0].pop('checked_at')
        checked=r.validate_json(r.json_bytes(data))
        self.assertNotIn('checked_at',checked['shops'][0]['plans'][0])
        with self.assertRaisesRegex(ValueError,'plan_checked_at_required'):
            r.validate_site({'site/research.json':r.json_bytes(data),'site/index.html':HTML})


class RepeatPublicationTests(unittest.TestCase):
    def test_old_data_prepare_and_verify_commands_succeed_without_refresh_or_network(self):
        from tests.http_fixtures import Response
        from unittest.mock import Mock
        content=files(1)
        data=json.loads(content['site/research.json'])
        data.update(generated_at='2020-01-01T00:00:00+09:00',period={'start':'2020-01-01','end':'2020-02-10'})
        data['shops'][0]['plans'][0]['checked_at']='2019-12-31T12:00:00+09:00'
        content['site/research.json']=r.json_bytes(data)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for path,value in content.items():
                (root/path).parent.mkdir(parents=True,exist_ok=True)
                (root/path).write_bytes(value)
            opener=Mock()
            opener.open.side_effect=lambda *args,**kwargs:Response(r.SITE,renderer.render(data))
            with patch.object(r,'ROOT',root),patch('afternoon_tea.build.validate_freshness',side_effect=AssertionError('publication must not recheck age')), \
                 patch.object(r.urllib.request,'build_opener',return_value=opener), \
                 patch.dict(os.environ,{'GITHUB_STEP_SUMMARY':str(root/'summary.md')}), \
                 patch('sys.stdout',new=io.StringIO()):
                r.main('prepare')
                r.main('verify',r.sha(renderer.render(data).encode()))
            self.assertEqual(opener.open.call_count,1)
            self.assertEqual((root/'site/research.json').read_bytes(),content['site/research.json'])
            self.assertEqual((root/'.staging/routine-delivery/site/index.html').read_bytes(),renderer.render(data).encode())
            checks=json.loads((root/'.staging/routine-delivery/public-verification.json').read_text())
            self.assertEqual(checks,[{'status':200,'sha256':r.sha(renderer.render(data).encode())}])
            self.assertIn('Pages公開確認成功',(root/'summary.md').read_text())

    def test_age_exemption_does_not_accept_bad_timestamps_or_unsafe_output(self):
        for stamp in (None,'invalid','2020-01-01T00:00:00'):
            content=files(1)
            data=json.loads(content['site/research.json'])
            data['shops'][0]['plans'][0]['checked_at']=stamp
            content['site/research.json']=r.json_bytes(data)
            with self.assertRaises(ValueError):
                r.validate_site(content)
        for area in (15, 0, True, '1', None):
            content=files(1)
            data=json.loads(content['site/research.json'])
            data['shops'][0]['area_no']=area
            content['site/research.json']=r.json_bytes(data)
            with self.assertRaisesRegex(ValueError,'shop_area_outside_fourteen'):
                r.validate_site(content)
        for key,value in (('site/research.json',b'{'),
                          ('site/index.html',HTML.replace(b'</body>',b'<form></form></body>'))):
            content=files(1);content[key]=value
            with self.assertRaises(ValueError):
                r.validate_site(content)

    def test_unsanitized_secrets_still_rejected_at_publication_boundary(self):
        content=files(1)
        data=json.loads(content['site/research.json'])
        data['shops'][0]['plans'][0]['menu']='private@example.test'
        content['site/research.json']=r.json_bytes(data)
        with self.assertRaises(r.SensitiveDataError):
            r.validate_site(content)


class PublicationFlowTests(unittest.TestCase):
    def test_only_research_json_can_change_and_pr_code_is_never_read(self):
        for path in ('site/index.html','afternoon_tea/check.py','.github/workflows/publish.yml','data/areas.json'):
            api=FakeAPI();api.changed=[{'filename':path,'status':'modified'}]
            with self.assertRaisesRegex(ValueError,'routine_change_allowlist'):
                r.intake(api,1,'tsubasa0518')
            self.assertFalse(api.calls)
        api=FakeAPI();reads=[]
        api.content['afternoon_tea/check.py']=b'raise AssertionError("PR code must not run")'
        original=api.blob
        def blob(key):
            reads.append(key)
            return original(key)
        api.blob=blob
        report=r.intake(api,1,'tsubasa0518',expected_head='a'*40)
        self.assertEqual(reads,[r.RESEARCH])
        self.assertEqual(report['commit'],'c'*40)
        self.assertEqual([c[0] for c in api.calls],['PUT'])

    def test_invalid_json_or_preview_cannot_merge(self):
        for raw in (b'{',r.json_bytes({'schema_version':1,'shops':[]})):
            api=FakeAPI();api.content[r.RESEARCH]=raw
            with self.assertRaises(ValueError):
                r.intake(api,1,'tsubasa0518')
            self.assertFalse(api.calls)

    def test_event_head_and_final_metadata_must_still_match(self):
        api=FakeAPI()
        with self.assertRaisesRegex(ValueError,'pr_head_changed'):
            r.intake(api,1,'tsubasa0518',expected_head='b'*40)
        self.assertFalse(api.calls)
        for mutate in (lambda p:p.update(title='other'),lambda p:p['base'].update(ref='develop'),
                       lambda p:p['head'].update(ref='other'),lambda p:p.update(draft=True)):
            api=FakeAPI();original=api.get;calls=[]
            def get(path):
                value=original(path)
                if '/files?' not in path:
                    calls.append(path)
                    if len(calls)==2:mutate(value)
                return value
            api.get=get
            with self.assertRaises(ValueError):
                r.intake(api,1,'tsubasa0518')
            self.assertFalse(api.calls)

    def test_ci_receipts_hash_manifest_and_html_tracking_are_gone(self):
        self.assertFalse((ROOT/'data/protected_hashes.json').exists())
        for gone in ('technical_ci','resume','protected_files','dispatch_publication'):
            self.assertFalse(hasattr(r,gone),gone)
        tracked=subprocess.check_output(['git','ls-files','--','site/index.html'],cwd=ROOT,text=True)
        self.assertEqual(tracked,'')
        self.assertIn('/site/index.html',(ROOT/'.gitignore').read_text())
        self.assertEqual(set(parser()._subparsers._group_actions[0].choices),{'begin','fetch','build','report','check'})

    def test_main_intake_outputs_only_the_validated_merge_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);event=root/'event.json';output=root/'output'
            event.write_text(json.dumps({'number':1,'pull_request':{'head':{'sha':'a'*40}}}))
            with patch.object(r,'API',return_value=FakeAPI()), \
                 patch.dict(os.environ,{'GITHUB_EVENT_PATH':str(event),'GITHUB_OUTPUT':str(output),'ROUTINE_AUTHOR':'tsubasa0518'}), \
                 patch('sys.stdout',new=io.StringIO()):
                r.main('intake')
            self.assertEqual(output.read_text(),'commit='+'c'*40+'\n')
            with patch.dict(os.environ,{'GITHUB_OUTPUT':str(output)}),self.assertRaises(ValueError):
                r.outputs(commit='a'*40+'\nmalicious=true')
            self.assertEqual(output.read_text(),'commit='+'c'*40+'\n')

    def test_generation_uses_json_even_if_untracked_html_is_unsafe(self):
        content=files(1)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'site').mkdir()
            (root/r.RESEARCH).write_bytes(content[r.RESEARCH])
            (root/'site/index.html').write_text('<form>UNTRUSTED</form>')
            output=root/'outputs'
            with patch.object(r,'ROOT',root),patch.dict(os.environ,{'SOURCE_COMMIT':'d'*40,'GITHUB_OUTPUT':str(output)}):
                report=r.prepare()
            generated=(root/'.staging/routine-delivery/site/index.html').read_bytes()
            self.assertNotIn(b'UNTRUSTED',generated)
            self.assertEqual(generated,renderer.render(json.loads(content[r.RESEARCH])).encode())
            self.assertIn('source_commit='+'d'*40,output.read_text())
            self.assertIn('html_sha256='+report['sha256'],output.read_text())
            self.assertEqual((root/'site/index.html').read_text(),'<form>UNTRUSTED</form>')

    def test_workflow_trust_and_permission_boundaries(self):
        paths=ROOT/'.github/workflows'
        self.assertEqual({p.name for p in paths.iterdir()},{'test.yml','publish.yml'})
        text=(paths/'publish.yml').read_text()
        review=text.split('  review:\n',1)[1].split('\n  generate:',1)[0]
        generate=text.split('  generate:\n',1)[1].split('\n  deploy:',1)[0]
        deploy=text.split('  deploy:\n',1)[1]
        self.assertIn('ref: ${{ github.sha }}',review)
        self.assertIn('ref: main',generate)
        self.assertIn('ref: ${{ needs.generate.outputs.source_commit }}',deploy)
        for block in (review,generate,deploy):
            self.assertNotIn('pull_request.head.sha',block)
            self.assertNotIn('refs/pull/',block)
            self.assertNotIn('actions: write',block)
            self.assertNotIn('download-artifact',block)
        self.assertIn('contents: write',review)
        self.assertNotIn('pages: write',review+generate)
        self.assertNotIn('id-token: write',review+generate)
        self.assertIn('pages: write',deploy)
        self.assertIn('id-token: write',deploy)
        self.assertNotIn('GH_TOKEN:',generate+deploy)
        self.assertIn('needs: review',generate)
        self.assertIn("needs.review.outputs.commit != ''",generate)
        self.assertIn("github.ref == 'refs/heads/main'",generate)
        self.assertIn('needs: generate',deploy)
        self.assertIn("if: always() && needs.generate.result == 'success'",deploy)
        self.assertIn('workflow_dispatch:',text)
        self.assertNotIn('workflow_run:',text)
        self.assertNotIn('schedule:',text)
        self.assertIn("|| 'github-pages'",text)
        self.assertIn("format('weekly-rejected-{0}'",text)
        test=(paths/'test.yml').read_text()
        self.assertNotIn('contents: write',test)
        self.assertNotIn('GH_TOKEN:',test)
        self.assertIn("github.event_name != 'pull_request'",test)

    def test_json_only_review_generate_and_public_verification_flow(self):
        from unittest.mock import Mock
        from tests.http_fixtures import Response
        api=FakeAPI()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'site').mkdir()
            original=api.call
            def merge(method,path,body):
                result=original(method,path,body)
                (root/r.RESEARCH).write_bytes(api.content[r.RESEARCH])
                return result
            api.call=merge
            review=r.intake(api,1,'tsubasa0518',expected_head='a'*40)
            self.assertEqual(review['commit'],'c'*40)
            self.assertFalse((root/'site/index.html').exists())
            with patch.object(r,'ROOT',root),patch.dict(os.environ,{'SOURCE_COMMIT':review['commit']}):
                prepared=r.prepare()
                html=(root/'.staging/routine-delivery/site/index.html').read_bytes()
                opener=Mock();opener.open.side_effect=lambda *a,**k:Response(r.SITE,html.decode())
                observations=r.verify_public(prepared['sha256'],opener=opener)
            self.assertEqual(observations,[{'status':200,'sha256':prepared['sha256']}])
            self.assertEqual(prepared['shops'],2)
            self.assertEqual((root/r.RESEARCH).read_bytes(),api.content[r.RESEARCH])
            self.assertFalse((root/'site/index.html').exists())
            self.assertEqual([c[0] for c in api.calls],['PUT'])

    def test_prepare_does_not_write_through_staging_symlinks(self):
        for relative in ('site/index.html','report.json'):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);(root/'site').mkdir()
                (root/r.RESEARCH).write_bytes(files(1)[r.RESEARCH])
                base=root/'.staging/routine-delivery';(base/'site').mkdir(parents=True)
                protected=root/'protected.txt';protected.write_text('preserve')
                (base/relative).symlink_to(protected)
                with patch.object(r,'ROOT',root),self.assertRaises(ValueError):
                    r.prepare()
                self.assertEqual(protected.read_text(),'preserve')
