"""Build an explicitly unresearched skeleton; never infer current restaurant facts."""
import copy
import datetime as dt
import re

JST = dt.timezone(dt.timedelta(hours=9))
CATS = ("cafe", "hotel", "lux")
PLAN_FIELDS = ("theme", "start", "end", "period_text", "sw", "country", "cc",
               "price_min", "price_text", "wd", "we", "days_text", "time_text")


def period(start=None, now=None):
    if start is None:
        now = now or dt.datetime.now(JST)
        if now.tzinfo is None:
            raise ValueError("now にはタイムゾーンが必要です")
        start = now.astimezone(JST).date()
    elif isinstance(start, str):
        start = dt.date.fromisoformat(start)
    return {"start": start.isoformat(), "end": (start + dt.timedelta(days=40)).isoformat()}


def unknown_plan():
    plan = dict.fromkeys(PLAN_FIELDS)
    plan.update(sw=[], wd="off", we="off")
    return plan


def master_shop(source, category):
    name, shop = source["name"], None
    if category != "cafe":
        match = re.fullmatch(r"(.+)（([^（）]+)）", name)
        if match:
            name, shop = match.groups()
            name = re.sub(r"\s*\d+F$", "", name)
    return {"master_id": source["id"], "master_name": source["name"],
            "master_category": category, "name": name, "shop": shop,
            "station": source["station"], "exit": source["exit"],
            "links": [], "links_note": "未調査", "plans": [unknown_plan()],
            "tabelog": None, "new": False,
            "research": {"status": "unresearched", "checked_on": None,
                         "in_hotel": None, "evidence": {}, "error": None}}


def create_data(master, start=None, now=None):
    per = period(start, now)
    areas, unresearched = [], []
    for source_area in master["areas"]:
        area = {"no": source_area["no"], "name": source_area["name"], "cats": {
            c: {"status": "unchecked", "shops": [],
                "research": {"status": "unresearched", "checks": {}}} for c in CATS}}
        for category, group in source_area["cats"].items():
            # Current price is unknown. The generator also treats unknown hotels as hotel.
            target = "cafe" if category == "cafe" else "hotel"
            for source in group["shops"]:
                area["cats"][target]["shops"].append(master_shop(source, category))
                unresearched.append(source["name"])
        areas.append(area)
    return {"generated": per["start"], "period": per, "areas": areas,
            "candidates": [], "excluded": [],
            "notes": {"status": "未調査。全14エリア・全42分類の検索は未実施。未調査店："
                      + "／".join(unresearched),
                      "pending_candidates": copy.deepcopy(master["candidates"])},
            "metadata": {"schema_version": 1, "purpose": "unresearched",
                         "master_sha256": master["source_sha256"]}}
