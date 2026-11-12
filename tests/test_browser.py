"""Research browser on local pages only: search is allowed, reservation is never sent."""
import tempfile
import unittest
from pathlib import Path

from afternoon_tea.browser import classify, search_forms, search_url
from afternoon_tea.config import settings
from afternoon_tea.fetch import Policy, RunState
from tests.local_site import LocalSite

try:
    import playwright.sync_api  # noqa: F401
    HAVE_PLAYWRIGHT = True
except ImportError:
    HAVE_PLAYWRIGHT = False


def item(**values):
    base = {'id': '1', 'tag': 'button', 'type': '', 'role': '', 'label': '', 'name': '', 'href': None, 'raw_href': None,
            'target': '', 'form': -1, 'disabled': False, 'checked': False, 'value': '', 'options': None,
            'in_calendar': False, 'in_paging': False}
    base.update(values)
    return base


class ClassificationTests(unittest.TestCase):
    policy = Policy()

    def kind(self, **values):
        return classify(item(**values), {0: {'index': 0}}, self.policy)[0]

    def test_reading_controls_are_allowed(self):
        self.assertEqual(self.kind(label='もっと見る'), 'click')
        self.assertEqual(self.kind(tag='summary', label='メニュー詳細'), 'click')
        self.assertEqual(self.kind(role='tab', label='アフタヌーンティー'), 'click')
        # Numbers and "next" are allowed for result paging.
        self.assertEqual(self.kind(label='2', in_paging=True), 'click')
        self.assertEqual(self.kind(tag='a', label='次へ', href='https://www.example.com/search?q=x&page=2',
                                   raw_href='/search?q=x&page=2', in_paging=True), 'navigate')
        self.assertEqual(self.kind(tag='a', label='【12/1〜12/25】クリスマス アフタヌーンティー',
                                   href='https://www.example.com/plan/12', raw_href='/plan/12'), 'navigate')

    def test_reservation_and_account_controls_are_refused(self):
        for values in ({'label': '予約する'}, {'label': '空席確認'}, {'label': 'キャンセル待ちに登録'},
                       {'label': 'ログイン'}, {'label': '会員登録'}, {'label': 'お問い合わせ'}, {'label': '購入手続きへ'},
                       {'label': 'Book now'}, {'label': '24', 'in_calendar': True}, {'label': '2名'},
                       {'label': '12:00'}, {'label': '日付を選ぶ'},
                       {'tag': 'a', 'label': 'このプランで予約する', 'href': 'https://www.example.com/plan/1', 'raw_href': '/plan/1'},
                       {'tag': 'a', 'label': '詳細', 'href': 'https://www.example.com/shop/reserve', 'raw_href': '/shop/reserve'},
                       {'label': 'よくわからない操作'}):
            with self.subTest(values=values):
                self.assertEqual(self.kind(**values), 'deny')

    def test_only_search_keyword_and_the_afternoon_tea_option(self):
        controls = [item(id='1', tag='input', type='text', name='q', label='キーワード', form=0),
                    item(id='2', tag='input', type='checkbox', name='g', value='at', label='アフタヌーンティー', form=0, checked=True),
                    item(id='3', tag='input', type='checkbox', name='g', value='date', label='デート向け', form=0, checked=True),
                    item(id='4', tag='select', name='people', label='人数', form=0),
                    item(id='5', tag='input', type='date', name='date', form=0, value='2026-12-24'),
                    item(id='6', tag='input', type='hidden', name='area', form=0, value='tokyo'),
                    item(id='7', tag='input', type='hidden', name='authenticity_token', form=0, value='secret')]
        forms = [{'index': 0, 'action': 'https://www.example.com/search', 'raw_action': '/search', 'method': 'get'}]
        searchable = search_forms(controls, forms, self.policy)
        self.assertIn(0, searchable)
        kinds = {c['id']: classify(c, searchable, self.policy)[0] for c in controls}
        self.assertEqual(kinds['1'], 'fill')
        self.assertEqual(kinds['2'], 'check')
        self.assertEqual(kinds['3'], 'deny')
        self.assertEqual(kinds['4'], 'deny')
        self.assertEqual(kinds['5'], 'deny')
        url = search_url(forms[0], controls, {'1': 'コンラッド東京 アフタヌーンティー'})
        self.assertIn('g=at', url)
        for added in ('date', 'people', 'authenticity_token'):
            self.assertNotIn(added, url)

    def test_reservation_or_personal_data_form_is_not_a_search_form(self):
        policy = self.policy
        controls = [item(id='1', tag='input', type='text', name='q', label='キーワード', form=0),
                    item(id='2', tag='input', type='email', name='mail', form=0)]
        forms = [{'index': 0, 'action': 'https://www.example.com/search', 'raw_action': '/search', 'method': 'get'}]
        self.assertEqual(search_forms(controls, forms, policy), {})
        forms = [{'index': 0, 'action': 'https://www.example.com/reserve', 'raw_action': '/reserve', 'method': 'get'}]
        self.assertEqual(search_forms(controls[:1], forms, policy), {})
        forms = [{'index': 0, 'action': 'https://www.example.com/search', 'raw_action': '/search', 'method': 'post'}]
        self.assertEqual(search_forms(controls[:1], forms, policy), {})


@unittest.skipUnless(HAVE_PLAYWRIGHT, 'Playwright is not installed')
class LocalBrowserTests(unittest.TestCase):
    """A real headless browser on local imitation pages; no external site is contacted."""

    def session(self, site):
        from afternoon_tea.browser import Session
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        run = RunState(Path(tmp.name))
        limits = settings()
        limits['min_interval_seconds'] = 0.01
        run.start(limits)
        session = Session(run, Policy(test_hosts={site.host}))
        self.addCleanup(session.close)
        return session, run

    def ids(self, session, **match):
        rows = session.list_controls()
        return {r['label']: (r['id'], r['allowed']) for r in rows}

    def test_from_a_shop_name_search_to_the_plan_page_without_any_reservation_request(self):
        from afternoon_tea.browser import execute
        with LocalSite() as site:
            session, run = self.session(site)
            execute(session, 'open', {'url': site.base + '/'})
            rows = session.list_controls()
            by_kind = {r['allowed']: r['id'] for r in reversed(rows)}
            keyword = by_kind['fill']
            at = [r['id'] for r in rows if r['allowed'] == 'check'][0]
            date_option = [r['id'] for r in rows if 'デート向け' in r['label']][0]
            self.assertTrue(execute(session, 'fill', {'id': keyword, 'text': 'テストラウンジ テストホテル東京'})['ok'])
            self.assertTrue(execute(session, 'check', {'id': at})['ok'])
            refused = execute(session, 'check', {'id': date_option})
            self.assertEqual(refused['kind'], 'forbidden')
            result = execute(session, 'submit', {'id': by_kind['submit']})
            self.assertTrue(result['ok'], result)
            self.assertIn('/search?', session.current.url)
            self.assertIn('genre=at', session.current.url)
            self.assertNotIn('date', session.current.url.split('?')[1])
            links = session.links()
            shop = [l for l in links if '検索結果' in l['label']][0]
            self.assertTrue([l for l in links if l['label'] in ('2', '次へ')])  # paging is available
            self.assertTrue(execute(session, 'click', {'id': shop['id']})['ok'])
            self.assertTrue(session.current.url.endswith('/shop/1'))
            rows = {r['label']: r for r in session.list_controls()}
            for label in ('予約する', '空席確認', '24', '12/24 2名で空きを見る'):
                outcome = execute(session, 'click', {'id': rows[label]['id']})
                self.assertEqual(outcome['kind'], 'forbidden', label)
            self.assertTrue(execute(session, 'click', {'id': rows['もっと見る']['id']})['ok'])
            self.assertIn('セイボリー3種とスコーン', session.snapshot()['text'])
            plan = execute(session, 'click', {'id': rows['【冬】ストロベリー アフタヌーンティー']['id']})
            self.assertTrue(plan['ok'])
            self.assertIn('7,500円', plan['result']['text'])
            self.assertIn('/shop/1/plan/10', [v['final_url'].split(site.host)[1] for v in run.load()['visits']])
            sent = site.log
            self.assertFalse([p for m, p in sent if m != 'GET'])
            self.assertFalse([p for m, p in sent if 'reserve' in p or 'login' in p or 'register' in p or 'date=' in p])
            self.assertGreaterEqual(run.load()['blocked_operations'], 5)

    def test_normal_redirect_paging_robots_refusal_and_denial(self):
        from afternoon_tea.browser import execute
        with LocalSite() as site:
            session, run = self.session(site)
            moved = execute(session, 'open', {'url': site.base + '/moved'})
            self.assertTrue(moved['ok'])
            self.assertTrue(session.current.url.endswith('/shop/1'))
            self.assertEqual(execute(session, 'open', {'url': site.base + '/go-reserve'})['kind'], 'forbidden')
            self.assertEqual(execute(session, 'open', {'url': site.base + '/private/page'})['kind'], 'access_refused')
            paging = [l for l in session.links() if l['label'] == '2']
            self.assertTrue(execute(session, 'click', {'id': paging[0]['id']})['ok'])
            self.assertTrue(execute(session, 'open', {'url': site.base + '/shop/1/plan/10', 'new_tab': True})['ok'])
            self.assertEqual(len(session.tabs()), 2)
            self.assertTrue(execute(session, 'tab', {'index': 0})['ok'])
            self.assertEqual(execute(session, 'open', {'url': site.base + '/denied'})['kind'], 'access_refused')
            self.assertEqual(execute(session, 'open', {'url': site.base + '/shop/2'})['kind'], 'access_refused')
            paths = [p for _, p in site.log]
            self.assertNotIn('/shop/1/reserve', paths)
            self.assertNotIn('/private/page', paths)
            self.assertNotIn('/shop/2', paths)  # no retry on a refused host

    def test_access_challenge_stops_the_host(self):
        from afternoon_tea.browser import execute
        with LocalSite() as site:
            session, run = self.session(site)
            self.assertEqual(execute(session, 'open', {'url': site.base + '/captcha'})['kind'], 'access_refused')
            self.assertIn(site.host, run.load()['blocked_hosts'])


if __name__ == '__main__':
    unittest.main()
