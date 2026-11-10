"""Regular-price bands, with evidenced venue fallback only when price is unknown."""
import math
import json
from afternoon_tea.common import ROOT
from afternoon_tea.processing.period_review import day


def regular_price(plan):
    value = plan.get('price_yen')
    return value if type(value) in (int, float) and math.isfinite(value) and value > 0 else None


def eligible_plans(plans, period):
    start, end = day(period['start']), day(period['end'])
    for plan in plans:
        first, last = day(plan.get('start')), day(plan.get('end'))
        if (first and first > end) or (last and last < start):
            continue
        yield plan


def facility_basis(shop, master=None):
    """Use explicit facility facts, never the shop name or its old category."""
    shop = shop or {}
    source = shop.get('facility_source')
    if isinstance(source, str) and source.strip():
        kind = shop.get('facility_type')
        if kind in ('hotel', 'non_hotel'):
            return ('hotel' if kind == 'hotel' else 'cafe'), source
    hotel_name = shop.get('hotel_name')
    if isinstance(hotel_name, str) and hotel_name.strip() and hotel_name.strip() != '未確認':
        return 'hotel', 'hotel_name: ' + hotel_name
    if shop.get('id') and shop.get('name'):
        if master is None:
            master = json.loads((ROOT / 'data/store_master.json').read_text())
        matches = [(cat, venue) for area in master['areas'] for cat, group in area['cats'].items()
                   for venue in group['shops'] if venue['id'] == shop['id'] and venue['name'] == shop['name']]
        if len(matches) == 1 and matches[0][0] in ('cafe', 'hotel', 'lux'):
            return ('cafe' if matches[0][0] == 'cafe' else 'hotel'), 'data/store_master.json#' + shop['id']
    return 'unknown', 'facility information unconfirmed'


def classify(plans, shop=None, master=None):
    prices = [price for plan in plans if (price := regular_price(plan)) is not None]
    if not prices:
        return facility_basis(shop, master)[0], None
    minimum = min(prices)
    return ('cafe' if minimum <= 6000 else 'hotel' if minimum < 10000 else 'lux'), minimum
