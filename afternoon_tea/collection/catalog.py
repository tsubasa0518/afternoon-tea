"""Protected canonical store catalog and strict fourteen-area schema."""
import hashlib
import json
from afternoon_tea.common import ROOT
CATEGORIES = {'カフェ': 'cafe', 'ホテル': 'hotel', 'ホテル（高級）': 'lux'}

def load_master():
    """Load the protected canonical JSON, validating structure and stable identities."""
    name = 'data/store_master.json'
    raw = (ROOT / name).read_bytes()
    manifest = json.loads((ROOT / 'data/protected_hashes.json').read_text())
    if hashlib.sha256(raw).hexdigest() != manifest.get(name):
        raise ValueError('untrusted canonical store master')
    result = json.loads(raw)
    if result.get('schema_version') != 1:
        raise ValueError('invalid master schema')
    areas = result.get('areas', [])
    if len(areas) != 14 or [a.get('no') for a in areas] != list(range(1, 15)):
        raise ValueError('14 master areas required')
    shops = []
    counts = {cat: 0 for cat in CATEGORIES.values()}
    for area in areas:
        if not isinstance(area.get('name'), str) or not area['name'] or (not area.get('stations')):
            raise ValueError('master area information missing')
        if any((not isinstance(v, str) or not v for v in area['stations'])) or len(set(area['stations'])) != len(area['stations']):
            raise ValueError('invalid master stations')
        if set(area.get('cats', {})) != set(CATEGORIES.values()):
            raise ValueError('three master categories required')
        for (category, group) in area['cats'].items():
            if not isinstance(group.get('shops'), list):
                raise ValueError('master shops required')
            for shop in group['shops']:
                if any((not isinstance(shop.get(k), str) or not shop[k] for k in ('id', 'name', 'station'))):
                    raise ValueError('master identity information missing')
                shops.append(shop)
                counts[category] += 1
    if [s['id'] for s in shops] != [f'master-{i:03d}' for i in range(1, len(shops) + 1)]:
        raise ValueError('master IDs missing or reordered')
    expected = {'shops': len(shops), 'by_category': counts, 'candidates': len(result['candidates']), 'out_of_scope': len(result['out_of_scope'])}
    if result.get('counts') != expected:
        raise ValueError('master counts mismatch')
    return result
