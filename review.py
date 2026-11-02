"""WhatsApp review loop for the LinkedIn auto-pilot.

Nothing is ever published without the owner tapping "Post it".

Schedule (IST), driven by an hourly tick:
  00:00        send tonight's post for review (full text + buttons)
  01:00-08:00  hourly reminder while there is no reply
  09:00        publish if approved; otherwise hold and ask again tonight

Replies (only from OWNER_WHATSAPP):
  "Post it"     approve (publishes at 09:00, or at once if it is already past 09:00)
  "Skip today"  nothing goes out today; the same post comes back tonight
  "Show post"   resend the full current draft
  any text      treated as feedback: the post is rewritten and sent back for review

All side effects (WhatsApp, LinkedIn, AI, storage) are injected, so the logic is
fully testable without network access.
"""
import datetime
import re

import post as ap

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
BUTTONS = [("post", "Post it"), ("skip", "Skip today"), ("show", "Show post")]
NUM = re.compile(r"\d[\d,.]*")


def ist_now(now=None):
    return (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(IST)


def numbers(text):
    return {n.strip(".,") for n in NUM.findall(text)}


def check_rewrite(original, feedback, rewrite):
    """Reasons a rewrite must not be used. Empty list means it is safe to show."""
    problems = ap.guard({"post": rewrite})
    new_numbers = numbers(rewrite) - numbers(original) - numbers(feedback)
    if new_numbers:
        problems.append("the rewrite added numbers that were not in the post or your feedback: "
                        + ", ".join(sorted(new_numbers)))
    return problems


class Review:
    def __init__(self, store, whatsapp, publish, rewrite, owner, refresh=None):
        self.store, self.wa, self.publish, self.rewrite, self.owner = store, whatsapp, publish, rewrite, owner
        self.refresh = refresh   # refresh(post) -> (draft, notes): live checks before review

    # ---------------------------------------------------------------- helpers
    def _next_post(self):
        queue, posted = self.store.queue(), self.store.posted()
        for p in sorted(queue, key=lambda p: p["day"]):
            if str(p["day"]) not in posted:
                return p
        return None

    def _window_open(self, st, t):
        last = (st or {}).get("last_inbound")
        if not last:
            return False
        return t - datetime.datetime.fromisoformat(last) < datetime.timedelta(hours=23, minutes=30)

    def _send_draft(self, st, intro):
        if st.get("notes"):
            intro += "\n\nBefore you approve:\n" + "\n".join("• " + n for n in st["notes"])
        self.wa.text(self.owner, intro)
        self.wa.text(self.owner, st["draft"])
        self.wa.buttons(self.owner, f"Day {st['day']}: {st['title']}. Post it?", BUTTONS)

    # ------------------------------------------------------------------ ticks
    def tick(self, now=None):
        t = ist_now(now)
        today = t.date().isoformat()
        st = self.store.state()
        if self.store.paused():
            return "paused"

        if t.hour == 9:
            if st and st.get("cycle") == today and st.get("status") == "approved":
                return self._do_publish(st)
            if st and st.get("cycle") == today and st.get("status") in ("waiting", "draft"):
                st["status"] = "held"
                self.store.save_state(st)
                self.wa.text(self.owner, f"No reply, so Day {st['day']} was not posted. I'll send it again tonight.")
                return "held"
            return "idle"

        if t.hour == 0:
            if st and st.get("cycle") == today:
                return "already-sent"
            p = self._next_post()
            if not p:
                return "series-finished"
            if st and st.get("day") == p["day"] and st.get("draft"):
                draft = st["draft"]            # keep earlier edits to the same post
            else:
                draft = p["post"]
            notes = []
            if self.refresh:
                draft, notes = self.refresh({**p, "post": draft})
            last = (st or {}).get("last_inbound")
            st = {"cycle": today, "day": p["day"], "title": p["title"], "draft": draft, "notes": notes,
                  "status": "waiting", "reminders": 0, "shown": False, "last_inbound": last}
            if self._window_open(st, t):
                st["shown"] = True
                self.store.save_state(st)
                self._send_draft(st, "Here's this morning's LinkedIn post. Reply with any changes, or tap a button.")
            else:
                self.store.save_state(st)
                self.wa.opener(self.owner, p["day"], p["title"])   # approved template; any reply opens the chat
            return "sent"

        if 1 <= t.hour <= 8 and st and st.get("cycle") == today and st.get("status") in ("waiting", "draft"):
            st["reminders"] = st.get("reminders", 0) + 1
            self.store.save_state(st)
            if self._window_open(st, t):
                self.wa.buttons(self.owner, f"Reminder: Day {st['day']} ({st['title']}) goes out at 9 AM only if you approve it.", BUTTONS)
            else:
                self.wa.opener(self.owner, st["day"], st["title"])
            return "reminded"
        return "idle"

    # --------------------------------------------------------------- replies
    def on_message(self, sender, kind, value, now=None):
        if sender != self.owner:
            return "ignored"
        st = self.store.state()
        if not st or st.get("status") in ("posted",):
            self.wa.text(self.owner, "Nothing is waiting for review right now. The next post comes at midnight.")
            return "nothing-pending"
        t = ist_now(now)
        st["last_inbound"] = t.isoformat()
        self.store.save_state(st)
        if not st.get("shown", True):
            st["shown"] = True
            self.store.save_state(st)
            self._send_draft(st, "Here's this morning's LinkedIn post. Reply with any changes, or tap a button.")
            return "shown"
        command = value.strip().lower() if kind == "button" else ""
        if kind == "text" and value.strip().lower() in ("post", "post it", "approve", "yes"):
            command = "post"
        if kind == "text" and value.strip().lower() in ("skip", "skip today"):
            command = "skip"

        if command == "post":
            st["status"] = "approved"
            self.store.save_state(st)
            if t.hour >= 9:
                return self._do_publish(st)
            self.wa.text(self.owner, f"Approved. Day {st['day']} goes live at 9:00 AM.")
            return "approved"
        if command == "skip":
            st["status"] = "skipped"
            self.store.save_state(st)
            self.wa.text(self.owner, f"Skipped. Day {st['day']} will come back tonight.")
            return "skipped"
        if command == "show":
            self._send_draft(st, "Here's the current version:")
            return "shown"

        feedback = value.strip()
        new = self.rewrite(st["draft"], feedback)
        problems = check_rewrite(st["draft"], feedback, new)
        if problems:
            self.wa.text(self.owner, "I couldn't apply that safely: " + "; ".join(problems)
                         + ". Try rephrasing, or tap Post it to use the current version.")
            return "rewrite-rejected"
        st["draft"], st["status"] = new, "draft"
        self.store.save_state(st)
        self._send_draft(st, "Updated with your feedback:")
        return "revised"

    # --------------------------------------------------------------- publish
    def _do_publish(self, st):
        problems = ap.guard({"post": st["draft"]})
        if problems:
            self.wa.text(self.owner, "Blocked before posting: " + "; ".join(problems))
            return "blocked"
        urn = self.publish(st["draft"])
        self.store.mark_posted(st["day"], st["title"], st["draft"], urn, st["cycle"])
        st["status"] = "posted"
        self.store.save_state(st)
        link = f"https://www.linkedin.com/feed/update/{urn}/" if urn else "(link unavailable)"
        self.wa.text(self.owner, f"Posted Day {st['day']}: {link}")
        return "posted"
