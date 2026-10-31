import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review as rv

OWNER = "919873945238"
IST = rv.IST


def at(day, hour, minute=0):
    return datetime.datetime(2026, 11, day, hour, minute, tzinfo=IST)


class FakeStore:
    def __init__(self):
        self.q = [{"day": 0, "title": "Intro", "post": "Hello world post with 20 products."},
                  {"day": 1, "title": "LifeCycle-OS", "post": "Project 1/20: LifeCycle-OS saves 5 hours."}]
        self.p, self.st, self.pause = {}, None, False

    def queue(self): return self.q
    def posted(self): return self.p
    def state(self): return dict(self.st) if self.st else None
    def save_state(self, st): self.st = dict(st)
    def paused(self): return self.pause
    def mark_posted(self, day, title, text, urn, cycle): self.p[str(day)] = {"urn": urn, "text": text}


class FakeWA:
    def __init__(self): self.sent = []
    def text(self, to, body): self.sent.append(("text", to, body))
    def buttons(self, to, body, buttons): self.sent.append(("buttons", to, body))
    def opener(self, to, day, title): self.sent.append(("template", to, f"{day}:{title}"))


def make(rewrite=lambda d, f: d + "\nShorter hook.", publish=None):
    store, wa, published = FakeStore(), FakeWA(), []
    def pub(text):
        published.append(text)
        return "urn:li:share:1"
    r = rv.Review(store, wa, publish or pub, rewrite, OWNER)
    return r, store, wa, published


def opened(store):
    """Simulate the owner having messaged recently, so free-form messages are allowed."""
    store.st = {"last_inbound": at(1, 23).isoformat()}


class Window(unittest.TestCase):
    def test_outside_the_window_only_the_approved_template_is_sent(self):
        r, store, wa, _ = make()
        r.tick(at(2, 0))
        self.assertEqual([k for k, *_ in wa.sent], ["template"])
        self.assertFalse(store.st["shown"])

    def test_first_reply_opens_the_chat_and_shows_the_post(self):
        r, store, wa, _ = make()
        r.tick(at(2, 0))
        self.assertEqual(r.on_message(OWNER, "button", "show", at(2, 1)), "shown")
        self.assertTrue(store.st["shown"])
        self.assertIn("buttons", [k for k, *_ in wa.sent])

    def test_cannot_approve_before_seeing_the_post(self):
        r, store, wa, published = make()
        r.tick(at(2, 0))
        self.assertEqual(r.on_message(OWNER, "button", "post", at(2, 1)), "shown")
        self.assertEqual(store.st["status"], "waiting")

    def test_inside_the_window_the_full_post_is_sent_at_midnight(self):
        r, store, wa, _ = make()
        opened(store)
        r.tick(at(2, 0))
        self.assertIn("buttons", [k for k, *_ in wa.sent])
        self.assertTrue(store.st["shown"])


class Schedule(unittest.TestCase):
    def test_midnight_sends_the_next_post_for_review(self):
        r, store, wa, _ = make()
        opened(store)
        self.assertEqual(r.tick(at(2, 0, 5)), "sent")
        self.assertEqual(store.st["day"], 0)
        self.assertTrue(any(k == "buttons" for k, *_ in wa.sent))

    def test_midnight_sends_only_once(self):
        r, store, *_ = make()
        r.tick(at(2, 0))
        self.assertEqual(r.tick(at(2, 0, 30)), "already-sent")

    def test_hourly_reminders_until_nine(self):
        r, store, *_ = make()
        r.tick(at(2, 0))
        for h in range(1, 9):
            self.assertEqual(r.tick(at(2, h)), "reminded")
        self.assertEqual(store.st["reminders"], 8)

    def test_no_reply_by_nine_means_nothing_is_posted(self):
        r, store, wa, published = make()
        r.tick(at(2, 0))
        self.assertEqual(r.tick(at(2, 9)), "held")
        self.assertEqual(published, [])
        self.assertEqual(r.tick(at(3, 0)), "sent")          # same post comes back
        self.assertEqual(store.st["day"], 0)

    def test_paused_does_nothing(self):
        r, store, wa, _ = make()
        store.pause = True
        self.assertEqual(r.tick(at(2, 0)), "paused")
        self.assertEqual(wa.sent, [])


class Replies(unittest.TestCase):
    def test_only_the_owner_can_approve(self):
        r, store, _, published = make()
        opened(store)
        r.tick(at(2, 0))
        self.assertEqual(r.on_message("911111111111", "button", "post", at(2, 1)), "ignored")
        self.assertEqual(store.st["status"], "waiting")

    def test_approval_before_nine_publishes_at_nine(self):
        r, store, _, published = make()
        opened(store)
        r.tick(at(2, 0))
        self.assertEqual(r.on_message(OWNER, "button", "post", at(2, 2)), "approved")
        self.assertEqual(published, [])
        self.assertEqual(r.tick(at(2, 9)), "posted")
        self.assertEqual(len(published), 1)
        self.assertIn("0", store.p)

    def test_approval_after_nine_publishes_at_once(self):
        r, store, _, published = make()
        opened(store)
        r.tick(at(2, 0))
        self.assertEqual(r.on_message(OWNER, "text", "Post it", at(2, 10)), "posted")
        self.assertEqual(len(published), 1)

    def test_skip_holds_the_post(self):
        r, store, _, published = make()
        opened(store)
        r.tick(at(2, 0))
        self.assertEqual(r.on_message(OWNER, "button", "skip", at(2, 1)), "skipped")
        self.assertEqual(r.tick(at(2, 9)), "idle")
        self.assertEqual(published, [])

    def test_feedback_rewrites_and_resends(self):
        r, store, wa, _ = make()
        opened(store)
        r.tick(at(2, 0))
        self.assertEqual(r.on_message(OWNER, "text", "make the hook punchier", at(2, 1)), "revised")
        self.assertIn("Shorter hook.", store.st["draft"])
        self.assertEqual(store.st["status"], "draft")

    def test_edits_survive_until_posted(self):
        r, store, _, published = make()
        opened(store)
        r.tick(at(2, 0))
        r.on_message(OWNER, "text", "tweak it", at(2, 1))
        r.tick(at(2, 9))                                       # not approved: held
        r.tick(at(3, 0))                                       # comes back with the edit
        self.assertIn("Shorter hook.", store.st["draft"])
        r.on_message(OWNER, "button", "post", at(3, 1))
        r.tick(at(3, 9))
        self.assertIn("Shorter hook.", published[0])

    def test_rewrite_cannot_invent_numbers(self):
        r, store, wa, _ = make(rewrite=lambda d, f: d + " Used by 10,000 people.")
        opened(store)
        r.tick(at(2, 0))
        self.assertEqual(r.on_message(OWNER, "text", "add social proof", at(2, 1)), "rewrite-rejected")
        self.assertNotIn("10,000", store.st["draft"])

    def test_rewrite_must_pass_the_content_guard(self):
        r, store, *_ = make(rewrite=lambda d, f: d + " \u2014 with a dash")
        opened(store)
        r.tick(at(2, 0))
        self.assertEqual(r.on_message(OWNER, "text", "anything", at(2, 1)), "rewrite-rejected")

    def test_numbers_from_feedback_are_allowed(self):
        r, store, *_ = make(rewrite=lambda d, f: d + " 300 downloads.")
        opened(store)
        r.tick(at(2, 0))
        self.assertEqual(r.on_message(OWNER, "text", "mention 300 downloads", at(2, 1)), "revised")

    def test_blocked_post_is_never_published(self):
        r, store, wa, published = make()
        store.q[0]["post"] = "Draft [ADD REAL METRIC]"
        opened(store)
        r.tick(at(2, 0))
        r.on_message(OWNER, "button", "post", at(2, 1))
        self.assertEqual(r.tick(at(2, 9)), "blocked")
        self.assertEqual(published, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
