"""Committed live checkpoints must remain complete, dated, and source-backed."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import unittest
from afternoon_tea.master import ROOT,load_master
from afternoon_tea.validation import validate_data
class SavedResearchTests(unittest.TestCase):
 def test_persisted_checkpoint_and_evidence(self):
  directory=ROOT/'research_data';state=json.loads((directory/'state.json').read_text())
  self.assertEqual(sum(x['kind']=='master' for x in state['items']),70)
  self.assertEqual(sum(x['kind']=='candidate' for x in state['items']),5)
  self.assertEqual(len({x['id'] for x in state['items']}),len(state['items']))
  self.assertEqual(state['data']['generated'],state['day']);validate_data(state['data'],load_master())
  for a in state['data']['areas']:
   for g in a['cats'].values():
    for shop in g['shops']:
     self.assertNotIn('TEST_ONLY',shop['name'])
     if shop['research']['status']=='confirmed':self.assertEqual(shop['research']['checked_on'],state['day'])
  for item in state['items']:
   for attempt in item.get('attempts',[]):
    for page in attempt.get('pages',[]):
     if 'evidence' not in page:continue
     path=(directory/page['evidence']).resolve();self.assertIn(directory.resolve(),path.parents)
     self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),path.stem)
     evidence=json.loads(path.read_text());self.assertEqual(evidence['url'],page['url'])
     self.assertIsNotNone(dt.datetime.fromisoformat(evidence['checked_at']).tzinfo)
