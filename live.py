"""Refresh a post from live data just before it goes to WhatsApp for review.

Three checks, in order:
  1. Every link in the post must load. Broken links are reported, never silently removed.
  2. Known live numbers are pulled fresh (for example ANCHOR's YouTube videos and subscribers).
  3. The product's live page is read, and AI updates the post only where the page shows
     newer or different facts. Every number the AI adds must appear on the live page.

Nothing here publishes anything. The refreshed draft and a list of what changed go to
WhatsApp, and the owner still approves every word.
"""
import html
import json
import re
import urllib.request

LINK = re.compile(r"(?:https?://)?(?:www\.)?(?:[a-z0-9-]+\.)+(?:com|in)(?:/[^\s|)]*)?")
PLACEHOLDER = re.compile(r"\[ADD[^\]]*\]", re.I)
NUM = re.compile(r"\d[\d,.]*")


def fetch(url, timeout=15):
    if not url.startswith("http"):
        url = "https://" + url
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (LinkedIn auto-pilot link check)",
                                               "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def page_text(raw):
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


def links_in(text):
    return sorted({u.rstrip(".,") for u in LINK.findall(text) if "amazon." not in u})


def broken_links(text, get=fetch):
    bad = []
    for u in links_in(text):
        try:
            status, _ = get(u)
            if status >= 400:
                bad.append(f"{u} ({status})")
        except Exception as e:  # noqa: BLE001
            bad.append(f"{u} ({type(e).__name__})")
    return bad


def youtube_stats(handle, get=fetch):
    """Public channel header numbers, e.g. {'subscribers': '24', 'videos': '127'}."""
    _, raw = get(f"https://www.youtube.com/@{handle}")
    out = {}
    for value, kind in re.findall(r'"content":"([\d.,KM]+) (subscribers|videos)"', raw):
        out.setdefault(kind, value)
    return out


def refresh_anchor(draft, get=fetch):
    stats = youtube_stats("ANCHOR_AT", get)
    if not {"videos", "subscribers"} <= stats.keys():
        return draft, ["Couldn't read ANCHOR's YouTube numbers, so the post keeps the last known ones."]
    new = re.sub(r"YouTube @ANCHOR_AT: [\d.,KM]+ videos so far, with [\d.,KM]+ subscribers",
                 f"YouTube @ANCHOR_AT: {stats['videos']} videos so far, with {stats['subscribers']} subscribers", draft)
    note = f"ANCHOR YouTube now: {stats['videos']} videos, {stats['subscribers']} subscribers."
    return new, ([note] if new != draft else [])


FACT_UPDATERS = {15: refresh_anchor}

AI_RULES = """You check a LinkedIn post against the live product page it describes.
Return JSON only: {"post": "<full post>", "changes": ["<plain sentence per change>"]}.
Change the post only where the live page clearly shows newer or different facts (a feature, a count, a status).
Never add a number that does not appear in the live page text. Keep the structure, links, hashtags, tone and length.
No em dashes or en dashes. If nothing needs changing, return the post unchanged with an empty changes list."""


def ai_update(draft, live_text, ask):
    """ask(system, user) -> text. Returns (post, changes); rejects any invented number."""
    try:
        out = json.loads(re.sub(r"^```(?:json)?|```$", "", ask(AI_RULES, f"POST:\n{draft}\n\nLIVE PAGE:\n{live_text[:12000]}").strip()))
        post, changes = out["post"].strip(), [c for c in out.get("changes", []) if c]
    except Exception:  # noqa: BLE001
        return draft, []
    allowed = set(NUM.findall(draft)) | set(NUM.findall(live_text))
    invented = {n.strip(".,") for n in NUM.findall(post)} - {n.strip(".,") for n in allowed}
    if invented or not changes:
        return draft, []
    return post, changes


def refresh(post, ask=None, get=fetch):
    """Return (draft, notes) for one queued post."""
    draft, notes = post["post"], []

    bad = broken_links(draft + " " + post.get("first_comment", ""), get)
    if bad:
        notes.append("Broken links: " + ", ".join(bad) + ". Fix them or skip this post.")

    updater = FACT_UPDATERS.get(post["day"])
    if updater:
        draft, more = updater(draft, get)
        notes += more

    live_link = post.get("link") or next(iter(LINK.findall(post.get("first_comment", ""))), None)
    if ask and live_link and "amazon." not in live_link and not bad:
        try:
            _, raw = get(live_link)
            draft2, changes = ai_update(draft, page_text(raw), ask)
            if changes:
                draft = draft2
                notes += ["Updated from the live site: " + c for c in changes]
        except Exception:  # noqa: BLE001
            notes.append("Couldn't read the live site, so the post wasn't checked against it.")

    if PLACEHOLDER.search(draft):
        notes.append("This post still has a blank to fill: " + ", ".join(PLACEHOLDER.findall(draft))
                     + ". Reply with the real numbers and I'll add them.")
    return draft, notes
