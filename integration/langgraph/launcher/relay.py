"""Loopback relay: fast seat-to-seat signals beyond the git bus.

The git bus is the durable record. The relay is an ephemeral wake/hint
channel so seats on one machine signal each other in milliseconds
instead of waiting out a poll interval. It never carries the only copy
of work: everything that matters is committed to the bus, and a dead
relay costs latency, never correctness (seats fall back to git polling).

Safety posture (deliberate): binds 127.0.0.1 only, requires a bearer
token, and the token never enters the repository. Exposing this beyond
loopback would be an exposure/auth/security decision for the owners,
not a default.
"""

from __future__ import annotations

import hmac
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN_HEADER = "x-relay-token"


MAX_BODY = 64 * 1024        # request body cap (bytes)
MAX_MESSAGES = 1000         # retained hints; the bus is the record
MAX_FIELD = 2000            # per-field length cap


class RelayState:
    def __init__(self, token):
        if not isinstance(token, str) or not token:
            raise ValueError("relay token must be a non-empty string")
        self.token = token
        self.messages = []  # [{seq, ts, seat, kind, body}] (most recent kept)
        self.latest = 0     # monotonic; never derived from len(messages)
        # New per server start: a client that sees it change knows seq
        # numbering restarted and must resync instead of waiting for
        # sequence numbers it already passed (hints would die silently).
        self.epoch = "%016x" % int.from_bytes(os.urandom(8), "big")
        self.cond = threading.Condition()

    def post(self, seat, kind, body):
        with self.cond:
            self.latest += 1
            self.messages.append({
                "seq": self.latest,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "seat": str(seat)[:MAX_FIELD], "kind": str(kind)[:MAX_FIELD],
                "body": str(body)[:MAX_FIELD],
            })
            del self.messages[:-MAX_MESSAGES]
            self.cond.notify_all()
            return self.latest

    def since(self, after, wait=0):
        deadline = time.time() + wait
        with self.cond:
            while True:
                fresh = [m for m in self.messages if m["seq"] > after]
                if fresh or time.time() >= deadline:
                    return fresh
                self.cond.wait(timeout=max(0.0, deadline - time.time()))


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        timeout = 5   # per-connection socket read timeout (half-sent requests)

        def handle(self):
            # A closed or stalled client is routine for a hint channel:
            # drop it quietly instead of printing a traceback per socket.
            try:
                super().handle()
            except (OSError, ValueError):
                self.close_connection = True

        def _authed(self):
            got = self.headers.get(TOKEN_HEADER) or ""
            if not state.token:
                return False
            return hmac.compare_digest(got.encode(), str(state.token).encode())

        def _send(self, code, payload):
            data = json.dumps(payload).encode()
            try:
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except OSError:
                self.close_connection = True

        def do_POST(self):
            if not self._authed():
                return self._send(403, {"error": "bad token"})
            if self.headers.get("transfer-encoding"):
                return self._send(411, {"error": "content-length required"})
            raw_len = self.headers.get("content-length")
            if raw_len is None:
                return self._send(411, {"error": "content-length required"})
            try:
                length = int(raw_len)
            except ValueError:
                return self._send(400, {"error": "bad content-length"})
            if length < 1:
                return self._send(400, {"error": "empty body"})
            if length > MAX_BODY:
                return self._send(413, {"error": "body too large"})
            try:
                body = json.loads(self.rfile.read(length))
            except (ValueError, RecursionError):
                return self._send(400, {"error": "invalid json"})
            if not isinstance(body, dict):
                return self._send(400, {"error": "body must be an object"})
            seq = state.post(body.get("seat", "?"),
                             body.get("kind", "signal"),
                             body.get("body", ""))
            self._send(200, {"seq": seq})

        def do_GET(self):
            if not self._authed():
                return self._send(403, {"error": "bad token"})
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            try:
                after = int(q.get("since", ["0"])[0])
                wait = float(q.get("wait", ["0"])[0])
            except ValueError:
                return self._send(400, {"error": "bad query"})
            if not (wait == wait) or wait < 0:   # NaN or negative
                wait = 0.0
            wait = min(wait, 30.0)
            msgs = state.since(after, wait)
            self._send(200, {"messages": msgs, "epoch": state.epoch,
                             "latest": state.latest})

        def log_message(self, *args):
            pass

    return Handler


def serve(port, token):
    """Blocking relay server on 127.0.0.1."""
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(RelayState(token)))
    server.serve_forever()


class RelayClient:
    """Seat-side client. Any platform that can speak HTTP can use this."""

    def __init__(self, base_url, token, timeout=35):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _req(self, method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            self.base_url + path, data=data, method=method,
            headers={TOKEN_HEADER: self.token,
                     "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())

    def post(self, seat, kind, body):
        return self._req("POST", "/messages",
                         {"seat": seat, "kind": kind, "body": body})["seq"]

    def since(self, after, wait=0):
        return self.poll(after, wait)["messages"]

    def poll(self, after, wait=0):
        """Like since() but returns the whole reply: messages plus the
        server's epoch and latest seq (absent on an older server)."""
        return self._req("GET", f"/messages?since={after}&wait={wait}")


class WebhookSink:
    """Outbound-only wake channel to any HTTPS webhook the team
    configures (Slack/Discord-compatible incoming webhook, an
    automation endpoint, another platform's listener).

    This is the beyond-git, beyond-loopback signal route that needs no
    exposed server of ours: seats POST a short wake message, the
    receiving platform's own integration delivers it. The webhook URL
    is a secret: from env (TEAM_WAKE_WEBHOOK), never committed.
    Delivery is best-effort; the git bus remains the record.
    """

    def __init__(self, url, timeout=10):
        self.url = url
        self.timeout = timeout

    def post(self, seat, kind, body):
        data = json.dumps({"text": f"[{seat}] {kind}: {body}"}).encode()
        req = urllib.request.Request(
            self.url, data=data,
            headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.status
