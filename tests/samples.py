"""TEST_ONLY fixtures. These are invented test values, never restaurant research."""
from afternoon_tea.data import create_data, unknown_plan
from afternoon_tea.master import load_master


def evidence(url, **extra):
    return {"url": url, "checked_on": "2026-11-06",
            "quote": "TEST_ONLY: synthetic fixture, not real restaurant information", **extra}


def sample():
    data = create_data(load_master(), "2026-11-06")
    data["metadata"]["purpose"] = "test"
    data["notes"]["status"] = "TEST_ONLY テスト専用。実在店の調査結果ではありません。"
    data["notes"]["pending_candidates"] = []
    for area in data["areas"]:
        for cat in area["cats"].values():
            cat["shops"] = []
    for category, price in (("cafe", 4000), ("hotel", 8999), ("lux", 9000)):
        url = f"https://restaurant.ikyu.com/__TEST_ONLY__/{category}"
        plan = unknown_plan()
        plan.update(theme="TEST_ONLY アフタヌーンティー", start="2026-11-06", end="2026-12-16",
                    price_min=price, price_text=f"TEST_ONLY {price:,}円（税サ込通常価格）",
                    wd="on", we="no", sw=["ichigo", "scone"], days_text="TEST_ONLY 平日のみ",
                    time_text="TEST_ONLY 14:00〜16:00、2時間制")
        shop = {"name": f"TEST_ONLY_{category}", "shop": None if category == "cafe" else "TEST_ONLYラウンジ",
                "station": "TEST_ONLY駅", "exit": "要確認", "links": [{"site": "ik", "url": url}],
                "plans": [plan], "tabelog": None, "new": True,
                "research": {"status": "confirmed", "checked_on": "2026-11-06",
                             "in_hotel": category != "cafe", "evidence": {}, "error": None}}
        proofs = shop["research"]["evidence"]
        for key in ("name", "shop", "station"):
            if shop[key] is not None:
                proofs["/" + key] = evidence(url)
        for key, value in plan.items():
            if value is not None and value != []:
                proofs[f"/plans/0/{key}"] = evidence(url)
        proofs["reservation"] = evidence(url, booking=True, menu=True, meal="lunch")
        proofs["classification"] = evidence(url)
        group = data["areas"][0]["cats"][category]
        group.update(status="ok", shops=[shop], research={"status": "confirmed", "checks": {}})
    return data
