"""Offline queue and coverage report for the user-supplied 134 priority sources.

This helper never fetches URLs, confirms a shop, or gates automatic publication.
Only reviewed venue aliases are merged; historical values remain reference hints.
"""
import argparse
from collections import Counter
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from .data import JST
from .master import ROOT
from .read_only import check_url, ForbiddenOperation
from .research_store import atomic_json
from .routine_site import resource

STATUSES = {'confirmed', 'information_insufficient', 'site_restriction',
            'access_denied', 'no_results', 'excluded', 'unresearched'}
GROUPS = ((1,), (2,), (3, 4), (5, 6), (7,), (8,), (9, 10), (11, 12), (13, 14))


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def stamp(value):
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('timezone required')
    return parsed


def master_entries(master):
    entries = {s['id']: {**s, 'area': a['name'], 'area_no': a['no']}
               for a in master['areas'] for g in a['cats'].values() for s in g['shops']}
    for i, shop in enumerate(master['candidates'], 1):
        # Candidate locations in the original master are station names.
        areas = [a for a in master['areas'] if shop['area'] in a['stations']]
        if len(areas) != 1:
            raise ValueError('ambiguous master candidate area')
        entries[f'master-candidate-{i:02d}'] = {
            **shop, 'area': areas[0]['name'], 'area_no': areas[0]['no']}
    return entries


def priority_entries(source, master):
    expected = [a['name'] for a in master['areas']]
    if [a['area'] for a in source['areas']] != expected or len(expected) != 14:
        raise ValueError('priority areas must match the 14 master areas in order')
    entries = []
    for no, area in enumerate(source['areas'], 1):
        for s in area['shops']:
            entries.append({**copy.deepcopy(s), 'id': f'priority-{s["source_row"]:03d}',
                            'area': area['area'], 'area_no': no, 'kind': 'listed'})
    if [x['source_row'] for x in entries] != list(range(1, 121)):
        raise ValueError('expected exactly source rows 1..120')
    if len(source['candidates']) != 14:
        raise ValueError('expected 14 historical candidates')
    for i, s in enumerate(source['candidates'], 1):
        entries.append({**copy.deepcopy(s), 'id': f'priority-candidate-{i:02d}',
                        'area_no': expected.index(s['area']) + 1, 'kind': 'candidate'})
    for item in entries:
        if not isinstance(item['name'], str) or not item['name'].strip() or item.get('must_research') is not True:
            raise ValueError('priority identity missing')
        # Validate reference syntax only. This does NOT authorize fetching it.
        resource(item['historical_url'])
    if source['counts'] != {'areas': 14, 'historical_listed_shops': 120, 'historical_candidates': 14}:
        raise ValueError('priority counts do not match records')
    return entries


def seed_policy(url):
    try:
        check_url(url)
        return {'allowed_by_read_only_url_policy': True,
                'note': 'robots/terms/HTTP restrictions must still be checked before reading'}
    except ForbiddenOperation as exc:
        return {'allowed_by_read_only_url_policy': False, 'reason': str(exc),
                'note': 'Do not fetch or rewrite this URL to bypass restrictions; use permitted public discovery'}


def prepare(source, master, matches, run_id, now, previous=None):
    stamp(now)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', run_id):
        raise ValueError('invalid run_id')
    priority = priority_entries(source, master)
    known = master_entries(master)
    tasks = {s['id']: {**s, 'priority': 'A', 'master_ids': [],
                       'status': 'unresearched', 'attempts': [], 'run_id': run_id,
                       'seed_policy': seed_policy(s['historical_url'])} for s in priority}
    linked = set()
    for link in matches['matches']:
        mid, pid = link['master_id'], link['priority_id']
        if mid in linked or mid not in known or pid not in tasks:
            raise ValueError('invalid or duplicate reviewed match')
        left, right = known[mid], tasks[pid]
        if (link['master_name'] != left['name'] or link['priority_name'] != right['name']
                or link['area'] != left['area'] or left['area'] != right['area']):
            raise ValueError('reviewed match identity changed; review it again')
        right['master_ids'].append(mid)
        linked.add(mid)
    for mid, s in known.items():
        if mid not in linked:
            tasks[mid] = {**s, 'id': mid, 'priority': 'B', 'master_ids': [mid],
                          'status': 'unresearched', 'attempts': [], 'run_id': run_id}
    previous_rows = {f.get('priority_id', f.get('queue_id')): f
                     for f in (previous or {}).get('failures', [])}
    for task in tasks.values():
        old = previous_rows.get(task['id'])
        if old is None:
            names = {task['name']} | {known[mid]['name'] for mid in task.get('master_ids', [])}
            old = next((f for f in (previous or {}).get('failures', [])
                        if f.get('scope', 'shop') == 'shop' and f.get('name') in names
                        and re.sub(r'^\d+ ', '', f.get('area', '')) == task['area']), None)
        # Previous status is a scheduling hint only; never restore confirmation.
        if old:
            task['previous_status'] = old['status']
            task['previous_checked_at'] = old.get('checked_at')
    areas = [{'no': a['no'], 'name': a['name'], 'stations': a['stations'],
              'group': next(i for i, group in enumerate(GROUPS, 1) if a['no'] in group),
              'discovery_status': 'unresearched', 'discovery_attempts': [],
              'tasks': sorted([s for s in tasks.values() if s['area_no'] == a['no']],
                              key=lambda s: (s['priority'], s.get('previous_status') != 'unresearched', s['id']))}
             for a in master['areas']]
    records = []
    for area in areas:
        for task in area['tasks']:
            records.append({'queue_id': task['id'],
                            **({'priority_id': task['id']} if task['priority'] == 'A' else {}),
                            'name': task['name'], 'area': task['area'], 'scope': 'shop',
                            'run_id': run_id, 'checked_at': now, 'status': 'unresearched',
                            'sources': [], 'attempts': [], 'reason': '今回未調査。AT提供なしを意味しない。',
                            'retry': True})
    return {'schema_version': 1, 'run_id': run_id, 'generated_at': now,
            'priority_count': 134, 'master_matches': len(linked), 'areas': areas,
            'failures_template': {'schema_version': 1, 'generated_at': now, 'failures': records}}


def add_discovery(queue, name, area_no, url, checked_at):
    """Explicit full-venue identity only; a hotel name alone never merges lounges."""
    stamp(checked_at)
    resource(url)
    def key(value):
        return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())
    if not name.strip():
        raise ValueError('discovery name missing')
    area = next(a for a in queue['areas'] if a['no'] == area_no)
    for task in area['tasks']:
        if key(task['name']) == key(name):
            return task
    identity = f'{area_no}:{key(name)}'
    item = {'id': 'discovered-' + hashlib.sha256(identity.encode()).hexdigest()[:16],
            'name': name, 'area': area['name'], 'area_no': area_no, 'priority': 'C',
            'new': True, 'discovered_url': url, 'discovered_at': checked_at,
            'run_id': queue['run_id'], 'status': 'unresearched', 'attempts': []}
    area['tasks'].append(item)
    return item


def report(queue, research, failures):
    """Pre-PR coverage diagnostics, not an Actions publication gate."""
    expected = {s['id']: s for a in queue['areas'] for s in a['tasks'] if s['priority'] == 'A'}
    records, errors = {}, []
    day = stamp(queue['generated_at']).astimezone(JST).date()
    def current(value):
        return stamp(value).astimezone(JST).date() == day
    for f in failures['failures']:
        pid = f.get('priority_id')
        if pid is None:
            continue  # Area/master/new records are not counted as the 134 rows.
        if pid not in expected or pid in records:
            errors.append('unknown_or_duplicate_priority_id:' + str(pid))
            continue
        records[pid] = f
        original = expected[pid]
        if f['name'] != original['name'] or f['area'] != original['area']:
            errors.append('identity_changed:' + pid)
        try:
            if f['status'] not in STATUSES or f.get('run_id') != queue['run_id'] or not current(f['checked_at']):
                raise ValueError('status_run_or_date')
            for attempt in f.get('attempts', []):
                resource(attempt['url'])
                if not current(attempt['checked_at']) or not attempt['result'] or not attempt['reason']:
                    raise ValueError('attempt_evidence')
            if f['status'] != 'unresearched' and not f.get('attempts'):
                raise ValueError('attempts_required')
            if f['status'] in ('confirmed', 'excluded'):
                resource(f['evidence_url'])
                if not f.get('evidence_quote', '').strip() or not current(f['verified_at']):
                    raise ValueError('decision_evidence_required')
            if f['status'] == 'confirmed':
                shops = [s for s in research['shops'] if pid in s.get('priority_ids', [])]
                if len(shops) != 1 or not current(shops[0]['checked_at']) or not shops[0].get('plans'):
                    raise ValueError('confirmed_shop_required')
                check_url(shops[0]['source_url'])
        except (KeyError, TypeError, ValueError, ForbiddenOperation):
            errors.append('invalid_or_missing_current_evidence:' + pid)
    for pid in expected.keys() - records.keys():
        errors.append('missing_priority_id:' + pid)
    valid = {pid: f for pid, f in records.items()
             if not any(e.endswith(':' + pid) for e in errors)}
    counts = Counter(f['status'] for f in valid.values())
    return {'run_id': queue['run_id'], 'priority_count': len(expected),
            'tracked': len(records), 'attempted_with_evidence': sum(f['status'] != 'unresearched' for f in valid.values()),
            'statuses': {s: counts[s] for s in sorted(STATUSES)}, 'errors': sorted(errors),
            'areas': [{'no': a['no'], 'name': a['name'],
                       'priority_count': sum(s['priority'] == 'A' for s in a['tasks']),
                       'confirmed': sum(f['status'] == 'confirmed' and f['area'] == a['name'] for f in valid.values())}
                      for a in queue['areas']],
            'published_shops': len(research['shops']),
            'published_plans': sum(len(s.get('plans', [])) for s in research['shops']),
            'note': 'Coverage diagnostics only. Historical URLs do not establish current AT availability.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'report'))
    parser.add_argument('--run-id', default=dt.datetime.now(JST).strftime('%Y%m%dT%H%M%S%f'))
    parser.add_argument('--workdir', type=Path, default=ROOT / '.staging/priority-research')
    parser.add_argument('--data', type=Path, default=ROOT / 'site/research.json')
    parser.add_argument('--failures', type=Path, default=ROOT / 'site/search_failures.json')
    args = parser.parse_args()
    # Working output is ephemeral; the three existing site files are the only routine commits.
    directory = args.workdir.resolve()
    if not directory.is_relative_to(ROOT.resolve() / '.staging'):
        parser.error('workdir must be under .staging')
    if args.command == 'prepare':
        if (directory/'collection.json').exists():
            parser.error('existing collection: resume it, or choose a new --workdir; do not overwrite its queue')
        queue = prepare(read(ROOT / 'data/priority_sources.json'), read(ROOT / 'data/store_master.json'),
                        read(ROOT / 'data/priority_master_matches.json'), args.run_id,
                        dt.datetime.now(JST).isoformat(), read(args.failures))
        # Existing checkpoints supply URL hints only, never current prices or confirmation.
        history = read(ROOT/'research_data/state.json') if (ROOT/'research_data/state.json').exists() else {}
        old = {x['id']: x for x in history.get('items', [])}
        for area in queue['areas']:
            for task in area['tasks']:
                task['source_hints'] = list(dict.fromkeys(url for mid in task.get('master_ids', [])
                    for site in ('ik', 'tb', 'tc') for url in old.get(mid, {}).get('sources', {}).get(site, [])
                    if seed_policy(url)['allowed_by_read_only_url_policy']))
        atomic_json(directory / 'queue.json', queue)
        atomic_json(directory / 'failures_template.json', queue['failures_template'])
        for area in queue['areas']:
            atomic_json(directory / f'area-{area["no"]:02d}.json', area)
        print(json.dumps({'run_id': queue['run_id'], 'priority': 134,
                          'total_tasks': sum(len(a['tasks']) for a in queue['areas']),
                          'master_matches': queue['master_matches']}, ensure_ascii=False))
        return 0
    result = report(read(directory / 'queue.json'), read(args.data), read(args.failures))
    atomic_json(directory / 'priority_report.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
