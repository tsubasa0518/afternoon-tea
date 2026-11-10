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

    def test_dynamic_data_and_reproducible_html(self):
        d = json.loads((ROOT / 'site/research.json').read_text())
        self.assertFalse(review(d)['errors'])
        ids = []
        for shop in d['shops']:
            self.assertIsInstance(shop['name'], str)
            ids.append(shop['id'])
            self.assertIn(shop.get('category'), (None, 'unknown', 'cafe', 'hotel', 'lux'))
            r.resource(shop['source_url'])
            self.assertTrue(shop['checked_at'])
            for p in shop['plans']:
                self.assertIsInstance(p['plan_name'], str)
                self.assertTrue(p.get('price_yen') is None or type(p['price_yen']) in (int, float))
                for key in ('sweets', 'season'):
                    self.assertTrue(p.get(key) is None or isinstance(p[key], (str, list)))
                for key in ('weekday_available', 'weekend_available'):
                    self.assertTrue(p.get(key) is None or type(p[key]) is bool)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(renderer.render(d), (ROOT / 'site/index.html').read_text())
        saved = max(dt.datetime.fromisoformat(p.get('checked_at', s['checked_at'])) for s in d['shops'] for p in s['plans'])
        from afternoon_tea.processing.weekly import validate_freshness
        with patch('afternoon_tea.processing.weekly.validate_freshness', side_effect=lambda data: validate_freshness(data, saved + dt.timedelta(days=1))):
            r.validate_site({p: (ROOT / p).read_bytes() for p in r.ALLOWED})

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
        # Not stated as a hotel: cafe, whatever the old reference page said.
        self.assertEqual(out['shops'][0]['category'], 'cafe')
        self.assertEqual(out['shops'][0]['plans'], [])
        reference = reference.replace('data-cat="cafe"', 'data-cat="lux"')
        self.assertEqual(enrich(d, master, reference)['shops'][0]['category'], 'cafe')

class InferredYearTests(unittest.TestCase):

    def test_inferred_year_is_not_confirmed_period(self):
        from afternoon_tea.processing.enrichment import enrich_plan
        p = {'plan_name': 'AT 11/1～11/30', 'start': '2026-11-01', 'end': '2026-11-30', 'note': '提供期間: 2026-11-01〜2026-11-30（タイトル/期間表記より。年は調査年と推定）'}
        out = enrich_plan(p, {})
        self.assertIsNone(out['start'])
        self.assertIsNone(out['end'])
        p['evidence_quote'] = '2026年11月1日～11月30日提供'
        self.assertEqual(enrich_plan(p, {})['start'], '2026-11-01')
