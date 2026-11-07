"""Offline, evidence-preserving structured fields for the fixed weekly renderer.

Never fetch, confirm a shop, advance its check date, or invent unknown values.
"""
import argparse
import copy
import json
import re
import unicodedata
from pathlib import Path
from .master import ROOT
from .research_store import atomic_json

SWEETS = {
    'ichigo': r'いちご|イチゴ|苺|strawberr', 'melon': r'メロン|melon',
    'peach': r'桃|ピーチ|peach', 'mango': r'マンゴー|mango',
    'grape': r'ぶどう|ブドウ|葡萄|マスカット|grape|muscat',
    'kuri': r'栗|マロン|モンブラン|chestnut', 'imo': r'さつまいも|紫芋|かぼちゃ|南瓜|sweet potato|pumpkin',
    'kaki': r'柿|洋梨|いちじく|無花果|persimmon|fig\b|pear\b',
    'citrus': r'柑橘|レモン|オレンジ|ゆず|柚子|citrus|lemon|orange',
    'choco': r'チョコ|ショコラ|chocolat', 'wa': r'抹茶|ほうじ茶|和菓子|matcha',
    'macaron': r'マカロン|macaron', 'parfait': r'パフェ|parfait', 'scone': r'スコーン|scone',
}
SEASONS = {'xmas': r'クリスマス|Xmas|Christmas', 'valentine': r'バレンタイン|Valentine',
           'whiteday': r'ホワイトデー|White Day', 'halloween': r'ハロウィン|Halloween',
           'collab': r'コラボ|collaboration', 'season': r'季節限定|季節の味覚|秋の味覚|旬の味覚|秋・Automne|Autumn Harvest'}


def text_sources(plan):
    """Keep source fields separate; notes are not automatically source evidence."""
    return [(key, unicodedata.normalize('NFKC', plan[key]))
            for key in ('plan_name', 'evidence_quote', 'menu') if isinstance(plan.get(key), str)]


def enrich_plan(plan, shop):
    result = copy.deepcopy(plan)
    evidence = result.get('structured_evidence')
    if not isinstance(evidence, dict):
        evidence = {}
    result['structured_evidence'] = evidence
    def save(key, value, quote, origin):
        result[key] = value
        evidence[key] = {'url': shop.get('source_url'), 'checked_at': shop.get('checked_at'),
                         'quote': quote, 'origin': origin}
    sources = text_sources(plan)
    # Explicitly recorded inferred years are not evidence of service dates.
    if '年は調査年と推定' in str(plan.get('note','')) and not any(re.search(r'20[0-9]{2}',t) for _,t in sources):
        result['unverified_period_history']={'start':plan.get('start'),'end':plan.get('end'),'reason':'year_inferred_without_saved_context'}
        result['start']=result['end']=None
        result['note']=re.sub(r'提供期間:.*?（タイトル/期間表記より。年は調査年と推定）','提供期間未確認（原文の年を確定できないため、推定年を取り消しました）',str(plan.get('note','')))

    # Only explicit plan/menu words, with the matched original line retained.
    for key, patterns in (('sweets', SWEETS), ('season', SEASONS)):
        hits = {}
        for origin, text in sources:
            for line in text.splitlines():
                if re.search(r'未確認|未定|不使用|含まれません|提供しません|ではありません|なし|追加料金|別料金|オプション|除く', line):
                    continue
                for tag, pattern in patterns.items():
                    if re.search(pattern, line, re.I):
                        hits.setdefault(tag, (origin, line))
        if hits:
            existing = plan.get(key, [])
            existing = [existing] if isinstance(existing, str) else existing if isinstance(existing, list) else []
            existing = [value for value in existing if isinstance(value, str)]
            save(key, sorted(set(existing) | set(hits)),
                 '\n'.join(dict.fromkeys(v[1] for v in hits.values())), ','.join(sorted({v[0] for v in hits.values()})))
    joined = '\n'.join(line for _, text in sources for line in text.splitlines()
                       if not re.search(r'未確認|未定|ではありません|提供しません|限定なし|適用外', line))
    weekday_only = bool(re.search(r'平日限定|平日のみ|[（(]平日[）)]|weekdays? only', joined, re.I))
    weekend_only = bool(re.search(r'土日祝限定|土日祝のみ|[（(]土日祝[）)]|weekends? (?:and holidays )?only', joined, re.I))
    both = bool(re.search(r'平日[・、/と]+土日祝(?:とも|も|提供|利用)|全日提供|毎日提供', joined))
    if both or weekday_only != weekend_only:
        save('weekday_available', both or weekday_only, joined, 'plan_name/evidence_quote/menu')
        save('weekend_available', both or weekend_only, joined, 'plan_name/evidence_quote/menu')
    # Never treat a sale as the regular price. Ambiguous discounts become null.
    quote = unicodedata.normalize('NFKC', str(plan.get('evidence_quote') or ''))
    note = unicodedata.normalize('NFKC', str(plan.get('price_note') or ''))
    normal = re.search(r'通常(?:価格|料金)?\s*[:：]?\s*[¥￥]?\s*([0-9][0-9,]*)\s*円', quote)
    if normal is None:
        candidate = re.search(r'通常(?:価格|料金)?\s*[:：]?\s*([0-9][0-9,]*)\s*円', note)
        if candidate and re.search(r'割引|OFF|セール|オフ', quote, re.I):
            amount = candidate.group(1)
            # A human-recorded regular-price note must be corroborated by the raw price block.
            if re.search(r'(?<![0-9,])' + re.escape(amount) + r'\s*円', quote):
                normal = candidate
    discounted = bool(re.search(r'割引|\d+\s*%\s*OFF|タイムセール|discount', quote + ' ' + note, re.I))
    if normal:
        regular = int(normal.group(1).replace(',', ''))
        old = plan.get('price_yen')
        if isinstance(old, (int, float)) and not isinstance(old, bool) and old != regular and discounted:
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


def enrich(research, master, reference=None):
    result = copy.deepcopy(research)
    known = {s['id']: (cat, s) for a in master['areas'] for cat, g in a['cats'].items() for s in g['shops']}
    historical = {}
    if reference:
        from .extraction import Document
        for card in Document(reference).root.find('article'):
            names=card.find('h4')
            if len(names)==1:
                historical.setdefault(names[0].text,[]).append(card)
    for shop in result['shops']:
        shop['plans'] = [enrich_plan(p, shop) for p in shop.get('plans', [])]
        match = known.get(shop.get('id'))
        # Exact known identity only; do not infer hotel/cafe from a suggestive name.
        if not shop.get('category_source') and match and shop['name'] == match[1]['name']:
            if match[0] == 'cafe':
                category = 'cafe'
            else:
                prices = [p['price_yen'] for p in shop['plans'] if type(p.get('price_yen')) in (int, float)]
                category = 'lux' if prices and min(prices) >= 9000 else 'hotel'
            shop.update(category=category, category_source=f'data/store_master.json#{shop["id"]} (as_of {master["as_of"]}; hotel tier uses current regular price, unknown => hotel)')
        if not shop.get('category_source'):
            # Exact name AND same public venue URL: no fuzzy hotel/lobby merging.
            cards=historical.get(shop.get('name'),[])
            from urllib.parse import urlsplit
            def venue(url):
                u=urlsplit(url or '')
                parts=u.path.strip('/').split('/')
                return (u.hostname,parts[0]) if u.hostname=='restaurant.ikyu.com' else (u.hostname,u.path.rstrip('/'))
            cards=[c for c in cards if any(venue(a.attrs.get('href'))==venue(shop.get('source_url')) for a in c.find('a'))]
            if len(cards)==1 and cards[0].attrs.get('data-cat') in ('cafe','hotel','lux'):
                base=cards[0].attrs['data-cat']
                prices=[p['price_yen'] for p in shop['plans'] if type(p.get('price_yen')) in (int,float)]
                shop['category']='cafe' if base=='cafe' else 'lux' if prices and min(prices)>=9000 else 'hotel'
                shop['category_source']='afternoon_tea_tokyo_2026-11-06.html: exact name + venue URL; historical venue type only, not a fresh AT check; tier uses saved current regular price'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT/'site/research.json')
    args = parser.parse_args()
    allowed = ROOT.resolve()/'site/research.json'
    path = args.data.resolve()
    if path != allowed and not path.is_relative_to(ROOT.resolve()/'.staging'):
        parser.error('output must be site/research.json or a staging JSON')
    if args.data.is_symlink():
        parser.error('symlink data is forbidden')
    data = json.loads(path.read_text())
    atomic_json(path, enrich(data, json.loads((ROOT/'data/store_master.json').read_text()), (ROOT/'afternoon_tea_tokyo_2026-11-06.html').read_text()))
    print(json.dumps({'shops': len(data['shops']), 'confirmation_dates_changed': False}))


if __name__ == '__main__':
    main()
