import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("build_page", ROOT / "tools/videos/build_page.py")
page = importlib.util.module_from_spec(spec)
spec.loader.exec_module(page)


class PageOrder(unittest.TestCase):
    def test_page_uses_the_same_order_and_preserves_live_links_and_explicit_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            class FixedTime(page.datetime.datetime):
                @classmethod
                def now(cls, tz=None):
                    return cls(2030, 1, 1, 0, tzinfo=page.IST)

            root = Path(tmp)
            site = root / "site"
            queue = [{"day": d, "title": str(d), "date": "2030-01-01", "post": "x", "first_comment": "",
                      "priority": d == 25, "defer": d == 7} for d in (25, 10, 8, 7, 17)]
            (root / "posts.json").write_text(json.dumps(queue))
            (root / "posted.json").write_text(json.dumps({"8": {"urn": "urn:li:share:8"}, "17": {"skipped": True}}))
            with patch.multiple(page, ROOT=str(root), SITE=str(site), VIDEOS=str(site / "videos")), patch.object(page.datetime, "datetime", FixedTime):
                page.main()
            html = (site / "index.html").read_text()
            data = json.loads(html.split('<script id="data" type="application/json">')[1].split('</script>')[0])
            self.assertNotIn(17, [p["day"] for p in data])
            self.assertEqual([p["day"] for p in data], [7, 8, 10, 25])
            queued = [p for p in data if p["status"] == "Queued"]
            self.assertEqual([p["day"] for p in queued], [7, 10, 25])
            self.assertEqual([p["when"] for p in queued], [
                "Earliest: Tue 1 Jan, 2:00 AM IST (estimate)",
                "Earliest: Tue 1 Jan, 8:00 AM IST (estimate)",
                "Earliest: Tue 1 Jan, 2:00 PM IST (estimate)"])
            self.assertTrue(all("(estimate)" in p["when"] for p in queued))
            live = next(p for p in data if p["day"] == 8)
            self.assertEqual(live["live"], "https://www.linkedin.com/feed/update/urn:li:share:8/")
            self.assertIn("A day awaiting its reviewed video holds the queue.", html)


if __name__ == "__main__":
    unittest.main()
