"""Offline renderer using the protected 2026-11-06 design, never its store data."""
import argparse
from collections import Counter
import datetime as dt
import html
import json
import os
from pathlib import Path
from string import Template
import tempfile
from urllib.parse import urlsplit
from .data import JST
from .routine_site import ROOT, json_bytes, validate_json, validate_html_bytes, resource
from .weekly_review import review, day

TEMPLATES=Path(__file__).with_name('templates')
SITES = [("ik", "一休.com"), ("tb", "食べログ"), ("tc", "TableCheck")]
SWEETS = [("ichigo", "いちご"), ("melon", "メロン"), ("peach", "桃"), ("mango", "マンゴー"), ("grape", "ぶどう・マスカット"),
          ("kuri", "栗・マロン"), ("imo", "芋・かぼちゃ"), ("kaki", "柿・洋梨・いちじく"), ("citrus", "柑橘"), ("choco", "チョコレート"),
          ("wa", "抹茶・和"), ("macaron", "マカロン"), ("parfait", "パフェ"), ("scone", "スコーン"), ("halloween", "ハロウィン"), ("xmas", "クリスマス"), ("valentine", "バレンタイン"), ("whiteday", "ホワイトデー"), ("collab", "コラボ企画"), ("season", "季節の味覚"), ("other", "その他")]
CATS = [("cafe", "カフェ", "c-cafe"), ("hotel", "ホテル", "c-hotel"), ("lux", "ホテル（高級）", "c-lux")]
SVG_LOC = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5a4.5 4.5 0 0 0-4.5 4.5c0 3.4 4.5 8.5 4.5 8.5s4.5-5.1 4.5-8.5A4.5 4.5 0 0 0 8 1.5zm0 6.2a1.7 1.7 0 1 1 0-3.4 1.7 1.7 0 0 1 0 3.4z" fill="currentColor"/></svg>'
SVG_TEA = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9h13v4a6 6 0 0 1-6 6H10a6 6 0 0 1-6-6V9zm13 1h1.5a2.5 2.5 0 0 1 0 5H17" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M8 3.5c0 1.5 1.2 1.5 1.2 3M11.5 3.5c0 1.5 1.2 1.5 1.2 3" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>'
SVG_EXT = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3h7v7M13 3 6.5 9.5M11 9.5V13H3V5h3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
SVG_CLK = '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 4.6V8l2.4 1.6" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>'

EVENTS={'halloween','xmas','valentine','whiteday','collab','season'}
LABELS=dict(SWEETS)
CLASSES={k:(label,cls) for k,label,cls in CATS}
CLASSES['unknown']=('分類未確認','c-unknown')
HOSTS={'restaurant.ikyu.com':'ik','tabelog.com':'tb','www.tabelog.com':'tb','tablecheck.com':'tc','www.tablecheck.com':'tc'}


def esc(value):
    return html.escape(str(value),quote=True) if value is not None else '未確認'


def tags(value):
    values=value if isinstance(value,list) else [value] if isinstance(value,str) else []
    reverse={v:k for k,v in SWEETS}
    return sorted({v if v in LABELS else reverse[v] for v in values if isinstance(v,str) and (v in LABELS or v in reverse)})


def category(shop):
    value=shop.get('category')
    return value if isinstance(value,str) and value in CLASSES else 'unknown'


def condition(plan,shop,keys):
    value=None
    for source in (plan,shop):
        found=next((k for k in keys if k in source),None)
        if found is not None:
            value=source[found];break
    if value is True or value=='on':return 'on'
    if value is False or value=='no':return 'no'
    return 'off'


def amount(plan):
    value=plan.get('price_yen',plan.get('price_min'))
    return value if type(value) in (int,float) and value>=0 else None


def plan_tags(plan):
    return tags(plan.get('sweets',plan.get('sw')))+tags(plan.get('season'))


def plan_html(plan,shop,index,total,generated):
    first,last=day(plan.get('start')),day(plan.get('end'))
    date=lambda x:f'{x.year}/{x.month}/{x.day}' if x else '未確認'
    dates=(date(first)+'〜'+date(last)) if first or last else '提供期間 未確認'
    badge=''
    if generated and first and first>generated:badge='<span class="pst soon">これから</span>'
    elif generated and first and last and first<=generated<=last:badge='<span class="pst now">提供期間内</span>'
    price=amount(plan)
    wd=condition(plan,shop,('weekday_available','weekday','wd'))
    we=condition(plan,shop,('weekend_available','weekend','we'))
    sw=plan_tags(plan)
    specified=int(any(k in plan for k in ('sweets','sw','season')))
    attrs=f'data-tags-specified="{specified}" data-wd="{int(wd=="on")}" data-we="{int(we=="on")}" data-pk="{int(price is not None)}" data-sw="{esc(" ".join(sw))}" data-price="{price if price is not None else ""}"'
    out=[f'<div class="plan" {attrs}><div class="plan-hd"><span class="pno">プラン{index+1}／{total}</span><p class="pper{ " na" if not first and not last else ""}">{esc(dates)}</p>{badge}</div>',
         f'<p class="theme">{SVG_TEA}<span>{esc(plan.get("plan_name",plan.get("theme")))}</span></p>']
    if sw:out.append('<p class="swt" aria-label="スイーツ・季節">'+''.join('<span>'+esc(LABELS[k])+'</span>' for k in sw)+'</p>')
    if price is None:out.append('<div class="price"><span class="pdet">料金 未確認</span></div>')
    else:
        suffix='〜' if 'price_min' in plan and 'price_yen' not in plan else ''
        note=plan.get('price_note',plan.get('price_text')) or '税・サービス料条件 未確認'
        out.append(f'<div class="price"><span class="pbig">{price:,}<small>円{suffix}</small></span><span class="pdet">{esc(note)}</span></div>')
    chips=[]
    for state,label in ((wd,'平日'),(we,'土日祝')):
        text=label if state=='on' else label+' ✕' if state=='no' else label+' 未確認'
        chips.append(f'<span class="chip {state}">{text}</span>')
    time=plan.get('time_note',plan.get('time_text')) or '提供時間・利用時間 未確認'
    out.append('<div class="when"><div class="chips" aria-label="提供日">'+''.join(chips)+'</div>'+f'<p class="time">{SVG_CLK}<span>{esc(time)}</span></p></div>')
    if plan.get('note'):out.append('<p class="dtxt">'+esc(plan['note'])+'</p>')
    if plan.get('menu'):out.append('<p class="dtxt">メニュー：'+esc(plan['menu'])+'</p>')
    out.append('</div>')
    return ''.join(out)


def card(shop,plans,generated):
    cat=category(shop);label,cls=CLASSES[cat]
    shop_sw=tags(shop.get('sweets'))+tags(shop.get('season'))
    sw=sorted(set(shop_sw+[t for p in plans for t in plan_tags(p)]))
    wd=any(condition(p,shop,('weekday_available','weekday','wd'))=='on' for p in plans)
    we=any(condition(p,shop,('weekend_available','weekend','we'))=='on' for p in plans)
    pk=any(amount(p) is not None for p in plans)
    out=[f'<article class="card {cls}" data-cat="{cat}" data-shop-sw="{esc(" ".join(shop_sw))}" data-sw="{esc(" ".join(sw))}" data-wd="{int(wd)}" data-we="{int(we)}" data-pk="{int(pk)}">',
         f'<div class="top"><header><h4>{esc(shop.get("name"))}</h4>']
    if shop.get('hotel_name'):out.append('<p class="shop">'+esc(shop['hotel_name'])+'</p>')
    out.append('</header></div>')
    out.append(f'<p class="rnote">{esc(label)} ／ 確認日時：{esc(shop.get("checked_at"))}</p>')
    out.append(f'<p class="loc">{SVG_LOC}{esc(shop.get("station"))}</p>')
    if shop.get('address'):out.append('<p class="rnote">'+esc(shop['address'])+'</p>')
    out.append('<div class="meet"><p><span class="mk">駅の出口・徒歩</span>'+esc(shop.get('exit',shop.get('access')))+'</p></div>')
    url=shop.get('booking_url_info_only') or shop.get('source_url')
    if url:
        resource(url);site=HOSTS.get(urlsplit(url).hostname)
        if site is None:raise ValueError('booking URL must use Ikyu, Tabelog or TableCheck')
        out.append(f'<div class="links" aria-label="予約・情報サイト"><a class="lk lk-{site}" href="{esc(url)}" target="_blank" rel="noopener noreferrer">{dict(SITES)[site]}{SVG_EXT}</a></div>')
    else:out.append('<p class="rnote">予約情報リンク 未確認</p>')
    if sw:out.append('<p class="swt" aria-label="店舗の確認済みタグ">'+''.join('<span>'+esc(LABELS[k])+'</span>' for k in sw)+'</p>')
    else:out.append('<p class="rnote">スイーツ・季節分類 未確認</p>')
    if shop.get('time_note'):out.append('<p class="rnote">店舗の提供時間補足：'+esc(shop['time_note'])+'</p>')
    out.append('<div class="plans">'+''.join(plan_html(p,shop,i,len(plans),generated) for i,p in enumerate(plans))+'</div></article>')
    return ''.join(out),sw


def render(research,failures):
    validate_json(json_bytes(research));validate_json(json_bytes(failures),True)
    check=review(research)
    invalid=[e for e in check['errors'] if e['reason']!='outside_research_period']
    if invalid:raise ValueError('invalid date input: '+json.dumps(invalid))
    outside={(e['shop_index'],e['plan_index']) for e in check['outside_plans']}
    stamp=research.get('generated_at')
    generated=dt.datetime.fromisoformat(stamp).astimezone(JST).date() if stamp else None
    master=json.loads((ROOT/'data/store_master.json').read_text())
    groups={a['no']:[] for a in master['areas']};unassigned=[];tot=Counter();swc=Counter();plan_count=0
    area_names={a['name']:a['no'] for a in master['areas']}
    for si,shop in enumerate(research['shops']):
        plans=[p for pi,p in enumerate(shop.get('plans',[])) if (si,pi) not in outside]
        if not plans:continue
        markup,sw=card(shop,plans,generated)
        no=shop.get('area_no')
        if type(no) is not int:no=area_names.get(shop.get('area'))
        target=groups[no] if no in groups else unassigned
        target.append((category(shop),markup));tot[category(shop)]+=1;swc.update(sw);plan_count+=len(plans)
    per=research['period'];start,end=day(per['start']),day(per['end'])
    stats=''.join(f'<div class="stat s-{cat}"><b>{tot[cat]}</b><span>{label}</span></div>' for cat,label,cls in CATS)
    hero=f'<div class="hero"><div class="hero-in"><div><h1>東京 アフタヌーンティー</h1><p class="period">{start.year}年{start.month}月{start.day}日〜{end.year}年{end.month}月{end.day}日<small>（40日間）</small></p><p class="lead legendline"><span class="lg"><span class="chip on">平日</span> 提供あり</span><span class="lg"><span class="chip no">土日祝 ✕</span> そのプランでは提供なし</span></p></div><div class="stats">{stats}</div></div></div>'
    def buttons(keys):
        return ''.join(f'<button class="fb f-x" data-sw="{k}" aria-pressed="false">{label.replace("・","・<wbr>")}<span class="bc{ " zero" if swc[k]==0 else ""}">{swc[k]}</span></button>' for k,label in SWEETS if k in keys)
    cats=''.join(f'<button class="fb f-{cat}" data-cat="{cat}" aria-pressed="true">{label}</button>' for cat,label,cls in CATS)
    if tot['unknown']:cats+='<button class="fb f-x" data-cat="unknown" aria-pressed="true">分類未確認</button>'
    nav=''.join(f'<a class="area-btn" href="#a{a["no"]}">{esc(a["name"]).replace("・","・<wbr>")}</a>' for a in master['areas'])
    row=lambda label,body,aria:f'<div class="frow" role="group" aria-label="{aria}"><span class="lb">{label}</span><div class="btns">{body}</div></div>'
    filters='<div class="fpanel" id="top"><div class="fpanel-in">'+row('分類',cats,'分類で絞り込み')+row('条件','<button class="fb f-x" data-x="wd" aria-pressed="false">平日に行ける</button><button class="fb f-x" data-x="we" aria-pressed="false">土日祝に行ける</button><button class="fb f-x" data-x="pk" aria-pressed="false">値段確認済</button>','条件で絞り込み')+row('スイーツ',buttons(set(LABELS)-EVENTS),'スイーツで絞り込み')+row('イベント<br>季節',buttons(EVENTS-{'halloween'}),'イベント・季節で絞り込み')+f'<nav class="frow" aria-label="エリア"><span class="lb">場所</span><div class="btns">{nav}</div></nav>'
    filters+='''<div class="search-fields"><label for="shop-search">店舗・ホテル名<input id="shop-search" type="search" autocomplete="off"></label><label for="theme-search">プラン名・テーマ<input id="theme-search" type="search" autocomplete="off"></label><label for="price-filter">料金帯<select id="price-filter"><option value="all">すべて</option><option value="low">8,000円以下</option><option value="mid">8,001〜10,000円</option><option value="high">10,001円以上</option><option value="unknown">料金未確認</option></select></label></div><div class="filter-status"><span id="filter-status" role="status" aria-live="polite"></span><button class="lk" id="reset-filters" type="button">絞り込みを解除</button></div></div></div>'''
    count=sum(tot.values());unresearched=sum(f['status']=='unresearched' and f.get('scope','shop')=='shop' for f in failures['failures'])
    notice=f'<div class="box"><p class="lead">確認日時：{esc(stamp)} ／ 掲載 {count}店舗・{plan_count}プラン ／ 未調査店舗 {unresearched}件。掲載なしはAT提供なしを意味しません。料金・期間・曜日の不明値は未確認です。予約操作・空席確認は行っていません。</p>'
    if research.get('note'):notice+='<p class="rnote">'+esc(research['note'])+'</p>'
    if tot['unknown']:notice+='<p class="rnote">分類未確認：'+str(tot['unknown'])+'店舗。価格や名称からカテゴリを推測していません。</p>'
    if outside:notice+='<p class="rnote">対象期間と重ならない'+str(len(outside))+'プランは掲載対象から除きました。</p>'
    notice+='</div>'
    empty='<p class="none" id="no-results" hidden>条件に合う掲載情報はありません。絞り込みを変更してください。</p>'
    if not count:empty+='<p class="none">今週は確認できた情報がありません</p>'
    areas=[]
    def area_html(no,name,entries,stations=None):
        parts=[f'<section class="area" id="a{no}"><h2><span class="no">{no:02d}</span>{esc(name)}<span class="acnt">{len(entries)}件</span></h2>']
        if stations:parts.append('<p class="rnote">対象駅：'+esc('、'.join(stations))+'</p>')
        for key,(label,cls) in sorted(CLASSES.items(),key=lambda item:not any(cat==item[0] for cat,markup in entries)):
            cards=[markup for cat,markup in entries if cat==key]
            if key=='unknown' and not cards:continue
            body='<div class="grid">'+''.join(cards)+'</div>' if cards else '<p class="none">今週は確認できた情報がありません</p>'
            parts.append(f'<div class="cat {cls}" data-cat="{key}"><h3><span class="tag">{label}</span><span class="cnt">{len(cards)}件</span></h3>{body}</div>')
        return ''.join(parts)+'</section>'
    for area in master['areas']:areas.append(area_html(area['no'],area['name'],groups[area['no']],area['stations']))
    if unassigned:areas.append(area_html(0,'エリア未確認',unassigned))
    template=Template((TEMPLATES/'routine.html').read_text())
    result=template.substitute(css=(TEMPLATES/'routine.css').read_text(),extra_css=(TEMPLATES/'routine_extra.css').read_text(),js=(TEMPLATES/'routine.js').read_text(),extra_js=(TEMPLATES/'routine_extra.js').read_text(),hero=hero,filters=filters,notice=notice,empty=empty,areas='\n'.join(areas))
    validate_html_bytes(result.encode())
    return result


def generate():
    target=ROOT/'site/index.html'
    if target.is_symlink() or target.parent.is_symlink() or target.parent.resolve()!=ROOT.resolve()/'site':raise ValueError('site/index.html must be inside the real site directory')
    text=render(json.loads((ROOT/'site/research.json').read_text()),json.loads((ROOT/'site/search_failures.json').read_text()))
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=target.parent,delete=False) as f:
            temporary=Path(f.name);f.write(text);f.flush();os.fsync(f.fileno());os.chmod(temporary,0o644)
        os.replace(temporary,target)
    finally:
        if temporary and temporary.exists():temporary.unlink()
    return validate_html_bytes(text.encode())


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['generate']);parser.parse_args()
    result=generate();print({'output':'site/index.html','sha256':result['sha256'],'bytes':result['bytes']})


if __name__=='__main__':main()
