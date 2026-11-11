"""Candidate CSV, anonymous GET, URL safety, robots, budgets and weekly state."""
import datetime as dt
import json
import re
import time
import os
import tempfile
import csv
import shutil
from pathlib import Path
from urllib.parse import urlsplit
from urllib.parse import unquote
from urllib.parse import urljoin
from urllib.request import Request
from urllib.request import HTTPRedirectHandler
from urllib.request import build_opener
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.robotparser import RobotFileParser
from contextlib import contextmanager
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
JST = dt.timezone(dt.timedelta(hours=9))

def require(condition, message):
    if not condition:
        raise ValueError(message)

def load_json(path):

    def pairs(items):
        result = {}
        for (key, value) in items:
            require(key not in result, 'JSONキーの重複: ' + key)
            result[key] = value
        return result

    def constant(value):
        raise ValueError('JSONに非有限数: ' + value)
    try:
        with open(path, encoding='utf-8') as stream:
            return json.load(stream, object_pairs_hook=pairs, parse_constant=constant)
    except json.JSONDecodeError as exc:
        raise ValueError('JSON構文エラー: ' + str(exc)) from exc

def dumps(data):
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n'


HOSTS = ('restaurant.ikyu.com', 'tabelog.com', 'www.tablecheck.com')
# Reservation, payment, cart, login and session words in a path are never sent.
# The exact TableCheck list URL (ending in /reserve or /reserve/landing) is the
# only exception, and only when it is the URL written in the candidate list.
TRANSACTION = re.compile(
    r'checkout|payment|pay/|purchase|confirm|cancel|submit|order|booking|reserv|hold|waitlist|'
    r'login|logout|signin|signup|sign_in|sign_up|register|account|mypage|member|session|cart|'
    r'entry|apply|inquiry|contact|auth')


class ForbiddenOperation(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ForbiddenOperation('redirect_blocked_before_follow')


def check_url(url, method='GET', list_url=None):
    """Generic safety check. `list_url` exempts only that exact candidate URL."""
    if method != 'GET':
        raise ForbiddenOperation('only_GET_allowed')
    if not isinstance(url, str):
        raise ForbiddenOperation('unsafe_URL')
    p = urlsplit(url)
    if (p.scheme != 'https' or p.username or p.password or p.port not in (None, 443) or p.fragment
            or p.query or any(c.isspace() for c in url) or '\\' in url):
        raise ForbiddenOperation('unsafe_URL')
    if p.hostname not in HOSTS:
        raise ForbiddenOperation('host_not_allowed')
    path = unquote(unquote(p.path)).lower()
    if path == '/robots.txt':
        return
    if TRANSACTION.search(path) and url != list_url:
        raise ForbiddenOperation('transaction_or_session_URL')


def shop_key(url):
    """Return (host, shop id) for a list or plan detail URL, else None."""
    p = urlsplit(url)
    path = p.path
    patterns = {
        'restaurant.ikyu.com': r'/(\d+)/(?:plan\d+/?)?',
        'tabelog.com': r'/tokyo/A\d+/A\d+/(\d+)/party/(?:\d+/)?',
        'www.tablecheck.com': r'/ja/(?:shops/)?([a-z0-9_-]+)/reserve(?:/landing)?',
    }
    pattern = patterns.get(p.hostname)
    match = pattern and re.fullmatch(pattern, path)
    return (p.hostname, match.group(1)) if match else None


def check_scope(url, list_url, method='GET'):
    """The candidate's own list URL, or a plan detail page of the same shop."""
    check_url(url, method, list_url)
    if url == list_url:
        return
    key = shop_key(url)
    if key is None or key != shop_key(list_url):
        raise ForbiddenOperation('outside_shop_scope')
    # TableCheck pages past the list URL are reservation steps.
    if key[0] == 'www.tablecheck.com':
        raise ForbiddenOperation('outside_shop_scope')


class ReadOnlyTransport:

    def __init__(self):
        self.blocked_requests = 0
        self.opener = build_opener(NoRedirect())

    def open(self, url, timeout=15, headers=None, method='GET', list_url=None):
        try:
            if list_url is None:
                check_url(url, method)
            else:
                check_scope(url, list_url, method)
            if headers and any(k.lower() not in ('user-agent', 'accept-language', 'accept') for k in headers):
                raise ForbiddenOperation('credentials_forbidden')
        except (ValueError, ForbiddenOperation):
            self.blocked_requests += 1
            raise
        return self.opener.open(Request(url, headers=headers or {}, method='GET'), timeout=timeout)

USER_AGENT = 'TokyoAfternoonTeaResearch/0.2 (+public research; no login; contact via GitHub issue)'
MAX_BYTES = 800000
RESEARCH_SECONDS = 1500
MAX_REQUESTS = 200
SHOP_SECONDS = 60
INTERVAL = 3.0
CHALLENGE = ('captcha', 'verify you are human', 'access denied', 'アクセスが制限')


class Reader:
    """Every request waits INTERVAL seconds (or the robots crawl-delay)."""

    def __init__(self, delay=INTERVAL, timeout=15.0, max_requests=MAX_REQUESTS, seconds=RESEARCH_SECONDS):
        self.deadline = time.monotonic() + seconds
        self.delay = delay
        self.timeout = timeout
        self.max_requests = max_requests
        self.count = 0
        self.last_request = 0.0
        self.robots = {}
        self.robots_cache = {}
        self.blocked_hosts = set()
        self.transport = ReadOnlyTransport()

    def _wait(self, host):
        robots = self.robots.get(host)
        delay = max(self.delay, (robots.crawl_delay(USER_AGENT) or robots.crawl_delay('*') or 0) if robots else 0)
        wait = max(0, delay - (time.monotonic() - self.last_request))
        if self.count >= self.max_requests:
            raise RuntimeError('request_budget_exhausted')
        if time.monotonic() + wait >= self.deadline:
            raise RuntimeError('research_budget_exhausted')
        if wait:
            time.sleep(wait)
        self.last_request = time.monotonic()
        self.count += 1

    def _get(self, url, list_url, limit):
        headers = {'User-Agent': USER_AGENT, 'Accept-Language': 'ja,en;q=0.8'}
        timeout = min(self.timeout, max(0.01, self.deadline - time.monotonic()))
        with self.transport.open(url, timeout=timeout, headers=headers, list_url=list_url) as response:
            if response.geturl() != url:
                raise ForbiddenOperation('redirect_blocked_before_follow')
            raw = response.read(limit + 1)
            if len(raw) > limit:
                raise RuntimeError('page_too_large')
            return response, raw

    def robots_allows(self, url, list_url):
        host = urlsplit(url).hostname
        if host not in self.robots:
            if host not in self.robots_cache:
                robots_url = 'https://' + host + '/robots.txt'
                try:
                    self._wait(host)
                    (_, body) = self._get(robots_url, None, 200000)
                    # Only rules are cached, not comments, sitemaps or page bodies.
                    directives = {'user-agent', 'allow', 'disallow', 'crawl-delay', 'request-rate'}
                    lines = []
                    for raw_line in body.decode('utf-8', errors='replace').splitlines():
                        # A comment is ignored by RobotFileParser; it is not a group boundary.
                        if raw_line.lstrip().startswith('#'):
                            continue
                        line = raw_line.split('#', 1)[0].strip()
                        if not line or line.partition(':')[0].strip().lower() in directives:
                            lines.append(line)
                    self.robots_cache[host] = lines
                except (HTTPError, URLError, OSError, ForbiddenOperation, RuntimeError) as error:
                    if isinstance(error, RuntimeError) and str(error).endswith('budget_exhausted'):
                        raise
                    # A refusal/unknown result is cached too: no retry this week.
                    self.robots_cache[host] = None
                    if isinstance(error, HTTPError) and error.code in (403, 429):
                        self.blocked_hosts.add(host)
            lines = self.robots_cache[host]
            parser = RobotFileParser()
            if lines is not None:
                parser.parse(lines)
            self.robots[host] = parser if lines is not None else None
        robots = self.robots[host]
        return robots is not None and robots.can_fetch(USER_AGENT, url)

    def fetch(self, url, list_url):
        """Return decoded HTML of `url`, which must be inside `list_url`'s shop scope."""
        check_scope(url, list_url)
        host = urlsplit(url).hostname
        if host in self.blocked_hosts:
            raise RuntimeError('host_stopped_this_week')
        if not self.robots_allows(url, list_url):
            raise RuntimeError('robots_disallowed_or_unknown')
        self._wait(host)
        try:
            (response, raw) = self._get(url, list_url, MAX_BYTES)
        except HTTPError as error:
            if error.code in (403, 429):
                self.blocked_hosts.add(host)
            raise RuntimeError('HTTP_' + str(error.code)) from error
        if 'text/html' not in response.headers.get('Content-Type', '').lower():
            raise RuntimeError('not_html')
        text = raw.decode(response.headers.get_content_charset() or 'utf-8', errors='replace')
        if any(marker in text.lower() for marker in CHALLENGE):
            self.blocked_hosts.add(host)
            raise RuntimeError('access_challenge')
        return text


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    (fd, tmp) = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(dumps(value))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

@contextmanager
def store_lock(directory):
    """Prevent overlapping local writers; kernel releases the lock on process exit."""
    import fcntl
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.lock').open('a') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('another_research_process_holds_store_lock')
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


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
    'unusable': 'HTML以外・サイズ超過など',
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
    atomic_json(STATE / 'state.json', state)


def begin(now=None):
    """Start the week: copy the previous site data, start an empty research file."""
    from afternoon_tea.build import period
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
                         'list_url': list_url, 'station': None, 'address': None, 'plans': []}}


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
    from afternoon_tea.build import display
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
    master = load_json(ROOT / 'data/areas.json')
    labels = {'cafe': 'カフェ', 'hotel': 'ホテル', 'lux': 'ホテル（高級）', 'unknown': '未確認'}
    countries = Counter(display(p) or '未確認' for s in shops for p in s.get('plans', []))
    plans = [p for s in shops for p in s.get('plans', [])]
    lines = ['## 今週の調査結果', '',
             '- 対象期間: %s〜%s' % (research['period']['start'], research['period']['end']),
             '- 調べた行数: %d / %d（No.1から順に）' % (len(attempted), len(rows)),
             '- 時間・要求数の上限などで調べられなかった行数: %d' % (len(rows) - len(attempted)),
             '- 今週確認できた店舗数・プラン数: %d店舗・%dプラン' % (len(week), sum(fresh(p) for p in plans)),
             '- 前回から引き継いだプラン数（14日以内・確認日時そのまま）: %d' % sum(not fresh(p) for p in plans),
             '- 掲載: %d店舗・%dプラン' % (len(shops), len(plans)),
             '- 秘密情報・個人情報の検査で除外したプラン数: %d' % sum(research.get('excluded_sensitive_plans', {}).values()),
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
