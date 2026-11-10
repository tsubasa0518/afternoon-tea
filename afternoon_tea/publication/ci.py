"""Resume eligible PR intake after technical CI; never execute PR code."""
import json, os
from pathlib import Path
from afternoon_tea.publication.site import API, REPO, BRANCH_PREFIX, intake, write_summary

def resume(api,event,author):
    run=event['workflow_run']
    if run.get('event')!='pull_request':return []
    # Discover open PRs via the repository API; do not trust workflow artifacts.
    rows=api.get('/pulls?state=open&per_page=100')
    reports=[]
    for pr in rows:
        if (pr['head']['sha']==run['head_sha'] and pr['head']['repo'] and
            pr['head']['repo']['full_name']==REPO and pr['base']['ref']=='main' and
            pr['head']['ref'].startswith(BRANCH_PREFIX) and pr['title'].startswith('[weekly-site]') and
            pr['user']['login']==author and not pr['draft']):
            report=intake(api,pr['number'],author);reports.append(report)
            write_summary(report.get('merge','自動マージ・公開要求完了'),report)
            if report.get('merge')=='ci_failed':raise ValueError('latest_head_technical_ci_failed')
    return reports

def main():
    print(resume(API(),json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text()),os.environ.get('ROUTINE_AUTHOR') or REPO.split('/')[0]))
