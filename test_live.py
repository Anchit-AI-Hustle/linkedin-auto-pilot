import json, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live

YT = '..."content":"31 subscribers"... "content":"140 videos"...'
PAGE = "<html><body><h1>LoosenUp</h1><p>Now with 3-minute breaks and 12 languages.</p></body></html>"


def getter(pages, broken=()):
    def get(url):
        if any(b in url for b in broken):
            return 404, ""
        for key, body in pages.items():
            if key in url:
                return 200, body
        return 200, "<html>ok</html>"
    return get


ANCHOR = {"day": 15, "title": "ANCHOR", "first_comment": "Listen: https://anchor.anchit-tandon.com",
          "post": "• YouTube @ANCHOR_AT: 127 videos so far, with 24 subscribers and growing\n🎧 anchor.anchit-tandon.com"}
LOOSEN = {"day": 4, "title": "LoosenUp", "first_comment": "Try: https://loosenup.anchit-tandon.com",
          "post": "Project 4/20: LoosenUp, 2-minute breaks.\n🌐 loosenup.anchit-tandon.com"}


class Live(unittest.TestCase):
    def test_anchor_numbers_are_refreshed_from_youtube(self):
        draft, notes = live.refresh(ANCHOR, get=getter({"youtube.com": YT}))
        self.assertIn("140 videos so far, with 31 subscribers", draft)
        self.assertTrue(any("140 videos" in n for n in notes))

    def test_unreadable_youtube_keeps_last_numbers(self):
        draft, notes = live.refresh(ANCHOR, get=getter({"youtube.com": "nothing"}))
        self.assertIn("127 videos", draft)
        self.assertTrue(any("last known" in n for n in notes))

    def test_broken_links_are_reported_not_removed(self):
        draft, notes = live.refresh(LOOSEN, get=getter({}, broken=("loosenup",)))
        self.assertIn("loosenup.anchit-tandon.com", draft)
        self.assertTrue(any("Broken links" in n for n in notes))

    def test_ai_update_from_the_live_page_is_applied_with_a_note(self):
        ask = lambda s, u: json.dumps({"post": LOOSEN["post"].replace("2-minute", "3-minute"), "changes": ["Breaks are now 3 minutes."]})
        draft, notes = live.refresh(LOOSEN, ask=ask, get=getter({"loosenup": PAGE}))
        self.assertIn("3-minute", draft)
        self.assertTrue(any("Updated from the live site" in n for n in notes))

    def test_ai_cannot_add_numbers_missing_from_the_live_page(self):
        ask = lambda s, u: json.dumps({"post": LOOSEN["post"] + " Used by 50,000 people.", "changes": ["Added users."]})
        draft, notes = live.refresh(LOOSEN, ask=ask, get=getter({"loosenup": PAGE}))
        self.assertEqual(draft, LOOSEN["post"])

    def test_bad_ai_output_leaves_the_post_unchanged(self):
        draft, _ = live.refresh(LOOSEN, ask=lambda s, u: "not json", get=getter({"loosenup": PAGE}))
        self.assertEqual(draft, LOOSEN["post"])

    def test_placeholder_asks_for_the_real_numbers(self):
        post = {"day": 17, "title": "Books", "first_comment": "", "post": "Results so far: [ADD KDP SALES]"}
        _, notes = live.refresh(post, get=getter({}))
        self.assertTrue(any("Reply with the real numbers" in n for n in notes))

    def test_amazon_links_are_not_fetched(self):
        calls = []
        def get(url): calls.append(url); return 200, ""
        live.refresh({"day": 17, "title": "B", "first_comment": "https://www.amazon.in/x", "post": "amazon.in/x"}, ask=lambda s, u: "{}", get=get)
        self.assertFalse(any("amazon" in c for c in calls))


if __name__ == "__main__":
    unittest.main(verbosity=1)
