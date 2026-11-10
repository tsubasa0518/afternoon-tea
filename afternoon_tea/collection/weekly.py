"""Ordered, bounded public reading. Responses exist only in memory/stdout."""
import csv
import datetime as dt
import json
from html.parser import HTMLParser
from pathlib import Path
import time
from urllib.parse import quote, urljoin, urlsplit
from afternoon_tea.common import ROOT
from afternoon_tea.collection.reader import Browser
from afternoon_tea.collection.transport import check_url, ForbiddenOperation

SERVICES = ('restaurant.ikyu.com', 'tabelog.com', 'tablecheck.com')
HEADERS = ['No','店名','最寄り駅','エリア番号','ジャンル','予約サイト','予約ページURL','備考']

class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []
        self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style','noscript'):
            self.hidden += 1
        if tag == 'a':
            self.links.append(dict(attrs).get('href',''))
    def handle_endtag(self, tag):
        if tag in ('script','style','noscript') and self.hidden:
            self.hidden -= 1
    def handle_data(self, text):
        if not self.hidden and text.strip():
            self.parts.append(text.strip())

def candidates(path=None):
    with Path(path or ROOT/'data/references/user_candidates.csv').open() as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != HEADERS:
            raise ValueError('candidate_columns_invalid')
        rows = list(reader)
    for no, row in enumerate(rows, 1):
        if row['No'] != str(no) or row['エリア番号'] not in {str(n) for n in range(1,15)}:
            raise ValueError('candidate_number_or_area_invalid')
    return rows

def search(browser, row, host):
    raw = browser.fetch('https://www.bing.com/search?q='+quote(row['店名']+' アフタヌーンティー site:'+host))
    page = Page(); page.feed(raw)
    for url in page.links:
        if urlsplit(url).hostname not in (host, 'www.'+host):
            continue
        try:
            check_url(url)
        except (ValueError, RuntimeError):
            continue
        yield url

def collect(rows, review, browser=None, finder=search, seconds=420, clock=time.monotonic):
    """review reads a page and returns completed shop/plans, or None.

    A caller (Claude) confirms concrete plans; HTTP success is never confirmation.
    No response bodies, rejected shop names, queues or resume files are saved.
    """
    browser = browser or Browser(max_requests=150)
    deadline = clock()+seconds
    result = {'shops': [], 'attempted':0, 'abandoned':0, 'blocked_requests':0}
    def available():
        return clock()<deadline and browser.count<browser.max_requests
    for row in rows:  # Always start at No.1; no checkpoint input exists.
        if not available():
            break
        result['attempted'] += 1
        tried=set(); confirmed=None; unsafe=False
        def read(url):
            nonlocal unsafe
            if url in tried or not available():
                return None
            tried.add(url)
            try:
                check_url(url)
                text=browser.fetch(url)
                item=review(row,text,url)
                if item and item.get('plans') and not item.get('pending_urls'):
                    return {**item,'area_no':int(row['エリア番号'])}
            except ForbiddenOperation:
                result['blocked_requests'] += 1
                unsafe=True
            except (ValueError,RuntimeError,OSError):
                pass
            return None
        confirmed=read(row['予約ページURL'])
        if not confirmed and not unsafe:
            original_host=urlsplit(row['予約ページURL']).hostname
            for host in SERVICES:
                if host in (original_host, (original_host or '').removeprefix('www.')) or not available():
                    continue
                try:
                    for url in finder(browser,row,host):
                        confirmed=read(url)
                        if confirmed or unsafe or not available():
                            break
                except ForbiddenOperation:
                    result['blocked_requests'] += 1
                    unsafe=True
                except (ValueError,RuntimeError,OSError):
                    pass
                if confirmed or unsafe:
                    break
        if confirmed:
            result['shops'].append(confirmed)
        else:
            result['abandoned'] += 1
    return result

BUDGET = ROOT/'.staging/weekly-budget'

def begin():
    from .storage import atomic_json, store_lock
    with store_lock(BUDGET):
        atomic_json(BUDGET/'limits.json', {'started_at':time.time(), 'requests':0,
                                         'blocked_hosts':[], 'last_request':{}})
    return {'research_seconds':420, 'max_requests':150, 'starts_at_no':1}

def fetch(url):
    from .storage import atomic_json, store_lock
    with store_lock(BUDGET):
        state = json.loads((BUDGET/'limits.json').read_text())
        elapsed = time.time()-state['started_at']
        if not 0 <= elapsed < 420 or state['requests'] >= 150:
            raise RuntimeError('research_budget_exhausted_publish_collected_results')
        browser = Browser(max_requests=150-state['requests'], timeout=min(15,420-elapsed), seconds=420-elapsed)
        browser.blocked_hosts.update(state['blocked_hosts'])
        # Wall-clock pacing persists across separate CLI requests.
        for host, value in state['last_request'].items():
            browser.last_request[host] = time.monotonic()-max(0,time.time()-value)
        try:
            check_url(url)
            raw = browser.fetch(url)
            page = Page(); page.feed(raw)
            links=[]
            for href in page.links:
                target=urljoin(url,href)
                try:
                    check_url(target)
                except (ValueError,RuntimeError):
                    continue
                if target not in links:
                    links.append(target)
            return {'url':url, 'links':links, 'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),
                    'text':'\n'.join(page.parts)}
        finally:
            state['requests'] += browser.count
            state['blocked_hosts'] = sorted(browser.blocked_hosts)
            state['last_request'].update({host:time.time()-max(0,time.monotonic()-value)
                                          for host,value in browser.last_request.items()})
            atomic_json(BUDGET/'limits.json',state)
