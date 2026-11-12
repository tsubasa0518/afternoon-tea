"""Categories by the lowest regular price: <=5000 cafe / 5001-8000 hotel / >=8001 lux."""
import copy
import unittest
import afternoon_tea.build as c
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import tempfile
import afternoon_tea.check as site_tools
import afternoon_tea.build as e
import afternoon_tea.render as renderer
import importlib
import io
from afternoon_tea.build import classify
from afternoon_tea.build import enrich
from afternoon_tea.build import sweet_tags as tags
from afternoon_tea.build import enrich_plan
from afternoon_tea.build import period
from afternoon_tea.build import review
from afternoon_tea.build import JST
from afternoon_tea.render import render
from tests.test_render import fixture
from tests.test_render import Buttons
from tests.html_nodes import Document
from unittest.mock import patch
from pathlib import Path
from tests.test_check import files
from tests.test_check import FakeAPI
from urllib.error import HTTPError
from afternoon_tea.fetch import ROOT
from afternoon_tea.fetch import candidates
from afternoon_tea.check import intake
from afternoon_tea.check import validate_site
from afternoon_tea.check import json_bytes


class PriceCategoryTests(unittest.TestCase):

    def test_boundaries_and_unknown_prices(self):
        for (price, category) in [(1, 'cafe'), (5000, 'cafe'), (5000.5, 'hotel'), (5001, 'hotel'), (8000, 'hotel'),
                                  (8000.5, 'lux'), (8001, 'lux'), (30000, 'lux'),
                                  (None, 'unknown'), (True, 'unknown'), (0, 'unknown'), (-1, 'unknown'),
                                  ('5000', 'unknown'), (float('inf'), 'unknown')]:
            self.assertEqual(classify([{'price_yen': price}])[0], category, price)
        self.assertEqual(classify([{'discount_price_yen': 5000, 'price_min': 5000}]), ('unknown', None))

    def test_venue_name_and_old_categories_do_not_matter(self):
        for name in ('アマン東京', 'TEST ホテル', 'cafe'):
            data = fixture()
            data['shops'][0].update(name=name, category='cafe')
            for price, expected in ((13000, 'lux'), (4950, 'cafe'), (None, 'unknown')):
                data['shops'][0]['plans'][0]['price_yen'] = price
                self.assertEqual(enrich(data)['shops'][0]['category'], expected)

    def test_minimum_ignores_outside_plans(self):
        data = fixture('cafe')
        shop = data['shops'][0]
        shop['plans'] = [{'price_yen': 10000}, {'price_yen': 7000}, {'price_yen': 1000, 'end': '2026-11-06'},
                         {'price_yen': 500, 'start': '2026-12-18'}]
        before = copy.deepcopy(data)
        enriched = enrich(data)
        self.assertEqual(data, before)
        self.assertEqual(enriched['shops'][0]['category'], 'hotel')
        self.assertEqual(enriched['shops'][0]['category_price_yen'], 7000)
        self.assertIn('class="stat s-hotel"><b>1</b>', render(enriched))
        self.assertEqual(enrich(enriched), enriched)

    def test_explicit_regular_price_and_discount_are_kept_separate(self):
        data = fixture()
        data['shops'][0]['plans'] = [{'price_yen': 10000, 'discount_price_yen': 5000,
                                      'evidence_quote': 'different price block must not override direct input'}]
        shop = enrich(data)['shops'][0]
        self.assertEqual(shop['category'], 'lux')
        self.assertEqual(shop['plans'][0]['discount_price_yen'], 5000)
        data['shops'][0]['plans'][0].update(price_yen=None, discount_price_yen=5000)
        self.assertEqual(enrich(data)['shops'][0]['category'], 'unknown')

    def test_plan_information_links_and_official_site(self):
        data = fixture()
        shop = data['shops'][0]
        shop['source_url'] = 'https://www.example.com/afternoon-tea/'
        shop['plans'] = [{'plan_name': 'First',
             'source_url': 'https://restaurant.ikyu.com/123456/plan111111',
             'price_yen': 5000,
             'checked_at': '2026-11-06T10:00:00+09:00'},
             {'plan_name': 'Second',
             'source_url': 'https://www.example.com/winter-tea/',
             'price_yen': 10000}]
        result = render(data)
        for value in ['プラン1／2', 'プラン2／2', 'https://www.example.com/winter-tea/', '提供期間 未確認']:
            self.assertIn(value, result)

    def test_json_and_html_agree_for_each_category(self):
        for (price, expected) in [(5000, 'cafe'), (5001, 'hotel'), (8000, 'hotel'), (8001, 'lux'), (None, 'unknown')]:
            data = fixture()
            data['shops'][0]['plans'][0]['price_yen'] = price
            enriched = enrich(data)
            self.assertEqual(enriched['shops'][0]['category'], expected)
            self.assertEqual(enriched['shops'][0]['category_price_yen'], price)
            self.assertEqual(enrich(enriched), enriched)
            self.assertIn('class="card c-' + expected + '"', render(enriched))


class SweetKeywordTests(unittest.TestCase):

    def test_all_fifteen_groups_and_japanese_english_variants(self):
        examples = {'ichigo': ['いちご',
             '苺',
             'ストロベリー',
             'STRAWBERRY',
             'strawberries'],
             'melon': ['メロン',
             'melon'],
             'peach': ['桃',
             'ピーチ',
             'peaches'],
             'mango': ['マンゴー',
             'mango'],
             'grape': ['葡萄',
             'グレープ',
             'シャインマスカット',
             'grapes',
             'muscat'],
             'kuri': ['栗',
             'マロン',
             'モンブラン',
             'marron',
             'chestnut'],
             'imo': ['芋',
             'さつまいも',
             '紫芋',
             'かぼちゃ',
             'パンプキン',
             'pumpkin',
             'sweet potato'],
             'kaki': ['柿',
             '洋梨',
             '梨',
             'ペアムース',
             'pear',
             'いちじく',
             'fig'],
             'citrus': ['柑橘',
             'オレンジ',
             'orange',
             'みかん',
             'レモン',
             'lemon',
             'ゆず',
             'グレープフルーツ',
             'grapefruit'],
             'choco': ['チョコ',
             'チョコレート',
             'ショコラ',
             'chocolate',
             'cacao'],
             'wa': ['抹茶',
             'ほうじ茶',
             '玄米茶',
             'あずき',
             'あんこ',
             'きなこ',
             '和風',
             'matcha'],
             'macaron': ['マカロン',
             'macaron'],
             'parfait': ['パフェ',
             'parfait'],
             'scone': ['スコーン',
             'scone'],
             'other': ['チーズケーキ',
             'ティラミス',
             'プリン',
             'baklava']}
        for (tag, words) in examples.items():
            for word in words:
                with self.subTest(word=word):
                    self.assertEqual(tags({'menu': word}), [tag])
        self.assertEqual(tags({'menu': 'ペアプラン appearance figures'}), [])
        self.assertEqual(tags({'menu': 'ＳＴＲＡＷＢＥＲＲＹ'}), ['ichigo'])

    def test_all_plan_fields_multiple_tags_and_repeated_words(self):
        for field in ('plan_name', 'menu'):
            self.assertEqual(tags({field: 'メロンとマカロン'}), ['macaron', 'melon'])
        for field in ('theme', 'theme_name', 'description', 'explanation', 'evidence_quote', 'note'):
            self.assertEqual(tags({field: 'メロンとマカロン'}), [])
        self.assertEqual(tags({'menu': '苺のタルト、メロンムース、桃のジュレ 苺 苺'}), ['ichigo', 'melon', 'peach'])
        self.assertEqual(tags({'menu': 'マロンモンブラン、マカロン、ショコラケーキ'}), ['choco', 'kuri', 'macaron'])
        self.assertEqual(tags({'menu': 'シャインマスカットのパフェ'}), ['grape', 'parfait'])
        self.assertEqual(tags({'menu': ['いちご', {'sweets': 'マカロン'}]}), ['ichigo', 'macaron'])
        self.assertEqual(tags({'notes': {'status': '推測 スコーン'}}), [])

    def test_local_negation_options_and_unrelated_operational_notes(self):
        for (menu,
             expected) in [('いちごタルト、マカロンは含まれません、メロンムース',
             ['ichigo',
             'melon']),
             ('時間制限なしの苺タルト',
             ['ichigo']),
             ('スコーンはありません、苺タルト',
             ['ichigo']),
             ('マカロンは含まれていません、メロン',
             ['melon']),
             ('苺タルト（アルコールはありません）',
             ['ichigo']),
             ('スコーンは付いていません',
             []),
             ('マカロン（アルコールは含まれません）',
             ['macaron']),
             ('乳製品不使用の苺タルト',
             ['ichigo']),
             ('マカロンは含まれない、スコーン',
             ['scone']),
             ('苺タルトは追加料金なし',
             ['ichigo']),
             ('追加料金なしのスコーン',
             ['scone']),
             ('マカロンはオプションではありません',
             ['macaron']),
             ('苺タルト（提供期間は未確認）',
             ['ichigo']),
             ('スコーンなしでも苺タルト付き',
             ['ichigo']),
             ('苺は提供しませんがメロンムースを提供',
             ['melon']),
             ('マカロン不使用、追加料金の苺パフェ、チョコケーキ',
             ['choco']),
             ('【オプション】\n苺パフェ\n【スイーツ】\nマカロン',
             ['macaron']),
             ('オプション：苺パフェ、チョコケーキ',
             []),
             ('通常ランチのチョコケーキ。他のプランのスコーン。いちごムース',
             ['ichigo']),
             ('単品パフェ、別売のスコーン、without macarons',
             []),
             ('マカロンは含まれませんが、苺のタルト',
             ['ichigo'])]:
            with self.subTest(menu=menu):
                self.assertEqual(tags({'menu': menu}), expected)

    def test_unknown_menu_is_not_other_and_stale_tags_are_replaced(self):
        for plan in ({'plan_name': 'AT',
             'menu': None},
             {'menu': 'メニュー未確認'},
             {'menu': 'スイーツ数種'},
             {'menu': None,
             'sweets': ['ichigo'],
             'notes': {'status': 'マカロン'}}):
            self.assertEqual(enrich_plan(plan)['sweets'], [])
        self.assertEqual(tags({'menu': 'ティラミスとスコーン'}), ['scone'])
        plan = {'menu': 'マカロン', 'sweets': ['ichigo'], 'note': '既存メモ', 'evidence_quote': 'マカロン', 'checked_at': '2026-11-07T12:00:00+09:00'}
        before = copy.deepcopy(plan)
        out = enrich_plan(plan)
        self.assertEqual(out['sweets'], ['macaron'])
        self.assertEqual(plan, before)
        for key in ('menu', 'checked_at'):
            self.assertEqual(out[key], plan[key])
        self.assertNotIn('note',out)
        self.assertNotIn('evidence_quote',out)
        self.assertEqual(enrich_plan(out), out)
        out['menu'] = None
        out['evidence_quote'] = 'ATの情報のみ'
        out = enrich_plan(out)
        self.assertEqual(out['sweets'], [])
        self.assertNotIn('sweets', out.get('structured_evidence', {}))

    def test_plan_counts_html_tags_and_json_tags_agree_and_ignore_store_tags(self):
        data = fixture()
        shop = data['shops'][0]
        shop['sweets'] = ['choco', 'scone']
        shop['plans'] = [{'plan_name': 'A いちご',
             'menu': 'メロン、桃、苺 苺'},
             {'plan_name': 'B 苺',
             'menu': 'マロン、マカロン'},
             {'plan_name': 'C メロン',
             'menu': 'スコーン'},
             {'plan_name': 'outside 苺',
             'start': '2026-12-18'}]
        for p in shop['plans']:
            p.update(enrich_plan(p))
        html = render(data)
        counts = {b['key']: int(__import__('re').search('\\d+$', b['text']).group()) for b in Buttons(html).buttons}
        for (key, value) in {'ichigo': 2, 'melon': 2, 'peach': 1, 'kuri': 1, 'macaron': 1, 'scone': 1, 'choco': 0}.items():
            self.assertEqual(counts[key], value)
        plans = [n for n in Document(html).root.find('div') if n.attrs.get('class') == 'plan']
        self.assertEqual(len(plans), 3)
        for (node, p) in zip(plans, shop['plans']):
            self.assertEqual(set(node.attrs['data-sw'].split()), set(p['sweets']))
        self.assertEqual(sum(('ichigo' in n.attrs['data-sw'].split() or 'scone' in n.attrs['data-sw'].split() for n in plans)), 3)

    def test_real_filter_script_matches_plan_counts_and_or_unions(self):
        import json, re, shutil, subprocess
        from pathlib import Path
        if not shutil.which('node'):
            self.skipTest('Node required for filter execution')
        data = fixture()
        base = data['shops'][0]

        def plan(name, price, wd=False, season=None):
            return {'plan_name': name, 'price_yen': price, 'weekday_available': wd, 'season': season or []}
        data['shops'] = [{**base,
             'name': 'First',
             'sweets': ['ichigo'],
             'plans': [plan('A 苺',
             7000,
             True,
             ['xmas']),
             plan('B スコーン',
             8000),
             plan('C 苺 スコーン',
             9000,
             True,
             ['xmas']),
             plan('D メロン',
             8000),
             plan('E マスカット チョコ',
             8000),
             plan('F マスカット',
             8000)]},
             {**base,
             'name': 'Second',
             'sweets': ['scone'],
             'plans': [plan('G チョコ',
             11000),
             plan('H いちご',
             12000,
             False,
             ['collab'])]}]
        data = enrich(data)
        html = render(data)
        records = []
        for card in Document(html).root.find('article'):
            records.append({'name': card.find('h4')[0].text,
                 'dataset': {k[5:]: v for (k,
                 v) in card.attrs.items() if k.startswith('data-')},
                 'plans': [{'name': next((n.text for n in p.find('p') if n.attrs.get('class') == 'theme')),
                 'dataset': {k[5:]: v for (k,
                 v) in p.attrs.items() if k.startswith('data-')}} for p in card.find('div') if p.attrs.get('class') == 'plan']})
        buttons = [{'key': b['key'], 'count': int(re.search('\\d+$', b['text']).group())} for b in Buttons(html).buttons]
        payload = {'js': re.search('<script>(.*?)</script>',
             html,
             re.S).group(1),
             'cards': records,
             'buttons': buttons,
             'eventKeys': list(__import__('afternoon_tea.render',
             fromlist=['EVENTS']).EVENTS)}
        harness = Path(__file__).parent / 'fixtures/sweet_filter_harness.js'
        proc = subprocess.run(['node', str(harness)], input=json.dumps(payload), text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


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
        from afternoon_tea.render import render
        from tests.test_render import fixture
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


STAMP = '2026-11-07T17:50:14+09:00'
URL = 'https://restaurant.ikyu.com/123456/plan123456'

class EnrichmentTests(unittest.TestCase):

    def test_weekday_christmas_and_menu_tags_preserve_original_quotes(self):
        p = {'plan_name': 'TEST ONLY クリスマスAT（平日）', 'menu': 'スコーン・マカロン・苺・栗・かぼちゃ', 'evidence_quote': 'Christmas afternoon tea'}
        result = e.enrich_plan(p)
        self.assertTrue(result['weekday_available'])
        self.assertFalse(result['weekend_available'])
        self.assertEqual(result['season'], ['xmas'])
        self.assertEqual(result['sweets'], ['ichigo', 'imo', 'kuri', 'macaron', 'scone'])
        self.assertEqual(result['menu'], p['menu'])

    def test_null_and_mixed_optional_tags_never_stop_html_generation(self):
        for existing in (None, [], [None, 1, 'scone'], 'scone'):
            plan = {'plan_name': 'TEST ONLY クリスマスAT（平日）', 'menu': 'マカロン', 'sweets': existing, 'season': None, 'structured_evidence': None}
            result = e.enrich_plan(plan)
            self.assertIn('macaron', result['sweets'])
            self.assertEqual(result['season'], ['xmas'])
            self.assertTrue(result['weekday_available'])
            d = fixture()
            d['shops'][0]['plans'] = [result]
            self.assertIn('マカロン', renderer.render(d))

    def test_unknown_and_negated_text_do_not_invent_availability_or_tags(self):
        for p in ({'plan_name': 'TEST ONLY AT'}, {'plan_name': '平日限定ではありません'}, {'menu': 'マカロンは含まれません'}):
            result = e.enrich_plan(p)
            self.assertNotIn('weekday_available', result)
            self.assertEqual(result['sweets'], [])

    def test_weekend_and_every_day_conditions(self):
        for (title, wd, we) in [('土日祝限定', False, True), ('全日提供', True, True), ('平日限定 土日祝限定', None, None)]:
            result = e.enrich_plan({'plan_name': title})
            self.assertEqual(result.get('weekday_available'), wd)
            self.assertEqual(result.get('weekend_available'), we)

    def test_regular_and_discount_prices_are_separate_and_idempotent(self):
        p = {'price_yen': 9200, 'discount_price_yen': 7200, 'price_note': '税サ込（通常9,200円）。', 'evidence_quote': '最大21%OFF 9,200円 税サ込7,200円'}
        result = e.enrich_plan(p)
        self.assertEqual(result['price_yen'], 9200)
        self.assertEqual(result['discount_price_yen'], 7200)
        self.assertEqual(e.enrich_plan(result), result)

    def test_discount_only_does_not_reverse_calculate_regular_price(self):
        p = {'price_yen': None, 'discount_price_yen': 6000, 'evidence_quote': '20%OFF 税サ込6,000円'}
        result = e.enrich_plan(p)
        self.assertIsNone(result['price_yen'])
        self.assertEqual(result['discount_price_yen'], 6000)
        self.assertEqual(e.enrich_plan(result), result)


    def test_zero_and_two_shops_still_generate_valid_html(self):
        for count in (0, 2):
            d = fixture()
            d['shops'] = d['shops'] * count
            d = e.enrich(d)
            html = renderer.render(d)
            self.assertEqual(html.count('<article '), count)
            self.assertEqual(validate_site({'site/index.html': html.encode(),
                 'site/research.json': json_bytes(d),
})['shops'],
                 count)

class DispatchIdempotenceTests(unittest.TestCase):

    def test_open_then_edited_same_head_dispatches_exactly_once(self):
        api = FakeAPI()
        intake(api, 26, 'tsubasa0518')
        result = intake(api, 26, 'tsubasa0518')
        self.assertEqual(result['dispatch'], 'already_requested')
        self.assertEqual(sum(('/dispatches' in p for (_, p, _) in api.calls)), 1)
        self.assertEqual(sum((m == 'PUT' for (m, _, _) in api.calls)), 1)

    def test_untrusted_comment_cannot_spoof_a_bot_receipt(self):
        api = FakeAPI()
        api.comments = [{'user': {'login': 'intruder'}, 'body': '<!-- weekly-site-dispatch:' + 'a' * 40 + ' -->\nfake'}]
        self.assertEqual(intake(api, 26, 'tsubasa0518')['dispatch'], 'requested')

    def test_existing_workflow_run_recovers_after_receipt_save_failure(self):
        api = FakeAPI()
        api.pr.update(merged=True, state='closed', merge_commit_sha='c' * 40)
        api.runs = [{'head_sha': 'c' * 40, 'event': 'workflow_dispatch'}]
        self.assertEqual(intake(api, 26, 'tsubasa0518')['dispatch'], 'already_requested')
        self.assertFalse(api.calls)

    def test_failed_dispatch_does_not_create_success_receipt_and_is_retryable(self):
        api = FakeAPI()
        original = api.call

        def fail(method, path, body):
            if path.endswith('/dispatches'):
                raise HTTPError('https://api.github.com', 503, 'TEST ONLY', {}, None)
            return original(method, path, body)
        api.call = fail
        with self.assertRaises(HTTPError):
            intake(api, 26, 'tsubasa0518')
        self.assertEqual(api.comments, [])
        api.call = original
        self.assertEqual(intake(api, 26, 'tsubasa0518')['dispatch'], 'requested')


builder=importlib.import_module('afternoon_tea.build')


def current(prices=(5000,5001,8000,8001,None)):
    now=dt.datetime.now(JST)
    row=candidates()[0]
    return {'schema_version':1,'generated_at':now.isoformat(),'period':period(now=now),
            'shops':[{'name':'TEST ONLY','area_no':int(row['エリア番号']),'list_url':row['予約ページURL'],
                      'station':'日本橋駅','address':None,'source_site':row['予約サイト'],
                      'plans':[{'plan_name':'PLAN '+str(i),'price_yen':price,'checked_at':now.isoformat(),
                                'start':None,'end':None,'menu':'スコーン','cc':'FR'} for i,price in enumerate(prices)]}]}


class BuildTests(unittest.TestCase):
    def test_build_is_non_mutating_and_creates_display_values_once(self):
        data=current();before=copy.deepcopy(data)
        out=builder.build(data)
        self.assertEqual(data,before)
        self.assertEqual(out['shops'][0]['category'],'cafe')
        for old,plan in zip(data['shops'][0]['plans'],out['shops'][0]['plans']):
            self.assertEqual(plan['checked_at'],old['checked_at'])
            self.assertEqual(plan['price_yen'],old['price_yen'])
            self.assertEqual(plan['sweets'],['scone'])
            self.assertEqual(plan['cc'],'fr')
        html=render(out)
        self.assertEqual(html.count('🇫🇷 フランス'),5)
        validate_site({'site/research.json':json_bytes(out),'site/index.html':html.encode()})

    def test_prices_are_direct_inputs_and_discount_never_replaces_regular(self):
        plan={'plan_name':'AT','price_yen':9000,'discount_price_yen':4500,
              'price_note':'50%OFF、通常価格12,000円','evidence_quote':'通常価格 20,000円 50%OFF 10,000円'}
        out=enrich_plan(plan)
        self.assertEqual((out['price_yen'],out['discount_price_yen']),(9000,4500))
        self.assertEqual(out['price_note'],plan['price_note'])
        plan.update(price_yen=None)
        self.assertIsNone(enrich_plan(plan)['price_yen'])
        del plan['price_yen']
        self.assertIsNone(enrich_plan(plan)['price_yen'])

    def test_invalid_country_codes_do_not_stop_build(self):
        for value in ('zz','uk',1,True,'JPN','',None):
            data=current((8001,));p=data['shops'][0]['plans'][0]
            p.update(cc=value,country='TEST old name',country_basis='TEST reason',
                     country_input_hash='old',country_decision_hash='old',notes={'status':'テーマ国推測：TEST'})
            out=builder.build(data);p=out['shops'][0]['plans'][0]
            self.assertIsNone(p['cc'])
            self.assertFalse(any(key.startswith('country') or key=='notes' for key in p))
            self.assertNotIn('country-theme',re.search(r'<main>(.*?)</main>',render(out),re.S).group(1))

    def test_fresh_carry_is_kept_old_future_and_outside_period_are_removed(self):
        data=current((9000,));now=dt.datetime.now(JST)
        previous=copy.deepcopy(data)
        p=previous['shops'][0]['plans'][0]
        p.update(plan_name='CARRIED',checked_at=(now-dt.timedelta(days=13)).isoformat())
        previous['shops'][0]['plans'] += [{**p,'plan_name':'OLD','checked_at':(now-dt.timedelta(days=15)).isoformat()},
                                         {**p,'plan_name':'FUTURE','checked_at':(now+dt.timedelta(days=1)).isoformat()},
                                         {**p,'plan_name':'OUTSIDE','end':(dt.date.fromisoformat(data['period']['start'])-dt.timedelta(days=1)).isoformat()}]
        out=builder.build(data,previous,now=now)
        plans={p['plan_name']:p for p in out['shops'][0]['plans']}
        self.assertEqual(set(plans),{'CARRIED','PLAN 0'})
        self.assertEqual(plans['CARRIED']['checked_at'],p['checked_at'])

    def test_renderer_does_not_recompute_saved_classification_or_sweets(self):
        data=builder.build(current((9000,)))
        data['shops'][0]['category']='cafe'
        data['shops'][0]['plans'][0].update(menu='チョコレート',sweets=['scone'])
        before=copy.deepcopy(data)
        with patch('afternoon_tea.build.classify',side_effect=AssertionError('render must use saved category')), \
             patch('afternoon_tea.build.extract_sweets',side_effect=AssertionError('render must use saved sweets')), \
             patch('afternoon_tea.build.enrich',side_effect=AssertionError('render must not build')):
            html=render(data)
        self.assertIn('class="card c-cafe"',html)
        plans=[n for n in Document(html).root.find('div') if n.attrs.get('class')=='plan']
        self.assertEqual(plans[0].attrs['data-sw'],'scone')
        self.assertEqual(data,before)

    def test_zero_is_a_valid_build_result(self):
        data=current();data['shops']=[]
        out=builder.build(data)
        html=render(out)
        self.assertNotIn('<article ',html)
        self.assertEqual(validate_site({'site/research.json':json_bytes(out),'site/index.html':html.encode()})['plans'],0)


class BuildCommandTests(unittest.TestCase):
    def run_in_root(self,data,html='previous HTML'):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        (root/'site').mkdir();(root/'data').mkdir()
        shutil.copyfile(ROOT/'data/areas.json',root/'data/areas.json')
        shutil.copyfile(ROOT/'data/country_registry.json',root/'data/country_registry.json')
        (root/'site/research.json').write_bytes(json_bytes(data))
        (root/'site/index.html').write_text(html)
        return root

    def test_build_command_writes_json_and_html_and_does_not_fetch(self):
        renderer=importlib.import_module('afternoon_tea.render')
        for count in (1,0):
            data=current((8001,));data['shops']=data['shops'][:count]
            root=self.run_in_root(data)
            with patch.object(builder,'ROOT',root),patch.object(renderer,'ROOT',root), \
                 patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('offline')), \
                 patch('sys.stdout',new=io.StringIO()):
                self.assertEqual(builder.main(),0)
            written=json.loads((root/'site/research.json').read_text())
            self.assertEqual(len(written['shops']),count)
            self.assertEqual((root/'site/index.html').read_text(),render(written))

    def test_validation_failure_keeps_existing_files(self):
        renderer=importlib.import_module('afternoon_tea.render')
        data=current();data['period']['end']='invalid'
        root=self.run_in_root(data);before=(root/'site/research.json').read_bytes()
        with patch.object(builder,'ROOT',root),patch.object(renderer,'ROOT',root),self.assertRaises(ValueError):
            builder.main()
        self.assertEqual((root/'site/research.json').read_bytes(),before)
        self.assertEqual((root/'site/index.html').read_text(),'previous HTML')


class PriceFilterTests(unittest.TestCase):
    def test_real_filter_boundaries(self):
        if not shutil.which('node'):
            self.fail('Node is required for the existing offline filter tests')
        html=render(builder.build(current()))
        self.assertIn('5,000円以下',html);self.assertIn('5,001〜8,000円',html);self.assertIn('8,001円以上',html)
        self.assertNotIn('6,000円以下',html)
        plans=[n for n in Document(html).root.find('div') if n.attrs.get('class')=='plan']
        payload={'js':re.search('<script>(.*?)</script>',html,re.S).group(1),
                 'plans':[{'name':'PLAN '+str(i),'dataset':{k[5:]:v for k,v in n.attrs.items() if k.startswith('data-')}} for i,n in enumerate(plans)]}
        harness=r'''
const vm=require('vm'),fs=require('fs'),p=JSON.parse(fs.readFileSync(0,'utf8'));
function node(dataset={}){const n={dataset,hidden:false,value:'',textContent:'',attrs:{},events:{},classes:new Set(),getAttribute(k){return this.attrs[k]},setAttribute(k,v){this.attrs[k]=String(v)},addEventListener(k,f){this.events[k]=f}};n.classList={toggle(k,v){v?n.classes.add(k):n.classes.delete(k)}};return n}
const plans=p.plans.map(x=>Object.assign(node(x.dataset),{name:x.name}));const card=node({cat:'cafe'});card.querySelectorAll=()=>plans;
const buttons=['cafe','hotel','lux','unknown'].map(cat=>node({cat})),ids={};for(const x of ['price-filter','filter-status','no-results','reset-filters','area-toggle','area-links'])ids[x]=node();
const document={getElementById(id){return ids[id]},querySelector(){return null},querySelectorAll(q){return q==='.fb'?buttons:q==='.card'?[card]:[]}};
vm.runInNewContext(p.js,{document,window:{addEventListener(){}},setTimeout(){}});
for(const [choice,wanted] of [['low',['PLAN 0']],['mid',['PLAN 1','PLAN 2']],['high',['PLAN 3']],['unknown',['PLAN 4']],['all',['PLAN 0','PLAN 1','PLAN 2','PLAN 3','PLAN 4']]]){
ids['price-filter'].value=choice;ids['price-filter'].events.change();const actual=plans.filter(x=>!x.hidden).map(x=>x.name);if(JSON.stringify(actual)!==JSON.stringify(wanted))throw Error(choice+': '+JSON.stringify(actual));
}
process.stdout.write('price boundaries passed');'''
        result=subprocess.run(['node','-e',harness],input=json.dumps(payload),capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)


class DocumentationTests(unittest.TestCase):
    def test_numbers_live_in_the_procedure_and_safety_source_only(self):
        for name in ('README.md','CLAUDE.md'):
            text=(ROOT/name).read_text()
            for value in ('1500','1,500','200要求','60秒','3秒','5,000','8,000','14日','07:17'):
                self.assertNotIn(value,text,name)
        procedure=(ROOT/'docs/weekly_procedure.md').read_text()
        for value in ('1,500秒','200要求','60秒','3秒','5,000円以下','5,001〜8,000円','8,001円以上','14日以内','07:17'):
            self.assertEqual(procedure.count(value),1,value)
        self.assertEqual((ROOT/'AGENTS.md').read_text().count('3秒'),1)
        self.assertNotIn('python3 -m unittest',procedure)
        self.assertIn('pip install -r requirements-browser.txt',procedure)
        self.assertIn('失敗してもGETだけで続ける',procedure)
        self.assertEqual(procedure.count('トークン'),1)


class PlanPrivacyTests(unittest.TestCase):
    def test_only_sensitive_plans_are_removed_and_no_values_are_logged(self):
        examples=('ghp_'+'x'*36,'-----BEGIN PRIVATE KEY-----','name@example.test',
                  '090-1234-5678','4111 1111 1111 1111')
        for secret in examples:
            with self.subTest(kind=examples.index(secret)):
                data=current((4000,9000))
                data['shops'][0]['plans'][0]['menu']=secret
                before=copy.deepcopy(data)
                out=builder.build(data)
                self.assertEqual(data,before)
                self.assertEqual([p['plan_name'] for p in out['shops'][0]['plans']],['PLAN 1'])
                self.assertEqual(out['shops'][0]['category'],'lux')
                self.assertEqual(out['excluded_sensitive_plans'],{'current':1,'previous':0})
                self.assertNotIn(secret,json_bytes(out).decode())
                html=render(out)
                self.assertNotIn(secret,html)
                self.assertEqual(validate_site({'site/research.json':json_bytes(out),'site/index.html':html.encode()})['plans'],1)

    def test_sensitive_only_shop_is_omitted_and_zero_is_publishable(self):
        data=current((5000,))
        data['shops'][0].update(name='EXCLUDED SHOP ONLY')
        data['shops'][0]['plans'][0]['menu']='name@example.test'
        out=builder.build(data)
        self.assertEqual(out['shops'],[])
        self.assertNotIn('EXCLUDED SHOP ONLY',json_bytes(out).decode())
        self.assertEqual(out['excluded_sensitive_plans']['current'],1)
        self.assertEqual(validate_site({'site/research.json':json_bytes(out),'site/index.html':render(out).encode()})['plans'],0)

    def test_safe_carried_plan_survives_unsafe_replacement_and_rebuild_count_is_stable(self):
        current_data=current((4000,9000))
        previous=copy.deepcopy(current_data)
        previous['shops'][0]['plans'][0]['price_yen']=6000
        previous['shops'][0]['plans'][0]['checked_at']=(dt.datetime.now(JST)-dt.timedelta(days=2)).isoformat()
        previous['shops'][0]['plans'][1]['menu']='old@example.test'
        current_data['shops'][0]['plans'][0]['menu']='new@example.test'
        out=builder.build(current_data,previous)
        self.assertEqual(out['excluded_sensitive_plans'],{'current':1,'previous':1})
        carried=out['shops'][0]['plans'][0]
        self.assertEqual(carried['price_yen'],6000)
        self.assertEqual(carried['checked_at'],previous['shops'][0]['plans'][0]['checked_at'])
        self.assertEqual(builder.build(out,previous),out)

    def test_unrelated_validation_error_is_not_silently_dropped(self):
        data=current((4000,));data['shops'][0]['plans'][0]['start']='invalid'
        with self.assertRaisesRegex(ValueError,'invalid_plan_period'):
            builder.build(data)
        data=current((4000,));data['shops'][0]['address']='person@example.test'
        with self.assertRaises(site_tools.SensitiveDataError):
            builder.build(data)

    def test_old_plans_are_still_removed_by_build(self):
        data=current((4000,))
        data['shops'][0]['plans'][0]['checked_at']=(dt.datetime.now(JST)-dt.timedelta(days=15)).isoformat()
        self.assertEqual(builder.build(data)['shops'],[])

    def test_build_command_writes_only_safe_data_and_report_has_only_a_count(self):
        data=current((4000,9000));data['shops'][0]['plans'][0]['menu']='hidden@example.test'
        root=BuildCommandTests.run_in_root(self,data)
        import afternoon_tea.fetch as collect
        with patch.object(builder,'ROOT',root),patch.object(renderer,'ROOT',root),patch('sys.stdout',new=io.StringIO()) as stdout:
            self.assertEqual(builder.main(),0)
        self.assertNotIn('hidden@example.test',stdout.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())['excluded_sensitive_plans'],1)
        result=json.loads((root/'site/research.json').read_text())
        state={'started_iso':data['generated_at'],'rows':{},'browser_runs':0,'browser_unavailable':None,
               'blocked_operations':0,'blocked_resources':0}
        text=collect.report(state=state,research=result)
        self.assertIn('秘密情報・個人情報の検査で除外したプラン数: 1',text)
        for path in (root/'site').iterdir():
            self.assertNotIn('hidden@example.test',path.read_text())
        self.assertNotIn('hidden@example.test',text)

    def test_retired_digest_shapes_do_not_hide_card_numbers(self):
        disguised='a'*24+'4111111111111111'+'a'*24
        for menu in (disguised,{'document_id':disguised},[disguised]):
            data=current((4000,9000));data['shops'][0]['plans'][0]['menu']=menu
            out=builder.build(data)
            self.assertEqual(out['excluded_sensitive_plans']['current'],1)
            self.assertEqual([p['plan_name'] for p in out['shops'][0]['plans']],['PLAN 1'])
            self.assertNotIn('4111111111111111',json_bytes(out).decode())
