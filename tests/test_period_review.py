"""Offline date, reporting and filter regressions; no reservation requests."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from afternoon_tea.processing.dates import period
from afternoon_tea.publication import site as site_tools
from afternoon_tea.processing.period_review import review
from tests.test_site_intake import files

def data(first=None, last=None):
    return {'generated_at': '2026-11-07T15:55:22+09:00',
         'period': {'start': '2026-11-07',
         'end': '2026-12-17'},
         'shops': [{'plans': [{'start': first,
         'end': last}]}]}

class WeeklyReviewTests(unittest.TestCase):

    def test_december_19_start_is_outside_december_17_window(self):
        result = review(data('2026-12-19', '2026-12-25'))
        self.assertEqual(len(result['outside_plans']), 1)
        self.assertEqual(result['errors'][0]['reason'], 'outside_research_period')

    def test_inclusive_boundary_overlap(self):
        for (first, last) in [('2026-12-17', '2026-12-25'), ('2026-10-01', '2026-11-07'), ('2026-11-07', '2026-12-17')]:
            self.assertEqual(review(data(first, last))['errors'], [])

    def test_expired_plan_is_outside(self):
        self.assertTrue(review(data('2026-10-01', '2026-11-06'))['outside_plans'])

    def test_unknown_dates_remain_unknown_without_mutation(self):
        for (first, last) in [(None, None), (None, '2026-12-20'), ('2026-12-01', None)]:
            source = data(first, last)
            before = copy.deepcopy(source)
            result = review(source)
            self.assertEqual(result['errors'], [])
            self.assertEqual(result['unknown_periods'], 1)
            self.assertEqual(source, before)

    def test_known_endpoint_can_prove_outside(self):
        for (first, last) in [('2026-12-19', None), (None, '2026-11-06')]:
            self.assertTrue(review(data(first, last))['outside_plans'])

    def test_invalid_dates_and_inversion_are_not_silently_corrected(self):
        for (first, last) in [('2026-02-30', None), ('2026-12-10', '2026-12-01'), ('20261201', None)]:
            self.assertEqual(review(data(first, last))['errors'][0]['reason'], 'invalid_plan_period')

    def test_wrong_40_day_window_rejected(self):
        source = data()
        source['period']['end'] = '2026-12-19'
        self.assertEqual(review(source)['errors'][0]['reason'], 'invalid_research_period')

    def test_jst_midnight_and_year_leap_boundaries(self):
        self.assertEqual(period(now=dt.datetime(2026, 11, 6, 16, tzinfo=dt.timezone.utc)), {'start': '2026-11-07', 'end': '2026-12-17'})
        self.assertEqual(period('2026-12-20')['end'], '2027-01-29')
        self.assertEqual(period('2028-02-01')['end'], '2028-03-12')

    def test_generated_timestamp_compared_in_jst(self):
        source = data()
        source['generated_at'] = '2026-11-06T16:00:00+00:00'
        self.assertEqual(review(source)['errors'], [])
        source['generated_at'] = '2026-11-06T14:59:00+00:00'
        self.assertTrue(review(source)['errors'])

    def test_no_shops_or_plans_is_not_a_review_failure(self):
        source = data()
        source['shops'] = []
        self.assertEqual(review(source)['errors'], [])

    def test_outside_period_plan_is_not_rendered(self):
        from afternoon_tea.publication.renderer import render
        from tests.test_renderer import fixture
        sample = fixture()
        sample['shops'][0]['plans'][0].update(start='2026-12-19', end=None, plan_name='OUTSIDE ONLY')
        self.assertTrue(review(sample)['outside_plans'])
        self.assertNotIn('OUTSIDE ONLY', render(sample))

    def test_date_review_is_not_a_new_automatic_publication_gate(self):
        # The pre-PR helper reports an error; the existing automation is unchanged.
        content = files(0)
        sample = {'schema_version': 1, **data('2026-12-19', None)}
        sample['shops'][0].update(area_no=1)
        sample['shops'][0]['plans'][0]['checked_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        content['site/research.json'] = site_tools.json_bytes(sample)
        self.assertTrue(review(json.loads(content['site/research.json']))['errors'])
        self.assertEqual(site_tools.validate_site(content)['shops'], 1)

    def test_actions_summary_is_optional_and_reports_real_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'summary.md'
            with patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': str(path), 'GITHUB_RUN_ID': '123'}):
                site_tools.write_summary('自動マージ成功・公開開始要求済み',
                     {'shops': 2,
                     'plans': 8,
                     'pr': '20',
                     'unresearched_shops': 73,
                     'search_statuses': {'unresearched': 74}})
            text = path.read_text()
            self.assertIn('2', text)
            self.assertIn('8', text)
            self.assertIn('/pull/20', text)
            self.assertIn('/actions/runs/123', text)
            self.assertNotIn('Pages公開確認成功', text)
