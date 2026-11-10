"""Venue categories: hotel or not by explicit text, then the regular price for hotels.

- Not stated as a hotel: cafe (whatever the price).
- Stated as a hotel: hotel at 6,000 yen or less, lux at 6,001 yen or more.
- A hotel whose regular price is unknown stays unknown.
"""
import math
import re
from afternoon_tea.processing.period_review import day

HOTEL_TEXT = re.compile(r'ホテル|hotel', re.I)
HOTEL_MAX_YEN = 6000
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

def hotel_basis(shop):
    """Return the field that states the venue is a hotel, or None.

    `hotel_name` is recorded during research only when the page says the venue
    is a hotel; the shop name and address count when they contain the word.
    """
    shop = shop or {}
    hotel_name = shop.get('hotel_name')
    if isinstance(hotel_name, str) and hotel_name.strip() and hotel_name.strip() != '未確認':
        return 'hotel_name'
    for key in ('name', 'address'):
        if isinstance(shop.get(key), str) and HOTEL_TEXT.search(shop[key]):
            return key
    return None


def classify(plans, shop=None):
    prices = [price for plan in plans if (price := regular_price(plan)) is not None]
    minimum = min(prices) if prices else None
    if hotel_basis(shop) is None:
        return ('cafe', minimum)
    if minimum is None:
        return ('unknown', None)
    return ('hotel' if minimum <= HOTEL_MAX_YEN else 'lux', minimum)
