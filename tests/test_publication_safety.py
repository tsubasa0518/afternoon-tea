import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from afternoon_tea.master import ROOT
from afternoon_tea.publication_safety import area_metrics,current_evidence,digest
from afternoon_tea.publication_bundle import rehearse,sha
from afternoon_tea.publication_quality import report_destination

class SafetyTests(unittest.TestCase):
 def areas(self,status):return [{'no':i,'discovery_status':status} for i in range(1,15)]
 def test_complete(self):self.assertEqual(area_metrics(self.areas('complete'))['completion_rate'],1)
 def test_incomplete(self):self.assertEqual(area_metrics(self.areas('incomplete'))['completion_rate'],0);self.assertEqual(area_metrics(self.areas('incomplete'))['started_rate'],1)
 def test_unknown(self):self.assertFalse(area_metrics(self.areas('other'))['valid'])
 def test_missing(self):self.assertFalse(area_metrics(self.areas('complete')[:-1])['valid'])
 def test_duplicate(self):a=self.areas('complete');a[0]['no']=2;self.assertFalse(area_metrics(a)['valid'])
 def test_mixed(self):a=self.areas('complete');a[0]['discovery_status']='incomplete';self.assertEqual(area_metrics(a)['completion_rate'],13/14)
 def fixture(self):
  from afternoon_tea.run_context import RunContext
  from afternoon_tea.communication_audit import identity
  from afternoon_tea.master import dumps
  from afternoon_tea.data import JST
  import datetime as dt,hashlib
  ctx=RunContext(run_id='TEST_RUN');url='https://www.tablecheck.com/ja/shops/test/reserve'
  shop={'master_id':'TEST_ONLY','research':{'status':'confirmed'},'links':[{'url':url}]}
  rid=ctx.journal.begin(url,'GET');ctx.journal.finish(rid,'http_success',http_status=200)
  doc=ctx.journal.record('document',resource=identity(url),status='success',request_id=rid,page_sha256='test-page-hash')
  evidence={'item_id':'TEST_ONLY','url':url,'extraction':{'master_id':'TEST_ONLY','status':'confirmed','sha256':'test-page-hash'}}
  key=hashlib.sha256(dumps(evidence).encode()).hexdigest()
  ctx.confirm(shop,evidence,'evidence/'+key+'.json',doc,dt.datetime.now(JST).isoformat())
  from types import SimpleNamespace
  browser=SimpleNamespace(count=1,communication_audit=ctx.journal,transport=SimpleNamespace(communication_audit=ctx.journal))
  run=ctx.snapshot(browser)
  data={'generated':dt.datetime.now(JST).date().isoformat(),'metadata':{'run_id':ctx.id,'generated_at':run['generated_at']},'areas':[{'cats':{'cafe':{'shops':[shop]}}}]}
  return data,{'current_run':run},run['receipts']['TEST_ONLY']
 def test_current_evidence(self):d,a,r=self.fixture();self.assertTrue(current_evidence(d,a))
 def test_restored(self):d,a,r=self.fixture();r['restored_from_previous']=True;self.assertFalse(current_evidence(d,a))
 def test_old_run(self):d,a,r=self.fixture();r['run_id']='OLD';self.assertFalse(current_evidence(d,a))
 def test_changed_shop(self):d,a,r=self.fixture();r['shop_sha256']='wrong';self.assertFalse(current_evidence(d,a))
 def test_no_telemetry(self):d,a,r=self.fixture();a['current_run']['reservation_audit']['complete']=False;self.assertFalse(current_evidence(d,a))
 def test_protected_output(self):
  for p in ('docs/index.html','build_html.py','research_spec.md','original_prompt.txt','.github/workflows/deploy.yml'):
   with self.assertRaises(ValueError):report_destination(ROOT/p)
 def test_symlink(self):
  root=ROOT/'.staging';root.mkdir(exist_ok=True)
  with tempfile.TemporaryDirectory(dir=root) as t:
   p=Path(t)/'link';p.symlink_to(ROOT/'docs/index.html')
   with self.assertRaises(ValueError):report_destination(p)
 def test_sandbox_rollback_and_binding(self):
  root=ROOT/'.staging';root.mkdir(exist_ok=True)
  with tempfile.TemporaryDirectory(dir=root) as t:
   b=Path(t)/'bundle';b.mkdir();(b/'index.html').write_text('TEST_ONLY new HTML');target=Path(t)/'site/index.html';target.parent.mkdir();target.write_text('TEST_ONLY old HTML')
   m={'files':{'index.html':sha((b/'index.html').read_bytes()),'data.json':'test-data-hash'},'baseline_sha256':sha(target.read_bytes())}
   auth={'kind':'initial_environment_approval','required_reviewers_verified':True,'run_id':'test-run','html_sha256':m['files']['index.html'],'data_sha256':'test-data-hash'}
   flags={'WEEKLY_RESEARCH_ENABLED':True,'WEEKLY_PUBLICATION_ENABLED':True}
   with patch('afternoon_tea.publication_bundle.verify',return_value=m):
    with self.assertRaises(ValueError):rehearse(b,target,'test-run','test-commit',{},auth,True)
    with self.assertRaises(ValueError):rehearse(b,target,'test-run','test-commit',flags,{},True)
    with self.assertRaises(RuntimeError):rehearse(b,target,'test-run','test-commit',flags,auth,True,lambda p:(_ for _ in ()).throw(RuntimeError('TEST_ONLY http failure')))
    self.assertEqual(target.read_text(),'TEST_ONLY old HTML')
    rehearse(b,target,'test-run','test-commit',flags,auth,True);self.assertEqual(target.read_text(),'TEST_ONLY new HTML')

 def test_date_only_refresh_rejected(self):
  d,a,r=self.fixture();d['generated']='2000-01-01';self.assertFalse(current_evidence(d,a))
 def test_prepare_keeps_research_quality_separate_from_authorization(self):
  from afternoon_tea.publication_bundle import prepare,verify
  root=ROOT/'.staging';root.mkdir(exist_ok=True)
  with tempfile.TemporaryDirectory(dir=root) as t:
   p=Path(t);d,a,r=self.fixture();(p/'data.json').write_text(json.dumps(d));(p/'audit.json').write_text(json.dumps(a));(p/'html').write_text('TEST_ONLY');(p/'baseline').write_text('TEST_ONLY baseline')
   def quality(data,audit,html,baseline,policy):
    self.assertFalse(policy['require_first_migration_approval']);return {'status':'APPROVED_FOR_PUBLICATION','publishable':True}
   with patch('afternoon_tea.publication_bundle.validate_data'),patch('afternoon_tea.publication_bundle.validate_html'),patch('afternoon_tea.publication_bundle.evaluate',side_effect=quality):
    prepare(p/'data.json',p/'audit.json',p/'html',p/'baseline',p/'bundle','TEST_RUN','TEST_COMMIT')
    verify(p/'bundle','TEST_RUN','TEST_COMMIT')
    with self.assertRaises(ValueError):rehearse(p/'bundle',p/'target','TEST_RUN','TEST_COMMIT',{'WEEKLY_RESEARCH_ENABLED':True,'WEEKLY_PUBLICATION_ENABLED':True},{},True)
