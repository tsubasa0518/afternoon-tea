"""Regression cases for weekly price bands and independent plan evidence."""
import copy
import unittest
from afternoon_tea.price_category import classify
from afternoon_tea.routine_enrichment import enrich
from afternoon_tea.routine_renderer import render
from afternoon_tea.read_only import check_url, ForbiddenOperation
from tests.test_routine_renderer import fixture, FAILURES


class PriceCategoryTests(unittest.TestCase):
    def test_boundaries_and_unknowns(self):
        for price, category in [(1,'cafe'),(6000,'cafe'),(6001,'hotel'),(9999,'hotel'),(10000,'lux'),(None,'unknown'),(True,'unknown'),(0,'unknown'),(-1,'unknown'),('6000','unknown'),(float('inf'),'unknown')]:
            self.assertEqual(classify([{'price_yen':price}])[0], category)
        self.assertEqual(classify([{'discount_price_yen':5000,'price_min':5000}]),('unknown',None))

    def test_minimum_ignores_outside_plans_and_venue_type(self):
        data=fixture('cafe');shop=data['shops'][0]
        shop['plans']=[{'price_yen':10000},{'price_yen':7000}, {'price_yen':1000,'end':'2026-11-06'}, {'price_yen':500,'start':'2026-12-18'}]
        before=copy.deepcopy(data)
        enriched=enrich(data,{'areas':[]})
        self.assertEqual(data,before)
        self.assertEqual(enriched['shops'][0]['category'],'hotel')
        self.assertEqual(enriched['shops'][0]['category_price_yen'],7000)
        self.assertIn('class="stat s-hotel"><b>1</b>',render(data,FAILURES))
        self.assertEqual(enrich(enriched,{'areas':[]}),enriched)

    def test_discount_does_not_lower_category(self):
        data=fixture();data['shops'][0]['plans']=[{'price_yen':5000,'evidence_quote':'通常価格 10,000円 50%OFF 5,000円'}]
        shop=enrich(data,{'areas':[]})['shops'][0]
        self.assertEqual(shop['category'],'lux')
        self.assertEqual(shop['plans'][0]['discount_price_yen'],5000)
        data['shops'][0]['plans'][0]['evidence_quote']='50%OFF 5,000円'
        self.assertEqual(enrich(data,{'areas':[]})['shops'][0]['category'],'unknown')

    def test_plan_links_and_source_dates_and_official_site(self):
        data=fixture();shop=data['shops'][0]
        shop['source_url']='https://www.example.com/afternoon-tea/'
        shop['plans']=[{'plan_name':'First','source_url':'https://restaurant.ikyu.com/123456/plan111111','price_yen':5000,'checked_at':'2026-11-06T10:00:00+09:00'}, {'plan_name':'Second','source_url':'https://www.example.com/winter-tea/','price_yen':10000}]
        result=render(data,FAILURES)
        for value in ['プラン1／2','プラン2／2','https://www.example.com/winter-tea/','2026-11-06T10:00:00+09:00','提供期間 未確認','施設の種類ではなく価格帯']:
            self.assertIn(value,result)

    def test_explicit_public_hosts_keep_transport_prohibitions(self):
        host='www.example.com'
        for path in ['/afternoon-tea/','/robots.txt']:
            check_url('https://'+host+path,public_hosts=[host])
        for url in ['https://'+host+'/login','https://'+host+'/booking','https://'+host+'/tea?date=2026-11-07','https://'+host+'/tea#reserve','https://another.example.com/tea']:
            with self.assertRaises(ForbiddenOperation):check_url(url,public_hosts=[host])
        for host in ['ssl.tabelog.com','localhost','127.0.0.1','foo.local']:
            with self.assertRaises(ForbiddenOperation):check_url('https://'+host+'/tea',public_hosts=[host])
        with self.assertRaises(ForbiddenOperation):check_url('https://www.example.com/tea','POST',public_hosts=['www.example.com'])

    def test_public_source_still_requires_robots_and_stops_on_denial(self):
        from afternoon_tea.research import Browser
        from urllib.robotparser import RobotFileParser
        from urllib.error import HTTPError
        from unittest.mock import Mock
        host='www.example.com';url='https://'+host+'/afternoon-tea/'
        browser=Browser(delay=0,public_hosts=[host])
        robots=RobotFileParser();robots.parse(['User-agent: *','Disallow: /'])
        browser.robots[host]=robots;browser._open=Mock()
        with self.assertRaisesRegex(RuntimeError,'robots_'):browser.fetch(url)
        browser._open.assert_not_called()
        robots=RobotFileParser();robots.parse(['User-agent: *','Allow: /']);browser.robots[host]=robots
        browser._open.side_effect=HTTPError(url,403,'denied',{},None)
        with self.assertRaisesRegex(RuntimeError,'HTTP_403'):browser.fetch(url)
        with self.assertRaisesRegex(RuntimeError,'host_stopped'):browser.fetch(url)
        self.assertEqual(browser._open.call_count,1)

    def test_public_search_only_accepts_one_text_query(self):
        check_url('https://www.bing.com/search?q=Tokyo%20afternoon%20tea')
        check_url('https://www.bing.com/robots.txt')
        for url in ['https://www.bing.com/search?q=tea&date=20261107','https://www.bing.com/search?q=tea&q=hotel','https://www.bing.com/search?q=','https://www.bing.com/login','https://www.example.com/tea?q=tea']:
            with self.assertRaises(ForbiddenOperation):check_url(url)
