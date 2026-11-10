"""Anonymous, robots-first public document reader shared by current collectors."""
import hashlib
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request
from urllib.robotparser import RobotFileParser
from afternoon_tea.collection.transport import ReadOnlyTransport, ForbiddenOperation

USER_AGENT = "TokyoAfternoonTeaResearch/0.1 (+public research; no login; contact via GitHub issue)"
MAX_BYTES = 800_000


class Browser:
    def __init__(self, delay=2.0, timeout=15.0, max_requests=400, audit=None, public_hosts=()):
        self.delay = delay
        self.timeout = timeout
        self.max_requests = max_requests
        self.count = 0
        self.last_request = {}
        self.robots = {}
        self.errors = []
        self.transport = ReadOnlyTransport(audit, public_hosts=public_hosts)
        self.communication_audit = self.transport.communication_audit
        self.blocked_hosts = set()
        self.network_events = []

    def _rate_limit(self, host):
        elapsed = time.monotonic() - self.last_request.get(host, 0)
        robots = self.robots.get(host)
        delay = max(self.delay, (robots.crawl_delay(USER_AGENT) or robots.crawl_delay("*") or 0) if robots else 0)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self.last_request[host] = time.monotonic()

    def _open(self, url):
        if self.count >= self.max_requests:
            raise RuntimeError("request_budget_exhausted")
        host = urlsplit(url).hostname
        self._rate_limit(host)
        self.count += 1
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.8"})
        with self.transport.open(url, timeout=self.timeout, headers=dict(request.header_items())) as response:
            final_url = response.geturl()
            if urlsplit(final_url).hostname != host:
                raise RuntimeError("cross_host_redirect")
            self.network_events.append({"url": url, "stage": "document", "http_status": response.status, "result": "received"})
            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" not in content_type:
                raise RuntimeError("not_html")
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise RuntimeError("page_too_large")
            charset = response.headers.get_content_charset() or "utf-8"
            text = raw.decode(charset, errors="replace")
            if any(marker in text.lower() for marker in ("captcha", "verify you are human", "access denied", "アクセスが制限")):
                self.blocked_hosts.add(host)
                self.network_events.append({"url": url, "stage": "document", "result": "access_challenge_stop_host",
                                            "matched_markers": [m for m in ("captcha", "verify you are human", "access denied", "アクセスが制限") if m in text.lower()]})
                raise RuntimeError("access_challenge_stop_host")
            return text

    def fetch(self,url):
        try:
            value=self._fetch(url)
            if self.communication_audit:
                from afternoon_tea.collection.audit import identity
                self.last_document=self.communication_audit.record('document',resource=identity(url),status='success',request_id=self.transport.last_request_id,page_sha256=hashlib.sha256(value.encode()).hexdigest())
            return value
        except Exception as e:
            if self.communication_audit:self.communication_audit.decision(url,str(e).split(':',1)[0] if isinstance(e,ForbiddenOperation) else type(e).__name__ if not isinstance(e,RuntimeError) else str(e),violation=isinstance(e,ForbiddenOperation))
            raise

    def _fetch(self, url):
        try:
            from afternoon_tea.collection.transport import check_url
            check_url(url, public_hosts=self.transport.public_hosts)
        except ForbiddenOperation as error:
            from afternoon_tea.collection.audit import identity
            self.errors.append({"resource": identity(url), "error": str(error).split(":",1)[0], "status": "blocked"})
            raise
        host = urlsplit(url).hostname
        if host in self.blocked_hosts:
            raise RuntimeError("host_stopped_after_access_denial")
        if not host or urlsplit(url).scheme != "https":
            raise ValueError("HTTPS_URL_required")
        # robots.txt failures are treated conservatively: no page fetch.
        if host not in self.robots:
            robots_url = "https://" + host + "/robots.txt"
            try:
                if self.count >= self.max_requests:
                    raise RuntimeError("request_budget_exhausted")
                self._rate_limit(host)
                self.count += 1
                req = Request(robots_url, headers={"User-Agent": USER_AGENT})
                with self.transport.open(robots_url, timeout=self.timeout, headers=dict(req.header_items())) as response:
                    self.network_events.append({"url": robots_url, "stage": "robots", "http_status": response.status, "result": "received"})
                    if response.geturl() != robots_url:
                        raise RuntimeError("robots_redirect")
                    body = response.read(200_001)
                    if len(body) > 200_000:
                        raise RuntimeError("robots_too_large")
                robots = RobotFileParser()
                robots.parse(body.decode("utf-8", errors="replace").splitlines())
                self.robots[host] = robots
            except ForbiddenOperation as error:
                self.robots[host] = None
                self.network_events.append({"url": robots_url, "stage": "robots", "result": "failed", "error": str(error)})
                raise
            except (HTTPError, URLError, OSError, RuntimeError) as error:
                self.robots[host] = None
                self.network_events.append({"url": robots_url, "stage": "robots", "result": "failed",
                                            "http_status": getattr(error, "code", None), "error": str(error)})
                self.errors.append({"url": robots_url, "error": type(error).__name__ + ": " + str(error)})
        robots = self.robots[host]
        if robots is None or not robots.can_fetch(USER_AGENT, url):
            self.network_events.append({"url": url, "stage": "robots_decision",
                                        "result": "unknown" if robots is None else "disallowed"})
            raise RuntimeError("robots_unknown_or_disallowed")
        try:
            return self._open(url)
        except HTTPError as error:
            self.network_events.append({"url": url, "stage": "document", "http_status": error.code, "result": "failed"})
            # Do not circumvent blocks, CAPTCHA or 429. Record instead.
            if error.code in (403, 429):
                self.blocked_hosts.add(host)
            raise RuntimeError("HTTP_" + str(error.code)) from error
