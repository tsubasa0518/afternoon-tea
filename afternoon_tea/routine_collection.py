"""Bounded multi-round public-page collection for Claude; never confirms or publishes.

One central GET-only collector shares robots, request limits and a communication
journal. Nine optional agents can review its saved area files without duplicate HTTP.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlsplit
from .communication_audit import CommunicationAudit
from .data import JST
from .discovery import AREA_LIST, listing_links
from .master import ROOT
from .priority_research import read, seed_policy, GROUPS
from .research import Browser
from .research_store import atomic_json, store_lock
from .read_only import ForbiddenOperation


def rounds(queue, done=()):
    """One uncollected task per area, then round 2, 3, ... until all 156 are visited."""
    remaining = [[t for t in a['tasks'] if t['id'] not in done] for a in queue['areas']]
    for index in range(max(map(len, remaining), default=0)):
        for area, tasks in zip(queue['areas'], remaining):
            if index < len(tasks):
                yield index + 1, area, tasks[index]


def run(queue, directory, browser, seconds=600, discovery_fraction=.2, clock=time.monotonic):
    """Save every result before proceeding; resume only within this exact run_id."""
    if seconds <= 0 or not 0 < discovery_fraction < 1:
        raise ValueError('positive time and discovery budget required')
    directory = Path(directory)
    path = directory/'collection.json'
    state = read(path) if path.exists() else {
        'run_id': queue['run_id'], 'documents': [], 'discovery_pages': [],
        'new_url_candidates': [], 'pending_lists': [AREA_LIST], 'stop_reason': None}
    if state['run_id'] != queue['run_id']:
        raise ValueError('different run checkpoint; prepare a separate workdir')
    began = clock(); deadline = began + seconds
    journal_path = browser.communication_audit.path
    segment = journal_path.name if journal_path else 'segment-'+str(len(state.get('communication_segments', {}))+1)
    state['stop_reason'] = None
    def save():
        state['requests_this_segment'] = browser.count
        snapshot = browser.communication_audit.snapshot(browser.count)
        state['communication_audit'] = snapshot
        state.setdefault('communication_segments', {})[segment] = {k: snapshot[k] for k in ('complete','requests','violations','chain_sha256','scope')}
        segments = list(state['communication_segments'].values())
        valid = state.get('stop_reason') != 'safety_or_program_error' and all(s['complete'] and not s['violations'] for s in segments)
        state['communication_summary'] = {'run_id': queue['run_id'], 'complete': valid,
            'requests': sum(s['requests'] for s in segments),
            'violations': sum(len(s['violations']) for s in segments),
            'operations_executed': 0 if valid else None,
            'scope': 'routine_collection ReadOnlyTransport segments only; excludes other tools'}
        atomic_json(path, state)
        # Separate fragments make nine-agent review and interrupted work resumable.
        for a in queue['areas']:
            atomic_json(directory/f'collected-area-{a["no"]:02d}.json', {
                'run_id': queue['run_id'], 'area': a['name'], 'stations': a['stations'],
                'group': next(i for i, g in enumerate(GROUPS, 1) if a['no'] in g),
                'documents': [d for d in state['documents'] if d['area_no'] == a['no']],
                'discovery_search': ' '.join([a['name'], *a['stations'], '新規開業 ホテル カフェ アフタヌーンティー', queue['generated_at'][:4]]),
                'discovery_status': 'incomplete' if any(d.get('area_no') == a['no'] for d in state['discovery_pages']) else 'unresearched'})
    def fetch(url, row):
        row['checked_at'] = dt.datetime.now(JST).isoformat()
        policy = seed_policy(url)
        if not policy['allowed_by_read_only_url_policy']:
            row.update(result='source_needed', reason=policy['reason'], http_attempted=False)
            return None
        before = browser.count
        try:
            raw = browser.fetch(url)
        except ForbiddenOperation:
            row.update(result='safety_stop', reason='forbidden_operation')
            raise
        except (RuntimeError, OSError) as exc:
            reason = str(exc)
            if browser.communication_audit.failed:
                raise
            if isinstance(exc, RuntimeError) and not reason.startswith(('HTTP_', 'robots_', 'host_', 'access_', 'page_too_large', 'not_html', 'request_budget_exhausted', 'cross_host_redirect')):
                raise
            row.update(result='access_denied' if reason in ('HTTP_403','HTTP_429') else 'site_restriction' if any(x in reason for x in ('robots','host_stopped','challenge')) else 'fetch_failed', reason=reason)
            if reason == 'request_budget_exhausted':
                row['result'] = 'budget_pending'
                raise TimeoutError('request_budget') from exc
            return None
        finally:
            row['request_count'] = browser.count - before
            row['http_attempted'] = row['request_count'] > 0
        row.update(result='fetched', sha256=hashlib.sha256(raw.encode()).hexdigest(),
                   fetched_at=dt.datetime.now(JST).isoformat())
        # Storage/program failures must propagate; only network failures are partial research.
        page = directory/'pages'/(row['sha256']+'.html')
        if page.parent.is_symlink() or page.is_symlink():
            raise ValueError('symlink page directory forbidden')
        page.parent.mkdir(parents=True, exist_ok=True)
        if page.exists():
            if hashlib.sha256(page.read_bytes()).hexdigest() != row['sha256']:
                raise ValueError('corrupt saved page')
        else:
            with page.open('x', encoding='utf-8') as output:
                output.write(raw)
        row['page_file'] = str(page.relative_to(directory))
        return raw
    try:
        # Reserve a real portion of both time and requests BEFORE store collection.
        discovery_deadline = began + seconds * discovery_fraction
        discovery_request_limit = max(1, int(browser.max_requests * discovery_fraction))
        seen = {p['url'] for p in state['discovery_pages'] if p.get('result') not in (None,'budget_pending','safety_stop')}
        while state['pending_lists'] and clock() < discovery_deadline and browser.count < discovery_request_limit:
            url = state['pending_lists'][0]
            if url in seen:
                state['pending_lists'].pop(0); continue
            row = {'url': url, 'area_no': None, 'scope': 'discovery'}
            state['discovery_pages'].append(row)
            raw = fetch(url, row)
            state['pending_lists'].pop(0);seen.add(url)
            if raw:
                stores, lists = listing_links(raw, url)
                # Area comes from the page's own visible heading, never the seed URL.
                from .extraction import Document
                headings = ' '.join(n.text for n in Document(raw).root.find('h1'))
                hits = [a['no'] for a in queue['areas'] if any(part in headings for part in a['name'].split('・'))]
                row['area_no'] = hits[0] if len(hits) == 1 else None
                for target, label in stores:
                    if not any(x['url'] == target for x in state['new_url_candidates']):
                        state['new_url_candidates'].append({'url': target, 'name_hint': label,
                            'area_no': row['area_no'], 'source_url': url, 'checked_at': row['checked_at'],
                            'status': 'unresearched', 'new': True})
                for target, label in lists:
                    if target not in seen and target not in state['pending_lists']:
                        state['pending_lists'].append(target)
            save()
        done = {d['queue_id'] for d in state['documents'] if d.get('result') not in (None, 'budget_pending', 'safety_stop')}
        # Do not cap at 14. Requests and wall time are the only collection limits.
        for number, area, task in rounds(queue, done):
            if clock() >= deadline:
                state['stop_reason'] = 'time_budget'; break
            if browser.count >= browser.max_requests:
                state['stop_reason'] = 'request_budget'; break
            row = next((d for d in state['documents'] if d['queue_id'] == task['id'] and d.get('result') == 'budget_pending'), None)
            if row is None:
                row = {'queue_id': task['id'], 'area_no': area['no'], 'round': number}
                state['documents'].append(row)
            else:
                previous = {k: v for k,v in row.items() if k != 'previous_collection_attempts'}
                history = row.get('previous_collection_attempts', []) + [previous]
                row.clear(); row.update(queue_id=task['id'], area_no=area['no'], round=number, previous_collection_attempts=history)
            # Reference URL is only a starting hint, not adopted booking evidence.
            urls = [task['historical_url']] if task.get('historical_url') else task.get('source_hints', [])
            if not urls:
                row.update(result='source_needed', http_attempted=False,
                           reason='No safe source hint; use permitted shop/station discovery')
            else:
                row['url'] = urls[0]
                fetch(urls[0], row)
            save()
    except TimeoutError as exc:
        state['stop_reason'] = str(exc)
    except BaseException:
        state['stop_reason'] = 'safety_or_program_error'
        save()
        raise
    finally:
        completed = {d['queue_id'] for d in state['documents'] if d.get('result') not in (None,'safety_stop','budget_pending')}
        state['remaining_queue_ids'] = [t['id'] for a in queue['areas'] for t in a['tasks'] if t['id'] not in completed]
        state['last_round'] = max((d.get('round',0) for d in state['documents']), default=0)
        state['needs_source_queue_ids'] = [d['queue_id'] for d in state['documents'] if d.get('result') == 'source_needed']
        state['complete_research'] = False  # Collection is not plan verification or full exploration.
        save()
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workdir', type=Path, default=ROOT/'.staging/priority-research')
    parser.add_argument('--seconds', type=int, default=600)
    parser.add_argument('--max-requests', type=int, default=240)
    args = parser.parse_args()
    directory = args.workdir.resolve()
    if not directory.is_relative_to(ROOT.resolve()/'.staging'):
        parser.error('workdir must be inside .staging')
    if not 1 <= args.seconds <= 3600 or not 1 <= args.max_requests <= 600:
        parser.error('bounded positive time/request limits required')
    queue = read(directory/'queue.json')
    with store_lock(directory):
        journal = CommunicationAudit(queue['run_id'], directory/('communication-'+dt.datetime.now(JST).strftime('%H%M%S%f')+'.jsonl'))
        browser = Browser(delay=2, timeout=min(10,args.seconds), max_requests=args.max_requests, audit=journal)
        result = run(queue, directory, browser, seconds=args.seconds)
    print(json.dumps({k: result[k] for k in ('run_id','last_round','remaining_queue_ids','stop_reason')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
