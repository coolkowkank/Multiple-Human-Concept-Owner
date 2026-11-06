"""live_entry preflight wiring: epoch-aware accounting with NO network.
_fresh_free_listing is replaced by a sentinel that raises, so reaching it
proves the preflight passed; nothing is ever requested."""
import os as _os; _os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import hashlib, json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fenced_http, langgraph_team as lt  # noqa: E402
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
class Reached(Exception): pass
def sentinel(*a, **k): raise Reached()
lt._fresh_free_listing = sentinel
NEM, LING = "nvidia/nemotron-3-ultra-550b-a55b", "novita/ling-3.1-flash"
tmp = tempfile.mkdtemp(); logs = os.path.join(tmp, "logs"); os.makedirs(logs, mode=0o700)
fenced_http.HTTP_LOG_DIR = logs
import reserve_preflight as rp
def wlog(name, n, model):
    prev, out = "0", b""
    for i in range(1, n + 1):
        for e in ({"phase": "reserve", "n": i, "model": model, "via": "complete"},
                  {"phase": "result", "n": i, "model": model, "status": 200, "class": "ok-shape", "usage": {"cost": 0}, "cost_zero": True}):
            raw = json.dumps(dict(e, prev=prev), sort_keys=True).encode(); out += raw + b"\n"; prev = hashlib.sha256(raw).hexdigest()
    p = os.path.join(logs, name); open(p, "wb").write(out); os.chmod(p, 0o600)
slug = lambda m: os.path.basename(fenced_http.log_path(m, "X"))[:-len(".X.jsonl")]
wlog("old-free.e0.jsonl", 8, "old/free"); wlog(f"{slug(NEM)}.c1.jsonl", 1, NEM); wlog(f"{slug(LING)}.b1.jsonl", 1, LING)
print([f for f in os.listdir(logs)])
cd = os.path.join(tmp, "cfg"); os.makedirs(cd, mode=0o700)
keyf = os.path.join(cd, "k"); open(keyf, "w").write("fake-key-not-real-0123\n"); os.chmod(keyf, 0o600)
def cfg(coord_b, rev_b, name):
    c = {"key_file": keyf, "stop_after": 1, "preflight": {},
         "seats": {"coordinator": {"model": NEM, "epoch": "c1", "budget": coord_b, "max_tokens": 100},
                   "reviewer": {"model": LING, "epoch": "b1", "budget": rev_b, "max_tokens": 100}}}
    p = os.path.join(cd, name); open(p, "w").write(json.dumps(c)); os.chmod(p, 0o600); return p
def go(c, fresh=False):
    r, d = os.path.join(tmp, "lane%d" % go.n), os.path.join(tmp, "db%d" % go.n); go.n += 1
    lt.init_repo(r)
    try: lt.live_entry(r, d, c, allow_fresh=fresh)
    except Reached: return "reached"
    except SystemExit as e: return str(e.code)
    return "returned"
go.n = 0
# 8 historic + c1 + b1 = 10 = cap. Resume with budget 1/1 needs 0 new calls.
res = go(cfg(1, 1, "a.json"))
check("resume (8 historic + c1/b1 already consumed, budgets 1/1) passes the preflight and reaches the listing sentinel: " + res[:80], res == "reached")
res = go(cfg(2, 1, "b.json"))
check("one more call than remaining is still refused", res.startswith("refused") and ("over_cap" in res or "remaining" in res))
res = go(cfg(2, 2, "c.json"))
check("two more refused", res.startswith("refused"))
print("\nLIVE ENTRY BUDGET WIRING:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
raise SystemExit(0 if ok else 1)
