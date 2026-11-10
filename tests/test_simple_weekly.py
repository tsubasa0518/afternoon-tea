"""Offline weekly behavior: list URLs only, in order from No.1, publish what was read."""
import collections
import copy
import datetime as dt
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from afternoon_tea.common import ROOT
from afternoon_tea.collection import browser, weekly as collect
from afternoon_tea.collection.transport import ForbiddenOperation, check_scope
from afternoon_tea.processing.weekly import retain, validate_freshness
from afternoon_tea.publication.renderer import render
from afternoon_tea.publication.site import validate_site, json_bytes, intake
from tests.test_renderer import fixture
from tests.test_site_intake import FakeAPI

NOW = dt.datetime(2026, 11, 10, 12, tzinfo=dt.timezone.utc)
AT = '<html><body><h1>アフタヌーンティー</h1><a href="plan111/">plan</a><a href="/999999/">other</a></body></html>'
PLAIN = '<html><body><div id="app"></div></body></html>'
# Expected area counts after the fourteen-area judgement of the 385-row list.
AREA_COUNTS = {1: 35, 2: 54, 3: 28, 4: 20, 5: 30, 6: 32, 7: 24, 8: 35, 9: 15, 10: 20, 11: 10, 12: 9, 13: 11, 14: 8}


class FakeReader:
    pages = {}
    opened = []

    def __init__(self, max_requests=150, timeout=15, seconds=420):
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
        for name in ('data/references/user_candidates.csv', 'data/store_master.json', 'site/research.json'):
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
        shop = {'name': 'ROW ONE', 'area_no': 1, 'source_url': self.url(1),
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

    def test_old_shop_timestamp_is_used_only_when_plan_date_absent(self):
        d = self.sample(NOW.isoformat())
        shop = d['shops'][0]
        shop['checked_at'] = NOW.isoformat()
        del shop['plans'][0]['checked_at']
        self.assertEqual(retain(d, now=NOW)['shops'][0]['plans'][0]['checked_at'], NOW.isoformat())
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
        self.assertEqual(render(data).encode(), (ROOT / 'site/index.html').read_bytes())

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
        self.assertEqual(len(rows), 331)
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
            {'name': 'ROW ONE', 'area_no': 2, 'source_url': self.url(1) + 'plan1/', 'category': 'hotel',
             'plans': [{'plan_name': 'A', 'checked_at': now.isoformat()}]},
            {'name': 'CARRIED', 'area_no': 3, 'source_url': 'https://restaurant.ikyu.com/1/', 'category': 'cafe',
             'plans': [{'plan_name': 'B', 'checked_at': (now - dt.timedelta(days=5)).isoformat()}]}]
        with patch.object(collect, 'ROOT', ROOT):
            text = collect.report(self.state(), research, self.rows)
        for expected in ('調べた行数: 3 / 331', '調べられなかった行数: 328', '今週確認できた店舗数・プラン数: 1店舗・1プラン',
                         '引き継いだプラン数（14日以内・確認日時そのまま）: 1', '403・429・CAPTCHA・同一サイトの停止 1',
                         'ATプラン未確認・情報不足 1', '一休.com 成功1・失敗2', '銀座・有楽町・日比谷 1',
                         'ホテル 1', 'カフェ 1', 'テーマ国別（プラン数）: 未確認 2'):
            self.assertIn(expected, text)
        for row in self.rows[1:3]:
            self.assertNotIn(row['店名'], text)


if __name__ == '__main__':
    unittest.main()
