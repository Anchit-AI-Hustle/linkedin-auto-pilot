import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import post as ap

HERE = os.path.dirname(os.path.abspath(__file__))


class LittleText(unittest.TestCase):
    def test_reserved_characters_are_escaped(self):
        self.assertEqual(ap.to_little_text("Plans (Basic) [x] a_b"), r"Plans \(Basic\) \[x\] a\_b")

    def test_hashtags_become_real_hashtags(self):
        self.assertEqual(ap.to_little_text("#ProductManagement #20ProductsIn20Days"),
                         r"{hashtag|\#|ProductManagement} {hashtag|\#|20ProductsIn20Days}")

    def test_plain_text_is_untouched(self):
        self.assertEqual(ap.to_little_text("Scaled ₹15L to ₹80L → done"), "Scaled ₹15L to ₹80L → done")


class Guard(unittest.TestCase):
    def test_placeholder_blocks(self):
        self.assertTrue(ap.guard({"post": "Users: [ADD REAL METRIC]"}))

    def test_dash_blocks(self):
        self.assertTrue(ap.guard({"post": "One \u2014 two"}))

    def test_too_long_blocks(self):
        self.assertTrue(ap.guard({"post": "x" * 3001}))

    def test_every_queued_post_passes(self):
        with open(os.path.join(HERE, "posts.json"), encoding="utf-8") as fh:
            queue = json.load(fh)
        self.assertEqual(len(queue), 22)
        for p in queue:
            self.assertEqual(ap.guard(p), [], f"Day {p['day']} failed the guard")


class Schedule(unittest.TestCase):
    queue = [{"day": 0, "date": "2026-11-02", "title": "a", "post": "x"},
             {"day": 1, "date": "2026-11-03", "title": "b", "post": "y"}]

    def test_starts_with_day_zero(self):
        self.assertEqual(ap.pick(self.queue, {}, "2026-12-01")["day"], 0)

    def test_next_day_follows_in_order(self):
        self.assertEqual(ap.pick(self.queue, {"0": {"date": "2026-12-01"}}, "2026-12-02")["day"], 1)

    def test_only_one_post_per_day(self):
        self.assertIsNone(ap.pick(self.queue, {"0": {"date": "2026-12-01"}}, "2026-12-01"))

    def test_stops_when_series_is_done(self):
        done = {"0": {"date": "2026-12-01"}, "1": {"date": "2026-12-02"}}
        self.assertIsNone(ap.pick(self.queue, done, "2026-12-03"))

    def test_queue_dates_are_consecutive_and_unique(self):
        with open(os.path.join(HERE, "posts.json"), encoding="utf-8") as fh:
            queue = json.load(fh)
        dates = [p["date"] for p in queue]
        self.assertEqual(len(dates), len(set(dates)))
        self.assertEqual([p["day"] for p in queue], list(range(len(queue))))


class LivePathWithFakeLinkedIn(unittest.TestCase):
    def test_publishes_once_with_correct_request(self):
        import shutil, tempfile
        tmp = tempfile.mkdtemp()
        for f in ("posts.json", "posted.json"):
            shutil.copy(os.path.join(HERE, f), tmp)
        calls = []
        def fake_call(method, path, token, version, body=None):
            calls.append((method, path, version, body))
            if path == "/v2/userinfo":
                return 200, {}, {"sub": "abc123"}
            return 201, {"x-restli-id": "urn:li:share:999"}, {}
        old = (ap.QUEUE, ap.STATE, ap.PAUSE, ap.call)
        ap.QUEUE, ap.STATE, ap.PAUSE = (os.path.join(tmp, "posts.json"), os.path.join(tmp, "posted.json"),
                                        os.path.join(tmp, "PAUSE"))
        ap.call = fake_call
        env = dict(LINKEDIN_ACCESS_TOKEN="t", POST_DATE="2026-12-01", DRY_RUN="false")
        saved = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            self.assertEqual(ap.main(), 0)
            method, path, version, body = calls[-1]
            self.assertEqual((method, path, version), ("POST", "/rest/posts", "202605"))
            self.assertEqual(body["author"], "urn:li:person:abc123")
            self.assertEqual(body["visibility"], "PUBLIC")
            self.assertEqual(body["lifecycleState"], "PUBLISHED")
            self.assertIn("{hashtag|\\#|20ProductsIn20Days}", body["commentary"])
            state = json.load(open(ap.STATE))
            self.assertEqual(state["0"]["urn"], "urn:li:share:999")
            n = len(calls)
            ap.main()  # second run the same day must not post again
            self.assertEqual(len(calls), n)
        finally:
            ap.QUEUE, ap.STATE, ap.PAUSE, ap.call = old
            for k, v in saved.items():
                if v is None: os.environ.pop(k, None)
                else: os.environ[k] = v
            shutil.rmtree(tmp)


class EndToEnd(unittest.TestCase):
    def run_script(self, **env):
        e = dict(os.environ, **env)
        e.pop("LINKEDIN_ACCESS_TOKEN", None)
        return subprocess.run([sys.executable, os.path.join(HERE, "post.py")], env=e,
                              capture_output=True, text=True)

    def test_dry_run_changes_nothing(self):
        before = open(os.path.join(HERE, "posted.json")).read()
        r = self.run_script(DRY_RUN="true", POST_DATE="2026-11-02")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("DRY RUN", r.stdout)
        self.assertEqual(open(os.path.join(HERE, "posted.json")).read(), before)

    def test_pause_stops_real_posting(self):
        path = os.path.join(HERE, "PAUSE")
        existed = os.path.exists(path)
        if not existed:
            open(path, "w").close()
        try:
            r = self.run_script(DRY_RUN="false", POST_DATE="2026-11-02")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Paused", r.stdout)
        finally:
            if not existed:
                os.remove(path)

    def test_missing_token_fails_loudly_when_live(self):
        path = os.path.join(HERE, "PAUSE")
        existed = os.path.exists(path)
        if existed:
            os.rename(path, path + ".bak")
        try:
            r = self.run_script(DRY_RUN="false", POST_DATE="2026-11-02")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("LINKEDIN_ACCESS_TOKEN is missing", r.stdout + r.stderr)
        finally:
            if existed:
                os.rename(path + ".bak", path)

    def test_check_mode_needs_a_token(self):
        e = dict(os.environ); e.pop("LINKEDIN_ACCESS_TOKEN", None)
        r = subprocess.run([sys.executable, os.path.join(HERE, "post.py"), "--check"], env=e,
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("missing", r.stdout + r.stderr)


class NoGitHub(unittest.TestCase):
    def test_github_links_are_blocked_in_post_and_first_comment(self):
        self.assertTrue(ap.guard({"post": "Code: github.com/Anchit-AI-Hustle/x"}))
        self.assertTrue(ap.guard({"post": "ok", "first_comment": "https://raw.githubusercontent.com/a/b"}))
        self.assertEqual(ap.guard({"post": "Try it: parwah-hq.anchit-tandon.com", "first_comment": "https://anchit-tandon.com"}), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
