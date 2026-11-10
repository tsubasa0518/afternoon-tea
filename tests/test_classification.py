"""Venue categories: cafe unless stated as a hotel; hotels split at 6,000 yen."""
import copy
import unittest
from afternoon_tea.processing.classification import classify, hotel_basis
from afternoon_tea.processing.enrichment import enrich
from afternoon_tea.publication.renderer import render
from tests.test_renderer import fixture

HOTEL = {'name': 'TEST ホテル東京 / ラウンジ'}


class PriceCategoryTests(unittest.TestCase):

    def test_hotel_boundaries_and_unknown_prices(self):
        for (price, category) in [(1, 'hotel'), (6000, 'hotel'), (6000.5, 'lux'), (6001, 'lux'), (10000, 'lux'),
                                  (None, 'unknown'), (True, 'unknown'), (0, 'unknown'), (-1, 'unknown'),
                                  ('6000', 'unknown'), (float('inf'), 'unknown')]:
            self.assertEqual(classify([{'price_yen': price}], HOTEL)[0], category, price)
        self.assertEqual(classify([{'discount_price_yen': 5000, 'price_min': 5000}], HOTEL), ('unknown', None))

    def test_not_stated_as_hotel_is_always_cafe(self):
        for price in (1, 6000, 6001, 10000, 30000, None):
            self.assertEqual(classify([{'price_yen': price}], {'name': 'パーク ハイアット 東京 / ピーク ラウンジ'})[0], 'cafe')
            self.assertEqual(classify([{'price_yen': price}])[0], 'cafe')
        self.assertEqual(classify([{'price_yen': 12000}], {'name': 'X', 'category': 'lux', 'facility_type': 'hotel',
                                                             'facility_source': 'old evidence'})[0], 'cafe')

    def test_hotel_is_stated_by_name_address_or_recorded_hotel_name(self):
        cases = [({'name': '京王プラザホテル / 樹林'}, 'name'), ({'name': 'SHIBUYA STREAM HOTEL / Bar'}, 'name'),
                 ({'name': 'Lounge', 'address': '東京都港区 ホテルオークラ東京 1F'}, 'address'),
                 ({'name': 'オリエンタルラウンジ', 'hotel_name': 'マンダリン オリエンタル 東京'}, 'hotel_name'),
                 ({'name': 'ラウンジ', 'hotel_name': '未確認'}, None), ({'name': 'ラウンジ', 'hotel_name': ' '}, None),
                 ({'name': 'cafe VAVA'}, None), ({}, None), (None, None)]
        for (shop, basis) in cases:
            self.assertEqual(hotel_basis(shop), basis, shop)

    def test_minimum_ignores_outside_plans(self):
        data = fixture('cafe')
        shop = data['shops'][0]
        shop['name'] = HOTEL['name']
        shop['plans'] = [{'price_yen': 10000}, {'price_yen': 7000}, {'price_yen': 1000, 'end': '2026-11-06'},
                         {'price_yen': 500, 'start': '2026-12-18'}]
        before = copy.deepcopy(data)
        enriched = enrich(data, {'areas': []})
        self.assertEqual(data, before)
        self.assertEqual(enriched['shops'][0]['category'], 'lux')
        self.assertEqual(enriched['shops'][0]['category_price_yen'], 7000)
        self.assertIn('class="stat s-lux"><b>1</b>', render(data))
        self.assertEqual(enrich(enriched, {'areas': []}), enriched)

    def test_discount_does_not_lower_category(self):
        data = fixture()
        data['shops'][0]['name'] = HOTEL['name']
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

    def test_json_and_html_agree_for_each_category(self):
        for (shop, price, expected) in [({'name': 'TEST cafe'}, 9000, 'cafe'), (HOTEL, 6000, 'hotel'),
                                        (HOTEL, 6001, 'lux'), (HOTEL, None, 'unknown'),
                                        ({'name': 'TEST cafe'}, None, 'cafe')]:
            data = fixture()
            data['shops'][0].update(shop)
            data['shops'][0]['plans'][0]['price_yen'] = price
            enriched = enrich(data)
            self.assertEqual(enriched['shops'][0]['category'], expected)
            self.assertEqual(enriched['shops'][0]['category_price_yen'], price)
            self.assertEqual(enrich(enriched), enriched)
            self.assertIn('class="card c-' + expected + '"', render(enriched))

    def test_named_hotels_with_unknown_prices_stay_unknown(self):
        data = fixture()
        base = data['shops'][0]
        data['shops'] = [{**base, 'name': name + ' / ' + lounge, 'hotel_name': name}
                         for (name, lounge) in [('マンダリン オリエンタル 東京', 'オリエンタルラウンジ'),
                                                ('パレスホテル東京', 'ザ パレス ラウンジ'),
                                                ('東京ドームホテル', 'アーティスト カフェ')]]
        result = enrich(data)
        for shop in result['shops']:
            self.assertEqual(shop['category'], 'unknown')
            self.assertIsNone(shop['category_price_yen'])
        html = render(result)
        self.assertEqual(html.count('料金 未確認'), 3)
        self.assertEqual(html.count('class="card c-unknown"'), 3)


if __name__ == '__main__':
    unittest.main()
