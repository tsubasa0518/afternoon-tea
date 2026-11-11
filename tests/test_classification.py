"""Categories by the lowest regular price: <=5000 cafe / 5001-8000 hotel / >=8001 lux."""
import copy
import unittest
from afternoon_tea.processing.classification import classify
from afternoon_tea.processing.enrichment import enrich
from afternoon_tea.publication.renderer import render
from tests.test_renderer import fixture


class PriceCategoryTests(unittest.TestCase):

    def test_boundaries_and_unknown_prices(self):
        for (price, category) in [(1, 'cafe'), (5000, 'cafe'), (5000.5, 'hotel'), (5001, 'hotel'), (8000, 'hotel'),
                                  (8000.5, 'lux'), (8001, 'lux'), (30000, 'lux'),
                                  (None, 'unknown'), (True, 'unknown'), (0, 'unknown'), (-1, 'unknown'),
                                  ('5000', 'unknown'), (float('inf'), 'unknown')]:
            self.assertEqual(classify([{'price_yen': price}])[0], category, price)
        self.assertEqual(classify([{'discount_price_yen': 5000, 'price_min': 5000}]), ('unknown', None))

    def test_venue_name_and_old_categories_do_not_matter(self):
        for shop in ({'name': 'アマン東京 / ザ・ラウンジ by アマン'}, {'name': 'TEST ホテル', 'hotel_name': 'TEST ホテル'},
                     {'name': 'cafe', 'category': 'cafe', 'facility_type': 'hotel', 'facility_source': 'old'}):
            self.assertEqual(classify([{'price_yen': 13000}], shop), ('lux', 13000))
            self.assertEqual(classify([{'price_yen': 4950}], shop), ('cafe', 4950))
            self.assertEqual(classify([], shop), ('unknown', None))

    def test_minimum_ignores_outside_plans(self):
        data = fixture('cafe')
        shop = data['shops'][0]
        shop['plans'] = [{'price_yen': 10000}, {'price_yen': 7000}, {'price_yen': 1000, 'end': '2026-11-06'},
                         {'price_yen': 500, 'start': '2026-12-18'}]
        before = copy.deepcopy(data)
        enriched = enrich(data, {'areas': []})
        self.assertEqual(data, before)
        self.assertEqual(enriched['shops'][0]['category'], 'hotel')
        self.assertEqual(enriched['shops'][0]['category_price_yen'], 7000)
        self.assertIn('class="stat s-hotel"><b>1</b>', render(enriched))
        self.assertEqual(enrich(enriched, {'areas': []}), enriched)

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


if __name__ == '__main__':
    unittest.main()
