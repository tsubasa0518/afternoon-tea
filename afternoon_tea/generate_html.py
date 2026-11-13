"""Offline fixed-design HTML from saved display values."""
from collections import Counter
import datetime as dt
import html
import json
import os
import re
import tempfile
from pathlib import Path
from string import Template
from urllib.parse import urlsplit
from afternoon_tea.prepare_listings import JST
from afternoon_tea.prepare_listings import review
from afternoon_tea.prepare_listings import day
from afternoon_tea.prepare_listings import regular_price
from afternoon_tea.prepare_listings import display as country_display
from afternoon_tea.prepare_listings import displayable
from afternoon_tea.prepare_listings import timestamp
from afternoon_tea.research_settings import settings
from afternoon_tea.publication_checks import ROOT
from afternoon_tea.publication_checks import json_bytes
from afternoon_tea.publication_checks import validate_json
from afternoon_tea.publication_checks import validate_html_bytes
from afternoon_tea.publication_checks import resource

TEMPLATES = Path(__file__).resolve().parent / 'page_templates'
SITES = [('ik', '一休.com'), ('tb', '食べログ'), ('tc', 'TableCheck')]
SEASON_LABELS = {'halloween': 'ハロウィン', 'xmas': 'クリスマス', 'valentine': 'バレンタイン',
                 'whiteday': 'ホワイトデー', 'collab': 'コラボ企画', 'season': '季節の味覚'}
CATS = [('cafe', 'カフェ', 'c-cafe'), ('hotel', 'ホテル', 'c-hotel'), ('lux', 'ホテル（高級）', 'c-lux')]
SVG_TEA = (
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9h13v4a6 6 0 0 1-6 '
    '6H10a6 6 0 0 1-6-6V9zm13 1h1.5a2.5 2.5 0 0 1 0 5H17" fill="none" stroke="cu'
    'rrentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M8 3.5c0 1'
    '.5 1.2 1.5 1.2 3M11.5 3.5c0 1.5 1.2 1.5 1.2 3" fill="none" stroke="currentC'
    'olor" stroke-width="1.4" stroke-linecap="round"/></svg>'
)
SVG_EXT = (
    '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3h7v7M13 3 6.5 9.5M'
    '11 9.5V13H3V5h3.5" fill="none" stroke="currentColor" stroke-width="1.5" str'
    'oke-linecap="round" stroke-linejoin="round"/></svg>'
)
SVG_CLK = (
    '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.2" f'
    'ill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 4.6V8l2.4 '
    '1.6" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="r'
    'ound"/></svg>'
)
CLASSES = {k: (label, cls) for (k, label, cls) in CATS}
CLASSES['unknown'] = ('分類未確認', 'c-unknown')
HOSTS = {'restaurant.ikyu.com': 'ik', 'tabelog.com': 'tb', 'www.tabelog.com': 'tb', 'tablecheck.com': 'tc', 'www.tablecheck.com': 'tc'}

def esc(value):
    return html.escape(str(value), quote=True) if value is not None else '未確認'

def season_tags(value):
    values = value if isinstance(value, list) else [value] if isinstance(value, str) else []
    reverse = {v: k for k, v in SEASON_LABELS.items()}
    return sorted({v if v in SEASON_LABELS else reverse[v] for v in values if isinstance(v, str) and (v in SEASON_LABELS or v in reverse)})

def category(shop):
    value = shop.get('category')
    return value if value in CLASSES else 'unknown'

def condition(plan, key):
    value = plan.get(key)
    return 'on' if value is True else 'no' if value is False else 'off'

def info_link(url, label=None):
    resource(url)
    site = HOSTS.get(urlsplit(url).hostname)
    label = label or dict(SITES).get(site, '公式・情報ページ')
    return f'''<a class="lk lk-{site or 'official'}" href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(label)}{SVG_EXT}</a>'''

def plan_html(plan, index, total, generated):
    (first, last) = (day(plan.get('start')), day(plan.get('end')))
    date = lambda x: f'{x.year}/{x.month}/{x.day}' if x else '未確認'
    dates = date(first) + '〜' + date(last) if first and last else '提供期間 未確認' + ('（' + date(first) + '〜' + date(last) + '）' if first or last else '')
    badge = ''
    checked = timestamp(plan['checked_at']).astimezone(JST).date()
    past = generated is not None and (generated - checked).days >= settings()['stale_after_days']
    if past:
        badge = '<span class="pst past">過去の確認情報</span>'
    elif generated and first and (first > generated):
        badge = '<span class="pst soon">これから</span>'
    elif generated and first and last and (first <= generated <= last):
        badge = '<span class="pst now">提供期間内</span>'
    price = regular_price(plan)
    wd = condition(plan, 'weekday_available')
    we = condition(plan, 'weekend_available')
    seasons = season_tags(plan.get('season'))
    attrs = (
        f'data-wd="'
        f"{int(wd == 'on')}"
        f'" data-we="'
        f"{int(we == 'on')}"
        f'" data-price="'
        f"{(price if price is not None else '')}"
        f'"'
    )
    out = [(
        f'<div class="plan" '
        f'{attrs}'
        f'><div class="plan-hd"><span class="pno">プラン'
        f'{index + 1}'
        f'／'
        f'{total}'
        f'</span><p class="pper'
        f"{(' na' if not first and (not last) else '')}"
        f'">'
        f'{esc(dates)}'
        f'</p>'
        f'{badge}'
        f'</div>'
    ), f"""<p class="theme">{SVG_TEA}<span>{esc(plan.get('plan_name'))}</span></p>"""]
    country = country_display(plan)
    if country:
        out.append('<p class="country-theme" aria-label="テーマの国・地域">' + esc(country) + '</p>')
    if seasons:
        out.append('<p class="season-tags" aria-label="季節・イベント">' + ''.join(('<span>' + esc(SEASON_LABELS[k]) + '</span>' for k in seasons)) + '</p>')
    if price is None:
        out.append('<div class="price"><span class="pdet">料金 未確認</span></div>')
    else:
        note = plan.get('price_note') or '税・サービス料条件 未確認'
        out.append(f'<div class="price"><span class="pbig">{price:,}<small>円</small></span><span class="pdet">{esc(note)}</span></div>')
    chips = []
    for (state, label) in ((wd, '平日'), (we, '土日祝')):
        text = label if state == 'on' else label + ' ✕' if state == 'no' else label + ' 未確認'
        chips.append(f'<span class="chip {state}">{text}</span>')
    time = plan.get('time_note') or '提供時間・利用時間 未確認'
    out.append('<div class="when"><div class="chips" aria-label="提供日">' + ''.join(chips) + '</div>' + f'<p class="time">{SVG_CLK}<span>{esc(time)}</span></p></div>')
    if plan.get('menu'):
        out.append('<p class="dtxt">メニュー：' + esc(plan['menu']) + '</p>')
    note = f'{date(checked)}に確認' + ('した過去の情報です。現在の提供状況は未確認です。' if past else '')
    out.append(f'<p class="checked{" past" if past else ""}">{esc(note)}</p>')
    url = plan.get('source_url')
    if url:
        out.append('<div class="links">' + info_link(url, 'プランの情報ページ') + '</div>')
    out.append('</div>')
    return ''.join(out)

def nearest_stations(shop):
    """Extract explicit station names from saved shop-specific access text."""
    names = []
    for value in (shop.get('station'),):
        if not isinstance(value, str):
            continue
        for match in re.finditer('[一-龥々ぁ-んァ-ヶーA-Za-z0-9]+駅', value):
            name = match.group()
            if name not in names:
                names.append(name)
    return '／'.join(names) if names else None

def card(shop, plans, generated):
    cat = category(shop)
    (label, cls) = CLASSES[cat]
    seasons = sorted({t for p in plans for t in season_tags(p.get('season'))})
    wd = any((condition(p, 'weekday_available') == 'on' for p in plans))
    we = any((condition(p, 'weekend_available') == 'on' for p in plans))
    out = [(
        f'<article class="card '
        f'{cls}'
        f'" data-cat="'
        f'{cat}'
        f'" data-wd="'
        f'{int(wd)}'
        f'" data-we="'
        f'{int(we)}'
        f'">'
    ), f"""<div class="top"><header><h4>{esc(shop.get('name'))}</h4>"""]
    if shop.get('hotel_name'):
        out.append('<p class="shop">' + esc(shop['hotel_name']) + '</p>')
    out.append('</header></div>')
    out.append(f'<p class="rnote">{esc(label)}</p>')
    if shop.get('address'):
        out.append('<p class="rnote">' + esc(shop['address']) + '</p>')
    out.append('<div class="meet"><p><span class="mk">最寄駅</span>' + esc(nearest_stations(shop)) + '</p></div>')
    url = shop.get('info_url')
    if url:
        out.append('<div class="links" aria-label="店舗の情報ページ">' + info_link(url) + '</div>')
    if seasons:
        out.append('<p class="season-tags" aria-label="店舗の季節・イベント">' + ''.join(('<span>' + esc(SEASON_LABELS[k]) + '</span>' for k in seasons)) + '</p>')
    out.append('<div class="plans">' + ''.join((plan_html(p, i, len(plans), generated) for (i, p) in enumerate(plans))) + '</div></article>')
    return ''.join(out)

def render(research):
    research = {**research, 'shops': [s for s in research.get('shops', [])
                if not isinstance(s, dict) or (type(s.get('area_no')) is int and 1 <= s['area_no'] <= 14)]}
    validate_json(json_bytes(research))
    check = review(research)
    invalid = [e for e in check['errors'] if e['reason'] != 'outside_research_period']
    if invalid:
        raise ValueError('invalid date input: ' + json.dumps(invalid))
    stamp = research.get('generated_at')
    generated = dt.datetime.fromisoformat(stamp).astimezone(JST).date() if stamp else None
    master = json.loads((ROOT / 'research_inputs/tokyo_areas.json').read_text())
    groups = {a['no']: [] for a in master['areas']}
    tot = Counter()
    for (shop, plans) in displayable(research):
        shop = {**shop, 'plans': plans}
        markup = card(shop, plans, generated)
        target = groups[shop['area_no']]
        target.append((category(shop), markup))
        tot[category(shop)] += 1
    per = research['period']
    (start, end) = (day(per['start']), day(per['end']))
    stats = ''.join((f'<div class="stat s-{cat}"><b>{tot[cat]}</b><span>{label}</span></div>' for (cat, label, cls) in CATS))
    hero = (
        f'<div class="hero"><div class="hero-in"><div><h1>東京 アフタヌーンティー</h1><p class="'
        f'period">'
        f'{start.year}'
        f'年'
        f'{start.month}'
        f'月'
        f'{start.day}'
        f'日〜'
        f'{end.year}'
        f'年'
        f'{end.month}'
        f'月'
        f'{end.day}'
        f'日<small>（'
        f'{(end - start).days}'
        f'日間）</small></p><p class="lead legendline"><span class="lg"><span'
        f' class="chip on">平日</span> 提供あり</span><span class="lg"><span class="chip no'
        f'">土日祝 ✕</span> そのプランでは提供なし</span></p></div><div class="stats">'
        f'{stats}'
        f'</div></div></div>'
    )

    cats = ''.join((f'<button class="fb f-{cat}" data-cat="{cat}" aria-pressed="true">{label}</button>' for (cat, label, cls) in CATS))
    if tot['unknown']:
        cats += '<button class="fb f-x" data-cat="unknown" aria-pressed="true">分類未確認</button>'
    nav = ''.join((f"""<a class="area-btn" href="#a{a['no']}">{esc(a['name']).replace('・', '・<wbr>')}</a>""" for a in master['areas']))
    row = lambda label, body, aria: f'<div class="frow" role="group" aria-label="{aria}"><span class="lb">{label}</span><div class="btns">{body}</div></div>'
    filters = '<div class="fpanel" id="top"><div class="fpanel-in">' + row('分類',
         cats,
         '分類で絞り込み') + row('日程条件',
         '<button class="fb f-x" data-x="wd" aria-pressed="false">平日</button><button class="fb f-x" data-x="we" aria-pressed="false">土日祝</button>',
         '日程条件で絞り込み')
    filters += (
        f'<nav class="frow area-nav" aria-label="エリア"><span class="lb">場所</span><div '
        f'class="area-disclosure"><button class="lk area-toggle" id="area-toggle" typ'
        f'e="button" aria-expanded="false" aria-controls="area-links">詳細</button><div'
        f' class="btns" id="area-links" hidden>'
        f'{nav}'
        f'</div></div></nav>'
    )
    filters += (
        '<div class="price-filter-field"><label class="lb" for="price-filter">料金帯</l'
        'abel><select id="price-filter"><option value="all">すべて</option><option valu'
        'e="low">5,000円以下</option><option value="mid">5,001〜8,000円</option><option v'
        'alue="high">8,001円以上</option><option value="unknown">料金未確認</option></selec'
        't></div><div class="filter-status"><span id="filter-status" role="status" a'
        'ria-live="polite"></span><button class="lk" id="reset-filters" type="button'
        '">絞り込みを解除</button></div></div></div>'
    )
    count = sum(tot.values())
    empty = '<p class="none" id="no-results" hidden>条件に合う掲載情報はありません。絞り込みを変更してください。</p>'
    if not count:
        empty += '<p class="none">確認できた情報はありません</p>'
    areas = []

    def area_html(no, name, entries, stations=None):
        parts = [f'<section class="area" id="a{no}"><h2><span class="no">{no:02d}</span>{esc(name)}<span class="acnt">{len(entries)}件</span></h2>']
        if stations:
            parts.append('<p class="rnote">対象駅：' + esc('、'.join(stations)) + '</p>')
        for (key, (label, cls)) in sorted(CLASSES.items(), key=lambda item: not any((cat == item[0] for (cat, markup) in entries))):
            cards = [markup for (cat, markup) in entries if cat == key]
            if key == 'unknown' and (not cards):
                continue
            body = '<div class="grid">' + ''.join(cards) + '</div>' if cards else '<p class="none">確認できた情報はありません</p>'
            parts.append(f'<div class="cat {cls}" data-cat="{key}"><h3><span class="tag">{label}</span><span class="cnt">{len(cards)}件</span></h3>{body}</div>')
        return ''.join(parts) + '</section>'
    for area in master['areas']:
        areas.append(area_html(area['no'], area['name'], groups[area['no']], area['stations']))
    template = Template((TEMPLATES / 'page_template.html').read_text())
    result = template.substitute(css=(TEMPLATES / 'page_styles.css').read_text(),
         js=(TEMPLATES / 'page_controls.js').read_text(),
         hero=hero,
         filters=filters,
         empty=empty,
         areas='\n'.join(areas))
    validate_html_bytes(result.encode())
    return result

def output_path():
    target = ROOT / 'website/index.html'
    if target.is_symlink() or target.parent.is_symlink() or target.parent.resolve() != ROOT.resolve() / 'website':
        raise ValueError('website/index.html must be inside the real website directory')
    return target

def write_html(text):
    target = output_path()
    validate_html_bytes(text.encode())
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent, delete=False) as f:
            temporary = Path(f.name)
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
            os.chmod(temporary, 420)
        os.replace(temporary, target)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return validate_html_bytes(text.encode())

def generate():
    output_path()
    return write_html(render(json.loads((ROOT / 'website/listings_and_progress.json').read_text())))


def main():
    result = generate()
    print({'output': 'website/index.html', 'sha256': result['sha256'], 'bytes': result['bytes']})
