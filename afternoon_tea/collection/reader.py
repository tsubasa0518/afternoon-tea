"""Anonymous, robots-first GET reader. Responses exist only in memory."""
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from afternoon_tea.collection.transport import ReadOnlyTransport, ForbiddenOperation, check_scope
USER_AGENT = 'TokyoAfternoonTeaResearch/0.2 (+public research; no login; contact via GitHub issue)'
MAX_BYTES = 800000
RESEARCH_SECONDS = 1500
MAX_REQUESTS = 200
SHOP_SECONDS = 60
INTERVAL = 3.0
CHALLENGE = ('captcha', 'verify you are human', 'access denied', 'アクセスが制限')


class Reader:
    """Every request waits INTERVAL seconds (or the robots crawl-delay)."""

    def __init__(self, delay=INTERVAL, timeout=15.0, max_requests=MAX_REQUESTS, seconds=RESEARCH_SECONDS):
        self.deadline = time.monotonic() + seconds
        self.delay = delay
        self.timeout = timeout
        self.max_requests = max_requests
        self.count = 0
        self.last_request = 0.0
        self.robots = {}
        self.robots_cache = {}
        self.blocked_hosts = set()
        self.transport = ReadOnlyTransport()

    def _wait(self, host):
        robots = self.robots.get(host)
        delay = max(self.delay, (robots.crawl_delay(USER_AGENT) or robots.crawl_delay('*') or 0) if robots else 0)
        wait = max(0, delay - (time.monotonic() - self.last_request))
        if self.count >= self.max_requests:
            raise RuntimeError('request_budget_exhausted')
        if time.monotonic() + wait >= self.deadline:
            raise RuntimeError('research_budget_exhausted')
        if wait:
            time.sleep(wait)
        self.last_request = time.monotonic()
        self.count += 1

    def _get(self, url, list_url, limit):
        headers = {'User-Agent': USER_AGENT, 'Accept-Language': 'ja,en;q=0.8'}
        timeout = min(self.timeout, max(0.01, self.deadline - time.monotonic()))
        with self.transport.open(url, timeout=timeout, headers=headers, list_url=list_url) as response:
            if response.geturl() != url:
                raise ForbiddenOperation('redirect_blocked_before_follow')
            raw = response.read(limit + 1)
            if len(raw) > limit:
                raise RuntimeError('page_too_large')
            return response, raw

    def robots_allows(self, url, list_url):
        host = urlsplit(url).hostname
        if host not in self.robots:
            if host not in self.robots_cache:
                robots_url = 'https://' + host + '/robots.txt'
                try:
                    self._wait(host)
                    (_, body) = self._get(robots_url, None, 200000)
                    # Only rules are cached, not comments, sitemaps or page bodies.
                    directives = {'user-agent', 'allow', 'disallow', 'crawl-delay', 'request-rate'}
                    lines = []
                    for raw_line in body.decode('utf-8', errors='replace').splitlines():
                        # A comment is ignored by RobotFileParser; it is not a group boundary.
                        if raw_line.lstrip().startswith('#'):
                            continue
                        line = raw_line.split('#', 1)[0].strip()
                        if not line or line.partition(':')[0].strip().lower() in directives:
                            lines.append(line)
                    self.robots_cache[host] = lines
                except (HTTPError, URLError, OSError, ForbiddenOperation, RuntimeError) as error:
                    if isinstance(error, RuntimeError) and str(error).endswith('budget_exhausted'):
                        raise
                    # A refusal/unknown result is cached too: no retry this week.
                    self.robots_cache[host] = None
                    if isinstance(error, HTTPError) and error.code in (403, 429):
                        self.blocked_hosts.add(host)
            lines = self.robots_cache[host]
            parser = RobotFileParser()
            if lines is not None:
                parser.parse(lines)
            self.robots[host] = parser if lines is not None else None
        robots = self.robots[host]
        return robots is not None and robots.can_fetch(USER_AGENT, url)

    def fetch(self, url, list_url):
        """Return decoded HTML of `url`, which must be inside `list_url`'s shop scope."""
        check_scope(url, list_url)
        host = urlsplit(url).hostname
        if host in self.blocked_hosts:
            raise RuntimeError('host_stopped_this_week')
        if not self.robots_allows(url, list_url):
            raise RuntimeError('robots_disallowed_or_unknown')
        self._wait(host)
        try:
            (response, raw) = self._get(url, list_url, MAX_BYTES)
        except HTTPError as error:
            if error.code in (403, 429):
                self.blocked_hosts.add(host)
            raise RuntimeError('HTTP_' + str(error.code)) from error
        if 'text/html' not in response.headers.get('Content-Type', '').lower():
            raise RuntimeError('not_html')
        text = raw.decode(response.headers.get_content_charset() or 'utf-8', errors='replace')
        if any(marker in text.lower() for marker in CHALLENGE):
            self.blocked_hosts.add(host)
            raise RuntimeError('access_challenge')
        from afternoon_tea.publication.site import scan
        scan(text.encode())
        return text
