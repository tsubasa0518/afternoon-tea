"""Mock-only collection, structured evidence, and duplicate-publication regressions."""
import copy
from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from afternoon_tea import routine_collection as c, routine_enrichment as e, routine_renderer as renderer
from afternoon_tea.communication_audit import CommunicationAudit
from afternoon_tea.priority_research import prepare, read, ROOT
from afternoon_tea.routine_site import intake, validate_site, json_bytes
from afternoon_tea.read_only import ForbiddenOperation
from tests.test_routine_site import FakeAPI
from tests.test_routine_renderer import fixture, FAILURES

STAMP='2026-11-07T17:50:14+09:00'
URL='https://restaurant.ikyu.com/123456/plan123456'


def queue():
    return prepare(read(ROOT/'data/priority_sources.json'),read(ROOT/'data/store_master.json'),
                   read(ROOT/'data/priority_master_matches.json'),'test-only-run',STAMP)


class FakeBrowser:
    def __init__(self, pages=None, max_requests=300):
        self.count=0;self.max_requests=max_requests;self.pages=pages or {};self.urls=[]
        self.communication_audit=CommunicationAudit('test-only-run')
    def fetch(self,url):
        if self.count>=self.max_requests:raise RuntimeError('request_budget_exhausted')
        self.urls.append(url);self.count+=1
        key=self.communication_audit.begin(url,'GET')
        value=self.pages.get(url,'<html><h1>TEST ONLY public page</h1></html>')
        if isinstance(value,Exception):
            self.communication_audit.finish(key,'http_failed',reason=type(value).__name__)
            raise value
        self.communication_audit.finish(key,'http_success',http_status=200)
        return value


class CollectionTests(unittest.TestCase):
    def test_all_156_have_second_third_and_later_rounds_without_duplicates(self):
        items=list(c.rounds(queue()))
        self.assertEqual(len(items),156);self.assertEqual(len({t['id'] for _,_,t in items}),156)
        self.assertEqual([a['no'] for _,a,_ in items[:14]],list(range(1,15)))
        self.assertEqual(items[14][0],2);self.assertTrue(any(n==3 for n,_,_ in items))
    def test_collection_keeps_going_past_14_and_resumes_without_refetch(self):
        q=queue();browser=FakeBrowser()
        with tempfile.TemporaryDirectory() as tmp:
            state=c.run(q,tmp,browser,clock=lambda:0)
            self.assertEqual(len(state['documents']),156)
            self.assertGreaterEqual(state['last_round'],3)
            self.assertEqual(len(list(Path(tmp).glob('collected-area-*.json'))),14)
            self.assertEqual(len({d['queue_id'] for d in state['documents']}),156)
            follow=FakeBrowser();c.run(q,tmp,follow,clock=lambda:0)
            self.assertEqual(follow.urls,[])
            self.assertFalse(state['complete_research'])
    def test_discovery_executes_and_retains_candidates_without_confirming_them(self):
        html='<h1>銀座 アフタヌーンティー</h1><a href="/999991/">TEST ONLY 新規ホテルラウンジ</a>'
        browser=FakeBrowser({c.AREA_LIST:html})
        with tempfile.TemporaryDirectory() as tmp:
            state=c.run(queue(),tmp,browser,clock=lambda:0)
        self.assertEqual(browser.urls[0],c.AREA_LIST)
        self.assertEqual(state['new_url_candidates'][0]['status'],'unresearched')
        self.assertEqual(state['new_url_candidates'][0]['area_no'],2)
    def test_blocked_discovery_still_records_failure_and_shop_rounds_continue(self):
        browser=FakeBrowser({c.AREA_LIST:RuntimeError('robots_unknown_or_disallowed')})
        with tempfile.TemporaryDirectory() as tmp:
            state=c.run(queue(),tmp,browser,clock=lambda:0)
        self.assertEqual(state['discovery_pages'][0]['result'],'site_restriction')
        self.assertEqual(len(state['documents']),156)
    def test_request_limit_saves_partial_results_and_resume_pending_ids(self):
        q=queue()
        with tempfile.TemporaryDirectory() as tmp:
            state=c.run(q,tmp,FakeBrowser(max_requests=4),clock=lambda:0)
            self.assertEqual(state['stop_reason'],'request_budget');self.assertTrue(state['remaining_queue_ids'])
            first={d['queue_id'] for d in state['documents']}
            resumed=c.run(q,tmp,FakeBrowser(),clock=lambda:0)
            self.assertEqual(len({d['queue_id'] for d in resumed['documents']}),156)
            self.assertEqual(sum(d['queue_id'] in first for d in resumed['documents']),len(first))
    def test_time_budget_and_different_run_rejection(self):
        clock=iter([0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15])
        with tempfile.TemporaryDirectory() as tmp:
            state=c.run(queue(),tmp,FakeBrowser(),seconds=5,clock=lambda:next(clock))
            self.assertEqual(state['stop_reason'],'time_budget')
            q=queue();q['run_id']='different'
            with self.assertRaises(ValueError):c.run(q,tmp,FakeBrowser(),clock=lambda:0)
    def test_safety_error_is_not_swallowed_and_checkpoint_survives(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ForbiddenOperation):
                c.run(queue(),tmp,FakeBrowser({c.AREA_LIST:ForbiddenOperation('TEST ONLY stop')}),clock=lambda:0)
            self.assertEqual(read(Path(tmp)/'collection.json')['stop_reason'],'safety_or_program_error')
    def test_blocked_seed_never_goes_to_transport(self):
        browser=FakeBrowser()
        with tempfile.TemporaryDirectory() as tmp:
            state=c.run(queue(),tmp,browser,clock=lambda:0)
        self.assertFalse(any('ssl.tabelog.com' in u for u in browser.urls))
        row=next(d for d in state['documents'] if d['queue_id']=='priority-candidate-07')
        self.assertFalse(row['http_attempted']);self.assertEqual(row['result'],'source_needed')
        self.assertTrue(state['communication_audit']['complete'])
        self.assertTrue(all(e['method']=='GET' for e in state['communication_audit']['events'] if e['event']=='request'))

    def test_resumed_communication_summary_preserves_all_segment_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=c.run(queue(),tmp,FakeBrowser(max_requests=4),clock=lambda:0)
            second=c.run(queue(),tmp,FakeBrowser(),clock=lambda:0)
            self.assertEqual(len(second['communication_segments']),2)
            self.assertGreater(second['communication_summary']['requests'],second['requests_this_segment'])
            self.assertTrue(second['communication_summary']['complete'])


    def test_unexpected_exception_is_abnormal_not_a_fetch_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                c.run(queue(),tmp,FakeBrowser({c.AREA_LIST:RuntimeError('TEST ONLY program error')}),clock=lambda:0)
            saved=read(Path(tmp)/'collection.json')
            self.assertEqual(saved['stop_reason'],'safety_or_program_error')
            self.assertIsNone(saved['communication_summary']['operations_executed'])
    def test_prepare_does_not_overwrite_an_existing_collection(self):
        import subprocess
        (ROOT/'.staging').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'.staging') as tmp:
            path=Path(tmp);(path/'collection.json').write_text('{}');(path/'queue.json').write_text('TEST ONLY preserved')
            result=subprocess.run(['python3','-m','afternoon_tea.priority_research','prepare','--workdir',tmp],capture_output=True,text=True,cwd=ROOT)
            self.assertEqual(result.returncode,2)
            self.assertEqual((path/'queue.json').read_text(),'TEST ONLY preserved')
    def test_http_403_is_recorded_without_confirming_or_erasing_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            q=queue();url=q['areas'][0]['tasks'][0]['historical_url']
            state=c.run(q,tmp,FakeBrowser({url:RuntimeError('HTTP_403')}),clock=lambda:0)
            row=next(d for d in state['documents'] if d['queue_id']=='priority-002') if q['areas'][0]['tasks'][0]['id']=='priority-002' else next(d for d in state['documents'] if d['queue_id']==q['areas'][0]['tasks'][0]['id'])
            self.assertEqual(row['result'],'access_denied');self.assertTrue(row['http_attempted'])
            self.assertFalse(state['complete_research'])



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
        self.assertIn('data-sw="xmas" aria-pressed="false">クリスマス<span class="bc">3</span>',html)
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


class TeaAndHistoricalTests(unittest.TestCase):
    def test_tea_requires_at_menu_and_booking_and_dinner_still_fails(self):
        from afternoon_tea.extraction import extract
        base='<h1>TEST ONLY cafe</h1>ティー <h1>アフタヌーンティー</h1> 税サ込6,000円 メニュー スコーン プラン紹介 <button>このプランを予約する</button>'
        self.assertTrue(extract(base,URL,STAMP)['plans'][0]['eligible_document'])
        for raw in (base.replace('スコーン','内容未確認'),base.replace('<button>このプランを予約する</button>',''),base.replace('ティー <h1>','ディナー <h1>')):
            self.assertFalse(extract(raw,URL,STAMP)['plans'][0]['eligible_document'])
    def test_ikyu_displayed_regular_price_not_tax_inclusive_sale(self):
        from afternoon_tea.extraction import extract
        base='<h1>TEST ONLY cafe</h1>ティー <h1>アフタヌーンティー</h1> 最大21%OFF 9,200円 税サ込7,200円 メニュー スコーン プラン紹介 <button>このプランを予約する</button>'
        self.assertEqual(extract(base,URL,STAMP)['plans'][0]['plan']['price_min'],9200)
        self.assertIsNone(extract(base.replace('9,200円 ',''),URL,STAMP)['plans'][0]['plan']['price_min'])
    def test_historical_master_is_pinned_and_not_relabelled_as_current(self):
        from afternoon_tea.master import load_master,load_master_snapshot
        state=read(ROOT/'research_data/state.json')
        old=load_master_snapshot(state['master_sha256'])
        self.assertEqual(old['source_sha256'],state['master_sha256'])
        self.assertNotEqual(old['source_sha256'],load_master()['source_sha256'])
        self.assertEqual(old['areas'],load_master()['areas'])
        with self.assertRaises(ValueError):load_master_snapshot('../bad')
