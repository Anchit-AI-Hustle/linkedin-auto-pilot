import datetime
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
        self.assertEqual(ap.to_little_text("#ProductManagement #BuildInPublic"),
                         r"{hashtag|\#|ProductManagement} {hashtag|\#|BuildInPublic}")

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
        self.assertEqual(len(queue), 25)
        for p in queue:
            self.assertEqual(ap.guard(p), [], f"Day {p['day']} failed the guard")


class Schedule(unittest.TestCase):
    queue = [{"day": 0, "date": "2026-11-02", "title": "a", "post": "x"},
             {"day": 1, "date": "2026-11-03", "title": "b", "post": "y"}]

    T = staticmethod(lambda s: datetime.datetime.fromisoformat(s))

    def test_starts_with_day_zero(self):
        self.assertEqual(ap.pick(self.queue, {}, self.T("2026-12-01T08:00:00+05:30"))["day"], 0)

    def test_next_post_after_six_hours(self):
        done = {"0": {"at": "2026-12-01T02:00:00+05:30"}}
        self.assertEqual(ap.pick(self.queue, done, self.T("2026-12-01T08:00:00+05:30"))["day"], 1)

    def test_no_second_post_in_the_same_slot(self):
        done = {"0": {"at": "2026-12-01T08:00:00+05:30"}}
        self.assertIsNone(ap.pick(self.queue, done, self.T("2026-12-01T08:40:00+05:30")))
        self.assertIsNone(ap.pick(self.queue, done, self.T("2026-12-01T12:59:00+05:30")))

    def test_delayed_run_still_posts_once_gap_passes(self):
        done = {"0": {"at": "2026-12-01T08:00:00+05:30"}}
        self.assertEqual(ap.pick(self.queue, done, self.T("2026-12-01T13:01:00+05:30"))["day"], 1)

    def test_stops_when_series_is_done(self):
        done = {"0": {"at": "2026-12-01T02:00:00+05:30"}, "1": {"at": "2026-12-01T08:00:00+05:30"}}
        self.assertIsNone(ap.pick(self.queue, done, self.T("2026-12-02T08:00:00+05:30")))

    def test_queue_dates_are_consecutive_and_unique(self):
        with open(os.path.join(HERE, "posts.json"), encoding="utf-8") as fh:
            queue = json.load(fh)
        self.assertEqual([p["day"] for p in queue], list(range(len(queue))))


class LivePathWithFakeLinkedIn(unittest.TestCase):
    def test_publishes_once_with_correct_request(self):
        import shutil, tempfile
        tmp = tempfile.mkdtemp()
        shutil.copy(os.path.join(HERE, "posts.json"), tmp)
        with open(os.path.join(tmp, "posted.json"), "w") as fh:
            fh.write("{}")
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
        env = dict(LINKEDIN_ACCESS_TOKEN="t", POST_AT="2026-12-01T08:00:00+05:30", DRY_RUN="false", ATTACH_VIDEO="false")
        saved = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            self.assertEqual(ap.main(), 0)
            posts_calls = [c for c in calls if c[1] == "/rest/posts"]
            self.assertEqual(len(posts_calls), 1)
            method, path, version, body = posts_calls[0]
            self.assertEqual((method, path, version), ("POST", "/rest/posts", "202605"))
            cm = calls[-1]  # the first comment follows the post, on the new post's URN
            self.assertEqual(cm[1], "/rest/socialActions/urn%3Ali%3Ashare%3A999/comments")
            self.assertEqual(cm[3]["actor"], "urn:li:person:abc123")
            self.assertTrue(cm[3]["message"]["text"].strip())
            self.assertEqual(body["author"], "urn:li:person:abc123")
            self.assertEqual(body["visibility"], "PUBLIC")
            self.assertEqual(body["lifecycleState"], "PUBLISHED")
            self.assertIn("{hashtag|\\#|BuildInPublic}", body["commentary"])
            state = json.load(open(ap.STATE))
            self.assertEqual(state["0"]["urn"], "urn:li:share:999")
            self.assertTrue(state["0"].get("commented"))
            n = len(calls)
            ap.main()  # a second run in the same slot must not post again
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
        r = self.run_script(DRY_RUN="true", POST_AT="2030-01-01T08:00:00+05:30")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue("DRY RUN" in r.stdout or "Nothing to post" in r.stdout, r.stdout)
        self.assertEqual(open(os.path.join(HERE, "posted.json")).read(), before)

    def test_pause_stops_real_posting(self):
        path = os.path.join(HERE, "PAUSE")
        existed = os.path.exists(path)
        if not existed:
            open(path, "w").close()
        try:
            r = self.run_script(DRY_RUN="false", POST_AT="2030-01-01T08:00:00+05:30")
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
            r = self.run_script(DRY_RUN="false", POST_AT="2030-01-01T08:00:00+05:30")
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



class FirstComment(unittest.TestCase):
    def test_request_shape_matches_comments_api(self):
        path, body = ap.comment_request("urn:li:share:7525391747045339136", "urn:li:person:abc", "Tried it?")
        self.assertEqual(path, "/rest/socialActions/urn%3Ali%3Ashare%3A7525391747045339136/comments")
        self.assertEqual(body, {"actor": "urn:li:person:abc", "object": "urn:li:share:7525391747045339136",
                                "message": {"text": "Tried it?"}})

    def test_failed_comment_never_breaks_the_post(self):
        original = ap.call
        def boom(*a, **k): raise SystemExit("LinkedIn API error 403: no")
        ap.call = boom
        try:
            self.assertFalse(ap.add_first_comment("t", "202510", "urn:li:share:1", "urn:li:person:a", "hi"))
        finally:
            ap.call = original

    def test_no_comment_without_urn_or_text(self):
        self.assertFalse(ap.add_first_comment("t", "v", "", "a", "hi"))
        self.assertFalse(ap.add_first_comment("t", "v", "urn:li:share:1", "a", "  "))


class VideoUpload(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.clip = os.path.join(self.tmp, "demo-04-loosenup.mp4")
        open(self.clip, "wb").write(b"x" * 2500)
        self.saved = (ap.call, ap.put_bytes, ap.time.sleep)
        ap.time.sleep = lambda s: None

    def tearDown(self):
        ap.call, ap.put_bytes, ap.time.sleep = self.saved

    def test_full_flow_uploads_every_part_and_waits_for_available(self):
        calls, puts, polls = [], [], iter(["PROCESSING", "AVAILABLE"])
        def fake_call(method, path, token, version, body=None):
            calls.append((method, path, body))
            if "initializeUpload" in path:
                return 200, {}, {"value": {"video": "urn:li:video:V1", "uploadToken": "",
                    "uploadInstructions": [{"uploadUrl": "https://up/1", "firstByte": 0, "lastByte": 1999},
                                           {"uploadUrl": "https://up/2", "firstByte": 2000, "lastByte": 2499}]}}
            if path.startswith("/rest/videos/"):
                return 200, {}, {"status": next(polls)}
            return 200, {}, {}
        ap.call = fake_call
        ap.put_bytes = lambda url, data, token, ct="application/octet-stream": puts.append((url, len(data))) or "etag-" + url[-1]
        self.assertEqual(ap.upload_video("t", "202605", "urn:li:person:a", self.clip), "urn:li:video:V1")
        self.assertEqual(puts, [("https://up/1", 2000), ("https://up/2", 500)])
        init = calls[0][2]["initializeUploadRequest"]
        self.assertEqual((init["owner"], init["fileSizeBytes"]), ("urn:li:person:a", 2500))
        fin = [c for c in calls if "finalizeUpload" in c[1]][0][2]["finalizeUploadRequest"]
        self.assertEqual(fin["uploadedPartIds"], ["etag-1", "etag-2"])

    def test_any_failure_means_text_only_never_a_missed_post(self):
        def boom(*a, **k): raise SystemExit("LinkedIn API error 403")
        ap.call = boom
        self.assertIsNone(ap.upload_video("t", "v", "urn:li:person:a", self.clip))

    def test_processing_failed_is_not_attached(self):
        def fake_call(method, path, token, version, body=None):
            if "initializeUpload" in path:
                return 200, {}, {"value": {"video": "urn:li:video:V2", "uploadInstructions": [
                    {"uploadUrl": "https://up/1", "firstByte": 0, "lastByte": 2499}]}}
            if path.startswith("/rest/videos/"):
                return 200, {}, {"status": "PROCESSING_FAILED"}
            return 200, {}, {}
        ap.call = fake_call
        ap.put_bytes = lambda *a, **k: "e"
        self.assertIsNone(ap.upload_video("t", "v", "urn:li:person:a", self.clip))

    def test_finds_rendered_video_by_post_number(self):
        saved = ap.VIDEOS
        ap.VIDEOS = self.tmp
        try:
            os.environ["USE_2160P"] = "false"
            self.assertEqual(ap.video_for(4), self.clip)
            self.assertIsNone(ap.video_for(5))
            os.environ["USE_2160P"] = "true"
            saved_rel = ap.RELEASE
            ap.RELEASE = "http://127.0.0.1:9/nothing/"          # unreachable: must fall back to the web copy
            try:
                self.assertEqual(ap.video_for(4), self.clip)
            finally:
                ap.RELEASE = saved_rel
        finally:
            ap.VIDEOS = saved

if __name__ == "__main__":
    unittest.main(verbosity=2)
