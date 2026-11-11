"""Create plan display values without inferring prices or advancing check dates."""
import copy
import re
import unicodedata
from afternoon_tea.processing.sweets import extract as extract_sweets
from afternoon_tea.processing.classification import regular_price
from afternoon_tea.processing.themes import normalize_plan
SEASONS = {'xmas': 'クリスマス|Xmas|Christmas',
     'valentine': 'バレンタイン|Valentine',
     'whiteday': 'ホワイトデー|White Day',
     'halloween': 'ハロウィン|Halloween',
     'collab': 'コラボ|collaboration',
     'season': '季節限定|季節の味覚|秋の味覚|旬の味覚|秋・Automne|Autumn Harvest'}

def text_sources(plan):
    """Keep source fields separate; notes are not automatically source evidence."""
    return [(key, unicodedata.normalize('NFKC', plan[key])) for key in ('plan_name', 'evidence_quote', 'menu') if isinstance(plan.get(key), str)]

def enrich_plan(plan, shop):
    result = normalize_plan(plan)
    result['price_yen'] = regular_price(plan)
    if 'discount_price_yen' in plan:
        result['discount_price_yen'] = regular_price({'price_yen': plan['discount_price_yen']})
    result.setdefault('menu', None)
    result.pop('structured_evidence', None)

    sources = text_sources(plan)
    # Explicitly recorded inferred years are not evidence of service dates.
    if '年は調査年と推定' in str(plan.get('note', '')) and (not any((re.search('20[0-9]{2}', t) for (_, t) in sources))):
        result['start'] = result['end'] = None
        result['note'] = re.sub('提供期間:.*?（タイトル/期間表記より。年は調査年と推定）', '提供期間未確認（原文の年を確定できないため、推定年を取り消しました）', str(plan.get('note', '')))
    hits = extract_sweets(plan)
    result['sweets'] = sorted(hits)
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

def enrich(research, master=None, reference=None):
    """Category from the lowest regular price: <=5000 cafe / <=8000 hotel / >=8001 lux."""
    result = copy.deepcopy(research)
    from afternoon_tea.processing.classification import classify, eligible_plans
    for shop in result['shops']:
        shop['plans'] = [enrich_plan(p, shop) for p in shop.get('plans', [])]
        (category, minimum) = classify(eligible_plans(shop['plans'], result['period']), shop)
        shop.update(category=category, category_price_yen=minimum)
        shop.pop('category_source', None)
    return result
