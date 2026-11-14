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
        self.assertEqual(len(queue), 26)
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

    def test_one_post_per_slot(self):
        done = {"0": {"at": "2026-12-01T08:00:00+05:30"}}
        self.assertIsNone(ap.pick(self.queue, done, self.T("2026-12-01T13:01:00+05:30")))   # still the 8 AM slot

    def test_missed_schedule_is_caught_up_within_the_slot(self):
        done = {"0": {"at": "2026-12-01T08:30:00+05:30"}}
        self.assertEqual(ap.pick(self.queue, done, self.T("2026-12-01T15:17:00+05:30"))["day"], 1)   # 2 PM slot, 77 min late
        self.assertEqual(ap.pick(self.queue, done, self.T("2026-12-01T19:40:00+05:30"))["day"], 1)   # a run this late in the slot still posts
        old = ap.CATCH_UP_HOURS; ap.CATCH_UP_HOURS = 4; self.addCleanup(lambda: setattr(ap, "CATCH_UP_HOURS", old))
        self.assertIsNone(ap.pick(self.queue, done, self.T("2026-12-01T18:30:00+05:30")))          # a shorter window, when set, is respected
        self.assertEqual(ap.pick(self.queue, done, self.T("2026-12-01T18:30:00+05:30"), force=True)["day"], 1)

    def test_hourly_runs_never_double_post(self):
        done = {"0": {"at": "2026-12-01T15:17:00+05:30"}}
        for hh in ("16:17", "17:17", "19:17"):
            self.assertIsNone(ap.pick(self.queue, done, self.T(f"2026-12-01T{hh}:00+05:30")))
        self.assertEqual(ap.pick(self.queue, done, self.T("2026-12-01T20:17:00+05:30"))["day"], 1)

    def test_slot_boundaries_including_2am(self):
        self.assertEqual(ap.slot_start(self.T("2026-12-02T02:17:00+05:30")).hour, 2)
        self.assertEqual(ap.slot_start(self.T("2026-12-02T01:59:00+05:30")).isoformat()[:13], "2026-12-01T20")
        self.assertEqual(ap.slot_start(self.T("2026-12-02T23:00:00+05:30")).hour, 20)

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
        prev_auto = ap.AUTO_COMMENT; ap.AUTO_COMMENT = True; self.addCleanup(lambda: setattr(ap, "AUTO_COMMENT", prev_auto))
        env = dict(LINKEDIN_ACCESS_TOKEN="t", POST_AT="2026-12-01T08:00:00+05:30", DRY_RUN="false", ATTACH_VIDEO="false", PREVIEW_CARD="false", REQUIRE_READY="false", AUTO_COMMENT="true")
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
            self.assertEqual(len(state), 1)
            first = next(iter(state.values()))
            self.assertEqual(first["urn"], "urn:li:share:999")
            self.assertTrue(first.get("commented"))
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
        sleep = ap.time.sleep; ap.time.sleep = lambda s: None
        try:
            self.assertFalse(ap.add_first_comment("t", "202510", "urn:li:share:1", "urn:li:person:a", "hi"))
        finally:
            ap.call = original; ap.time.sleep = sleep

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
            self.assertIsNone(ap.video_for(4))                       # not reviewed yet: never attached
            json.dump([os.path.basename(self.clip)], open(os.path.join(self.tmp, "verified.json"), "w"))
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


class PreviewCard(unittest.TestCase):
    def setUp(self):
        self.saved = (ap.call, ap.put_bytes, ap.page_meta, ap.urllib.request.urlopen)

    def tearDown(self):
        ap.call, ap.put_bytes, ap.page_meta, ap.urllib.request.urlopen = self.saved

    def test_every_queued_post_has_its_own_link(self):
        with open(os.path.join(HERE, "posts.json"), encoding="utf-8") as fh:
            for p in json.load(fh):
                url = ap.site_url(p)
                self.assertTrue(url and url.startswith("https://"), p["day"])
                self.assertNotIn("/get", url, p["day"])

    def test_card_uses_page_tags_and_uploaded_image(self):
        ap.page_meta = lambda url: {"title": "Parwah - the family superapp", "description": "Family superapp", "image": "https://x/og.png"}
        class R:
            def read(self, *a): return b"PNG" * 10
        ap.urllib.request.urlopen = lambda *a, **k: R()
        calls = []
        def fake_call(method, path, token, version, body=None):
            calls.append(path)
            return 200, {}, {"value": {"uploadUrl": "https://up/img", "image": "urn:li:image:I1"}}
        ap.call = fake_call
        ap.put_bytes = lambda *a, **k: "e"
        post_ = {"title": "Parwah", "post": "x\n\U0001f310 Website: parwah-hq.anchit-tandon.com\n\U0001f5c2\ufe0f Portfolio: anchit-tandon.com"}
        card = ap.article_content("t", "v", "urn:li:person:a", post_)
        self.assertEqual(card["article"], {"source": "https://parwah-hq.anchit-tandon.com", "title": "Parwah - the family superapp",
                                           "description": "Family superapp", "thumbnail": "urn:li:image:I1"})
        self.assertEqual(calls, ["/rest/images?action=initializeUpload"])

    def test_card_still_goes_out_if_image_fails(self):
        ap.page_meta = lambda url: {"title": "T", "description": "", "image": "https://x/og.png"}
        def boom(*a, **k): raise OSError("no image")
        ap.urllib.request.urlopen = boom
        card = ap.article_content("t", "v", "a", {"title": "T", "post": "\U0001f310 Website: a.example.com"})
        self.assertEqual(card["article"], {"source": "https://a.example.com", "title": "T"})


class Readiness(unittest.TestCase):
    """A post never goes out before its demo video is a reviewed full tour."""
    def run_live(self, verified):
        import tempfile, shutil
        tmp = tempfile.mkdtemp()
        for f in ("post.py", "posts.json"):
            shutil.copy(os.path.join(HERE, f), tmp)
        json.dump({}, open(os.path.join(tmp, "posted.json"), "w"))
        vids = os.path.join(tmp, "linkedin-auto-pilot", "videos"); os.makedirs(vids)
        open(os.path.join(vids, "demo-00-23-products.mp4"), "wb").write(b"x" * 100)
        if verified:
            json.dump(["demo-00-23-products.mp4"], open(os.path.join(vids, "verified.json"), "w"))
        e = dict(os.environ, DRY_RUN="false", LINKEDIN_ACCESS_TOKEN="fake", POST_AT="2030-01-01T08:05:00+05:30",
                 USE_2160P="false", LINKEDIN_VERSION="202605")
        r = subprocess.run([sys.executable, os.path.join(tmp, "post.py")], env=e, capture_output=True, text=True)
        return r, json.load(open(os.path.join(tmp, "posted.json")))

    def test_holds_when_video_not_reviewed(self):
        r, posted = self.run_live(verified=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Holding Day", r.stdout)
        self.assertEqual(posted, {})

    def test_reviewed_video_proceeds_to_publishing(self):
        r, posted = self.run_live(verified=True)       # fake token: it gets past the gate and fails at LinkedIn
        self.assertNotIn("Holding", r.stdout)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(posted, {})

    def test_catch_up_comments_only_recent_and_missing(self):
        calls = []
        saved = (ap.add_first_comment, ap.person_urn)
        saved_auto = ap.AUTO_COMMENT; ap.AUTO_COMMENT = True
        ap.add_first_comment = lambda t, v, urn, a, text: calls.append(urn) or True
        ap.person_urn = lambda t, v: "urn:li:person:a"
        posted = {"3": {"urn": "u3", "at": "2030-01-01T02:00:00+05:30", "commented": True},
                  "4": {"urn": "u4", "at": "2030-01-01T03:00:00+05:30"},
                  "1": {"urn": "u1", "at": "2029-12-30T03:00:00+05:30"}}
        queue = [{"day": d, "first_comment": "hi"} for d in (1, 3, 4)]
        import tempfile
        saved_state = ap.STATE; ap.STATE = tempfile.mktemp()
        try:
            ap.catch_up_comments("t", "v", queue, posted, self_T("2030-01-01T08:00:00+05:30"))
        finally:
            ap.add_first_comment, ap.person_urn = saved; ap.STATE = saved_state; ap.AUTO_COMMENT = saved_auto
        self.assertEqual(calls, ["u4"])
        self.assertTrue(posted["4"]["commented"])


def self_T(s):
    return datetime.datetime.fromisoformat(s)


class Defer(unittest.TestCase):
    def test_deferred_posts_go_after_everything_else(self):
        q = [{"day": d, "post": "x", "defer": d in (7, 10)} for d in range(6, 12)]
        done = {"6": {"at": "2030-01-01T02:05:00+05:30"}}
        order = []
        for slot in ("08", "14", "20"):
            p = ap.pick(q, done, datetime.datetime.fromisoformat(f"2030-01-01T{slot}:20:00+05:30"))
            order.append(p["day"]); done[str(p["day"])] = {"at": f"2030-01-01T{slot}:20:00+05:30"}
        self.assertEqual(order, [8, 9, 11])
        p = ap.pick(q, done, datetime.datetime.fromisoformat("2030-01-02T02:20:00+05:30"))
        self.assertEqual(p["day"], 7)


class NotBlocked(unittest.TestCase):
    """One post waiting for its video must never stall the posts behind it."""
    def test_a_post_without_a_reviewed_video_is_passed_over(self):
        q = [{"day": d, "post": "x"} for d in range(14, 18)]
        ready = lambda p: p["day"] in (15, 17)
        now = datetime.datetime.fromisoformat("2030-01-01T08:20:00+05:30")
        self.assertEqual(ap.pick(q, {}, now, ready=ready)["day"], 15)
        done = {"15": {"at": "2030-01-01T08:20:00+05:30"}}
        later = datetime.datetime.fromisoformat("2030-01-01T14:20:00+05:30")
        self.assertEqual(ap.pick(q, done, later, ready=ready)["day"], 17)
        self.assertEqual(ap.pick(q, done, later, ready=lambda p: True)["day"], 14)   # goes out as soon as it is ready

    def test_when_nothing_is_ready_the_next_post_is_named_so_the_run_can_say_why(self):
        q = [{"day": d, "post": "x"} for d in range(14, 16)]
        now = datetime.datetime.fromisoformat("2030-01-01T08:20:00+05:30")
        self.assertEqual(ap.pick(q, {}, now, ready=lambda p: False)["day"], 14)


class Priority(unittest.TestCase):
    def test_a_priority_post_goes_out_in_the_very_next_slot(self):
        q = [{"day": d, "post": "x", "defer": d == 7} for d in range(6, 12)] + [{"day": 25, "post": "x", "priority": True}]
        done = {"6": {"at": "2030-01-01T02:05:00+05:30"}}
        p = ap.pick(q, done, datetime.datetime.fromisoformat("2030-01-01T08:20:00+05:30"))
        self.assertEqual(p["day"], 25)
        done["25"] = {"at": "2030-01-01T08:20:00+05:30"}
        p = ap.pick(q, done, datetime.datetime.fromisoformat("2030-01-01T14:20:00+05:30"))
        self.assertEqual(p["day"], 8)                              # then the series carries on in order

    def test_the_bonus_post_is_queued_first_and_passes_the_guard(self):
        with open(os.path.join(HERE, "posts.json"), encoding="utf-8") as fh:
            queue = json.load(fh)
        with open(os.path.join(HERE, "posted.json"), encoding="utf-8") as fh:
            posted = json.load(fh)
        bonus = [p for p in queue if p["title"] == "Find a Flatmate"]
        self.assertEqual(len(bonus), 1)
        self.assertEqual(ap.guard(bonus[0]), [])
        self.assertIn("6 to 7 hours", bonus[0]["post"])
        self.assertEqual(ap.site_url(bonus[0]), "https://find-a-flatmate.anchit-tandon.com")
        self.assertEqual(bonus[0]["post"].count("#"), 5)
        if str(bonus[0]["day"]) not in posted:
            nxt = ap.pick(queue, {k: v for k, v in posted.items() if not v.get("at")}, datetime.datetime.fromisoformat("2030-01-01T08:20:00+05:30"))
            self.assertEqual(nxt["title"], "Find a Flatmate")

    def test_books_on_amazon_stays_out(self):
        with open(os.path.join(HERE, "posted.json"), encoding="utf-8") as fh:
            self.assertTrue(json.load(fh)["17"].get("skipped"))

class RetryTests(unittest.TestCase):
    """Passing LinkedIn errors are retried, but publishing is never repeated when it may have gone out."""

    class _Resp:
        status, headers = 200, {"ETag": "e1"}
        def __init__(self, body=b'{"ok": 1}'): self.body = body
        def read(self): return self.body
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def setUp(self):
        self.saved = (ap.urllib.request.urlopen, ap.time.sleep)
        ap.time.sleep = lambda s: None
        self.attempts = 0

    def tearDown(self):
        ap.urllib.request.urlopen, ap.time.sleep = self.saved

    def _fail_then_ok(self, failures, exc_factory):
        def fake(req, data=None, timeout=None):
            self.attempts += 1
            if self.attempts <= failures:
                raise exc_factory()
            return self._Resp()
        ap.urllib.request.urlopen = fake

    @staticmethod
    def _http(code):
        import io
        return lambda: ap.urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b"err"))

    def test_get_retries_5xx_then_succeeds(self):
        self._fail_then_ok(2, self._http(503))
        status, _, body = ap.call("GET", "/v2/userinfo", "t", "202605")
        self.assertEqual((status, body, self.attempts), (200, {"ok": 1}, 3))

    def test_get_retries_network_errors(self):
        self._fail_then_ok(1, lambda: ap.urllib.error.URLError("reset"))
        ap.call("GET", "/rest/videos/x", "t", "202605")
        self.assertEqual(self.attempts, 2)

    def test_gives_up_after_all_retries(self):
        self._fail_then_ok(99, self._http(502))
        with self.assertRaises(SystemExit):
            ap.call("GET", "/v2/userinfo", "t", "202605")
        self.assertEqual(self.attempts, len(ap.RETRY_WAITS) + 1)

    def test_publish_is_not_repeated_after_5xx_or_timeout(self):
        for exc in (self._http(500), lambda: ap.urllib.error.URLError("timed out"), lambda: TimeoutError()):
            self.attempts = 0
            self._fail_then_ok(1, exc)
            with self.assertRaises(SystemExit):
                ap.call("POST", "/rest/posts", "t", "202605", {"a": 1})
            self.assertEqual(self.attempts, 1)

    def test_publish_retries_on_rate_limit_only(self):
        self._fail_then_ok(1, self._http(429))
        ap.call("POST", "/rest/posts", "t", "202605", {"a": 1})
        self.assertEqual(self.attempts, 2)

    def test_comment_not_repeated_after_5xx(self):
        self._fail_then_ok(1, self._http(500))
        with self.assertRaises(SystemExit):
            ap.call("POST", "/rest/socialActions/x/comments", "t", "202605", {"a": 1})
        self.assertEqual(self.attempts, 1)

    def test_client_errors_and_401_fail_fast(self):
        for code in (400, 401, 403):
            self.attempts = 0
            self._fail_then_ok(1, self._http(code))
            with self.assertRaises(SystemExit):
                ap.call("GET", "/v2/userinfo", "t", "202605")
            self.assertEqual(self.attempts, 1)

    def test_upload_part_retries(self):
        self._fail_then_ok(2, self._http(503))
        self.assertEqual(ap.put_bytes("https://up", b"x", "t"), "e1")
        self.assertEqual(self.attempts, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
