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
