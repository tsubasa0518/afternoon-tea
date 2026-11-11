"""Build the weekly listing once; render only reads saved display values."""
import json
from afternoon_tea.common import ROOT, load_json
from afternoon_tea.collection.storage import atomic_json
from afternoon_tea.processing.weekly import retain, validate_freshness
from afternoon_tea.processing.enrichment import enrich
from afternoon_tea.processing.period_review import review
from afternoon_tea.publication.site import validate_json, json_bytes, validate_site


def build(current, previous=None, now=None, rows=None):
    data = retain(current, previous, now=now, rows=rows)
    periods = review(data)
    errors = [e for e in periods['errors'] if e['reason'] != 'outside_research_period']
    if errors:
        raise ValueError('invalid_plan_period')
    outside = {(e['shop_index'], e['plan_index']) for e in periods['outside_plans']}
    shops = []
    for si, shop in enumerate(data['shops']):
        shop['plans'] = [p for pi, p in enumerate(shop['plans']) if (si, pi) not in outside]
        if shop['plans']:
            shops.append(shop)
    data['shops'] = shops
    data = enrich(data)
    validate_json(json_bytes(data))
    validate_freshness(data, now=now)
    return data


def main():
    from afternoon_tea.publication.renderer import render
    from afternoon_tea.publication.renderer import write_html
    target = ROOT / 'site/research.json'
    if target.is_symlink() or target.parent.is_symlink():
        raise ValueError('symlink data forbidden')
    previous = ROOT / '.staging/weekly/previous.json'
    data = build(load_json(target), load_json(previous) if previous.exists() else None)
    html = render(data)
    report = validate_site({'site/research.json': json_bytes(data), 'site/index.html': html.encode()})
    # Prepare and validate both values before either tracked file is replaced.
    write_html(html)
    atomic_json(target, data)
    print(json.dumps({'shops': report['shops'], 'plans': report['plans'], 'confirmation_dates_changed': False}))
    return 0
