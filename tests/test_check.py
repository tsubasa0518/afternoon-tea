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
                'period':{'start':'2026-11-09','end':'2026-12-19'},
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
        self.changed = [{'filename': 'site/index.html', 'status': 'modified'}]
        self.content = files(2)
        self.calls = []
        self.denied = False
        self.comments = []
        self.runs = []

    def get(self, path):
        if '/comments?' in path:
            return copy.deepcopy(self.comments)
        if '/test-data.yml/runs?' in path:
            return {'workflow_runs': [{'id': 1, 'head_sha': self.pr['head']['sha'], 'event': 'pull_request', 'status': 'completed', 'conclusion': 'success'}]}
        if '/runs?' in path:
            return {'workflow_runs': copy.deepcopy(self.runs)}
        if '/files?' in path:
            return self.changed
        return copy.deepcopy(self.pr)

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
        if path.endswith('/comments'):
            self.comments.append({'user': {'login': 'github-actions[bot]'}, 'body': body['body']})
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
        r.validate_html_bytes((r.ROOT / 'site/index.html').read_bytes())

    def test_merge_then_explicit_dispatch_with_expected_sha(self):
        api = FakeAPI()
        r.intake(api, 1, 'tsubasa0518')
        self.assertEqual([x[0] for x in api.calls], ['PUT', 'POST', 'POST'])
        self.assertEqual(api.calls[0][2]['sha'], 'a' * 40)
        self.assertEqual(api.calls[1][1], '/actions/workflows/deploy.yml/dispatches')
        self.assertEqual(api.calls[1][2], {'ref': 'main'})

    def test_already_merged_retry_dispatches_only_if_not_previously_requested(self):
        api = FakeAPI()
        api.pr.update(merged=True, state='closed')
        r.intake(api, 1, 'tsubasa0518')
        self.assertEqual(len(api.calls), 2)
        self.assertTrue(all((c[0] == 'POST' for c in api.calls)))

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
        tree['site/index.html']['mode'] = '120000'
        api.files = lambda c: tree
        with self.assertRaises(ValueError):
            r.intake(api, 1, 'tsubasa0518')

    def test_protection_failure_never_dispatches_or_force_pushes(self):
        api = FakeAPI()
        api.denied = True
        with self.assertRaises(HTTPError):
            r.intake(api, 1, 'tsubasa0518', sleep=lambda s: None)
        self.assertEqual(len(api.calls), 10)
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
            self.assertEqual((root / '.staging/routine-delivery/site/index.html').read_bytes(), HTML)
            self.assertEqual(report['sha256'], r.sha(HTML))
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
                self.assertEqual((root / '.staging/routine-delivery/site/index.html').read_bytes(), content['site/index.html'])
            self.assertIn('今週確認できた情報はありません', (root / '.staging/routine-delivery/site/index.html').read_text())

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
        self.assertEqual(len(api.calls), 3)

    def test_escaped_json_credentials_rejected(self):
        value = b'{"schema_version":1,"shops":[],"note":"gh\\u0070_' + b'a' * 36 + b'"}'
        with self.assertRaises(ValueError):
            r.validate_json(value)

    def test_non_standard_json_numbers_rejected(self):
        for value in (b'NaN', b'Infinity', b'-Infinity'):
            with self.assertRaises(ValueError):
                r.validate_json(b'{"schema_version":1,"shops":[],"value":' + value + b'}')

    def test_invalid_html_prevents_preparing_an_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = files()
            content['site/index.html'] = b''
            for (path, value) in content.items():
                (root / path).parent.mkdir(exist_ok=True)
                (root / path).write_bytes(value)
            with patch.object(r, 'ROOT', root), self.assertRaises(ValueError):
                r.prepare()
            self.assertFalse((root / '.staging/routine-delivery/site/index.html').exists())

    def test_workflow_is_trusted_and_single_publication_route(self):
        auto = (r.ROOT / '.github/workflows/auto-merge-weekly.yml').read_text()
        pub = (r.ROOT / '.github/workflows/deploy.yml').read_text()
        self.assertIn('pull_request_target:', auto)
        self.assertIn('ref: ${{ github.sha }}', auto)
        self.assertNotIn('pull_request.head.sha', auto)
        self.assertIn('actions: write', auto)
        self.assertNotIn('pages: write', auto)
        self.assertIn("if: github.ref == 'refs/heads/main'", pub)
        self.assertIn('group: github-pages', pub)
        self.assertIn('cancel-in-progress: false', pub)
        self.assertNotIn('publication_quality', pub)
        self.assertFalse((r.ROOT / '.github/workflows/publish-site.yml').exists())
        self.assertFalse((r.ROOT / '.github/workflows/auto-publish-weekly.yml').exists())
        self.assertIn("paths: ['site/**']", pub)
        self.assertIn("head.ref, 'claude/weekly-afternoon-tea-'", auto)
        self.assertNotIn('rollback', pub)


class TechnicalCITests(unittest.TestCase):

    def check(self, runs, expected):
        api = FakeAPI()
        original = api.get
        api.get = lambda p: {'workflow_runs': runs} if '/test-data.yml/runs?' in p else original(p)
        result = r.intake(api, 1, 'tsubasa0518', sleep=lambda _: None)
        self.assertEqual(result.get('merge'), expected)
        self.assertFalse(any((c[0] == 'PUT' for c in api.calls)))

    def test_missing(self):
        self.check([], 'ci_pending')

    def test_running(self):
        self.check([{'id': 1, 'head_sha': 'a' * 40, 'event': 'pull_request', 'status': 'in_progress'}], 'ci_pending')

    def test_failure(self):
        self.check([{'id': 1, 'head_sha': 'a' * 40, 'event': 'pull_request', 'status': 'completed', 'conclusion': 'failure'}], 'ci_failed')

    def test_old_sha(self):
        self.check([{'id': 1, 'head_sha': 'b' * 40, 'event': 'pull_request', 'status': 'completed', 'conclusion': 'success'}], 'ci_pending')

    def test_rerun_failure_wins(self):
        self.check([{'id': 1,
             'run_attempt': a,
             'head_sha': 'a' * 40,
             'event': 'pull_request',
             'status': 'completed',
             'conclusion': c} for (a,
             c) in [(1,
             'success'),
             (2,
             'failure')]],
             'ci_failed')

    def test_resume_ignores_non_pr(self):
        from afternoon_tea.check import resume
        self.assertEqual(resume(None, {'workflow_run': {'event': 'push'}}, 'x'), [])

class ProductionTests(unittest.TestCase):

    def assert_saved_site(self, data, html):
        self.assertFalse(review(data)['errors'])
        # Legacy saved data is readable during PR 1; modern shops need no id or timestamp.
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
        stamps = [dt.datetime.fromisoformat(p['checked_at']) for s in checked['shops'] for p in s['plans']]
        now = max(stamps) + dt.timedelta(days=1) if stamps else dt.datetime.now(dt.timezone.utc)
        from afternoon_tea.build import validate_freshness
        with patch('afternoon_tea.build.validate_freshness', side_effect=lambda value: validate_freshness(value, now)):
            return r.validate_site({'site/research.json': r.json_bytes(data), 'site/index.html': html.encode()})

    def test_dynamic_data_and_reproducible_html(self):
        data = json.loads((ROOT / 'site/research.json').read_text())
        self.assert_saved_site(data, (ROOT / 'site/index.html').read_text())

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

class CatalogProtectionTests(unittest.TestCase):


    def test_manifest_tamper_is_rejected(self):
        import afternoon_tea.check as guards
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'data').mkdir()
            (root / 'protected.txt').write_text('changed')
            (root / 'data/protected_hashes.json').write_text(json.dumps({'protected.txt': '0' * 64}))
            with patch.object(guards, 'ROOT', root), self.assertRaises(ValueError):
                guards.protected_files()


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

    def test_render_does_not_change_any_site_input_and_matches_current_html(self):
        paths = [ROOT / 'site' / name for name in ('research.json', 'index.html')]
        before = [p.read_bytes() for p in paths]
        result = render(json.loads(before[0])).encode()
        self.assertEqual(result, before[1])
        self.assertEqual([p.read_bytes() for p in paths], before)

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
        r.protected_files()

    def test_validator_does_not_fill_missing_plan_date_from_shop(self):
        data=json.loads(files(1)['site/research.json'])
        shop=data['shops'][0]
        shop['checked_at']=shop['plans'][0].pop('checked_at')
        checked=r.validate_json(r.json_bytes(data))
        self.assertNotIn('checked_at',checked['shops'][0]['plans'][0])
        with self.assertRaisesRegex(ValueError,'missing_checked_at'):
            r.validate_site({'site/research.json':r.json_bytes(data),'site/index.html':HTML})
