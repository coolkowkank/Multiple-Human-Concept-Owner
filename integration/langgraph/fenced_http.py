"""Fenced single-request HTTP adapter for the LangGraph seat boundary.

Replaces the project's generic HttpAdapter on this path (the runtime
builds an HttpAdapter from the spec; langgraph_team swaps it for this
class before any call, so the generic adapter never sends anything).

Properties (each has a test in http_fence_test.py):
- ONE request per complete(); no retries, no backoff.
- Durable reserve line is written (flock + fsync) BEFORE the request. A
  crash, malformed 200, timeout or socket error leaves the reserve in
  place, so the attempt stays counted across restarts.
- Redirects are never followed (a 3xx is an error), so the Authorization
  header cannot be forwarded to another host. System proxies are ignored.
- Lifetime cap across ALL log files in the fixed log directory
  (HTTP_LIFETIME_CAP): changing the epoch/path cannot reset it. Deleting
  the log directory still resets it - operator-level, not prevented here.
- Log lines are hash-chained; a broken chain refuses further calls.
  Tail truncation is NOT detected.
- Response must report an explicit numeric cost of exactly 0, else the
  adapter halts (a halt line blocks all later calls). The pre-call basis
  is only the fixed host plus the exact model allowlist (listing fact).
- Error text never includes provider bodies; logs hold only attempt
  number, model, status class, sanitized usage numbers. No key, no
  prompt, no completion text.
"""
import fcntl
import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.request

from launcher.adapters import Adapter, AdapterError, parse_response

HTTP_LOG_DIR = os.path.join(os.path.expanduser("~"), ".lg-http-usage")
HTTP_LIFETIME_CAP = 8
MAX_BODY = 2_000_000
EPOCH_RE = re.compile(r"^[a-z0-9-]{1,32}$")
USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens", "cost")


def log_path(model, epoch):
    slug = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")
    return os.path.join(HTTP_LOG_DIR, f"{slug}.{epoch}.jsonl")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                       _NoRedirect())


def _num_ok(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v) and v >= 0)


def _read_all(dirpath):
    """-> (reserves_total, halted, chain_ok) over every log in the dir."""
    reserves, halted, ok = 0, False, True
    if not os.path.isdir(dirpath):
        return 0, False, True
    for fn in sorted(os.listdir(dirpath)):
        if not fn.endswith(".jsonl"):
            continue
        prev = "0"
        with open(os.path.join(dirpath, fn), "rb") as fh:
            for raw in fh:
                if not raw.strip():
                    continue
                try:
                    e = json.loads(raw)
                    if e.get("prev") != prev:
                        ok = False
                except ValueError:
                    ok = False
                    e = {}
                prev = hashlib.sha256(raw.rstrip(b"\n")).hexdigest()
                if e.get("phase") == "reserve":
                    reserves += 1
                if e.get("phase") == "halt":
                    halted = True
    return reserves, halted, ok


class FencedHttpAdapter(Adapter):
    REPORTS_PROVIDER_USAGE = True

    def __init__(self, base_url, model, api_key_env, epoch, call_budget,
                 max_tokens, timeout, reasoning_effort, opener=None):
        if not EPOCH_RE.match(str(epoch)):
            raise AdapterError("bad log epoch")
        self.base_url, self.model = base_url.rstrip("/"), model
        self.api_key_env, self.epoch = api_key_env, epoch
        self.call_budget, self.max_tokens = call_budget, max_tokens
        self.timeout, self.effort = timeout, reasoning_effort
        self.path = log_path(model, epoch)
        self._opener = opener or _opener()
        self.last_call = None

    def _append(self, fh, entry):
        fh.seek(0)
        data = fh.read()
        lines = [l for l in data.split(b"\n") if l.strip()]
        prev = hashlib.sha256(lines[-1]).hexdigest() if lines else "0"
        entry = dict(entry, prev=prev)
        fh.seek(0, os.SEEK_END)
        fh.write((json.dumps(entry, sort_keys=True) + "\n").encode())
        fh.flush()
        os.fsync(fh.fileno())

    def _open_log(self):
        os.makedirs(HTTP_LOG_DIR, mode=0o700, exist_ok=True)   # private: reserve_preflight refuses group/other-accessible dirs
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        fh = os.fdopen(fd, "r+b")
        fcntl.flock(fh, fcntl.LOCK_EX)    # exclusive writer
        return fh

    def complete(self, system, prompt):
        self.last_call = None
        key = os.environ.get(self.api_key_env)
        if not key:
            raise AdapterError("missing API key env var")
        fh = self._open_log()
        try:
            total, halted, chain_ok = _read_all(HTTP_LOG_DIR)
            if not chain_ok:
                raise AdapterError("usage log chain broken; refusing")
            if halted:
                raise AdapterError("adapter halted earlier; refusing")
            mine = sum(1 for l in open(self.path, "rb")
                       if b'"phase": "reserve"' in l)
            if mine >= self.call_budget or total >= HTTP_LIFETIME_CAP:
                raise AdapterError("request budget exhausted; refusing")
            n = mine + 1
            self._append(fh, {"phase": "reserve", "n": n,
                              "model": self.model})   # BEFORE any I/O
            cls, usage, code, text = "unknown", None, None, None
            try:
                payload = {"model": self.model,
                           "messages": [{"role": "system", "content": system},
                                        {"role": "user", "content": prompt}],
                           "max_completion_tokens": self.max_tokens,
                           "reasoning_effort": self.effort}
                req = urllib.request.Request(
                    self.base_url + "/chat/completions",
                    data=json.dumps(payload).encode(), method="POST",
                    headers={"content-type": "application/json",
                             "authorization": "Bearer " + key,
                             "user-agent": "lg-fenced-http/0.1"})
                try:
                    with self._opener.open(req, timeout=self.timeout) as r:
                        code = r.status
                        raw = r.read(MAX_BODY + 1)
                except urllib.error.HTTPError as e:
                    code = e.code
                    cls = "redirect" if 300 <= e.code < 400 else "http"
                    raw = None
                if raw is not None:
                    if code != 200 or len(raw) > MAX_BODY:
                        cls = "bad-status-or-size"
                    else:
                        d = json.loads(raw)
                        u = d.get("usage") if isinstance(d, dict) else None
                        if isinstance(u, dict):
                            usage = {k: u[k] for k in USAGE_KEYS
                                     if k in u and _num_ok(u[k])}
                        cls = "ok-shape"
                        ch = d["choices"][0]["message"]["content"]
                        if not isinstance(ch, str) or not ch.strip():
                            cls = "empty-content"
                        else:
                            text = ch
            except Exception as e:   # malformed body, timeout, socket, shape
                if cls == "unknown":
                    cls = "error:" + type(e).__name__
            cost = (usage or {}).get("cost")
            cost_known_zero = cost == 0 and isinstance(cost, (int, float))
            outcome = {"phase": "result", "n": n, "model": self.model,
                       "status": code, "class": cls, "usage": usage,
                       "cost_zero": bool(cost_known_zero)}
            self._append(fh, outcome)
            if code == 200 and usage:
                # the request happened and the provider reported usage:
                # keep that evidence even if the reply is unusable or the
                # cost check below halts (never reads as "no call")
                self.last_call = {"origin": "provider", "response_id": None,
                                  "usage": usage}
            if code == 200 and not cost_known_zero:
                self._append(fh, {"phase": "halt", "n": n,
                                  "why": "cost missing or nonzero"})
                raise AdapterError("cost not reported as exactly zero; halted")
            if text is None:
                raise AdapterError("no usable response (%s)" % cls)
            self.last_call = {"origin": "provider", "response_id": None,
                              "usage": usage}
            try:
                return parse_response(text)
            except AdapterError:
                # no raw model text in the error (it reaches traces)
                raise AdapterError("response is not the required "
                                   "structured format") from None
        finally:
            fh.close()
