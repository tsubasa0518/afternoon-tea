"""Country codes are saved facts; no evidence, inference status or cache remains."""
import copy
import unittest
from unittest.mock import patch
from afternoon_tea.processing import themes as c
from afternoon_tea.publication.renderer import render
from tests.test_renderer import fixture

class CountryThemesTests(unittest.TestCase):
    def test_every_assigned_code_has_a_flag(self):
        self.assertGreater(len(c.registry()),240)
        for cc in c.registry():
            result=c.normalize_plan({'cc':cc.upper()})
            self.assertEqual(result,{'cc':cc})
            self.assertEqual(''.join(chr(ord(ch)-127462+ord('a')) for ch in c.flag(cc)),cc)
        self.assertEqual(c.flag('GB'),'🇬🇧')
        self.assertEqual(c.flag('fr'),'🇫🇷')
        self.assertEqual(c.flag('jp'),'🇯🇵')

    def test_invalid_or_missing_codes_become_null(self):
        for value in (None,'zz','uk','',1,True,['jp'],'日本',' jp','JPN','KZ'):
            result=c.normalize_plan({'cc':value})
            self.assertIsNone(result['cc'])
            c.validate_country(result)
            self.assertIsNone(c.display(result))
        self.assertEqual(c.normalize_plan({}),{'cc':None})

    def test_country_code_alone_displays_flag_without_a_country_filter(self):
        data=fixture();data['shops'][0]['plans'][0]['cc']='fr'
        before=copy.deepcopy(data);html=render(data)
        self.assertIn('🇫🇷 フランス',html)
        self.assertNotIn('data-country',html)
        self.assertNotIn('country-filter',html)
        self.assertEqual(data,before)

    def test_old_rationale_hash_and_inferred_notes_are_removed(self):
        plan={'plan_name':'AT','price_yen':9000,'cc':'jp','country':'日本','country_source_type':'inferred',
              'country_basis':'TEST reason','country_input_hash':'a'*64,'country_decision_hash':'b'*64,
              'notes':{'status':'テーマ国推測：TEST'}}
        before=copy.deepcopy(plan);out=c.normalize_plan(plan)
        self.assertEqual(out,{'plan_name':'AT','price_yen':9000,'cc':'jp'})
        self.assertEqual(plan,before)
        self.assertFalse(any(hasattr(c,key) for key in ('prepare','finalize','content_hash','identity')))

    def test_no_country_is_inferred_from_food_or_old_country_name(self):
        for plan in ({'menu':'抹茶とスコーン'},{'country':'フランス','menu':'マカロン'}):
            self.assertIsNone(c.normalize_plan(plan)['cc'])
        with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('offline')):
            self.assertEqual(c.display({'cc':'uy'}),'🇺🇾 ウルグアイ')
