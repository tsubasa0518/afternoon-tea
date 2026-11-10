"""Current enrichment and delivery regression cases with fixed offline inputs."""
import copy,json,tempfile,unittest
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch
from afternoon_tea import routine_enrichment as e, routine_renderer as renderer
from afternoon_tea.master import ROOT
from afternoon_tea.routine_site import intake,validate_site,json_bytes
from tests.test_routine_site import FakeAPI
from tests.test_routine_renderer import fixture,FAILURES

def read(path):return json.loads(Path(path).read_text())
STAMP='2026-11-07T17:50:14+09:00'
URL='https://restaurant.ikyu.com/123456/plan123456'

class EnrichmentTests(unittest.TestCase):
    def shop(self):return {'source_url':URL,'checked_at':STAMP}
    def test_weekday_christmas_and_menu_tags_preserve_original_quotes(self):
        p={'plan_name':'TEST ONLY クリスマスAT（平日）','menu':'スコーン・マカロン・苺・栗・かぼちゃ','evidence_quote':'Christmas afternoon tea'}
        result=e.enrich_plan(p,self.shop())
        self.assertTrue(result['weekday_available']);self.assertFalse(result['weekend_available'])
        self.assertEqual(result['season'],['xmas'])
        self.assertEqual(result['sweets'],['ichigo','imo','kuri','macaron','scone'])
        self.assertEqual(result['menu'],p['menu']);self.assertEqual(result['structured_evidence']['sweets']['url'],URL)
    def test_null_and_mixed_optional_tags_never_stop_html_generation(self):
        for existing in (None, [], [None, 1, 'scone'], 'scone'):
            plan={'plan_name':'TEST ONLY クリスマスAT（平日）','menu':'マカロン',
                  'sweets':existing,'season':None,'structured_evidence':None}
            result=e.enrich_plan(plan,self.shop())
            self.assertIn('macaron',result['sweets']);self.assertEqual(result['season'],['xmas'])
            self.assertTrue(result['weekday_available'])
            d=fixture();d['shops'][0]['plans']=[result]
            self.assertIn('マカロン',renderer.render(d,FAILURES))
    def test_unknown_and_negated_text_do_not_invent_availability_or_tags(self):
        for p in ({'plan_name':'TEST ONLY AT'},{'plan_name':'平日限定ではありません'},{'menu':'マカロンは含まれません'}):
            result=e.enrich_plan(p,self.shop())
            self.assertNotIn('weekday_available',result);self.assertEqual(result['sweets'],[])
    def test_weekend_and_every_day_conditions(self):
        for title,wd,we in [('土日祝限定',False,True),('全日提供',True,True),('平日限定 土日祝限定',None,None)]:
            result=e.enrich_plan({'plan_name':title},self.shop())
            self.assertEqual(result.get('weekday_available'),wd);self.assertEqual(result.get('weekend_available'),we)
    def test_regular_and_discount_prices_are_separate_and_idempotent(self):
        p={'price_yen':7200,'price_note':'税サ込（通常9,200円）。','evidence_quote':'最大21%OFF 9,200円 税サ込7,200円'}
        result=e.enrich_plan(p,self.shop())
        self.assertEqual(result['price_yen'],9200);self.assertEqual(result['discount_price_yen'],7200)
        self.assertEqual(e.enrich_plan(result,self.shop()),result)
    def test_discount_only_does_not_reverse_calculate_regular_price(self):
        p={'price_yen':6000,'evidence_quote':'20%OFF 税サ込6,000円'}
        result=e.enrich_plan(p,self.shop())
        self.assertIsNone(result['price_yen']);self.assertNotIn('discount_price_yen',result)
        self.assertEqual(e.enrich_plan(result,self.shop()),result)
    def test_master_facility_classifies_unknown_price_with_exact_identity(self):
        master=read(ROOT/'data/store_master.json');source=master['areas'][0]['cats']['cafe']['shops'][0]
        d={'period':{'start':'2026-11-07','end':'2026-12-17'},'shops':[{'id':source['id'],'name':source['name'],'plans':[]}, {'id':source['id'],'name':'OTHER LOUNGE','plans':[]}]}
        result=e.enrich(d,master)
        self.assertEqual(result['shops'][0]['category'],'cafe')
        self.assertEqual(result['shops'][1]['category'],'unknown')
    def test_current_six_records_and_rendered_filters_are_fixed_without_new_confirmation(self):
        d=read(ROOT/'tests/fixtures/post26_six.json');master=read(ROOT/'data/store_master.json');result=e.enrich(d,master)
        self.assertEqual(e.enrich(result,master),result)
        self.assertEqual([s['checked_at'] for s in result['shops']],[s['checked_at'] for s in d['shops']])
        self.assertEqual(Counter(s['category'] for s in result['shops']),{'cafe':1,'hotel':5})
        self.assertTrue(all(s['checked_at']==STAMP for s in d['shops']))
        html=renderer.render(d,read(ROOT/'site/search_failures.json'))
        self.assertNotIn('data-sw="xmas" aria-pressed=',html)
        self.assertIn('クリスマス',html)
        self.assertEqual(sum(p.get('weekday_available') is True for s in d['shops'] for p in s['plans']),3)
        self.assertEqual(next(s for s in d['shops'] if s['id']=='master-031')['plans'][0]['price_yen'],9200)
        self.assertEqual(next(s for s in d['shops'] if s['id']=='master-058')['plans'][0]['price_yen'],7345)
    def test_zero_and_two_shops_still_generate_valid_html(self):
        for count in (0,2):
            d=fixture();d['shops']=d['shops']*count;d=e.enrich(d,read(ROOT/'data/store_master.json'))
            html=renderer.render(d,FAILURES)
            self.assertEqual(html.count('<article '),count)
            self.assertEqual(validate_site({'site/index.html':html.encode(),'site/research.json':json_bytes(d),'site/search_failures.json':json_bytes(FAILURES)})['shops'],count)

class DispatchIdempotenceTests(unittest.TestCase):
    def test_open_then_edited_same_head_dispatches_exactly_once(self):
        api=FakeAPI();intake(api,26,'tsubasa0518');result=intake(api,26,'tsubasa0518')
        self.assertEqual(result['dispatch'],'already_requested')
        self.assertEqual(sum('/dispatches' in p for _,p,_ in api.calls),1)
        self.assertEqual(sum(m=='PUT' for m,_,_ in api.calls),1)
    def test_untrusted_comment_cannot_spoof_a_bot_receipt(self):
        api=FakeAPI();api.comments=[{'user':{'login':'intruder'},'body':'<!-- weekly-site-dispatch:'+'a'*40+' -->\nfake'}]
        self.assertEqual(intake(api,26,'tsubasa0518')['dispatch'],'requested')
    def test_existing_workflow_run_recovers_after_receipt_save_failure(self):
        api=FakeAPI();api.pr.update(merged=True,state='closed',merge_commit_sha='c'*40)
        api.runs=[{'head_sha':'c'*40,'event':'workflow_dispatch'}]
        self.assertEqual(intake(api,26,'tsubasa0518')['dispatch'],'already_requested')
        self.assertFalse(api.calls)
    def test_failed_dispatch_does_not_create_success_receipt_and_is_retryable(self):
        api=FakeAPI();original=api.call
        def fail(method,path,body):
            if path.endswith('/dispatches'):raise HTTPError('https://api.github.com',503,'TEST ONLY',{},None)
            return original(method,path,body)
        api.call=fail
        with self.assertRaises(HTTPError):intake(api,26,'tsubasa0518')
        self.assertEqual(api.comments,[])
        api.call=original
        self.assertEqual(intake(api,26,'tsubasa0518')['dispatch'],'requested')
