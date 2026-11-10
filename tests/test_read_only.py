"""No live requests: URL checks and the GET reader use mocked openers only."""
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError
from afternoon_tea.collection.reader import Reader
from afternoon_tea.collection.transport import (ReadOnlyTransport, ForbiddenOperation, check_url, check_scope,
                                                NoRedirect, shop_key)
from afternoon_tea.collection.weekly import candidates
from tests.http_fixtures import Response

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

    def test_redirect_size_and_secrets_make_page_unusable(self):
        reader, _ = self.reader({IKYU: 'x' * 900000})
        with self.assertRaisesRegex(RuntimeError, 'page_too_large'):
            reader.fetch(IKYU, IKYU)
        reader, _ = self.reader({IKYU: '<p>mail someone@example.com</p>'})
        with self.assertRaisesRegex(ValueError, 'secret_or_personal'):
            reader.fetch(IKYU, IKYU)

    def test_request_budget(self):
        reader, seen = self.reader({IKYU: 'x'})
        reader.max_requests = 1
        with self.assertRaisesRegex(RuntimeError, 'budget_exhausted'):
            reader.fetch(IKYU, IKYU)
        self.assertEqual(len(seen), 1)
