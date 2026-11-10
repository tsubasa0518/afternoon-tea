"""Validate fresh, acquired, subject-bound evidence before merge/publication."""
import datetime as dt
import hashlib
import re
import unicodedata
from afternoon_tea.collection.campaign import reference, current_day, FRESH_DAYS, venue_key
from afternoon_tea.collection.catalog import load_master
from afternoon_tea.processing.dates import JST
from afternoon_tea.collection.evidence import validate_audit, source_document


def publication_gate(research,failures):
    campaign=failures.get('research_campaign')
    if not isinstance(campaign,dict):raise ValueError('research_campaign_missing')
    rows,sha=reference()
    if campaign.get('reference_sha256')!=sha:raise ValueError('campaign_reference_mismatch')
    if campaign.get('version')!=2:raise ValueError('campaign_evidence_migration_required')
    records=campaign.get('rows',[])
    if [r.get('no') for r in records]!=list(range(1,386)):raise ValueError('campaign_rows_incomplete')
    today=current_day();week=today-dt.timedelta(days=today.weekday())
    start=dt.date.fromisoformat(research['period']['start'])
    if not week<=start<=today:raise ValueError('campaign_not_current_week')
    began=dt.date.fromisoformat(campaign['started_on'])
    if began>today or not campaign.get('campaign_id'):raise ValueError('campaign_start_invalid')
    segments=campaign.get('audit_segments')
    if not isinstance(segments,dict) or not segments:raise ValueError('research_audit_missing')
    audited={}
    for key,snapshot in segments.items():
        if snapshot.get('run_id')!=key:raise ValueError('research_audit_id_mismatch')
        audited.update(validate_audit(snapshot))
    if 'communication_audit' in campaign:validate_audit(campaign['communication_audit'])
    def proofs(record,subject,aliases=()):
        sources=record.get('reviewed_sources')
        if not isinstance(sources,list) or not sources:raise ValueError('evidence_source_missing')
        texts=[]
        for source in sources:
            actual=campaign.get('documents',{}).get(source.get('document_id'),{}).get('subject_id')
            if actual not in (subject,*aliases):raise ValueError('evidence_subject_or_url_mismatch')
            text=source_document(campaign,source,actual,audited)
            stamp=dt.datetime.fromisoformat(source['checked_at'])
            if stamp.tzinfo is None:raise ValueError('evidence_timezone_missing')
            day=stamp.astimezone(JST).date()
            if not max(began,today-dt.timedelta(days=FRESH_DAYS))<=day<=today:
                raise ValueError('evidence_stale_or_future')
            texts.append(text)
        return texts
    entities=campaign.get('entities',{})
    def canonical(subject):
        entity=entities[subject]
        target=entity.get('collection_alias')
        if not target:return subject
        # An alias requires two acquired, reviewed identity proofs.
        owner=entities[target]
        link=next((v for v in owner.get('identity_links',[]) if v['entity_id']==subject),None)
        if not link or len(link['sources'])!=2:raise ValueError('identity_link_missing')
        identity_text=[]
        for identity_subject in (target,subject):
            evidence=next((s for s in link['sources'] if s['subject_id']==identity_subject),None)
            if not evidence:raise ValueError('identity_link_missing')
            identity_text+=proofs({'reviewed_sources':[evidence]},identity_subject)
        names={s.get('verified_name') for s in link['sources']};addresses={s.get('verified_address') for s in link['sources']}
        if len(names)!=1 or len(addresses)!=1 or not next(iter(names)) or not next(iter(addresses)):
            raise ValueError('identity_link_mismatch')
        if any(next(iter(names)) not in text or next(iter(addresses)) not in text for text in identity_text):
            raise ValueError('identity_link_unsupported')
        if owner.get('collection_alias'):raise ValueError('identity_alias_chain_forbidden')
        return target
    resolved={entity:canonical(entity) for entity in entities}
    def aliases_for(subject):return tuple(entity for entity,owner in resolved.items() if owner==subject)
    for record,original in zip(records,rows):
        if record.get('original')!=original:raise ValueError('campaign_original_changed')
        if record.get('status') not in {'reviewed','excluded'}:raise ValueError('campaign_list_research_incomplete')
        stable=venue_key(original['予約ページURL']) or 'url:'+hashlib.sha256(original['予約ページURL'].encode()).hexdigest()
        if record.get('entity_id')!=stable:raise ValueError('campaign_row_identity_mismatch')
        subject=resolved[record['entity_id']]
        if entities[subject]['queue']:raise ValueError('campaign_documents_pending')
        proofs(record,subject,aliases_for(subject))
    coverage=campaign.get('discovery',[])
    expected={a['no']:set(a['stations']) for a in load_master()['areas']}
    if len(coverage)!=len(expected) or {a.get('area_no') for a in coverage}!=set(expected):raise ValueError('campaign_discovery_incomplete')
    for area in coverage:
        no=area['area_no']
        if area.get('status')!='reviewed' or set(area.get('stations',[]))!=expected[no]:raise ValueError('campaign_discovery_incomplete')
        proofs(area,'area:'+str(no))
        station_records=area.get('station_evidence',{})
        if set(station_records)!=expected[no]:raise ValueError('station_evidence_missing')
        for station,record in station_records.items():
            text='\n'.join(proofs(record,'area:'+str(no)+':station:'+station))
            if station not in text:raise ValueError('station_not_in_evidence')
    def fact_supported(field,value,text):
        normalized=lambda v:re.sub(r'\s+','',unicodedata.normalize('NFKC',str(v)))
        body=normalized(text)
        if field=='price_yen':
            return any(int(n.replace(',',''))==value for n in re.findall(r'(?<![0-9])[0-9][0-9,]*(?![0-9])',body))
        if field in ('start','end'):
            date=dt.date.fromisoformat(value)
            return any(normalized(v) in body for v in [value,f'{date.year}/{date.month}/{date.day}',f'{date.year}年{date.month}月{date.day}日'])
        return normalized(value) in body
    # Every published plan must refer to reviewed acquisition and matching facts.
    for shop in research.get('shops',[]):
        if not shop.get('plans'):continue
        if shop.get('area_no')==15:raise ValueError('outside_research_scope')
        subject=canonical(shop['research_entity_id'])
        for plan in shop.get('plans',[]):
            sources=plan.get('research_evidence',[])
            source_texts=proofs({'reviewed_sources':sources},subject,aliases_for(subject))
            if not any(s['url']==plan.get('source_url') and s['checked_at']==plan.get('checked_at') for s in sources):raise ValueError('plan_provenance_mismatch')
            for field in ('plan_name','price_yen','start','end','menu'):
                if plan.get(field) is not None and not any(field in s.get('verified_fields',{}) and s['verified_fields'][field]==plan[field] and fact_supported(field,plan[field],s['basis']) for s,text in zip(sources,source_texts)):
                    raise ValueError('plan_field_evidence_missing:'+field)
    if campaign.get('phase')!='complete' or campaign.get('publication_ready') is not True:raise ValueError('campaign_not_ready')

# Approved maintenance publication: preserve the already-published 2026-11-09
# snapshot byte-for-byte. This is never an exemption for new weekly PR intake.
RETAINED_SNAPSHOT = {'research.json': 'b5531394b14581e5d54c8faec94a0054a14b17da01951cd63f4d5f97f21255d6', 'search_failures.json': 'c6aab1ad0bb89907c17b4e16174c241bf4bc77c746a594315bf0c9260d353fc4'}

def retained_snapshot(research_bytes, failures_bytes):
    return all(hashlib.sha256(value).hexdigest() == RETAINED_SNAPSHOT[name]
               for name,value in [('research.json',research_bytes),('search_failures.json',failures_bytes)])
