"""Anonymous GET-only public-document transport. No cookies, forms, or redirects."""
import re
from urllib.parse import urlsplit, unquote
from urllib.request import Request, HTTPRedirectHandler, build_opener


class ForbiddenOperation(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ForbiddenOperation("redirect_blocked_before_follow")


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
    def __init__(self, communication_audit=None):
        self.audit = []
        if communication_audit is None:
            from .communication_audit import CommunicationAudit
            import uuid
            communication_audit=CommunicationAudit(uuid.uuid4().hex)
        self.communication_audit = communication_audit
        self.last_request_id = None
        self.opener = build_opener(NoRedirect())  # no CookieProcessor, no credentials

    def open(self, url, timeout=15, headers=None, method="GET"):
        request_id=None
        journal=self.communication_audit
        try:
            check_url(url, method)
            if headers and any(k.lower() not in ("user-agent", "accept-language", "accept") for k in headers):
                raise ForbiddenOperation("credentials_forbidden")
            if journal:
                request_id=journal.begin(url,method);self.last_request_id=request_id
            response=self.opener.open(Request(url, headers=headers or {}, method="GET"), timeout=timeout)
            if journal:
                journal.finish(request_id,"http_success",http_status=response.status)
            return response
        except ForbiddenOperation as error:
            self.audit.append({"method": method, "status": "blocked", "reason": str(error).split(":",1)[0]})
            if journal:
                if request_id is not None:journal.finish(request_id,"forbidden",reason=str(error).split(":",1)[0])
                else:journal.decision(url,str(error).split(":",1)[0],violation=True,method=method)
            raise
        except Exception as error:
            if journal and request_id is not None:
                journal.finish(request_id,"http_failed",http_status=getattr(error,"code",None),reason=type(error).__name__)
            raise
