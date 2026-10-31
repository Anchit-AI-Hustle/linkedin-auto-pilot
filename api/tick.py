"""Vercel function: hourly tick, called by GitHub Actions with the shared TICK_SECRET."""
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from whatsapp import build  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        given = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if not hmac.compare_digest(given, os.environ.get("TICK_SECRET", "\x00missing")):
            self.send_response(401); self.end_headers(); self.wfile.write(b"unauthorized"); return
        result = build().tick()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"result": result}).encode())
