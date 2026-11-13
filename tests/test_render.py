"""Fixed design, saved JSON and local-only filter tests."""
import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import afternoon_tea.render as r
from pathlib import Path
from unittest.mock import patch
from afternoon_tea.check import validate_site
from afternoon_tea.build import enrich


def plan(**values):
    """A displayable plan: a name, the page it was read from and when it was read."""
    return {'plan_name': 'TEST plan', 'checked_at': '2026-11-07T10:00:00+09:00',
            'source_url': 'https://example.com/test-only/plan', **values}


def fixture(category='unknown'):
    return {'schema_version': 2,
         'generated_at': '2026-11-07T15:55:22+09:00',
         'period': {'start': '2026-11-07',
         'end': '2026-12-17'},
         'shops': [{'name': 'TEST ONLY lounge',
         'area_no': 1,
         'category': category,
         'station': 'TEST station',
         'info_url': 'https://www.tablecheck.com/ja/shops/test-only/reserve',
         'plans': [{'plan_name': 'TEST winter AT', 'checked_at': '2026-11-07T10:00:00+09:00',
         'source_url': 'https://example.com/test-only/plan',
         'start': None,
         'end': None,
         'price_yen': None}]}]}

class RoutineRendererTests(unittest.TestCase):


    def test_current_saved_data_renders_reproducibly_without_old_store_data(self):
        research = json.loads((r.ROOT / 'site/research.json').read_text())
        before = copy.deepcopy(research)
        result = r.render(research)
        self.assertEqual(research, before)
        self.assertEqual(r.render(research), result)

    def test_zero_stores_and_all_14_areas(self):
        source = fixture()
        source['shops'] = []
        result = r.render(source)
        self.assertIn('確認できた情報はありません', result)
        for no in range(1, 15):
            self.assertIn('id="a' + str(no) + '"', result)
            self.assertIn('href="#a' + str(no) + '"', result)
        self.assertNotIn('<article ', result)

    def test_reference_card_and_plan_dom_and_unknown_values(self):
        data = fixture()
        data['shops'][0]['hotel_name'] = 'TEST ホテル'
        result = r.render(data)
        self.assertNotIn('cafe VAVA', result)
        for value in ['class="card c-unknown"',
             'class="plan"',
             'class="when"',
             'class="price"',
             'class="links"',
             'class="meet"',
             'class="top"',
             'class="plans"',
             'class="totop"']:
            self.assertIn(value, result)
        for value in ['料金 未確認', '提供期間 未確認', '平日 未確認', '土日祝 未確認', '提供時間・利用時間 未確認']:
            self.assertIn(value, result)

    def test_categories_use_regular_price_not_stale_categories_or_names(self):
        source = fixture()
        shop = source['shops'][0]
        source['shops'] = [{**shop, 'name': 'TEST ホテル', 'category': 'lux', 'plans': [plan(price_yen=price)]}
                           for price in (5000, 8000, 8001, None)]
        result = r.render(enrich(source))
        for cat in ['cafe', 'hotel', 'lux']:
            self.assertIn(f'class="stat s-{cat}"><b>1</b>', result)
        self.assertIn('class="card c-unknown"', result)

    def test_multiple_plans_keep_menu_and_season_display(self):
        source = fixture()
        source['shops'][0]['plans'] = [plan(plan_name='TEST 1', menu='スコーン', season=['xmas'], price_yen=1000), plan(plan_name='TEST 2', price_yen=2000)]
        result = r.render(enrich(source))
        self.assertIn('プラン1／2', result)
        self.assertIn('プラン2／2', result)
        self.assertIn('メニュー：スコーン', result)
        self.assertIn('季節・イベント', result)
        self.assertIn('クリスマス', result)
        self.assertNotIn('data-sw=', result)
        self.assertNotIn('スイーツ', result)

    def test_outside_plan_is_omitted_without_mutating_evidence(self):
        source = fixture()
        source['shops'][0]['plans'] += [{'plan_name': 'OUTSIDE ONLY', 'start': '2026-12-19', 'end': '2026-12-25'}]
        before = copy.deepcopy(source)
        result = r.render(source)
        self.assertNotIn('OUTSIDE ONLY', result)
        self.assertEqual(source, before)

    def test_research_notice_is_never_rendered_and_json_is_preserved(self):
        failures = {'schema_version': 2,
             'generated_at': None,
             'failures': [{'name': 'TEST unresearched venue',
             'area': 'TEST area',
             'checked_at': '2026-11-07T15:55:22+09:00',
             'sources': [],
             'status': 'unresearched',
             'reason': 'TEST restriction audit only',
             'retry': True}]}
        for count in (0, 1):
            source = fixture()
            source['note'] = 'TEST research note must remain in JSON only'
            source['shops'] = source['shops'][:count]
            if count:
                source['shops'][0]['hotel_name'] = 'TEST ホテル'
                source['shops'][0]['plans'].append({'plan_name': 'OUTSIDE ONLY', 'start': '2026-12-19'})
            before = copy.deepcopy((source, failures))
            for _ in range(2):
                result = r.render(source)
                for removed in ['<div class="aside">',
                     '<div class="box">',
                     source['note'],
                     'TEST restriction audit only',
                     '未調査店舗',
                     '分類は原則として価格帯',
                     '掲載なしはAT提供なしを意味しません',
                     'プランは掲載対象から除きました']:
                    self.assertNotIn(removed, result)
                if count:
                    self.assertIn('class="card c-unknown"', result)
                    self.assertIn('料金 未確認', result)
                self.assertEqual((source, failures), before)
        template = (r.TEMPLATES / 'site.html').read_text()
        self.assertNotIn('$notice', template)
        self.assertNotIn('class="aside"', template)

    def test_card_evidence_display_is_omitted_but_links_and_json_remain(self):
        urls = ['https://restaurant.ikyu.com/123456/plan111111',
             'https://www.tablecheck.com/ja/shops/test-only/reserve',
             'https://tabelog.com/tokyo/A1301/A130101/12345678/',
             'https://www.example.com/afternoon-tea/']
        for (name, price, label) in [('TEST venue', 5000, 'カフェ'), ('TEST venue', 8000, 'ホテル'),
                                     ('TEST venue', 8001, 'ホテル（高級）')]:
            data = fixture()
            base = data['shops'][0]
            data['shops'] = [{**base,
                 'name': name + ' ' + str(i),
                 'info_url': url,
                 'checked_at': '2026-11-06T09:00:00+09:00',
                 'evidence_quote': 'TEST shop evidence',
                 'plans': [{'plan_name': 'TEST plan',
                 'source_url': url,
                 'booking_url_info_only': url,
                 'checked_at': '2026-11-06T10:00:00+09:00',
                 'evidence_quote': 'TEST plan evidence',
                 'price_yen': price,
                 'start': '2026-11-07',
                 'end': '2026-12-01',
                 'weekday_available': True}]} for (i,
                 url) in enumerate(urls)]
            data = enrich(data)
            before = copy.deepcopy(data)
            for _ in range(2):
                result = r.render(data)
                for removed in ['出典：', '確認日時：', '2026-11-06T09:00:00+09:00', '2026-11-06T10:00:00+09:00', 'TEST shop evidence', 'TEST plan evidence']:
                    self.assertNotIn(removed, result)
                for url in urls:
                    self.assertEqual(result.count('href="' + url + '"'), 2)
                self.assertEqual(result.count('<p class="rnote">' + label + '</p>'), 4)
                self.assertIn('プランの情報ページ', result)
                self.assertIn('2026/11/7〜2026/12/1', result)
                self.assertIn('data-wd="1"', result)
                self.assertEqual(data, before)

    def test_text_and_attribute_injection_is_escaped(self):
        source = fixture()
        source['shops'][0]['name'] = '</h4><script>alert(1)</script>'
        source['shops'][0]['plans'][0]['plan_name'] = '" onmouseover="alert(1)<img src=x>'
        result = r.render(source)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', result)
        self.assertNotIn('<script>alert(1)</script>', result)
        self.assertIn('&lt;img src=x&gt;', result)
        self.assertEqual(result.count('<script>'), 1)

    def test_unsafe_booking_link_is_rejected(self):
        for url in ['javascript:alert(1)', 'https://user:pass@tablecheck.com/x']:
            source = fixture()
            source['shops'][0]['info_url'] = url
            with self.assertRaises(ValueError):
                r.render(source)

    def test_shop_time_is_not_assigned_to_each_plan(self):
        source = fixture()
        source['shops'][0]['time_note'] = 'Store-wide note, not per-plan evidence'
        result = r.render(source)
        self.assertNotIn('Store-wide note', result)
        self.assertIn('提供時間・利用時間 未確認', result)

    def test_no_network_calls(self):
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network forbidden')):
            self.assertIn('TEST ONLY lounge', r.render(fixture()))

    def test_invalid_generation_preserves_previous_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'site').mkdir()
            (root / 'data').mkdir()
            shutil.copy(r.ROOT / 'data/areas.json', root / 'data/areas.json')
            target = root / 'site/index.html'
            target.write_text('previous page')
            (root / 'site/research.json').write_text('{broken')
            with patch.object(r, 'ROOT', root), self.assertRaises(ValueError):
                r.generate()
            self.assertEqual(target.read_text(), 'previous page')

    def test_generate_only_replaces_index_with_valid_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'site').mkdir()
            (root / 'data').mkdir()
            shutil.copy(r.ROOT / 'data/areas.json', root / 'data/areas.json')
            (root / 'site/research.json').write_text(json.dumps(fixture()))
            before = {p.name: p.read_bytes() for p in (root / 'site').iterdir()}
            with patch.object(r, 'ROOT', root):
                r.generate()
                first = target_text = (root / 'site/index.html').read_text()
                r.generate()
                self.assertEqual((root / 'site/index.html').read_text(), first)
                self.assertNotIn('<div class="aside">', target_text)
            for (name, raw) in before.items():
                self.assertEqual((root / 'site' / name).read_bytes(), raw)
            self.assertEqual(set((p.name for p in (root / 'site').iterdir())), {'index.html', 'research.json'})
            self.assertEqual(validate_site({'site/' + p.name: p.read_bytes() for p in (root / 'site').iterdir()})['shops'], 1)

    def test_symlink_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'site').mkdir()
            protected = root / 'protected.html'
            protected.write_text('protected')
            (root / 'site/index.html').symlink_to(protected)
            with patch.object(r, 'ROOT', root), self.assertRaises(ValueError):
                r.generate()
            self.assertEqual(protected.read_text(), 'protected')

    def test_layout_has_reference_responsiveness_and_dark_mode(self):
        result = r.render(fixture())
        for value in ['prefers-color-scheme:dark',
             'max-width:820px',
             'max-width:420px',
             'grid-template-columns:1fr',
             'minmax(330px,1fr)',
             'IntersectionObserver']:
            self.assertIn(value, result)

    def test_simplified_filter_markup_survives_regeneration(self):
        source = fixture()
        before = copy.deepcopy(source)
        for _ in range(2):
            result = r.render(source)
            for removed in ['id="shop-search"', 'id="theme-search"', '店舗・ホテル名', 'プラン名・テーマ', 'data-x="pk"', '料金確認済', '値段確認済', 'イベント・季節で絞り込み']:
                self.assertNotIn(removed, result)
            self.assertIn('日程条件', result)
            self.assertIn('data-x="wd" aria-pressed="false">平日</button>', result)
            self.assertIn('data-x="we" aria-pressed="false">土日祝</button>', result)
            self.assertNotIn('平日に行ける', result)
            self.assertNotIn('土日祝に行ける', result)
            self.assertIn('aria-expanded="false" aria-controls="area-links">詳細</button>', result)
            links = re.search('<div class="btns" id="area-links" hidden>(.*?)</div>', result, re.S).group(1)
            self.assertEqual(len(re.findall('href="#a\\d+"', links)), 14)
            self.assertNotIn('スイーツで絞り込み', result)
            self.assertNotIn('data-sw=', result)
            self.assertIn('TEST ONLY lounge', result)
            self.assertIn('TEST winter AT', result)
            self.assertEqual(source, before)

    def test_filter_javascript_runs_locally(self):
        if not shutil.which('node'):
            self.skipTest('Node is needed for local filter execution')
        result = r.render(fixture())
        js = re.search('<script>(.*?)</script>', result, re.S).group(1)
        harness = (Path(__file__).parent / 'fixtures/filter_harness.js').read_text()
        for early in ('', '1'):
            proc = subprocess.run(['node', '-e', harness], input=json.dumps(js), text=True, capture_output=True, env={**os.environ, 'TEST_EARLY_CHOICE': early})
            self.assertEqual(proc.returncode, 0, proc.stderr)

class OtherAreaTests(unittest.TestCase):

    def test_verified_other_area_does_not_absorb_unknown_location(self):
        source = fixture()
        source['shops'][0]['area_no'] = 15
        result = r.render(source)
        for area in (15, None, 0, 16, '1'):
            source['shops'][0]['area_no'] = area
            result = r.render(source)
            self.assertNotIn('その他のエリア', result)
            self.assertNotIn('TEST ONLY lounge', result)
            self.assertNotIn('id="a0"', result)

class CanonicalFieldTests(unittest.TestCase):
    def test_only_canonical_station_and_plan_fields_are_displayed(self):
        source=fixture()
        shop=source['shops'][0]
        shop.update(station='日本橋駅／東京駅／日本橋駅',exit='銀座駅 B4出口 徒歩5分',
                    access='新橋駅 直結',time_note='OLD SHOP TIME')
        plan=shop['plans'][0]
        plan.update(price_yen=5000,price_note=None,time_note=None,plan_name='TEST plan',
                    price_text='OLD PRICE',time_text='OLD TIME',theme='OLD TITLE',
                    note='OLD NOTE',booking_url_info_only='https://example.com/old-plan',
                    weekday=True,wd=True)
        text=r.render(source)
        self.assertIn('<span class="mk">最寄駅</span>日本橋駅／東京駅',text)
        for old in ('銀座駅','新橋駅','B4出口','徒歩5分','直結','OLD SHOP TIME','OLD PRICE','OLD TIME','OLD TITLE','OLD NOTE','https://example.com/old-plan'):
            self.assertNotIn(old,text)
        self.assertIn('data-wd="0"',text)
        self.assertIn('提供時間・利用時間 未確認',text)
