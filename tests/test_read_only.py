"""No live requests: safety checks use a mocked opener exclusively."""
import unittest
from unittest.mock import Mock
from afternoon_tea.collection.transport import ReadOnlyTransport, ForbiddenOperation, check_url, NoRedirect

class SafetyTests(unittest.TestCase):

    def setUp(self):
        self.transport = ReadOnlyTransport()
        self.transport.opener = Mock()

    def test_methods_never_reach_network(self):
        for method in ('POST', 'PUT', 'PATCH', 'DELETE', 'HEAD'):
            with self.assertRaises(ForbiddenOperation):
                self.transport.open('https://restaurant.ikyu.com/112520/', method=method)
        self.transport.opener.open.assert_not_called()
        self.assertEqual(len(self.transport.audit), 5)

    def test_transaction_links_never_followed(self):
        for url in ('https://restaurant.ikyu.com/112520/confirm/',
             'https://tabelog.com/booking/hold',
             'https://www.tablecheck.com/checkout',
             'https://www.tablecheck.com/ja/shops/vava/reserve?date=20261109',
             'https://tabelog.com/payment',
             'https://restaurant.ikyu.com/%2563onfirm/'):
            with self.assertRaises(ForbiddenOperation):
                self.transport.open(url)
        self.transport.opener.open.assert_not_called()

    def test_no_form_body_or_credentials(self):
        with self.assertRaises(TypeError):
            self.transport.open('https://restaurant.ikyu.com/112520/', data=b'person=test')
        for h in ({'Cookie': 'logged-in'}, {'Authorization': 'token'}):
            with self.assertRaises(ForbiddenOperation):
                self.transport.open('https://restaurant.ikyu.com/112520/', headers=h)
        self.transport.opener.open.assert_not_called()

    def test_redirect_blocked_before_follow(self):
        with self.assertRaises(ForbiddenOperation):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com/payment')

    def test_public_documents_allowed(self):
        for u in ('https://restaurant.ikyu.com/112520/plan12815175/',
             'https://tabelog.com/tokyo/A1302/A130202/13226051/party/232732756/',
             'https://www.tablecheck.com/ja/shops/vava/reserve'):
            check_url(u)

    def test_private_unknown_hosts_blocked(self):
        for u in ('http://127.0.0.1/', 'https://evil.example/', 'https://user:pass@restaurant.ikyu.com/112520/'):
            with self.assertRaises(ForbiddenOperation):
                check_url(u)

    def test_denial_stops_host_without_retry(self):
        from afternoon_tea.collection.documents import Browser
        from urllib.robotparser import RobotFileParser
        from urllib.error import HTTPError
        b = Browser()
        robots = RobotFileParser()
        robots.parse(['User-agent: *', 'Allow: /'])
        b.robots['restaurant.ikyu.com'] = robots
        b._open = Mock(side_effect=HTTPError('https://restaurant.ikyu.com/112520/', 403, 'denied', {}, None))
        with self.assertRaisesRegex(RuntimeError, 'HTTP_403'):
            b.fetch('https://restaurant.ikyu.com/112520/')
        with self.assertRaisesRegex(RuntimeError, 'host_stopped'):
            b.fetch('https://restaurant.ikyu.com/112520/')
        self.assertEqual(b._open.call_count, 1)
