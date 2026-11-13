"""Build saved display values and retain eligible plans without changing check dates."""
import datetime as dt
import math
import re
import unicodedata
import copy
import json
from afternoon_tea.fetch import JST
from afternoon_tea.config import ROOT
from afternoon_tea.fetch import load_json
from afternoon_tea.fetch import atomic_json
from functools import lru_cache

def period(start=None, now=None):
    if start is None:
        now = now or dt.datetime.now(JST)
        if now.tzinfo is None:
            raise ValueError('now にはタイムゾーンが必要です')
        start = now.astimezone(JST).date()
    elif isinstance(start, str):
        start = dt.date.fromisoformat(start)
    return {'start': start.isoformat(), 'end': (start + dt.timedelta(days=period_days())).isoformat()}


def period_days():
    from afternoon_tea.config import settings
    return int(settings()['period_days'])


def day(value):
    if value is None:
        return None
    parsed = dt.date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('use YYYY-MM-DD or null')
    return parsed

def review(data):
    (errors, outside) = ([], [])
    try:
        window = data['period']
        (start, end) = (day(window['start']), day(window['end']))
        if start is None or end is None or end != start + dt.timedelta(days=period_days()):
            raise ValueError('period.end must be period_days after period.start')
        generated = data.get('generated_at')
        if generated is not None:
            stamp = dt.datetime.fromisoformat(generated)
            if stamp.tzinfo is None or stamp.astimezone(JST).date() != start:
                raise ValueError('period.start must match generated_at in JST')
    except (KeyError, TypeError, ValueError) as exc:
        return {'errors': [{'reason': 'invalid_research_period', 'detail': str(exc)}], 'outside_plans': [], 'unknown_periods': 0}
    unknown = total = 0
    for (si, shop) in enumerate(data.get('shops', [])):
        for (pi, plan) in enumerate(shop.get('plans', [])):
            total += 1
            location = {'shop_index': si, 'plan_index': pi}
            try:
                (first, last) = (day(plan.get('start')), day(plan.get('end')))
                if first and last and (first > last):
                    raise ValueError('plan.start is after plan.end')
            except (TypeError, ValueError) as exc:
                errors.append({**location, 'reason': 'invalid_plan_period', 'detail': str(exc)})
                continue
            # Inclusive intersection; an unknown endpoint is never invented.
            if first and first > end or (last and last < start):
                item = {**location, 'reason': 'outside_research_period'}
                outside.append(item)
                errors.append(item)
            elif first is None or last is None:
                unknown += 1
    return {'period': window, 'shops': len(data.get('shops', [])), 'plans': total, 'errors': errors, 'outside_plans': outside, 'unknown_periods': unknown}


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

def classify(plans):
    """The venue name and type do not affect the category."""
    prices = [price for plan in plans if (price := regular_price(plan)) is not None]
    if not prices:
        return ('unknown', None)
    minimum = min(prices)
    return ('cafe' if minimum <= CAFE_MAX_YEN else 'hotel' if minimum <= HOTEL_MAX_YEN else 'lux', minimum)

@lru_cache(maxsize=1)
def registry():
    return json.loads((ROOT / 'data/country_registry.json').read_text())['countries']

def code(value):
    if isinstance(value, str) and value.isascii() and value.isalpha() and len(value) == 2 and value.lower() in registry():
        return value.lower()
    return None

def normalize_plan(plan):
    result = {key: copy.deepcopy(value) for key, value in plan.items() if key in PLAN_FIELDS}
    result['cc'] = code(plan.get('cc'))
    return result

def validate_country(plan):
    if plan.get('cc') is not None and code(plan['cc']) is None:
        raise ValueError('invalid_ISO_country_code')

def flag(value):
    cc = code(value)
    if cc is None:
        raise ValueError('invalid_ISO_country_code')
    return ''.join(chr(127462 + ord(letter) - ord('A')) for letter in cc.upper())

def display(plan):
    cc = code(plan.get('cc'))
    if cc is None:
        return None
    entry = registry()[cc]
    return flag(cc) + ' ' + entry.get('short_name', entry['name'])


# Only the documented record shape and generated display values are retained.
SHOP_FIELDS = {'id', 'candidate_no', 'origin', 'name', 'hotel_name', 'area_no', 'genre', 'address', 'station',
               'source_site', 'info_url', 'reference_urls', 'plans', 'category', 'category_price_yen'}
PLAN_FIELDS = {'plan_name', 'price_yen', 'discount_price_yen', 'price_note', 'start', 'end',
               'weekday_available', 'weekend_available', 'time_note', 'menu', 'source_url',
               'checked_at', 'cc', 'season'}
FUTURE_SKEW = dt.timedelta(minutes=10)

def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('plan_checked_at_required')
    stamp = dt.datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError('plan_checked_at_timezone_required')
    return stamp

def valid_plan(plan):
    """A real plan: a name, the page it was read from and when it was read. No placeholders."""
    try:
        timestamp(plan.get('checked_at'))
    except (TypeError, ValueError):
        return False
    name, url = plan.get('plan_name'), plan.get('source_url')
    return (isinstance(name, str) and bool(name.strip()) and isinstance(url, str)
            and url.startswith(('https://', 'http://')) and not re.search(r'(?i)dummy|placeholder|ダミー|サンプル', name))

def ended(plan, window):
    last = day(plan.get('end'))
    return bool(last and last < day(window['start']))

def displayable(data):
    """Shops and plans shown on the site; also the count the publication guard requires to be > 0."""
    from afternoon_tea.config import excluded_genre
    window = data['period']
    end = day(window['end'])
    for shop in data.get('shops', []):
        if not isinstance(shop, dict) or type(shop.get('area_no')) is not int or not 1 <= shop['area_no'] <= 14:
            continue
        if not isinstance(shop.get('name'), str) or not shop['name'].strip() or excluded_genre(shop.get('genre')):
            continue
        plans = []
        for plan in shop.get('plans', []):
            if not isinstance(plan, dict) or not valid_plan(plan) or ended(plan, window):
                continue
            first = day(plan.get('start'))
            if first and first > end:
                continue
            plans.append(plan)
        if plans:
            yield shop, plans

def normalize(data, now=None):
    """Keep confirmed plans with their own checked_at; drop only what is broken, ended or excluded."""
    from afternoon_tea.config import excluded_genre
    from afternoon_tea.check import scan, json_bytes, SensitiveDataError
    from afternoon_tea.research import migrate
    now = now or dt.datetime.now(JST)
    data = migrate(copy.deepcopy(data))
    result = {key: data[key] for key in ('schema_version', 'generated_at', 'period') if key in data}
    progress = copy.deepcopy(data.get('progress') or {'updated_at': None, 'entries': {}})
    excluded = copy.deepcopy(data.get('excluded_sensitive_plans', {'current': 0, 'previous': 0}))
    if (not isinstance(excluded, dict) or set(excluded) != {'current', 'previous'}
            or any(type(n) is not int or n < 0 for n in excluded.values())):
        raise ValueError('invalid_excluded_sensitive_plan_count')
    # Excluded plans are removed here, so a rebuild cannot count them twice. begin resets the counts.
    shops, seen = [], set()
    for original in data.get('shops', []):
        shop = {k: copy.deepcopy(v) for k, v in original.items() if k in SHOP_FIELDS}
        key = shop.get('id')
        if not isinstance(key, str) or key in seen:
            raise ValueError('shop_id_missing_or_duplicated')
        seen.add(key)
        entry = progress['entries'].get(key)
        if type(shop.get('area_no')) is not int or not 1 <= shop['area_no'] <= 14:
            continue
        if excluded_genre(shop.get('genre')):
            if entry:
                entry['status'] = 'excluded_genre'
            continue
        kept, had = [], bool(shop.get('plans'))
        for original_plan in shop.get('plans', []):
            plan = normalize_plan(original_plan)
            try:
                scan(json_bytes(plan))
            except SensitiveDataError:
                excluded['current'] += 1
                continue
            stamp = timestamp(plan.get('checked_at'))
            if stamp > now + FUTURE_SKEW:
                raise ValueError('plan_checked_at_in_the_future')
            if ended(plan, result['period']):
                continue
            kept.append(plan)
        if not kept:
            if had and entry and entry.get('status') == 'plan_confirmed':
                entry['status'] = 'plans_ended'
            continue
        shop['plans'] = kept
        shops.append(shop)
    result['shops'] = shops
    result['progress'] = progress
    result['excluded_sensitive_plans'] = excluded
    return result

SEASONS = {'xmas': 'クリスマス|Xmas|Christmas',
     'valentine': 'バレンタイン|Valentine',
     'whiteday': 'ホワイトデー|White Day',
     'halloween': 'ハロウィン|Halloween',
     'collab': 'コラボ|collaboration',
     'season': '季節限定|季節の味覚|秋の味覚|旬の味覚|秋・Automne|Autumn Harvest'}

def text_sources(plan):
    """Keep source fields separate; notes are not automatically source evidence."""
    return [(key, unicodedata.normalize('NFKC', plan[key])) for key in ('plan_name', 'menu') if isinstance(plan.get(key), str)]

def enrich_plan(plan):
    result = normalize_plan(plan)
    result['price_yen'] = regular_price(plan)
    if 'discount_price_yen' in plan:
        result['discount_price_yen'] = regular_price({'price_yen': plan['discount_price_yen']})
    result.setdefault('menu', None)

    sources = text_sources(plan)
    # Only explicit plan/menu words, without saving acquisition metadata.
    for (key, patterns) in (('season', SEASONS),):
        hits = {}
        for (origin, text) in sources:
            for line in text.splitlines():
                if re.search('未確認|未定|不使用|含まれません|提供しません|ではありません|なし|追加料金|別料金|オプション|除く', line):
                    continue
                for (tag, pattern) in patterns.items():
                    if re.search(pattern, line, re.I):
                        hits.setdefault(tag, (origin, line))
        if hits:
            existing = plan.get(key, [])
            existing = [existing] if isinstance(existing, str) else existing if isinstance(existing, list) else []
            existing = [value for value in existing if isinstance(value, str)]
            result[key] = sorted(set(existing) | set(hits))
    joined = '\n'.join((line for (_, text) in sources for line in text.splitlines() if not re.search('未確認|未定|ではありません|提供しません|限定なし|適用外', line)))
    weekday_only = bool(re.search('平日限定|平日のみ|[（(]平日[）)]|weekdays? only', joined, re.I))
    weekend_only = bool(re.search('土日祝限定|土日祝のみ|[（(]土日祝[）)]|weekends? (?:and holidays )?only', joined, re.I))
    both = bool(re.search('平日[・、/と]+土日祝(?:とも|も|提供|利用)|全日提供|毎日提供', joined))
    if both or weekday_only != weekend_only:
        if result.get('weekday_available') is None:
            result['weekday_available'] = both or weekday_only
        if result.get('weekend_available') is None:
            result['weekend_available'] = both or weekend_only
    return result

def enrich(research):
    """Category from the lowest regular price: <=5000 cafe / <=8000 hotel / >=8001 lux."""
    result = copy.deepcopy(research)
    for shop in result['shops']:
        shop['plans'] = [enrich_plan(p) for p in shop.get('plans', [])]
        (category, minimum) = classify(eligible_plans(shop['plans'], result['period']))
        shop.update(category=category, category_price_yen=minimum)
    return result


def build(current, previous=None, now=None, rows=None):
    data = normalize(current, now=now)
    periods = review(data)
    errors = [e for e in periods['errors'] if e['reason'] != 'outside_research_period']
    if errors:
        raise ValueError('invalid_plan_period')
    data = enrich(data)
    from afternoon_tea.check import validate_json, json_bytes
    validate_json(json_bytes(data))
    return data


def main():
    from afternoon_tea.check import validate_site, json_bytes, publishable
    from afternoon_tea.render import render
    from afternoon_tea.render import write_html
    target = ROOT / 'site/research.json'
    if target.is_symlink() or target.parent.is_symlink():
        raise ValueError('symlink data forbidden')
    data = build(load_json(target))
    html = render(data)
    report = validate_site({'site/research.json': json_bytes(data), 'site/index.html': html.encode()})
    # Prepare and validate both values before either tracked file is replaced.
    write_html(html)
    atomic_json(target, data)
    counts = publishable(data, require_nonzero=False)
    print(json.dumps({'shops': counts['shops'], 'plans': counts['plans'],
                      'excluded_sensitive_plans': sum(data['excluded_sensitive_plans'].values()),
                      'confirmation_dates_changed': False,
                      'publication': 'allowed' if counts['plans'] else 'refused_zero_listing'}, ensure_ascii=False))
    return 0
