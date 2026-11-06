"""Offline tests for Step 6 network discovery; absolutely no real HTTP calls."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from afternoon_tea import research


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


if __name__ == "__main__":
    unittest.main()
