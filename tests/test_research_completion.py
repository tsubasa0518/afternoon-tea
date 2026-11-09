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

class ReviewRegressionTests(unittest.TestCase):
    def existing(self):
        baseline={'schema_version':1,'generated_at':'2026-11-09T07:17:00+09:00',
                  'period':{'start':WEEK,'end':'2026-12-19'},
                  'shops':[{'id':'prior','name':'TEST ONLY shop','source_url':'https://official.example.com/tea',
                            'checked_at':'2026-11-08T10:00:00+09:00','plans':[
                                {'plan_name':'TEST ONLY afternoon tea','price_yen':6000,'menu':'TEST sweets',
                                 'checked_at':'2026-11-08T10:00:00+09:00'}]}]}
        return fixture(baseline=baseline)
    def test_unchanged_carried_plan_is_allowed(self):
        d,f,m,b=self.existing();self.assertEqual(validate(d,f,m,b)['confirmed_plans'],0)
    def test_existing_plan_source_facts_cannot_change_with_old_checked_at(self):
        for key,value in [('price_yen',5000),('menu','new unsupported menu'),('start','2026-11-10'),('description','new description')]:
            d,f,m,b=self.existing();d['shops'][0]['plans'][0][key]=value;seal(d,f)
            with self.assertRaisesRegex(ValueError,'unreceipted_plan_change'):validate(d,f,m,b)
    def test_new_plan_at_existing_shop_needs_receipt(self):
        d,f,m,b=self.existing();d['shops'][0]['plans'].append({'plan_name':'TEST new unverified plan','price_yen':5000})
        seal(d,f)
        with self.assertRaisesRegex(ValueError,'unreceipted_plan_change'):validate(d,f,m,b)
    def test_tuesday_resume_keeps_monday_week_and_real_generation_date(self):
        import datetime as dt
        d,f,m,b=fixture();d['generated_at']='2026-11-10T08:00:00+09:00'
        d['period']={'start':'2026-11-10','end':'2026-12-20'}
        d['weekly_run']['finished_at']='2026-11-10T08:00:00+09:00';seal(d,f)
        result=validate(d,f,m,b,now=dt.datetime.fromisoformat('2026-11-10T09:00:00+09:00'))
        self.assertEqual(result['week_key'],WEEK)
    def test_substantive_change_rejected_at_intake_and_deployment(self):
        from tests.test_routine_site import FakeAPI
        from tests.weekly_completion_fixture import files,BASE,HEAD
        from afternoon_tea.publication_completion import gate
        api=FakeAPI();d,f,m,b=self.existing();d['shops'][0]['plans'][0]['price_yen']=5000;seal(d,f)
        api.data,api.failures,api.master,api.baseline=d,f,m,b;api.content=files(d,f)
        for base in (BASE,None):
            with self.assertRaisesRegex(ValueError,'unreceipted_plan_change'):gate(api,HEAD,api.content,base)
    def test_new_plan_with_current_receipt_and_unknown_fields_is_allowed(self):
        d,f,m,b=self.existing();ex=f['research_execution']
        read=next(r for r in ex['reads'] if r.get('shop_id')=='prior')
        plan={'plan_name':'TEST ONLY shop アフタヌーンティー','price_yen':None,'menu':None,'start':None,'end':None,
              'checked_at':read['checked_at'],'source_url':read['url'],'evidence_quote':read['excerpt']}
        d['shops'][0]['plans'].append(plan)
        ex['verified_plans']=[{'shop_id':'prior','plan_name':plan['plan_name'],'read_id':read['id']}]
        ex['metrics']={'confirmed_shops':1,'confirmed_plans':1,'new_shops':0};seal(d,f)
        self.assertEqual(validate(d,f,m,b)['confirmed_plans'],1)
    def test_unrelated_receipt_cannot_authorize_a_new_plan(self):
        d,f,m,b=self.existing();ex=f['research_execution'];read=ex['reads'][0]
        plan={'plan_name':'UNRELATED invented plan','price_yen':None,'checked_at':read['checked_at'],
              'source_url':read['url'],'evidence_quote':read['excerpt']}
        d['shops'][0]['plans'].append(plan)
        ex['verified_plans']=[{'shop_id':'prior','plan_name':plan['plan_name'],'read_id':read['id']}]
        ex['metrics']={'confirmed_shops':1,'confirmed_plans':1,'new_shops':0};seal(d,f)
        with self.assertRaisesRegex(ValueError,'plan_title'):validate(d,f,m,b)
