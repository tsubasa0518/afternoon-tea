"""Lossless, fail-closed extraction from research_spec.md."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "research_spec.md"
CATEGORIES = {"カフェ": "cafe", "ホテル": "hotel", "ホテル（高級）": "lux"}


def extract_master(path=SPEC):
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8")
    stations, rest = text.split("# 対象エリアと駅\n", 1)[1].split(
        "# 店舗マスター（店名｜駅｜出口）\n", 1)
    shops_text, rest = rest.split("# 未検証の候補（", 1)
    candidates_text, rest = rest.split("# 調査対象外（", 1)
    excluded_text = rest.split("\n", 1)[1].split("# HTML生成スクリプト", 1)[0].strip()
    areas = []
    for line in stations.strip().splitlines():
        match = re.fullmatch(r"(\d+) (.+)：(.+)", line)
        if not match:
            raise ValueError("対象エリア行を解釈できません: " + line)
        no, name, names = match.groups()
        areas.append({"no": int(no), "name": name, "stations": names.split("、"),
                      "raw": line, "cats": {}})
    if [a["no"] for a in areas] != list(range(1, 15)):
        raise ValueError("14エリアが揃っていません")
    current = None
    shop_count = 0
    for line in shops_text.strip().splitlines():
        if not line.strip():
            continue
        if line.startswith("【"):
            match = re.fullmatch(r"【(\d+)(?: [^｜]+)?｜([^】]+)】(（該当なし）)?", line)
            if not match:
                raise ValueError("分類見出しを解釈できません: " + line)
            no, label, empty = match.groups()
            cat = CATEGORIES[label]
            categories = areas[int(no) - 1]["cats"]
            if cat in categories:
                raise ValueError("分類の重複: " + line)
            current = {"label": label, "raw": line, "originally_empty": bool(empty), "shops": []}
            categories[cat] = current
        elif line.startswith("- ") and current is not None:
            fields = line[2:].split("｜")
            if len(fields) != 3 or current["originally_empty"]:
                raise ValueError("店舗行を解釈できません: " + line)
            name, station, exit_text = fields
            shop_count += 1
            current["shops"].append({"id": f"master-{shop_count:03d}", "name": name,
                                     "station": station, "exit": exit_text, "raw": line})
        else:
            raise ValueError("未処理の行: " + line)
    for area in areas:
        if set(area["cats"]) != set(CATEGORIES.values()):
            raise ValueError("分類が欠落しています")
    source_lines = [x for x in shops_text.splitlines() if x.startswith("- ")]
    extracted = [s["raw"] for a in areas for c in a["cats"].values() for s in c["shops"]]
    if source_lines != extracted:
        raise ValueError("店舗の抽出漏れまたは順序変更")
    candidate_groups, candidates = [], []
    for line in candidates_text.splitlines()[1:]:
        if not line.strip():
            continue
        if not line.startswith("- ") or "：" not in line:
            raise ValueError("候補行を解釈できません: " + line)
        area, names = line[2:].split("：", 1)
        candidate_groups.append(line)
        for name in names.split("／"):
            candidates.append({"area": area, "name": name, "raw": line})
    forbidden = excluded_text.split("／")
    return {"schema_version": 1, "source": "research_spec.md",
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "as_of": "2026-10-02", "areas": areas,
            "candidate_source_lines": candidate_groups, "candidates": candidates,
            "out_of_scope": forbidden, "out_of_scope_raw": excluded_text,
            "counts": {"shops": shop_count, "by_category": {
                c: sum(len(a["cats"][c]["shops"]) for a in areas) for c in CATEGORIES.values()},
                "candidates": len(candidates), "out_of_scope": len(forbidden)}}


def dumps(data):
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def load_master():
    """Load the protected canonical JSON, validating structure and stable identities."""
    name='data/store_master.json'
    raw=(ROOT/name).read_bytes()
    manifest=json.loads((ROOT/'data/protected_hashes.json').read_text())
    if hashlib.sha256(raw).hexdigest()!=manifest.get(name):
        raise ValueError('untrusted canonical store master')
    result=json.loads(raw)
    if result.get('schema_version')!=1:raise ValueError('invalid master schema')
    areas=result.get('areas',[])
    if len(areas)!=14 or [a.get('no') for a in areas]!=list(range(1,15)):
        raise ValueError('14 master areas required')
    shops=[];counts={cat:0 for cat in CATEGORIES.values()}
    for area in areas:
        if not isinstance(area.get('name'),str) or not area['name'] or not area.get('stations'):
            raise ValueError('master area information missing')
        if any(not isinstance(v,str) or not v for v in area['stations']) or len(set(area['stations']))!=len(area['stations']):
            raise ValueError('invalid master stations')
        if set(area.get('cats',{}))!=set(CATEGORIES.values()):raise ValueError('three master categories required')
        for category,group in area['cats'].items():
            if not isinstance(group.get('shops'),list):raise ValueError('master shops required')
            for shop in group['shops']:
                if any(not isinstance(shop.get(k),str) or not shop[k] for k in ('id','name','station')):
                    raise ValueError('master identity information missing')
                shops.append(shop);counts[category]+=1
    if [s['id'] for s in shops]!=[f'master-{i:03d}' for i in range(1,len(shops)+1)]:
        raise ValueError('master IDs missing or reordered')
    expected={'shops':len(shops),'by_category':counts,'candidates':len(result['candidates']),
              'out_of_scope':len(result['out_of_scope'])}
    if result.get('counts')!=expected:raise ValueError('master counts mismatch')
    return result


def load_master_snapshot(source_sha):
    """Validate archived evidence against its original master, never re-date it."""
    current = load_master()
    if source_sha == current['source_sha256']:
        return current
    if not isinstance(source_sha, str) or not re.fullmatch(r'[0-9a-f]{64}', source_sha):
        raise ValueError('invalid historical master hash')
    name = 'data/master_history/' + source_sha + '.json'
    manifest = json.loads((ROOT/'data/protected_hashes.json').read_text())
    raw = (ROOT/name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest.get(name):
        raise ValueError('untrusted historical master snapshot')
    result = json.loads(raw)
    if result['source_sha256'] != source_sha:
        raise ValueError('historical master source mismatch')
    return result
