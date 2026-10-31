"""Live adapters for the review loop. Secrets come only from environment variables:

  WA_TOKEN, WA_PHONE_NUMBER_ID, WA_APP_SECRET, WA_VERIFY_TOKEN, WA_TEMPLATE, WA_TEMPLATE_LANG
  OWNER_WHATSAPP            e.g. 919873945238
  GITHUB_TOKEN, GITHUB_REPO e.g. Anchit-AI-Hustle/linkedin-auto-pilot
  ANTHROPIC_API_KEY, ANTHROPIC_MODEL
  LINKEDIN_ACCESS_TOKEN, LINKEDIN_VERSION
  TICK_SECRET               shared secret for the hourly tick
"""
import base64
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request

import post as ap

GRAPH = "https://graph.facebook.com/v25.0"


def _http(method, url, headers=None, body=None, opener=urllib.request.urlopen):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with opener(req, timeout=30) as r:
            raw = r.read().decode() or "{}"
            return r.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode("utf-8", "replace")[:400]}


# ------------------------------------------------------------------ WhatsApp
class WhatsApp:
    def __init__(self, env=os.environ, http=_http):
        self.token, self.phone_id = env["WA_TOKEN"], env["WA_PHONE_NUMBER_ID"]
        self.template = env.get("WA_TEMPLATE", "hello_world")
        self.lang = env.get("WA_TEMPLATE_LANG", "en_US")
        self.http = http

    def _send(self, payload):
        payload = {"messaging_product": "whatsapp", **payload}
        status, out = self.http("POST", f"{GRAPH}/{self.phone_id}/messages",
                                {"Authorization": "Bearer " + self.token}, payload)
        if status >= 300:
            raise RuntimeError(f"WhatsApp send failed ({status}): {out}")
        return out

    def text(self, to, body):
        return self._send({"to": to, "type": "text", "text": {"body": body[:4096]}})

    def buttons(self, to, body, buttons):
        return self._send({"to": to, "type": "interactive", "interactive": {
            "type": "button", "body": {"text": body[:1024]},
            "action": {"buttons": [{"type": "reply", "reply": {"id": i, "title": t[:20]}} for i, t in buttons[:3]]}}})

    def opener(self, to, day, title):
        tpl = {"name": self.template, "language": {"code": self.lang}}
        if self.template != "hello_world":
            tpl["components"] = [{"type": "body", "parameters": [
                {"type": "text", "text": str(day)}, {"type": "text", "text": title[:60]}]}]
        return self._send({"to": to, "type": "template", "template": tpl})


def verify_signature(app_secret, raw_body, header):
    """Meta signs every webhook with X-Hub-Signature-256: sha256=<hex HMAC of the raw body>."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[7:])


def parse_webhook(payload):
    """Yield (sender, kind, value) for each incoming message. kind is 'text' or 'button'."""
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for m in change.get("value", {}).get("messages", []) or []:
                sender, t = m.get("from"), m.get("type")
                if t == "text":
                    yield sender, "text", m["text"]["body"]
                elif t == "interactive" and m["interactive"].get("type") == "button_reply":
                    yield sender, "button", m["interactive"]["button_reply"]["id"]
                elif t == "button":   # quick-reply button on a template
                    yield sender, "button", m["button"].get("payload") or m["button"].get("text", "")


# -------------------------------------------------------------------- GitHub
class GitHubStore:
    def __init__(self, env=os.environ, http=_http):
        self.repo, self.token, self.http = env["GITHUB_REPO"], env["GITHUB_TOKEN"], http
        self._sha = {}

    def _h(self):
        return {"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"}

    def _get(self, path, default):
        status, out = self.http("GET", f"https://api.github.com/repos/{self.repo}/contents/{path}", self._h())
        if status == 404:
            self._sha.pop(path, None)
            return default
        if status >= 300:
            raise RuntimeError(f"GitHub read {path} failed ({status})")
        self._sha[path] = out["sha"]
        return json.loads(base64.b64decode(out["content"]).decode())

    def _put(self, path, obj, message):
        body = {"message": message,
                "content": base64.b64encode(json.dumps(obj, ensure_ascii=False, indent=2).encode()).decode()}
        if path in self._sha:
            body["sha"] = self._sha[path]
        status, out = self.http("PUT", f"https://api.github.com/repos/{self.repo}/contents/{path}", self._h(), body)
        if status >= 300:
            raise RuntimeError(f"GitHub write {path} failed ({status}): {out}")
        self._sha[path] = out["content"]["sha"]

    def queue(self): return self._get("posts.json", [])
    def posted(self): return self._get("posted.json", {})
    def state(self): return self._get("review_state.json", None)
    def save_state(self, st): self._put("review_state.json", st, f"Review: Day {st.get('day')} {st.get('status')}")

    def paused(self):
        status, _ = self.http("GET", f"https://api.github.com/repos/{self.repo}/contents/PAUSE", self._h())
        return status == 200

    def mark_posted(self, day, title, text, urn, cycle):
        posted = self.posted()
        posted[str(day)] = {"date": cycle, "title": title, "urn": urn}
        self._put("posted.json", posted, f"Posted Day {day}")
        queue = self.queue()
        for p in queue:
            if p["day"] == day:
                p["post"] = text           # keep the approved wording in the queue
        self._put("posts.json", queue, f"Day {day}: approved wording")


# --------------------------------------------------------------- AI rewrite
REWRITE_RULES = """You edit LinkedIn posts for Anchit Tandon. Apply the feedback to the post and return only the full revised post text.
Rules: keep every fact, link and hashtag unless the feedback says otherwise. Never add numbers, results or claims that are not in the post or the feedback. No em dashes or en dashes. Keep the first two lines explaining what the post is about. Stay under 2,800 characters."""


def claude_rewrite(env=os.environ, http=_http):
    def rewrite(draft, feedback):
        status, out = http("POST", "https://api.anthropic.com/v1/messages",
                           {"x-api-key": env["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
                           {"model": env.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"), "max_tokens": 2000,
                            "system": REWRITE_RULES,
                            "messages": [{"role": "user", "content": f"POST:\n{draft}\n\nFEEDBACK:\n{feedback}"}]})
        if status >= 300:
            raise RuntimeError(f"Rewrite failed ({status})")
        return "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text").strip()
    return rewrite


# ---------------------------------------------------------------- LinkedIn
def linkedin_publish(env=os.environ):
    def publish(text):
        token, version = env["LINKEDIN_ACCESS_TOKEN"], env.get("LINKEDIN_VERSION", "202605")
        author = ap.person_urn(token, version)
        body = {"author": author, "commentary": ap.to_little_text(text), "visibility": "PUBLIC",
                "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                                 "thirdPartyDistributionChannels": []},
                "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
        _, headers, _ = ap.call("POST", "/rest/posts", token, version, body)
        return headers.get("x-restli-id") or headers.get("X-RestLi-Id") or ""
    return publish
