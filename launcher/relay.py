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

import json
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN_HEADER = "x-relay-token"


class RelayState:
    def __init__(self, token):
        self.token = token
        self.messages = []  # [{seq, ts, seat, kind, body}]
        self.cond = threading.Condition()

    def post(self, seat, kind, body):
        with self.cond:
            seq = len(self.messages) + 1
            self.messages.append({
                "seq": seq,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "seat": seat, "kind": kind, "body": body,
            })
            self.cond.notify_all()
            return seq

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
        def _authed(self):
            return self.headers.get(TOKEN_HEADER) == state.token

        def _send(self, code, payload):
            data = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if not self._authed():
                return self._send(403, {"error": "bad token"})
            length = int(self.headers.get("content-length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "invalid json"})
            seq = state.post(body.get("seat", "?"),
                             body.get("kind", "signal"),
                             body.get("body", ""))
            self._send(200, {"seq": seq})

        def do_GET(self):
            if not self._authed():
                return self._send(403, {"error": "bad token"})
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            after = int(q.get("since", ["0"])[0])
            wait = min(float(q.get("wait", ["0"])[0]), 30.0)
            self._send(200, {"messages": state.since(after, wait)})

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
        return self._req(
            "GET", f"/messages?since={after}&wait={wait}")["messages"]
