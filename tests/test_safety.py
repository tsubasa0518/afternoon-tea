"""Request checks, robots.txt, access refusal, limits and saved research progress.

No live request is made: the reader uses a scripted opener, and research files are temporary.
"""
import copy
import datetime as dt
import io
import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import afternoon_tea.research as research
from afternoon_tea.config import candidates, excluded_genre, main_genre, same_venue, search_queries, settings
from afternoon_tea.fetch import (JST, AccessRefused, BudgetExhausted, ForbiddenOperation, Policy, Reader, RunState,
                                 Unusable)


def limits(**values):
    base = settings()
    base.update(min_interval_seconds=0.0, **values)
    return base


class Scripted:
    """Answers by URL; records every request that would have been sent."""

    def __init__(self, pages):
        self.pages = pages
        self.sent = []

    def open(self, request, timeout):
        url = request.full_url
        self.sent.append(url)
        status, body, kind, location = self.pages.get(url, (404, 'not found', 'text/plain', None))
        headers = Message()
        headers['Content-Type'] = kind
        if location:
            headers['Location'] = location
        if status >= 300:
            raise HTTPError(url, status, 'x', headers, io.BytesIO(body.encode()))
        response = io.BytesIO(body.encode())
        response.status, response.headers = status, headers
        return response


def page(body='<html><body><p>アフタヌーンティー 5,000円</p></body></html>'):
    return (200, body, 'text/html; charset=utf-8', None)


ROBOTS = (200, 'User-agent: *\nDisallow: /private/\nCrawl-delay: 4\n', 'text/plain', None)


class Temp(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.run = RunState(self.dir / 'run')
        self.run.start(limits())

    def reader(self, pages, **values):
        opener = Scripted(pages)
        sleeps = []
        reader = Reader(self.run, Policy(), opener=opener, limits=limits(**values) if values else None,
                        sleep=sleeps.append)
        return reader, opener, sleeps


class PolicyTests(unittest.TestCase):
    policy = Policy()

    def test_search_results_paging_and_official_pages_are_allowed(self):
        for url in ('https://www.example-hotel.co.jp/restaurant/lounge/afternoon-tea/',
                    'https://tabelog.com/tokyo/rstLst/?sk=%E3%82%A2%E3%83%95%E3%82%BF%E3%83%8C%E3%83%BC%E3%83%B3&page=2',
                    'https://www.example.com/search?q=ザ・グラン ラウンジ アフタヌーンティー'.replace(' ', '+'),
                    'https://restaurant.ikyu.com/107408/plan12345/',
                    'https://www.example.com/border/plan',  # "order" inside a word is not an order page
                    'https://www.tablecheck.com/ja/shops/test-only/reserve',
                    'https://www.tablecheck.com/ja/test-only/reserve/landing',
                    'https://www.tablecheck.com/test-only/reserve/experiences'):
            self.policy.check(url)

    def test_reservation_transaction_login_and_slot_urls_are_refused_before_sending(self):
        for url in ('https://www.example.com/shop/1/reserve', 'https://www.example.com/booking/step1',
                    'https://www.example.com/login', 'https://www.example.com/member/register',
                    'https://www.example.com/checkout', 'https://www.example.com/cart',
                    'https://www.example.com/inquiry', 'https://www.example.com/%E4%BA%88%E7%B4%84/',
                    'https://www.example.com/plan?date=2026-12-24', 'https://www.example.com/plan?people=2',
                    'https://www.example.com/plan?party_size=2&time=12:00', 'https://www.example.com/x?session_id=1',
                    'https://www.tablecheck.com/ja/shops/test-only/reserve?menu_items=1&num_people=2',
                    'https://www.tablecheck.com/ja/reservations/new', 'https://tabelog.com/yoyaku/net/',
                    'https://www.tablecheck.com/test-only/reserve/message', 'https://www.example.com/shop/reserve/experiences'):
            with self.subTest(url=url), self.assertRaises(ForbiddenOperation):
                self.policy.check(url)

    def test_only_https_public_hosts_without_credentials_and_only_get(self):
        for url in ('http://www.example.com/', 'https://user:pass@www.example.com/', 'https://127.0.0.1/',
                    'https://localhost/', 'https://intranet.local/', 'https://www.example.com:8443/', 'ftp://x.com/'):
            with self.subTest(url=url), self.assertRaises(ForbiddenOperation):
                self.policy.check(url)
        for method in ('POST', 'PUT', 'DELETE'):
            with self.assertRaises(ForbiddenOperation):
                self.policy.check('https://www.example.com/', method=method)


class ReaderTests(Temp):
    BASE = 'https://www.example.com'

    def test_robots_first_then_page_and_crawl_delay_is_respected(self):
        reader, opener, sleeps = self.reader({self.BASE + '/robots.txt': ROBOTS, self.BASE + '/a': page(),
                                              self.BASE + '/b': page()})
        reader.get(self.BASE + '/a')
        reader.get(self.BASE + '/b')
        self.assertEqual(opener.sent, [self.BASE + '/robots.txt', self.BASE + '/a', self.BASE + '/b'])
        self.assertTrue(sleeps and max(sleeps) > 3.0)  # crawl-delay 4 is longer than the setting
        visits = [v['url'] for v in self.run.load()['visits']]
        self.assertEqual(visits, [self.BASE + '/a', self.BASE + '/b'])

    def test_robots_disallow_is_not_requested(self):
        reader, opener, _ = self.reader({self.BASE + '/robots.txt': ROBOTS})
        with self.assertRaisesRegex(AccessRefused, 'disallows'):
            reader.get(self.BASE + '/private/page')
        self.assertEqual(opener.sent, [self.BASE + '/robots.txt'])

    def test_missing_robots_allows_but_unreachable_robots_is_neither_permission_nor_permanent(self):
        reader, opener, _ = self.reader({self.BASE + '/a': page()})  # robots.txt 404
        reader.get(self.BASE + '/a')
        other = 'https://www.other.example'
        reader, opener, _ = self.reader({other + '/robots.txt': (503, 'busy', 'text/plain', None), other + '/a': page()})
        with self.assertRaisesRegex(AccessRefused, 'robots_txt_unavailable'):
            reader.get(other + '/a')
        self.assertNotIn(other + '/a', opener.sent)
        # Only this run remembers it; the next run starts with empty state and may try again.
        self.assertEqual(self.run.load()['robots']['www.other.example']['status'], 'unknown')
        self.run.start(limits())
        self.assertEqual(self.run.load()['robots'], {})

    def test_403_429_and_challenge_stop_that_host_without_retry(self):
        for status in (403, 429):
            self.run.start(limits())
            reader, opener, _ = self.reader({self.BASE + '/a': (status, 'no', 'text/html', None), self.BASE + '/b': page()})
            with self.assertRaises(AccessRefused):
                reader.get(self.BASE + '/a')
            with self.assertRaisesRegex(AccessRefused, 'host_stopped'):
                reader.get(self.BASE + '/b')
            self.assertNotIn(self.BASE + '/b', opener.sent)
        self.run.start(limits())
        reader, opener, _ = self.reader({self.BASE + '/a': page('<html><body>Please verify you are human</body></html>'),
                                         'https://www.independent.example/a': page()})
        with self.assertRaisesRegex(AccessRefused, 'challenge'):
            reader.get(self.BASE + '/a')
        self.assertIn('www.example.com', self.run.load()['blocked_hosts'])
        # An independent public source is still available in the same run.
        reader.get('https://www.independent.example/a')

    def test_robots_refusal_stops_host(self):
        reader, opener, _ = self.reader({self.BASE + '/robots.txt': (403, 'no', 'text/html', None)})
        with self.assertRaisesRegex(AccessRefused, 'robots_txt_refused'):
            reader.get(self.BASE + '/a')
        self.assertNotIn(self.BASE + '/a', opener.sent)

    def test_redirect_hops_are_checked_before_they_are_sent(self):
        reader, opener, _ = self.reader({self.BASE + '/moved': (302, '', 'text/html', '/shop'), self.BASE + '/shop': page(),
                                         self.BASE + '/go': (302, '', 'text/html', '/shop/reserve')})
        result = reader.get(self.BASE + '/moved')
        self.assertEqual(result.final_url, self.BASE + '/shop')
        with self.assertRaises(ForbiddenOperation):
            reader.get(self.BASE + '/go')
        self.assertNotIn(self.BASE + '/shop/reserve', opener.sent)

    def test_limits_are_settings_and_stop_with_a_save_signal(self):
        reader, opener, _ = self.reader({self.BASE + '/a': page()}, max_navigations=2)
        reader.get(self.BASE + '/a')  # robots + page
        with self.assertRaises(BudgetExhausted):
            reader.get(self.BASE + '/a')
        with patch.dict('os.environ', {'AFTERNOON_TEA_TOTAL_SECONDS': '7200'}):
            self.assertEqual(settings()['total_seconds'], 7200)
        with patch.dict('os.environ', {'AFTERNOON_TEA_TOTAL_SECONDS': 'inf'}), self.assertRaises(ValueError):
            settings()

    def test_non_html_is_unusable(self):
        reader, _, _ = self.reader({self.BASE + '/menu.pdf': (200, '%PDF', 'application/pdf', None)})
        with self.assertRaisesRegex(Unusable, 'not_html'):
            reader.get(self.BASE + '/menu.pdf')


class GenreAndIdentityTests(unittest.TestCase):
    def test_owner_genres_are_excluded_by_the_main_genre_only(self):
        self.assertEqual(excluded_genre('フレンチレストラン・バー'), 'フレンチ')
        self.assertEqual(excluded_genre('イタリアン、ダイニングバー、カフェ'), 'イタリアン')
        self.assertEqual(excluded_genre('日本料理、創作料理'), '日本食')
        self.assertEqual(excluded_genre('広東料理'), '中華')
        for genre in ('ラウンジ', 'カフェ・ラウンジ', 'ロビーラウンジ', 'バーラウンジ・フランス料理', 'カフェ、ケーキ', None, ''):
            self.assertIsNone(excluded_genre(genre), genre)
        self.assertEqual(main_genre('ダイニングバー、イタリアン、居酒屋'), 'ダイニングバー')

    def test_exclusion_list_is_an_editable_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'genres.json'
            path.write_text(json.dumps({'genres': [{'label': 'テスト料理', 'terms': ['テスト料理']}]}), encoding='utf-8')
            self.assertEqual(excluded_genre('テスト料理店', path=path), 'テスト料理')
            self.assertIsNone(excluded_genre('フレンチ', path=path))

    def test_identity_uses_names_and_facility_not_urls(self):
        self.assertTrue(same_venue(('パーク ハイアット 東京 / ピーク ラウンジ', None), ('ピーク ラウンジ＆バー', 'パーク ハイアット 東京')))
        self.assertTrue(same_venue(('マンダリン オリエンタル 東京 / オリエンタルラウンジ（38F）', None),
                                   ('オリエンタルラウンジ', 'マンダリン オリエンタル 東京')))
        self.assertTrue(same_venue(('セルリアンタワー東急ホテル / ガーデンラウンジ 坐忘', None),
                                   ('ガーデンラウンジ「坐忘」', 'セルリアンタワー東急ホテル')))
        self.assertFalse(same_venue(('ロビーラウンジ', '第一ホテル東京'), ('ロビーラウンジ', 'ザ・プリンス パークタワー東京')))
        self.assertFalse(same_venue(('ル サロン ド ニナス 小田急百貨店新宿', None), ('ル サロン ド ニナス 日比谷', None)))

    def test_search_starts_from_names_not_from_stored_urls(self):
        queries = search_queries('ザ・グラン ラウンジ', None, '一休.com')
        self.assertEqual(queries, ['ザ・グラン ラウンジ アフタヌーンティー', 'ザ・グラン ラウンジ 一休.com アフタヌーンティー'])
        self.assertTrue(all('http' not in q for q in queries))

    def test_candidate_list_has_no_count_condition_and_url_is_optional(self):
        rows = candidates()
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'c.csv'
            path.write_text('No,店舗名,ホテル名,エリア番号,ジャンル,優先して調べるサイト,参考URL,備考\n'
                            '7,テストラウンジ,,3,ラウンジ,,,\n', encoding='utf-8')
            self.assertEqual(candidates(path)[0]['参考URL'], '')
            path.write_text('No,店舗名,ホテル名,エリア番号,ジャンル,優先して調べるサイト,参考URL,備考\n'
                            '1,テスト,,15,ラウンジ,,,\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                candidates(path)  # only the existing fourteen areas


ROWS = [
    {'No': '1', '店舗名': 'テストラウンジ', 'ホテル名': 'テストホテル東京', 'エリア番号': '2', 'ジャンル': 'ラウンジ',
     '優先して調べるサイト': '一休.com', '参考URL': 'https://restaurant.ikyu.com/100001/', '備考': ''},
    {'No': '2', '店舗名': 'テストフレンチ', 'ホテル名': '', 'エリア番号': '2', 'ジャンル': 'フレンチ', '優先して調べるサイト': '',
     '参考URL': '', '備考': ''},
    {'No': '3', '店舗名': 'テストカフェ', 'ホテル名': '', 'エリア番号': '5', 'ジャンル': 'カフェ', '優先して調べるサイト': '',
     '参考URL': '', '備考': ''},
]


class ProgressTests(Temp):
    def setUp(self):
        super().setUp()
        self.research = self.dir / 'research.json'
        data = research.empty()
        research.save(data, self.research)
        patches = [patch.object(research, 'RESEARCH', self.research), patch.object(research, 'RUN', self.dir / 'run'),
                   patch.object(research, 'candidates', lambda path=None: copy.deepcopy(ROWS))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def visit(self, url, at='2026-11-12T10:00:00+09:00'):
        with self.run.update() as state:
            state['visits'].append({'url': url, 'final_url': url, 'at': at, 'via': 'browser'})

    def plan(self, url='https://www.example-hotel.co.jp/at/', **values):
        return {'plan_name': '冬のアフタヌーンティー', 'price_yen': 7500, 'source_url': url, **values}

    def test_queue_starts_with_unresearched_and_skips_excluded_genres(self):
        q = research.queue(research.load(self.research), rows=ROWS)
        self.assertEqual([t['key'] for t in q['tasks'] if t['kind'] == 'unresearched'], ['c1', 'c3'])
        self.assertEqual(q['counts']['excluded_genre_rows'], 1)
        first = q['tasks'][0]
        self.assertIn('テストラウンジ テストホテル東京 アフタヌーンティー', first['queries'])
        self.assertEqual(first['reference_url'], 'https://restaurant.ikyu.com/100001/')  # a hint, not a required page

    def test_record_saves_progress_and_next_run_resumes_from_the_next_unresearched_shop(self):
        url = 'https://www.example-hotel.co.jp/at/'
        self.visit(url)
        result = research.record({'key': 'c1', 'status': 'plan_confirmed', 'urls': [url],
                                  'shop': {'station': '有楽町駅／日比谷駅／有楽町駅', 'plans': [self.plan(url)]}},
                                 run=self.run, rows=ROWS)
        self.assertEqual(result['saved_plans'], 1)
        data = research.load(self.research)
        shop = data['shops'][0]
        # The official page differs from the reference URL in the list; the shop is still kept.
        self.assertEqual(shop['id'], 'c1')
        self.assertEqual(shop['station'], '有楽町駅／日比谷駅')
        self.assertEqual(shop['plans'][0]['checked_at'], '2026-11-12T10:00:00+09:00')  # the reading time
        # A new run keeps the progress and starts from the next unresearched row, not from No.1.
        self.run.start(limits())
        with patch.object(research, 'settings', lambda: limits()):
            started = research.begin(run=self.run)
        self.assertEqual(started['next'][0]['key'], 'c3')
        self.assertEqual(len(research.load(self.research)['shops']), 1)

    def test_unread_pages_and_guessed_values_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'read_in_this_run'):
            research.record({'key': 'c1', 'status': 'plan_confirmed', 'shop': {'plans': [self.plan()]}},
                            run=self.run, rows=ROWS)
        self.visit('https://www.example-hotel.co.jp/at/')
        for bad in ({'price_yen': '7,500円'}, {'start': '12/1'}, {'notes': 'guess'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                research.record({'key': 'c1', 'status': 'plan_confirmed', 'shop': {'plans': [self.plan(**bad)]}},
                                run=self.run, rows=ROWS)
        with self.assertRaisesRegex(ValueError, 'station'):
            research.record({'key': 'c1', 'status': 'plan_confirmed',
                             'shop': {'station': '有楽町駅 徒歩3分', 'plans': [self.plan()]}}, run=self.run, rows=ROWS)

    def test_failure_is_recorded_with_reason_and_is_not_a_confirmation_or_no_offer(self):
        url = 'https://www.example-hotel.co.jp/at/'
        self.visit(url)
        research.record({'key': 'c1', 'status': 'plan_confirmed', 'shop': {'plans': [self.plan(url)]}}, run=self.run, rows=ROWS)
        research.record({'key': 'c1', 'status': 'failed', 'reason': 'HTTP_403', 'note': '一休.comが403'},
                        run=self.run, rows=ROWS)
        data = research.load(self.research)
        self.assertEqual(len(data['shops'][0]['plans']), 1)  # earlier confirmed plan is kept
        entry = data['progress']['entries']['c1']
        self.assertEqual((entry['status'], entry['reason']), ('failed', 'HTTP_403'))
        self.assertEqual(entry['confirmed_at'], '2026-11-12T10:00:00+09:00')
        research.record({'key': 'c3', 'status': 'failed', 'reason': 'robots_txt_unavailable'}, run=self.run, rows=ROWS)
        q = research.queue(research.load(self.research), rows=ROWS, now=dt.datetime.now(JST) + dt.timedelta(days=7))
        self.assertIn('c3', [t['key'] for t in q['tasks'] if t['kind'] == 'retry'])
        q = research.queue(research.load(self.research), rows=ROWS, now=dt.datetime.now(JST))
        self.assertNotIn('c3', [t['key'] for t in q['tasks'] if t['kind'] in ('unresearched', 'retry')])

    def test_recheck_is_managed_apart_from_unresearched(self):
        url = 'https://www.example-hotel.co.jp/at/'
        self.visit(url, at='2026-10-01T10:00:00+09:00')
        research.record({'key': 'c1', 'status': 'plan_confirmed', 'shop': {'plans': [self.plan(url)]}}, run=self.run,
                        rows=ROWS, now=dt.datetime(2026, 10, 1, 11, tzinfo=JST))
        q = research.queue(research.load(self.research), rows=ROWS, now=dt.datetime(2026, 11, 12, tzinfo=JST))
        kinds = {t['key']: t['kind'] for t in q['tasks'] if t.get('key')}
        self.assertEqual(kinds['c1'], 'recheck')
        self.assertEqual(kinds['c3'], 'unresearched')
        self.assertLess([t['key'] for t in q['tasks']].index('c3'), [t['key'] for t in q['tasks']].index('c1'))

    def test_shop_outside_the_list_needs_genre_area_and_is_matched_by_name(self):
        url = 'https://www.other-hotel.example/lounge/'
        self.visit(url)
        with self.assertRaisesRegex(ValueError, 'genre'):
            research.record({'status': 'plan_confirmed', 'shop': {'name': '新ラウンジ', 'area_no': 3, 'plans': [self.plan(url)]}},
                            run=self.run, rows=ROWS)
        result = research.record({'status': 'plan_confirmed', 'shop': {'name': '新ラウンジ', 'hotel_name': '新ホテル東京',
                                  'area_no': 3, 'genre': 'ロビーラウンジ', 'plans': [self.plan(url)]}}, run=self.run, rows=ROWS)
        self.assertTrue(result['key'].startswith('x-'))
        # The same venue written differently in the owner's list resolves to that list row.
        result = research.record({'status': 'plan_confirmed', 'shop': {'name': 'テストホテル東京 / テストラウンジ（2F）',
                                  'area_no': 2, 'genre': 'ラウンジ', 'plans': [self.plan(url)]}}, run=self.run, rows=ROWS)
        self.assertEqual(result['key'], 'c1')
        excluded = research.record({'status': 'plan_confirmed', 'shop': {'name': '中国料理 テスト', 'area_no': 3,
                                    'genre': '中国料理', 'plans': [self.plan(url)]}}, run=self.run, rows=ROWS)
        self.assertEqual(excluded['status'], 'excluded_genre')
        outside = research.record({'status': 'plan_confirmed', 'shop': {'name': '横浜ラウンジ', 'area_no': 15,
                                   'genre': 'ラウンジ', 'plans': [self.plan(url)]}}, run=self.run, rows=ROWS)
        self.assertEqual(outside['status'], 'out_of_area')
        names = [s['name'] for s in research.load(self.research)['shops']]
        self.assertEqual(sorted(names), ['テストラウンジ', '新ラウンジ'])

    def test_plan_with_personal_data_is_not_saved_or_logged(self):
        url = 'https://www.example-hotel.co.jp/at/'
        self.visit(url)
        result = research.record({'key': 'c1', 'status': 'plan_confirmed',
                                  'shop': {'plans': [self.plan(url, menu='連絡先 person@example.test')]}}, run=self.run, rows=ROWS)
        self.assertEqual(result['excluded_sensitive_plans'], 1)
        self.assertNotIn('person@example.test', self.research.read_text())


class MigrationTests(unittest.TestCase):
    def test_old_list_url_data_is_kept_by_name_and_dates_are_unchanged(self):
        old = {'schema_version': 1, 'generated_at': '2026-11-09T07:19:58+09:00',
               'period': {'start': '2026-11-09', 'end': '2026-12-19'},
               'shops': [{'name': 'テストホテル東京 / テストラウンジ', 'area_no': 2, 'list_url': None, 'plans': [
                   {'plan_name': 'A', 'checked_at': '2026-11-07T18:26:50+09:00', 'source_url': 'https://x.example/a'}]},
                         {'name': 'リスト外ラウンジ', 'area_no': 3, 'list_url': 'https://y.example/', 'plans': [
                   {'plan_name': 'B', 'checked_at': '2026-11-08T10:00:00+09:00', 'source_url': 'https://y.example/b'}]}]}
        new = research.migrate(old, rows=ROWS)
        self.assertEqual([s['id'] for s in new['shops']][0], 'c1')
        self.assertEqual(new['shops'][1]['origin'], 'explore')
        self.assertEqual([p['checked_at'] for s in new['shops'] for p in s['plans']],
                         ['2026-11-07T18:26:50+09:00', '2026-11-08T10:00:00+09:00'])


if __name__ == '__main__':
    unittest.main()
