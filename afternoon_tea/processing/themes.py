(
    'Offline country decisions: Claude judges saved text; Python validates and r'
    'euses.\n\nNo country-specific theme heuristics, model calls or network operat'
    'ions live here.\n'
)
import copy
from functools import lru_cache
import hashlib
import json
import re
import unicodedata
from afternoon_tea.collection.catalog import ROOT
from afternoon_tea.collection.storage import atomic_json
FIELDS = ('country', 'cc', 'country_source_type')
TEXT_FIELDS = ('plan_name', 'theme', 'menu', 'description')

@lru_cache(maxsize=1)
def registry():
    return json.loads((ROOT / 'data/country_registry.json').read_text())['countries']

def normalize(value):
    return re.sub('\\s+', ' ', unicodedata.normalize('NFKC', value)).strip().casefold()

def validate_country(plan):
    """Optional schema extension, strict as soon as a decision is present."""
    hashes = [plan[key] for key in ('country_input_hash', 'country_decision_hash') if key in plan]
    if any((not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value) for value in hashes)):
        raise ValueError('invalid_country_content_hash')
    if not any((key in plan for key in FIELDS)) and (not hashes):
        return
    if not all((key in plan for key in FIELDS)):
        raise ValueError('country_fields_incomplete')
    kind = plan['country_source_type']
    if kind == 'unknown':
        if plan['country'] is not None or plan['cc'] is not None:
            raise ValueError('unknown_country_must_be_null')
        return
    if kind not in ('explicit', 'inferred'):
        raise ValueError('invalid_country_source_type')
    (cc, name) = (plan['cc'], plan['country'])
    if not isinstance(cc, str) or cc.lower() not in registry():
        raise ValueError('invalid_ISO_country_code')
    entry = registry()[cc.lower()]
    if not isinstance(name, str) or normalize(name) not in {normalize(n) for n in [entry['name'], *entry['aliases']]}:
        raise ValueError('country_name_code_mismatch')

def flag(cc):
    if not isinstance(cc, str) or cc.lower() not in registry():
        raise ValueError('invalid_ISO_country_code')
    return ''.join((chr(127462 + ord(letter) - ord('A')) for letter in cc.upper()))

def content_hash(plan, shop):
    """Only thematic content, not prices, dates, URLs, timestamps or decisions."""
    fields = {key: plan.get(key) for key in TEXT_FIELDS}
    fields['venue_concept'] = shop.get('concept')
    text = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(text.encode()).hexdigest()

def identity(shop):
    return shop.get('id') or shop.get('name')

def prepare(data, previous=None):
    """Restore unchanged decisions; return only new/changed plans for Claude to read."""
    result = copy.deepcopy(data)
    cache = {}
    for shop in (previous or {}).get('shops', []):
        for plan in shop.get('plans', []):
            digest = content_hash(plan, shop)
            if plan.get('country_decision_hash') == digest:
                validate_country(plan)
                cache[identity(shop), digest] = plan
    pending = []
    decision_keys = (*FIELDS, 'country_basis', 'country_decision_hash')
    for (si, shop) in enumerate(result['shops']):
        for (pi, plan) in enumerate(shop.get('plans', [])):
            digest = content_hash(plan, shop)
            plan['country_input_hash'] = digest
            if plan.get('country_decision_hash') == digest:
                validate_country(plan)
                continue
            saved = cache.get((identity(shop), digest))
            if saved:
                for key in decision_keys:
                    if key in saved:
                        plan[key] = copy.deepcopy(saved[key])
                # Preserve this week's other notes; recreate the reused inferred audit at finalize.
                continue
            plan.update(country=None, cc=None, country_source_type='unknown')
            plan.pop('country_decision_hash', None)
            plan.pop('country_basis', None)
            pending.append({'shop_index': si,
                 'plan_index': pi,
                 'shop_name': shop.get('name'),
                 'input_hash': digest,
                 **{key: plan.get(key) for key in TEXT_FIELDS},
                 'evidence_quote': plan.get('evidence_quote'),
                 'venue_concept': shop.get('concept')})
    return (result, pending)

def finalize(data):
    """Seal Claude's decisions and keep inferred explanations in internal notes.status."""
    result = copy.deepcopy(data)
    for shop in result['shops']:
        for plan in shop.get('plans', []):
            digest = content_hash(plan, shop)
            if plan.get('country_input_hash') != digest:
                raise ValueError('country_content_changed_run_prepare_and_reassess')
            validate_country(plan)
            kind = plan['country_source_type']
            basis = plan.get('country_basis')
            if not isinstance(basis, str) or not basis.strip():
                raise ValueError('country_basis_required_even_for_unknown')
            if kind != 'unknown':
                plan['cc'] = plan['cc'].lower()
                plan['country'] = registry()[plan['cc']]['name']
            if kind == 'inferred':
                message = f"テーマ国推測：店舗={shop.get('name')} ／ プラン={plan.get('plan_name')} ／ 国={plan['country']} ({plan['cc']}) ／ 根拠={basis}"
                notes = plan.setdefault('notes', {})
                if not isinstance(notes, dict):
                    notes = plan['notes'] = {'previous': notes}
                status = notes.get('status')
                if status is None:
                    notes['status'] = message
                elif isinstance(status, str):
                    if message not in status:
                        notes['status'] = status + '\n' + message
                elif isinstance(status, list):
                    if message not in status:
                        status.append(message)
                else:
                    notes['status'] = [status, message]
            plan['country_decision_hash'] = digest
    return result

def display(plan, shop):
    validate_country(plan)
    if plan.get('country_source_type') not in ('explicit', 'inferred'):
        return None
    # A changed plan may not display last week's semantic decision.
    if plan.get('country_decision_hash') is not None and plan['country_decision_hash'] != content_hash(plan, shop):
        return None
    entry = registry()[plan['cc'].lower()]
    name = entry.get('short_name', entry['name'])
    return flag(plan['cc']) + ' ' + name + ('風' if plan['country_source_type'] == 'inferred' else '')

def main(args):
    parser = args.parser
    path = ROOT / 'site/research.json'
    if path.is_symlink():
        parser.error('symlink data forbidden')
    data = json.loads(path.read_text())
    if args.command == 'prepare':
        previous = json.loads(args.previous.read_text()) if args.previous else None
        (result, pending) = prepare(data, previous)
        atomic_json(path, result)
        print(json.dumps({'pending_plans': pending}, ensure_ascii=False, indent=2))
    else:
        result = finalize(data)
        atomic_json(path, result)
        print(json.dumps({'country_decisions_saved': sum((len(s.get('plans', [])) for s in result['shops']))}))
