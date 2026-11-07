"""One audited research execution. Artifacts only; no publication client."""
import argparse
import datetime as dt
import json
from pathlib import Path
from .data import JST
from .master import ROOT,dumps
from .pipeline import protected_files,staging_directory
from .research_queue import run as run_queue
from .discovery import run as run_discovery
from .research_store import atomic_json
from .run_context import RunContext
from .research import Browser
from .publication_quality import evaluate,DEFAULTS
from .publication_bundle import prepare,sha


def run(directory=None,limit=300,seconds=600,max_requests=300,discovery_pages=28,browser=None):
    protected_files();started=dt.datetime.now(JST);day=str(started.date());errors=[]
    directory=Path(directory or ROOT/'research_data')
    output=staging_directory()/('weekly-'+started.strftime('%Y%m%dT%H%M%S%f'));output.mkdir()
    context=RunContext(output)
    browser=browser or Browser(delay=1,timeout=8,max_requests=max_requests,audit=context.journal)
    state={};out=output;discovery={};quality=None;html=None
    try:
        discovery=run_discovery(directory=directory,max_pages=discovery_pages,seconds=min(seconds,240),browser=browser)
        if context.journal.snapshot()['violations']:raise RuntimeError('safety_violation_during_discovery')
        out,state=run_queue(limit=limit,seconds=seconds,max_requests=max_requests,directory=directory,browser=browser,retry=True,context=context,fresh=True)
        if state.get('stop_reason'):errors.append('research_interrupted:'+state['stop_reason'])
    except Exception as e:
        errors.append('research:'+type(e).__name__+':'+str(e))
        if not state:
            try:state=json.loads((directory/'state.json').read_text())
            except (OSError,ValueError):state={}
        state['current_run']=context.snapshot(browser)
        atomic_json(out/'audit.json',{'current_run':state['current_run'],'items':state.get('items',[]),'areas':state.get('areas',[]),'stop_reason':'exception','errors':errors})
    # Final integrity snapshot includes discovery and store HTTP traffic.
    communication=context.snapshot(browser)['reservation_audit']
    atomic_json(out/'communication_audit.json',communication)
    if not communication['complete']:errors.append('communication_audit_incomplete')
    if communication['violations']:errors.append('reservation_safety_violation')
    data=out/('data_'+day+'.json');audit=out/'audit.json'
    try:
        if not data.exists():raise ValueError('data_missing')
        meta=json.loads((out/'artifact.json').read_text()) if (out/'artifact.json').exists() else {}
        html=Path(meta.get('html_directory',''))/('afternoon_tea_tokyo_'+day+'.html')
        if not html.is_file():raise ValueError('html_missing')
        dataset=json.loads(data.read_text());audit_data=json.loads(audit.read_text())
        quality=evaluate(dataset,audit_data,html.read_text(),(ROOT/'docs/index.html').read_text(),DEFAULTS)
        quality.update(run_id=context.id,data_sha256=sha(data.read_bytes()),audit_sha256=sha(audit.read_bytes()),html_sha256=sha(html.read_bytes()))
        atomic_json(out/'quality_report.json',quality)
        if any(quality.get('checks',{}).get(k,{}).get('status')!='pass' for k in ('json_14_areas','html_structure')):raise ValueError('structural_validation_failed')
        prepare(data,audit,html,ROOT/'docs/index.html',out/'bundle',context.id,'local-uncommitted' if not __import__('os').environ.get('GITHUB_SHA') else __import__('os').environ['GITHUB_SHA'])
    except Exception as e:errors.append(str(e))
    unknown=[{'id':x.get('id'),'name':x.get('name'),'status':x.get('status'),'reason':x.get('reason')} for x in state.get('items',[]) if x.get('status') in ('unresolved','failed','unresearched')]
    atomic_json(out/'unresolved.json',unknown);atomic_json(out/'errors.json',errors)
    receipts=context.receipts
    summary={'run_id':context.id,'day':day,'generated_at':dt.datetime.now(JST).isoformat(),'period_end':(started.date()+dt.timedelta(days=40)).isoformat(),
        'discovery':discovery,'queue':state.get('last_run',{}),'counts':{k:sum(x.get('status')==k for x in state.get('items',[])) for k in ('confirmed','excluded','unresolved','failed','unresearched')},
        'newly_verified_shops':len(receipts),'restored_confirmed_shops':sum(x.get('status')=='confirmed' and x['id'] not in receipts for x in state.get('items',[])),
        'errors':errors,'reservation_operations':communication['operations_executed'],'reservation_audit_complete':communication['complete'],
        'communication_requests':communication['requests'],'quality_status':quality['status'] if quality else None,'published':False}
    atomic_json(out/'summary.json',summary);protected_files();return out,summary,2 if errors else 0

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--state-dir');p.add_argument('--limit',type=int,default=300);p.add_argument('--seconds',type=int,default=600);p.add_argument('--max-requests',type=int,default=300);p.add_argument('--discovery-pages',type=int,default=28);a=p.parse_args()
    if not 1<=a.limit<=300 or not 1<=a.seconds<=600 or not 1<=a.max_requests<=300 or not 1<=a.discovery_pages<=28:p.error('bounded positive limits required')
    out,summary,code=run(a.state_dir,a.limit,a.seconds,a.max_requests,a.discovery_pages);print(dumps({'output':str(out),'summary':summary}));raise SystemExit(code)
