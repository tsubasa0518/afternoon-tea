"""Categories by the lowest regular price of the plans in the research period.

- 5,000 yen or less: cafe
- 5,001 to 8,000 yen: hotel
- 8,001 yen or more: lux (ホテル（高級）)
- No regular price: unknown (未確認)
"""
import math
from afternoon_tea.processing.period_review import day

CAFE_MAX_YEN = 5000
HOTEL_MAX_YEN = 8000


def regular_price(plan):
    value = plan.get('price_yen')
    return value if type(value) in (int, float) and math.isfinite(value) and (value > 0) else None

def eligible_plans(plans, period):
    (start, end) = (day(period['start']), day(period['end']))
    for plan in plans:
        (first, last) = (day(plan.get('start')), day(plan.get('end')))
        if first and first > end or (last and last < start):
            continue
        yield plan

def classify(plans, shop=None):
    """`shop` is accepted for callers; the venue type does not affect the category."""
    prices = [price for plan in plans if (price := regular_price(plan)) is not None]
    if not prices:
        return ('unknown', None)
    minimum = min(prices)
    return ('cafe' if minimum <= CAFE_MAX_YEN else 'hotel' if minimum <= HOTEL_MAX_YEN else 'lux', minimum)
