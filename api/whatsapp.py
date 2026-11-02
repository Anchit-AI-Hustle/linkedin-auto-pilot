"""Vercel function: WhatsApp webhook. GET = Meta's verification handshake, POST = incoming replies."""
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import adapters as ad  # noqa: E402
import live            # noqa: E402
import review as rv    # noqa: E402


def build():
    env = os.environ
    ask = ad.claude_ask(env)
    return rv.Review(ad.GitHubStore(env), ad.WhatsApp(env), ad.linkedin_publish(env),
                     ad.claude_rewrite(env), env["OWNER_WHATSAPP"],
                     refresh=lambda post: live.refresh(post, ask=ask))


class handler(BaseHTTPRequestHandler):
    def _reply(self, code, body=b"ok", ctype="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if q.get("hub.mode", [""])[0] == "subscribe" and q.get("hub.verify_token", [""])[0] == os.environ.get("WA_VERIFY_TOKEN"):
            return self._reply(200, q.get("hub.challenge", [""])[0].encode())
        return self._reply(403, b"forbidden")

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
        if not ad.verify_signature(os.environ["WA_APP_SECRET"], raw, self.headers.get("X-Hub-Signature-256")):
            return self._reply(401, b"bad signature")
        review = build()
        for sender, kind, value in ad.parse_webhook(json.loads(raw or b"{}")):
            review.on_message(sender, kind, value)
        return self._reply(200)
