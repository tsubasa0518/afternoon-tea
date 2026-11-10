import copy
import tempfile
import unittest
from afternoon_tea.collection.audit import CommunicationAudit
from afternoon_tea.collection.campaign import initialize, run
from afternoon_tea.collection.resume import BLOCKED, STORE, resume_legacy_directory_stop
from test_list_research import FakeBrowser


def legacy_campaign():
    state=initialize({});state['version']=1
    journal=CommunicationAudit('legacy-test')
    request=journal.begin(BLOCKED,'GET')
    journal.finish(request,'forbidden',reason='redirect_blocked_before_follow')
    journal.decision(BLOCKED,'redirect_blocked_before_follow',violation=True)
    state.update(stop_reason='forbidden_operation',communication_audit=journal.snapshot())
    state['rows'][0].update(status='interrupted',observations={'old':'historical only'},
                            reviewed_sources=[{'url':STORE,'basis':'not v2 evidence'}])
    return state


class ScopedResumeTests(unittest.TestCase):
    def test_explicit_resume_preserves_incident_and_never_follows_directory(self):
        old=legacy_campaign();state=initialize({},old)
        snapshot=copy.deepcopy(state['legacy_checkpoint'])
        self.assertEqual(state['rows'][0]['reviewed_sources'],[])
        self.assertIn('observations',state['rows'][0]['legacy_record'])
        resolution=resume_legacy_directory_stop(state,'User authorized safe store-only route after mock validation')
        self.assertFalse(resolution['legacy_evidence_promoted'])
        self.assertEqual(state['legacy_checkpoint'],snapshot)
        with tempfile.TemporaryDirectory() as tmp:
            plan=STORE+'plan123456'
            browser=FakeBrowser({STORE:'<p>TEST ONLY</p><a href="'+BLOCKED+'">アフタヌーンティー</a><a href="'+plan+'">アフタヌーンティー</a>'})
            run(state,tmp,browser,limit=1)
            self.assertEqual(browser.visited,[STORE,plan])
            self.assertEqual(state['legacy_checkpoint'],snapshot)
            self.assertEqual(state['rows'][0]['status'],'awaiting_review')

    def test_missing_reason_tampering_other_violation_and_v2_stop_refused(self):
        state=initialize({},legacy_campaign())
        with self.assertRaisesRegex(ValueError,'resume_reason_required'):resume_legacy_directory_stop(state,'')
        bad=copy.deepcopy(state);bad['legacy_checkpoint']['communication_audit']['events'][0]['method']='POST'
        with self.assertRaises(ValueError):resume_legacy_directory_stop(bad,'maintenance request')
        bad=copy.deepcopy(state);bad['rows'][1]['status']='interrupted'
        with self.assertRaises(ValueError):resume_legacy_directory_stop(bad,'maintenance request')
        bad=initialize({});bad['rows'][0]['status']='interrupted'
        with self.assertRaises(ValueError):resume_legacy_directory_stop(bad,'maintenance request')
