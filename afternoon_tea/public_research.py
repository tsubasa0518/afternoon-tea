"""Bounded public-page discovery without search engines or booking interaction."""
import argparse
import datetime as dt
from html.parser import HTMLParser
import json
from pathlib import Path
import time
from urllib.parse import urljoin, urlsplit

from .data import create_data
from .master import ROOT, load_master, dumps
from .pipeline import staging_directory, protected_files
from .research import Browser, inspect_page, TextAndLinks
from .read_only import check_url, ForbiddenOperation


class Seeds(HTMLParser):
    def __init__(self):
        super().__init__()
        self.area = None
        self.urls = []
        self.section_stack = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "section": self.section_stack.append(self.area)
        if tag == 'section' and a.get('id', '').startswith('a'):
            try: self.area = int(a['id'][1:])
            except ValueError: self.area = None
        if tag == 'a' and self.area and a.get('href', '').startswith('https://'):
            if urlsplit(a['href']).hostname == 'restaurant.ikyu.com':
                a['href']='https://restaurant.ikyu.com/'+urlsplit(a['href']).path.strip('/').split('/')[0]+'/'
            try: check_url(a['href'])
            except (ValueError, ForbiddenOperation): return
            item = (self.area, a['href'])
            if item not in self.urls: self.urls.append(item)

    def handle_endtag(self, tag):
        if tag == "section" and self.section_stack: self.area = self.section_stack.pop()

def run(limit=5, seconds=180):
    protected_files()
    master = load_master()
    parser = Seeds()
    parser.feed((ROOT/'docs/index.html').read_text())
    # Historical HTML supplies discovery URLs only. No old prices/themes are reused.
    ordered = []
    by_area = {a['no']: [u for n,u in parser.urls if n==a['no']] for a in master['areas']}
    for i in range(max(map(len, by_area.values()), default=0)):
        for n, urls in by_area.items():
            if i < len(urls): ordered.append((n, urls[i]))
    stamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    start = stamp.date()
    out = staging_directory()/('public-'+stamp.strftime('%Y%m%dT%H%M%S%f'))
    out.mkdir()
    browser = Browser(delay=1, timeout=8, max_requests=limit*2+8)
    audit = {'started_at':stamp.isoformat(), 'period':{'start':str(start),'end':str(start+dt.timedelta(days=40))},
             'mode':'anonymous_public_GET_only', 'publishable':False, 'confirmed':0,
             'coverage_complete':False, 'pages':[], 'areas':[{'no':a['no'],'name':a['name'],'status':'unresearched'} for a in master['areas']],
             'candidates':[dict(c,status='unresearched') for c in master['candidates']],
             'limitations':['Historical URLs are discovery seeds, not verified current information.',
                            'Text clues never confirm a plan; field-level review is still required.',
                            'Area lists, openings, and complete hotel inventory remain incomplete.']}
    def save():
        audit['requests']=browser.count
        audit['blocked_operations']=browser.transport.audit
        p=out/'.audit.tmp';p.write_text(dumps(audit));p.replace(out/'audit.json')
    dataset=create_data(master, str(start))
    dataset["metadata"]["purpose"]="research"
    dataset["notes"]["status"] += " 公開文書の探索のみ。予約プランの個別検証は未完了。過去のカレンダー操作による確認は再利用しない。"
    (out/("data_"+str(start)+".json")).write_text(dumps(dataset))
    save()
    began=time.monotonic()
    for area,url in ordered[:limit]:
        if time.monotonic()-began > seconds:
            audit['stop_reason']='time_budget';break
        row={'area':area,'url':url,'status':'unresolved','checked_at':dt.datetime.now(dt.timezone.utc).isoformat()}
        try:
            raw=browser.fetch(url)
            row['evidence']=inspect_page(raw,url,str(start))
            links=TextAndLinks();links.feed(raw)
            discovered=[]
            for href in links.links:
                target=urljoin(url,href)
                try: check_url(target)
                except (ValueError,ForbiddenOperation): continue
                if target not in discovered and target!=url: discovered.append(target)
            row['discovered_public_urls']=discovered[:100]
            row['fetch']='success'
        except Exception as error:
            row['fetch']='failed';row['reason']=str(error)
        audit['pages'].append(row)
        audit['areas'][area-1]['status']='incomplete'
        save()
        if browser.transport.audit:
            audit['stop_reason']='forbidden_operation_detected';save();break
    protected_files();save()
    return out,audit


def main():
    p=argparse.ArgumentParser();p.add_argument('--limit',type=int,default=5);p.add_argument('--seconds',type=int,default=180)
    a=p.parse_args()
    if not 1<=a.limit<=200 or not 1<=a.seconds<=1800: p.error('bounded positive limits required')
    out,audit=run(a.limit,a.seconds)
    print(json.dumps({'output':str(out),'pages':len(audit['pages']),'fetched':sum(r.get('fetch')=='success' for r in audit['pages']),'confirmed':0,'publishable':False}))
if __name__=='__main__': main()
