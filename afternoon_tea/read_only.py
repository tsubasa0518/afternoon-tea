"""Anonymous GET-only public-document transport. No cookies, forms, or redirects."""
import re
from urllib.parse import urlsplit, unquote
from urllib.request import Request, HTTPRedirectHandler, build_opener


class ForbiddenOperation(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ForbiddenOperation("redirect_blocked_before_follow: " + newurl)


def check_url(url, method="GET"):
    if method != "GET":
        raise ForbiddenOperation("only_GET_allowed")
    p = urlsplit(url)
    if (p.scheme != "https" or p.username or p.password or p.port not in (None, 443)
            or p.fragment or any(c.isspace() for c in url) or "\\" in url):
        raise ForbiddenOperation("unsafe_URL")
    host = p.hostname
    path = unquote(unquote(p.path)).lower()
    if re.search(r"(?:checkout|payment|purchase|confirm|cancel|submit|order|booking|hold|waitlist|login|signup|account|session)", path):
        raise ForbiddenOperation("transaction_or_session_URL")
    # Queries are deliberately rejected: booking dates/party sizes/actions cannot be sent.
    if p.query:
        raise ForbiddenOperation("query_not_allowed")
    if host not in {"restaurant.ikyu.com", "tabelog.com", "tablecheck.com", "www.tablecheck.com"}:
        raise ForbiddenOperation("host_not_allowed")
    if path == "/robots.txt":
        return
    patterns = {
        "restaurant.ikyu.com": r"/(?:\d+(?:/plan\d+)?/?|t/[^?]+|area/[^?]+|s-tokyo/)",
        "tabelog.com": r"/tokyo/(?:a\d+/)*(?:\d+/(?:party/(?:\d+/)?)?|rstlst/[^?]*)",
        "tablecheck.com": r"/(?:ja|en)/(?:shops/[a-z0-9_-]+/reserve|[a-z0-9_-]+)/?",
        "www.tablecheck.com": r"/(?:ja|en)/(?:shops/[a-z0-9_-]+/reserve|[a-z0-9_-]+)/?",
    }
    if not re.fullmatch(patterns[host], path):
        raise ForbiddenOperation("public_document_path_not_allowlisted")


class ReadOnlyTransport:
    def __init__(self):
        self.audit = []
        self.opener = build_opener(NoRedirect())  # no CookieProcessor, no credentials

    def open(self, url, timeout=15, headers=None, method="GET"):
        try:
            check_url(url, method)
            if headers and any(k.lower() in ("cookie", "authorization") for k in headers):
                raise ForbiddenOperation("credentials_forbidden")
            return self.opener.open(Request(url, headers=headers or {}, method="GET"), timeout=timeout)
        except ForbiddenOperation as error:
            self.audit.append({"url": url, "method": method, "status": "blocked", "reason": str(error)})
            raise
