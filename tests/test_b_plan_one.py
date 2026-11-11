"""B案PR1: new list and retention, per-week robots cache and bounded text output.

Only local fixtures and mocked openers are used, including TableCheck rows 88–90.
"""
import copy
import datetime as dt
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import urlsplit
from afternoon_tea.__main__ import parser
from afternoon_tea.collection import reader as reader_module, weekly as collect
from afternoon_tea.collection.reader import Reader
from afternoon_tea.collection.transport import ReadOnlyTransport, ForbiddenOperation
from afternoon_tea.collection.browser import Guard
from afternoon_tea.processing.weekly import retain
from afternoon_tea.processing.enrichment import enrich
from afternoon_tea.build import build
from afternoon_tea.publication.renderer import render
from afternoon_tea.publication.site import validate_site, json_bytes
from tests.http_fixtures import Response
from tests.test_simple_weekly import Week, FakeReader
from tests.test_renderer import fixture

class RobotsCacheTests(Week):
    def open_pages(self, rules='User-agent: *\nAllow: /\n'):
        self.opened=[]
        def open_(request, timeout):
            url=request.full_url; self.opened.append(url)
            if url.endswith('/robots.txt'):
                if isinstance(rules,Exception):raise rules
                return Response(url,rules,'text/plain')
            return Response(url,'<p>アフタヌーンティー</p>')
        def factory(**options):
            reader=Reader(delay=0,**options)
            reader.transport.opener=Mock()
            reader.transport.opener.open.side_effect=open_
            return reader
        return factory

    def test_all_ninety_rows_get_robots_once_per_host_and_reset_next_week(self):
        factory=self.open_pages()
        for no in range(1,91):
            out=collect.fetch(no,reader_factory=factory)
            self.assertEqual(out['shop']['list_url'],self.url(no))
            self.assertEqual(out['detail_links'],[])
        robots=[url for url in self.opened if url.endswith('/robots.txt')]
        self.assertEqual(sorted(robots),sorted({'https://'+urlsplit(row['予約ページURL']).hostname+'/robots.txt' for row in self.rows}))
        self.assertEqual(self.state()['requests'],93)
        state_text=json.dumps(self.state(),ensure_ascii=False)
        self.assertNotIn(self.rows[0]['店名'],state_text)
        self.assertEqual(set(self.state()['robots']),{'restaurant.ikyu.com','tabelog.com','www.tablecheck.com'})
        collect.begin()
        collect.fetch(1,reader_factory=factory)
        self.assertEqual(self.opened.count('https://restaurant.ikyu.com/robots.txt'),2)

    def test_unknown_and_refused_robots_are_cached_without_retry(self):
        for code in (403,429,500):
            collect.begin()
            factory=self.open_pages(HTTPError('https://restaurant.ikyu.com/robots.txt',code,'test',{},None))
            for no in (1,2):
                with self.assertRaises(RuntimeError):collect.fetch(no,reader_factory=factory)
            self.assertEqual(self.opened,['https://restaurant.ikyu.com/robots.txt'])
            self.assertIsNone(self.state()['robots']['restaurant.ikyu.com'])

    def test_cached_rules_are_evaluated_per_url_not_as_a_host_allow_boolean(self):
        factory=self.open_pages('User-agent: *\nDisallow: '+urlsplit(self.url(1)).path+'\n')
        with self.assertRaisesRegex(RuntimeError,'robots'):collect.fetch(1,reader_factory=factory)
        collect.fetch(2,reader_factory=factory)
        self.assertEqual(self.opened,['https://restaurant.ikyu.com/robots.txt',self.url(2)])

    def test_comment_only_lines_do_not_split_the_user_agent_group(self):
        for comment in ('# private pages', '   # private pages', '\t# private pages'):
            collect.begin()
            rules = 'User-agent: *\n'+comment+'\nDisallow: '+urlsplit(self.url(1)).path+'\n'
            factory = self.open_pages(rules)
            with self.assertRaisesRegex(RuntimeError, 'robots'):
                collect.fetch(1, reader_factory=factory)
            self.assertEqual(self.opened, ['https://restaurant.ikyu.com/robots.txt'])
            collect.fetch(2, reader_factory=factory)
            self.assertNotIn(self.url(1), self.opened)
            self.assertEqual(self.opened.count('https://restaurant.ikyu.com/robots.txt'), 1)

    def test_rule_cache_restores_crawl_delay_and_drops_comments_and_sitemaps(self):
        rules='User-agent: *\nAllow: /\nCrawl-delay: 7\n# contact: not saved\nSitemap: https://example.test/sitemap.xml\n'
        factory=self.open_pages(rules)
        with patch.object(reader_module.time,'sleep'):
            collect.fetch(1,reader_factory=factory)
        restored=Reader(delay=0);restored.robots_cache=self.state()['robots']
        restored.transport.opener=Mock(side_effect=AssertionError('cached robots must not make a request'))
        self.assertTrue(restored.robots_allows(self.url(2),self.url(2)))
        self.assertEqual(restored.robots['restaurant.ikyu.com'].crawl_delay(reader_module.USER_AGENT),7)
        self.assertNotIn('contact',json.dumps(self.state()['robots']))
        self.assertNotIn('sitemap',json.dumps(self.state()['robots']))

class TableCheckListTests(unittest.TestCase):
    def test_rows_88_to_90_exact_get_allowed_but_following_pages_never_sent(self):
        rows=collect.candidates()
        endings=('/reserve/message','/reserve/landing','/reserve/experiences')
        for row,ending in zip(rows[-3:],endings):
            url=row['予約ページURL'];self.assertTrue(url.endswith(ending))
            transport=ReadOnlyTransport();transport.opener=Mock()
            transport.open(url,list_url=url)
            sent=transport.opener.open.call_args.args[0]
            self.assertEqual((sent.full_url,sent.method),(url,'GET'))
            for target in (url+'/next',url.rsplit('/',1)[0],url+'?date=20261116',url+'#next'):
                with self.assertRaises(ForbiddenOperation):transport.open(target,list_url=url)
            with self.assertRaises(ForbiddenOperation):transport.open(url,list_url=url,method='POST')
            self.assertEqual(transport.opener.open.call_count,1)
            self.assertEqual(collect._links(url,[url+'/next',url.rsplit('/',1)[0]],url),[])
            guard=Guard(url,url)
            self.assertTrue(guard.allow(url,'GET','document',True,True))
            self.assertFalse(guard.allow(url+'/next','GET','document',True,True))

class ExcerptTests(Week):
    def test_default_shows_only_at_context_and_full_flag_shows_all_without_a_second_read(self):
        text='NON_AT_START'+'x'*35000+'アフタヌーンティー 通常料金7000円 メニュー 苺'+'y'*35000+'NON_AT_END'
        FakeReader.pages[self.url(1)]='<p>'+text+'</p>'
        short=self.fetch(1)
        self.assertIn('アフタヌーンティー',short['text'])
        self.assertNotIn('NON_AT_START',short['text']);self.assertNotIn('NON_AT_END',short['text'])
        self.assertLessEqual(len(short['text']),collect.MAX_EXCERPT)
        self.assertEqual(short['full_text_chars'],len(text));self.assertTrue(short['truncated'])
        before=len(FakeReader.opened)
        full=self.fetch(1,full=True)
        self.assertEqual(full['text'],text);self.assertFalse(full['truncated'])
        self.assertEqual(len(FakeReader.opened)-before,1)
        self.assertTrue(parser().parse_args(['fetch','1','--full']).full)

    def test_no_at_word_is_empty_and_overlapping_windows_are_not_duplicated(self):
        self.assertEqual(collect.excerpt('regular lunch only'), '')
        text='Afternoon Tea / ハイティー / アフタヌーンティー'
        self.assertEqual(collect.excerpt(text),text)
        many=('x'*1700+'アフタヌーンティー')*20
        self.assertLessEqual(len(collect.excerpt(many)),collect.MAX_EXCERPT)

class URLRetentionTests(unittest.TestCase):
    def data(self):
        data=fixture();shop=data['shops'][0]
        shop.pop('id',None);shop.pop('checked_at',None)
        row=collect.candidates()[0]
        shop.update(list_url=row['予約ページURL'],area_no=int(row['エリア番号']))
        shop['plans'][0]['checked_at']=dt.datetime.now(dt.timezone.utc).isoformat()
        return data

    def test_exact_csv_url_is_only_shop_key_and_plan_name_is_only_plan_key(self):
        previous=self.data();current=copy.deepcopy(previous)
        previous['shops'][0].update(name='Old name',id='old-id')
        current['shops'][0].update(name='New name',id='new-id')
        current['shops'][0]['plans'][0]['price_yen']=7000
        out=retain(current,previous)
        self.assertEqual(len(out['shops']),1)
        self.assertEqual(out['shops'][0]['name'],'New name')
        self.assertEqual(len(out['shops'][0]['plans']),1)
        self.assertEqual(out['shops'][0]['plans'][0]['price_yen'],7000)
        current['shops'][0]['list_url']=current['shops'][0]['list_url'].rstrip('/')
        self.assertEqual(retain(current)['shops'],[])

    def test_current_96_shops_are_not_in_the_list_and_are_excluded_even_when_fresh(self):
        from afternoon_tea.common import ROOT
        saved=json.loads((ROOT/'site/research.json').read_text())
        self.assertEqual(len(saved['shops']),96)
        stamps=[dt.datetime.fromisoformat(p.get('checked_at',s['checked_at'])) for s in saved['shops'] for p in s['plans']]
        out=retain(saved,now=max(stamps)+dt.timedelta(days=1))
        self.assertEqual(out['shops'],[])
        self.assertNotIn('<article ',render(out))

    def test_new_format_one_shop_and_zero_shops_complete_current_pipeline(self):
        for count in (1,0):
            data=self.data(); data['shops']=data['shops'][:count]
            if count:data['shops'][0]['plans'][0]['cc']=None
            data=build(data)
            html=render(data)
            self.assertEqual(validate_site({'site/research.json':json_bytes(data),'site/index.html':html.encode()})['shops'],count)
            self.assertEqual(html.count('<article '),count)
            if count:
                self.assertNotIn('id',data['shops'][0]);self.assertNotIn('checked_at',data['shops'][0])

    def test_dates_preserved_for_carried_plans_and_outside_list_not_retained(self):
        old=self.data();now=dt.datetime.now(dt.timezone.utc)
        stamp=(now-dt.timedelta(days=13)).isoformat()
        old['shops'][0]['plans'][0]['checked_at']=stamp
        current=copy.deepcopy(old);current['shops']=[]
        out=retain(current,old,now=now)
        self.assertEqual(out['shops'][0]['plans'][0]['checked_at'],stamp)
        old['shops'][0]['list_url']='https://restaurant.ikyu.com/999999/'
        self.assertEqual(retain(current,old,now=now)['shops'],[])

class BudgetDefinitionTests(unittest.TestCase):
    def test_limits_have_one_definition_and_reader_and_begin_use_them(self):
        self.assertEqual((collect.RESEARCH_SECONDS,collect.MAX_REQUESTS,collect.SHOP_SECONDS,collect.INTERVAL),(1500,200,60,3))
        with patch.object(reader_module.time,'monotonic',return_value=100):
            reader=Reader()
            self.assertEqual((reader.deadline,reader.max_requests,reader.delay),(1600,200,3))

class TableCheckReportTests(Week):
    def test_tablecheck_without_shop_key_is_matched_only_by_exact_list_url(self):
        state=self.state()
        state['rows']={str(no):{'site':'TableCheck','outcome':'no_plan','browser':False} for no in (88,89)}
        research=json.loads((self.root/'site/research.json').read_text())
        research['shops']=[{'name':'ONE CONFIRMED','area_no':2,'list_url':self.url(88),'category':'unknown',
                            'plans':[{'plan_name':'AT','checked_at':dt.datetime.now(dt.timezone.utc).isoformat()}]}]
        text=collect.report(state,research,self.rows)
        self.assertIn('TableCheck 成功1・失敗1',text)
        self.assertNotIn(self.rows[88]['店名'],text)
