"""Bounded current public AT-list discovery; store URLs are candidates, not facts."""
import datetime as dt
import re
import time
from urllib.parse import urlsplit,urljoin
from .data import JST
from .extraction import Document,first
from .master import ROOT,load_master
from .read_only import check_url,ForbiddenOperation
from .research import Browser
from .research_store import load_state,save_state,add_discovery,atomic_json,store_lock

# A known public editorial/list route, not a booking or form endpoint.
AREA_LIST='https://restaurant.ikyu.com/t/s495-%E8%BB%BD%E9%A3%9F/g15-%E3%82%A2%E3%83%95%E3%82%BF%E3%83%8C%E3%83%BC%E3%83%B3%E3%83%86%E3%82%A3%E3%83%BC/tokyo/011/0027/'

def listing_links(raw,url):
    root=Document(raw).root
    at_list=any('アフタヌーンティー' in h.text for h in root.find('h1'))
    stores={};lists=[]
    for a in root.find('a'):
        p=urlsplit(urljoin(url,a.attrs.get('href','')))
        # Derive the public document path only; never send the listing's guest query.
        if at_list and p.hostname=='restaurant.ikyu.com' and re.fullmatch(r'/\d{5,6}/?',p.path) and a.text and not a.text.isdigit():
            target='https://restaurant.ikyu.com'+p.path.rstrip('/')+'/'
            check_url(target);stores[target]=a.text
        elif p.hostname=='restaurant.ikyu.com' and not p.query and ((p.path.startswith('/t/') and 'アフタヌーンティー' in a.text) or p.path.startswith('/area/') or p.path=='/s-tokyo/'):
            target='https://restaurant.ikyu.com'+p.path
            try:check_url(target)
            except (ValueError,ForbiddenOperation):continue
            if (target,a.text) not in lists:lists.append((target,a.text))
    return list(stores.items()),lists

def _run(directory=None,max_pages=28,seconds=240,browser=None):
    directory=directory or ROOT/'research_data';master=load_master();state=load_state(directory,master,str(dt.datetime.now(JST).date()))
    browser=browser or Browser(delay=1,timeout=8,max_requests=max_pages*2+4)
    frontier=[tuple(x) for x in state.get('discovery_frontier',[(1,AREA_LIST)])];seen=set();visited_areas={a['no'] for a in state['areas'] if a['discovery_status']=='incomplete'};records=[];began=time.monotonic();added=0
    prior={r['url']:r for r in state.get('discovery_runs',[]) if r['checked_at'].startswith(state['day'])}
    def enqueue(lists):
        for target,label in lists:
            hits=[a['no'] for a in master['areas'] if any(token in label for token in a['name'].split('・'))]
            pair=(0,target) if urlsplit(target).path=='/s-tokyo/' else (hits[0],target) if len(hits)==1 else None
            if pair and pair not in frontier and target not in seen:frontier.append(pair)
        frontier.sort(key=lambda pair:pair[0] in visited_areas)
    while frontier and len(records)<max_pages and time.monotonic()-began<seconds:
        area,url=frontier.pop(0)
        if url in seen:continue
        seen.add(url);visited_areas.add(area)
        cached=prior.get(url)
        if cached and 'listing_links' in cached:
            enqueue(cached['listing_links']);continue
        # Older checkpoints lack outgoing links; re-read that public document once.
        row={'area':area,'url':url,'checked_at':dt.datetime.now(JST).isoformat()}
        try:
            raw=browser.fetch(url);stores,lists=listing_links(raw,url)
            row.update(fetch='success',store_urls=len(stores),listing_links=lists)
            for target,label in stores:
                added+=add_discovery(state,target,label,area,url,row['checked_at'])
            enqueue(lists)
        except ForbiddenOperation as e:
            row.update(fetch='blocked',reason=str(e));records.append(row);state.setdefault('discovery_runs',[]).append(row);break
        except Exception as e:row.update(fetch='failed',reason=str(e))
        records.append(row)
        state['discovery_frontier']=frontier
        state['discovery_runs']=state.get('discovery_runs',[])+[row];save_state(directory,state,master)
    state['discovery_frontier']=frontier
    reconcile_areas(state)
    summary={'checked_at':dt.datetime.now(JST).isoformat(),'pages':records,'new_candidate_urls':added,'requests':browser.count,'complete_coverage':False}
    state['last_discovery']=summary;save_state(directory,state,master);return summary

def reconcile_areas(state):
    for area in state['areas']:
        related=[r for r in state.get('discovery_runs',[]) if r['area']==area['no'] and r['checked_at'].startswith(state['day'])]
        area['discovery_status']='incomplete' if any(r.get('fetch')=='success' for r in related) else 'unresolved'
        area['reason']='Bounded current AT-list page only; no complete hotel/opening/station search' if related else 'No allowed current area-list route discovered; no absence claim'


def run(directory=None,max_pages=28,seconds=240,browser=None):
    with store_lock(directory or ROOT/'research_data'):return _run(directory,max_pages,seconds,browser)

if __name__=='__main__':
    from .master import dumps
    print(dumps(run()))
