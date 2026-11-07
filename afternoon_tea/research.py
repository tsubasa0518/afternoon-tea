"""Conservative, rate-limited live research discovery (never publishes unverified claims).

This module researches the 14-area master and stores audit evidence. It intentionally
does not turn search snippets or keyword matches into verified reservation plans.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import html
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit
from urllib.request import Request
from urllib.robotparser import RobotFileParser

from .read_only import ReadOnlyTransport, ForbiddenOperation
from .data import create_data
from .master import ROOT, dumps, load_master
from .pipeline import protected_files, staging_directory
from .validation import allowed_url, validate_data

SITES = (
    ("ik", "restaurant.ikyu.com"),
    ("tb", "tabelog.com"),
    ("tc", "tablecheck.com"),
)
USER_AGENT = "TokyoAfternoonTeaResearch/0.1 (+public research; no login; contact via GitHub issue)"
AT_WORDS = ("アフタヌーンティー", "afternoon tea", "Afternoon Tea")
BOOKING_WORDS = ("予約", "空席", "オンライン予約", "ネット予約", "Reserve", "Book")
MAX_BYTES = 800_000


class TextAndLinks(HTMLParser):
    """Collect visible text and hrefs, excluding scripts/styles."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.depth += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth and data.strip():
            self.parts.append(data.strip())


def compact(text):
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def context(text, needle, radius=140):
    index = text.casefold().find(needle.casefold())
    return compact(text[max(0, index - radius):index + len(needle) + radius]) if index >= 0 else ""


def site_url(url, site):
    """Return URL only if it is a direct, valid link for the requested site."""
    if url.startswith("//"):
        url = "https:" + url
    if "bing.com/ck/" in url or "duckduckgo.com/l/" in url:
        return None
    if url.startswith("/"):
        return None
    if urlsplit(url).hostname not in (site, "www." + site):
        return None
    try:
        allowed_url(url)
    except ValueError:
        return None
    return url


class Browser:
    def __init__(self, delay=2.0, timeout=15.0, max_requests=400, audit=None):
        self.delay = delay
        self.timeout = timeout
        self.max_requests = max_requests
        self.count = 0
        self.last_request = {}
        self.robots = {}
        self.errors = []
        self.transport = ReadOnlyTransport(audit)
        self.communication_audit = self.transport.communication_audit
        self.blocked_hosts = set()

    def _rate_limit(self, host):
        elapsed = time.monotonic() - self.last_request.get(host, 0)
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
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
                raise RuntimeError("access_challenge_stop_host")
            return text

    def fetch(self,url):
        try:
            value=self._fetch(url)
            if self.communication_audit:
                from .communication_audit import identity
                self.last_document=self.communication_audit.record('document',resource=identity(url),status='success',request_id=self.transport.last_request_id,page_sha256=hashlib.sha256(value.encode()).hexdigest())
            return value
        except Exception as e:
            if self.communication_audit:self.communication_audit.decision(url,str(e).split(':',1)[0] if isinstance(e,ForbiddenOperation) else type(e).__name__ if not isinstance(e,RuntimeError) else str(e),violation=isinstance(e,ForbiddenOperation))
            raise

    def _fetch(self, url):
        try:
            from .read_only import check_url
            check_url(url)
        except ForbiddenOperation as error:
            from .communication_audit import identity
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
                    if response.geturl() != robots_url:
                        raise RuntimeError("robots_redirect")
                    body = response.read(200_001)
                    if len(body) > 200_000:
                        raise RuntimeError("robots_too_large")
                robots = RobotFileParser()
                robots.parse(body.decode("utf-8", errors="replace").splitlines())
                self.robots[host] = robots
            except ForbiddenOperation:
                raise
            except (HTTPError, URLError, OSError, RuntimeError) as error:
                self.robots[host] = None
                self.errors.append({"url": robots_url, "error": type(error).__name__ + ": " + str(error)})
        robots = self.robots[host]
        if robots is None or not robots.can_fetch(USER_AGENT, url):
            raise RuntimeError("robots_unknown_or_disallowed")
        try:
            return self._open(url)
        except HTTPError as error:
            # Do not circumvent blocks, CAPTCHA or 429. Record instead.
            if error.code in (403, 429):
                self.blocked_hosts.add(host)
            raise RuntimeError("HTTP_" + str(error.code)) from error

    def query(self, shop_name, domain):
        """Bing HTML index is optional; unsupported/blocked results are unresolved."""
        q = quote(shop_name + " アフタヌーンティー site:" + domain)
        search_url = "https://www.bing.com/search?q=" + q
        source = self.fetch(search_url)
        parser = TextAndLinks()
        parser.feed(source)
        found = []
        for item in parser.links:
            candidate = site_url(html.unescape(item), domain)
            if candidate and candidate not in found:
                found.append(candidate)
        return found[:5], search_url


def inspect_page(html_source, url, checked):
    parser = TextAndLinks()
    parser.feed(html_source)
    text = compact(" ".join(parser.parts))
    at_quote = next((context(text, word) for word in AT_WORDS if word.casefold() in text.casefold()), "")
    booking_quote = next((context(text, word) for word in BOOKING_WORDS if word.casefold() in text.casefold()), "")
    prices = re.findall(r"(?:[1-9][0-9]{0,2}(?:,[0-9]{3})+|[1-9][0-9]{3,5})\s*円", text)
    # These are *clues*, never confirmation of a purchasable plan or its final price.
    return {
        "url": url,
        "checked_on": checked,
        "at_excerpt": at_quote,
        "booking_excerpt": booking_quote,
        "price_clues": prices[:8],
        "has_at_text": bool(at_quote),
        "has_booking_text": bool(booking_quote),
        "text_chars": len(text),
        "status": "unverified_evidence_only",
    }


def research_one(browser, shop, checked):
    attempts = []
    evidence = []
    for site_code, domain in SITES:
        try:
            links, search_url = browser.query(shop["master_name"], domain)
            attempts.append({"site": site_code, "stage": "search", "url": search_url,
                             "result_count": len(links), "status": "ok"})
        except (HTTPError, URLError, OSError, RuntimeError, ValueError) as error:
            attempts.append({"site": site_code, "stage": "search", "status": "failed",
                             "error": str(error)})
            continue
        for link in links:
            try:
                raw = browser.fetch(link)
                result = inspect_page(raw, link, checked)
                evidence.append(result)
                attempts.append({"site": site_code, "stage": "page", "url": link, "status": "ok",
                                 "has_at_text": result["has_at_text"]})
                # Look no further *only* after obtaining promising evidence.
                # This is NOT a verified plan: do not add it to site output.
                if result["has_at_text"] and result["has_booking_text"]:
                    return {"attempts": attempts, "evidence": evidence,
                            "status": "requires_plan_review"}
            except (HTTPError, URLError, OSError, RuntimeError, ValueError) as error:
                attempts.append({"site": site_code, "stage": "page", "url": link,
                                 "status": "failed", "error": str(error)})
    return {"attempts": attempts, "evidence": evidence, "status": "unresolved"}


def _checkpoint(output, dataset, audit, today):
    """Atomically retain the latest partial evidence; never write outside .staging."""
    output.mkdir(parents=True, exist_ok=True)
    for name, content in (("data_" + today + ".json", dumps(dataset)),
                          ("audit.json", dumps(audit))):
        target = output / name
        temporary = output / ("." + name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(target)


def run(start=None, max_shops=None, delay=2.0, timeout=15.0, max_requests=400, browser=None):
    protected_files()
    master = load_master()
    dataset = create_data(master, start=start)
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()
    if dataset["period"]["start"] > today:
        raise ValueError("future_research_date_not_allowed")
    if dataset["period"]["start"] != today:
        raise ValueError("research_date_must_be_today_JST")
    browser = browser or Browser(delay=delay, timeout=timeout, max_requests=max_requests)
    dataset["metadata"]["purpose"] = "research"
    run_stamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y%m%dT%H%M%S%f%z")
    output = staging_directory() / ("research-" + today + "-" + run_stamp)
    audit = {"checked_on": today, "period": dataset["period"], "by_shop": {}, "limitations": [],
             "all_tokyo_coverage_verified": False, "final_unverified_candidates": None,
             "candidate_resolution": "not_started", "area_discovery": "not_started",
             "run_id": run_stamp, "attempted_shops": 0, "requests": 0}
    _checkpoint(output, dataset, audit, today)
    count = 0
    attempted_ids = set()
    errors_by_shop = {}
    for area in dataset["areas"]:
        for cat in ("cafe", "hotel", "lux"):
            for shop in area["cats"][cat]["shops"]:
                if max_shops is not None and count >= max_shops:
                    continue
                count += 1
                attempted_ids.add(shop["master_id"])
                result = research_one(browser, shop, today)
                audit["by_shop"][shop["master_id"]] = {"name": shop["master_name"], "area": area["name"],
                                                       **result}
                # Search snippets and page clues are not field-level verification. Preserve
                # the unconfirmed record and distinguish transport/access failures from
                # pages that need human review.
                reasons = [item.get("error") for item in result["attempts"]
                           if item.get("status") == "failed"]
                if result["status"] == "requires_plan_review":
                    error = "予約ページとAT記載の手掛かりあり。期間・各項目の根拠を個別確認できず未確定"
                elif reasons:
                    error = "検索未完了: " + "; ".join(dict.fromkeys(reasons))
                else:
                    error = "指定3サイトで掲載条件を確認できず。除外判定には追加確認が必要"
                shop["research"].update(status="failed", attempted_on=today,
                                        error=error, checked_on=None, evidence={})
                shop["links_note"] = "取得失敗"
                errors_by_shop[shop["master_id"]] = error
                audit["attempted_shops"] = count
                audit["requests"] = browser.count
                audit["transport_errors"] = browser.errors
                _checkpoint(output, dataset, audit, today)
    missing = [shop["name"] for a in dataset["areas"] for cat in a["cats"].values()
               for shop in cat["shops"] if shop["research"]["status"] != "confirmed"]
    unattempted = [shop["master_id"] for a in dataset["areas"] for cat in a["cats"].values()
                   for shop in cat["shops"] if shop["master_id"] not in attempted_ids]
    dataset["notes"]["status"] = (
        f"調査未完了。70店中{count}店を検索試行、予約プランの項目検証済み0店。"
        "検索結果・キーワード一致を確認済みとして扱わない。"
        f"未試行{len(unattempted)}店、未解決・取得失敗を含む未検証{len(missing)}店。"
        "未検証店：" + "／".join(missing))
    dataset["notes"]["pending_candidates"] = copy.deepcopy(master["candidates"])
    dataset["candidates"] = []  # Unverified candidates are NEVER rendered or presented as verified.
    audit["master_shops"] = sum(len(g["shops"]) for a in master["areas"] for g in a["cats"].values())
    audit["attempted_shops"] = count
    audit["confirmed_shops"] = 0
    audit["unverified_shops"] = len(missing)
    audit["failed_shops"] = sum(shop["research"]["status"] == "failed"
                                 for a in dataset["areas"] for cat in a["cats"].values()
                                 for shop in cat["shops"])
    audit["unattempted_shops"] = len(unattempted)
    audit["unattempted_master_ids"] = unattempted
    audit["shop_errors"] = errors_by_shop
    audit["area_status"] = [
        {"no": a["no"], "name": a["name"],
         "master_shops": sum(len(g["shops"]) for g in a["cats"].values()),
         "attempted": sum(s["id"] in attempted_ids for g in a["cats"].values()
                          for s in g["shops"]),
         "confirmed": 0, "coverage": "incomplete"}
        for a in master["areas"]]
    audit["candidate_count_master"] = len(master["candidates"])
    audit["candidate_resolution"] = "unresolved_not_researched"
    audit["area_discovery"] = "not_performed"
    audit["requests"] = browser.count
    audit["transport_errors"] = browser.errors
    audit["limitations"].extend([
        "All-area listings, hotel inventory, opening news, and new-store discovery were not performed.",
        "Master candidates were retained as unresolved; no candidate was confirmed or excluded.",
        "Search-result excerpts and automated text clues are not booking-plan verification.",
        "No verified plan data; therefore no updated HTML can be published.",
    ])
    validate_data(dataset, master)
    protected_files()
    _checkpoint(output, dataset, audit, today)
    return output, audit


def main(argv=None):
    parser = argparse.ArgumentParser(description="Live website discovery; NO publication")
    parser.add_argument("--start", help="JST date YYYY-MM-DD; default today")
    parser.add_argument("--max-shops", type=int, default=None,
                        help="limit for smoke test; omit for all 70 master shops")
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--max-requests", type=int, default=400)
    args = parser.parse_args(argv)
    if args.max_shops is not None and args.max_shops < 1:
        parser.error("--max-shops must be positive")
    if args.delay < 1:
        parser.error("--delay must be >= 1 second")
    path, audit = run(args.start, args.max_shops, args.delay, args.timeout, args.max_requests)
    print(json.dumps({"path": str(path), "attempted": audit["attempted_shops"],
                      "verified": audit["confirmed_shops"], "requests": audit["requests"],
                      "publishable": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
