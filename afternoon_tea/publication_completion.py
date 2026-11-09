"""Trusted-main checks for the exact candidate or delivery commit and bytes."""
import json
from .research_completion import validate, digest, week_key


def gate(api,commit,files,base_commit=None):
    from .routine_site import sha, require
    from .weekly_run import read_lock,publications
    data=json.loads(files['site/research.json']);failures=json.loads(files['site/search_failures.json'])
    from .routine_renderer import render
    require(render(data,failures).encode()==files['site/index.html'],'fixed_renderer_bytes_mismatch')
    parents=api.get('/git/commits/'+commit)['parents']
    parent=base_commit or (parents[0]['sha'] if parents else None)
    require(parent is not None,'research_incomplete:baseline_missing')
    baseline=json.loads(api.read(parent,'site/research.json'))
    run=data.get('weekly_run',{})
    if run.get('base_commit')==parent:
        master=json.loads(api.read(parent,'data/store_master.json'))
        report=validate(data,failures,master,baseline)
        lock=read_lock(api,run['week_key']);require(lock is not None,'research_incomplete:checkpoint_missing')
        _,record=lock
        require(record.get('state') in ('submitted','published') and record.get('run_id')==run['run_id'] and
                record.get('base_commit')==parent and record.get('files_sha256')=={p:sha(v) for p,v in files.items()},'research_incomplete:checkpoint_mismatch')
        # The head accepted by the coordinator is immutable. A merge commit may
        # differ, but its three file digests must be exactly the checkpoint.
        if base_commit:require(record.get('head_sha')==commit,'research_incomplete:head_mismatch')
        return {**report,'coordinator_branch':record['branch'],'coordinator_pr':record['pr']}
    if base_commit is not None:raise ValueError('research_incomplete:weekly_run_base_mismatch')
    # A maintenance PR may regenerate HTML without falsely declaring a new
    # weekly investigation. Reuse only IDENTICAL JSON from a proven published
    # main ancestor; never an unreviewed PR payload or a complete=true bypass.
    current=parent
    for _ in range(100):
        prior={p:api.read(current,p) for p in ('site/research.json','site/search_failures.json')}
        require(all(prior[p]==files[p] for p in prior),'research_incomplete:maintenance_changed_research')
        if publications(api,current):
            saved=json.loads(prior['site/research.json']);saved_failures=json.loads(prior['site/search_failures.json'])
            saved_run=saved.get('weekly_run',{})
            require(bool(saved_run.get('base_commit')),'research_incomplete:published_baseline_not_complete')
            original_base=saved_run['base_commit']
            validate(saved,saved_failures,json.loads(api.read(original_base,'data/store_master.json')),
                     json.loads(api.read(original_base,'site/research.json')))
            lock=read_lock(api,saved_run['week_key']);require(lock is not None,'research_incomplete:baseline_checkpoint_missing')
            record=lock[1]
            require(record.get('run_id')==saved_run['run_id'] and all(record.get('files_sha256',{}).get(p)==sha(v) for p,v in prior.items()),
                    'research_incomplete:baseline_checkpoint_mismatch')
            return {'research_completion':'published_baseline_reused','baseline_commit':current}
        ancestors=api.get('/git/commits/'+current)['parents']
        require(bool(ancestors),'research_incomplete:no_published_baseline')
        current=ancestors[0]['sha']
    raise ValueError('research_incomplete:publication_history_limit')
