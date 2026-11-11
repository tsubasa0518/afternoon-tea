"""ISO country codes and card flags. No inference, evidence or decision cache."""
import copy
from functools import lru_cache
import json
from afternoon_tea.common import ROOT

RETIRED = {'country', 'country_source_type', 'country_basis',
           'country_input_hash', 'country_decision_hash', 'notes'}

@lru_cache(maxsize=1)
def registry():
    return json.loads((ROOT / 'data/country_registry.json').read_text())['countries']

def code(value):
    if isinstance(value, str) and value.isascii() and value.isalpha() and len(value) == 2 and value.lower() in registry():
        return value.lower()
    return None

def normalize_plan(plan):
    result = {key: copy.deepcopy(value) for key, value in plan.items() if key not in RETIRED}
    result['cc'] = code(plan.get('cc'))
    return result

def validate_country(plan):
    if plan.get('cc') is not None and code(plan['cc']) is None:
        raise ValueError('invalid_ISO_country_code')

def flag(value):
    cc = code(value)
    if cc is None:
        raise ValueError('invalid_ISO_country_code')
    return ''.join(chr(127462 + ord(letter) - ord('A')) for letter in cc.upper())

def display(plan, shop=None):
    cc = code(plan.get('cc'))
    if cc is None:
        return None
    entry = registry()[cc]
    return flag(cc) + ' ' + entry.get('short_name', entry['name'])
