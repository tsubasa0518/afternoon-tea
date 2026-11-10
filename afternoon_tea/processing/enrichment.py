(
    'Offline, evidence-preserving structured fields for the fixed weekly rendere'
    'r.\n\nNever fetch, confirm a shop, advance its check date, or invent unknown '
    'values.\n'
)
import copy
import json
import re
import unicodedata
from afternoon_tea.collection.catalog import ROOT
from afternoon_tea.collection.checkpoints import atomic_json
from afternoon_tea.processing.sweets import extract as extract_sweets
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
    result = copy.deepcopy(plan)
    result.setdefault('menu', None)
    evidence = result.get('structured_evidence')
    if not isinstance(evidence, dict):
        evidence = {}
    result['structured_evidence'] = evidence

    def save(key, value, quote, origin):
        result[key] = value
        # A new plan may come from a different source than the venue's
        # historical listing. Never attribute its menu to that older page.
        source = plan if plan.get('source_url') else shop
        evidence[key] = {'url': source.get('source_url'), 'checked_at': plan.get('checked_at', source.get('checked_at')), 'quote': quote, 'origin': origin}
    sources = text_sources(plan)
    # Explicitly recorded inferred years are not evidence of service dates.
    if '年は調査年と推定' in str(plan.get('note', '')) and (not any((re.search('20[0-9]{2}', t) for (_, t) in sources))):
        result['unverified_period_history'] = {'start': plan.get('start'), 'end': plan.get('end'), 'reason': 'year_inferred_without_saved_context'}
        result['start'] = result['end'] = None
        result['note'] = re.sub('提供期間:.*?（タイトル/期間表記より。年は調査年と推定）', '提供期間未確認（原文の年を確定できないため、推定年を取り消しました）', str(plan.get('note', '')))
    hits = extract_sweets(plan)
    result['sweets'] = sorted(hits)
    if hits:
        save('sweets', sorted(hits), '\n'.join(dict.fromkeys((v[1] for v in hits.values()))), ','.join(sorted({v[0] for v in hits.values()})))
    else:
        evidence.pop('sweets', None)
    # Only explicit plan/menu words, with the matched original line retained.
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
            save(key,
                 sorted(set(existing) | set(hits)),
                 '\n'.join(dict.fromkeys((v[1] for v in hits.values()))),
                 ','.join(sorted({v[0] for v in hits.values()})))
    joined = '\n'.join((line for (_, text) in sources for line in text.splitlines() if not re.search('未確認|未定|ではありません|提供しません|限定なし|適用外', line)))
    weekday_only = bool(re.search('平日限定|平日のみ|[（(]平日[）)]|weekdays? only', joined, re.I))
    weekend_only = bool(re.search('土日祝限定|土日祝のみ|[（(]土日祝[）)]|weekends? (?:and holidays )?only', joined, re.I))
    both = bool(re.search('平日[・、/と]+土日祝(?:とも|も|提供|利用)|全日提供|毎日提供', joined))
    if both or weekday_only != weekend_only:
        save('weekday_available', both or weekday_only, joined, 'plan_name/evidence_quote/menu')
        save('weekend_available', both or weekend_only, joined, 'plan_name/evidence_quote/menu')
    # Never treat a sale as the regular price. Ambiguous discounts become null.
    quote = unicodedata.normalize('NFKC', str(plan.get('evidence_quote') or ''))
    note = unicodedata.normalize('NFKC', str(plan.get('price_note') or ''))
    normal = re.search('通常(?:価格|料金)?\\s*[:：]?\\s*[¥￥]?\\s*([0-9][0-9,]*)\\s*円', quote)
    if normal is None:
        candidate = re.search('通常(?:価格|料金)?\\s*[:：]?\\s*([0-9][0-9,]*)\\s*円', note)
        if candidate and re.search('割引|OFF|セール|オフ', quote, re.I):
            amount = candidate.group(1)
            # A human-recorded regular-price note must be corroborated by the raw price block.
            if re.search('(?<![0-9,])' + re.escape(amount) + '\\s*円', quote):
                normal = candidate
    discounted = bool(re.search('割引|\\d+\\s*%\\s*OFF|タイムセール|discount', quote + ' ' + note, re.I))
    if normal:
        regular = int(normal.group(1).replace(',', ''))
        old = plan.get('price_yen')
        if isinstance(old, (int, float)) and (not isinstance(old, bool)) and (old != regular) and discounted:
            save('discount_price_yen', old, quote, 'evidence_quote')
        save('price_yen', regular, quote, 'evidence_quote')
        if discounted:
            prefix = f'通常価格 {regular:,}円。'
            result['price_note'] = note if note.startswith(prefix) else prefix + note
    elif discounted:
        save('price_yen', None, quote, 'evidence_quote:regular_price_unknown')
        result['price_note'] = note if note.startswith('通常価格 未確認。') else '通常価格 未確認。' + note
    if not evidence:
        result.pop('structured_evidence', None)
    return result

def enrich(research, master=None, reference=None):
    """Prices take precedence; master facility facts are only an unknown-price fallback."""
    result = copy.deepcopy(research)
    from afternoon_tea.processing.classification import classify, eligible_plans, facility_basis
    for shop in result['shops']:
        shop['plans'] = [enrich_plan(p, shop) for p in shop.get('plans', [])]
        (category, minimum) = classify(eligible_plans(shop['plans'], result['period']), shop, master)
        shop.update(category=category,
             category_price_yen=minimum,
             category_source='unknown regular price; facility fallback: ' + facility_basis(shop,
             master)[1] if minimum is None else 'saved regular price_yen; minimum of plans overlapping research period; <=6000 cafe / <10000 hotel / >=10000 lux; no fresh web verification')
    return result

def main(args):
    parser = args.parser
    allowed = ROOT.resolve() / 'site/research.json'
    path = args.data.resolve()
    if path != allowed and (not path.is_relative_to(ROOT.resolve() / '.staging')):
        parser.error('output must be site/research.json or a staging JSON')
    if args.data.is_symlink():
        parser.error('symlink data is forbidden')
    data = json.loads(path.read_text())
    atomic_json(path, enrich(data))
    print(json.dumps({'shops': len(data['shops']), 'confirmation_dates_changed': False}))
