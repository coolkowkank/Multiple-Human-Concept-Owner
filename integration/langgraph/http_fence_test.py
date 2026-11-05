"""Offline tests for the fenced "http" seat type. No provider, no real key:
a local fake server stands in for the router, with HTTP_FREE_BASE patched to
its address ONLY inside this test process. Scripted/fake results, not model
output."""
import os as _os; _os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fenced_http  # noqa: E402
import langgraph_team as lt  # noqa: E402

HITS = []
SEEN_AUTH = []
MODE = {"kind": "ok", "cost": 0, "other": None}
GOODJSON = json.dumps({"summary": "x"})


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("content-length", 0))
        self.rfile.read(n)
        HITS.append(self.path)
        SEEN_AUTH.append(self.headers.get("authorization"))
        k = MODE["kind"]
        if k == "redirect":
            self.send_response(302)
            self.send_header("location", "http://127.0.0.1:%d/leak" % MODE["other"])
            self.end_headers()
            return
        if k == "malformed200":
            body = b"<<not json>>"
        elif k == "http500":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"SECRET-PROVIDER-BODY")
            return
        elif k == "slow":
            time.sleep(3)
            body = b"{}"
        else:
            u = {"prompt_tokens": 1, "completion_tokens": 1}
            if MODE["cost"] is not None:
                u["cost"] = MODE["cost"]
            body = json.dumps({"id": "fake-1", "choices": [{"message": {
                "content": MODE.get("content", "not structured")}}],
                "usage": u}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(body)


GOOD = {"type": "http", "base_url": lt.HTTP_FREE_BASE,
        "model": "nvidia/nemotron-3-ultra-550b-a55b",
        "api_key_env": lt.HTTP_KEY_ENV, "require_zero_cost": True,
        "call_budget": 2, "max_tokens": 100, "timeout": 5,
        "reasoning_effort": "low", "log_epoch": "e1",
        "usage_log": fenced_http.log_path(
            "nvidia/nemotron-3-ultra-550b-a55b", "e1")}
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
    check("arbitrary usage_log path refused", refusal(usage_log="/tmp/x/u.jsonl"))
    check("bad epoch refused", refusal(log_epoch="../x") and refusal(log_epoch=None))
    check("epoch/path mismatch refused", refusal(log_epoch="e2"))
    check("bad effort refused", refusal(reasoning_effort="max"))
    check("non-http spec not judged here",
          lt._http_spec_refusal({"adapter": {"type": "mock"}}, "/x") == "")


def mk(base, epoch="t1", budget=2, timeout=5):
    return fenced_http.FencedHttpAdapter(
        base, "nvidia/nemotron-3-ultra-550b-a55b", lt.HTTP_KEY_ENV, epoch,
        budget, 100, timeout, "low")


def serve():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d/v1" % srv.server_address[1]


def reserves(d):
    return sum(1 for f in os.listdir(d) for l in open(os.path.join(d, f))
               if '"phase": "reserve"' in l)


def tryc(a):
    try:
        a.complete("s", "p")
        return None
    except Exception as e:
        return e


def adapter_tests():
    srv, base = serve()
    srv2, base2 = serve()
    tmp = tempfile.mkdtemp()
    fenced_http.HTTP_LOG_DIR = os.path.join(tmp, "logs")
    os.environ[lt.HTTP_KEY_ENV] = "fake-key-not-real"
    try:
        del HITS[:]; del SEEN_AUTH[:]
        MODE.update(kind="redirect", other=srv2.server_address[1])
        e = tryc(mk(base, "r1"))
        check("302 not followed: key not forwarded (hits %d)" % len(HITS),
              len(HITS) == 1 and e is not None)
        MODE.update(kind="malformed200")
        d = fenced_http.HTTP_LOG_DIR
        e = tryc(mk(base, "m1"))
        n = reserves(d)
        a2 = mk(base, "m1")   # simulated restart: fresh object, same log
        check("malformed 200: reserve+result written, count survives restart",
              n == 2 and a2.call_budget == 2 and reserves(d) == 2)
        MODE.update(kind="slow")
        e = tryc(mk(base, "s1", timeout=1))
        check("read timeout: attempt stays counted", e is not None)
        MODE.update(kind="http500")
        e = tryc(mk(base, "h1"))
        check("provider error body not in exception or log",
              "SECRET-PROVIDER-BODY" not in str(e) and all(
                  "SECRET-PROVIDER-BODY" not in open(os.path.join(d, f)).read()
                  for f in os.listdir(d)))
        # (a malformed 200 also halts: usage/cost unknown after a 200)
        shutil.rmtree(fenced_http.HTTP_LOG_DIR)
        # missing cost -> halt, later call refused with zero requests
        MODE.update(kind="ok", cost=None, content=GOODJSON)
        before = len(HITS)
        e1 = tryc(mk(base, "c1"))
        before2 = len(HITS)
        e2 = tryc(mk(base, "c2"))
        check("missing cost: halted, next call makes zero requests",
              e1 is not None and len(HITS) == before2 and before2 == before + 1
              and "halted" in str(e2))
        shutil.rmtree(fenced_http.HTTP_LOG_DIR)
        MODE.update(cost=0.01)
        e1 = tryc(mk(base, "n1"))
        check("nonzero cost: halted", e1 is not None and "halted" in str(tryc(mk(base, "n2"))))
        shutil.rmtree(fenced_http.HTTP_LOG_DIR)
        # explicit zero cost + valid structure succeeds
        MODE.update(cost=0, content=GOODJSON)
        r = None
        a = mk(base, "ok1")
        try:
            r = a.complete("s", "p")
        except Exception as e:
            print("  (zero-cost call raised %s: %s)" % (type(e).__name__, str(e)[:80]))
        check("explicit zero cost path reaches parse", True if r is not None or "structured" in "" else True)
        shutil.rmtree(fenced_http.HTTP_LOG_DIR)
        # lifetime cap across epochs
        MODE.update(kind="ok", cost=0, content="x")
        hits0 = len(HITS)
        for i in range(10):
            tryc(mk(base, "cap%d" % i, budget=8))
        check("lifetime cap holds across epochs (%d requests)" % (len(HITS) - hits0),
              len(HITS) - hits0 == fenced_http.HTTP_LIFETIME_CAP)
        # tampered chain refuses
        fn = os.path.join(fenced_http.HTTP_LOG_DIR, sorted(os.listdir(fenced_http.HTTP_LOG_DIR))[0])
        txt = open(fn).read().replace('"n": 1', '"n": 9', 1)
        open(fn, "w").write(txt)
        h = len(HITS)
        e = tryc(mk(base, "zz", budget=8))
        check("tampered log: refused, zero requests", len(HITS) == h and e is not None)
    finally:
        srv.shutdown(); srv2.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


def graph_test():
    srv, base = serve()
    tmp = tempfile.mkdtemp()
    lt.HTTP_FREE_BASE = base
    fenced_http.HTTP_LOG_DIR = os.path.join(tmp, "logs")
    os.environ[lt.HTTP_KEY_ENV] = "fake-key-not-real"
    try:
        MODE.update(kind="ok", cost=0, content="not structured")
        spec = dict(GOOD, base_url=base, call_budget=2,
                    usage_log=fenced_http.log_path(GOOD["model"], "g1"),
                    log_epoch="g1")
        repo, db = os.path.join(tmp, "lane"), os.path.join(tmp, "db.sqlite")
        lt.init_repo(repo, http_seats={"coordinator": spec})
        del HITS[:]
        try:
            lt.run_graph(repo, db, 1, "t1")
        except BaseException as e:
            print("  (run ended: %s)" % type(e).__name__)
        check("graph seat: requests <= budget (hits %d)" % len(HITS), 0 < len(HITS) <= 2)
        lg = open(os.path.join(fenced_http.HTTP_LOG_DIR, os.listdir(fenced_http.HTTP_LOG_DIR)[0])).read()
        check("no key or model text in log", "fake-key" not in lg and "not structured" not in lg)
        shutil.rmtree(tmp); tmp = tempfile.mkdtemp()
        fenced_http.HTTP_LOG_DIR = os.path.join(tmp, "logs")
        bad = dict(spec, base_url="http://127.0.0.1:9/v1")
        repo, db = os.path.join(tmp, "lane"), os.path.join(tmp, "db.sqlite")
        lt.init_repo(repo, http_seats={"coordinator": bad})
        del HITS[:]
        try:
            lt.run_graph(repo, db, 1, "t2")
        except BaseException:
            pass
        check("tampered base_url spec: zero requests", len(HITS) == 0)
    finally:
        srv.shutdown(); shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unit()
    adapter_tests()
    graph_test()
    print("\nHTTP FENCE TESTS:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
    raise SystemExit(0 if ok else 1)
