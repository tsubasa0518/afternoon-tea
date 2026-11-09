import base64
import copy
import datetime as dt
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from afternoon_tea.communication_audit import CommunicationAudit,identity
from afternoon_tea.research import Browser
from afternoon_tea.read_only import ForbiddenOperation
from afternoon_tea.list_research import reference,initialize,run,list_traversed,venue_key,link_identity
from afternoon_tea.research_evidence import save_document,restore_documents,text_of,validate_audit
from afternoon_tea.campaign_gate import publication_gate
from afternoon_tea.master import load_master

class FixedDateTime(dt.datetime):
    @classmethod
    def now(cls,tz=None):return cls(2026,11,9,7,17,tzinfo=dt.timezone(dt.timedelta(hours=9))).astimezone(tz) if tz else cls(2026,11,9,7,17)


def acquired(campaign,journal,subject,url,text,when='2026-11-09T07:17:00+09:00'):
    # Offline transport fixture: acquisition and normalized evidence are chained.
    original_datetime=dt.datetime
    class AcquisitionTime(original_datetime):
        @classmethod
        def now(cls,tz=None):
            stamp=original_datetime.fromisoformat(when)
            return stamp.astimezone(tz) if tz else stamp.replace(tzinfo=None)
    with patch('afternoon_tea.communication_audit.dt.datetime',AcquisitionTime):
        request=journal.begin(url,'GET');journal.finish(request,'http_success',http_status=200)
        event=journal.record('evidence',status='success',request_id=request,resource=identity(url),
                             subject_id=subject,page_sha256=hashlib.sha256(text.encode()).hexdigest(),
                             text_sha256=hashlib.sha256(text.encode()).hexdigest())
    key=save_document(campaign,subject,url,text,event['at'],event['page_sha256'],event['sha256'],hosts=['example.org'])
    campaign['audit_segments'][journal.run_id]=journal.snapshot()
    return {'url':url,'checked_at':event['at'],'basis':text,'document_id':key,'subject_id':subject}


@lru_cache(maxsize=1)
def _completed():
    state=initialize({'shops':[]},day=dt.date(2026,11,9));journal=CommunicationAudit('test-completed')
    proofs={}
    for i,(entity,group) in enumerate(state['entities'].items()):
        group['queue']=[]
        proofs[entity]=acquired(state,journal,entity,'https://example.org/venue/'+str(i),('TEST ONLY plan 8,500円' if i==0 else 'TEST ONLY venue '+str(i)))
    for row in state['rows']:row.update(status='reviewed',reviewed_sources=[proofs[row['entity_id']]])
    for area in [*load_master()['areas'],{'no':15,'stations':[]}]:
        no=area['no'];subject='area:'+str(no)
        proof=acquired(state,journal,subject,'https://example.org/area/'+str(no),'TEST ONLY area '+str(no))
        stations=area['stations'] if no!=15 else ['立川']
        station_records={}
        for i,station in enumerate(stations):
            source=acquired(state,journal,subject+':station:'+station,'https://example.org/area/'+str(no)+'/station/'+str(i),'TEST ONLY '+station)
            station_records[station]={'reviewed_sources':[source]}
        state['discovery'].append({'area_no':no,'stations':area['stations'],'places':stations if no==15 else [],
                                   'status':'reviewed','reviewed_sources':[proof],'station_evidence':station_records})
    state.update(phase='complete',publication_ready=True)
    return state


def completed_campaign():return copy.deepcopy(_completed())


class FakeBrowser(Browser):
    def __init__(self,pages=None,fail=None,max_requests=150):
        super().__init__(delay=0,max_requests=max_requests)
        self.pages=pages or {};self.fail=fail;self.visited=[]
    def fetch(self,url):
        if self.count>=self.max_requests:raise RuntimeError('request_budget_exhausted')
        self.count+=1;self.visited.append(url)
        if self.fail:raise self.fail
        raw=self.pages.get(url,'<title>AT</title><p>TEST ONLY afternoon tea</p>')
        request=self.communication_audit.begin(url,'GET')
        self.communication_audit.finish(request,'http_success',http_status=200)
        self.last_document=self.communication_audit.record('document',status='success',request_id=request,
            resource=identity(url),page_sha256=hashlib.sha256(raw.encode()).hexdigest())
        return raw


class CampaignTests(unittest.TestCase):
    def setUp(self):
        p=patch('afternoon_tea.campaign_gate.current_day',return_value=dt.date(2026,11,9));p.start();self.addCleanup(p.stop)
    def test_original_and_resume_identity(self):
        rows,_=reference();state=initialize({},day=dt.date(2026,11,9))
        self.assertEqual(len(rows),385);self.assertEqual(state['rows'][0]['original'],rows[0])
        self.assertIs(initialize({},state,day=dt.date(2026,11,10)),state)
        bad=copy.deepcopy(state);bad['rows'].pop()
        with self.assertRaises(ValueError):initialize({},bad)
    def test_unfinished_campaign_survives_weeks_but_completed_campaign_refreshes(self):
        state=completed_campaign();state['phase']='list';state['rows'][-1]['status']='unresearched'
        resumed=initialize({},state,day=dt.date(2026,11,16))
        self.assertIs(resumed,state);self.assertEqual(resumed['rows'][0]['status'],'reviewed')
        self.assertEqual(sum(r['status']=='unresearched' for r in resumed['rows']),1)
        done=completed_campaign();fresh=initialize({},done,day=dt.date(2026,11,16))
        self.assertTrue(all(r['status']=='unresearched' for r in fresh['rows']))
        self.assertTrue(fresh['history'])
    def test_legacy_stop_survives_migration_without_fetch(self):
        state=initialize({});state['version']=1;state['rows'][0]['status']='interrupted'
        migrated=initialize({},state)
        with tempfile.TemporaryDirectory() as tmp:
            browser=FakeBrowser();run(migrated,tmp,browser)
            self.assertFalse(browser.visited)
            self.assertEqual(migrated['rows'][0]['status'],'interrupted')
    def test_collection_stop_is_global_and_durable(self):
        state=initialize({})
        with tempfile.TemporaryDirectory() as tmp:
            browser=FakeBrowser(fail=ForbiddenOperation('redirect_blocked_before_follow'))
            run(state,tmp,browser)
            self.assertEqual(len(browser.visited),1);self.assertEqual(state['rows'][0]['status'],'interrupted')
            self.assertEqual(state['rows'][1]['status'],'unresearched')
            self.assertTrue(any(e.get('violation') for e in browser.communication_audit.events))
    def test_store_scope_and_fresh_checkout_restore(self):
        state=initialize({});url=state['rows'][0]['original']['予約ページURL']
        with tempfile.TemporaryDirectory() as first,tempfile.TemporaryDirectory() as second:
            browser=FakeBrowser({url:'<p>TEST ONLY tea</p><a href="/area/tokyo/">レストラン</a><a href="/100000/">Afternoon tea</a>'})
            run(state,first,browser,limit=1)
            self.assertEqual(browser.visited,[url]);self.assertEqual(state['rows'][0]['status'],'awaiting_review')
            restored=json.loads((Path(first)/'checkpoint.json').read_text())
            no_network=FakeBrowser();run(restored,second,no_network,limit=0)
            self.assertFalse(no_network.visited)
            for key,document in restored['documents'].items():self.assertEqual((Path(second)/'documents'/(key+'.txt')).read_text(),text_of(document))
    def test_pending_plan_resumes_without_refetching_store(self):
        state=initialize({});url=state['rows'][0]['original']['予約ページURL'];plan=url+'plan123'
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
            browser=FakeBrowser({url:'<p>TEST tea</p><a href="'+plan+'">アフタヌーンティー</a>'},max_requests=1)
            run(state,a,browser,limit=1)
            self.assertEqual(state['rows'][0]['status'],'needs_collection')
            resumed=json.loads((Path(a)/'checkpoint.json').read_text());next_browser=FakeBrowser()
            run(resumed,b,next_browser,limit=1)
            self.assertEqual(next_browser.visited,[plan]);self.assertEqual(resumed['rows'][0]['status'],'awaiting_review')
    def test_service_identity_matching_and_duplicate_collection(self):
        url='https://restaurant.ikyu.com/107408/'
        self.assertEqual(venue_key(url),venue_key(url+'plan123'))
        state=initialize({'shops':[{'id':'known','source_url':url+'plan123'}]})
        self.assertEqual(state['rows'][0]['matched_shop_id'],'known')
        # Two rows identified with this service venue collect only one URL.
        entity=state['rows'][0]['entity_id'];group=state['entities'][entity]
        state['rows'][1]['entity_id']=entity;group['rows'].append(2)
        old_entity=next(k for k,v in state['entities'].items() if 2 in v['rows'] and k!=entity)
        del state['entities'][old_entity]
        with tempfile.TemporaryDirectory() as tmp:
            browser=FakeBrowser();run(state,tmp,browser,limit=1)
            self.assertEqual(browser.visited,[url]);self.assertEqual(state['rows'][1]['status'],'awaiting_review')
    def test_initial_url_rejection_is_audited_without_fetch(self):
        state=initialize({})
        for entity in list(state['entities']):
            if 378 not in state['entities'][entity]['rows']:state['entities'][entity]['queue']=[]
        with tempfile.TemporaryDirectory() as tmp:
            browser=FakeBrowser();run(state,tmp,browser,limit=1)
            self.assertFalse(browser.visited);self.assertEqual(state['rows'][377]['status'],'interrupted')
            self.assertTrue(any(e.get('violation') for e in browser.communication_audit.events))
    def test_multiday_evidence_and_stale_or_future_refusal(self):
        state=completed_campaign()
        journal=CommunicationAudit('second-day')
        subject=state['rows'][0]['entity_id']
        new=acquired(state,journal,subject,'https://example.org/new-day','TEST ONLY day 10',when='2026-11-10T07:17:00+09:00')
        state['rows'][0]['reviewed_sources']=[new]
        # A mixture of day 9 and day 10 observations supports day 10 publication.
        with patch('afternoon_tea.campaign_gate.current_day',return_value=dt.date(2026,11,10)):
            publication_gate({'period':{'start':'2026-11-10'}},{'research_campaign':state})
        with patch('afternoon_tea.campaign_gate.current_day',return_value=dt.date(2026,11,24)):
            with self.assertRaisesRegex(ValueError,'evidence_stale_or_future'):
                publication_gate({'period':{'start':'2026-11-24'}},{'research_campaign':state})
    def test_gate_rejects_wrong_subject_url_missing_text_and_failed_audit(self):
        complete=completed_campaign();publication_gate({'period':{'start':'2026-11-09'}},{'research_campaign':complete})
        changes=[lambda x:x['rows'][0].update(status='interrupted'),
                 lambda x:x['rows'][0].update(reviewed_sources=x['rows'][1]['reviewed_sources']),
                 lambda x:x['rows'][0]['reviewed_sources'][0].update(url='https://example.org/wrong'),
                 lambda x:x['rows'][0]['reviewed_sources'][0].update(basis='NOT IN DOCUMENT'),
                 lambda x:x['documents'].clear(),lambda x:x['discovery'].pop(),
                 lambda x:x['discovery'][0]['station_evidence'].clear(),
                 lambda x:next(iter(x['audit_segments'].values())).update(complete=False),
                 lambda x:next(iter(x['audit_segments'].values()))['events'][1].update(method='POST'),
                 lambda x:x.update(publication_ready=False)]
        for change in changes:
            state=copy.deepcopy(complete);change(state)
            with self.assertRaises(ValueError):publication_gate({'period':{'start':'2026-11-09'}},{'research_campaign':state})
    def test_unbound_or_changed_plan_is_rejected(self):
        state=completed_campaign();subject=state['rows'][0]['entity_id'];source=state['rows'][0]['reviewed_sources'][0]
        plan={'plan_name':'TEST ONLY plan','price_yen':8500,'source_url':source['url'],'checked_at':source['checked_at'],'research_evidence':[dict(source,verified_fields={'plan_name':'TEST ONLY plan','price_yen':8500})]}
        research={'period':{'start':'2026-11-09'},'shops':[{'research_entity_id':subject,'plans':[plan]}]}
        publication_gate(research,{'research_campaign':state})
        plan['price_yen']=9999
        with self.assertRaisesRegex(ValueError,'plan_field_evidence_missing'):publication_gate(research,{'research_campaign':state})
    def test_traversal_is_not_publication(self):
        state=completed_campaign();state['rows'][0]['status']='access_restricted'
        self.assertTrue(list_traversed(state))
        with self.assertRaises(ValueError):publication_gate({'period':{'start':'2026-11-09'}},{'research_campaign':state})
    def test_old_period_rejected(self):
        with self.assertRaisesRegex(ValueError,'campaign_not_current_week'):
            publication_gate({'period':{'start':'2020-01-06'}},{'research_campaign':completed_campaign()})
    def test_retained_snapshot_is_exact(self):
        from afternoon_tea.campaign_gate import retained_snapshot
        a=b'{"shops":[]}';b=b'{"failures":[]}'
        with patch('afternoon_tea.campaign_gate.RETAINED_SNAPSHOT',{'research.json':hashlib.sha256(a).hexdigest(),'search_failures.json':hashlib.sha256(b).hexdigest()}):
            self.assertTrue(retained_snapshot(a,b));self.assertFalse(retained_snapshot(a+b' ',b))
    def test_archive_tampering_and_decompression_limit(self):
        state=completed_campaign();document=next(iter(state['documents'].values()))
        document['text_zlib']=base64.b64encode(b'bad zlib').decode()
        with self.assertRaises(ValueError):text_of(document)

    def test_digest_digits_are_not_mistaken_for_cards_but_real_cards_are_rejected(self):
        from afternoon_tea.routine_site import scan
        scan(json.dumps({'sha256':'a'*20+'4111111111111111'+'b'*28}).encode())
        with self.assertRaises(ValueError):scan(b'"card": "4111 1111 1111 1111"')

    def test_stale_rows_are_queued_after_untouched_rows_without_losing_progress(self):
        state=completed_campaign();state['phase']='list';state['rows'][-1]['status']='unresearched'
        resumed=initialize({},state,day=dt.date(2026,11,24))
        self.assertEqual(resumed['rows'][0]['status'],'needs_refresh')
        self.assertEqual(resumed['rows'][-1]['status'],'unresearched')
        self.assertTrue(resumed['entities'][resumed['rows'][0]['entity_id']]['queue'])
    def test_cross_site_identity_requires_acquired_name_and_address(self):
        state=initialize({});a=state['rows'][0]['entity_id'];b=state['rows'][1]['entity_id']
        journal=CommunicationAudit('identity')
        proofs=[acquired(state,journal,subject,'https://example.org/identity/'+str(i),'TEST SAME LOUNGE 東京1-2-3') for i,subject in enumerate([a,b])]
        for proof in proofs:proof.update(verified_name='TEST SAME LOUNGE',verified_address='東京1-2-3')
        bad=copy.deepcopy(proofs);bad[1]['verified_name']='OTHER LOUNGE'
        with self.assertRaises(ValueError):link_identity(state,1,2,bad)
        link_identity(state,1,2,proofs)
        self.assertEqual(state['entities'][b]['collection_alias'],a)
    def test_plain_text_is_scanned_before_compression(self):
        state=initialize({});journal=CommunicationAudit('private')
        with self.assertRaises(ValueError):acquired(state,journal,state['rows'][0]['entity_id'],'https://example.org/private','person@example.test')

    def test_collector_evidence_is_bound_to_original_download_and_audit(self):
        from afternoon_tea.research_evidence import source_document
        state=initialize({})
        with tempfile.TemporaryDirectory() as tmp:
            browser=FakeBrowser();run(state,tmp,browser,limit=1)
            key=next(iter(state['documents']));document=state['documents'][key]
            proof={k:document[k] for k in ('url','checked_at')}
            proof.update(document_id=key,basis='TEST ONLY afternoon tea')
            audit=validate_audit(state['audit_segments'][browser.communication_audit.run_id])
            self.assertIn('TEST ONLY',source_document(state,proof,document['subject_id'],audit))
    def test_changed_verified_fields_cannot_invent_a_price_in_the_document(self):
        state=completed_campaign();source=copy.deepcopy(state['rows'][0]['reviewed_sources'][0]);source['verified_fields']={'plan_name':'TEST ONLY plan','price_yen':9999}
        plan={'plan_name':'TEST ONLY plan','price_yen':9999,'source_url':source['url'],'checked_at':source['checked_at'],'research_evidence':[source]}
        with self.assertRaisesRegex(ValueError,'plan_field_evidence_missing'):
            publication_gate({'period':{'start':'2026-11-09'},'shops':[{'research_entity_id':state['rows'][0]['entity_id'],'plans':[plan]}]}, {'research_campaign':state})

    def test_completed_same_cycle_is_a_noop_not_a_review_reset(self):
        state=completed_campaign()
        with tempfile.TemporaryDirectory() as tmp:
            browser=FakeBrowser();run(state,tmp,browser)
            self.assertFalse(browser.visited)
            self.assertEqual(state['phase'],'complete');self.assertTrue(state['publication_ready'])

    def test_private_document_failure_is_checkpointed_and_not_retried(self):
        state=initialize({});url=state['rows'][0]['original']['予約ページURL']
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
            browser=FakeBrowser({url:'<p>person@example.test</p>'})
            with self.assertRaises(ValueError):run(state,a,browser,limit=1)
            saved=json.loads((Path(a)/'checkpoint.json').read_text())
            self.assertEqual(saved['stop_reason'],'evidence_or_storage_error')
            self.assertFalse(saved['documents'])
            self.assertNotIn('person@example.test',(Path(a)/'checkpoint.json').read_text())
            next_browser=FakeBrowser();run(saved,b,next_browser,limit=1)
            self.assertFalse(next_browser.visited)

    def test_transient_connection_failure_does_not_disable_campaign(self):
        state=initialize({});first=state['rows'][0]['original']['予約ページURL']
        class TransientBrowser(FakeBrowser):
            def fetch(self,url):
                if url==first:
                    self.count+=1;self.visited.append(url)
                    request=self.communication_audit.begin(url,'GET')
                    self.communication_audit.finish(request,'http_failed',reason='URLError')
                    raise OSError('temporary connection failure')
                return super().fetch(url)
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
            browser=TransientBrowser();run(state,a,browser,limit=2)
            self.assertEqual(state['rows'][0]['status'],'needs_collection')
            self.assertEqual(state['rows'][1]['status'],'awaiting_review')
            self.assertNotEqual(state.get('stop_reason'),'evidence_or_storage_error')
            restored=json.loads((Path(a)/'checkpoint.json').read_text())
            retry=FakeBrowser();run(restored,b,retry,limit=1)
            self.assertEqual(retry.visited,[first]);self.assertEqual(restored['rows'][0]['status'],'awaiting_review')
    def test_linking_reviewed_entities_keeps_their_original_evidence_valid(self):
        state=completed_campaign();a=state['rows'][0]['entity_id'];b=state['rows'][1]['entity_id']
        journal=CommunicationAudit('reviewed-identity')
        proofs=[acquired(state,journal,subject,'https://example.org/reviewed-identity/'+str(i),'TEST SAME LOUNGE 東京1-2-3') for i,subject in enumerate([a,b])]
        for proof in proofs:proof.update(verified_name='TEST SAME LOUNGE',verified_address='東京1-2-3')
        old_proof=copy.deepcopy(state['rows'][1]['reviewed_sources'])
        link_identity(state,1,2,proofs)
        self.assertEqual(state['rows'][1]['reviewed_sources'],old_proof)
        publication_gate({'period':{'start':'2026-11-09'}},{'research_campaign':state})
