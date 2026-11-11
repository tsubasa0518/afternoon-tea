"""Stable fixtures and changing production data; no live reservation requests."""
import copy, json, unittest, datetime as dt
from unittest.mock import patch
from afternoon_tea.publication import site as r
from afternoon_tea.publication import renderer as renderer
from afternoon_tea.collection.catalog import ROOT
from afternoon_tea.processing.period_review import review
from tests.test_site_intake import FakeAPI

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
        from afternoon_tea.publication.ci import resume
        self.assertEqual(resume(None, {'workflow_run': {'event': 'push'}}, 'x'), [])

class ProductionTests(unittest.TestCase):

    def assert_saved_site(self, data, html):
        self.assertFalse(review(data)['errors'])
        # Legacy saved data is readable during PR 1; modern shops need no id or timestamp.
        checked = r.validate_json(r.json_bytes(data))
        for shop in checked['shops']:
            self.assertIsInstance(shop['name'], str)
            self.assertIn(shop.get('category'), (None, 'unknown', 'cafe', 'hotel', 'lux'))
            r.resource(shop.get('list_url') or shop.get('source_url'))
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
        from afternoon_tea.processing.weekly import validate_freshness
        with patch('afternoon_tea.processing.weekly.validate_freshness', side_effect=lambda value: validate_freshness(value, now)):
            return r.validate_site({'site/research.json': r.json_bytes(data), 'site/index.html': html.encode()})

    def test_dynamic_data_and_reproducible_html(self):
        data = json.loads((ROOT / 'site/research.json').read_text())
        self.assert_saved_site(data, (ROOT / 'site/index.html').read_text())

    def test_new_shop_needs_only_plan_timestamp_not_shop_id_or_shop_timestamp(self):
        from tests.test_renderer import fixture
        from afternoon_tea.collection.weekly import candidates
        data = fixture()
        shop = data['shops'][0]
        shop.pop('checked_at', None)
        shop.pop('id', None)
        shop['list_url'] = candidates()[0]['予約ページURL']
        shop.pop('source_url', None)
        shop['plans'][0]['checked_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        self.assertEqual(self.assert_saved_site(data, renderer.render(data))['shops'], 1)

    def test_zero_shops_have_no_timestamp_maximum_and_are_valid(self):
        from tests.test_renderer import fixture
        data = fixture(); data['shops'] = []
        self.assertEqual(self.assert_saved_site(data, renderer.render(data))['shops'], 0)

    def test_multiple_plans_not_truncated(self):
        d = json.loads((ROOT / 'tests/fixtures/enrichment_cases.json').read_text())
        s = d['shops'][0]
        s['plans'] = [copy.deepcopy(s['plans'][0]) for _ in range(3)]
        for (i, p) in enumerate(s['plans']):
            p['plan_name'] = 'TEST ONLY plan ' + str(i)
        d['shops'] = [s]
        h = renderer.render(d)
        for i in range(3):
            self.assertIn('TEST ONLY plan ' + str(i), h)

class CollectionDetailsTests(unittest.TestCase):

    def test_historical_category_cannot_classify_unknown_price(self):
        from afternoon_tea.processing.enrichment import enrich
        d = {'period': {'start': '2026-11-07',
             'end': '2026-12-17'},
             'shops': [{'id': 'unknown',
             'name': 'TEST cafe',
             'source_url': 'https://restaurant.ikyu.com/123456/plan111111',
             'plans': []}]}
        reference = '<article data-cat="cafe"><h4>TEST cafe</h4><a href="https://restaurant.ikyu.com/123456/plan222222">old</a></article>'
        master = {'areas': []}
        out = enrich(d, master, reference)
        # No regular price: unknown, whatever the old reference page said.
        self.assertEqual(out['shops'][0]['category'], 'unknown')
        self.assertEqual(out['shops'][0]['plans'], [])
        reference = reference.replace('data-cat="cafe"', 'data-cat="lux"')
        self.assertEqual(enrich(d, master, reference)['shops'][0]['category'], 'unknown')

class InferredYearTests(unittest.TestCase):

    def test_inferred_year_is_not_confirmed_period(self):
        from afternoon_tea.processing.enrichment import enrich_plan
        p = {'plan_name': 'AT 11/1～11/30', 'start': '2026-11-01', 'end': '2026-11-30', 'note': '提供期間: 2026-11-01〜2026-11-30（タイトル/期間表記より。年は調査年と推定）'}
        out = enrich_plan(p, {})
        self.assertIsNone(out['start'])
        self.assertIsNone(out['end'])
        p['evidence_quote'] = '2026年11月1日～11月30日提供'
        self.assertEqual(enrich_plan(p, {})['start'], '2026-11-01')
