"""Collect official public documents for Claude to read, never infer published plans.

Uses the unchanged GET-only, robots-first Browser. Documents and the honest
coverage report stay in .staging; only Claude's reviewed facts enter site JSON.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from .master import ROOT
from .read_only import check_url, ForbiddenOperation
from .research import Browser

AT = re.compile(r'アフタ[ー]?ヌーン[・\s]?ティー|afternoon[\s_/-]*tea', re.I)
TOPIC = re.compile(r'メニュー|ラウンジ|レストラン|飲食|加盟|ホテル一覧|ニュース|新着|プレス|menu|lounge|restaurant|dining|news|press|member|hotel-list', re.I)
ACTION = re.compile(r'予約|空席|申し込|購入|注文|ログイン|問い合わせ|お問い合わせ|reserve|reservation|contact|register|sign.?in|book\b', re.I)
ASSET = re.compile(r'\.(?:pdf|jpe?g|png|gif|svg|webp|zip|mp4|css|js)$', re.I)


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []
        self.links = []
        self.anchor = None
        self.title = []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.hidden += 1
        if tag == 'title':
            self.in_title = True
        if tag == 'a' and not self.hidden:
            attrs = dict(attrs)
            self.anchor = [attrs.get('href', ''), [attrs.get('title', ''), attrs.get('aria-label', '')]]
        if tag == 'img' and self.anchor and not self.hidden:
            self.anchor[1].append(dict(attrs).get('alt', ''))

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript') and self.hidden:
            self.hidden -= 1
        if tag == 'title':
            self.in_title = False
        if tag == 'a' and self.anchor:
            self.links.append((self.anchor[0], ' '.join(self.anchor[1]).strip()))
            self.anchor = None

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())
            if self.anchor:
                self.anchor[1].append(data.strip())
            if self.in_title:
                self.title.append(data.strip())


def links(raw, base, public_hosts, path_prefix='/'):
    """Rank observed document anchors; never grant an external host access."""
    p = Page(); p.feed(raw)
    internal, candidates, rejected = {}, [], []
    for href, label in p.links:
        if not href or href.startswith(('#', 'mailto:', 'tel:', 'javascript:')):
            continue
        u = urlsplit(urljoin(base, href))
        url = urlunsplit((u.scheme, u.netloc, u.path or '/', u.query, ''))
        words = label + ' ' + unquote(u.path)
        if ACTION.search(words) or ASSET.search(u.path):
            continue
        rank = 0 if AT.search(words) else 1 if TOPIC.search(words) else 2
        if rank == 2 and AT.search(unquote(urlsplit(base).path) + ' '.join(p.title)) and re.search(r'詳しく|詳細|detail|/plan/|/offer/', words, re.I):
            rank = 1
        if u.hostname != urlsplit(base).hostname:
            # A directory may discover venues. These are hints, NOT approved
            # destinations, verified stores, or permission to contact a service.
            if rank < 2:
                candidates.append({'url': url, 'label': label, 'status': 'unverified_external_candidate'})
            continue
        if rank == 2 or not (u.path or '/').startswith(path_prefix):
            continue
        try:
            check_url(url, public_hosts=public_hosts)
        except (ForbiddenOperation, ValueError) as error:
            rejected.append({'url': url, 'reason': str(error)})
            continue
        internal[url] = min(internal.get(url, (rank, label)), (rank, label))
    return p, sorted(((r, u, label) for u, (r, label) in internal.items())), candidates, rejected


def collect(sources, areas, directory, browser, seconds=1200, max_depth=4, clock=time.monotonic):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    deadline = clock() + seconds
    report = {'started_at': started, 'sources': [], 'areas': [], 'pages': [],
              'attempts': [], 'external_candidates': [], 'rejected_links': [],
              'verified_shops': 0, 'verified_plans': 0, 'verified_menus': 0,
              'note': 'Documents/candidates are not confirmed plans. Claude must read evidence and record accepted facts separately.'}
    # Round robin: every area/source gets a chance before one large site can
    # consume the budget. Within each source AT anchors outrank navigation.
    queues, seen = [], set()
    forbidden_stop = False
    for source in sources:
        check_url(source['url'], public_hosts=browser.transport.public_hosts)
        report['sources'].append(dict(source, fetched_pages=0, at_text_pages=0))
        queues.append([(0, source['url'], 0, None)])
    while not forbidden_stop and any(queues) and clock() < deadline and browser.count < browser.max_requests:
        for i, queue in enumerate(queues):
            if not queue or clock() >= deadline or browser.count >= browser.max_requests:
                continue
            queue.sort(key=lambda item: (item[0], item[2], item[1]))
            rank, url, depth, parent = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            source = report['sources'][i]
            before = browser.count
            attempt = {'url': url, 'source_id': source['id'], 'depth': depth, 'parent': parent,
                       'checked_at': dt.datetime.now(dt.timezone.utc).isoformat()}
            try:
                raw = browser.fetch(url)
                page, found, candidates, rejected = links(raw, url, browser.transport.public_hosts, source.get('path_prefix', '/'))
                digest = hashlib.sha256(raw.encode()).hexdigest()
                filename = digest + '.txt'
                text = '\n'.join(page.parts)
                (directory / filename).write_text(text, encoding='utf-8')
                source['fetched_pages'] += 1
                source['at_text_pages'] += bool(AT.search(text))
                report['pages'].append({'url': url, 'source_id': source['id'], 'checked_at': attempt['checked_at'],
                                        'title': ' '.join(page.title), 'text_file': filename, 'sha256': digest,
                                        'has_at_text': bool(AT.search(text)),
                                        'warning': 'AT text can be navigation, not plan confirmation.'})
                report['external_candidates'].extend(dict(c, found_on=url, source_id=source['id']) for c in candidates)
                report['rejected_links'].extend(rejected)
                if depth < max_depth:
                    queued = {item[1] for item in queue}
                    queue.extend((r, u, depth + 1, url) for r, u, label in found if u not in seen and u not in queued)
                else:
                    source.setdefault('unvisited_links', []).extend(u for r, u, label in found if u not in seen)
                attempt['status'] = 'fetched'
            except ForbiddenOperation as error:
                attempt.update(status="forbidden", error=str(error))
                forbidden_stop = True
            except (RuntimeError, ValueError, OSError) as error:
                attempt.update(status='failed', error=str(error))
            attempt['http_requests'] = browser.count - before
            report['attempts'].append(attempt)
            if forbidden_stop:
                break
            host = urlsplit(url).hostname
            if host in browser.blocked_hosts or (host in browser.robots and browser.robots[host] is None):
                queue.clear()
    for i, source in enumerate(report['sources']):
        source['pending_urls'] = list(dict.fromkeys(item[1] for item in queues[i] if item[1] not in seen))
        source['attempted_pages'] = sum(a['source_id'] == source['id'] for a in report['attempts'])
    for area in areas:
        existing = [s for s in report['sources'] if area['no'] in s['areas'] and s['purpose'] == 'existing']
        discovery = [s for s in report['sources'] if area['no'] in s['areas'] and s['purpose'] == 'discovery']
        report['areas'].append({'area_no': area['no'], 'area': area['name'],
            'existing_attempts': sum(s['attempted_pages'] for s in existing),
            'discovery_attempts': sum(s['attempted_pages'] for s in discovery),
            'status': 'unreviewed', 'new_shops_confirmed': 0,
            'remaining': 'Read area/station-specific evidence; source access alone is not completed area exploration.'})
    report.update(finished_at=dt.datetime.now(dt.timezone.utc).isoformat(), http_requests=browser.count,
                  browser_errors=browser.errors, network_events=getattr(browser, 'network_events', []),
                  communication_audit=browser.communication_audit.snapshot(),
                  stop_reason='forbidden_operation' if forbidden_stop else 'budget_or_deadline' if any(queues) else 'queue_finished')
    (directory / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, default=ROOT / 'data/official_sources.json')
    parser.add_argument('--output', type=Path, default=ROOT / '.staging/official-research')
    parser.add_argument('--seconds', type=float, default=1200)
    parser.add_argument('--max-requests', type=int, default=280)
    args = parser.parse_args()
    sources = json.loads(args.sources.read_text(encoding='utf-8'))['sources']
    areas = json.loads((ROOT / 'data/store_master.json').read_text(encoding='utf-8'))['areas']
    hosts = {urlsplit(s['url']).hostname for s in sources}
    from .communication_audit import CommunicationAudit
    import uuid
    audit = CommunicationAudit(uuid.uuid4().hex, args.output / ('audit-' + uuid.uuid4().hex + '.jsonl'))
    report = collect(sources, areas, args.output,
                     Browser(public_hosts=hosts, max_requests=args.max_requests, audit=audit), args.seconds)
    print(json.dumps({'report': str(args.output / 'report.json'), 'pages': len(report['pages']),
                      'requests': report['http_requests'], 'verified_plans': 0,
                      'stop_reason': report['stop_reason']}, ensure_ascii=False))
    if report['stop_reason'] == 'forbidden_operation':
        raise SystemExit(2)


if __name__ == '__main__':
    main()
