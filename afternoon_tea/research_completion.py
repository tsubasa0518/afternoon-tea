"""Fail-closed run-scoped research completion, separate from technical validation.

Evidence is an auditable public-document record, not a claim that HTTP success
or a complete=true flag proves research. Required work comes from trusted main.
"""
import copy
import datetime as dt
import hashlib
import json
import re
from .data import JST
from .read_only import check_url
from urllib.parse import urlsplit


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def week_key(value=None):
    stamp=value or dt.datetime.now(JST)
    if isinstance(stamp,str):stamp=dt.date.fromisoformat(stamp) if len(stamp)==10 else dt.datetime.fromisoformat(stamp)
    if isinstance(stamp,dt.datetime):
        if stamp.tzinfo is None:raise ValueError('week_timezone_required')
        stamp=stamp.astimezone(JST).date()
    return (stamp-dt.timedelta(days=stamp.weekday())).isoformat()


def required_tasks(master, baseline):
    tasks={}
    for area in master['areas']:
        for station in area['stations']:
            for purpose in ('existing','discovery'):
                key=f"station:{area['no']}:{station}:{purpose}"
                tasks[key]={'area_no':area['no'],'station':station,'purpose':purpose}
    for shop in baseline['shops']:
        key='shop:'+shop['id']
        tasks[key]={'shop_id':shop['id'],'shop_name':shop['name'],'purpose':'existing'}
    return tasks


def payload_hash(research):
    return digest({k:v for k,v in research.items() if k!='weekly_run'})


def stamp(value):
    if not isinstance(value,str):raise ValueError('timestamp_required')
    value=dt.datetime.fromisoformat(value)
    if value.tzinfo is None:raise ValueError('timestamp_timezone_required')
    return value


def collection_totals(research, execution, baseline):
    shops={s['id']:s for s in research['shops']};old={s['id'] for s in baseline['shops']}
    old_plans={(s['id'],p['plan_name']) for s in baseline['shops'] for p in s.get('plans',[])}
    sources={};refs=set();verified=set();new=set();menus=0
    for item in execution['verified_plans']:
        sid,pn=item['shop_id'],item['plan_name'];key=(sid,pn)
        if key in refs:raise ValueError('duplicate_plan_metric')
        refs.add(key);verified.add(sid)
        if sid not in old:new.add(sid)
        plan=next(p for p in shops[sid]['plans'] if p['plan_name']==pn)
        host=urlsplit(plan.get('source_url') or shops[sid].get('source_url')).hostname
        row=sources.setdefault(host,{'shop_ids':set(),'new_ids':set(),'confirmed_plans':0,'menu_plans':0})
        row['shop_ids'].add(sid);row['new_ids'].update([sid] if sid not in old else [])
        row['confirmed_plans']+=1;row['menu_plans']+=bool(plan.get('menu'));menus+=bool(plan.get('menu'))
    return {'run_id':execution['run_id'],'week_key':execution['week_key'],
            'confirmed_shops':len(verified),'confirmed_plans':len(refs),'new_shops':len(new),
            'added_plans':len(refs-old_plans),'menu_plans':menus,
            'by_source':[{'host':host,'confirmed_shops':len(row['shop_ids']),'new_shops':len(row['new_ids']),
                          'confirmed_plans':row['confirmed_plans'],'menu_plans':row['menu_plans']}
                         for host,row in sorted(sources.items())]}


def validate(research, failures, master, baseline, *, expected_week=None, now=None):
    def need(ok,reason):
        if not ok:raise ValueError('research_incomplete:'+reason)
    try:
        run=research['weekly_run']; execution=failures['research_execution']
        need(isinstance(run,dict) and isinstance(execution,dict),'missing_run')
        run_id=run['run_id']; week=run['week_key']
        need(isinstance(run_id,str) and bool(re.fullmatch(r'[a-zA-Z0-9_-]{16,100}',run_id)),'invalid_run_id')
        need(week_key(week)==week and week==week_key(research['period']['start']),'week_mismatch')
        if expected_week is not None:need(week==expected_week,'unexpected_week')
        first,last=stamp(run['started_at']),stamp(run['finished_at'])
        now=now or dt.datetime.now(JST)
        need(first<=last<=now+dt.timedelta(minutes=5) and week_key(first)==week,'run_time_mismatch')
        need(last-first<=dt.timedelta(days=7),'run_too_long')
        from .weekly_review import review
        need(not review(research)['errors'],'invalid_period')
        need(first.astimezone(JST).date().isoformat()==research['period']['start'],'period_run_mismatch')
        need(execution.get('run_id')==run_id and execution.get('week_key')==week,'execution_mismatch')
        need(run.get('baseline_sha256')==digest(baseline),'baseline_mismatch')
        need(run.get('payload_sha256')==payload_hash(research) and run.get('execution_sha256')==digest(execution),'payload_changed')
        need(isinstance(execution.get('stop_reasons'),list) and not execution['stop_reasons'],'interrupted')
        need(isinstance(execution.get('safety_violations'),list) and not execution['safety_violations'],'safety_stop')
        from .publication_safety import valid_communication
        audits=execution['communication_audits']
        need(isinstance(audits,list) and bool(audits),'missing_communication_audit')
        receipts={}
        for audit in audits:
            need(valid_communication(audit,run_id),'invalid_communication_audit')
            requests={e['request_id']:e for e in audit['events'] if e['event']=='request'}
            responses={e['request_id']:e for e in audit['events'] if e['event']=='response'}
            for event in audit['events']:
                need(first<=stamp(event['at'])<=last,'stale_audit')
                if event['event']=='document':
                    rid=event['request_id'];need(rid in requests and rid in responses,'orphan_document')
                    need(responses[rid].get('http_status')==200 and responses[rid].get('status')=='http_success','document_http_failed')
                    need(event.get('status')=='success','document_not_successful')
                    receipts[event['sha256']]=(event,requests[rid])
        reads=execution['reads']; tasks=execution['tasks']
        need(isinstance(reads,list) and isinstance(tasks,list),'invalid_records')
        index={}; required=required_tasks(master,baseline)
        for row in reads:
            need(isinstance(row,dict),'invalid_read')
            key=row['id']; need(isinstance(key,str) and key not in index,'duplicate_read')
            need(row.get('run_id')==run_id and row.get('week_key')==week,'stale_read')
            need(first<=stamp(row['checked_at'])<=last,'stale_read_time')
            need(type(row.get('http_status')) is int and row['http_status']==200 and row.get('result')=='read','not_read')
            url=row['url'];check_url(url,public_hosts=[urlsplit(url).hostname])
            need(bool(re.fullmatch(r'[0-9a-f]{64}',row['document_sha256'])),'missing_document_digest')
            need(isinstance(row.get('excerpt'),str) and 10<=len(row['excerpt'])<=4000,'missing_excerpt')
            event,request=receipts[row['document_event_sha256']]
            need(event['page_sha256']==row['document_sha256'] and
                 request['resource']['url_sha256']==hashlib.sha256(url.encode()).hexdigest(),'document_receipt_mismatch')
            index[key]=row
        found={};discovery_urls=set()
        for task in tasks:
            need(isinstance(task,dict) and task.get('id') in required and task['id'] not in found,'unexpected_or_duplicate_task')
            spec=required[task['id']]
            if spec['purpose']=='discovery':
                need(task.get('method') in ('public_directory','public_release','official_opening','area_listing'),'discovery_method_missing')
                terms=task.get('searched_terms')
                need(isinstance(terms,list) and terms and all(isinstance(t,str) for t in terms) and
                     any(spec['station'] in t and ('アフタヌーンティー' in t or 'afternoon tea' in t.lower()) for t in terms),'station_search_scope_missing')
                need(isinstance(task.get('candidates'),list),'discovery_results_missing')
            need(task.get('run_id')==run_id and task.get('week_key')==week,'stale_task')
            need(task.get('state')=='completed' and task.get('result') in ('confirmed','no_discovery','fields_unknown','not_offered'),'unfinished_task')
            need(isinstance(task.get('conclusion'),str) and len(task['conclusion'].strip())>=10,'missing_conclusion')
            refs=task.get('read_ids');need(isinstance(refs,list) and refs and len(set(refs))==len(refs),'missing_read_refs')
            for ref in refs:
                need(ref in index,'unknown_read_ref')
            # A common index cannot be recycled as completion for every station.
            # At least one actual excerpt must identify this specific station or
            # the specific existing shop, and carry the exact scoped purpose.
            eligible=[index[r] for r in refs if index[r].get('purpose')==spec['purpose']]
            if 'station' in spec:
                eligible=[r for r in eligible if r.get('area_no')==spec['area_no'] and r.get('station')==spec['station'] and spec['station'] in r['excerpt']]
            else:
                terms=[re.sub(r'[\W_]+','',t).casefold() for t in re.split(r'[/／]',re.split(r'[（(]',spec['shop_name'])[0]) if t.strip()]
                eligible=[r for r in eligible if r.get('shop_id')==spec['shop_id'] and
                          all(t in re.sub(r'[\W_]+','',r['excerpt']).casefold() for t in terms)]
            need(bool(eligible),'scope_evidence_missing')
            if spec['purpose']=='discovery':
                distinct=next((r['url'] for r in eligible if r['url'] not in discovery_urls),None)
                need(distinct is not None,'shared_listing_only')
                discovery_urls.add(distinct)
            found[task['id']]=task
        need(set(found)==set(required),'required_work_missing')
        metrics=execution['metrics'];need(isinstance(metrics,dict),'missing_metrics')
        # Metrics are rebuilt from current run result references, not carried
        # collection_summary or total displayed shops. Null prices remain legal.
        verified=set(); new=set(); plan_refs=set()
        old_ids={s['id'] for s in baseline['shops']}
        shops={s['id']:s for s in research['shops']}
        results=execution['verified_plans'];need(isinstance(results,list),'invalid_verified_plans')
        for item in results:
            sid,pn=item['shop_id'],item['plan_name'];ref=(sid,pn)
            need(ref not in plan_refs and sid in shops,'duplicate_or_unknown_plan')
            matching=[p for p in shops[sid].get('plans',[]) if p['plan_name']==pn]
            need(len(matching)==1,'plan_reference_ambiguous')
            p=matching[0];read=index[item['read_id']]
            need(read['url']==(p.get('source_url') or shops[sid].get('source_url')),'plan_source_mismatch')
            need(stamp(p.get('checked_at') or shops[sid].get('checked_at'))==stamp(read['checked_at']),'plan_check_time_mismatch')
            quote=p.get('evidence_quote')
            need(isinstance(quote,str) and len(quote.strip())>=5 and
                 re.sub(r'\s+','',quote) in re.sub(r'\s+','',read['excerpt']),'plan_quote_not_in_current_read')
            plan_refs.add(ref);verified.add(sid)
            if sid not in old_ids:new.add(sid)
        actual={'confirmed_shops':len(verified),'confirmed_plans':len(plan_refs),'new_shops':len(new)}
        need(all(type(metrics.get(k)) is int and metrics[k]==v for k,v in actual.items()),'stale_metrics')
        summary=research.get('collection_summary')
        if summary is not None:
            need(isinstance(summary,dict) and summary.get('run_id')==run_id and summary.get('week_key')==week,'stale_collection_summary')
            need(all(type(summary.get(k)) is int and summary[k]==v for k,v in actual.items()),'stale_collection_metrics')
            totals=collection_totals(research,execution,baseline)
            need(all(summary.get(k)==v for k,v in totals.items()),'stale_collection_details')
        need(all(sid in verified for sid in shops if sid not in old_ids),'unverified_new_shop')
        # Never advance a carried-forward fact's date without a current receipt.
        for sid,shop in shops.items():
            prior=next((s for s in baseline['shops'] if s['id']==sid),None)
            if prior:
                for p in shop.get('plans',[]):
                    previous=next((q for q in prior.get('plans',[]) if q['plan_name']==p['plan_name']),None)
                    if previous and p.get('checked_at')!=previous.get('checked_at'):
                        need((sid,p['plan_name']) in plan_refs,'unreceipted_check_date')
        return {'research_completion':'passed','week_key':week,'run_id':run_id,'required_tasks':len(required),**actual}
    except (KeyError,TypeError,AttributeError,ValueError) as error:
        if isinstance(error,ValueError) and str(error).startswith('research_incomplete:'):raise
        raise ValueError('research_incomplete:invalid_or_missing_evidence') from error
