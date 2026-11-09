"""Fail closed on campaign incompleteness before merge or publication."""
import datetime as dt
import hashlib
from .list_research import reference, current_day
from .master import load_master
from .data import JST


def publication_gate(research, failures):
    campaign=failures.get('research_campaign')
    if not isinstance(campaign,dict): raise ValueError('research_campaign_missing')
    rows,digest=reference()
    if campaign.get('reference_sha256')!=digest: raise ValueError('campaign_reference_mismatch')
    records=campaign.get('rows',[])
    if [r.get('no') for r in records]!=list(range(1,386)):
        raise ValueError('campaign_rows_incomplete')
    start=dt.date.fromisoformat(research['period']['start'])
    today=current_day()
    week=today-dt.timedelta(days=today.weekday())
    if not week<=start<=today or campaign.get('week_key')!=week.isoformat():
        raise ValueError('campaign_not_current_week')
    # Current run evidence only; old observations cannot approve a new publication.
    def evidence(record):
        sources=record.get('reviewed_sources')
        if not isinstance(sources,list) or not sources: return False
        try:
            return all(isinstance(s,dict) and s['url'].startswith('https://') and
                       bool(s['basis'].strip()) and dt.datetime.fromisoformat(s['checked_at']).tzinfo is not None and
                       dt.datetime.fromisoformat(s['checked_at']).astimezone(JST).date()==start for s in sources)
        except (KeyError,TypeError,ValueError,AttributeError): return False
    for record,original in zip(records,rows):
        if record.get('original')!=original: raise ValueError('campaign_original_changed')
        if record.get('status') not in {'reviewed','excluded'} or not evidence(record):
            raise ValueError('campaign_list_research_incomplete')
    coverage=campaign.get('discovery',[])
    expected={a['no']:set(a['stations']) for a in load_master()['areas']}
    expected[15]=set()
    if len(coverage)!=15 or {a.get('area_no') for a in coverage}!=set(expected):
        raise ValueError('campaign_discovery_incomplete')
    for area in coverage:
        if area.get('status')!='reviewed' or set(area.get('stations',[]))!=expected[area['area_no']] or not evidence(area):
            raise ValueError('campaign_discovery_evidence_missing')
    if campaign.get('phase')!='complete' or campaign.get('publication_ready') is not True:
        raise ValueError('campaign_not_ready')


# Approved maintenance publication: preserve the already-published 2026-11-09
# snapshot byte-for-byte. This is never an exemption for new weekly PR intake.
RETAINED_SNAPSHOT = {'research.json': 'b5531394b14581e5d54c8faec94a0054a14b17da01951cd63f4d5f97f21255d6', 'search_failures.json': 'c6aab1ad0bb89907c17b4e16174c241bf4bc77c746a594315bf0c9260d353fc4'}

def retained_snapshot(research_bytes, failures_bytes):
    return all(hashlib.sha256(value).hexdigest() == RETAINED_SNAPSHOT[name]
               for name,value in [('research.json',research_bytes),('search_failures.json',failures_bytes)])
