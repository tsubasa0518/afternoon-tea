"""Stateless weekly retention and publication freshness; no evidence ledger."""
import copy
import datetime as dt
from afternoon_tea.processing.dates import JST

# Display facts survive; the retired acquisition/evidence machinery does not.
REMOVED = {'research_campaign', 'research_entity_id', 'research_evidence', 'structured_evidence',
           'identity_links', 'station_evidence', 'documents', 'audit_segments', 'access_evidence',
           'evidence_quote',
           'unverified_period_history', 'menu_evidence', 'price_evidence', 'period_evidence',
           'exit', 'collection_summary', 'out_of_period_removed', 'audit', 'document_ids', 'document_refs', 'campaign_id', 'entity_id',
           'facility_type', 'facility_source'}

def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('plan_checked_at_required')
    stamp = dt.datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError('plan_checked_at_timezone_required')
    return stamp

def fresh(value, now):
    try:
        return now - dt.timedelta(days=14) <= timestamp(value) <= now
    except (ValueError, TypeError):
        return False

def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if k not in REMOVED}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value

def retain(current, previous=None, now=None):
    """Only completed reviewed plans enter current; previous dates never advance."""
    now = now or dt.datetime.now(JST)
    result = copy.deepcopy(current)
    shops = {}
    for source in (previous or {'shops': []}, current):
        for original in source.get('shops', []):
            if type(original.get('area_no')) is not int or not 1 <= original['area_no'] <= 14:
                continue
            shop = clean(copy.deepcopy(original))
            accepted = []
            for original_plan in original.get('plans', []):
                plan = clean(copy.deepcopy(original_plan))
                # Legacy plans already used the saved shop's actual check date.
                stamp = plan.get('checked_at', original.get('checked_at'))
                if fresh(stamp, now):
                    plan['checked_at'] = stamp
                    accepted.append(plan)
            if not accepted:
                continue
            key = shop.get('id') or (shop.get('name'), shop['area_no'])
            old = shops.get(key, {'plans': []})
            plans = {p.get('plan_name'): p for p in old['plans']}
            plans.update({p.get('plan_name'): p for p in accepted})
            shops[key] = {**shop, 'plans': list(plans.values())}
    result['shops'] = list(shops.values())
    return clean(result)

def validate_freshness(data, now=None):
    now = now or dt.datetime.now(JST)
    for shop in data.get('shops', []):
        if type(shop.get('area_no')) is not int or not 1 <= shop['area_no'] <= 14:
            raise ValueError('shop_area_outside_fourteen')
        for plan in shop.get('plans', []):
            if not fresh(plan.get('checked_at'), now):
                raise ValueError('plan_stale_future_or_missing_checked_at')
