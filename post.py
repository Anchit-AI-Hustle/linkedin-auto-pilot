"""LinkedIn auto-pilot: publishes the next approved post from posts.json, one every 6 hours.

Publish-only by design: it creates one post per day on the author's own profile
through LinkedIn's official Posts API. It never likes, comments on other
people's posts, messages or connects.

Environment:
  LINKEDIN_ACCESS_TOKEN  member token with scopes: openid profile w_member_social
  LINKEDIN_VERSION       API version header, YYYYMM (default 202605)
  DRY_RUN                "true" prints what would be posted and changes nothing
  POST_AT                optional ISO time override (default: now in IST)
  MIN_GAP_HOURS          minimum hours between posts (default 5)

Usage:
  python post.py           publish the next post, if none has gone out today
  python post.py --check   only confirm the token works, post nothing

The series starts when the PAUSE file is removed (the "Start posting" workflow
does this) and then publishes the next unposted day, one per day, in order.
"""
import datetime
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(HERE, "posts.json")
STATE = os.path.join(HERE, "posted.json")
PAUSE = os.path.join(HERE, "PAUSE")
API = "https://api.linkedin.com"
VIDEOS = os.path.join(HERE, "linkedin-auto-pilot", "videos")  # rendered by the "Demo videos" workflow
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

# Characters LinkedIn's little text format reserves (Microsoft Learn, "little text format").
RESERVED = re.compile(r"[\\|{}@\[\]()<>#*_~]")
HASHTAG = re.compile(r"\\#([A-Za-z0-9]+)")


def to_little_text(text):
    """Escape every reserved character, then turn #Word back into a real hashtag."""
    escaped = RESERVED.sub(lambda m: "\\" + m.group(0), text)
    return HASHTAG.sub(lambda m: "{hashtag|\\#|" + m.group(1) + "}", escaped)


def guard(post):
    """Return a list of reasons this post must not go out. Empty list means safe."""
    problems = []
    text = post.get("post", "")
    if not text.strip():
        problems.append("post text is empty")
    if len(text) > 3000:
        problems.append(f"post is {len(text)} characters, over LinkedIn's 3,000 limit")
    if re.search(r"\[(ADD|NEEDS|TODO)[^\]]*\]", text, re.I):
        problems.append("post still contains a placeholder")
    if "\u2014" in text or "\u2013" in text:
        problems.append("post contains an em or en dash")
    if re.search(r"github\.com|githubusercontent\.com|github\.io", text + " " + post.get("first_comment", ""), re.I):
        problems.append("post links to GitHub; only website and app links are allowed")
    return problems


MIN_GAP_HOURS = float(os.environ.get("MIN_GAP_HOURS", "3"))
SLOT_HOURS_IST = (2, 8, 14, 20)          # 2 AM, 8 AM, 2 PM, 8 PM IST
CATCH_UP_HOURS = float(os.environ.get("CATCH_UP_HOURS", "4"))
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def slot_start(now):
    """Start of the posting slot that `now` falls in (IST)."""
    t = now.astimezone(IST)
    h = max([x for x in SLOT_HOURS_IST if x <= t.hour] or [SLOT_HOURS_IST[-1] - 24])
    base = t.replace(minute=0, second=0, microsecond=0)
    return base.replace(hour=h) if h >= 0 else (base - datetime.timedelta(days=1)).replace(hour=h + 24)


def pick(queue, posted, now, force=False):
    """The next unposted post, or None.

    The workflow runs every hour, so a dropped or delayed GitHub schedule is retried
    within the slot. One post per slot: nothing if a post already went out since this
    slot started, if the slot's catch-up window has passed (unless forced by hand),
    or if the last post went out under MIN_GAP_HOURS ago."""
    start = slot_start(now)
    for v in posted.values():
        at = v.get("at")
        if not at:
            continue
        when = datetime.datetime.fromisoformat(at)
        if when >= start or (now - when).total_seconds() < MIN_GAP_HOURS * 3600:
            return None
    if not force and (now - start).total_seconds() > CATCH_UP_HOURS * 3600:
        return None
    for post in sorted(queue, key=lambda p: (bool(p.get("defer")), p["day"])):   # deferred posts go last
        if str(post["day"]) not in posted:
            return post
    return None


def call(method, path, token, version, body=None):
    req = urllib.request.Request(API + path, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("LinkedIn-Version", version)
    req.add_header("X-Restli-Protocol-Version", "2.0.0")
    data = None
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode("utf-8")
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return resp.status, dict(resp.headers), json.loads(raw)
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:500]
        if err.code == 401:
            raise SystemExit("LinkedIn rejected the token (401). Tokens last 60 days: "
                             "generate a new one and update the LINKEDIN_ACCESS_TOKEN secret.")
        raise SystemExit(f"LinkedIn API error {err.code}: {detail}")


def comment_request(post_urn, author, text):
    """Path and body for a first comment (Comments API: POST /rest/socialActions/{urn}/comments, scope w_member_social)."""
    return ("/rest/socialActions/" + urllib.parse.quote(post_urn, safe="") + "/comments",
            {"actor": author, "object": post_urn, "message": {"text": text}})


def add_first_comment(token, version, post_urn, author, text):
    """Add the first comment. A failure here never undoes the post: it is reported, not raised."""
    if not (post_urn and text.strip()):
        return False
    path, body = comment_request(post_urn, author, text)
    for attempt in range(3):                                  # a just-published post can take a moment to accept comments
        try:
            status, _, _ = call("POST", path, token, version, body)
            print(f"First comment added (HTTP {status}).")
            return True
        except SystemExit as err:
            print(f"First comment attempt {attempt + 1} failed: {err}")
            time.sleep(8 * (attempt + 1))
    print("First comment NOT added; the next hourly run will try again.")
    return False


RELEASE = "https://github.com/Anchit-AI-Hustle/linkedin-auto-pilot/releases/download/demo-videos/"


def video_for(day):
    """The demo video for a post: the 2160p master from the release if it can be fetched, else the web copy, else None."""
    found = sorted(f for f in glob.glob(os.path.join(VIDEOS, f"demo-{int(day):02d}-*.mp4")) if not f.endswith("-2160p.mp4"))
    if not found:
        return None
    web = found[0]
    if os.path.basename(web) not in verified_videos():
        print(f"{os.path.basename(web)} is not marked as a reviewed full tour yet; not attaching it.")
        return None
    if os.environ.get("USE_2160P", "true").lower() != "false":
        name = os.path.basename(web)[:-4] + "-2160p.mp4"
        dest = os.path.join(HERE, name)
        try:
            if not os.path.exists(dest):
                urllib.request.urlretrieve(RELEASE + name, dest)
            if os.path.getsize(dest) > 75000:
                return dest
        except Exception as err:
            print(f"2160p master not available ({err}); using the web copy.")
    return web


def verified_videos():
    """Videos reviewed as complete product tours (written after each render is checked)."""
    try:
        return set(json.load(open(os.path.join(VIDEOS, "verified.json"), encoding="utf-8")))
    except Exception:
        return set()


def site_url(post):
    """The product's own link: the first "Label: address" line that isn't the phone app or portfolio, else the portfolio."""
    pat = re.compile(r":\s*(?:https?://)?([a-z0-9-]+(?:\.[a-z0-9-]+)+(?:/[^\s()]*)?)(?:\s*\([^)]*\))?\s*$", re.I)
    fallback = None
    for line in post["post"].split("\n"):
        m = pat.search(line)
        if not m or "#" in line:
            continue
        if "Portfolio" in line:
            fallback = fallback or m.group(1)
        elif "Phone app" not in line:
            return "https://" + m.group(1)
    return "https://" + fallback if fallback else None


def page_meta(url):
    """Title, description and image from the page's own preview (Open Graph) tags."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 linkedin-auto-pilot"})
    html = urllib.request.urlopen(req, timeout=20).read(400000).decode("utf-8", "ignore")
    def tag(*names):
        for n in names:
            m = re.search(r'<meta[^>]+(?:property|name)=["\']' + re.escape(n) + r'["\'][^>]*content=["\']([^"\']+)', html, re.I) or \
                re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']' + re.escape(n) + r'["\']', html, re.I)
            if m:
                return m.group(1).strip()
        return None
    import html as _h
    title = tag("og:title", "twitter:title") or (re.search(r"<title>([^<]+)", html, re.I) or [None, None])[1]
    desc = tag("og:description", "description", "twitter:description")
    image = tag("og:image", "twitter:image")
    return {"title": _h.unescape(title or url)[:390], "description": _h.unescape(desc or "")[:600],
            "image": urllib.parse.urljoin(url, image) if image else None}


def article_content(token, version, author, post):
    """Website preview card for the post (the API does not build one by itself), or None."""
    url = site_url(post)
    if not url:
        return None
    try:
        meta = page_meta(url)
    except Exception as err:
        print(f"Preview card without page details ({err}).")
        meta = {"title": post["title"], "description": "", "image": None}
    art = {"source": url, "title": meta["title"]}
    if meta["description"]:
        art["description"] = meta["description"]
    if meta["image"]:
        try:
            img = urllib.request.urlopen(urllib.request.Request(meta["image"], headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read()
            _, _, init = call("POST", "/rest/images?action=initializeUpload", token, version,
                              {"initializeUploadRequest": {"owner": author}})
            put_bytes(init["value"]["uploadUrl"], img, token)
            art["thumbnail"] = init["value"]["image"]
        except (SystemExit, Exception) as err:
            print(f"Preview card without image ({err}).")
    return {"article": art}


def put_bytes(url, data, token, content_type="application/octet-stream"):
    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", content_type)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.headers.get("ETag", "").strip()


def upload_video(token, version, author, path, poster=None, wait_seconds=300):
    """Videos API: initializeUpload -> PUT each part -> finalizeUpload -> wait until AVAILABLE.
    Returns the video URN, or None on any failure (the post then goes out as text, on time)."""
    try:
        data = open(path, "rb").read()
        _, _, init = call("POST", "/rest/videos?action=initializeUpload", token, version, {"initializeUploadRequest": {
            "owner": author, "fileSizeBytes": len(data), "uploadCaptions": False, "uploadThumbnail": bool(poster)}})
        value = init["value"]; video = value["video"]
        etags = [put_bytes(part["uploadUrl"], data[part["firstByte"]:part["lastByte"] + 1], token)
                 for part in value["uploadInstructions"]]
        if poster and value.get("thumbnailUploadUrl"):
            try: put_bytes(value["thumbnailUploadUrl"], open(poster, "rb").read(), token, "image/jpeg")
            except Exception as err: print(f"Thumbnail skipped: {err}")
        call("POST", "/rest/videos?action=finalizeUpload", token, version, {"finalizeUploadRequest": {
            "video": video, "uploadToken": value.get("uploadToken", ""), "uploadedPartIds": etags}})
        deadline = time.time() + wait_seconds
        while True:
            _, _, info = call("GET", "/rest/videos/" + urllib.parse.quote(video, safe=""), token, version)
            status = info.get("status")
            if status == "AVAILABLE":
                print(f"Video ready: {os.path.basename(path)} ({len(data) / 1e6:.1f} MB) {video}")
                return video
            if status == "PROCESSING_FAILED" or time.time() > deadline:
                print(f"Video not used ({status}); posting text only.")
                return None
            time.sleep(10)
    except (SystemExit, Exception) as err:
        print(f"Video not used ({err}); posting text only.")
        return None


def person_urn(token, version):
    # /v2/userinfo returns the member id as "sub" for apps with Sign In with LinkedIn (OpenID Connect).
    _, _, info = call("GET", "/v2/userinfo", token, version)
    return "urn:li:person:" + info["sub"]


def catch_up_comments(token, version, queue, posted, now):
    """Add the first comment to any post from the last 24 hours that is missing it."""
    texts = {str(p["day"]): p.get("first_comment", "") for p in queue}
    todo = [d for d, v in posted.items() if v.get("urn") and not v.get("commented") and v.get("at")
            and (now - datetime.datetime.fromisoformat(v["at"])).total_seconds() < 24 * 3600]
    if not todo:
        return
    author = person_urn(token, version)
    for d in todo:
        if add_first_comment(token, version, posted[d]["urn"], author, texts.get(d, "")):
            posted[d]["commented"] = True
            json.dump(posted, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def main():
    dry = os.environ.get("DRY_RUN", "").lower() == "true"
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "").strip()
    version = os.environ.get("LINKEDIN_VERSION", "202605").strip()
    now = datetime.datetime.fromisoformat(os.environ["POST_AT"]) if os.environ.get("POST_AT") else datetime.datetime.now(IST)
    date_str = now.date().isoformat()

    if "--check" in sys.argv:
        if not token:
            raise SystemExit("LINKEDIN_ACCESS_TOKEN is missing. Add it under Settings, Secrets and variables, Actions.")
        print("Token works for " + person_urn(token, version) + ". Ready to post.")
        return 0

    if os.path.exists(PAUSE) and not dry:
        print("Paused: nothing posted. Run the 'Start posting' workflow to begin.")
        return 0

    queue = json.load(open(QUEUE, encoding="utf-8"))
    posted = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}
    if not dry and token:
        catch_up_comments(token, version, queue, posted, now)
    post = pick(queue, posted, now, force=os.environ.get("FORCE", "false").lower() == "true")
    if post is None:
        print(f"Nothing to post at {now.isoformat(timespec='minutes')}: this slot (from {slot_start(now):%-I %p} IST) already has its post, its {CATCH_UP_HOURS:g}-hour window has passed, or the series is finished.")
        return 0

    problems = guard(post)
    if problems:
        raise SystemExit(f"Day {post['day']} blocked: " + "; ".join(problems))

    commentary = to_little_text(post["post"])
    print(f"Day {post['day']} ({post['title']}) for {date_str}: {len(post['post'])} characters.")
    if not dry and not token:
        raise SystemExit("LINKEDIN_ACCESS_TOKEN is missing, so nothing was posted. Add it under Settings, Secrets and variables, Actions.")
    require_ready = os.environ.get("REQUIRE_READY", "true").lower() != "false"
    clip = video_for(post["day"]) if os.environ.get("ATTACH_VIDEO", "true").lower() != "false" else None
    if require_ready and not clip and not dry:
        msg = (f"Holding Day {post['day']} ({post['title']}): its demo video is not a reviewed full tour yet. "
               "The series waits and posts in the first slot after the video is marked ready.")
        print(("::warning::" if os.environ.get("GITHUB_ACTIONS") else "") + msg)
        return 0
    if dry:
        print("Video: " + (os.path.basename(clip) if clip else "NOT READY (a live run would hold this post)"))
        print("DRY RUN: nothing was posted.")
        print("---\n" + post["post"][:400] + "\n---")
        return 0

    author = person_urn(token, version)
    body = {
        "author": author,
        "commentary": commentary,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                         "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if clip:
        poster = os.path.join(VIDEOS, os.path.basename(clip).replace("-2160p", "")[:-4] + ".jpg")
        video = upload_video(token, version, author, clip, poster if os.path.exists(poster) else None)
        if video:
            body["content"] = {"media": {"id": video, "title": post["title"] + " demo"}}
        elif require_ready:                                   # never post without its video; the next hourly run retries
            raise SystemExit(f"Day {post['day']} not posted: its video did not upload. The next hourly run will retry.")
    if "content" not in body and os.environ.get("PREVIEW_CARD", "true").lower() != "false":   # no reviewed video: website card
        card = article_content(token, version, author, post)
        if card:
            body["content"] = card
    status, headers, _ = call("POST", "/rest/posts", token, version, body)
    urn = headers.get("x-restli-id") or headers.get("X-RestLi-Id") or ""
    posted[str(post["day"])] = {"date": date_str, "at": now.isoformat(timespec="seconds"), "title": post["title"], "urn": urn}
    json.dump(posted, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Published Day {post['day']} (HTTP {status}) {urn}")
    if add_first_comment(token, version, urn, author, post.get("first_comment", "")):
        posted[str(post["day"])]["commented"] = True
        json.dump(posted, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return 0


class _Tee:
    """Keeps a copy of everything printed in last-run.log, committed with posted.json, so every run can be read later."""
    def __init__(self, stream, fh): self.stream, self.fh = stream, fh
    def write(self, s): self.stream.write(s); self.fh.write(s)
    def flush(self): self.stream.flush(); self.fh.flush()


if __name__ == "__main__":
    if os.environ.get("GITHUB_ACTIONS"):
        _log = open(os.path.join(HERE, "last-run.log"), "w", encoding="utf-8")
        _log.write(f"Run at {datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')} UTC\n")
        sys.stdout = _Tee(sys.stdout, _log); sys.stderr = _Tee(sys.stderr, _log)
    sys.exit(main())
