import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from afternoon_tea import routine_site as r
from afternoon_tea.publication_completion import gate
from tests.test_routine_site import FakeAPI
from tests.weekly_completion_fixture import BASE,HEAD,seal,files

class CompletionBoundaries(unittest.TestCase):
    def test_complete_zero_new_can_merge_exact_ci_head(self):
        api=FakeAPI();out=r.intake(api,1,'tsubasa0518');self.assertEqual(out['research_completion'],'passed')
        self.assertEqual(api.calls[0][2]['sha'],HEAD)
    def test_pr45_equivalent_blocks_intake_despite_technical_success(self):
        api=FakeAPI();api.failures['research_execution']['tasks']=[]
        api.failures['research_execution']['stop_reasons']=['ForbiddenOperation']
        seal(api.data,api.failures);api.content=files(api.data,api.failures)
        with self.assertRaises(ValueError):r.intake(api,1,'tsubasa0518')
        self.assertFalse(api.calls)
    def test_manual_dispatch_rejects_same_incomplete_data_before_artifact(self):
        api=FakeAPI();api.failures['research_execution']['tasks']=[]
        seal(api.data,api.failures);api.content=files(api.data,api.failures)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name,body in api.content.items():(root/name).parent.mkdir(exist_ok=True);(root/name).write_bytes(body)
            with patch.object(r,'ROOT',root),patch.dict('os.environ',{'SOURCE_COMMIT':HEAD}):
                with self.assertRaises(ValueError):r.prepare(api)
            self.assertFalse((root/'.staging/routine-delivery/site/index.html').exists())
    def test_missing_run_or_old_metrics_fail_both_boundaries(self):
        for mutate in (lambda api:api.data.pop('weekly_run'),
                       lambda api:api.failures['research_execution']['metrics'].update(new_shops=10)):
            api=FakeAPI();mutate(api)
            if 'weekly_run' in api.data:seal(api.data,api.failures)
            api.content=files(api.data,api.failures)
            for base in (BASE,None):
                with self.assertRaises(ValueError):gate(api,HEAD,api.content,base)
            self.assertFalse(api.calls)
    def test_fixed_renderer_and_exact_checkpoint_bytes_required(self):
        api=FakeAPI();api.content['site/index.html']=api.content['site/index.html'].replace(b'</body>',b'<p>extra</p></body>')
        with self.assertRaisesRegex(ValueError,'fixed_renderer'):gate(api,HEAD,api.content,BASE)
    def test_draft_pending_ci_failed_ci_head_change_and_extra_file_rejected(self):
        api=FakeAPI();api.pr['draft']=True
        with self.assertRaises(ValueError):r.intake(api,1,'tsubasa0518')
        api=FakeAPI();api.changed=[{'filename':'AGENTS.md','status':'modified'}]
        with self.assertRaises(ValueError):r.intake(api,1,'tsubasa0518')
    def test_failed_completion_keeps_existing_public_file(self):
        api=FakeAPI();api.data.pop('weekly_run');api.content=files(api.data,api.failures)
        original=b'EXISTING PUBLIC SITE'
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'published.html';target.write_bytes(original)
            with self.assertRaises(ValueError):gate(api,HEAD,api.content,BASE)
            self.assertEqual(target.read_bytes(),original)
    def test_main_workflows_gate_before_upload_and_pin_event_commit(self):
        text=(r.ROOT/'.github/workflows/deploy.yml').read_text()
        self.assertIn('ref: ${{ github.sha }}',text)
        self.assertLess(text.index('routine_site prepare'),text.index('upload-pages-artifact'))
        self.assertIn('routine_site verify',text)
        auto=(r.ROOT/'.github/workflows/auto-merge-weekly.yml').read_text()
        self.assertNotIn('pull_request.head.sha',auto);self.assertIn('ref: ${{ github.sha }}',auto)

class DigestSafetyTests(unittest.TestCase):
    def test_full_digest_is_not_misread_as_card_but_real_card_still_rejected(self):
        digest='a'*20+'4111111111111111'+'b'*28
        self.assertEqual(len(digest),64);r.scan(digest.encode())
        with self.assertRaises(ValueError):r.scan((digest+' card: 4111 1111 1111 1111').encode())

class MaintenanceBoundaryTests(unittest.TestCase):
    def api_for_published_parent(self):
        api=FakeAPI();original=api.get
        def get(path):
            if path=='/git/commits/'+'f'*40:return {'parents':[{'sha':HEAD}]}
            if '/deploy.yml/runs?' in path:return {'workflow_runs':[{'id':99,'head_sha':HEAD,'status':'completed','conclusion':'success'}]}
            if '/jobs?' in path:return {'jobs':[{'steps':[{'name':'Verify public URL and exact HTML bytes','conclusion':'success'}]}]}
            return original(path)
        api.get=get;return api
    def test_maintenance_reuses_completed_published_json_without_new_research(self):
        api=self.api_for_published_parent()
        out=gate(api,'f'*40,api.content)
        self.assertEqual(out['research_completion'],'published_baseline_reused')
    def test_published_pr45_style_incomplete_data_is_not_grandfathered(self):
        api=self.api_for_published_parent();api.data.pop('weekly_run');api.content=files(api.data,api.failures)
        with self.assertRaisesRegex(ValueError,'published_baseline_not_complete'):gate(api,'f'*40,api.content)
    def test_changed_json_cannot_claim_maintenance_reuse(self):
        api=self.api_for_published_parent();data=copy.deepcopy(api.data);data['note']='changed research'
        with self.assertRaises(ValueError):gate(api,'f'*40,files(data,api.failures))
