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
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(HERE, "posts.json")
STATE = os.path.join(HERE, "posted.json")
PAUSE = os.path.join(HERE, "PAUSE")
API = "https://api.linkedin.com"
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


MIN_GAP_HOURS = float(os.environ.get("MIN_GAP_HOURS", "5"))


def pick(queue, posted, now):
    """The next unposted post, or None if one went out less than MIN_GAP_HOURS ago or all are done.

    The schedule runs every 6 hours; the 5-hour gap stops a delayed or repeated run
    from posting twice in one slot."""
    for v in posted.values():
        at = v.get("at")
        if at and (now - datetime.datetime.fromisoformat(at)).total_seconds() < MIN_GAP_HOURS * 3600:
            return None
    for post in sorted(queue, key=lambda p: p["day"]):
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


def person_urn(token, version):
    # /v2/userinfo returns the member id as "sub" for apps with Sign In with LinkedIn (OpenID Connect).
    _, _, info = call("GET", "/v2/userinfo", token, version)
    return "urn:li:person:" + info["sub"]


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
    post = pick(queue, posted, now)
    if post is None:
        print(f"Nothing to post at {now.isoformat(timespec='minutes')}: the last post went out under {MIN_GAP_HOURS:g} hours ago, or the series is finished.")
        return 0

    problems = guard(post)
    if problems:
        raise SystemExit(f"Day {post['day']} blocked: " + "; ".join(problems))

    commentary = to_little_text(post["post"])
    print(f"Day {post['day']} ({post['title']}) for {date_str}: {len(post['post'])} characters.")
    if not dry and not token:
        raise SystemExit("LINKEDIN_ACCESS_TOKEN is missing, so nothing was posted. Add it under Settings, Secrets and variables, Actions.")
    if dry:
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
    status, headers, _ = call("POST", "/rest/posts", token, version, body)
    urn = headers.get("x-restli-id") or headers.get("X-RestLi-Id") or ""
    posted[str(post["day"])] = {"date": date_str, "at": now.isoformat(timespec="seconds"), "title": post["title"], "urn": urn}
    json.dump(posted, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Published Day {post['day']} (HTTP {status}) {urn}")
    print("First comment to add by hand: " + post.get("first_comment", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
