"""All-country validation and saved-text-only semantic decision lifecycle."""
import copy
import json
import unittest
from unittest.mock import patch
from afternoon_tea.processing import themes as c
from afternoon_tea.publication.renderer import render
from afternoon_tea.publication.site import validate_json, json_bytes
from tests.test_renderer import fixture, FAILURES

def judged(country='フランス', cc='fr', kind='explicit'):
    data = fixture()
    plan = data['shops'][0]['plans'][0]
    plan.update(plan_name='TEST cultural afternoon tea',
         menu='TEST full menu',
         description='TEST official description',
         evidence_quote='TEST original evidence',
         note='Keep existing note',
         notes={'status': 'Keep previous status'})
    (data, _) = c.prepare(data)
    data['shops'][0]['plans'][0].update(country=country, cc=cc, country_source_type=kind, country_basis='TEST full menu cultural evidence')
    return c.finalize(data)

class CountryThemesTests(unittest.TestCase):

    def test_every_assigned_code_round_trips_to_regional_indicator_flag(self):
        self.assertGreater(len(c.registry()), 240)
        for (cc, entry) in c.registry().items():
            with self.subTest(cc=cc):
                value = c.flag(cc.upper())
                self.assertEqual(''.join((chr(ord(ch) - 127462 + ord('a')) for ch in value)), cc)
                c.validate_country({'country': entry['name'], 'cc': cc, 'country_source_type': 'explicit'})
        for code in ('gb', 'fr', 'it', 'jp', 'bt', 'uy', 'fj', 'mg'):
            self.assertEqual(len(c.flag(code)), 2)
        self.assertEqual(c.flag('gb'), '🇬🇧')
        self.assertEqual(c.flag('fr'), '🇫🇷')
        self.assertEqual(c.flag('it'), '🇮🇹')
        self.assertEqual(c.flag('jp'), '🇯🇵')

    def test_schema_rejects_unassigned_codes_name_mismatch_and_partial_decisions(self):
        cases = [{'country': '日本',
             'cc': 'fr',
             'country_source_type': 'explicit'},
             {'country': 'France',
             'cc': 'zz',
             'country_source_type': 'inferred'},
             {'country': 'United Kingdom',
             'cc': 'uk',
             'country_source_type': 'explicit'},
             {'country': 'France',
             'cc': 'fr',
             'country_source_type': 'unknown'},
             {'country': None,
             'cc': None,
             'country_source_type': 'guessed'},
             {'cc': 'fr'}]
        for decision in cases:
            data = fixture()
            data['shops'][0]['plans'][0].update(decision)
            with self.subTest(decision=decision), self.assertRaises(ValueError):
                validate_json(json_bytes(data))
        c.validate_country({'country': 'France', 'cc': 'FR', 'country_source_type': 'explicit'})
        c.validate_country({'country': 'イギリス', 'cc': 'gb', 'country_source_type': 'explicit'})
        c.validate_country({'country': None, 'cc': None, 'country_source_type': 'unknown'})
        c.validate_country({})

    def test_explicit_and_inferred_are_distinct_and_internal_audit_is_private(self):
        for (kind, label) in [('explicit', '🇫🇷 フランス'), ('inferred', '🇫🇷 フランス風')]:
            data = judged(kind=kind)
            before = copy.deepcopy(data)
            html = render(data, FAILURES)
            self.assertIn(label, html)
            for private in ('TEST full menu cultural evidence', 'Keep previous status', 'TEST original evidence', 'notes.status', '出典：', '確認日時：'):
                self.assertNotIn(private, html)
            self.assertIn('Keep existing note', html)
            plan = data['shops'][0]['plans'][0]
            if kind == 'inferred':
                for text in (data['shops'][0]['name'], plan['plan_name'], 'フランス', plan['country_basis']):
                    self.assertIn(text, plan['notes']['status'])
                self.assertIn('Keep previous status', plan['notes']['status'])
            self.assertEqual(c.finalize(data), data)
            self.assertEqual(data, before)

    def test_minimal_saved_fields_support_countries_without_pre_registration(self):
        for cc in ('bt', 'uy', 'fj', 'mg', 'gb'):
            data = fixture()
            plan = data['shops'][0]['plans'][0]
            plan.update(country=c.registry()[cc]['name'], cc=cc, country_source_type='explicit')
            self.assertIn(c.flag(cc), render(data, FAILURES))
        with self.assertRaises(ValueError):
            c.validate_country({'country_decision_hash': 'not a hash'})

    def test_unknown_and_legacy_plan_have_no_badge_and_no_automatic_food_guess(self):
        data = fixture()
        data['shops'][0]['plans'] = [{'plan_name': 'Afternoon tea', 'menu': 'スコーンとマカロン'}, {'plan_name': 'Swiss tea brand', 'menu': 'チョコレート一品'}]
        (prepared, pending) = c.prepare(data)
        self.assertEqual(len(pending), 2)
        for plan in prepared['shops'][0]['plans']:
            self.assertIsNone(plan['country'])
            self.assertIsNone(plan['cc'])
            plan['country_basis'] = 'Insufficient whole-plan evidence'
        done = c.finalize(prepared)
        self.assertNotIn('aria-label="テーマの国・地域"', render(done, FAILURES))
        self.assertNotIn('aria-label="テーマの国・地域"', render(data, FAILURES))
        self.assertEqual(len(c.prepare(done)[1]), 0)

    def test_unchanged_previous_decisions_and_reasons_are_reused(self):
        for kind in ('explicit', 'inferred', 'unknown'):
            previous = judged(kind=kind, country=None if kind == 'unknown' else 'フランス', cc=None if kind == 'unknown' else 'fr')
            current = fixture()
            current['shops'] = copy.deepcopy(previous['shops'])
            plan = current['shops'][0]['plans'][0]
            for key in (*c.FIELDS, 'country_basis', 'country_decision_hash', 'country_input_hash'):
                plan.pop(key, None)
            plan['checked_at'] = '2026-11-08T10:00:00+09:00'
            plan['price_yen'] = 8000
            plan['start'] = '2026-11-08'
            before = copy.deepcopy(current)
            (result, pending) = c.prepare(current, previous)
            self.assertEqual(pending, [])
            self.assertEqual(result['shops'][0]['plans'][0]['country_source_type'], kind)
            self.assertEqual(result['shops'][0]['plans'][0]['country_basis'], previous['shops'][0]['plans'][0]['country_basis'])
            self.assertEqual(current, before)
            self.assertEqual(c.finalize(result)['shops'][0]['plans'][0]['price_yen'], 8000)

    def test_new_and_changed_content_only_is_pending_and_stale_badges_are_hidden(self):
        for key in ('plan_name', 'menu', 'description', 'theme'):
            previous = judged()
            current = copy.deepcopy(previous)
            current['shops'][0]['plans'][0][key] = 'NEW themed content'
            self.assertNotIn('aria-label="テーマの国・地域"', render(current, FAILURES))
            (result, pending) = c.prepare(current, previous)
            self.assertEqual(len(pending), 1)
            self.assertIsNone(result['shops'][0]['plans'][0]['cc'])
            with self.assertRaises(ValueError):
                c.finalize(current)
        current = judged()
        current['shops'][0]['concept'] = 'NEW venue concept'
        self.assertEqual(len(c.prepare(current)[1]), 1)

    def test_multiple_plans_are_independent_and_research_facts_remain_unchanged(self):
        france = judged()
        japan = judged(country='日本', cc='jp', kind='inferred')
        data = copy.deepcopy(france)
        data['shops'][0]['plans'] += japan['shops'][0]['plans']
        before = copy.deepcopy(data)
        (result, pending) = c.prepare(data)
        self.assertEqual(pending, [])
        result = c.finalize(result)
        html = render(result, FAILURES)
        self.assertIn('🇫🇷 フランス', html)
        self.assertIn('🇯🇵 日本風', html)
        self.assertIn('プラン1／2', html)
        self.assertIn('プラン2／2', html)
        self.assertEqual(result, before)

    def test_no_http_or_model_calls_and_weekly_regeneration_is_reproducible(self):
        data = judged(kind='inferred')
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('no network')):
            (result, pending) = c.prepare(data, data)
            self.assertEqual(pending, [])
            result = c.finalize(result)
            self.assertEqual(render(result, FAILURES), render(data, FAILURES))

    def test_finalization_requires_current_content_and_a_recorded_reason(self):
        (data, _) = c.prepare(fixture())
        with self.assertRaises(ValueError):
            c.finalize(data)
        plan = data['shops'][0]['plans'][0]
        plan['country_basis'] = 'No country evidence'
        done = c.finalize(data)
        plan['menu'] = 'Changed without re-reading'
        with self.assertRaises(ValueError):
            c.finalize(data)
        self.assertEqual(c.prepare(done)[1], [])
