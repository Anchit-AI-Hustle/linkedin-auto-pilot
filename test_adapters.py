import base64, hashlib, hmac, io, json, os, sys, unittest, importlib.util, threading, urllib.request
from http.server import HTTPServer
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import adapters as ad

ENV = {"WA_TOKEN": "t", "WA_PHONE_NUMBER_ID": "1374923709046462", "WA_APP_SECRET": "s3cret",
       "WA_VERIFY_TOKEN": "vt", "OWNER_WHATSAPP": "919873945238", "GITHUB_TOKEN": "g",
       "GITHUB_REPO": "Anchit-AI-Hustle/linkedin-auto-pilot", "ANTHROPIC_API_KEY": "a", "TICK_SECRET": "tick"}


class Recorder:
    def __init__(self, responses=None): self.calls, self.responses = [], list(responses or [])
    def __call__(self, method, url, headers=None, body=None):
        self.calls.append((method, url, headers, body))
        return self.responses.pop(0) if self.responses else (200, {})


class WhatsAppShapes(unittest.TestCase):
    def test_text_payload(self):
        h = Recorder(); ad.WhatsApp(ENV, h).text("919873945238", "hi")
        m, url, hd, body = h.calls[0]
        self.assertEqual(url, "https://graph.facebook.com/v25.0/1374923709046462/messages")
        self.assertEqual(body, {"messaging_product": "whatsapp", "to": "919873945238", "type": "text", "text": {"body": "hi"}})
        self.assertEqual(hd["Authorization"], "Bearer t")

    def test_buttons_are_capped_to_whatsapp_limits(self):
        h = Recorder(); ad.WhatsApp(ENV, h).buttons("1", "x" * 2000, [("a", "A very long button title"), ("b", "B"), ("c", "C"), ("d", "D")])
        inter = h.calls[0][3]["interactive"]
        self.assertEqual(len(inter["body"]["text"]), 1024)
        self.assertEqual(len(inter["action"]["buttons"]), 3)
        self.assertTrue(all(len(b["reply"]["title"]) <= 20 for b in inter["action"]["buttons"]))

    def test_default_opener_uses_hello_world_template(self):
        h = Recorder(); ad.WhatsApp(ENV, h).opener("1", 3, "Parwah")
        self.assertEqual(h.calls[0][3]["template"], {"name": "hello_world", "language": {"code": "en_US"}})

    def test_custom_template_gets_day_and_title(self):
        h = Recorder(); ad.WhatsApp(dict(ENV, WA_TEMPLATE="post_review_ready", WA_TEMPLATE_LANG="en"), h).opener("1", 3, "Parwah")
        params = h.calls[0][3]["template"]["components"][0]["parameters"]
        self.assertEqual([p["text"] for p in params], ["3", "Parwah"])

    def test_send_failure_is_raised(self):
        with self.assertRaises(RuntimeError):
            ad.WhatsApp(ENV, Recorder([(400, {"error": "bad"})])).text("1", "x")


class Webhook(unittest.TestCase):
    def test_signature(self):
        body = b'{"a":1}'
        good = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        self.assertTrue(ad.verify_signature("s3cret", body, good))
        self.assertFalse(ad.verify_signature("s3cret", body, "sha256=" + "0" * 64))
        self.assertFalse(ad.verify_signature("s3cret", body, None))

    def test_parse_text_button_and_template_reply(self):
        payload = {"entry": [{"changes": [{"value": {"messages": [
            {"from": "919873945238", "type": "text", "text": {"body": "make it shorter"}},
            {"from": "919873945238", "type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": "post", "title": "Post it"}}},
            {"from": "919873945238", "type": "button", "button": {"payload": "show", "text": "Show post"}}]}}]}]}
        self.assertEqual(list(ad.parse_webhook(payload)), [
            ("919873945238", "text", "make it shorter"), ("919873945238", "button", "post"), ("919873945238", "button", "show")])

    def test_status_updates_are_ignored(self):
        self.assertEqual(list(ad.parse_webhook({"entry": [{"changes": [{"value": {"statuses": [{"status": "read"}]}}]}]})), [])


class GitHub(unittest.TestCase):
    def test_round_trip_uses_sha_for_safe_updates(self):
        enc = base64.b64encode(json.dumps({"day": 1}).encode()).decode()
        h = Recorder([(200, {"sha": "abc", "content": enc}), (200, {"content": {"sha": "def"}})])
        st = ad.GitHubStore(ENV, h)
        self.assertEqual(st.state(), {"day": 1})
        st.save_state({"day": 2, "status": "draft"})
        method, url, hd, body = h.calls[1]
        self.assertEqual((method, body["sha"]), ("PUT", "abc"))
        self.assertTrue(url.endswith("/contents/review_state.json"))

    def test_missing_state_returns_none(self):
        self.assertIsNone(ad.GitHubStore(ENV, Recorder([(404, {})])).state())

    def test_pause_detection(self):
        self.assertTrue(ad.GitHubStore(ENV, Recorder([(200, {})])).paused())
        self.assertFalse(ad.GitHubStore(ENV, Recorder([(404, {})])).paused())


class Rewrite(unittest.TestCase):
    def test_claude_request_and_reply(self):
        h = Recorder([(200, {"content": [{"type": "text", "text": "New post"}]})])
        out = ad.claude_rewrite(ENV, h)("Old post", "shorter")
        m, url, hd, body = h.calls[0]
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(hd["anthropic-version"], "2023-06-01")
        self.assertIn("Never add numbers", body["system"])
        self.assertEqual(out, "New post")


def load(path):
    spec = importlib.util.spec_from_file_location(os.path.basename(path)[:-3] + "_fn", path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


class Endpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.update(ENV)
        cls.wa = load(os.path.join(HERE, "api", "whatsapp.py"))
        cls.tick = load(os.path.join(HERE, "api", "tick.py"))

    def serve(self, handler):
        srv = HTTPServer(("127.0.0.1", 0), handler); threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown); return f"http://127.0.0.1:{srv.server_port}"

    def req(self, url, method="GET", body=None, headers=None):
        r = urllib.request.Request(url, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(r) as resp: return resp.status, resp.read().decode()
        except urllib.error.HTTPError as e: return e.code, e.read().decode()

    def test_meta_verification_handshake(self):
        base = self.serve(self.wa.handler)
        self.assertEqual(self.req(base + "/?hub.mode=subscribe&hub.verify_token=vt&hub.challenge=42"), (200, "42"))
        self.assertEqual(self.req(base + "/?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=42")[0], 403)

    def test_unsigned_webhook_is_rejected(self):
        base = self.serve(self.wa.handler)
        self.assertEqual(self.req(base, "POST", b"{}", {"X-Hub-Signature-256": "sha256=bad"})[0], 401)

    def test_signed_webhook_reaches_the_review_loop(self):
        seen = []
        class FakeReview:
            def on_message(self, *a): seen.append(a)
        self.wa.build = lambda: FakeReview()
        base = self.serve(self.wa.handler)
        body = json.dumps({"entry": [{"changes": [{"value": {"messages": [{"from": "919873945238", "type": "text", "text": {"body": "hi"}}]}}]}]}).encode()
        sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        self.assertEqual(self.req(base, "POST", body, {"X-Hub-Signature-256": sig, "Content-Length": str(len(body))})[0], 200)
        self.assertEqual(seen, [("919873945238", "text", "hi")])

    def test_tick_needs_the_secret(self):
        base = self.serve(self.tick.handler)
        self.assertEqual(self.req(base, "POST", b"", {"Authorization": "Bearer wrong"})[0], 401)

    def test_tick_runs_with_the_secret(self):
        class FakeReview:
            def tick(self): return "idle"
        self.tick.build = lambda: FakeReview()
        base = self.serve(self.tick.handler)
        self.assertEqual(self.req(base, "POST", b"", {"Authorization": "Bearer tick"}), (200, '{"result": "idle"}'))


if __name__ == "__main__":
    unittest.main(verbosity=1)
