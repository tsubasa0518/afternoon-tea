"""No live requests: URL checks and the GET reader use mocked openers only."""
import unittest
import collections
import copy
import datetime as dt
import json
import re
import shutil
import sys
import tempfile
import afternoon_tea.browser as browser
import afternoon_tea.fetch as collect
import afternoon_tea.fetch as reader_module
from unittest.mock import Mock
from unittest.mock import patch
from urllib.error import HTTPError
from afternoon_tea.fetch import Reader
from afternoon_tea.fetch import ReadOnlyTransport
from afternoon_tea.fetch import ForbiddenOperation
from afternoon_tea.fetch import check_url
from afternoon_tea.fetch import check_scope
from afternoon_tea.fetch import NoRedirect
from afternoon_tea.fetch import shop_key
from afternoon_tea.fetch import candidates
from afternoon_tea.fetch import ROOT
from tests.http_fixtures import Response
from pathlib import Path
from afternoon_tea.build import retain
from afternoon_tea.build import validate_freshness
from afternoon_tea.build import build
from afternoon_tea.render import render
from afternoon_tea.check import validate_site
from afternoon_tea.check import json_bytes
from afternoon_tea.check import intake
from tests.test_render import fixture
from tests.test_check import FakeAPI
from urllib.parse import urlsplit
from afternoon_tea.__main__ import parser
from afternoon_tea.browser import Guard


IKYU = 'https://restaurant.ikyu.com/112520/'
TABELOG = 'https://tabelog.com/tokyo/A1302/A130202/13226051/party/'
LANDING = 'https://www.tablecheck.com/ja/cafe-jardin-de-rose/reserve/landing'
RESERVE = 'https://www.tablecheck.com/ja/shops/zikkai/reserve'


class SafetyTests(unittest.TestCase):

    def setUp(self):
        self.transport = ReadOnlyTransport()
        self.transport.opener = Mock()

    def test_methods_never_reach_network(self):
        for method in ('POST', 'PUT', 'PATCH', 'DELETE', 'HEAD'):
            with self.assertRaises(ForbiddenOperation):
                self.transport.open(IKYU, method=method)
        self.transport.opener.open.assert_not_called()
        self.assertEqual(self.transport.blocked_requests, 5)

    def test_transaction_links_never_followed(self):
        for url in ('https://restaurant.ikyu.com/112520/confirm/',
                    'https://tabelog.com/booking/hold',
                    'https://www.tablecheck.com/checkout',
                    'https://www.tablecheck.com/ja/shops/vava/reserve?date=20261109',
                    'https://www.tablecheck.com/ja/shops/vava/reserve',
                    'https://tabelog.com/payment',
                    'https://restaurant.ikyu.com/112520/cart/',
                    'https://restaurant.ikyu.com/login/',
                    'https://restaurant.ikyu.com/%2563onfirm/'):
            with self.assertRaises(ForbiddenOperation):
                self.transport.open(url)
        self.transport.opener.open.assert_not_called()

    def test_no_form_body_or_credentials(self):
        with self.assertRaises(TypeError):
            self.transport.open(IKYU, data=b'person=test')
        for h in ({'Cookie': 'logged-in'}, {'Authorization': 'token'}):
            with self.assertRaises(ForbiddenOperation):
                self.transport.open(IKYU, headers=h)
        self.transport.opener.open.assert_not_called()

    def test_redirect_blocked_before_follow(self):
        with self.assertRaises(ForbiddenOperation):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com/payment')

    def test_every_list_url_and_same_shop_details_are_in_scope(self):
        for row in candidates():
            check_scope(row['予約ページURL'], row['予約ページURL'])
        check_scope('https://restaurant.ikyu.com/112520/plan12815175/', IKYU)
        check_scope('https://tabelog.com/tokyo/A1302/A130202/13226051/party/232732756/', TABELOG)
        self.assertEqual(shop_key('https://restaurant.ikyu.com/112520/plan1'), shop_key(IKYU))

    def test_other_shop_other_site_and_search_are_outside_scope(self):
        for url in ('https://restaurant.ikyu.com/999999/', 'https://restaurant.ikyu.com/999999/plan1/',
                    'https://tabelog.com/tokyo/A1302/A130202/13226051/', 'https://tabelog.com/tokyo/A1302/A130202/1/party/',
                    'https://www.bing.com/search?q=tea', 'https://restaurant.ikyu.com/area/tokyo/',
                    'https://restaurant.ikyu.com/s-tokyo/', TABELOG):
            with self.assertRaises(ForbiddenOperation):
                check_scope(url, IKYU)

    def test_tablecheck_list_url_itself_only(self):
        check_scope(LANDING, LANDING)
        check_scope(RESERVE, RESERVE)
        for url in (LANDING + '/2', 'https://www.tablecheck.com/ja/cafe-jardin-de-rose/reserve',
                    'https://www.tablecheck.com/ja/cafe-jardin-de-rose/reserve/landing?menu=1',
                    'https://www.tablecheck.com/ja/shops/zikkai/reserve/confirm', RESERVE):
            with self.assertRaises(ForbiddenOperation):
                check_scope(url, LANDING)
        with self.assertRaises(ForbiddenOperation):
            check_url(LANDING)

    def test_private_unknown_hosts_blocked(self):
        for u in ('http://127.0.0.1/', 'https://evil.example/', 'https://user:pass@restaurant.ikyu.com/112520/',
                  'https://ssl.tabelog.com/tokyo/', 'https://tablecheck.com/ja/x/', 'https://www.example.com/robots.txt'):
            with self.assertRaises(ForbiddenOperation):
                check_url(u)


class ReaderTests(unittest.TestCase):

    def reader(self, pages, robots='User-agent: *\nAllow: /\n'):
        reader = Reader(delay=0)
        seen = []

        def open_(request, timeout=0):
            url = request.full_url
            seen.append(url)
            if url.endswith('/robots.txt'):
                return Response(url, robots, 'text/plain')
            value = pages[url]
            if isinstance(value, Exception):
                raise value
            return Response(url, value)
        reader.transport.opener = Mock()
        reader.transport.opener.open.side_effect = open_
        return reader, seen

    def test_robots_first_then_page(self):
        reader, seen = self.reader({IKYU: '<p>アフタヌーンティー</p>'})
        self.assertIn('アフタヌーンティー', reader.fetch(IKYU, IKYU))
        self.assertEqual(seen, ['https://restaurant.ikyu.com/robots.txt', IKYU])
        self.assertEqual(reader.count, 2)

    def test_robots_disallow_abandons_without_fetching_page(self):
        reader, seen = self.reader({IKYU: 'x'}, robots='User-agent: *\nDisallow: /\n')
        with self.assertRaisesRegex(RuntimeError, 'robots'):
            reader.fetch(IKYU, IKYU)
        self.assertEqual(seen, ['https://restaurant.ikyu.com/robots.txt'])

    def test_denial_and_captcha_stop_host_without_retry(self):
        for value in (HTTPError(IKYU, 403, 'denied', {}, None), HTTPError(IKYU, 429, 'slow', {}, None),
                      '<p>Please complete the CAPTCHA</p>'):
            reader, seen = self.reader({IKYU: value})
            with self.assertRaises(RuntimeError):
                reader.fetch(IKYU, IKYU)
            with self.assertRaisesRegex(RuntimeError, 'host_stopped'):
                reader.fetch('https://restaurant.ikyu.com/112520/plan1/', IKYU)
            self.assertEqual(len(seen), 2)

    def test_oversized_page_is_still_unusable(self):
        reader, _ = self.reader({IKYU: 'x' * 900000})
        with self.assertRaisesRegex(RuntimeError, 'page_too_large'):
            reader.fetch(IKYU, IKYU)

    def test_request_budget(self):
        reader, seen = self.reader({IKYU: 'x'})
        reader.max_requests = 1
        with self.assertRaisesRegex(RuntimeError, 'budget_exhausted'):
            reader.fetch(IKYU, IKYU)
        self.assertEqual(len(seen), 1)


NOW = dt.datetime(2026, 11, 10, 12, tzinfo=dt.timezone.utc)
AT = '<html><body><h1>アフタヌーンティー</h1><a href="plan111/">plan</a><a href="/999999/">other</a></body></html>'
PLAIN = '<html><body><div id="app"></div></body></html>'
# Expected area counts in the owner-provided ninety-row list.
AREA_COUNTS = {1: 15, 2: 17, 3: 11, 4: 6, 5: 6, 6: 6, 7: 3, 8: 6, 9: 2, 10: 11, 11: 1, 12: 1, 13: 3, 14: 2}


class FakeReader:
    pages = {}
    opened = []

    def __init__(self, max_requests=collect.MAX_REQUESTS, timeout=15, seconds=collect.RESEARCH_SECONDS):
        self.count = 0
        self.blocked_hosts = set()
        self.last_request = 0.0
        self.max_requests = max_requests

    def fetch(self, url, list_url):
        check_scope(url, list_url)
        self.count += 1
        FakeReader.opened.append(url)
        value = FakeReader.pages.get(url, AT)
        if isinstance(value, Exception):
            raise value
        return value


class Week(unittest.TestCase):
    """A temporary repository root, so begin/fetch never touch the real files."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        for name in ('data/references/user_candidates.csv', 'data/areas.json', 'site/research.json'):
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, root / name)
        self.root = root
        self.patches = [patch.object(collect, 'ROOT', root), patch.object(collect, 'STATE', root / '.staging/weekly')]
        for p in self.patches:
            p.start()
        FakeReader.pages = {}
        FakeReader.opened = []
        self.rows = collect.candidates()
        collect.begin()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def url(self, no):
        return self.rows[no - 1]['予約ページURL']

    def fetch(self, no, url=None, **kw):
        kw.setdefault('renderer', lambda *a, **k: (_ for _ in ()).throw(AssertionError('browser not needed')))
        return collect.fetch(no, url, reader_factory=FakeReader, **kw)

    def state(self):
        return json.loads((self.root / '.staging/weekly/state.json').read_text())


class ListOnlyTests(Week):

    def test_only_the_rows_own_url_and_same_shop_details_are_opened(self):
        out = self.fetch(1)
        self.assertEqual(FakeReader.opened, [self.url(1)])
        self.assertEqual(out['detail_links'], [self.url(1) + 'plan111/'])
        self.assertEqual(out['shop']['area_no'], int(self.rows[0]['エリア番号']))
        self.fetch(1, self.url(1) + 'plan111/')
        for other in ('https://restaurant.ikyu.com/999999/', self.url(2), 'https://tabelog.com/tokyo/A1301/A130101/1/party/',
                      'https://www.bing.com/search?q=' + self.rows[0]['店名']):
            with self.assertRaises(ForbiddenOperation):
                self.fetch(1, other)
        self.assertEqual(FakeReader.opened, [self.url(1), self.url(1) + 'plan111/'])
        self.assertFalse(hasattr(collect, 'search') or hasattr(collect, 'SERVICES'))

    def test_rows_start_at_one_in_order_every_week(self):
        with self.assertRaisesRegex(ValueError, 'in_order'):
            self.fetch(2)
        self.fetch(1)
        with self.assertRaisesRegex(ValueError, 'in_order'):
            self.fetch(3)
        self.fetch(2)
        with self.assertRaisesRegex(ValueError, 'in_order'):
            self.fetch(1)
        collect.begin()
        with self.assertRaisesRegex(ValueError, 'next_is_1'):
            self.fetch(2)
        self.assertEqual(self.state()['rows'], {})

    def test_failures_skip_to_next_row_without_saving_names(self):
        errors = [RuntimeError('HTTP_403'), RuntimeError('robots_disallowed_or_unknown'),
                  ValueError('secret_or_personal_contact_detected'), ForbiddenOperation('redirect_blocked_before_follow'),
                  RuntimeError('page_too_large')]
        for (no, error) in enumerate(errors, 1):
            FakeReader.pages[self.url(no)] = error
            with self.assertRaises(type(error)):
                self.fetch(no)
        self.fetch(len(errors) + 1)
        state = self.state()
        self.assertEqual([state['rows'][str(n)]['outcome'] for n in range(1, 6)],
                         ['denied', 'robots', 'unusable', 'forbidden', 'unusable'])
        text = json.dumps(state, ensure_ascii=False)
        for row in self.rows[:6]:
            self.assertNotIn(row['店名'], text)
            self.assertNotIn(row['予約ページURL'], text)

    def test_shop_time_limit_moves_on(self):
        self.fetch(1)
        state = self.state()
        state['rows']['1']['first_at'] -= collect.SHOP_SECONDS + 1
        (self.root / '.staging/weekly/state.json').write_text(json.dumps(state))
        with self.assertRaisesRegex(RuntimeError, 'shop_time_limit'):
            self.fetch(1, self.url(1) + 'plan111/')
        self.fetch(2)

    def test_budget_stop_still_generates_and_passes_publication_check(self):
        self.fetch(1)
        state = self.state()
        state['requests'] = collect.MAX_REQUESTS
        (self.root / '.staging/weekly/state.json').write_text(json.dumps(state))
        with self.assertRaises(collect.BudgetExhausted):
            self.fetch(2)
        state.update(requests=0, started_at=state['started_at'] - collect.RESEARCH_SECONDS)
        (self.root / '.staging/weekly/state.json').write_text(json.dumps(state))
        with self.assertRaises(collect.BudgetExhausted):
            self.fetch(2)
        # Publish what was read: row 1 only.
        data = json.loads((self.root / 'site/research.json').read_text())
        shop = {'name': 'ROW ONE', 'area_no': 2, 'list_url': self.url(1), 'source_url': self.url(1),
                'plans': [{'plan_name': 'AT', 'checked_at': dt.datetime.now(dt.timezone.utc).isoformat()}]}
        data['shops'] = [shop]
        data = retain(data, json.loads((self.root / '.staging/weekly/previous.json').read_text()))
        html = render(data)
        self.assertIn('ROW ONE', html)
        validate_site({'site/research.json': json_bytes(data), 'site/index.html': html.encode()})

    def test_begin_starts_empty_week_and_keeps_previous_copy(self):
        before = (ROOT / 'site/research.json').read_bytes()
        data = json.loads((self.root / 'site/research.json').read_text())
        self.assertEqual(data['shops'], [])
        self.assertEqual(dt.date.fromisoformat(data['period']['end']) - dt.date.fromisoformat(data['period']['start']),
                         dt.timedelta(days=40))
        self.assertEqual((self.root / '.staging/weekly/previous.json').read_bytes(), before)
        self.assertEqual((ROOT / 'site/research.json').read_bytes(), before)


class BrowserFallbackTests(Week):

    def test_browser_used_only_when_get_text_has_no_plan(self):
        FakeReader.pages[self.url(1)] = PLAIN
        calls = []

        def renderer(url, list_url, deadline=None):
            calls.append(url)
            guard = browser.Guard(url, list_url)
            guard.blocked_operations = 2
            return ('アフタヌーンティー 5,000円', [list_url + 'plan9/', 'https://restaurant.ikyu.com/1/'], guard)
        out = collect.fetch(1, reader_factory=FakeReader, renderer=renderer)
        self.assertEqual((out['method'], out['detail_links'], calls), ('browser', [self.url(1) + 'plan9/'], [self.url(1)]))
        self.fetch(2)
        self.assertEqual(self.state()['browser_runs'], 1)
        self.assertEqual(self.state()['blocked_operations'], 2)

    def test_browser_unavailable_continues_with_get_only(self):
        FakeReader.pages[self.url(1)] = PLAIN

        def missing(*a, **k):
            raise browser.BrowserUnavailable('playwright_not_installed')
        out = collect.fetch(1, reader_factory=FakeReader, renderer=missing)
        self.assertEqual(out['method'], 'get')
        self.assertTrue(self.state()['browser_unavailable'])
        FakeReader.pages[self.url(2)] = PLAIN
        self.assertEqual(collect.fetch(2, reader_factory=FakeReader)['method'], 'get')
        with patch.dict(sys.modules, {'playwright.sync_api': None, 'playwright': None}):
            with self.assertRaises(browser.BrowserUnavailable):
                browser.render(self.url(3), self.url(3))

    def test_forbidden_browser_operation_abandons_only_that_shop(self):
        FakeReader.pages[self.url(1)] = PLAIN

        def renderer(url, list_url, deadline=None):
            error = ForbiddenOperation('browser_left_page')
            error.guard = browser.Guard(url, list_url)
            error.guard.blocked_operations = 1
            raise error
        with self.assertRaises(ForbiddenOperation):
            collect.fetch(1, reader_factory=FakeReader, renderer=renderer)
        self.assertEqual(self.state()['rows']['1']['outcome'], 'forbidden')
        self.assertEqual(self.state()['blocked_operations'], 1)
        self.fetch(2)


class FakeRequest:
    def __init__(self, url, method='GET', kind='document', navigation=True, frame='main'):
        self.url, self.method, self.resource_type, self.frame = url, method, kind, frame
        self.navigation = navigation

    def is_navigation_request(self):
        return self.navigation


class FakeRoute:
    def __init__(self, log, request):
        self.log, self.request = log, request

    def continue_(self):
        self.log.append(('sent', self.request.url, self.request.method))

    def abort(self):
        self.log.append(('blocked', self.request.url, self.request.method))


class FakePlaywright:
    """Simulates a page whose controls try reservation steps after a click."""

    def __init__(self, url, candidates, on_click):
        self.url, self.candidates, self.on_click = url, candidates, on_click
        self.log, self.clicked, self.dialogs, self.closed = [], [], [], []
        self.chromium = self

    def launch(self, **options):
        self.options = options
        return self

    def new_context(self, **options):
        self.context_options = options
        return self

    def route(self, pattern, handler):
        self.handler = handler

    def on(self, event, callback):
        setattr(self, 'on_' + event, callback)

    def new_page(self):
        self.main_frame = 'main'
        return self

    def request(self, request):
        self.handler(FakeRoute(self.log, request), request)

    def set_default_timeout(self, value):
        pass

    def goto(self, url, **options):
        self.request(FakeRequest(url))
        self.request(FakeRequest('https://static.ikyu.com/app.js', kind='script', navigation=False))
        self.request(FakeRequest('https://ads.example.net/track.js', kind='script', navigation=False))
        self.request(FakeRequest('https://restaurant.ikyu.com/api/session', 'POST', 'xhr', False))
        self.request(FakeRequest('https://ads.example.net/frame', frame='child'))
        return type('R', (), {'status': 200})()

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_timeout(self, value):
        pass

    @property
    def mouse(self):
        return type('M', (), {'wheel': lambda *a: None})()

    def evaluate(self, script):
        if 'document.links' in script:
            return [self.url + 'plan5/', 'https://restaurant.ikyu.com/1/reserve/']
        return [c for c in self.candidates if c['label'] not in self.clicked]

    def click(self, selector, **options):
        item = next(c for c in self.candidates if selector == '[data-at-candidate="%s"]' % c['id'])
        self.clicked.append(item['label'])
        self.on_click(self, item)

    def inner_text(self, selector):
        return 'アフタヌーンティー 6,000円'

    def close(self):
        self.closed.append(True)

    def stop(self):
        pass


def item(i, label, **extra):
    return {'id': str(i), 'tag': 'button', 'label': label, 'href': None, 'type': '', 'in_form': False,
            'disabled': False, 'popup': False, **extra}


class BrowserSafetyTests(unittest.TestCase):
    URL = 'https://restaurant.ikyu.com/107408/'

    def test_click_allow_and_deny_lists(self):
        for label in ('もっと見る', 'プラン一覧', 'メニューを表示', '閉じる', '×', 'Show more'):
            self.assertTrue(browser.click_allowed(item(0, label)), label)
        for label in ('予約する', '空席確認', '予約へ進む', 'プランを予約', '申し込む', '注文', '購入', '決済', 'ログイン',
                      '会員登録', '次へ', '2名', '11月20日', '15:00', 'Reserve', 'Book now', 'Sign in', '人数を選ぶ', ''):
            self.assertFalse(browser.click_allowed(item(0, label)), label)
        self.assertFalse(browser.click_allowed(item(0, 'もっと見る', in_form=True)))
        self.assertFalse(browser.click_allowed(item(0, 'もっと見る', type='submit')))
        self.assertFalse(browser.click_allowed(item(0, 'プラン', tag='a', href='/107408/plan1/')))
        self.assertFalse(browser.click_allowed(item(0, 'もっと見る', popup=True)))
        self.assertTrue(browser.click_allowed(item(0, 'もっと見る', tag='a', href='#plans')))

    def test_guard_allows_one_navigation_get_and_site_resources_only(self):
        guard = browser.Guard(self.URL, self.URL)
        self.assertTrue(guard.allow(self.URL, 'GET', 'document', True, True))
        for (url, method, kind, nav, main) in (
                (self.URL, 'GET', 'document', True, True),
                (self.URL + 'plan1/', 'GET', 'document', True, True),
                ('https://restaurant.ikyu.com/107408/reserve/', 'GET', 'document', True, True),
                (self.URL, 'POST', 'document', True, True)):
            self.assertFalse(guard.allow(url, method, kind, nav, main))
        self.assertEqual(guard.blocked_operations, 4)
        self.assertTrue(guard.allow('https://static.ikyu.com/x.js', 'GET', 'script', False, True))
        for (url, method, kind) in (('https://restaurant.ikyu.com/api', 'POST', 'xhr'),
                                    ('https://restaurant.ikyu.com/api/login', 'GET', 'fetch'),
                                    ('https://restaurant.ikyu.com/cart/items', 'GET', 'xhr'),
                                    ('https://ads.example.net/a.js', 'GET', 'script'),
                                    ('https://static.ikyu.com/a.png', 'GET', 'image')):
            self.assertFalse(guard.allow(url, method, kind, False, True))
        with self.assertRaises(ForbiddenOperation):
            browser.Guard('https://restaurant.ikyu.com/1/', self.URL)
        with self.assertRaises(ForbiddenOperation):
            browser.Guard('https://restaurant.ikyu.com/107408/confirm/', self.URL)

    def test_reservation_controls_never_clicked_and_navigation_blocked_before_sent(self):
        candidates = [item(0, '予約する'), item(1, '11月20日'), item(2, '2名'), item(3, 'ログイン'),
                      item(4, 'もっと見る'), item(5, 'プラン一覧'), item(6, '送信', type='submit')]

        def on_click(page, clicked):
            # A page script tries to leave for a booking step and to post a form.
            page.request(FakeRequest('https://restaurant.ikyu.com/107408/reserve/step1/'))
            page.request(FakeRequest(self.URL, 'POST', 'document'))
            page.on_page(page)
            page.on_dialog(type('D', (), {'dismiss': lambda s: page.dialogs.append('dismissed')})())
        fake = FakePlaywright(self.URL, candidates, on_click)
        (text, links, guard) = browser.render(self.URL, self.URL, playwright=fake)
        self.assertEqual(fake.clicked, ['もっと見る', 'プラン一覧'])
        sent = [entry for entry in fake.log if entry[0] == 'sent']
        self.assertEqual(sent, [('sent', self.URL, 'GET'), ('sent', 'https://static.ikyu.com/app.js', 'GET')])
        self.assertIn(('blocked', 'https://restaurant.ikyu.com/107408/reserve/step1/', 'GET'), fake.log)
        self.assertIn(('blocked', self.URL, 'POST'), fake.log)
        self.assertEqual(guard.blocked_operations, 6)
        self.assertEqual(fake.dialogs, ['dismissed', 'dismissed'])
        self.assertIn('アフタヌーンティー', text)
        self.assertFalse(fake.context_options['accept_downloads'])
        self.assertEqual(fake.context_options['service_workers'], 'block')
        self.assertNotIn('storage_state', fake.context_options)

    def test_tablecheck_list_url_opens_but_reservation_steps_do_not(self):
        url = 'https://www.tablecheck.com/ja/kaguwa/reserve/landing'
        guard = browser.Guard(url, url)
        self.assertTrue(guard.allow(url, 'GET', 'document', True, True))
        self.assertFalse(guard.allow(url + '/menu/1', 'GET', 'document', True, True))
        self.assertFalse(guard.allow('https://www.tablecheck.com/ja/kaguwa/reserve/message', 'GET', 'xhr', False, True))

    def test_leaving_page_by_script_stops_that_shop(self):
        def on_click(page, clicked):
            page.url = self.URL + 'reserve/'
        fake = FakePlaywright(self.URL, [item(0, 'もっと見る')], on_click)
        with self.assertRaises(ForbiddenOperation) as caught:
            browser.render(self.URL, self.URL, playwright=fake)
        self.assertEqual(caught.exception.guard.blocked_operations, 1)


class RetentionTests(unittest.TestCase):
    def sample(self, stamp):
        d = fixture()
        d['shops'][0]['plans'][0]['checked_at'] = stamp
        d['shops'][0]['list_url'] = collect.candidates()[0]['予約ページURL']
        return d

    def test_boundary_date_retention_and_no_redating(self):
        for (age, keep) in ((0, True), (14, True), (14.0001, False), (-0.001, False)):
            stamp = (NOW - dt.timedelta(days=age)).isoformat()
            source = self.sample(stamp)
            before = copy.deepcopy(source)
            out = retain(source, now=NOW)
            self.assertEqual(bool(out['shops']), keep)
            if keep:
                self.assertEqual(out['shops'][0]['plans'][0]['checked_at'], stamp)
            self.assertEqual(source, before)

    def test_missing_naive_future_and_stale_rejected(self):
        for stamp in (None, 'invalid', '2026-11-10T00:00:00', (NOW + dt.timedelta(seconds=1)).isoformat(),
                      (NOW - dt.timedelta(days=15)).isoformat()):
            d = self.sample(stamp)
            self.assertEqual(retain(d, now=NOW)['shops'], [])
            with self.assertRaises(ValueError):
                validate_freshness(d, now=NOW)

    def test_previous_kept_with_dates_current_overrides_same_plan(self):
        old = self.sample((NOW - dt.timedelta(days=3)).isoformat())
        old['research_campaign'] = {'secret': 'not stored'}
        old['shops'][0]['plans'][0]['structured_evidence'] = {'anything': {}}
        old['shops'][0]['plans'].append({'plan_name': 'OLD ONLY', 'checked_at': (NOW - dt.timedelta(days=2)).isoformat()})
        old['shops'][0]['plans'].append({'plan_name': 'TOO OLD', 'checked_at': (NOW - dt.timedelta(days=20)).isoformat()})
        new = self.sample(NOW.isoformat())
        new['shops'][0]['plans'][0]['price_yen'] = 7000
        out = retain(new, old, now=NOW)
        plans = {p['plan_name']: p for p in out['shops'][0]['plans']}
        self.assertEqual(set(plans), {'TEST winter AT', 'OLD ONLY'})
        self.assertEqual(plans['TEST winter AT']['price_yen'], 7000)
        self.assertEqual(plans['OLD ONLY']['checked_at'], (NOW - dt.timedelta(days=2)).isoformat())
        self.assertNotIn('research_campaign', out)
        self.assertNotIn('structured_evidence', plans['TEST winter AT'])

    def test_shop_timestamp_never_replaces_missing_plan_timestamp(self):
        d = self.sample(NOW.isoformat())
        shop = d['shops'][0]
        shop['checked_at'] = NOW.isoformat()
        del shop['plans'][0]['checked_at']
        self.assertEqual(retain(d, now=NOW)['shops'], [])
        shop['plans'][0]['checked_at'] = None
        self.assertEqual(retain(d, now=NOW)['shops'], [])


class PublicationTests(unittest.TestCase):

    def test_fourteen_area_buttons_no_other_area_and_out_of_range_hidden(self):
        for area in (15, 16, 0, None, '1', True):
            d = fixture()
            d['shops'][0]['area_no'] = area
            self.assertEqual(retain(d)['shops'], [])
            self.assertNotIn('TEST ONLY lounge', render(d))
        for data in (fixture(), json.loads((ROOT / 'site/research.json').read_text())):
            html = render(data)
            self.assertEqual(len(re.findall(r'class="area-btn"', html)), 14)
            self.assertNotIn('その他のエリア', html)

    def test_current_main_data_renders_without_change(self):
        data = json.loads((ROOT / 'site/research.json').read_text())
        self.assertTrue(all(1 <= s['area_no'] <= 14 for s in data['shops']))
        html=render(data)
        self.assertEqual(html.count('<article '),len(data['shops']))
        self.assertEqual(html.count('class="plan"'),sum(len(s['plans']) for s in data['shops']))

    def test_zero_plans_publish_and_bad_third_file_is_rejected(self):
        d = fixture()
        d['shops'] = []
        f = {'site/research.json': json_bytes(d), 'site/index.html': render(d).encode()}
        self.assertEqual(validate_site(f)['plans'], 0)
        f['site/third.json'] = b'{}'
        with self.assertRaises(ValueError):
            validate_site(f)
        api = FakeAPI()
        api.pr['changed_files'] = 3
        with self.assertRaises(ValueError):
            intake(api, 1, 'tsubasa0518')
        self.assertFalse(api.calls)

    def test_candidates_are_fourteen_area_rows_in_order(self):
        rows = collect.candidates()
        self.assertEqual(len(rows), 90)
        self.assertEqual(collections.Counter(int(r['エリア番号']) for r in rows), AREA_COUNTS)
        self.assertEqual([int(r['No']) for r in rows], list(range(1, len(rows) + 1)))


class ReportTests(Week):

    def test_report_counts_without_abandoned_names(self):
        self.fetch(1)
        FakeReader.pages[self.url(2)] = RuntimeError('HTTP_429')
        with self.assertRaises(RuntimeError):
            self.fetch(2)
        self.fetch(3)
        research = json.loads((self.root / 'site/research.json').read_text())
        now = dt.datetime.now(dt.timezone.utc)
        research['shops'] = [
            {'name': 'ROW ONE', 'area_no': 2, 'list_url': self.url(1), 'source_url': self.url(1) + 'plan1/', 'category': 'hotel',
             'plans': [{'plan_name': 'A', 'checked_at': now.isoformat()}]},
            {'name': 'CARRIED', 'area_no': 3, 'list_url': self.url(4), 'source_url': self.url(4), 'category': 'cafe',
             'plans': [{'plan_name': 'B', 'checked_at': (now - dt.timedelta(days=5)).isoformat()}]}]
        with patch.object(collect, 'ROOT', ROOT):
            text = collect.report(self.state(), research, self.rows)
        for expected in ('調べた行数: 3 / 90', '調べられなかった行数: 87', '今週確認できた店舗数・プラン数: 1店舗・1プラン',
                         '引き継いだプラン数（14日以内・確認日時そのまま）: 1', '403・429・CAPTCHA・同一サイトの停止 1',
                         'ATプラン未確認・情報不足 1', '一休.com 成功1・失敗2', '銀座・有楽町・日比谷 1',
                         'ホテル 1', 'カフェ 1', 'テーマ国別（プラン数）: 未確認 2'):
            self.assertIn(expected, text)
        for row in self.rows[1:3]:
            self.assertNotIn(row['店名'], text)


class RobotsCacheTests(Week):
    def open_pages(self, rules='User-agent: *\nAllow: /\n'):
        self.opened=[]
        def open_(request, timeout):
            url=request.full_url; self.opened.append(url)
            if url.endswith('/robots.txt'):
                if isinstance(rules,Exception):raise rules
                return Response(url,rules,'text/plain')
            return Response(url,'<p>アフタヌーンティー</p>')
        def factory(**options):
            reader=Reader(delay=0,**options)
            reader.transport.opener=Mock()
            reader.transport.opener.open.side_effect=open_
            return reader
        return factory

    def test_all_ninety_rows_get_robots_once_per_host_and_reset_next_week(self):
        factory=self.open_pages()
        for no in range(1,91):
            out=collect.fetch(no,reader_factory=factory)
            self.assertEqual(out['shop']['list_url'],self.url(no))
            self.assertEqual(out['detail_links'],[])
        robots=[url for url in self.opened if url.endswith('/robots.txt')]
        self.assertEqual(sorted(robots),sorted({'https://'+urlsplit(row['予約ページURL']).hostname+'/robots.txt' for row in self.rows}))
        self.assertEqual(self.state()['requests'],93)
        state_text=json.dumps(self.state(),ensure_ascii=False)
        self.assertNotIn(self.rows[0]['店名'],state_text)
        self.assertEqual(set(self.state()['robots']),{'restaurant.ikyu.com','tabelog.com','www.tablecheck.com'})
        collect.begin()
        collect.fetch(1,reader_factory=factory)
        self.assertEqual(self.opened.count('https://restaurant.ikyu.com/robots.txt'),2)

    def test_unknown_and_refused_robots_are_cached_without_retry(self):
        for code in (403,429,500):
            collect.begin()
            factory=self.open_pages(HTTPError('https://restaurant.ikyu.com/robots.txt',code,'test',{},None))
            for no in (1,2):
                with self.assertRaises(RuntimeError):collect.fetch(no,reader_factory=factory)
            self.assertEqual(self.opened,['https://restaurant.ikyu.com/robots.txt'])
            self.assertIsNone(self.state()['robots']['restaurant.ikyu.com'])

    def test_cached_rules_are_evaluated_per_url_not_as_a_host_allow_boolean(self):
        factory=self.open_pages('User-agent: *\nDisallow: '+urlsplit(self.url(1)).path+'\n')
        with self.assertRaisesRegex(RuntimeError,'robots'):collect.fetch(1,reader_factory=factory)
        collect.fetch(2,reader_factory=factory)
        self.assertEqual(self.opened,['https://restaurant.ikyu.com/robots.txt',self.url(2)])

    def test_comment_only_lines_do_not_split_the_user_agent_group(self):
        for comment in ('# private pages', '   # private pages', '\t# private pages'):
            collect.begin()
            rules = 'User-agent: *\n'+comment+'\nDisallow: '+urlsplit(self.url(1)).path+'\n'
            factory = self.open_pages(rules)
            with self.assertRaisesRegex(RuntimeError, 'robots'):
                collect.fetch(1, reader_factory=factory)
            self.assertEqual(self.opened, ['https://restaurant.ikyu.com/robots.txt'])
            collect.fetch(2, reader_factory=factory)
            self.assertNotIn(self.url(1), self.opened)
            self.assertEqual(self.opened.count('https://restaurant.ikyu.com/robots.txt'), 1)

    def test_rule_cache_restores_crawl_delay_and_drops_comments_and_sitemaps(self):
        rules='User-agent: *\nAllow: /\nCrawl-delay: 7\n# contact: not saved\nSitemap: https://example.test/sitemap.xml\n'
        factory=self.open_pages(rules)
        with patch.object(reader_module.time,'sleep'):
            collect.fetch(1,reader_factory=factory)
        restored=Reader(delay=0);restored.robots_cache=self.state()['robots']
        restored.transport.opener=Mock(side_effect=AssertionError('cached robots must not make a request'))
        self.assertTrue(restored.robots_allows(self.url(2),self.url(2)))
        self.assertEqual(restored.robots['restaurant.ikyu.com'].crawl_delay(reader_module.USER_AGENT),7)
        self.assertNotIn('contact',json.dumps(self.state()['robots']))
        self.assertNotIn('sitemap',json.dumps(self.state()['robots']))

class TableCheckListTests(unittest.TestCase):
    def test_rows_88_to_90_exact_get_allowed_but_following_pages_never_sent(self):
        rows=collect.candidates()
        endings=('/reserve/message','/reserve/landing','/reserve/experiences')
        for row,ending in zip(rows[-3:],endings):
            url=row['予約ページURL'];self.assertTrue(url.endswith(ending))
            transport=ReadOnlyTransport();transport.opener=Mock()
            transport.open(url,list_url=url)
            sent=transport.opener.open.call_args.args[0]
            self.assertEqual((sent.full_url,sent.method),(url,'GET'))
            for target in (url+'/next',url.rsplit('/',1)[0],url+'?date=20261116',url+'#next'):
                with self.assertRaises(ForbiddenOperation):transport.open(target,list_url=url)
            with self.assertRaises(ForbiddenOperation):transport.open(url,list_url=url,method='POST')
            self.assertEqual(transport.opener.open.call_count,1)
            self.assertEqual(collect._links(url,[url+'/next',url.rsplit('/',1)[0]],url),[])
            guard=Guard(url,url)
            self.assertTrue(guard.allow(url,'GET','document',True,True))
            self.assertFalse(guard.allow(url+'/next','GET','document',True,True))

class ExcerptTests(Week):
    def test_default_shows_only_at_context_and_full_flag_shows_all_without_a_second_read(self):
        text='NON_AT_START'+'x'*35000+'アフタヌーンティー 通常料金7000円 メニュー 苺'+'y'*35000+'NON_AT_END'
        FakeReader.pages[self.url(1)]='<p>'+text+'</p>'
        short=self.fetch(1)
        self.assertIn('アフタヌーンティー',short['text'])
        self.assertNotIn('NON_AT_START',short['text']);self.assertNotIn('NON_AT_END',short['text'])
        self.assertLessEqual(len(short['text']),collect.MAX_EXCERPT)
        self.assertEqual(short['full_text_chars'],len(text));self.assertTrue(short['truncated'])
        before=len(FakeReader.opened)
        full=self.fetch(1,full=True)
        self.assertEqual(full['text'],text);self.assertFalse(full['truncated'])
        self.assertEqual(len(FakeReader.opened)-before,1)
        self.assertTrue(parser().parse_args(['fetch','1','--full']).full)

    def test_no_at_word_is_empty_and_overlapping_windows_are_not_duplicated(self):
        self.assertEqual(collect.excerpt('regular lunch only'), '')
        text='Afternoon Tea / ハイティー / アフタヌーンティー'
        self.assertEqual(collect.excerpt(text),text)
        many=('x'*1700+'アフタヌーンティー')*20
        self.assertLessEqual(len(collect.excerpt(many)),collect.MAX_EXCERPT)

class URLRetentionTests(unittest.TestCase):
    def data(self):
        data=fixture();shop=data['shops'][0]
        shop.pop('id',None);shop.pop('checked_at',None)
        row=collect.candidates()[0]
        shop.update(list_url=row['予約ページURL'],area_no=int(row['エリア番号']))
        shop['plans'][0]['checked_at']=dt.datetime.now(dt.timezone.utc).isoformat()
        return data

    def test_exact_csv_url_is_only_shop_key_and_plan_name_is_only_plan_key(self):
        previous=self.data();current=copy.deepcopy(previous)
        previous['shops'][0].update(name='Old name',id='old-id')
        current['shops'][0].update(name='New name',id='new-id')
        current['shops'][0]['plans'][0]['price_yen']=7000
        out=retain(current,previous)
        self.assertEqual(len(out['shops']),1)
        self.assertEqual(out['shops'][0]['name'],'New name')
        self.assertEqual(len(out['shops'][0]['plans']),1)
        self.assertEqual(out['shops'][0]['plans'][0]['price_yen'],7000)
        current['shops'][0]['list_url']=current['shops'][0]['list_url'].rstrip('/')
        self.assertEqual(retain(current)['shops'],[])

    def test_unlisted_shops_are_excluded_even_when_fresh(self):
        for url in (None, 'https://www.example.com/legacy-tea/'):
            saved=self.data()
            saved['shops'][0]['list_url']=url
            before=copy.deepcopy(saved)
            stamp=dt.datetime.fromisoformat(saved['shops'][0]['plans'][0]['checked_at'])
            out=retain(saved,now=stamp+dt.timedelta(days=1))
            self.assertEqual(out['shops'],[])
            self.assertNotIn('<article ',render(out))
            self.assertEqual(saved,before)

    def test_new_format_one_shop_and_zero_shops_complete_current_pipeline(self):
        for count in (1,0):
            data=self.data(); data['shops']=data['shops'][:count]
            if count:data['shops'][0]['plans'][0]['cc']=None
            data=build(data)
            html=render(data)
            self.assertEqual(validate_site({'site/research.json':json_bytes(data),'site/index.html':html.encode()})['shops'],count)
            self.assertEqual(html.count('<article '),count)
            if count:
                self.assertNotIn('id',data['shops'][0]);self.assertNotIn('checked_at',data['shops'][0])

    def test_dates_preserved_for_carried_plans_and_outside_list_not_retained(self):
        old=self.data();now=dt.datetime.now(dt.timezone.utc)
        stamp=(now-dt.timedelta(days=13)).isoformat()
        old['shops'][0]['plans'][0]['checked_at']=stamp
        current=copy.deepcopy(old);current['shops']=[]
        out=retain(current,old,now=now)
        self.assertEqual(out['shops'][0]['plans'][0]['checked_at'],stamp)
        old['shops'][0]['list_url']='https://restaurant.ikyu.com/999999/'
        self.assertEqual(retain(current,old,now=now)['shops'],[])

class BudgetDefinitionTests(unittest.TestCase):
    def test_limits_have_one_definition_and_reader_and_begin_use_them(self):
        self.assertEqual((collect.RESEARCH_SECONDS,collect.MAX_REQUESTS,collect.SHOP_SECONDS,collect.INTERVAL),(1500,200,60,3))
        with patch.object(reader_module.time,'monotonic',return_value=100):
            reader=Reader()
            self.assertEqual((reader.deadline,reader.max_requests,reader.delay),(1600,200,3))

class TableCheckReportTests(Week):
    def test_tablecheck_without_shop_key_is_matched_only_by_exact_list_url(self):
        state=self.state()
        state['rows']={str(no):{'site':'TableCheck','outcome':'no_plan','browser':False} for no in (88,89)}
        research=json.loads((self.root/'site/research.json').read_text())
        research['shops']=[{'name':'ONE CONFIRMED','area_no':2,'list_url':self.url(88),'category':'unknown',
                            'plans':[{'plan_name':'AT','checked_at':dt.datetime.now(dt.timezone.utc).isoformat()}]}]
        text=collect.report(state,research,self.rows)
        self.assertIn('TableCheck 成功1・失敗1',text)
        self.assertNotIn(self.rows[88]['店名'],text)


class PublicContactPageTests(unittest.TestCase):
    reader = ReaderTests.reader

    def test_get_page_with_contact_details_is_read_without_saving_body(self):
        raw='<h1>アフタヌーンティー</h1><p>Contact someone@example.test 090-1234-5678</p>'
        reader, seen=self.reader({IKYU:raw})
        self.assertEqual(reader.fetch(IKYU,IKYU),raw)
        self.assertEqual(seen,['https://restaurant.ikyu.com/robots.txt',IKYU])
        self.assertNotIn('someone@example.test',json.dumps(reader.robots_cache))
        self.assertFalse(reader.blocked_hosts)

    def test_browser_contact_is_read_but_captcha_still_stops(self):
        for body,challenge in (('アフタヌーンティー info@example.test',False),
                               ('Please complete CAPTCHA info@example.test',True)):
            fake=FakePlaywright(IKYU,[],lambda *args:None)
            fake.inner_text=lambda selector:body
            if challenge:
                with self.assertRaisesRegex(RuntimeError,'access_challenge') as caught:
                    browser.render(IKYU,IKYU,playwright=fake)
                self.assertIsInstance(caught.exception.guard,browser.Guard)
            else:
                text,links,guard=browser.render(IKYU,IKYU,playwright=fake)
                self.assertEqual(text,body)
                self.assertFalse(guard.blocked_operations)
