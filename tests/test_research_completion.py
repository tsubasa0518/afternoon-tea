import copy,json,unittest
from afternoon_tea.research_completion import validate,week_key,required_tasks
from afternoon_tea.routine_site import ROOT
from tests.weekly_completion_fixture import fixture,seal,WEEK

class CompletionTests(unittest.TestCase):
    def valid(self,data=None):
        d,f,m,b=fixture() if data is None else data
        return validate(d,f,m,b,expected_week=WEEK)
    def mutate(self,change):
        d,f,m,b=fixture();change(d,f);seal(d,f)
        with self.assertRaises(ValueError):validate(d,f,m,b,expected_week=WEEK)
    def test_all_14_areas_all_stations_zero_discovery_pass(self):
        d,f,m,b=fixture();r=self.valid((d,f,m,b))
        self.assertEqual({t['area_no'] for t in required_tasks(m,b).values()},set(range(1,15)))
        self.assertEqual(r['new_shops'],0)
    def test_jst_week_is_monday_even_for_utc_sunday(self):
        self.assertEqual(week_key('2026-11-08T22:17:00+00:00'),WEEK)
        self.assertEqual(week_key('2026-11-12'),WEEK)
    def test_pr45_stopped_and_station_unstarted_fail(self):
        self.mutate(lambda d,f:f['research_execution'].update(tasks=[],stop_reasons=['ForbiddenOperation']))
    def test_missing_metadata_and_complete_flag_are_not_completion(self):
        d,f,m,b=fixture();d.pop('weekly_run');d['complete']=True
        with self.assertRaises(ValueError):validate(d,f,m,b)
    def test_every_unfinished_state_rejected(self):
        for state in ('not_started','running','access_restricted','failed','information_insufficient','interrupted'):
            self.mutate(lambda d,f:f['research_execution']['tasks'][0].update(state=state))
    def test_missing_required_station_or_prior_shop(self):
        self.mutate(lambda d,f:f['research_execution']['tasks'].pop())
        d,f,m,b=fixture();b['shops']=[{'id':'prior','name':'TEST ONLY shop','plans':[]}]
        d['weekly_run']['baseline_sha256']=__import__('afternoon_tea.research_completion',fromlist=['digest']).digest(b)
        seal(d,f)
        with self.assertRaises(ValueError):validate(d,f,m,b)
    def test_common_listing_does_not_complete_other_station(self):
        self.mutate(lambda d,f:f['research_execution']['tasks'][1].update(read_ids=['1']))
    def test_previous_run_week_and_receipt_dates_rejected(self):
        for key,value in [('run_id','old_run_1234567890'),('week_key','2026-11-02'),('checked_at','2026-11-02T07:18:00+09:00')]:
            self.mutate(lambda d,f:f['research_execution']['reads'][0].update({key:value}))
    def test_old_metrics_with_renamed_run_rejected(self):
        self.mutate(lambda d,f:f['research_execution']['metrics'].update(new_shops=10))
    def test_renamed_prior_collection_summary_is_rejected(self):
        self.mutate(lambda d,f:d.update(collection_summary={'run_id':d['weekly_run']['run_id'],'week_key':WEEK,'confirmed_shops':13,'confirmed_plans':23,'new_shops':10}))
    def test_invalid_types_duplicates_or_missing_proofs(self):
        for key,value in [('http_status',True),('excerpt',''),('document_sha256','bad'),('document_event_sha256','bad')]:
            self.mutate(lambda d,f:f['research_execution']['reads'][0].update({key:value}))
        self.mutate(lambda d,f:f['research_execution']['tasks'].append(copy.deepcopy(f['research_execution']['tasks'][0])))
    def test_audit_replayed_not_complete_boolean(self):
        self.mutate(lambda d,f:f['research_execution']['communication_audits'][0]['events'][1].update(method='POST'))
        self.mutate(lambda d,f:f['research_execution'].update(communication_audits=[]))
    def test_payload_digest_covers_exact_json(self):
        d,f,m,b=fixture();d['note']='changed after checkpoint'
        with self.assertRaises(ValueError):validate(d,f,m,b)
    def test_safe_independent_source_can_finish_after_one_url_failure(self):
        d,f,m,b=fixture();f['failures']=[{'status':'access_denied','reason':'TEST one provider denied, scoped independent source read succeeded'}]
        seal(d,f);self.assertEqual(self.valid((d,f,m,b))['research_completion'],'passed')
    def test_real_pr45_snapshot_is_not_a_complete_run(self):
        d=json.loads((ROOT/'site/research.json').read_text());f=json.loads((ROOT/'site/search_failures.json').read_text())
        m=json.loads((ROOT/'data/store_master.json').read_text())
        with self.assertRaises(ValueError):validate(d,f,m,d)
