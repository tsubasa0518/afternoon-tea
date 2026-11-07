"""Offline publication gate. It reports policy; it never writes public files."""
import argparse, datetime as dt, json
from pathlib import Path
from .master import ROOT, load_master
from .pipeline import protected_files
from .validation import load_json, validate_data
from .html_validation import validate_html
from .extraction import Document
from .research_store import atomic_json
from .publication_safety import area_metrics, current_evidence

DEFAULTS={"min_confirmed_shops":1,"min_master_review_rate":1.0,"min_area_research_rate":1.0,"max_unresolved_master_rate":0.0,"max_shop_drop_rate":0.1,"max_age_days":7,"require_first_migration_approval":True}

def card_count(html): return len(Document(html).root.find('article'))
def check(ok, evidence): return {"status":"pass" if ok else "fail","evidence":evidence}
def evaluate(data,audit,html,baseline_html,config,now=None,approval=False):
 now=now or dt.date.today();master=load_master();checks={}; errors=[]
 try:
  summary=validate_data(data,master); checks['json_14_areas']=check(True,summary)
 except Exception as e:summary={};checks['json_14_areas']=check(False,str(e));errors.append('json_validation')
 try:
  hs=validate_html(html,data);checks['html_structure']=check(True,hs)
 except Exception as e:hs={};checks['html_structure']=check(False,str(e));errors.append('html_validation')
 confirmed=[s for a in data.get('areas',[]) for g in a.get('cats',{}).values() for s in g.get('shops',[]) if s.get('research',{}).get('status')=='confirmed']
 plans=sum(len(s.get('plans',[])) for s in confirmed);urls=[json.dumps(x.get('links',[None])[0],sort_keys=True,ensure_ascii=False) for x in confirmed]
 proof_ok=bool(confirmed) and all(s.get('research',{}).get('evidence') and s.get('plans') and s.get('links') for s in confirmed)
 checks['confirmed_evidence']=check(proof_ok,{'shops':len(confirmed),'plans':plans,'required_provenance_complete':proof_ok})
 checks['safe_unique_urls']=check(len(urls)==len(set(urls)) and all(u for u in urls),{'count':len(urls),'unique':len(set(urls))})
 day=dt.date.fromisoformat(data.get('generated','1900-01-01'));age=(now-day).days
 checks['freshness']=check(0<=age<=config['max_age_days'],{'generated':str(day),'age_days':age,'max_age_days':config['max_age_days']})
 states=[x.get('status') for x in audit.get('items',[])];counts={k:states.count(k) for k in ('confirmed','excluded','unresolved','failed','unresearched')}
 checks['research_complete']=check(counts['unresolved']==0 and counts['failed']==0 and counts['unresearched']==0 and not audit.get('stop_reason'),counts|{'stop_reason':audit.get('stop_reason')})
 areas=audit.get('areas',[]);rates=area_metrics(areas);area_rate=rates['completion_rate']
 checks['area_exploration']=check(rates['valid'] and area_rate>=config['min_area_research_rate'],rates)
 checks['current_run_evidence']=check(current_evidence(data,audit),{'required':'Current run receipts, exact shop hashes and fetched/verified timestamps; restored data is not fresh'})
 master_items=[x for x in audit.get('items',[]) if x.get('kind')=='master'];reviewed=sum(x.get('status') in ('confirmed','excluded') for x in master_items)/len(master_items) if master_items else 0
 checks['master_coverage']=check(reviewed>=config['min_master_review_rate'] and counts['unresolved']/max(1,len(master_items))<=config['max_unresolved_master_rate'],{'reviewed_rate':reviewed,'unresolved':counts['unresolved'],'master_total':len(master_items)})
 checks['priority_audit']=check(bool(audit.get('items')) and all(len(x.get('attempts',[])) for x in audit['items'] if x.get('status')=='confirmed'),{'confirmed':len(confirmed),'audit_items':len(audit.get('items',[]))})
 before,after=card_count(baseline_html),card_count(html);drop=max(0,(before-after)/max(1,before))
 checks['baseline_delta']=check(drop<=config['max_shop_drop_rate'],{'previous_shops':before,'candidate_shops':after,'drop_rate':drop,'new_shops':max(0,after-before)})
 checks['minimum_shops']=check(len(confirmed)>=config['min_confirmed_shops'],len(confirmed))
 checks['interrupted_run']=check(not audit.get('stop_reason') and audit.get('last_run',{}).get('complete_coverage') is True,audit.get('last_run',{}))
 checks['test_data_absent']=check(data.get('metadata',{}).get('purpose')=='research' and not any('TEST_ONLY' in str(s) for s in confirmed),data.get('metadata',{}).get('purpose'))
 checks['initial_migration_approval']=check(not config['require_first_migration_approval'] or approval,{'required':config['require_first_migration_approval'],'provided':approval})
 # Structural success yields STAGING_VALID; human review is required until every publication gate passes.
 structural=checks['json_14_areas']['status']=='pass' and checks['html_structure']['status']=='pass'
 hard_complete=(len(confirmed)>0 and len(master_items)==70 and counts['unresolved']==0 and counts['failed']==0 and counts['unresearched']==0 and len(areas)==14 and all(x.get('discovery_status')=='complete' for x in areas) and drop<=0.5 and (not config['require_first_migration_approval'] or approval))
 all_pass=structural and hard_complete and all(v['status']=='pass' for k,v in checks.items() if k not in ('json_14_areas','html_structure'))
 status='APPROVED_FOR_PUBLICATION' if all_pass else 'REVIEW_REQUIRED' if structural and len(confirmed)>0 else 'STAGING_VALID'
 return {'status':status,'publishable':status=='APPROVED_FOR_PUBLICATION','score':round(sum(v['status']=='pass' for v in checks.values())/len(checks),3),'checks':checks,'metrics':{'confirmed_shops':len(confirmed),'confirmed_plans':plans,'previous_shops':before,'candidate_shops':after,'master_review_rate':reviewed,'area_exploration_rate':area_rate,'area_started_rate':rates['started_rate'],'area_completion_rate':rates['completion_rate'],'unresolved':counts['unresolved'],'failed':counts['failed'],'expired_plans':sum(bool(p.get('end') and p['end']<str(now)) for s in confirmed for p in s.get('plans',[]))},'failed_reasons':[k for k,v in checks.items() if v['status']=='fail'],'next_step':'No publication action is performed by this program.'}

def report_destination(value):
 path=Path(value)
 if (ROOT/'.staging').is_symlink() or path.is_symlink():raise ValueError('report_symlink_forbidden')
 path=path.resolve();staging=(ROOT/'.staging').resolve()
 if staging not in path.parents:raise ValueError('report_must_be_inside_staging')
 return path

def main():
 p=argparse.ArgumentParser();p.add_argument('--data',required=True);p.add_argument('--audit',required=True);p.add_argument('--html',required=True);p.add_argument('--baseline-html',default=str(ROOT/'docs/index.html'));p.add_argument('--config',default=str(ROOT/'data/publication_quality.json'));p.add_argument('--report',required=True);p.add_argument('--initial-migration-approved',action='store_true');a=p.parse_args()
 protected_files();destination=report_destination(a.report);cfg=load_json(a.config);cfg={**DEFAULTS,**cfg};report=evaluate(load_json(a.data),load_json(a.audit),Path(a.html).read_text(),Path(a.baseline_html).read_text(),cfg,approval=a.initial_migration_approved);atomic_json(destination,report);print(json.dumps({'status':report['status'],'publishable':report['publishable'],'reasons':report['failed_reasons'],'score':report['score']}));return 0 if report['publishable'] else 2
if __name__=='__main__':raise SystemExit(main())
