"""Weekly list reading: candidate rows in order from No.1, list URLs only.

`begin` starts the week; `fetch N [URL]` reads row N's list URL (or a plan
detail page of that same shop). Page text is printed for Claude to read and is
never saved. The temporary state in .staging keeps only counts, row numbers
and times for this week's limits and report; `begin` erases it.
"""
import csv
import datetime as dt
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import time
from urllib.error import URLError
from urllib.parse import urljoin, urlsplit
from afternoon_tea.common import ROOT
from afternoon_tea.collection.reader import Reader, RESEARCH_SECONDS, MAX_REQUESTS, SHOP_SECONDS, INTERVAL
from afternoon_tea.collection.transport import ForbiddenOperation, check_scope
from afternoon_tea.processing.dates import JST, period

HEADERS = ['No', '店名', '最寄り駅', 'エリア番号', 'ジャンル', '予約サイト', '予約ページURL', '備考']
STATE = ROOT / '.staging/weekly'
EXCERPT_CHARS = 800
MAX_EXCERPT = 12000
AT_WORDS = re.compile(r'アフタヌーン\s*ティー|afternoon\s*tea|ハイティー|high\s*tea', re.I)
# Reasons are counted for the PR body; shop names are never recorded.
REASONS = {
    'robots': 'robots.txtで禁止・不明',
    'denied': '403・429・CAPTCHA・同一サイトの停止',
    'forbidden': '禁止URL・転送・範囲外',
    'network': '通信・HTTPエラー',
    'unusable': 'HTML以外・サイズ超過・秘密情報',
    'shop_time_limit': '1店舗の時間上限',
    'no_plan': 'ATプラン未確認・情報不足',
}


class BudgetExhausted(RuntimeError):
    pass


class Page(HTMLParser):

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript', 'template'):
            self.hidden += 1
        if tag == 'a':
            self.links.append(dict(attrs).get('href') or '')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'template') and self.hidden:
            self.hidden -= 1

    def handle_data(self, text):
        if not self.hidden and text.strip():
            self.parts.append(text.strip())


def candidates(path=None):
    with Path(path or ROOT / 'data/references/user_candidates.csv').open(encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != HEADERS:
            raise ValueError('candidate_columns_invalid')
        rows = list(reader)
    for (no, row) in enumerate(rows, 1):
        if row['No'] != str(no) or row['エリア番号'] not in {str(n) for n in range(1, 15)}:
            raise ValueError('candidate_number_or_area_invalid')
        check_scope(row['予約ページURL'], row['予約ページURL'])
    return rows


def reason(error):
    text = str(error)
    if isinstance(error, ForbiddenOperation):
        return 'forbidden'
    if text.startswith('robots'):
        return 'robots'
    if text in ('HTTP_403', 'HTTP_429', 'access_challenge', 'host_stopped_this_week'):
        return 'denied'
    if text.startswith(('HTTP_', 'browser_HTTP_')) or isinstance(error, (URLError, OSError)):
        return 'network'
    if text == 'shop_time_limit':
        return 'shop_time_limit'
    return 'unusable'


def _load():
    path = STATE / 'state.json'
    if not path.exists():
        raise RuntimeError('run_begin_first')
    return json.loads(path.read_text())


def _save(state):
    from .storage import atomic_json
    atomic_json(STATE / 'state.json', state)


def begin(now=None):
    """Start the week: copy the previous site data, start an empty research file."""
    from .storage import atomic_json, store_lock
    now = now or dt.datetime.now(JST)
    research = ROOT / 'site/research.json'
    if research.is_symlink():
        raise ValueError('symlink data forbidden')
    with store_lock(STATE):
        shutil.copyfile(research, STATE / 'previous.json')
        atomic_json(research, {'schema_version': 1, 'generated_at': now.isoformat(timespec='seconds'),
                               'period': period(now=now), 'shops': []})
        _save({'started_at': time.time(), 'started_iso': now.isoformat(timespec='seconds'), 'requests': 0,
               'last_request': 0, 'blocked_hosts': [], 'robots': {}, 'current': 0, 'rows': {},
               'browser_runs': 0, 'browser_unavailable': None, 'blocked_operations': 0, 'blocked_resources': 0})
    return {'research_seconds': RESEARCH_SECONDS, 'max_requests': MAX_REQUESTS, 'shop_seconds': SHOP_SECONDS,
            'starts_at_no': 1, 'candidates': len(candidates()), 'period': period(now=now)}


def _links(base, hrefs, list_url):
    found = []
    for href in hrefs:
        target = urljoin(base, href or '').split('#')[0]
        try:
            check_scope(target, list_url)
        except (ForbiddenOperation, ValueError):
            continue
        if target != base and target not in found:
            found.append(target)
    return found


def excerpt(text):
    """Merge context windows around AT words; use --full for the complete text."""
    windows = []
    for match in AT_WORDS.finditer(text):
        start, end = max(0, match.start()-EXCERPT_CHARS), min(len(text), match.end()+EXCERPT_CHARS)
        if windows and start <= windows[-1][1]:
            windows[-1] = (windows[-1][0], end)
        else:
            windows.append((start, end))
        if sum(end-start for start, end in windows) >= MAX_EXCERPT:
            break
    return '\n…\n'.join(text[start:end] for start, end in windows)[:MAX_EXCERPT]


def fetch(no, url=None, use_browser=False, reader_factory=Reader, renderer=None, full=False):
    """Read row `no` (in order from 1) or a plan detail page of that same shop."""
    from .storage import store_lock
    rows = candidates()
    with store_lock(STATE):
        state = _load()
        elapsed = time.time() - state['started_at']
        if not 0 <= elapsed < RESEARCH_SECONDS or state['requests'] >= MAX_REQUESTS:
            raise BudgetExhausted('research_budget_exhausted_publish_collected_results')
        if not 1 <= no <= len(rows):
            raise ValueError('no_such_row')
        if no not in (state['current'], state['current'] + 1):
            raise ValueError('rows_are_read_in_order_from_No.1_next_is_%d' % (state['current'] + 1))
        row = rows[no - 1]
        list_url = row['予約ページURL']
        target = url or list_url
        first = str(no) not in state['rows']
        entry = state['rows'].setdefault(str(no), {'site': row['予約サイト'], 'first_at': time.time(),
                                                  'outcome': 'no_plan', 'browser': False})
        state['current'] = no
        reader = reader_factory(max_requests=MAX_REQUESTS - state['requests'],
                                timeout=min(15, RESEARCH_SECONDS - elapsed), seconds=RESEARCH_SECONDS - elapsed)
        reader.blocked_hosts.update(state['blocked_hosts'])
        reader.robots_cache = state.get('robots', {})
        reader.last_request = time.monotonic() - max(0, time.time() - state['last_request'])
        method = 'get'
        try:
            if time.time() - entry['first_at'] > SHOP_SECONDS:
                raise RuntimeError('shop_time_limit')
            check_scope(target, list_url)
            raw = reader.fetch(target, list_url)
            page = Page()
            page.feed(raw)
            text = '\n'.join(page.parts)
            links = _links(target, page.links, list_url)
            if use_browser or not AT_WORDS.search(text):
                result = _browse(state, entry, target, list_url, renderer)
                if result:
                    (text, hrefs) = result
                    links = _links(target, hrefs, list_url)
                    method = 'browser'
        except RuntimeError as error:
            if str(error).endswith('budget_exhausted'):
                if first:
                    entry['outcome'] = 'budget'
                raise BudgetExhausted(str(error) + '_publish_collected_results') from error
            entry['outcome'] = reason(error)
            if entry['outcome'] == 'denied':
                reader.blocked_hosts.add(urlsplit(target).hostname)
            raise
        except (ValueError, OSError) as error:
            entry['outcome'] = reason(error)
            raise
        finally:
            state['requests'] += reader.count
            state['robots'] = reader.robots_cache
            state['blocked_hosts'] = sorted(reader.blocked_hosts)
            state['last_request'] = time.time() - max(0, time.monotonic() - reader.last_request)
            _save(state)
        output = text if full else excerpt(text)
        return {'no': no, 'url': target, 'method': method,
                'checked_at': dt.datetime.now(JST).isoformat(timespec='seconds'),
                'detail_links': links, 'truncated': output != text, 'text': output,
                'text_mode': 'full' if full else 'excerpt', 'full_text_chars': len(text),
                'shop': {'name': row['店名'], 'area_no': int(row['エリア番号']), 'source_site': row['予約サイト'],
                         'list_url': list_url, 'source_url': target, 'station': None, 'address': None, 'plans': []}}


def _browse(state, entry, url, list_url, renderer):
    """Headless browser fallback. Unavailable browser means GET-only, not failure."""
    from . import browser
    if state['browser_unavailable'] and renderer is None:
        return None
    deadline = time.monotonic() + max(0, RESEARCH_SECONDS - (time.time() - state['started_at']))
    guard = None
    try:
        (text, hrefs, guard) = (renderer or browser.render)(url, list_url, deadline=deadline)
    except browser.BrowserUnavailable as error:
        state['browser_unavailable'] = str(error)
        return None
    except (ForbiddenOperation, RuntimeError) as error:
        guard = getattr(error, 'guard', None)
        state['browser_runs'] += 1
        entry['browser'] = True
        raise
    finally:
        if guard is not None:
            state['blocked_operations'] += guard.blocked_operations
            state['blocked_resources'] += guard.blocked_resources
    state['browser_runs'] += 1
    entry['browser'] = True
    return (text, hrefs)


def report(state=None, research=None, rows=None):
    """Counts for the weekly PR body. No shop names of abandoned rows."""
    from collections import Counter
    from afternoon_tea.processing.themes import display
    state = state or _load()
    research = research or json.loads((ROOT / 'site/research.json').read_text())
    rows = rows or candidates()
    start = dt.datetime.fromisoformat(state['started_iso'])
    fresh = lambda plan: dt.datetime.fromisoformat(plan['checked_at']) >= start
    shops = research.get('shops', [])
    week = [s for s in shops if any(fresh(p) for p in s.get('plans', []))]
    confirmed = {s['list_url'] for s in week}
    attempted = {int(n): e for (n, e) in state['rows'].items() if e['outcome'] != 'budget'}
    sites = {name: Counter() for name in ('一休.com', '食べログ', 'TableCheck')}
    abandoned = Counter()
    for (no, entry) in attempted.items():
        ok = rows[no - 1]['予約ページURL'] in confirmed
        sites.setdefault(entry['site'], Counter())['成功' if ok else '失敗'] += 1
        if not ok:
            abandoned[entry['outcome']] += 1
    areas = Counter(s['area_no'] for s in shops)
    master = json.loads((ROOT / 'data/store_master.json').read_text())
    labels = {'cafe': 'カフェ', 'hotel': 'ホテル', 'lux': 'ホテル（高級）', 'unknown': '未確認'}
    countries = Counter(display(p, s) or '未確認' for s in shops for p in s.get('plans', []))
    plans = [p for s in shops for p in s.get('plans', [])]
    lines = ['## 今週の調査結果', '',
             '- 対象期間: %s〜%s' % (research['period']['start'], research['period']['end']),
             '- 調べた行数: %d / %d（No.1から順に）' % (len(attempted), len(rows)),
             '- 時間・要求数の上限などで調べられなかった行数: %d' % (len(rows) - len(attempted)),
             '- 今週確認できた店舗数・プラン数: %d店舗・%dプラン' % (len(week), sum(fresh(p) for p in plans)),
             '- 前回から引き継いだプラン数（14日以内・確認日時そのまま）: %d' % sum(not fresh(p) for p in plans),
             '- 掲載: %d店舗・%dプラン' % (len(shops), len(plans)),
             '- 諦めた行数: %d（理由別: %s）' % (sum(abandoned.values()), '、'.join(
                 '%s %d' % (REASONS.get(k, k), v) for (k, v) in sorted(abandoned.items())) or 'なし'),
             '- 予約サイト別: ' + '、'.join('%s 成功%d・失敗%d' % (k, v['成功'], v['失敗']) for (k, v) in sites.items()),
             '- ブラウザを使った件数: %d%s' % (state['browser_runs'], '（ブラウザ利用不可: GETのみで継続）' if state['browser_unavailable'] else ''),
             '- 止めた禁止操作: %d（遷移・ポップアップ・クリック）、止めた補助通信: %d' % (state['blocked_operations'], state['blocked_resources']),
             '- エリア別掲載店舗数: ' + '、'.join('%s %d' % (a['name'], areas[a['no']]) for a in master['areas']),
             '- 料金区分別: ' + '、'.join('%s %d' % (labels.get(k, k), v) for (k, v) in sorted(Counter(s.get('category', 'unknown') for s in shops).items())),
             '- テーマ国別（プラン数）: ' + ('、'.join('%s %d' % (k, v) for (k, v) in sorted(countries.items())) or 'なし'),
             '']
    return '\n'.join(lines)


def main(args):
    try:
        if args.operation == 'begin':
            print(json.dumps(begin(), ensure_ascii=False))
            return 0
        if args.operation == 'report':
            print(report())
            return 0
        result = fetch(args.no, args.url, args.browser, full=args.full)
    except BudgetExhausted as error:
        print(json.dumps({'no': getattr(args, 'no', None), 'stop_research': True, 'error': str(error)}))
        return 3
    except (ForbiddenOperation, RuntimeError, ValueError, OSError) as error:
        if str(error) == 'run_begin_first' or 'in_order' in str(error):
            print(json.dumps({'no': args.no, 'error': str(error)}))
            return 2
        print(json.dumps({'no': args.no, 'abandon_shop': True, 'reason': reason(error), 'error': str(error)},
                         ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0
