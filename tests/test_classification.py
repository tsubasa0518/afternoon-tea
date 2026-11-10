"""Regression cases for weekly price bands and independent plan evidence."""
import copy
import unittest
from afternoon_tea.processing.classification import classify
from afternoon_tea.processing.enrichment import enrich
from afternoon_tea.publication.renderer import render
from afternoon_tea.collection.transport import check_url, ForbiddenOperation
from tests.test_renderer import fixture, FAILURES

class PriceCategoryTests(unittest.TestCase):

    def test_boundaries_and_unknowns(self):
        for (price,
             category) in [(1,
             'cafe'),
             (6000,
             'cafe'),
             (6001,
             'hotel'),
             (9999,
             'hotel'),
             (10000,
             'lux'),
             (None,
             'unknown'),
             (True,
             'unknown'),
             (0,
             'unknown'),
             (-1,
             'unknown'),
             ('6000',
             'unknown'),
             (float('inf'),
             'unknown')]:
            self.assertEqual(classify([{'price_yen': price}])[0], category)
        self.assertEqual(classify([{'discount_price_yen': 5000, 'price_min': 5000}]), ('unknown', None))

    def test_minimum_ignores_outside_plans_and_venue_type(self):
        data = fixture('cafe')
        shop = data['shops'][0]
        shop['plans'] = [{'price_yen': 10000}, {'price_yen': 7000}, {'price_yen': 1000, 'end': '2026-11-06'}, {'price_yen': 500, 'start': '2026-12-18'}]
        before = copy.deepcopy(data)
        enriched = enrich(data, {'areas': []})
        self.assertEqual(data, before)
        self.assertEqual(enriched['shops'][0]['category'], 'hotel')
        self.assertEqual(enriched['shops'][0]['category_price_yen'], 7000)
        self.assertIn('class="stat s-hotel"><b>1</b>', render(data))
        self.assertEqual(enrich(enriched, {'areas': []}), enriched)

    def test_discount_does_not_lower_category(self):
        data = fixture()
        data['shops'][0]['plans'] = [{'price_yen': 5000, 'evidence_quote': '通常価格 10,000円 50%OFF 5,000円'}]
        shop = enrich(data, {'areas': []})['shops'][0]
        self.assertEqual(shop['category'], 'lux')
        self.assertEqual(shop['plans'][0]['discount_price_yen'], 5000)
        data['shops'][0]['plans'][0]['evidence_quote'] = '50%OFF 5,000円'
        self.assertEqual(enrich(data, {'areas': []})['shops'][0]['category'], 'unknown')

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

    def test_explicit_public_hosts_keep_transport_prohibitions(self):
        host = 'www.example.com'
        for path in ['/afternoon-tea/', '/robots.txt']:
            check_url('https://' + host + path, public_hosts=[host])
        for url in ['https://' + host + '/login',
             'https://' + host + '/booking',
             'https://' + host + '/tea?date=2026-11-07',
             'https://' + host + '/tea#reserve',
             'https://another.example.com/tea']:
            with self.assertRaises(ForbiddenOperation):
                check_url(url, public_hosts=[host])
        for host in ['ssl.tabelog.com', 'localhost', '127.0.0.1', 'foo.local']:
            with self.assertRaises(ForbiddenOperation):
                check_url('https://' + host + '/tea', public_hosts=[host])
        with self.assertRaises(ForbiddenOperation):
            check_url('https://www.example.com/tea', 'POST', public_hosts=['www.example.com'])

    def test_public_source_still_requires_robots_and_stops_on_denial(self):
        from afternoon_tea.collection.reader import Browser
        from urllib.robotparser import RobotFileParser
        from urllib.error import HTTPError
        from unittest.mock import Mock
        host = 'www.example.com'
        url = 'https://' + host + '/afternoon-tea/'
        browser = Browser(delay=0, public_hosts=[host])
        robots = RobotFileParser()
        robots.parse(['User-agent: *', 'Disallow: /'])
        browser.robots[host] = robots
        browser._open = Mock()
        with self.assertRaisesRegex(RuntimeError, 'robots_'):
            browser.fetch(url)
        browser._open.assert_not_called()
        robots = RobotFileParser()
        robots.parse(['User-agent: *', 'Allow: /'])
        browser = Browser(delay=0, public_hosts=[host])
        browser._open = Mock()
        browser.robots[host] = robots
        browser._open.side_effect = HTTPError(url, 403, 'denied', {}, None)
        with self.assertRaisesRegex(RuntimeError, 'HTTP_403'):
            browser.fetch(url)
        with self.assertRaisesRegex(RuntimeError, 'host_stopped'):
            browser.fetch(url)
        self.assertEqual(browser._open.call_count, 1)

    def test_public_search_only_accepts_one_text_query(self):
        check_url('https://www.bing.com/search?q=Tokyo%20afternoon%20tea')
        check_url('https://www.bing.com/robots.txt')
        for url in ['https://www.bing.com/search?q=tea&date=20261107',
             'https://www.bing.com/search?q=tea&q=hotel',
             'https://www.bing.com/search?q=',
             'https://www.bing.com/login',
             'https://www.example.com/tea?q=tea']:
            with self.assertRaises(ForbiddenOperation):
                check_url(url)

    def test_unknown_price_uses_only_evidenced_facility(self):
        plans = [{'price_yen': None, 'discount_price_yen': 5000}]
        cases = [({'hotel_name': 'TEST Hotel'},
             'hotel'),
             ({'facility_type': 'hotel',
             'facility_source': 'https://example.com/facility'},
             'hotel'),
             ({'facility_type': 'non_hotel',
             'facility_source': 'saved facility evidence'},
             'cafe'),
             ({'facility_type': 'hotel'},
             'unknown'),
             ({'hotel_name': '未確認'},
             'unknown'),
             ({'name': 'TEST Hotel lounge',
             'category': 'hotel'},
             'unknown')]
        for (shop, expected) in cases:
            with self.subTest(shop=shop):
                self.assertEqual(classify(plans, shop), (expected, None))
        for (price, expected) in [(5000, 'cafe'), (7000, 'hotel'), (10000, 'lux')]:
            self.assertEqual(classify([{'price_yen': price}], {'hotel_name': 'TEST Hotel'})[0], expected)
            self.assertEqual(classify([{'price_yen': price}], {'facility_type': 'non_hotel', 'facility_source': 'saved'})[0], expected)

    def test_master_fallback_requires_exact_identity_and_never_produces_lux(self):
        master = {'areas': [{'cats': {'lux': {'shops': [{'id': 'test', 'name': 'Exact venue'}]}}}]}
        self.assertEqual(classify([], {'id': 'test', 'name': 'Exact venue'}, master), ('hotel', None))
        self.assertEqual(classify([], {'id': 'test', 'name': 'Different venue'}, master), ('unknown', None))
        master['areas'][0]['cats'] = {'cafe': {'shops': [{'id': 'test', 'name': 'Exact venue'}]}}
        self.assertEqual(classify([], {'id': 'test', 'name': 'Exact venue'}, master), ('cafe', None))

    def test_unknown_price_json_and_html_agree_without_filling_prices(self):
        for (facility, expected) in [('hotel', 'hotel'), ('non_hotel', 'cafe')]:
            data = fixture()
            shop = data['shops'][0]
            shop.update(facility_type=facility, facility_source='saved facility evidence')
            original = copy.deepcopy(data)
            enriched = enrich(data)
            self.assertEqual(enriched['shops'][0]['category'], expected)
            self.assertIsNone(enriched['shops'][0]['category_price_yen'])
            self.assertTrue(all((enriched['shops'][0]['plans'][0][key] == value for (key, value) in original['shops'][0]['plans'][0].items())))
            self.assertEqual(data, original)
            self.assertEqual(enrich(enriched), enriched)
            html = render(enriched)
            self.assertIn('class="card c-' + expected + '"', html)
            self.assertIn('料金 未確認', html)
            self.assertIn('data-price=""', html)
            self.assertIn('<option value="unknown">料金未確認</option>', html)

    def test_three_named_hotels_keep_unknown_prices_in_hotel_category(self):
        data = fixture()
        base = data['shops'][0]
        data['shops'] = [{**base,
             'name': name + ' / ' + lounge,
             'hotel_name': name} for (name,
             lounge) in [('マンダリン オリエンタル 東京',
             'オリエンタルラウンジ'),
             ('パレスホテル東京',
             'ザ パレス ラウンジ'),
             ('東京ドームホテル',
             'アーティスト カフェ')]]
        result = enrich(data)
        for shop in result['shops']:
            self.assertEqual(shop['category'], 'hotel')
            self.assertIsNone(shop['category_price_yen'])
            self.assertTrue(all((p['price_yen'] is None for p in shop['plans'])))
        html = render(result)
        self.assertIn('class="stat s-hotel"><b>3</b>', html)
        self.assertEqual(html.count('料金 未確認'), 3)
