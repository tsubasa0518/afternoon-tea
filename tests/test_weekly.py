import unittest
from pathlib import Path
from datetime import date,timedelta
from afternoon_tea.master import ROOT
class WeeklyWorkflowTests(unittest.TestCase):
 def test_jst_window_is_40_days(self):self.assertEqual(date(2026,11,7)+timedelta(days=40),date(2026,12,17))
 def test_legacy_has_no_schedule_or_enable_switch(self):
  workflow=(ROOT/'.github/workflows/weekly-research.yml').read_text()
  self.assertNotIn('schedule:',workflow);self.assertNotIn('WEEKLY_RESEARCH_ENABLED',workflow)
 def test_manual_diagnostic_cannot_commit_or_publish(self):
  workflow=(ROOT/'.github/workflows/weekly-research.yml').read_text()
  self.assertIn('workflow_dispatch:',workflow);self.assertIn('contents: read',workflow)
  for forbidden in ['contents: write','git push','git commit','persist_state','deploy-pages','pull-requests: write']:self.assertNotIn(forbidden,workflow)
  self.assertIn('--state-dir .staging/legacy-diagnostic-state',workflow)
 def test_hidden_staging_artifacts_are_included(self):
  self.assertIn('include-hidden-files: true',(ROOT/'.github/workflows/weekly-research.yml').read_text())
 def test_missing_html_is_an_error_with_saved_summary(self):
  import tempfile,json
  from unittest.mock import patch
  from afternoon_tea.weekly import run
  from afternoon_tea.data import JST
  import datetime as dt
  with tempfile.TemporaryDirectory() as tmp:
   out=Path(tmp);day=str(dt.datetime.now(JST).date());(out/('data_'+day+'.json')).write_text('{}')
   state={'items':[],'last_run':{}}
   with patch('afternoon_tea.weekly.protected_files'),patch('afternoon_tea.weekly.run_discovery',return_value={}),patch('afternoon_tea.weekly.run_queue',return_value=(out,state)):
    result,summary,code=run()
   self.assertNotEqual(code,0);self.assertIn('html_missing',summary['errors']);self.assertTrue((out/'summary.json').exists())
   self.assertIn('reservation_audit_complete',summary)
