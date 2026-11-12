"""Read-only access to public pages: URL checks before sending, robots.txt, pacing and run state.

Both the plain reader (`read`) and the browser use `Reader.get` for every page they open, so
the same checks apply: https only, no credentials, no reservation/transaction/session URLs,
no reservation slot parameters, robots.txt, 403/429/CAPTCHA stop the host for this run, and
each redirect hop is checked before it is requested.
"""
import datetime as dt
import ipaddress
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

from afternoon_tea.config import ROOT, settings

JST = dt.timezone(dt.timedelta(hours=9))
RUN = ROOT / '.staging/run'
USER_AGENT = 'TokyoAfternoonTeaResearch/0.3 (+public research; no login; no reservation)'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
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


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(dumps(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextmanager
def store_lock(directory, wait=30.0):
    """Serialize writers of the run state; the kernel releases the lock if a process dies."""
    import fcntl
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.lock').open('a') as lock:
        end = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > end:
                    raise RuntimeError('another_research_process_holds_store_lock')
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class ForbiddenOperation(RuntimeError):
    """A request or browser operation that is not information gathering. Never sent."""


class BudgetExhausted(RuntimeError):
    """The configurable run limit was reached: save results and the resume position."""


class AccessRefused(RuntimeError):
    """robots.txt, 403/429, CAPTCHA or an access challenge. Not retried in this run."""


class Unusable(RuntimeError):
    """Network error, non-HTML, oversized page: this page only."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Words in a URL path that mean a reservation, transaction, login or session step.
TRANSACTION_TOKENS = {
    'reserve', 'reserves', 'reservation', 'reservations', 'booking', 'bookings', 'book', 'yoyaku',
    'checkout', 'payment', 'payments', 'pay', 'purchase', 'order', 'orders', 'cart', 'basket',
    'login', 'logout', 'signin', 'signout', 'signup', 'register', 'registration', 'account', 'accounts',
    'mypage', 'member', 'members', 'inquiry', 'inquiries', 'contact', 'otoiawase', 'apply', 'application',
    'entry', 'waitlist', 'waiting', 'cancel', 'confirm', 'confirmation', 'auth', 'oauth', 'session',
    'sessions', 'password', 'wallet', 'gift', 'voucher'}
TRANSACTION_JA = re.compile(r'予約|申込|申し込|問い?合わ?せ|購入|決済|注文|ログイン|会員登録')
# Query parameters that select a reservation slot (date, time, party size) or carry a session.
SLOT_PARAMS = re.compile(
    r'^(?:date|dates|day|days|time|times|visit_?date|visit_?time|start_?date|start_?time|start_?at|'
    r'rsv_?date|rsv_?time|pdate|ptime|people|person|persons|party|party_?size|pax|pups|num_?people|'
    r'covers|adults?|child(?:ren)?|kids|guests?|seats?|seat_?type|ninzu|token|session|session_?id|sid|'
    r'auth|password|booking_?id|reservation_?id|cart|coupon_?code)$', re.I)
# TableCheck shop pages that list plans (no date, time or party size chosen yet).
TABLECHECK_SHOP = re.compile(r'^(?:/[a-z]{2}(?:-[A-Za-z]+)?)?/(?:shops/)?[a-z0-9_-]+/reserve(?:/landing|/experiences)?/?$')
CHALLENGE = ('captcha', 'verify you are human', 'are you a robot', 'ロボットではありません', 'just a moment...',
             'アクセスが制限', 'アクセスしようとしたページは表示できませんでした', 'access denied', 'checking your browser',
             'unusual traffic')


class Policy:
    """Which URLs may be requested. Test hosts (local pages) are only set by the test suite."""

    def __init__(self, test_hosts=()):
        self.test_hosts = set(test_hosts)

    def check(self, url, method='GET', robots_path=False):
        if method != 'GET':
            raise ForbiddenOperation('only_GET_navigation')
        if not isinstance(url, str) or len(url) > 2000 or any(c.isspace() for c in url) or '\\' in url:
            raise ForbiddenOperation('unsafe_URL')
        p = urlsplit(url)
        host = (p.hostname or '').lower()
        netloc = host + (':%d' % p.port if p.port else '')
        test = netloc in self.test_hosts
        if p.scheme != ('http' if test and p.scheme == 'http' else 'https') or p.username or p.password:
            raise ForbiddenOperation('unsafe_URL')
        if not test:
            if p.port not in (None, 443) or not host or '.' not in host or host.endswith(('.local', '.internal', '.localhost')):
                raise ForbiddenOperation('unsafe_URL')
            try:
                ipaddress.ip_address(host)
                raise ForbiddenOperation('ip_address_host')
            except ValueError:
                pass
        if robots_path:
            return
        path = unquote(unquote(p.path))
        tokens = set(re.findall(r'[a-z0-9]+', path.lower()))
        if host == 'www.tablecheck.com' and TABLECHECK_SHOP.match(p.path) and not p.query:
            tokens -= {'reserve'}  # The TableCheck shop page that lists plans; selections are not allowed.
        if tokens & TRANSACTION_TOKENS or TRANSACTION_JA.search(path):
            raise ForbiddenOperation('transaction_or_session_URL')
        for key, value in parse_qsl(p.query, keep_blank_values=True):
            if SLOT_PARAMS.match(key) or (TRANSACTION_JA.search(key)):
                raise ForbiddenOperation('reservation_or_session_parameter')
        return p


def visible_text(html):
    parser = _Text()
    parser.feed(html)
    return '\n'.join(parser.parts), parser.links, parser.title


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.links, self.hidden, self.title, self._in_title = [], [], 0, '', False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript', 'template'):
            self.hidden += 1
        if tag == 'title':
            self._in_title = True
        if tag == 'a':
            self.links.append(dict(attrs).get('href') or '')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'template') and self.hidden:
            self.hidden -= 1
        if tag == 'title':
            self._in_title = False

    def handle_data(self, text):
        if self._in_title:
            self.title += text.strip()
        elif not self.hidden and text.strip():
            self.parts.append(text.strip())


def challenged(text):
    lowered = text[:6000].lower()
    return any(marker in lowered for marker in CHALLENGE)


def now_iso():
    return dt.datetime.now(JST).isoformat(timespec='seconds')


class RunState:
    """Per-run state in .staging/run (not tracked). Progress that must survive is in site/research.json."""

    def __init__(self, directory=None):
        self.directory = Path(directory or RUN)
        self.path = self.directory / 'state.json'

    def start(self, limits):
        state = {'started_at': time.time(), 'started_iso': now_iso(), 'limits': limits, 'navigations': 0,
                 'blocked_hosts': {}, 'robots': {}, 'last_request': {}, 'visits': [], 'task': None,
                 'blocked_operations': 0, 'blocked_resources': 0, 'browser_pages': 0, 'browser_unavailable': None}
        with store_lock(self.directory):
            atomic_json(self.path, state)
        return state

    def load(self):
        if not self.path.exists():
            raise RuntimeError('run_begin_first')
        return json.loads(self.path.read_text(encoding='utf-8'))

    @contextmanager
    def update(self):
        with store_lock(self.directory):
            state = self.load()
            try:
                yield state
            finally:
                atomic_json(self.path, state)


class Page:
    def __init__(self, url, final_url, status, headers, body, chain):
        self.url, self.final_url, self.status, self.headers, self.body, self.chain = url, final_url, status, headers, body, chain

    @property
    def content_type(self):
        return (self.headers.get('Content-Type') or '').lower()

    def text(self):
        charset = re.search(r'charset=([\w-]+)', self.content_type)
        try:
            return self.body.decode(charset.group(1) if charset else 'utf-8', errors='replace')
        except LookupError:
            return self.body.decode('utf-8', errors='replace')


class Reader:
    """Anonymous GET of documents. No cookies, no credentials, no automatic redirects."""

    def __init__(self, run=None, policy=None, opener=None, limits=None, sleep=time.sleep, clock=time.time):
        self.run = run or RunState()
        self.policy = policy or Policy()
        self.opener = opener or build_opener(NoRedirect())
        self.limits = limits
        self.sleep, self.clock = sleep, clock

    def _limits(self, state):
        return self.limits or state.get('limits') or settings()

    def _budget(self, state):
        limits = self._limits(state)
        if self.clock() - state['started_at'] >= limits['total_seconds']:
            raise BudgetExhausted('research_time_limit_save_and_publish_collected_results')
        if state['navigations'] >= limits['max_navigations']:
            raise BudgetExhausted('navigation_limit_save_and_publish_collected_results')
        task = state.get('task')
        if task and self.clock() - task['started_at'] > limits['shop_seconds']:
            raise BudgetExhausted('shop_time_limit_record_this_shop_and_continue')

    def _send(self, state, url, robots=None):
        """One paced request. 403/429 stop the host for this run."""
        host = urlsplit(url).netloc.lower()
        limits = self._limits(state)
        delay = float(limits['min_interval_seconds'])
        if robots is not None:
            delay = max(delay, float(robots.crawl_delay(USER_AGENT) or robots.crawl_delay('*') or 0))
        wait = delay - (self.clock() - state['last_request'].get(host, 0))
        if wait > 0:
            self.sleep(wait)
        state['last_request'][host] = self.clock()
        state['navigations'] += 1
        request = Request(url, headers={'User-Agent': USER_AGENT, 'Accept-Language': 'ja,en;q=0.8',
                                        'Accept': 'text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5'})
        try:
            response = self.opener.open(request, timeout=limits['page_timeout_seconds'])
            status, headers = response.status, response.headers
        except HTTPError as error:
            response, status, headers = error, error.code, error.headers
        except (URLError, OSError, ValueError) as error:
            raise Unusable('network_error:' + type(error).__name__) from error
        try:
            body = response.read(int(limits['max_page_bytes']) + 1) if response is not None and hasattr(response, 'read') else b''
        except OSError as error:
            raise Unusable('network_error:' + type(error).__name__) from error
        finally:
            if hasattr(response, 'close'):
                response.close()
        if status in (401, 403, 429):
            state['blocked_hosts'][host] = 'HTTP_%d' % status
            raise AccessRefused('HTTP_%d_host_stopped_for_this_run' % status)
        if len(body) > limits['max_page_bytes']:
            raise Unusable('page_too_large')
        return status, headers, body

    def _robots(self, state, url):
        """RFC 9309: 2xx rules, 4xx none (except 401/403/429 = refused), 5xx/unreachable = not now."""
        p = urlsplit(url)
        host = p.netloc.lower()
        entry = state['robots'].get(host)
        if entry is None:
            robots_url = '%s://%s/robots.txt' % (p.scheme, p.netloc)
            entry = {'status': 'unknown', 'lines': None}
            try:
                target = robots_url
                for _ in range(5):
                    self.policy.check(target, robots_path=True)
                    status, headers, body = self._send(state, target)
                    if status in (301, 302, 303, 307, 308) and headers.get('Location'):
                        target = urljoin(target, headers['Location'])
                        continue
                    break
                if 200 <= status < 300:
                    lines = []
                    for raw in body.decode('utf-8', errors='replace').splitlines():
                        line = raw.split('#', 1)[0].strip()
                        if raw.lstrip().startswith('#'):
                            continue
                        if not line or line.partition(':')[0].strip().lower() in (
                                'user-agent', 'allow', 'disallow', 'crawl-delay', 'request-rate'):
                            lines.append(line)
                    entry = {'status': 'rules', 'lines': lines}
                elif 400 <= status < 500:
                    entry = {'status': 'none', 'lines': None}
            except AccessRefused:
                entry = {'status': 'refused', 'lines': None}
            except (Unusable, ForbiddenOperation):
                entry = {'status': 'unknown', 'lines': None}
            state['robots'][host] = entry
        if entry['status'] == 'refused':
            raise AccessRefused('robots_txt_refused_host_stopped_for_this_run')
        if entry['status'] == 'unknown':
            # Not permission, not a permanent exclusion: try another public source now, this host next run.
            raise AccessRefused('robots_txt_unavailable_try_other_public_source')
        parser = RobotFileParser()
        parser.parse(entry['lines'] or [])
        if entry['status'] == 'rules' and not parser.can_fetch(USER_AGENT, url):
            raise AccessRefused('robots_txt_disallows_this_page')
        return parser

    def get(self, url, via='get', follow=True):
        """Return a Page for an HTML document. Each redirect hop is checked before it is sent."""
        chain = []
        target = url
        with self.run.update() as state:
            limits = self._limits(state)
            for _ in range(int(limits['max_redirects']) + 1):
                self.policy.check(target)
                host = urlsplit(target).netloc.lower()
                if host in state['blocked_hosts']:
                    raise AccessRefused('host_stopped_for_this_run:' + state['blocked_hosts'][host])
                self._budget(state)
                robots = self._robots(state, target)
                self._budget(state)
                status, headers, body = self._send(state, target, robots)
                chain.append({'url': target, 'status': status})
                if status in (301, 302, 303, 307, 308):
                    location = headers.get('Location')
                    if not location:
                        raise Unusable('redirect_without_location')
                    nxt = urljoin(target, location)
                    try:
                        self.policy.check(nxt)
                    except ForbiddenOperation:
                        state['blocked_operations'] += 1
                        raise
                    if not follow:
                        return Page(url, nxt, status, headers, body, chain)
                    target = nxt
                    continue
                if status >= 400:
                    raise Unusable('HTTP_%d' % status)
                page = Page(url, target, status, headers, body, chain)
                if not any(t in page.content_type for t in ('text/html', 'application/xhtml', 'text/plain')):
                    raise Unusable('not_html:' + page.content_type.split(';')[0])
                text = page.text()
                if challenged(visible_text(text)[0] + ' ' + visible_text(text)[2]):
                    state['blocked_hosts'][host] = 'access_challenge'
                    raise AccessRefused('access_challenge_host_stopped_for_this_run')
                state['visits'].append({'url': url, 'final_url': target, 'at': now_iso(), 'via': via})
                return page
            raise Unusable('too_many_redirects')


def excerpt(text, chars=800, limit=12000):
    """Context windows around afternoon-tea words; the full text is available with --full."""
    windows = []
    for match in AT_WORDS.finditer(text):
        start, end = max(0, match.start() - chars), min(len(text), match.end() + chars)
        if windows and start <= windows[-1][1]:
            windows[-1] = (windows[-1][0], end)
        else:
            windows.append((start, end))
        if sum(e - s for s, e in windows) >= limit:
            break
    return '\n…\n'.join(text[s:e] for s, e in windows)[:limit]


AT_WORDS = re.compile(r'アフタヌーン\s*ティー|afternoon\s*tea|ハイティー|high\s*tea|ヌン活', re.I)


def read(url, full=False, run=None, policy=None):
    """Plain GET reading (no JavaScript). Use the browser when the plans are drawn by scripts."""
    run = run or RunState()
    page = Reader(run, policy).get(url, via='get')
    text, hrefs, title = visible_text(page.text())
    limits = run.load()['limits']
    links = []
    for href in hrefs:
        target = urljoin(page.final_url, href or '').split('#')[0]
        if target.startswith(('https://', 'http://')) and target not in links:
            links.append(target)
    output = text if full else excerpt(text, limits['excerpt_chars'], limits['max_excerpt_chars'])
    return {'url': url, 'final_url': page.final_url, 'title': title, 'method': 'get', 'read_at': now_iso(),
            'at_words_found': bool(AT_WORDS.search(text)), 'text_mode': 'full' if full else 'excerpt',
            'full_text_chars': len(text), 'text': output, 'links': links[:300]}
