"""Stable fixtures and changing production data; no live reservation requests."""
import copy,json,unittest
from unittest.mock import patch
from afternoon_tea import routine_site as r, routine_renderer as renderer
from afternoon_tea.master import ROOT
from afternoon_tea.weekly_review import review
from tests.test_routine_site import FakeAPI

class TechnicalCITests(unittest.TestCase):
    def check(self,runs,expected):
        api=FakeAPI();original=api.get
        api.get=lambda p: {'workflow_runs':runs} if '/test-data.yml/runs?' in p else original(p)
        result=r.intake(api,1,'tsubasa0518',sleep=lambda _:None)
        self.assertEqual(result.get('merge'),expected)
        self.assertFalse(any(c[0]=='PUT' for c in api.calls))
    def test_missing(self):self.check([],'ci_pending')
    def test_running(self):self.check([{'id':1,'head_sha':'a'*40,'event':'pull_request','status':'in_progress'}],'ci_pending')
    def test_failure(self):self.check([{'id':1,'head_sha':'a'*40,'event':'pull_request','status':'completed','conclusion':'failure'}],'ci_failed')
    def test_old_sha(self):self.check([{'id':1,'head_sha':'b'*40,'event':'pull_request','status':'completed','conclusion':'success'}],'ci_pending')
    def test_rerun_failure_wins(self):self.check([{'id':1,'run_attempt':a,'head_sha':'a'*40,'event':'pull_request','status':'completed','conclusion':c} for a,c in [(1,'success'),(2,'failure')]],'ci_failed')
    def test_resume_ignores_non_pr(self):
        from afternoon_tea.routine_ci_resume import resume
        self.assertEqual(resume(None,{'workflow_run':{'event':'push'}},'x'),[])

class ProductionTests(unittest.TestCase):
    def test_dynamic_data_and_reproducible_html(self):
        d=json.loads((ROOT/'site/research.json').read_text());f=json.loads((ROOT/'site/search_failures.json').read_text())
        self.assertFalse(review(d)['errors'])
        ids=[]
        for shop in d['shops']:
            self.assertIsInstance(shop['name'],str);ids.append(shop['id'])
            self.assertIn(shop.get('category'),(None,'cafe','hotel','lux'))
            r.resource(shop['source_url']);self.assertTrue(shop['checked_at'])
            for p in shop['plans']:
                self.assertIsInstance(p['plan_name'],str)
                self.assertTrue(p.get('evidence_quote'))
                self.assertTrue(p.get('price_yen') is None or type(p['price_yen']) in (int,float))
                for key in ('sweets','season'):
                    self.assertTrue(p.get(key) is None or isinstance(p[key],(str,list)))
                for key in ('weekday_available','weekend_available'):
                    self.assertTrue(p.get(key) is None or type(p[key]) is bool)
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(renderer.render(d,f),(ROOT/'site/index.html').read_text())
        r.validate_site({p:(ROOT/p).read_bytes() for p in r.ALLOWED})
    def test_multiple_plans_not_truncated(self):
        d=json.loads((ROOT/'tests/fixtures/post26_six.json').read_text());s=d['shops'][0]
        s['plans']=[copy.deepcopy(s['plans'][0]) for _ in range(3)]
        for i,p in enumerate(s['plans']):p['plan_name']='TEST ONLY plan '+str(i)
        d['shops']=[s];h=renderer.render(d,{'schema_version':1,'failures':[]})
        for i in range(3):self.assertIn('TEST ONLY plan '+str(i),h)

class CollectionDetailsTests(unittest.TestCase):
    def test_two_safe_at_details_and_blocked_discovery(self):
        import tempfile
        from afternoon_tea import routine_collection as c
        from tests.test_post26 import FakeBrowser,queue
        q=queue();q['areas']=q['areas'][:1];q['areas'][0]['tasks']=q['areas'][0]['tasks'][:1]
        url=q['areas'][0]['tasks'][0]['historical_url']
        html='<div>ティー アフタヌーンティー <a href="/123456/plan111111">詳細</a></div><div>ランチ アフタヌーンティー <a href="/123456/plan222222">詳細</a></div><div>ディナー 通常 <a href="/123456/plan333333">詳細</a></div>'
        b=FakeBrowser({c.AREA_LIST:RuntimeError('robots_unknown_or_disallowed'),url:html})
        with tempfile.TemporaryDirectory() as tmp:state=c.run(q,tmp,b,clock=lambda:0)
        self.assertTrue(state['discovery_budget']['fallback_required'])
        self.assertEqual(len(state['documents'][0]['plan_pages']),2)
        self.assertFalse(any('plan333333' in x for x in b.urls))
    def test_exact_historical_category_does_not_copy_plan_data(self):
        from afternoon_tea.routine_enrichment import enrich
        d={'shops':[{'id':'unknown','name':'TEST cafe','source_url':'https://restaurant.ikyu.com/123456/plan111111','plans':[]}]}
        reference='<article data-cat="cafe"><h4>TEST cafe</h4><a href="https://restaurant.ikyu.com/123456/plan222222">old</a></article>'
        master={'areas':[]}
        out=enrich(d,master,reference);self.assertEqual(out['shops'][0]['category'],'cafe');self.assertEqual(out['shops'][0]['plans'],[])
        d['shops'][0]['name']='Other cafe';self.assertNotIn('category',enrich(d,master,reference)['shops'][0])
