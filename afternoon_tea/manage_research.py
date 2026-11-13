"""Research progress kept in website/listings_and_progress.json: resume from unresearched shops, never from No.1.

Queue order: owner's list not yet researched -> owner's list to retry (failed or unclear, after
`retry_after_days`) -> recheck of confirmed information (up to `recheck_per_run`) -> shops outside
the list found by public search -> the remaining rechecks. A failure is never a confirmation and
never "not offered".
"""
import copy
import datetime as dt
import hashlib
import json
import re
import shutil
import time
import unicodedata
from collections import Counter
from pathlib import Path

from afternoon_tea.research_settings import (AREAS, ROOT, candidates, excluded_genre, name_parts, norm, same_venue,
                                  search_queries, settings)
from afternoon_tea.read_public_pages import JST, RUN, RunState, atomic_json, load_json, now_iso, store_lock

RESEARCH = ROOT / 'website/listings_and_progress.json'
SCHEMA = 2
STATUSES = {
    'plan_confirmed': '具体的なプランを確認',
    'general_only': '一般的な紹介のみ（具体的なプラン未確認）',
    'no_at_found': '読めたページにアフタヌーンティーの記載なし（提供なしとは扱わない）',
    'failed': '取得不能（アクセス拒否・通信・robotsなど）',
    'excluded_genre': '除外ジャンル',
    'out_of_area': '東京14エリア外',
    'plans_ended': '掲載中のプランが提供期間を終了',
}
RETRY = {'failed', 'general_only', 'no_at_found'}
SHOP_FIELDS = ('id', 'candidate_no', 'origin', 'name', 'hotel_name', 'area_no', 'genre', 'address', 'station',
               'source_site', 'info_url', 'reference_urls', 'plans', 'category', 'category_price_yen')
PLAN_FIELDS = ('plan_name', 'price_yen', 'discount_price_yen', 'price_note', 'start', 'end', 'weekday_available',
               'weekend_available', 'time_note', 'menu', 'source_url', 'checked_at', 'cc', 'season')
ENTRY_FIELDS = ('key', 'origin', 'name', 'hotel_name', 'area_no', 'genre', 'status', 'attempted_at', 'confirmed_at',
                'reason', 'note', 'urls')
STATION = re.compile(r'^[^\s／/、,]{1,30}駅$')


def period(now=None, days=None):
    from afternoon_tea.prepare_listings import period as window
    return window(now=now)


def stamp(value):
    if not isinstance(value, str):
        raise ValueError('timestamp_required')
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('timestamp_timezone_required')
    return parsed


def shop_key(name, hotel_name=None):
    digest = hashlib.sha1('|'.join(sorted(name_parts(name, hotel_name))).encode()).hexdigest()[:10]
    return 'x-' + digest


def empty():
    now = dt.datetime.now(JST)
    return {'schema_version': SCHEMA, 'generated_at': now.isoformat(timespec='seconds'), 'period': period(now),
            'shops': [], 'progress': {'updated_at': None, 'entries': {}},
            'excluded_sensitive_plans': {'current': 0, 'previous': 0}}


def migrate(data, rows=None, aliases=None):
    """Version 1 data (list_url based) to version 2 without changing any checked_at.

    Shops are linked to the owner's list by name/facility evidence, never by URL equality;
    unmatched shops are kept as shops found outside the list.
    """
    if data.get('schema_version') == SCHEMA:
        return data
    if data.get('schema_version') != 1:
        raise ValueError('unknown_schema_version')
    rows = candidates() if rows is None else rows
    aliases = aliases or {}
    result = {'schema_version': SCHEMA, 'generated_at': data.get('generated_at'), 'period': data.get('period'),
              'shops': [], 'progress': {'updated_at': None, 'entries': {}},
              'excluded_sensitive_plans': data.get('excluded_sensitive_plans') or {'current': 0, 'previous': 0}}
    for old in data.get('shops', []):
        name, hotel = old.get('name'), old.get('hotel_name')
        row = None
        if name in aliases:
            row = next(r for r in rows if r['No'] == str(aliases[name]))
        else:
            matches = [r for r in rows if same_venue((name, hotel), (r['店舗名'], r['ホテル名']))]
            row = matches[0] if len(matches) == 1 else None
        shop = {k: copy.deepcopy(old[k]) for k in ('address', 'station', 'source_site', 'plans', 'category',
                                                   'category_price_yen') if k in old}
        shop.update(name=name, hotel_name=hotel, area_no=old.get('area_no'))
        if row is not None:
            shop.update(id='c' + row['No'], candidate_no=int(row['No']), origin='list', genre=row['ジャンル'] or None)
        else:
            shop.update(id=shop_key(name, hotel), candidate_no=None, origin='explore', genre=old.get('genre'))
        refs = [u for u in (old.get('list_url'),) if isinstance(u, str)]
        if refs:
            shop['reference_urls'] = refs
        if any(s['id'] == shop['id'] for s in result['shops']):
            target = next(s for s in result['shops'] if s['id'] == shop['id'])
            names = {p.get('plan_name') for p in target['plans']}
            target['plans'] += [p for p in shop.get('plans', []) if p.get('plan_name') not in names]
            continue
        result['shops'].append(shop)
        confirmed = max((p['checked_at'] for p in shop.get('plans', []) if isinstance(p.get('checked_at'), str)),
                        default=None, key=lambda v: stamp(v))
        result['progress']['entries'][shop['id']] = {
            'key': shop['id'], 'origin': shop['origin'], 'name': name, 'hotel_name': hotel, 'area_no': shop['area_no'],
            'genre': shop['genre'], 'status': 'plan_confirmed', 'attempted_at': confirmed, 'confirmed_at': confirmed,
            'reason': None, 'note': 'Git履歴の公開データから確認日時を変えずに復旧', 'urls': []}
    return result


def load(path=None):
    path = Path(path or RESEARCH)
    if path.is_symlink():
        raise ValueError('symlink data forbidden')
    data = load_json(path)
    data = migrate(data)
    data.setdefault('progress', {'updated_at': None, 'entries': {}})
    data.setdefault('excluded_sensitive_plans', {'current': 0, 'previous': 0})
    return data


def save(data, path=None):
    atomic_json(path or RESEARCH, data)


def _age_days(value, now):
    try:
        return (now - stamp(value)).total_seconds() / 86400
    except (TypeError, ValueError):
        return float('inf')


def queue(data, rows=None, now=None, limits=None):
    """Tasks in priority order. Reference URLs are hints, never a required first page."""
    rows = candidates() if rows is None else rows
    now = now or dt.datetime.now(JST)
    limits = limits or settings()
    entries = data.get('progress', {}).get('entries', {})
    shops = {s.get('id'): s for s in data.get('shops', [])}
    unresearched, retry, recheck = [], [], []
    for row in rows:
        key = 'c' + row['No']
        task = {'key': key, 'kind': None, 'no': int(row['No']), 'name': row['店舗名'], 'hotel_name': row['ホテル名'] or None,
                'area_no': int(row['エリア番号']), 'genre': row['ジャンル'] or None,
                'preferred_site': row['優先して調べるサイト'] or None,
                'queries': search_queries(row['店舗名'], row['ホテル名'], row['優先して調べるサイト'] or None),
                'reference_url': row['参考URL'] or None, 'note': row['備考'] or None}
        label = excluded_genre(row['ジャンル'])
        if label:
            continue  # The owner's genre exclusion has priority over the list.
        entry = entries.get(key)
        if entry is None:
            unresearched.append({**task, 'kind': 'unresearched'})
        elif entry['status'] in RETRY and _age_days(entry.get('attempted_at'), now) >= limits['retry_after_days']:
            retry.append({**task, 'kind': 'retry', 'last_status': entry['status'], 'last_reason': entry.get('reason'),
                          'attempted_at': entry.get('attempted_at')})
        elif entry['status'] in ('plan_confirmed', 'plans_ended'):
            due = entry['status'] == 'plans_ended' or _age_days(entry.get('confirmed_at'), now) >= limits['recheck_after_days']
            if due and _age_days(entry.get('attempted_at'), now) >= 1:
                recheck.append({**task, 'kind': 'recheck', 'confirmed_at': entry.get('confirmed_at')})
    for key, entry in entries.items():
        if entry.get('origin') != 'explore':
            continue
        task = {'key': key, 'kind': 'recheck', 'no': None, 'name': entry.get('name'), 'hotel_name': entry.get('hotel_name'),
                'area_no': entry.get('area_no'), 'genre': entry.get('genre'), 'preferred_site': None,
                'queries': search_queries(entry.get('name'), entry.get('hotel_name')), 'reference_url': None, 'note': None,
                'confirmed_at': entry.get('confirmed_at')}
        shop = shops.get(key)
        if entry['status'] in ('plan_confirmed', 'plans_ended'):
            due = (entry['status'] == 'plans_ended' or _age_days(entry.get('confirmed_at'), now) >= limits['recheck_after_days']
                   or (shop is not None and not shop.get('genre')))
            if due and _age_days(entry.get('attempted_at'), now) >= 1:
                recheck.append(task)
        elif entry['status'] in RETRY and _age_days(entry.get('attempted_at'), now) >= limits['retry_after_days']:
            retry.append({**task, 'kind': 'retry', 'last_status': entry['status'], 'last_reason': entry.get('reason')})
    recheck.sort(key=lambda t: t.get('confirmed_at') or '')
    share = int(limits['recheck_per_run'])
    explore = {'key': None, 'kind': 'explore', 'note': '候補リスト外の有名ホテル・ラウンジ・カフェを、エリア名と「アフタヌーンティー」で公開検索して探す',
               'queries': ['東京 ホテル アフタヌーンティー', '銀座 アフタヌーンティー ラウンジ']}
    order = unresearched + retry + recheck[:share] + [explore] + recheck[share:]
    return {'counts': {'unresearched': len(unresearched), 'retry': len(retry), 'recheck': len(recheck),
                       'list_total': len(rows),
                       'excluded_genre_rows': sum(bool(excluded_genre(r['ジャンル'])) for r in rows)},
            'tasks': order}


def begin(now=None, run=None):
    """Start a run: keep all saved progress and listings; set this run's period and limits."""
    now = now or dt.datetime.now(JST)
    run = run or RunState()
    limits = settings()
    data = load()
    RUN.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RESEARCH, run.directory / 'previous.json')
    data['generated_at'] = now.isoformat(timespec='seconds')
    data['period'] = period(now, limits['period_days'])
    data['excluded_sensitive_plans'] = {'current': 0, 'previous': 0}  # counts for this run only
    save(data)
    run.start(limits)
    q = queue(data, now=now, limits=limits)
    return {'period': data['period'], 'limits': limits, 'queue': q['counts'],
            'next': [summary(t) for t in q['tasks'][:5]]}


def summary(task):
    return {k: v for k, v in task.items() if v is not None}


def next_tasks(count=5):
    data = load()
    q = queue(data)
    return {'queue': q['counts'], 'next': [summary(t) for t in q['tasks'][:count]]}


def start_task(key, run=None):
    """Mark the shop being researched; the configurable per-shop limit counts from here."""
    run = run or RunState()
    data = load()
    tasks = {t['key']: t for t in queue(data)['tasks'] if t.get('key')}
    with run.update() as state:
        state['task'] = {'key': key, 'started_at': time.time()}
    task = tasks.get(key)
    return summary(task) if task else {'key': key, 'note': '優先キューの外の店舗です。調査後に record で保存します。'}


def _text(value, limit, field):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError('invalid_text:' + field)
    value = value.strip()
    return value or None


def _visited(state):
    visits = {}
    for visit in state.get('visits', []):
        for url in (visit['url'], visit['final_url']):
            visits[url.split('#')[0]] = visit['at']
    return visits


def clean_station(value):
    if value is None:
        return None
    names = []
    for name in re.split(r'[／/、,]', unicodedata.normalize('NFKC', str(value)).replace(' ', '')):
        if not name:
            continue
        if not STATION.match(name):
            raise ValueError('station_must_be_station_names_only')
        if name not in names:
            names.append(name)
    return '／'.join(names) or None


def clean_plan(raw, visits):
    from afternoon_tea.prepare_listings import day
    if not isinstance(raw, dict) or set(raw) - set(PLAN_FIELDS):
        raise ValueError('unknown_plan_field')
    plan = {}
    plan['plan_name'] = _text(raw.get('plan_name'), 300, 'plan_name')
    if not plan['plan_name']:
        raise ValueError('plan_name_required')
    url = raw.get('source_url')
    if not isinstance(url, str) or url.split('#')[0] not in visits:
        raise ValueError('source_url_must_be_a_page_read_in_this_run')
    plan['source_url'] = url.split('#')[0]
    plan['checked_at'] = visits[plan['source_url']]  # the time the page was actually read
    for key in ('price_yen', 'discount_price_yen'):
        value = raw.get(key)
        if value is not None and (type(value) is not int or value <= 0 or value > 1000000):
            raise ValueError('invalid_price:' + key)
        plan[key] = value
    for key in ('start', 'end'):
        plan[key] = raw.get(key)
        day(plan[key])
    if plan['start'] and plan['end'] and plan['start'] > plan['end']:
        raise ValueError('plan_start_after_end')
    for key in ('weekday_available', 'weekend_available'):
        if raw.get(key) not in (None, True, False):
            raise ValueError('invalid_boolean:' + key)
        plan[key] = raw.get(key)
    plan['price_note'] = _text(raw.get('price_note'), 300, 'price_note')
    plan['time_note'] = _text(raw.get('time_note'), 300, 'time_note')
    plan['menu'] = _text(raw.get('menu'), 3000, 'menu')
    plan['cc'] = raw.get('cc') if isinstance(raw.get('cc'), str) else None
    return plan


def record(payload, run=None, rows=None, now=None):
    """Save one shop's result immediately, so the next run resumes from the next shop."""
    from afternoon_tea.publication_checks import SensitiveDataError, json_bytes, scan
    run = run or RunState()
    rows = candidates() if rows is None else rows
    now = now or dt.datetime.now(JST)
    state = run.load()
    visits = _visited(state)
    if not isinstance(payload, dict) or set(payload) - {'key', 'status', 'reason', 'note', 'urls', 'shop', 'keep_other_plans'}:
        raise ValueError('unknown_record_field')
    status = payload.get('status')
    if status not in STATUSES or status == 'plans_ended':
        raise ValueError('invalid_status')
    shop_in = payload.get('shop') or {}
    if set(shop_in) - {'name', 'hotel_name', 'area_no', 'genre', 'address', 'station', 'source_site', 'info_url', 'plans'}:
        raise ValueError('unknown_shop_field')
    key = payload.get('key')
    row = None
    if key is not None:
        if not isinstance(key, str):
            raise ValueError('invalid_key')
        if re.fullmatch(r'c\d+', key):
            row = next((r for r in rows if 'c' + r['No'] == key), None)
            if row is None:
                raise ValueError('unknown_candidate')
    with store_lock(RUN / 'research'):
        data = load()
        entries = data['progress']['entries']
        if key is None:
            name = _text(shop_in.get('name'), 200, 'name')
            if not name:
                raise ValueError('shop_name_required_for_a_shop_outside_the_list')
            hotel = _text(shop_in.get('hotel_name'), 200, 'hotel_name')
            matches = [r for r in rows if same_venue((name, hotel), (r['店舗名'], r['ホテル名']))]
            if len(matches) == 1:
                row = matches[0]
                key = 'c' + row['No']
            else:
                known = [k for k, e in entries.items() if e.get('origin') == 'explore'
                         and same_venue((name, hotel), (e.get('name'), e.get('hotel_name')))]
                key = known[0] if len(known) == 1 else shop_key(name, hotel)
        old = entries.get(key, {})
        origin = 'list' if row is not None else 'explore'
        name = (row['店舗名'] if row else None) or _text(shop_in.get('name'), 200, 'name') or old.get('name')
        hotel = (row['ホテル名'] or None) if row else (_text(shop_in.get('hotel_name'), 200, 'hotel_name') or old.get('hotel_name'))
        area = int(row['エリア番号']) if row else shop_in.get('area_no', old.get('area_no'))
        genre = (row['ジャンル'] or None) if row and row['ジャンル'] else (
            _text(shop_in.get('genre'), 60, 'genre') or old.get('genre'))
        if status == 'plan_confirmed' and origin == 'explore' and not genre:
            raise ValueError('genre_of_the_venue_required_for_a_shop_outside_the_list')
        if excluded_genre(genre) and status == 'plan_confirmed':
            status = 'excluded_genre'
        if status == 'plan_confirmed' and (type(area) is not int or area not in AREAS):
            status = 'out_of_area'
        urls = payload.get('urls') or []
        if not isinstance(urls, list) or len(urls) > 10 or not all(isinstance(u, str) and u.startswith(('https://', 'http://'))
                                                                   and len(u) < 600 for u in urls):
            raise ValueError('invalid_urls')
        entry = {'key': key, 'origin': origin, 'name': name, 'hotel_name': hotel, 'area_no': area, 'genre': genre,
                 'status': status, 'attempted_at': now.isoformat(timespec='seconds'),
                 'confirmed_at': old.get('confirmed_at'), 'reason': _text(payload.get('reason'), 100, 'reason'),
                 'note': _text(payload.get('note'), 300, 'note'), 'urls': urls}
        result = {'key': key, 'status': status, 'saved_plans': 0, 'excluded_sensitive_plans': 0}
        shops = data['shops']
        existing = next((s for s in shops if s.get('id') == key), None)
        if status == 'plan_confirmed':
            plans = shop_in.get('plans')
            if not isinstance(plans, list) or not plans:
                raise ValueError('plans_required_for_plan_confirmed')
            cleaned = []
            for raw in plans:
                plan = clean_plan(raw, visits)
                try:
                    scan(json_bytes(plan))
                except SensitiveDataError:
                    result['excluded_sensitive_plans'] += 1
                    data['excluded_sensitive_plans']['current'] += 1
                    continue
                cleaned.append(plan)
            if not cleaned:
                entry['status'] = 'general_only'
                entry['note'] = entry['note'] or '確認したプランが秘密情報検査で除外された'
            else:
                info = shop_in.get('info_url')
                if info is not None and (not isinstance(info, str) or info.split('#')[0] not in visits):
                    raise ValueError('info_url_must_be_a_page_read_in_this_run')
                shop = {'id': key, 'candidate_no': int(row['No']) if row else None, 'origin': origin, 'name': name,
                        'hotel_name': hotel, 'area_no': area, 'genre': genre,
                        'address': _text(shop_in.get('address'), 200, 'address'),
                        'station': clean_station(shop_in.get('station')),
                        'source_site': _text(shop_in.get('source_site'), 60, 'source_site'),
                        'info_url': info.split('#')[0] if info else None, 'plans': cleaned}
                if existing is not None:
                    if existing.get('reference_urls'):
                        shop['reference_urls'] = existing['reference_urls']
                    if payload.get('keep_other_plans'):
                        names = {p['plan_name'] for p in cleaned}
                        shop['plans'] = cleaned + [p for p in existing.get('plans', []) if p.get('plan_name') not in names]
                    shops.remove(existing)
                shops.append(shop)
                entry['confirmed_at'] = max(p['checked_at'] for p in cleaned)
                result['saved_plans'] = len(cleaned)
        elif status in ('excluded_genre', 'out_of_area') and existing is not None:
            shops.remove(existing)
        # Other outcomes keep earlier confirmed plans: a failure is not "no longer offered".
        entries[key] = entry
        data['progress']['updated_at'] = now.isoformat(timespec='seconds')
        save(data)
    with run.update() as state:
        state['task'] = None
    return result


def report(state=None, data=None, rows=None, now=None):
    from afternoon_tea.prepare_listings import displayable
    from afternoon_tea.research_settings import settings as limits_of
    state = state or RunState().load()
    data = data or load()
    rows = candidates() if rows is None else rows
    now = now or dt.datetime.now(JST)
    start = dt.datetime.fromisoformat(state['started_iso'])
    entries = data['progress']['entries']
    this_run = [e for e in entries.values() if e.get('attempted_at') and stamp(e['attempted_at']) >= start]
    statuses = Counter(e['status'] for e in this_run)
    shown = list(displayable(data))
    plans = [p for _, ps in shown for p in ps]
    fresh = [p for p in plans if stamp(p['checked_at']) >= start]
    stale_days = limits_of()['stale_after_days']
    stale = [p for p in plans if (now - stamp(p['checked_at'])).days >= stale_days]
    q = queue(data, rows=rows, now=now)
    failed = [e for e in this_run if e['status'] in RETRY]
    lines = ['## 調査結果', '',
             '- 対象期間: %s〜%s' % (data['period']['start'], data['period']['end']),
             '- 今回調べた店舗: %d（%s）' % (len(this_run), '、'.join('%s %d' % (STATUSES[k], v) for k, v in sorted(statuses.items())) or 'なし'),
             '- 今回確認できたプラン: %d（%d店舗）' % (len(fresh), len({id(s) for s, ps in shown if any(p in fresh for p in ps)})),
             '- 掲載: %d店舗・%dプラン（うち%d日以上前に確認した過去の確認情報 %dプラン）' % (len(shown), len(plans), stale_days, len(stale)),
             '- 未調査（候補リスト）: %d / 対象 %d（除外ジャンル %d行を除く）' % (
                 q['counts']['unresearched'], q['counts']['list_total'] - q['counts']['excluded_genre_rows'],
                 q['counts']['excluded_genre_rows']),
             '- 再試行待ち: %d、再確認対象: %d' % (q['counts']['retry'], q['counts']['recheck']),
             '- 秘密情報・個人情報の検査で除外したプラン数: %d' % sum(data.get('excluded_sensitive_plans', {}).values()),
             '- ブラウザで開いたページ: %d、送信前に止めた禁止操作: %d、止めた補助通信: %d%s' % (
                 state.get('browser_pages', 0), state.get('blocked_operations', 0), state.get('blocked_resources', 0),
                 '（ブラウザ利用不可: ' + state['browser_unavailable'] + '）' if state.get('browser_unavailable') else ''),
             '- 要求数: %d、この実行で停止した取得先: %s' % (state.get('navigations', 0), '、'.join(
                 '%s（%s）' % (h, r) for h, r in sorted(state.get('blocked_hosts', {}).items())) or 'なし')]
    if failed:
        lines.append('- 取得不能・未確定（次回再試行）: ' + '、'.join(
            '%s（%s）' % (e['name'], e.get('reason') or STATUSES[e['status']]) for e in failed[:40]))
    if not shown:
        lines.append('- 掲載対象が0件のため、この結果では自動マージ・公開を行いません（前回の公開サイトを維持）。')
    lines.append('')
    return '\n'.join(lines)
