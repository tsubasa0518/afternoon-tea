"""Offline tests for Step 6 network discovery; absolutely no real HTTP calls."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from afternoon_tea import research
from afternoon_tea.data import create_data, unknown_plan
from afternoon_tea.master import load_master
from afternoon_tea.validation import validate_data


class ExampleBrowser:
    def __init__(self):
        self.count = 0
        self.errors = []
        self.queries = []

    def query(self, name, domain):
        self.queries.append((name, domain))
        self.count += 1
        return (["https://" + domain + "/restaurant/example"] if domain == "restaurant.ikyu.com" else [],
                "https://www.bing.com/search?q=test")

    def fetch(self, url):
        self.count += 1
        return """<html><head><script>do not include this</script></head>
        <body><h1>アフタヌーンティー</h1><p>予約する 6,500円</p>
        <a href="https://restaurant.ikyu.com/restaurant/example">リンク</a></body></html>"""


class ResearchTests(unittest.TestCase):
    def test_partial_category_preserves_unknown_shops_without_rendering_them_as_confirmed(self):
        data = create_data(load_master(), "2026-11-06")
        data["metadata"]["purpose"] = "research"
        group = data["areas"][0]["cats"]["cafe"]
        shop = group["shops"][0]
        url = "https://tabelog.com/__TEST_ONLY__/course"
        shop["links"] = [{"site": "tb", "url": url}]
        shop["links_note"] = "確認済み"
        plan = shop["plans"][0]
        plan.update(theme="TEST_ONLY plan", price_min=4000,
                    price_text="TEST_ONLY 4,000円", wd="on",
                    days_text="TEST_ONLY 平日", time_text="TEST_ONLY 11:00")
        proof = lambda quote, **extra: {"url": url, "checked_on": "2026-11-06",
                                        "quote": "TEST_ONLY " + quote, **extra}
        shop["research"].update(status="confirmed", checked_on="2026-11-06",
                                in_hotel=False, evidence={
            "/plans/0/theme": proof("plan title"),
            "/plans/0/price_min": proof("price"),
            "/plans/0/price_text": proof("price text"),
            "/plans/0/wd": proof("weekdays"),
            "/plans/0/days_text": proof("days"),
            "/plans/0/time_text": proof("time"),
            "reservation": proof("menu and booking", booking=True, menu=True),
            "classification": proof("cafe", in_hotel=False),
        })
        group["status"] = "ok"
        group["research"]["status"] = "partial"
        result = validate_data(data, load_master())
        self.assertEqual((result["confirmed"], result["unresearched"]), (1, 69))

    def test_site_url_excludes_external(self):
        self.assertEqual(
            research.site_url("https://restaurant.ikyu.com/1000", "restaurant.ikyu.com"),
            "https://restaurant.ikyu.com/1000")
        self.assertIsNone(research.site_url("https://evil.example/1000", "restaurant.ikyu.com"))
        self.assertIsNone(research.site_url("/redirect?url=https://restaurant.ikyu.com", "restaurant.ikyu.com"))
        self.assertIsNone(research.site_url("https://restaurant.ikyu.com.evil.com/x", "restaurant.ikyu.com"))

    def test_extract_clues_only(self):
        info = research.inspect_page(
            "<html><script>fake data</script><body>アフタヌーンティー 予約 6,500円</body></html>",
            "https://restaurant.ikyu.com/1000", "2026-11-06")
        self.assertTrue(info["has_at_text"])
        self.assertTrue(info["has_booking_text"])
        self.assertEqual(info["price_clues"], ["6,500円"])
        self.assertEqual(info["status"], "unverified_evidence_only")

    def test_research_order_stops_on_clue(self):
        browser = ExampleBrowser()
        sample = {"master_name": "TEST_ONLY example"}
        result = research.research_one(browser, sample, "2026-11-06")
        self.assertEqual(result["status"], "requires_plan_review")
        self.assertEqual(len(browser.queries), 1)
        self.assertEqual(browser.queries[0][1], "restaurant.ikyu.com")

    def test_unverified_clues_never_published(self):
        browser = ExampleBrowser()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("afternoon_tea.research.staging_directory", return_value=Path(tmp)):
                path, audit = research.run(
                    start=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat(),
                    max_shops=1, browser=browser)
            self.assertEqual(audit["confirmed_shops"], 0)
            self.assertEqual(audit["attempted_shops"], 1)
            self.assertFalse(audit["all_tokyo_coverage_verified"])
            self.assertFalse((path / "index.html").exists())
            import json
            data = json.loads(next(path.glob("data_*.json")).read_text(encoding="utf-8"))
            self.assertEqual(data["candidates"], [])
            self.assertEqual(data["metadata"]["purpose"], "research")
            self.assertEqual(
                sum(s["research"]["status"] == "confirmed" for a in data["areas"]
                    for c in a["cats"].values() for s in c["shops"]), 0)
            self.assertEqual(audit["unattempted_shops"], 69)
            self.assertEqual(audit["failed_shops"], 1)
            self.assertEqual(audit["candidate_resolution"], "unresolved_not_researched")
            self.assertEqual(audit["area_discovery"], "not_performed")
            states = [s["research"]["status"] for a in data["areas"]
                      for c in a["cats"].values() for s in c["shops"]]
            self.assertEqual(states.count("failed"), 1)
            self.assertEqual(states.count("unresearched"), 69)
            self.assertIn("未試行69店", data["notes"]["status"])

    def test_attempted_robots_failure_reason_is_not_fabricated(self):
        class DeniedBrowser:
            count = 1
            errors = []
            def query(self, name, domain):
                raise RuntimeError("robots_unknown_or_disallowed")
        with tempfile.TemporaryDirectory() as tmp:
            with patch("afternoon_tea.research.staging_directory", return_value=Path(tmp)):
                path, audit = research.run(
                    start=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat(),
                    max_shops=1, browser=DeniedBrowser())
            self.assertIn("robots_unknown_or_disallowed", audit["shop_errors"]["master-001"])
            self.assertEqual(audit["unattempted_shops"], 69)
            self.assertEqual(len(audit["area_status"]), 14)
            self.assertTrue(all(x["coverage"] == "incomplete" for x in audit["area_status"]))


if __name__ == "__main__":
    unittest.main()
