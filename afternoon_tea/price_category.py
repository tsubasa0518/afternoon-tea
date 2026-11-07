"""Price bands shared by JSON enrichment and rendering; no venue-type inference."""
import math
from .weekly_review import day


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


def classify(plans):
    prices = [price for plan in plans if (price := regular_price(plan)) is not None]
    if not prices:
        return 'unknown', None
    minimum = min(prices)
    return ('cafe' if minimum <= 6000 else 'hotel' if minimum < 10000 else 'lux'), minimum
