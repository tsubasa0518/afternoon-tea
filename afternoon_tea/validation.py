"""Offline structural and provenance validation; this does not verify Web truth."""
import ast
import datetime as dt
import json
import math
import re
import unicodedata
from urllib.parse import urlsplit

from .data import CATS, PLAN_FIELDS, master_shop, unknown_plan
from .master import ROOT

DOMAINS = {"ik": "restaurant.ikyu.com", "tb": "tabelog.com", "tc": "tablecheck.com"}
FLAGS = {"jp", "gb", "fr", "it", "ma", "cn"}
UNKNOWN = {None, "", "要確認", "未確認", "不明", "未調査"}


class ValidationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def object_at(value, path):
    require(isinstance(value, dict), path + ": object が必要です")
    return value


def list_at(value, path):
    require(isinstance(value, list), path + ": array が必要です")
    return value


def text_at(value, path, nullable=False):
    require((nullable and value is None) or isinstance(value, str), path + ": 文字列が必要です")


def date_at(value, path, nullable=False):
    if value is None and nullable:
        return None
    require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value), path + ": ISO日付が必要です")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(path + ": 存在しない日付") from exc


def normalize(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


def allowed_url(value, site=None):
    require(isinstance(value, str) and value, "URLが必要です")
    require(not any(c.isspace() or ord(c) < 32 for c in value) and "\\" not in value, "不正なURL")
    try:
        parts = urlsplit(value)
        host, port = parts.hostname, parts.port
    except ValueError as exc:
        raise ValidationError("不正なURL") from exc
    allowed = {DOMAINS[site]} if site in DOMAINS else set(DOMAINS.values())
    # www is the sole accepted alias; arbitrary subdomains and suffix matches are unsafe.
    aliases = allowed | {"www." + h for h in allowed}
    require(parts.scheme == "https" and host in aliases and port in (None, 443)
            and parts.username is None and parts.password is None, "許可ドメイン以外のURL: " + value)
    return value


def load_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "JSONキーの重複: " + key)
            result[key] = value
        return result

    def constant(value):
        raise ValidationError("JSONに非有限数: " + value)

    try:
        with open(path, encoding="utf-8") as stream:
            return json.load(stream, object_pairs_hook=pairs, parse_constant=constant)
    except json.JSONDecodeError as exc:
        raise ValidationError("JSON構文エラー: " + str(exc)) from exc


def known(value):
    return isinstance(value, (list, dict)) and bool(value) or (
        not isinstance(value, (list, dict)) and value not in UNKNOWN)


def reference_price(shop):
    prices = [p["price_min"] for p in shop["plans"] if p["price_min"] is not None]
    if prices:
        return min(prices)
    prices = []
    for p in shop["plans"]:
        match = re.search(r"([0-9][0-9,]{2,})\s*円", p["price_text"] or "")
        if match:
            prices.append(int(match.group(1).replace(",", "")))
    return min(prices) if prices else None


def expected_category(shop):
    in_hotel = shop["research"]["in_hotel"]
    if in_hotel is None:
        return "cafe" if shop["master_category"] == "cafe" else "hotel"
    return "cafe" if not in_hotel else ("lux" if (reference_price(shop) or 0) >= 9000 else "hotel")


def proof(value, path, start, generated, url=None):
    value = object_at(value, path)
    allowed_url(value.get("url"))
    checked = date_at(value.get("checked_on"), path + ".checked_on")
    require(start <= checked <= generated, path + ": 調査期間開始〜generatedの確認日が必要です")
    require(isinstance(value.get("quote"), str) and value["quote"].strip(), path + ": 根拠の原文が必要です")
    require(value.get("kind", "observed") in ("observed", "inferred"), path + ": 根拠の種別が不正です")
    if url is not None:
        require(value["url"] == url, path + ": 採用予約URLと異なります")


def validate_data(data, master):
    object_at(data, "root")
    for key in ("generated", "period", "areas", "candidates", "excluded", "notes", "metadata"):
        require(key in data, "必須項目: " + key)
    generated = date_at(data["generated"], "generated")
    per = object_at(data["period"], "period")
    start, end = (date_at(per.get(k), "period." + k) for k in ("start", "end"))
    require(end == start + dt.timedelta(days=40), "調査終了日は開始日の40日後")
    require(start <= generated <= end, "generatedは調査期間内にしてください")
    meta = object_at(data["metadata"], "metadata")
    require(meta.get("schema_version") == 1 and meta.get("purpose") in
            ("unresearched", "research", "test"), "metadataが不正です")
    require(meta.get("master_sha256") == master["source_sha256"], "マスター出典ハッシュが不一致")
    notes = object_at(data["notes"], "notes")
    text_at(notes.get("status"), "notes.status")
    require(notes["status"].strip(), "確認状況を記録してください")
    # Policy genres are read from the specification without changing its wording.
    spec = (ROOT / "research_spec.md").read_text(encoding="utf-8")
    section = spec.split("# 検索対象（", 1)[1].split("# 調査の分担", 1)[0]
    forbidden_genres = set()
    for line in section.splitlines():
        if (line.startswith("- ") and "系：" in line) or line.startswith("- その他："):
            forbidden_genres.update(line.split("：", 1)[1].split("／"))
    sweets = None
    for node in ast.parse((ROOT / "build_html.py").read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SWEETS" for t in node.targets):
            sweets = {k for k, _ in ast.literal_eval(node.value)}
    require(sweets is not None, "生成スクリプトのSWEETSが読めません")
    areas = list_at(data["areas"], "areas")
    require(len(areas) == 14, "14エリアが必要です")
    master_index = {s["id"]: (a["no"], c, s) for a in master["areas"]
                    for c, group in a["cats"].items() for s in group["shops"]}
    seen_ids, seen_names, seen_urls = set(), set(), set()
    confirmed, unresearched, failed = 0, 0, 0

    def permitted_name(name):
        require(isinstance(name, str) and name.strip(), "店舗名が必要です")
        value = normalize(name)
        for banned in master["out_of_scope"]:
            stem = normalize(banned.split("（", 1)[0].removesuffix("全店"))
            require(stem not in value, "調査対象外店舗を調査データに含めないでください")

    for area, original_area in zip(areas, master["areas"]):
        object_at(area, "area")
        require(type(area.get("no")) is int and area["no"] == original_area["no"]
                and area.get("name") == original_area["name"], "エリア番号・名称・順序が不一致")
        cats = object_at(area.get("cats"), "cats")
        require(set(cats) == set(CATS), "3分類が必要です")
        for category in CATS:
            group = object_at(cats[category], category)
            require(group.get("status") in ("ok", "none", "unchecked"), "分類statusが不正")
            shops = list_at(group.get("shops"), "shops")
            state = object_at(group.get("research"), "分類research")
            require(state.get("status") in ("unresearched", "failed", "confirmed"), "分類の調査状態が不正")
            checks = object_at(state.get("checks"), "checks")
            for key, evidence in checks.items():
                proof(evidence, "checks." + key, start, generated)
            if group["status"] == "none":
                required = {"ikyu_area_list", "tabelog_area_list", "tabelog_station_search"}
                if category != "cafe":
                    required |= {"hotel_list", "hotel_openings", "hotel_at_checks"}
                require(not shops and state["status"] == "confirmed" and required <= set(checks),
                        "該当なしの厳格チェックが未完了です")
            if group["status"] == "ok":
                require(shops and state["status"] == "confirmed", "okには店舗と確認済み分類が必要です")
            elif group["status"] == "unchecked":
                require(state["status"] != "confirmed", "未確認分類の状態が矛盾しています")
            if state["status"] == "failed":
                require(isinstance(state.get("error"), str) and state["error"].strip(), "分類の取得失敗理由が必要です")
            for shop in shops:
                object_at(shop, "shop")
                for key in ("name", "shop", "station", "exit", "links", "plans", "tabelog", "new", "research"):
                    require(key in shop, "店舗の必須項目: " + key)
                permitted_name(shop["name"])
                for key in ("shop", "station", "exit"):
                    text_at(shop[key], key, nullable=(key == "shop"))
                require(shop["station"].strip(), "最寄り駅が必要です")
                require(type(shop["new"]) is bool, "newはbooleanです")
                identity = (normalize(shop["name"]), normalize(shop["shop"] or ""))
                require(identity not in seen_names, "店舗の重複: " + shop["name"])
                seen_names.add(identity)
                mid = shop.get("master_id")
                base = None
                if mid is not None:
                    require(mid in master_index and mid not in seen_ids, "master_idの不明または重複")
                    seen_ids.add(mid)
                    no, old_category, source = master_index[mid]
                    require(area["no"] == no and shop.get("master_name") == source["name"]
                            and shop.get("master_category") == old_category and shop["new"] is False,
                            "店舗マスターの出典を改変しないでください")
                    base = master_shop(source, old_category)
                else:
                    require(shop["new"], "新規店はnew=trueです")
                score = shop["tabelog"]
                require(score is None or (type(score) in (int, float) and math.isfinite(score) and 3 <= score <= 5),
                        "tabelogはnullまたは3〜5の数値です（3未満は本表対象外）")
                links = list_at(shop["links"], "links")
                require(len(links) <= 1, "1店舗の予約リンクは1件です")
                for link in links:
                    object_at(link, "link")
                    require(link.get("site") in DOMAINS, "予約サイトコードが不正")
                    url = allowed_url(link.get("url"), link["site"])
                    require(url not in seen_urls, "予約URLの重複店舗")
                    seen_urls.add(url)
                plans = list_at(shop["plans"], "plans")
                require(plans, "少なくとも1つのプラン枠が必要です")
                research = object_at(shop["research"], "research")
                status = research.get("status")
                require(status in ("confirmed", "unresearched", "failed"), "店舗の調査状態が不正")
                evidence = object_at(research.get("evidence"), "evidence")
                genres = list_at(research.get("genres", []), "genres")
                require(all(isinstance(g, str) for g in genres) and not forbidden_genres.intersection(genres),
                        "対象外ジャンルを調査データに残さないでください")
                require(research.get("date_suitable") is not False, "デート向けでない店は残せません")
                require(research.get("in_hotel") is None or type(research["in_hotel"]) is bool, "in_hotelはbool/null")
                for key, value in evidence.items():
                    proof(value, key, start, generated)
                    require(value.get("kind", "observed") != "inferred" or key.endswith("/country") or key.endswith("/cc"),
                            "推測できるのはテーマ国のみです")
                    if value.get("kind") == "inferred":
                        require(shop["name"] in notes["status"] and value["quote"] in notes["status"],
                                "テーマ国の推測根拠をnotes.statusにも記録してください")
                for index, plan in enumerate(plans):
                    object_at(plan, "plan")
                    require(set(PLAN_FIELDS) <= set(plan), "プラン項目が不足しています")
                    for key in ("theme", "period_text", "country", "cc", "price_text", "days_text", "time_text"):
                        text_at(plan[key], key, nullable=True)
                    pstart, pend = (date_at(plan[k], k, nullable=True) for k in ("start", "end"))
                    require(not (pstart and pend and pstart > pend), "プラン開始日が終了日より後です")
                    require(not (pend and pend < start or pstart and pstart > end), "期間外プランです")
                    price = plan["price_min"]
                    require(price is None or type(price) is int and price > 0, "price_minは正の整数/nullです")
                    require(plan["wd"] in ("on", "no", "off") and plan["we"] in ("on", "no", "off"), "曜日コードが不正")
                    tags = list_at(plan["sw"], "sw")
                    require(all(isinstance(t, str) and t in sweets for t in tags) and len(tags) == len(set(tags)), "swが不正")
                    require(plan["cc"] is None or plan["cc"] in FLAGS, "国旗コードが不正")
                    require(plan["cc"] is None or known(plan["country"]), "国旗には国名が必要です")
                    if status == "confirmed":
                        for key in PLAN_FIELDS:
                            value = plan[key]
                            if (key in ("wd", "we") and value == "off") or not known(value):
                                continue
                            require(f"/plans/{index}/{key}" in evidence, f"{shop['name']}: {key}の出典がありません")
                if status != "confirmed":
                    require(base is not None and all(shop[k] == base[k] for k in
                            ("name", "shop", "station", "exit", "links", "plans", "tabelog", "new")),
                            "未調査・取得失敗を確定情報に変換しないでください")
                    require(research.get("in_hotel") is None and not evidence and research.get("checked_on") is None,
                            "未調査・取得失敗に確認済み情報は持たせられません")
                    require(group["status"] == "unchecked" and shop["name"] in notes["status"], "未調査店を確認状況に列挙してください")
                    if status == "failed":
                        require(isinstance(research.get("error"), str) and research["error"].strip(), "取得失敗理由が必要です")
                        attempted = date_at(research.get("attempted_on"), "attempted_on")
                        require(start <= attempted <= generated and shop.get("links_note") == "取得失敗",
                                "取得失敗の試行日・links_noteが必要です")
                        failed += 1
                    else:
                        require(shop.get("links_note") == "未調査", "未調査のlinks_noteが必要です")
                        unresearched += 1
                else:
                    confirmed += 1
                    require(research.get("error") is None, "成功状態に取得失敗理由があります")
                    require(len(links) == 1 and group["status"] in ("ok", "unchecked"), "確認済み店には予約リンクが必要です")
                    checked = date_at(research.get("checked_on"), "checked_on")
                    require(start <= checked <= generated and type(research.get("in_hotel")) is bool,
                            "確認日・ホテル内外の根拠が必要です")
                    for key in ("reservation", "classification"):
                        require(key in evidence, key + "の根拠が必要です")
                    reservation = evidence["reservation"]
                    proof(reservation, "reservation", start, generated, links[0]["url"])
                    require(reservation.get("booking") is True and reservation.get("menu") is True,
                            "ATの予約ページとメニューの確認が必要です")
                    require(links[0]["site"] != "ik" or reservation.get("meal") in ("lunch", "breakfast"),
                            "一休はランチ・朝食だけが対象です")
                    for key in ("name", "shop", "station", "exit", "tabelog"):
                        if (base is None or shop[key] != base[key]) and known(shop[key]):
                            require("/" + key in evidence, key + "の変更根拠がありません")
                require(category == expected_category(shop), "ホテル内外または9000円基準の分類が不一致")
    auxiliary_names = set()
    for key in ("candidates", "excluded"):
        for item in list_at(data[key], key):
            object_at(item, key)
            permitted_name(item.get("name"))
            aux_name = normalize(item["name"])
            require(aux_name not in auxiliary_names, "候補・除外店の重複")
            auxiliary_names.add(aux_name)
            require(not any(normalize(item["name"]) == name for name, _ in seen_names), "本表との重複候補・除外店")
            if key == "candidates":
                text_at(item.get("area"), "candidate.area")
                text_at(item.get("note"), "candidate.note")
                proof(item.get("evidence"), "candidate.evidence", start, generated)
                require(item.get("status") == "unresolved", "候補は検索抜粋のみ確認したunresolvedです")
                if item.get("url"):
                    allowed_url(item["url"])
            else:
                require(isinstance(item.get("reason"), str) and item["reason"].strip(), "除外理由が必要です")
                proof(item.get("evidence"), "excluded.evidence", start, generated)
    if meta["purpose"] == "unresearched":
        require(confirmed == 0 and not data["candidates"] and not data["excluded"] and
                len(seen_ids) == len(master_index), "未調査スケルトンの欠落または確認済み化")
    if meta["purpose"] == "test":
        require(all("TEST_ONLY" in shop["name"] for a in areas for c in a["cats"].values()
                    for shop in c["shops"]), "テスト店舗名はTEST_ONLYを含めてください")
    else:
        require(all("test_only" not in name for name, _ in seen_names), "テスト店を調査結果にしないでください")
    return {"areas": 14, "shops": len(seen_names), "confirmed": confirmed,
            "unresearched": unresearched, "failed": failed,
            "expected_cards": confirmed, "purpose": meta["purpose"], "publishable": False,
            "limits": "オフライン検証。URL疎通・引用の真偽・調査網羅性はWebで未確認。公開機能は未実装。"}
