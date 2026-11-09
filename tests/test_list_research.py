import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from afternoon_tea.research import Browser
from afternoon_tea.read_only import ForbiddenOperation
from afternoon_tea.list_research import reference,initialize,run,list_traversed
from afternoon_tea.campaign_gate import publication_gate
from afternoon_tea.master import load_master


def completed_campaign():
    state=initialize({'shops':[]})
    source={'url':'https://example.org/at','checked_at':'2026-11-09T07:17:00+09:00','basis':'TEST ONLY plan evidence'}
    for row in state['rows']:
        row.update(status='reviewed',reviewed_sources=[source.copy()])
    state['discovery']=[{'area_no':a['no'],'stations':a['stations'],'status':'reviewed','reviewed_sources':[source.copy()]} for a in load_master()['areas']]
    state['discovery'].append({'area_no':15,'stations':[],'status':'reviewed','reviewed_sources':[source.copy()]})
    state.update(phase='complete',publication_ready=True)
    return state


class CampaignTests(unittest.TestCase):
    def test_original_and_resume_identity(self):
        rows,digest=reference();self.assertEqual(len(rows),385)
        state=initialize({'shops':[]});self.assertEqual(state['rows'][0]['original'],rows[0])
        self.assertIs(initialize({},state),state)
        damaged=copy.deepcopy(state);damaged['rows'].pop()
        with self.assertRaises(ValueError):initialize({},damaged)
    def test_interruption_is_not_retried_or_skipped(self):
        state=initialize({});state['rows'][0]['status']='interrupted'
        class NoNetwork:
            count=0;max_requests=100
            def fetch(self,url):raise AssertionError('network forbidden')
        with tempfile.TemporaryDirectory() as tmp:
            result=run(state,tmp,NoNetwork())
            self.assertEqual(result['rows'][1]['status'],'unresearched')
            self.assertEqual(json.loads((Path(tmp)/'checkpoint.json').read_text()),result)
    def test_traversal_is_not_publication(self):
        state=completed_campaign();state['rows'][0]['status']='access_restricted'
        self.assertTrue(list_traversed(state))
        with self.assertRaises(ValueError):publication_gate({'period':{'start':'2026-11-09'}},{'research_campaign':state})
    def test_gate_rejects_missing_partial_stale_and_duplicate_evidence(self):
        research={'period':{'start':'2026-11-09'}}
        with self.assertRaises(ValueError):publication_gate(research,{})
        complete=completed_campaign();publication_gate(research,{'research_campaign':complete})
        for alter in [lambda x:x['rows'][0].update(status='interrupted'),lambda x:x['rows'][0].update(reviewed_sources=[]),lambda x:x['rows'][0]['reviewed_sources'][0].update(checked_at='2026-11-08T07:17:00+09:00'),lambda x:x.update(discovery=x['discovery'][:-1]),lambda x:x.update(publication_ready=False)]:
            bad=copy.deepcopy(complete);alter(bad)
            with self.assertRaises(ValueError):publication_gate(research,{'research_campaign':bad})

    def test_collection_stops_globally_and_checkpoints(self):
        state=initialize({})
        with tempfile.TemporaryDirectory() as tmp:
            browser=Browser(delay=0)
            with patch.object(browser,'fetch',side_effect=ForbiddenOperation('redirect_blocked_before_follow')) as fetch:
                result=run(state,tmp,browser)
            self.assertEqual(fetch.call_count,1)
            self.assertEqual(result['rows'][0]['status'],'interrupted')
            self.assertEqual(result['rows'][1]['status'],'unresearched')
    def test_store_collection_does_not_follow_general_area_or_other_store(self):
        state=initialize({})
        with tempfile.TemporaryDirectory() as tmp:
            browser=Browser(delay=0)
            with patch.object(browser,'fetch',return_value='<title>AT</title><a href="/area/tokyo/">レストラン</a><a href="/100000/">Afternoon tea</a>') as fetch:
                run(state,tmp,browser,limit=1)
            self.assertEqual(fetch.call_count,1)
            self.assertEqual(state['rows'][0]['status'],'awaiting_review')
