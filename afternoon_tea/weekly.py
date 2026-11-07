"""Run a bounded JST research and staging-quality cycle; never publishes."""
import datetime as dt,json,subprocess,sys
from pathlib import Path
from .data import JST
from .master import ROOT,dumps
from .pipeline import protected_files
from .research_queue import run as run_queue
from .discovery import run as run_discovery
from .research_store import atomic_json

def run():
 protected_files();started=dt.datetime.now(JST);day=str(started.date());errors=[]
 try: discovery=run_discovery(max_pages=28,seconds=240)
 except Exception as e: discovery={'error':str(e),'complete_coverage':False};errors.append('discovery:'+str(e))
 try: out,state=run_queue(limit=300,seconds=600,max_requests=300,retry=True)
 except Exception as e:
  errors.append('research:'+str(e));out=ROOT/'.staging'/('weekly-failed-'+started.strftime('%Y%m%dT%H%M%S'));out.mkdir(parents=True,exist_ok=True)
  state=json.loads((ROOT/'research_data/state.json').read_text())
  atomic_json(out/'audit.json',{'day':day,'error':str(e),'items':state.get('items',[]),'areas':state.get('areas',[]),'stop_reason':'exception'})
 data=out/('data_'+day+'.json');audit=out/'audit.json'
 if data.exists():
  artifact_meta=json.loads((out/'artifact.json').read_text()) if (out/'artifact.json').exists() else {}
  html=Path(artifact_meta.get('html_directory',''))/('afternoon_tea_tokyo_'+day+'.html')
  if html.is_file():
   report=out/'quality_report.json'
   proc=subprocess.run([sys.executable,'-m','afternoon_tea.publication_quality','--data',str(data),'--audit',str(audit),'--html',str(html),'--report',str(report)],capture_output=True,text=True)
   if proc.returncode not in (0,2):errors.append('quality_cli:'+proc.stderr)
 else:errors.append('data_missing')
 unknown=[{'id':x.get('id'),'name':x.get('name'),'status':x.get('status'),'reason':x.get('reason')} for x in state.get('items',[]) if x.get('status') in ('unresolved','failed','unresearched')]
 atomic_json(out/'unresolved.json',unknown)
 summary={'day':day,'period_end':(started.date()+dt.timedelta(days=40)).isoformat(),'discovery':discovery,'queue':state.get('last_run',{}),'counts':{k:sum(x.get('status')==k for x in state.get('items',[])) for k in ('confirmed','excluded','unresolved','failed','unresearched')},'errors':errors,'reservation_operations':0,'published':False}
 atomic_json(out/'summary.json',summary);return out,summary,2 if errors else 0
if __name__=='__main__':
 out,summary,code=run();print(dumps({'output':str(out),'summary':summary}));raise SystemExit(code)
