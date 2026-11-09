"""Single weekly Routine coordinator: durable GitHub lock and one PR per JST week.

Only the three site files go to the research branch. Lock checkpoints live in
commit messages on a separate control ref, not in tracked repository files.
"""
import argparse
import datetime as dt
import json
from pathlib import Path
import uuid
from urllib.error import HTTPError
from .research_completion import week_key, digest, required_tasks, payload_hash, validate, collection_totals
from .routine_site import API, ROOT, REPO, ALLOWED, BRANCH_PREFIX, json_bytes, sha, require

LOCK_PREFIX='routine-lock/'


def read_lock(api,week):
    try:ref=api.get('/git/ref/heads/'+LOCK_PREFIX+week)
    except HTTPError as error:
        if error.code==404:return None
        raise
    commit=api.get('/git/commits/'+ref['object']['sha'])
    record=json.loads(commit['message'])
    require(record.get('week_key')==week,'lock_week_mismatch')
    return ref['object']['sha'],record


def write_lock(api,week,record,previous=None):
    base=api.get('/git/commits/'+(previous or record['base_commit']))
    commit=api.call('POST','/git/commits',{'message':json.dumps(record,sort_keys=True),
        'tree':base['tree']['sha'],'parents':[previous or record['base_commit']]})
    if previous:
        # A concurrent owner's sibling commit is not a fast-forward: GitHub
        # rejects it. Never force-update refs or silently steal a live lease.
        api.call('PATCH','/git/refs/heads/'+LOCK_PREFIX+week,{'sha':commit['sha'],'force':False})
    else:
        api.call('POST','/git/refs',{'ref':'refs/heads/'+LOCK_PREFIX+week,'sha':commit['sha']})
    return commit['sha']


def publications(api,commit):
    runs=api.get('/actions/workflows/deploy.yml/runs?head_sha='+commit+'&per_page=100')['workflow_runs']
    verified=[]
    for run in runs:
        if run.get('head_sha')!=commit or run.get('status')!='completed' or run.get('conclusion')!='success':continue
        jobs=api.get('/actions/runs/'+str(run['id'])+'/jobs?per_page=100')['jobs']
        if any(s.get('name')=='Verify public URL and exact HTML bytes' and s.get('conclusion')=='success'
               for job in jobs for s in job.get('steps',[])):verified.append(run)
    return verified


def same_week_prs(api,week):
    rows=[]
    for page in range(1,21):
        batch=api.get('/pulls?state=all&sort=created&direction=desc&per_page=100&page='+str(page))
        for pr in batch:
            if not(pr.get('head',{}).get('repo') and pr['head']['repo']['full_name']==REPO and pr['head']['ref'].startswith(BRANCH_PREFIX)):continue
            # Legacy -r2 PRs are matched by their actual data period, not their
            # misleading branch date or signature. They are never recreated.
            data=json.loads(api.read(pr['head']['sha'],'site/research.json'))
            if week_key(data['period']['start'])==week:rows.append(pr)
        if len(batch)<100:return rows
    raise ValueError('weekly_pr_history_incomplete')


def start(api,week=None,resume=False,now=None):
    now=now or dt.datetime.now(dt.timezone.utc);week=week or week_key(now)
    require(week_key(week)==week,'week_must_be_JST_monday')
    for status in ('in_progress','queued'):
        active=api.get('/actions/workflows/weekly-research.yml/runs?status='+status+'&per_page=100')['workflow_runs']
        require(not active,'legacy_diagnostic_in_progress')
    prs=same_week_prs(api,week)
    require(len(prs)<=1,'duplicate_weekly_prs_need_review')
    if prs and prs[0].get('merged_at'):
        pr=prs[0];commit=pr['merge_commit_sha']
        return {'week_key':week,'pr':pr['number'],'commit':commit,
                'action':'already_published' if publications(api,commit) else 'recover_publication'}
    current=read_lock(api,week)
    if current:
        lock_sha,record=current
        if record['state']=='submitted':
            from .routine_site import technical_ci
            ci=technical_ci(api,record['head_sha'])
            if ci=='pending' or (ci=='success' and dt.datetime.fromisoformat(record['expires_at'])>now):return {**record,'lock_sha':lock_sha,'action':'await_existing_ci'}
        live=dt.datetime.fromisoformat(record['expires_at'])>now and record['state']=='running'
        require(not live,'weekly_run_in_progress')
        require(resume,'existing_week_requires_resume')
        record=dict(record,owner=uuid.uuid4().hex,state='running',expires_at=(now+dt.timedelta(hours=2)).isoformat())
        lock_sha=write_lock(api,week,record,lock_sha)
    else:
        base=api.get('/git/ref/heads/main')['object']['sha']
        branch=prs[0]['head']['ref'] if prs else BRANCH_PREFIX+week.replace('-','')
        # Inventory orphan branches as well as open/draft/merged PRs.
        refs=api.get('/git/matching-refs/heads/'+BRANCH_PREFIX)
        existing=next((r for r in refs if r['ref']=='refs/heads/'+branch),None)
        if existing:require(resume,'existing_branch_requires_resume')
        record={'week_key':week,'run_id':uuid.uuid4().hex,'owner':uuid.uuid4().hex,'state':'running',
                'base_commit':base,'branch':branch,'started_at':now.isoformat(),
                'expires_at':(now+dt.timedelta(hours=2)).isoformat(),'pr':prs[0]['number'] if prs else None}
        lock_sha=write_lock(api,week,record)
    return {**record,'lock_sha':lock_sha,'action':'resume' if resume else 'start'}


def owned(api,state):
    current=read_lock(api,state['week_key']);require(current is not None,'lock_missing')
    lock_sha,record=current
    require(record['owner']==state['owner'] and record['run_id']==state['run_id'] and
            lock_sha==state['lock_sha'] and record['state']=='running','lease_lost')
    require(dt.datetime.fromisoformat(record['expires_at'])>dt.datetime.now(dt.timezone.utc),'lease_expired')
    return lock_sha,record


def initialize(api,state,files,master):
    baseline=json.loads(api.read(state['base_commit'],'site/research.json'))
    data=json.loads(files['site/research.json']);failures=json.loads(files['site/search_failures.json'])
    if data.get('weekly_run',{}).get('run_id')==state['run_id']:return data,failures
    data['weekly_run']={'run_id':state['run_id'],'week_key':state['week_key'],'base_commit':state['base_commit'],
                        'baseline_sha256':digest(baseline),'started_at':state['started_at']}
    failures['research_execution']={'run_id':state['run_id'],'week_key':state['week_key'],
        'reads':[],'tasks':[{'id':k,**v,'run_id':state['run_id'],'week_key':state['week_key'],'state':'not_started',
                            'result':None,'read_ids':[],'conclusion':''} for k,v in required_tasks(master,baseline).items()],
        'stop_reasons':[],'safety_violations':[],'communication_audits':[],'verified_plans':[],
        'metrics':{'confirmed_shops':0,'confirmed_plans':0,'new_shops':0}}
    # Remove stale aggregate claims, never the carried-forward shop evidence.
    data['collection_summary']={'run_id':state['run_id'],'week_key':state['week_key'],'confirmed_shops':0,'confirmed_plans':0,'new_shops':0,'added_plans':0,'menu_plans':0,'by_source':[]}
    return data,failures


def submit(api,state,files,master):
    from .routine_site import validate_site
    validate_site(files);lock_sha,record=owned(api,state)
    baseline=json.loads(api.read(state['base_commit'],'site/research.json'))
    data=json.loads(files['site/research.json']);failures=json.loads(files['site/search_failures.json'])
    run=data['weekly_run'];require(run['run_id']==state['run_id'] and run['week_key']==state['week_key'] and
            run['started_at']==record['started_at'] and run['base_commit']==record['base_commit'],'run_mismatch')
    run['finished_at']=dt.datetime.now(dt.timezone.utc).isoformat()
    try:data['collection_summary']=collection_totals(data,failures['research_execution'],baseline)
    except (KeyError,TypeError,StopIteration,ValueError):pass  # Invalid references stay draft; validate explains why.
    run['payload_sha256']=payload_hash(data);run['execution_sha256']=digest(failures['research_execution'])
    complete=False;reason=None
    try:validate(data,failures,master,baseline,expected_week=state['week_key']);complete=True
    except ValueError as error:reason=str(error)
    files=dict(files);files['site/research.json']=json_bytes(data)
    branch=state['branch'];prs=same_week_prs(api,state['week_key'])
    require(len(prs)<=1 and not any(p.get('merged_at') for p in prs),'week_already_merged')
    if prs:require(prs[0]['head']['ref']==branch,'week_branch_mismatch')
    try:ref=api.get('/git/ref/heads/'+branch);parent=ref['object']['sha']
    except HTTPError as error:
        if error.code!=404:raise
        parent=state['base_commit']
        api.call('POST','/git/refs',{'ref':'refs/heads/'+branch,'sha':parent})
    tree_base=api.get('/git/commits/'+parent)['tree']['sha'];entries=[]
    for path in sorted(ALLOWED):
        blob=api.call('POST','/git/blobs',{'content':files[path].decode(),'encoding':'utf-8'})
        entries.append({'path':path,'mode':'100644','type':'blob','sha':blob['sha']})
    tree=api.call('POST','/git/trees',{'base_tree':tree_base,'tree':entries})
    commit=api.call('POST','/git/commits',{'tree':tree['sha'],'parents':[parent],
        'message':'Weekly research checkpoint '+state['week_key']})
    owned(api,state)
    api.call('PATCH','/git/refs/heads/'+branch,{'sha':commit['sha'],'force':False})
    pending=[t['id'] for t in failures['research_execution']['tasks'] if t.get('state')!='completed']
    body='week_key: '+state['week_key']+'\nrun_id: '+state['run_id']+'\n'+('調査完了・技術CI待ち' if complete else '未完了・公開不可: '+str(reason))
    body+='\n今回の実績: '+json.dumps(failures['research_execution']['metrics'],ensure_ascii=False)
    body+='\n未完了作業: '+json.dumps(pending,ensure_ascii=False)
    body+='\n再開: python3 -m afternoon_tea.weekly_run start --week '+state['week_key']+' --resume'
    body+='\n掲載総数と今週の確認実績、未完了理由・取得失敗はJSONを参照。未完了はdraftのまま公開しません。'
    if prs:
        pr=prs[0]
        if not complete and not pr['draft']:
            api.graphql('mutation($id:ID!){convertPullRequestToDraft(input:{pullRequestId:$id}){pullRequest{id}}}',{'id':pr['node_id']})
        api.call('PATCH','/pulls/'+str(pr['number']),{'body':body,'state':'open'})
    else:
        # Create draft first, even for complete data. A crash before checkpoint
        # persistence cannot leave a mergeable PR without an attestation.
        try:pr=api.call('POST','/pulls',{'base':'main','head':branch,'title':'[weekly-site] '+state['week_key']+' 自動更新','body':body,'draft':True})
        except HTTPError as error:
            if error.code!=422:raise
            existing=same_week_prs(api,state['week_key']);require(len(existing)==1,'weekly_pr_create_conflict');pr=existing[0]
    record.update(state='submitted' if complete else 'paused',pr=pr['number'],head_sha=commit['sha'],
                  files_sha256={p:sha(v) for p,v in files.items()},reason=reason)
    new_lock=write_lock(api,state['week_key'],record,lock_sha)
    if complete and pr.get('draft'):
        api.graphql('mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id}){pullRequest{id}}}',{'id':pr['node_id']})
    return {**record,'lock_sha':new_lock,'action':'ready' if complete else 'draft_saved'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['start','submit','recover-publication'])
    p.add_argument('--week');p.add_argument('--resume',action='store_true');p.add_argument('--state',type=Path,default=ROOT/'.staging/weekly-run.json');a=p.parse_args()
    api=API()
    if a.command=='start':
        state=start(api,a.week,a.resume)
        if state['action'] in ('start','resume'):
            files={k:(ROOT/k).read_bytes() for k in ALLOWED};master=json.loads((ROOT/'data/store_master.json').read_text())
            # Resume the existing remote draft checkpoint before editing JSON.
            if a.resume:
                try:
                    head=api.get('/git/ref/heads/'+state['branch'])['object']['sha']
                    files={k:api.read(head,k) for k in ALLOWED}
                except HTTPError as e:
                    if e.code!=404:raise
            data,failures=initialize(api,state,files,master)
            (ROOT/'site/research.json').write_bytes(json_bytes(data));(ROOT/'site/search_failures.json').write_bytes(json_bytes(failures))
            (ROOT/'site/index.html').write_bytes(files['site/index.html'])
    else:
        state=json.loads(a.state.read_text())
        if a.command=='submit':state=submit(api,state,{k:(ROOT/k).read_bytes() for k in ALLOWED},json.loads((ROOT/'data/store_master.json').read_text()))
        else:
            from .routine_site import intake
            require(state.get('action')=='recover_publication','no_publication_to_recover')
            state=intake(api,state['pr'],REPO.split('/')[0])
    a.state.parent.mkdir(parents=True,exist_ok=True);a.state.write_bytes(json_bytes(state));print(json.dumps(state,ensure_ascii=False))

if __name__=='__main__':main()
