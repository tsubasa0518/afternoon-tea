"""Explicit maintenance-only resolution of the legacy No.1 directory detour.

Not called by the scheduled collector. The failed journal remains historical;
none of its documents or observations are promoted to publishable v2 evidence.
"""
import datetime as dt
import hashlib
from urllib.parse import urlsplit
from afternoon_tea.collection.official import links
from afternoon_tea.common import digest

BLOCKED='https://restaurant.ikyu.com/area/tokyo/t-scene2981/'
STORE='https://restaurant.ikyu.com/107408/'


def resume_legacy_directory_stop(campaign,reason):
    if not isinstance(reason,str) or not reason.strip():raise ValueError('resume_reason_required')
    legacy=campaign.get('legacy_checkpoint',{})
    audit=legacy.get('communication_audit',{})
    row=campaign['rows'][0]
    if (campaign.get('version')!=2 or row['no']!=1 or row['status']!='interrupted'
        or row['original']['予約ページURL']!=STORE
        or legacy.get('stop_reason')!='forbidden_operation'
        or any(r['status']=='interrupted' for r in campaign['rows'][1:])):
        raise ValueError('not_legacy_directory_incident')
    # Check the original failed chain without reclassifying it as successful.
    previous=None;requests={};pending=set();blocked=hashlib.sha256(BLOCKED.encode()).hexdigest()
    violations=[]
    for i,event in enumerate(audit.get('events',[])):
        if (event.get('seq')!=i or event.get('run_id')!=audit.get('run_id')
            or event.get('previous')!=previous
            or event.get('sha256')!=digest({k:v for k,v in event.items() if k!='sha256'})):
            raise ValueError('legacy_audit_chain_invalid')
        previous=event['sha256']
        if event['event']=='request':
            request=event['request_id']
            if request in requests or event.get('method')!='GET':raise ValueError('legacy_request_invalid')
            requests[request]=event['resource']['url_sha256'];pending.add(request)
        if event['event']=='response':
            if event['request_id'] not in pending:raise ValueError('legacy_response_invalid')
            pending.remove(event['request_id'])
        if event.get('violation') or event.get('status')=='forbidden':
            resource=event.get('resource',{}).get('url_sha256',requests.get(event.get('request_id')))
            if event.get('reason')!='redirect_blocked_before_follow' or resource!=blocked:
                raise ValueError('different_legacy_violation')
            violations.append(event)
    if (not violations or audit.get('violations')!=violations or audit.get('complete') is not True
        or previous!=audit.get('chain_sha256') or pending or audit.get('requests')!=len(requests)):
        raise ValueError('legacy_audit_incomplete')
    entity=campaign['entities'][row['entity_id']]
    prefix=urlsplit(STORE).path
    if entity.get('collection_alias') or entity['rows']!=[1] or entity.get('documents'):
        raise ValueError('resume_entity_changed')
    # Exercise the current link filter locally before authorizing this route.
    plan=STORE+'plan123456'
    raw='<a href="'+BLOCKED+'">アフタヌーンティー</a><a href="/100000/">アフタヌーンティー</a><a href="'+plan+'">アフタヌーンティー</a>'
    _,found,_,_=links(raw,STORE,(),prefix)
    if [u for _,u,_ in found]!=[plan]:raise ValueError('store_scope_mock_failed')
    resolution={'at':dt.datetime.now(dt.timezone.utc).isoformat(),'reason':reason,
        'legacy_audit_sha256':digest(audit),'legacy_chain_sha256':previous,
        'blocked_url_sha256':blocked,'resume_url':STORE,'path_prefix':prefix,
        'local_mock':'store_plan_only; directory_and_other_store_excluded',
        'legacy_evidence_promoted':False}
    campaign.setdefault('resume_resolutions',[]).append(resolution)
    campaign.setdefault('blocked_url_sha256',[]).append(blocked)
    entity['queue']=[{'url':STORE,'depth':0,'prefix':prefix}]
    row.update(status='needs_collection',reviewed_sources=[],reason='audited_store_scoped_resume')
    campaign['publication_ready']=False
    campaign['stop_reason']='explicit_scoped_resume'
    return resolution
