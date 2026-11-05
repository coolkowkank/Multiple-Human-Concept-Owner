"""Strict Requesty transport for ryan_cycle.step (offline-tested only).

Contract (same shape as ryan_cycle.http_post_factory's post):
    post(model, system, prompt, max_tokens, effort="low") -> result dict
    kind "ok" | "http" | "unknown"; never raises on a vendor problem,
    raises ryan_cycle.Halt only for a local refusal made BEFORE any
    network I/O (bad model string, bad effort, bad ceiling, no key).

What it enforces (all before or around the single request):
  * exact-string allowlist of FREE ids (docs.requesty.ai/features/
    free-models list, verified against the public /v1/models listing);
    anything else - prefix variants, `policy/...`, `:flex` suffixes,
    managed-policy ids - is refused with no request.
  * the allowlist handed to the factory must be a subset of FREE_IDS.
  * https only, fixed host, no redirects followed (the key is never
    re-sent to a redirect target), bounded response size, one request,
    NO retry, fixed timeout.
  * the response's `model` must equal the requested id exactly; a
    missing or different model is an UNKNOWN outcome (content dropped).
  * usage/cost signals are returned for the runner's settle() to judge.
It does NOT claim to catch an undocumented vendor charge: free status
rests on the vendor docs plus the listing, not on this code.
"""
import json
import os
import http.client
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ryan_cycle as rc  # noqa: E402

FREE_IDS = frozenset([
    "nvidia/nemotron-3-ultra-550b-a55b",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-3-nano-30b-a3b",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "poolside/laguna-xs.2",
    "poolside/laguna-m.1",
    "google/gemma-4-31b-it",
    "mistral/leanstral-1-5",
    "nvidia/nemotron-3.5-content-safety",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "nvidia/muse-glimmer-30b",
    "novita/ling-3.1-flash",
    "novita/inclusionai/ling-3.0-tiny",
])
HOST = "router.requesty.ai"
MAX_BODY = 1_000_000
TIMEOUT_S = 120
# Admitted ids carry the EXACT max_output_tokens from the fresh public
# /v1/models listing (2026-11-05 01:58 UTC, requesty-listing-fresh.json).
# FREE_IDS with a listed max of 0/undefined (nemotron-3-nano-30b-a3b,
# poolside laguna-xs.2 / laguna-m.1) are NOT admitted: no evidenced ceiling.
LISTING_MAX_OUT = {
    "nvidia/nemotron-3-ultra-550b-a55b": 65536,
    "nvidia/nemotron-3-super-120b-a12b": 65536,
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning": 20480,
    "google/gemma-4-31b-it": 8192,
    "mistral/leanstral-1-5": 32768,
    "nvidia/nemotron-3.5-content-safety": 8192,
    "nvidia/nemotron-3.5-lightning-30b-a3b": 65536,
    "nvidia/muse-glimmer-30b": 20480,
    "novita/ling-3.1-flash": 32768,
    "novita/inclusionai/ling-3.0-tiny": 32768,
}
MAX_REQUESTS = 3        # hard in-process attempt bound per factory
MAX_REQUEST_BODY = 65536


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None   # a 3xx surfaces as HTTPError, never followed


def _default_opener():
    return urllib.request.build_opener(_NoRedirect())


def check_model(model, allowed):
    if not isinstance(model, str) or model != model.strip():
        raise rc.Halt("model must be an exact string")
    if (model.startswith("policy/") or ":" in model
            or model not in allowed):
        raise rc.Halt("model %r is not in the exact free allowlist"
                      % model[:80])


ENDPOINT = rc.BASE_URL + "/chat/completions"


def _pos_num(v, hi, integer=False):
    import math
    ok = (isinstance(v, int) if integer else isinstance(v, (int, float)))
    return (ok and not isinstance(v, bool) and math.isfinite(v)
            and 0 < v <= hi)


def guarded_post_factory(allowed, env="REQUESTY_API_KEY", opener=None,
                         max_body=MAX_BODY, timeout=TIMEOUT_S,
                         max_requests=MAX_REQUESTS):
    """Strict by construction: the endpoint is the one fixed constant
    (no base_url argument), and the model echo is always required.
    max_body/timeout can only be LOWERED."""
    allowed = frozenset(allowed)
    if (not allowed or not allowed <= FREE_IDS
            or not allowed <= set(LISTING_MAX_OUT)):
        raise rc.Halt("allowlist must be a non-empty subset of the free "
                      "ids with an evidenced listing ceiling")
    u = urllib.parse.urlsplit(ENDPOINT)
    if (u.scheme, u.hostname, u.port, u.username, u.password, u.path,
            u.query, u.fragment) != ("https", HOST, None, None, None,
                                     "/v1/chat/completions", "", ""):
        raise rc.Halt("endpoint constant is not the exact intended URL")
    if (not _pos_num(max_body, MAX_BODY, True)
            or not _pos_num(timeout, TIMEOUT_S)
            or not _pos_num(max_requests, MAX_REQUESTS, True)):
        raise rc.Halt("max_body/timeout/max_requests may only be lowered")
    op = opener or _default_opener()
    attempts = [0]

    def post(model, system, prompt, max_tokens, effort="low"):
        check_model(model, allowed)
        if effort not in rc.EFFORT_VALUES:
            raise rc.Halt("invalid reasoning_effort")
        if (not isinstance(max_tokens, int) or isinstance(max_tokens, bool)
                or not 0 < max_tokens <= LISTING_MAX_OUT[model]):
            raise rc.Halt("max_tokens outside the listed ceiling for model")
        key = os.environ.get(env)
        if not key:
            raise rc.Halt("missing key env " + env)
        if not isinstance(system, str) or not isinstance(prompt, str):
            raise rc.Halt("system and prompt must be strings")
        t0 = time.monotonic()

        def unk(stage, cls, exc=None, raw=None, ctype=None, data=None):
            d = {"stage": stage, "class": cls,
                 "elapsed_s": time.monotonic() - t0}
            if exc is not None:
                d["error_type"] = type(exc).__name__
            if ctype:
                d["content_type"] = ctype
            if raw is not None:
                d["body_len"] = len(raw)
                d["body_kind"] = rc.body_kind(raw)
            return {"kind": "unknown", "usage": None, "content": "",
                    "cost_signal": rc.cost_signal(rc.raw_usage(raw))
                    if raw is not None else None,
                    "diag": rc.clean_diag(d)}
        body = json.dumps({
            "model": model, "temperature": 0, "max_tokens": max_tokens,
            "reasoning_effort": effort,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}]}).encode()
        if len(body) > MAX_REQUEST_BODY:
            raise rc.Halt("request body above the bounded size")
        if attempts[0] >= max_requests:
            raise rc.Halt("per-factory request bound reached; no request")
        attempts[0] += 1      # counted BEFORE I/O: an attempt is consumed
        req = urllib.request.Request(
            ENDPOINT, data=body, method="POST",
            headers={"content-type": "application/json",
                     "authorization": "Bearer " + key,
                     "user-agent": "team-launcher-requesty-transport/0.1"})
        try:
            resp = op.open(req, timeout=timeout)   # ONE attempt, no retry
        except urllib.error.HTTPError as e:
            ct = e.headers.get("content-type", "") if e.headers else ""
            try:
                eb = e.read(2001)[:2000]     # bounded read, then bounded
            except (TimeoutError, socket.timeout) as e2:
                return unk("read-error-body", "timeout", e2)
            except (OSError, http.client.HTTPException) as e2:
                return unk("read-error-body", "network", e2)
            return {"kind": "http", "code": e.code, "usage": None,
                    "content": "",
                    "cost_signal": rc.cost_signal(rc.raw_usage(eb)),
                    "diag": rc.clean_diag({
                        "stage": "http-status", "class": "http",
                        "status": e.code, "content_type": ct.split(";")[0],
                        "body_len": len(eb), "body_kind": rc.body_kind(eb),
                        "elapsed_s": time.monotonic() - t0})}
        except urllib.error.URLError as e:
            r = e.reason
            cls = "timeout" if isinstance(r, (TimeoutError, socket.timeout)) \
                else "network"
            return unk("connect-or-send", cls, r)
        except (TimeoutError, socket.timeout) as e:
            return unk("connect-or-send", "timeout", e)
        except (OSError, http.client.HTTPException) as e:
            return unk("connect-or-send", "network", e)
        with resp:
            resp_status = getattr(resp, "status", None)
            ctype = (resp.headers.get("content-type", "") or "").split(";")[0]
            try:
                raw = resp.read(max_body + 1)
            except (TimeoutError, socket.timeout) as e:
                return unk("read-body", "timeout", e, ctype=ctype)
            except (OSError, http.client.HTTPException) as e:
                return unk("read-body", "network", e, ctype=ctype)
            except Exception as e:
                return unk("read-body", "network", e, ctype=ctype)
        if len(raw) > max_body:
            return unk("read-body", "oversize", None, raw[:max_body], ctype)
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError, MemoryError) as e:
            return unk("parse-json", "malformed", e, raw, ctype)
        echoed = data.get("model") if isinstance(data, dict) else None
        if echoed != model:
            return unk("model-check",
                       "model-missing" if echoed is None
                       else "model-mismatch", None, raw, ctype)
        try:
            ch = data["choices"][0]
            content = ch["message"]["content"]
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            r = unk("response-shape", "malformed", e, raw, ctype)
            r["diag"] = rc.clean_diag(dict(
                r["diag"], status=resp_status, **rc.shape_probe(data)))
            ur = data.get("usage") if isinstance(data, dict) else None
            r["usage"], r["usage_flag"] = rc.sanitize_usage(ur)
            r["cost_signal"] = rc.cost_signal(ur)
            return r
        usage_raw = data.get("usage")
        usage, uflag = rc.sanitize_usage(usage_raw)
        csig = rc.cost_signal(usage_raw)
        fr = rc.finish_enum(ch.get("finish_reason")
                            if isinstance(ch, dict) else None)
        if not isinstance(content, str) or not content.strip():
            r = unk("response-shape", "empty-content", None, raw, ctype)
            r["diag"]["finish_reason"] = fr
            r["usage"], r["usage_flag"], r["cost_signal"] = usage, uflag, csig
            return r
        if csig != "zero":
            # absent / invalid cost is NOT cost-verified: never an ok
            # result here (nonzero is also caught by settle()). The
            # attempt stays consumed and the run pauses.
            r = unk("cost-check", "cost-unverified", None, raw, ctype)
            r["usage"], r["usage_flag"], r["cost_signal"] = usage, uflag, csig
            return r
        return {"kind": "ok", "usage": usage, "content": content,
                "finish_reason": fr, "usage_flag": uflag,
                "cost_signal": csig}
    return post
