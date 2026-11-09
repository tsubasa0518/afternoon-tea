"""Synthetic current-run GET receipts. Never send requests to a real service."""
import copy,json,hashlib
from urllib.parse import quote
from afternoon_tea.research_completion import digest,payload_hash,required_tasks
from afternoon_tea.routine_site import ROOT,json_bytes,ALLOWED
from afternoon_tea.routine_renderer import render

BASE='b'*40;HEAD='a'*40;LOCK='c'*40;RUN='test_run_20261109'
WEEK='2026-11-09';WHEN='2026-11-09T07:18:00+09:00'


def fixture(master=None,baseline=None):
    master=master or json.loads((ROOT/'data/store_master.json').read_text())
    baseline=baseline or {'schema_version':1,'generated_at':'2026-11-09T07:17:00+09:00','period':{'start':WEEK,'end':'2026-12-19'},'shops':[]}
    data=copy.deepcopy(baseline)
    data['weekly_run']={'run_id':RUN,'week_key':WEEK,'base_commit':BASE,'baseline_sha256':digest(baseline),
                       'started_at':'2026-11-09T07:17:00+09:00','finished_at':'2026-11-09T08:00:00+09:00'}
    ex={'run_id':RUN,'week_key':WEEK,'reads':[],'tasks':[],'stop_reasons':[],'safety_violations':[],
        'verified_plans':[],'metrics':{'confirmed_shops':0,'confirmed_plans':0,'new_shops':0}}
    events=[]
    def event(name,**kwargs):
        row={'seq':len(events),'run_id':RUN,'at':WHEN,'event':name,'previous':events[-1]['sha256'] if events else None,**kwargs}
        row['sha256']=digest(row);events.append(row);return row
    event('begin');n=0
    for key,spec in required_tasks(master,baseline).items():
        n+=1;label=spec.get('station') or spec.get('shop_name');url='https://official.example.com/'+quote(key,safe='')
        body='TEST ONLY '+label+' アフタヌーンティーの既存確認・新規探索を実施、新規発見0件。'
        doc=hashlib.sha256(body.encode()).hexdigest();resource={'url_sha256':hashlib.sha256(url.encode()).hexdigest()}
        event('request',request_id=n,method='GET',resource=resource)
        event('response',request_id=n,status='http_success',http_status=200)
        receipt=event('document',request_id=n,status='success',page_sha256=doc,resource=resource)
        ex['reads'].append({'id':str(n),'run_id':RUN,'week_key':WEEK,'url':url,'checked_at':WHEN,'http_status':200,
                            'result':'read','document_sha256':doc,'document_event_sha256':receipt['sha256'],
                            'excerpt':body,**spec})
        ex['tasks'].append({'id':key,'run_id':RUN,'week_key':WEEK,'state':'completed','result':'no_discovery',
                            'conclusion':'TEST ONLY 必須の調査を実施、新規発見は0件。','read_ids':[str(n)]})
        if spec['purpose']=='discovery':ex['tasks'][-1].update(method='public_directory',searched_terms=[label+' アフタヌーンティー'],candidates=[])
    ex['communication_audits']=[{'run_id':RUN,'complete':True,'violations':[],'requests':n,'events':events,'chain_sha256':events[-1]['sha256']}]
    failures={'schema_version':1,'generated_at':WHEN,'failures':[],'research_execution':ex}
    seal(data,failures)
    return data,failures,master,baseline


def seal(data,failures):
    data['weekly_run']['payload_sha256']=payload_hash(data)
    data['weekly_run']['execution_sha256']=digest(failures['research_execution'])


def files(data,failures):
    return {'site/research.json':json_bytes(data),'site/search_failures.json':json_bytes(failures),
            'site/index.html':render(data,failures).encode()}
