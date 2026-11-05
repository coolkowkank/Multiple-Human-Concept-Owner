"""Offline tests for the fenced "http" seat type. No provider, no real key:
a local fake server stands in for the router, with HTTP_FREE_BASE patched to
its address ONLY inside this test process. Scripted/fake results, not model
output."""
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import langgraph_team as lt  # noqa: E402

HITS = []
MODE = {"cost": 0}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("content-length", 0))
        self.rfile.read(n)
        HITS.append(self.path)
        body = json.dumps({"id": "fake-1", "choices": [{"message": {
            "content": "this is not the required structured response"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                      "cost": MODE["cost"]}}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(body)


GOOD = {"type": "http", "base_url": lt.HTTP_FREE_BASE,
        "model": "nvidia/nemotron-3-ultra-550b-a55b",
        "api_key_env": lt.HTTP_KEY_ENV, "require_zero_cost": True,
        "call_budget": 2, "max_tokens": 100, "timeout": 5,
        "reasoning_effort": "low", "usage_log": "/tmp/outside/u.jsonl"}
ok = True


def check(name, cond):
    global ok
    ok = ok and bool(cond)
    print(("PASS  " if cond else "FAIL  ") + name, flush=True)


def refusal(**over):
    ad = dict(GOOD)
    for k, v in over.items():
        if v is None:
            ad.pop(k, None)
        else:
            ad[k] = v
    return lt._http_spec_refusal({"adapter": ad}, "/tmp/repo-x")


def unit():
    check("exact fenced spec accepted", refusal() == "")
    check("other host refused", refusal(base_url="https://evil.example/v1"))
    check("paid/unlisted model refused", refusal(model="openai/gpt-5"))
    check("wrong key env refused", refusal(api_key_env="HOME"))
    check("zero-cost not true refused", refusal(require_zero_cost=False)
          and refusal(require_zero_cost=None))
    check("budget 0/9/bool/missing refused", all(
        refusal(call_budget=v) for v in (0, 9, True, "2", None)))
    check("max_tokens bounds", refusal(max_tokens=0) and refusal(max_tokens=10**6))
    check("extra key refused", refusal(extra="x"))
    check("relative usage_log refused", refusal(usage_log="u.jsonl"))
    check("usage_log inside repo refused",
          refusal(usage_log="/tmp/repo-x/.team/u.jsonl"))
    check("bad effort refused", refusal(reasoning_effort="max"))
    check("non-http spec not judged here",
          lt._http_spec_refusal({"adapter": {"type": "mock"}}, "/x") == "")


def seat_run(tmp, spec, steps=1):
    repo, db = os.path.join(tmp, "lane"), os.path.join(tmp, "db.sqlite")
    lt.init_repo(repo, http_seats={"coordinator": spec})
    lt.run_graph(repo, db, steps, "t1")
    return repo


def e2e():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/v1" % srv.server_address[1]
    lt.HTTP_FREE_BASE = base
    os.environ[lt.HTTP_KEY_ENV] = "fake-key-not-real"
    tmp = tempfile.mkdtemp()
    try:
        ulog = os.path.join(tmp, "usage.jsonl")
        spec = dict(GOOD, base_url=base, usage_log=ulog, call_budget=2)
        del HITS[:]
        try:
            seat_run(tmp, spec)
        except BaseException as e:  # a failed seat may raise/stop; bounded either way
            print("  (run ended: %s)" % type(e).__name__)
        lines = [json.loads(l) for l in open(ulog)] if os.path.exists(ulog) else []
        check("requests bounded by call_budget (hits %d)" % len(HITS), 0 < len(HITS) <= 2)
        check("usage log has one line per attempt", len(lines) == len(HITS))
        check("no key in usage log", "fake-key-not-real" not in open(ulog).read())
        check("usage log outside repo", not os.path.exists(os.path.join(tmp, "lane", "usage.jsonl")))
        # nonzero cost response: stop fail-closed, no further request
        shutil.rmtree(tmp); tmp = tempfile.mkdtemp()
        ulog = os.path.join(tmp, "usage.jsonl")
        MODE["cost"] = 0.01
        del HITS[:]
        try:
            seat_run(tmp, dict(spec, usage_log=ulog, call_budget=4))
        except BaseException as e:
            print("  (run ended: %s)" % type(e).__name__)
        MODE["cost"] = 0
        check("nonzero cost: exactly one request then stop (hits %d)" % len(HITS),
              len(HITS) == 1)
        # missing cost field with require_zero_cost: reported as not charged only
        # if present; absence is NOT proof of zero (documented, not asserted here)
        # tampered committed roster: other host -> zero new requests
        shutil.rmtree(tmp); tmp = tempfile.mkdtemp()
        bad = dict(spec, base_url="http://127.0.0.1:9/v1",
                   usage_log=os.path.join(tmp, "u.jsonl"))
        del HITS[:]
        res = None
        try:
            seat_run(tmp, bad)
        except BaseException as e:
            res = e
        check("tampered base_url: zero requests", len(HITS) == 0)
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unit()
    e2e()
    print("\nHTTP FENCE TESTS:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
    raise SystemExit(0 if ok else 1)
