"""Anonymous GET-only transport and the URL checks shared with the browser.

Only the three reservation sites named in the candidate list are reachable.
A shop's list URL and that same shop's plan detail pages are the only pages
read. No cookies, forms, query strings, credentials or redirects.
"""
import re
from urllib.parse import urlsplit, unquote
from urllib.request import Request, HTTPRedirectHandler, build_opener

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
