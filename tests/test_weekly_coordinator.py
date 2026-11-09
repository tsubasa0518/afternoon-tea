import copy,datetime as dt,hashlib,json,threading,unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from unittest.mock import patch
from afternoon_tea import weekly_run as w
from afternoon_tea.routine_site import REPO
from tests.weekly_completion_fixture import BASE,WEEK,fixture,files

class ControlAPI:
    """Atomic server ref semantics, including no-fast-forward/duplicate failures."""
    def __init__(self):
        self.refs={'heads/main':BASE};self.commits={BASE:{'tree':{'sha':'d'*40},'parents':[]}}
        self.blobs={};self.trees={};self.prs=[];self.calls=[];self.counter=0;self.mutex=threading.Lock();self.barrier=None;self.published=False
        self.data,self.failures,self.master,self.baseline=fixture()
    def read(self,commit,path):
        if commit in self.commits and self.commits[commit]['tree']['sha'] in self.trees:
            mapping=self.trees[self.commits[commit]['tree']['sha']]
            if path in mapping:return self.blobs[mapping[path]]
        if path=='site/research.json':return json.dumps(self.data if commit!=BASE else self.baseline).encode()
        if path=='data/store_master.json':return json.dumps(self.master).encode()
        return json.dumps(self.failures).encode()
    def get(self,path):
        if path.startswith('/git/ref/'):
            key=path[len('/git/ref/'):]
            if key not in self.refs:raise HTTPError('',404,'missing',{},None)
            return {'object':{'sha':self.refs[key]}}
        if path.startswith('/git/commits/'):return copy.deepcopy(self.commits[path.rsplit('/',1)[-1]])
        if path.startswith('/git/matching-refs/'):
            prefix=path[len('/git/matching-refs/'):]
            return [{'ref':'refs/'+k,'object':{'sha':v}} for k,v in self.refs.items() if k.startswith(prefix)]
        if path.startswith('/pulls?'):return copy.deepcopy(self.prs)
        if '/jobs?' in path:return {'jobs':[{'steps':[{'name':'Verify public URL and exact HTML bytes','conclusion':'success'}]}]}
        if '/deploy.yml/runs?' in path:return {'workflow_runs':[{'id':99,'head_sha':'e'*40,'status':'completed','conclusion':'success'}] if self.published else []}
        if '/test-data.yml/runs?' in path:return {'workflow_runs':[]}
        if '/runs?' in path:return {'workflow_runs':[]}
        raise AssertionError(path)
    def call(self,method,path,body):
        if self.barrier and path=='/git/refs' and body['ref'].startswith('refs/heads/routine-lock/'):
            self.barrier.wait(timeout=5)
        with self.mutex:
            self.calls.append((method,path,copy.deepcopy(body)))
            if path=='/git/blobs':
                sha=hashlib.sha1(body['content'].encode()).hexdigest();self.blobs[sha]=body['content'].encode();return {'sha':sha}
            if path=='/git/trees':
                sha=hashlib.sha1(json.dumps(body).encode()).hexdigest();self.trees[sha]={e['path']:e['sha'] for e in body['tree']};return {'sha':sha}
            if path=='/pulls':
                if self.prs:raise HTTPError('',422,'PR exists',{},None)
                pr={'number':1,'node_id':'TEST_NODE','state':'open','draft':body['draft'],'title':body['title'],
                    'head':{'ref':body['head'],'sha':self.refs['heads/'+body['head']],'repo':{'full_name':REPO}}}
                self.prs.append(pr);return copy.deepcopy(pr)
            if path=='/pulls/1':
                self.prs[0].update(body);return copy.deepcopy(self.prs[0])
            if path=='/git/commits':
                self.counter+=1;sha=hashlib.sha1(str(self.counter).encode()).hexdigest()
                self.commits[sha]={'message':body['message'],'tree':{'sha':body['tree']},'parents':[{'sha':s} for s in body['parents']]};return {'sha':sha}
            if path=='/git/refs':
                ref=body['ref'][len('refs/'):]
                if ref in self.refs:raise HTTPError('',422,'already exists',{},None)
                self.refs[ref]=body['sha'];return {}
            if path.startswith('/git/refs/'):
                ref=path[len('/git/refs/'):];parents=[r['sha'] for r in self.commits[body['sha']]['parents']]
                if self.refs[ref] not in parents or body.get('force') is not False:raise HTTPError('',422,'not fast-forward',{},None)
                self.refs[ref]=body['sha']
                for pr in self.prs:
                    if ref=='heads/'+pr['head']['ref']:pr['head']['sha']=body['sha']
                return {}
            raise AssertionError(path)

class CoordinatorTests(unittest.TestCase):
    def now(self):return dt.datetime.now(dt.timezone.utc)
    def test_parallel_start_one_owner_only(self):
        api=ControlAPI();api.barrier=threading.Barrier(2)
        def run():
            try:return w.start(api,WEEK,now=self.now())
            except (HTTPError,ValueError):return None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:run(),range(2)))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(len([k for k in api.refs if 'routine-lock' in k]),1)
    def test_live_lease_rejects_second_start_even_resume(self):
        api=ControlAPI();w.start(api,WEEK)
        for resume in (False,True):
            with self.assertRaisesRegex(ValueError,'in_progress'):w.start(api,WEEK,resume)
        self.assertFalse(api.prs)
    def test_paused_resume_preserves_run_and_branch_fences_old_owner(self):
        api=ControlAPI();state=w.start(api,WEEK);sha,record=w.read_lock(api,WEEK)
        record['state']='paused';w.write_lock(api,WEEK,record,sha)
        resumed=w.start(api,WEEK,True)
        self.assertEqual(resumed['run_id'],state['run_id']);self.assertEqual(resumed['branch'],state['branch'])
        self.assertNotEqual(resumed['owner'],state['owner'])
        with self.assertRaisesRegex(ValueError,'lease_lost'):w.owned(api,state)
    def test_same_week_published_legacy_pr_no_new_lock_or_pr(self):
        api=ControlAPI();api.published=True
        api.prs=[{'number':45,'merged_at':'2026-11-09T07:21:09+09:00','merge_commit_sha':'e'*40,
                  'head':{'sha':'a'*40,'ref':'claude/weekly-afternoon-tea-20261108-r2','repo':{'full_name':REPO}}}]
        result=w.start(api,WEEK)
        self.assertEqual(result['action'],'already_published');self.assertEqual(result['pr'],45);self.assertFalse(api.calls)
    def test_publication_failure_reuses_pr_and_commit(self):
        api=ControlAPI();api.prs=[{'number':45,'merged_at':'yes','merge_commit_sha':'e'*40,
                   'head':{'sha':'a'*40,'ref':'claude/weekly-afternoon-tea-20261108-r2','repo':{'full_name':REPO}}}]
        result=w.start(api,WEEK);self.assertEqual(result['action'],'recover_publication');self.assertEqual(result['commit'],'e'*40)
        self.assertFalse(api.calls)
    def test_existing_branch_without_pr_requires_resume_no_r2(self):
        api=ControlAPI();branch='heads/'+w.BRANCH_PREFIX+WEEK.replace('-','');api.refs[branch]=BASE
        with self.assertRaisesRegex(ValueError,'existing_branch'):w.start(api,WEEK)
        result=w.start(api,WEEK,True);self.assertEqual('heads/'+result['branch'],branch)
    def test_two_legacy_prs_block_instead_of_third(self):
        api=ControlAPI();p={'number':1,'head':{'sha':'a'*40,'ref':w.BRANCH_PREFIX+'20261109','repo':{'full_name':REPO}}}
        api.prs=[p,dict(p,number=2)]
        with self.assertRaisesRegex(ValueError,'duplicate_weekly'):w.start(api,WEEK)
        self.assertFalse(api.calls)
    def test_partial_checkpoint_draft_resumes_same_pr_without_duplicates(self):
        api=ControlAPI();state=w.start(api,WEEK)
        api.data['weekly_run'].update(run_id=state['run_id'],started_at=state['started_at'])
        api.failures['research_execution']['run_id']=state['run_id']
        api.failures['research_execution']['tasks']=[]
        api.failures['research_execution']['stop_reasons']=['ForbiddenOperation']
        first=w.submit(api,state,files(api.data,api.failures),api.master)
        self.assertEqual(first['action'],'draft_saved');self.assertTrue(api.prs[0]['draft'])
        resumed=w.start(api,WEEK,True)
        second=w.submit(api,resumed,files(api.data,api.failures),api.master)
        self.assertEqual(second['pr'],first['pr']);self.assertEqual(len(api.prs),1)
        self.assertEqual(sum(path=='/pulls' for _,path,_ in api.calls),1)
        self.assertFalse(any('dispatches' in path for _,path,_ in api.calls))

    def test_interrupted_run_cannot_become_ready(self):
        api=ControlAPI();state=w.start(api,WEEK)
        # Abort before any GitHub mutation beyond lease when run does not match.
        api.data['weekly_run']['run_id']='wrong_run_1234567890'
        with self.assertRaises(ValueError):w.submit(api,state,files(api.data,api.failures),api.master)
        self.assertFalse(any(path=='/pulls' for _,path,_ in api.calls))
