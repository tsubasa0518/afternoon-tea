import unittest
from pathlib import Path
from datetime import date,timedelta
from afternoon_tea.master import ROOT
class WeeklyWorkflowTests(unittest.TestCase):
 def test_jst_window_is_40_days(self):self.assertEqual(date(2026,11,7)+timedelta(days=40),date(2026,12,17))
 def test_cron_monday_0717_jst(self):self.assertIn("cron: '17 22 * * 0'",(ROOT/'.github/workflows/weekly-research.yml').read_text())
 def test_schedule_requires_explicit_enable(self):self.assertIn("vars.WEEKLY_RESEARCH_ENABLED == 'true'",(ROOT/'.github/workflows/weekly-research.yml').read_text())
 def test_enabled_schedule_persists_state(self):self.assertIn("github.event_name == 'schedule' && vars.WEEKLY_RESEARCH_ENABLED == 'true'",(ROOT/'.github/workflows/weekly-research.yml').read_text())
 def test_no_pages_publication_or_deploy_workflow_change(self):self.assertFalse((ROOT/'.github/workflows/weekly-research.yml').read_text().find('deploy-pages')>=0)
 def test_dispatch_defaults_to_dry_run_without_persist(self):
  workflow=(ROOT/'.github/workflows/weekly-research.yml').read_text()
  self.assertIn('default: true',workflow);self.assertIn('default: false',workflow)
  self.assertIn('inputs.dry_run == false && inputs.persist_state == true',workflow)
 def test_schedule_commit_requires_explicit_enable(self):
  workflow=(ROOT/'.github/workflows/weekly-research.yml').read_text()
  self.assertIn("github.event_name == 'schedule' && vars.WEEKLY_RESEARCH_ENABLED == 'true'",workflow)
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
   self.assertIsNone(summary['reservation_operations'])
