import copy,unittest
from datetime import date
from pathlib import Path
from afternoon_tea.master import load_master,ROOT
from afternoon_tea.data import create_data
from afternoon_tea.publication_quality import evaluate,DEFAULTS
from afternoon_tea.validation import validate_data

class PublicationGateTests(unittest.TestCase):
 def setUp(self):
  self.master=load_master();self.data=create_data(self.master,'2026-11-07');self.data['metadata']['purpose']='research'
  self.audit={'items':[],'areas':[{'discovery_status':'incomplete'} for _ in range(14)],'last_run':{'complete_coverage':False}}
  self.html=(ROOT/'docs/index.html').read_text()
  self.cfg={**DEFAULTS,'min_master_review_rate':0,'min_area_research_rate':0,'max_unresolved_master_rate':1,'require_first_migration_approval':False}
 def result(self,d=None,a=None,h=None):return evaluate(d or self.data,a or self.audit,h or self.html,self.html,self.cfg,now=date(2026,11,7))
 def test_empty_confirmed_is_not_approved(self):self.assertNotEqual(self.result()['status'],'APPROVED_FOR_PUBLICATION')
 def test_120_to_2_is_blocked(self):
  r=self.result(h='<article></article><article></article>');self.assertEqual(r['checks']['baseline_delta']['status'],'fail')
 def test_missing_area_fails_json(self):
  d=copy.deepcopy(self.data);d['areas'].pop();self.assertEqual(self.result(d=d)['checks']['json_14_areas']['status'],'fail')
 def test_stale_data_fails_freshness(self):
  d=copy.deepcopy(self.data);d['generated']='2020-01-01';self.assertEqual(self.result(d=d)['checks']['freshness']['status'],'fail')
 def test_test_purpose_never_approved(self):
  d=copy.deepcopy(self.data);d['metadata']['purpose']='test';self.assertNotEqual(self.result(d=d)['status'],'APPROVED_FOR_PUBLICATION')
 def test_incomplete_run_blocks(self):
  a=copy.deepcopy(self.audit);a['stop_reason']='time_budget';self.assertEqual(self.result(a=a)['checks']['interrupted_run']['status'],'fail')
 def test_valid_structure_is_only_staging(self):self.assertEqual(self.result()['status'],'STAGING_VALID')
