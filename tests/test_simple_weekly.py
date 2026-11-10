"""Offline weekly behavior: no access to store or reservation servers."""
import copy
import datetime as dt
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.robotparser import RobotFileParser
from afternoon_tea.collection import weekly as collect
from afternoon_tea.collection.reader import Browser
from afternoon_tea.collection.transport import ForbiddenOperation, ReadOnlyTransport, NoRedirect
from afternoon_tea.processing.weekly import retain, validate_freshness, REMOVED
from afternoon_tea.publication.renderer import render
from afternoon_tea.publication.site import validate_site, json_bytes
from test_renderer import fixture
from test_site_intake import FakeAPI
from afternoon_tea.publication.site import intake

NOW = dt.datetime(2026,11,10,12,tzinfo=dt.timezone.utc)
URL = 'https://restaurant.ikyu.com/123456/'
URL2 = 'https://restaurant.ikyu.com/222222/'
TABEL = 'https://tabelog.com/tokyo/A1301/A130101/12345678/'
TABLE = 'https://www.tablecheck.com/ja/shops/test-only/reserve'

def row(no=1, url=URL):
    return {'No':str(no),'店名':'TEST '+str(no),'予約ページURL':url,'エリア番号':'1'}

def reviewed(r, text, url):
    if text == 'confirmed':
        return {'name':r['店名'],'plans':[{'plan_name':'AT','checked_at':NOW.isoformat()}]}

class FakeBrowser:
    def __init__(self, pages=None, max_requests=150):
        self.pages=pages or {}; self.count=0; self.max_requests=max_requests; self.urls=[]; self.blocked_hosts=set(); self.last_request={}
    def fetch(self, url):
        self.count+=1; self.urls.append(url)
        value=self.pages.get(url,'unknown')
        if isinstance(value,Exception):
            raise value
        return value

class OrderedCollectionTests(unittest.TestCase):
    def test_order_original_then_untried_services_stop_at_confirmation(self):
        browser=FakeBrowser({TABLE:'confirmed'})
        calls=[]
        def finder(b,r,host):
            calls.append(host)
            return [TABEL if host=='tabelog.com' else TABLE]
        result=collect.collect([row()],reviewed,browser,finder)
        self.assertEqual(browser.urls,[URL,TABEL,TABLE])
        self.assertEqual(calls,['tabelog.com','tablecheck.com'])
        self.assertEqual(len(result['shops']),1)
        self.assertEqual(result['shops'][0]['area_no'],1)
        browser=FakeBrowser({URL:'confirmed'})
        collect.collect([row()],reviewed,browser,Mock(side_effect=AssertionError('unneeded search')))
        self.assertEqual(browser.urls,[URL])

    def test_ikyu_first_when_original_is_tablecheck(self):
        browser=FakeBrowser({TABEL:'confirmed'})
        calls=[]
        def finder(b,r,host):
            calls.append(host); return [URL if host=='restaurant.ikyu.com' else TABEL]
        collect.collect([row(url=TABLE)],reviewed,browser,finder)
        self.assertEqual(browser.urls,[TABLE,URL,TABEL])
        self.assertEqual(calls,['restaurant.ikyu.com','tabelog.com'])

    def test_redirect_and_forbidden_store_do_not_stop_next_store(self):
        for bad in ('https://restaurant.ikyu.com/123456/confirm/', 'https://evil.invalid/'):
            b=FakeBrowser({URL2:'confirmed'})
            out=collect.collect([row(url=bad),row(2,URL2)],reviewed,b,lambda *a: [])
            self.assertEqual(b.urls,[URL2])
            self.assertEqual(out['blocked_requests'],1)
            self.assertEqual(out['abandoned'],1)
            self.assertEqual(out['shops'][0]['name'],'TEST 2')
        b=FakeBrowser({URL:ForbiddenOperation('redirect_blocked_before_follow'),URL2:'confirmed'})
        out=collect.collect([row(),row(2,URL2)],reviewed,b,lambda *a: [])
        self.assertEqual(out['shops'][0]['name'],'TEST 2')

    def test_post_never_sent_and_no_redirect_follow(self):
        t=ReadOnlyTransport();t.opener=Mock()
        with self.assertRaises(ForbiddenOperation):t.open(URL,method='POST')
        t.opener.open.assert_not_called()
        with self.assertRaises(ForbiddenOperation):
            NoRedirect().redirect_request(None,None,302,'',{},URL2)

    def test_every_invocation_starts_at_one_and_unconfirmed_not_rendered(self):
        for _ in range(2):
            b=FakeBrowser({URL2:'confirmed'})
            out=collect.collect([row(),row(2,URL2)],reviewed,b,lambda *a: [])
            self.assertEqual(b.urls,[URL,URL2])
            d=fixture();d['shops']=out['shops']
            self.assertNotIn('>TEST 1<',render(d))
            self.assertIn('TEST 2',render(d))

    def test_request_and_time_limit_publish_completed_subset(self):
        b=FakeBrowser({URL:'confirmed'},max_requests=1)
        out=collect.collect([row(),row(2,URL2)],reviewed,b,lambda *a: [])
        self.assertEqual(out['attempted'],1)
        times=iter([0,0,0,500])
        partial=collect.collect([row(),row(2,URL2)],reviewed,FakeBrowser({URL:'confirmed'}),lambda *a: [],clock=lambda:next(times,500))
        self.assertEqual(len(partial['shops']),1)
        d=fixture();d['shops']=out['shops']
        d['shops'][0]['plans'][0]['checked_at']=dt.datetime.now(dt.timezone.utc).isoformat()
        validate_site({'site/research.json':json_bytes(d),'site/index.html':render(d).encode()})

    def test_page_errors_skip_without_persisting_failure_names(self):
        for error in (ValueError('secret_or_personal_contact_detected'),RuntimeError('page_too_large'),RuntimeError('HTTP_403')):
            out=collect.collect([row(),row(2,URL2)],reviewed,FakeBrowser({URL:error,URL2:'confirmed'}),lambda *a: [])
            self.assertEqual([s['name'] for s in out['shops']],['TEST 2'])
            self.assertNotIn('TEST 1',json.dumps(out))

    def test_incomplete_store_is_not_adopted(self):
        pending=lambda *a: {'name':'TEST pending','plans':[{}],'pending_urls':[URL2]}
        out=collect.collect([row()],pending,FakeBrowser({URL:'confirmed'}),lambda *a: [])
        self.assertEqual(out['shops'],[])

class RetentionTests(unittest.TestCase):
    def sample(self, stamp):
        d=fixture();d['shops'][0]['plans'][0]['checked_at']=stamp
        return d
    def test_boundary_date_retention_and_no_redating(self):
        for age,keep in ((0,True),(14,True),(14.0001,False),(-0.001,False)):
            stamp=(NOW-dt.timedelta(days=age)).isoformat()
            source=self.sample(stamp);before=copy.deepcopy(source)
            out=retain(source,now=NOW)
            self.assertEqual(bool(out['shops']),keep)
            if keep:self.assertEqual(out['shops'][0]['plans'][0]['checked_at'],stamp)
            self.assertEqual(source,before)
    def test_missing_naive_future_and_stale_rejected(self):
        for stamp in (None,'invalid','2026-11-10T00:00:00',(NOW+dt.timedelta(seconds=1)).isoformat(),(NOW-dt.timedelta(days=15)).isoformat()):
            d=self.sample(stamp)
            self.assertEqual(retain(d,now=NOW)['shops'],[])
            with self.assertRaises(ValueError):validate_freshness(d,now=NOW)
    def test_previous_merged_current_overrides_same_plan_and_drops_old_fields(self):
        old=self.sample((NOW-dt.timedelta(days=1)).isoformat());old['research_campaign']={'secret':'not stored'}
        old['shops'][0]['plans'][0]['structured_evidence']={'anything':{}}
        new=self.sample(NOW.isoformat());new['shops'][0]['plans'][0]['price_yen']=7000
        out=retain(new,old,now=NOW)
        self.assertEqual(len(out['shops'][0]['plans']),1)
        self.assertEqual(out['shops'][0]['plans'][0]['price_yen'],7000)
        self.assertNotIn('research_campaign',out)
        self.assertNotIn('structured_evidence',out['shops'][0]['plans'][0])
    def test_old_shop_timestamp_is_used_only_when_plan_date_absent(self):
        d=self.sample(NOW.isoformat());shop=d['shops'][0];shop['checked_at']=NOW.isoformat()
        del shop['plans'][0]['checked_at']
        self.assertEqual(retain(d,now=NOW)['shops'][0]['plans'][0]['checked_at'],NOW.isoformat())
        shop['plans'][0]['checked_at']=None
        self.assertEqual(retain(d,now=NOW)['shops'],[])
    def test_area_outside_unknown_string_bool_are_filtered_before_html(self):
        for area in (15,16,0,None,'1',True):
            d=self.sample(NOW.isoformat());d['shops'][0]['area_no']=area
            self.assertEqual(retain(d,now=NOW)['shops'],[])
            self.assertNotIn('TEST ONLY lounge',render(d))
        html=render(self.sample(NOW.isoformat()))
        self.assertEqual(len(re.findall(r'class="area-btn"',html)),14)
        self.assertNotIn('その他のエリア',html)
    def test_empty_results_publish_and_bad_third_file_is_rejected(self):
        d=fixture();d['shops']=[];f={'site/research.json':json_bytes(d),'site/index.html':render(d).encode()}
        self.assertEqual(validate_site(f)['plans'],0)
        f['site/third.json']=b'{}'
        with self.assertRaises(ValueError):validate_site(f)
        api=FakeAPI();api.pr['changed_files']=3
        with self.assertRaises(ValueError):intake(api,1,'tsubasa0518')
        self.assertFalse(api.calls)
    def test_candidates_have_expected_count_order_and_fourteen_areas(self):
        rows=collect.candidates()
        self.assertEqual(len(rows),329)
        self.assertEqual({int(r['エリア番号']) for r in rows},set(range(1,15)))
        self.assertEqual([int(r['No']) for r in rows],list(range(1,len(rows)+1)))

class SharedBudgetTests(unittest.TestCase):
    def test_counts_and_time_are_shared_across_commands_without_bodies(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(collect,'BUDGET',Path(tmp)),patch.object(collect,'Browser',return_value=FakeBrowser({URL:'confirmed'})):
            collect.begin();collect.fetch(URL)
            state=json.loads((Path(tmp)/'limits.json').read_text())
            self.assertEqual(state['requests'],1)
            self.assertNotIn('text',state)
            state['requests']=150;(Path(tmp)/'limits.json').write_text(json.dumps(state))
            with self.assertRaisesRegex(RuntimeError,'research_budget_exhausted'):collect.fetch(URL)
            state.update(requests=0,started_at=0);(Path(tmp)/'limits.json').write_text(json.dumps(state))
            with self.assertRaisesRegex(RuntimeError,'research_budget_exhausted'):collect.fetch(URL)
    def test_begin_does_not_save_shop_progress(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(collect,'BUDGET',Path(tmp)):
            self.assertEqual(collect.begin()['starts_at_no'],1)
            self.assertEqual(set(json.loads((Path(tmp)/'limits.json').read_text())),{'started_at','requests','blocked_hosts','last_request'})
