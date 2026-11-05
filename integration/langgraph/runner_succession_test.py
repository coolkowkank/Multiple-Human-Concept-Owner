"""Offline tests for the successor-window shape patch in the vendored runner
(a successor is [verifier] or [verifier, ryan], never ryan-only). Temp roots,
a throwaway test key, scripted ledger lines. No provider, no real history, no
real key. Run: python3 runner_succession_test.py"""
import hashlib, json, os, shutil, stat, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "runner"))
import ryan_cycle as rc
import make_allowance as ma
import runner_lane_demo_fixtures as fx

T0 = fx.T0
tmp = tempfile.mkdtemp()
kp = os.path.join(tmp, "test-key"); open(kp, "w").write("test-only-not-a-secret\n"); os.chmod(kp, 0o600)
os.environ["RYAN_ALLOWANCE_KEY_FILE"] = kp
fails = []
def check(n, c):
    print(("PASS  " if c else "FAIL  ") + n, flush=True)
    if not c: fails.append(n)
def md5(p): return hashlib.md5(open(os.path.join(HERE, p), "rb").read()).hexdigest()

FIND = [{"id": "C1", "claim": "alpha claim", "sources": ["P1"], "status": "SUPPORTED_BY_PACKET"}]
def mkq(): return {"id": "q2", "status": "drafted", "attempts": {}, "question": "?", "packet": fx.PACKET,
                   "lineage": "L", "findings": FIND, "kind": "verify"}
def res(i, role, model, qid="q2", aid=None):
    e = {"phase": "reserved", "rid": "r%d" % i, "role": role, "model": model, "qid": qid,
         "lineage": "L", "work_fp": rc.work_fp(mkq())}
    if aid: e["allowance"] = aid
    return e

def world(ryan_model="novita/ling-3.1-flash"):
    """lineage: researcher 1 + verifier 4 (one under bound window A1, which is stopped)."""
    d = fx.root_with(mkq(), fx.ASSIGN, tmp); st = rc.Store(d); q = st.queue()["questions"][0]
    fp = rc.work_fp(q)
    st.append(res(0, "researcher", fx.NEM)); st.append(res(1, "verifier", "m-ling"))
    st.append(res(2, "verifier", "m-leanstral")); st.append(res(3, "verifier", "m-old-a", aid="A1"))
    st.append(res(4, "verifier", "m-old-b", aid="A2"))
    st.append({"phase": "allowance-bind", "allowance": "A1", "lineage": "L", "work_fp": fp, "digest": "d" * 64})
    st.append({"phase": "allowance-stop", "allowance": "A1", "reason": "x", "kind": "failure"})
    st.append({"phase": "allowance-bind", "allowance": "A2", "lineage": "L", "work_fp": fp, "digest": "e" * 64, "succeeds": "A1"})
    st.append({"phase": "allowance-stop", "allowance": "A2", "reason": "settle halted", "kind": "failure"})
    return d, st, q

def grant(d, st, q, roles=("verifier", "ryan"), vmodel="m-new", rmodel="novita/ling-3.1-flash", aid="A3",
          succ=None, fp=None, maxr=None, ttl=3000, issued=-60, base=None):
    used = rc.lineage_counts(st, st.queue(), q)
    base = base or {r: used.get(r, 0) for r in rc.ROLE_CAP}
    models = {"verifier": vmodel, "ryan": rmodel}
    roles = list(roles)
    body = {"version": 2, "id": aid, "lineage": "L", "work_fp": fp or rc.work_fp(q), "roles": roles,
            "models": {r: models[r] for r in roles if r in models}, "baseline": base,
            "max_counts": {r: base[r] + 1 for r in roles}, "max_requests": maxr if maxr is not None else len(roles),
            "issued_at": rc.iso(T0 + issued), "expires_at": rc.iso(T0 + issued + ttl + 60),
            "succeeds": succ or {"id": "A2", "digest": "e" * 64}}
    key, _ = rc._allowance_key()
    json.dump({"body": body, "sig": rc.allowance_sign(key, body)}, open(os.path.join(d, "allowance.json"), "w"))
    return body

def win(d, st, q, role, model):
    used = rc.lineage_counts(st, st.queue(), q)
    return rc.allowance_window(d, st, q, role, used, model, T0)

def done(st, i, role, model, aid="A3"):
    st.append(res(i, role, model, aid=aid)); st.append({"phase": "allowance-done", "allowance": aid, "rid": "r%d" % i, "role": role})

# --- shape ---------------------------------------------------------------
d, st, q = world(); b = grant(d, st, q)
check("shape: [verifier,ryan] successor accepted with succession", rc._shape_ok(b, succession_ok=True) == "")
check("shape: [verifier] successor still accepted", rc._shape_ok(grant(d, st, q, roles=("verifier",)), succession_ok=True) == "")
check("shape: ryan-only successor refused", "successor" in rc._shape_ok(grant(d, st, q, roles=("ryan",)), succession_ok=True))
bad = dict(b); bad["roles"] = ["ryan", "verifier"]
check("shape: reversed roles refused", rc._shape_ok(bad, succession_ok=True) != "")
bad = dict(b); bad["models"] = {"verifier": "m-new"}
check("shape: ryan role without ryan model refused", rc._shape_ok(bad, succession_ok=True) != "")
bad = dict(b); bad["max_requests"] = 1
check("shape: two roles with max_requests 1 refused", rc._shape_ok(bad, succession_ok=True) != "")
bad = dict(b); bad["max_requests"] = 3
check("shape: max_requests 3 refused", rc._shape_ok(bad, succession_ok=True) != "")
check("shape: without succession the cap+1 relaxation is not granted (verifier base 4)", rc._shape_ok(b, succession_ok=False) != "")
# regression: the pre-patch source refused the two-step successor shape
old = subprocess.run(["git", "-C", HERE, "show", "ac1557c:integration/langgraph/runner/ryan_cycle.py"], capture_output=True, text=True)
if old.returncode == 0:
    ns = {"__name__": "old_rc"}; od = os.path.join(tmp, "old"); os.makedirs(od)
    open(os.path.join(od, "ryan_cycle.py"), "w").write(old.stdout)
    r = subprocess.run([sys.executable, "-c", "import sys,json;sys.path.insert(0,%r);sys.path.append(%r);import ryan_cycle as o;b=json.loads(sys.argv[1]);print(o._shape_ok(b,succession_ok=True))" % (od, os.path.join(HERE, "runner")), json.dumps(b)], capture_output=True, text=True)
    check("regression: pre-patch code refused the [verifier,ryan] successor", "exactly one verifier request" in r.stdout)
else:
    print("SKIP  regression against ac1557c (git object not available)")

# --- chain: verifier step then ryan step ----------------------------------
d, st, q = world(); grant(d, st, q); before = st.ledger()
check("chain: ryan before verifier is not the next step", win(d, st, q, "ryan", "novita/ling-3.1-flash")[0] == "blocked")
w = win(d, st, q, "verifier", "m-new")
check("chain: verifier step ok and binds the successor", w[0] == "ok" and st.ledger()[-1]["phase"] == "allowance-bind" and st.ledger()[-1]["succeeds"] == "A2")
check("chain: history lines before the new bind are unchanged", st.ledger()[:len(before)] == before)
check("chain: ryan blocked while the verifier request has no allowance-done", (st.append(res(9, "verifier", "m-new", aid="A3")), win(d, st, q, "ryan", "novita/ling-3.1-flash")[0])[1] == "blocked")
st.append({"phase": "allowance-done", "allowance": "A3", "rid": "r9", "role": "verifier"})
w = win(d, st, q, "ryan", "novita/ling-3.1-flash")
check("chain: ryan ok after clean verifier done", w[0] == "ok")
check("chain: ryan pinned model enforced", win(d, st, q, "ryan", "other/model")[0] == "blocked")
done(st, 10, "ryan", "novita/ling-3.1-flash")
check("chain: window exhausted after ryan; no retry", win(d, st, q, "ryan", "novita/ling-3.1-flash")[0] == "blocked" and win(d, st, q, "verifier", "m-new")[0] == "blocked")

# --- stop / unknown / expiry / grant removed or replaced between steps -------
def at_ryan():
    d, st, q = world(); grant(d, st, q); win(d, st, q, "verifier", "m-new"); done(st, 9, "verifier", "m-new"); return d, st, q
d, st, q = at_ryan(); st.append({"phase": "allowance-stop", "allowance": "A3", "reason": "stale", "kind": "stale"})
check("stop line blocks ryan", win(d, st, q, "ryan", "novita/ling-3.1-flash")[0] == "blocked")
d, st, q = at_ryan(); os.remove(os.path.join(d, "allowance.json"))
check("grant deleted between steps blocks ryan", win(d, st, q, "ryan", "novita/ling-3.1-flash")[0] == "blocked")
d, st, q = at_ryan(); grant(d, st, q, aid="A4", succ={"id": "A3", "digest": "f" * 64})
check("grant replaced (wrong predecessor digest/not terminal) blocks ryan", win(d, st, q, "ryan", "novita/ling-3.1-flash")[0] == "blocked")
d, st, q = at_ryan(); grant(d, st, q, aid="A3", ttl=100, issued=-3000)
check("expired window blocks ryan", win(d, st, q, "ryan", "novita/ling-3.1-flash")[0] == "blocked")
d, st, q = world(); grant(d, st, q); win(d, st, q, "verifier", "m-new"); st.append(res(9, "verifier", "m-new", aid="A3"))
check("unknown/unfinished verifier request blocks ryan", win(d, st, q, "ryan", "novita/ling-3.1-flash")[0] == "blocked")

# --- succession invariants --------------------------------------------------
def first(**kw):
    d, st, q = world(); grant(d, st, q, **kw); return win(d, st, q, "verifier", kw.get("vmodel", "m-new"))
check("invariant: valid successor ok", first()[0] == "ok")
check("invariant: wrong predecessor digest blocked", first(succ={"id": "A2", "digest": "0" * 64})[0] == "blocked")
check("invariant: wrong predecessor id blocked", first(succ={"id": "A1", "digest": "d" * 64})[0] == "blocked")
check("invariant: wrong work_fp blocked", first(fp="0" * 64)[0] == "blocked")
check("invariant: prior bound-window model reused blocked", first(vmodel="m-old-b")[0] == "blocked")
check("invariant: model used only before any window is not blocked by the rule", first(vmodel="m-ling")[0] == "ok")
check("invariant: reused window id blocked", first(aid="A2")[0] == "blocked")
check("invariant: baseline off lineage counts blocked", first(base={"researcher": 1, "verifier": 3, "ryan": 0})[0] == "blocked")
d, st, q = world(); st.append({"phase": "allowance-bind", "allowance": "A2x", "lineage": "L", "work_fp": rc.work_fp(q), "digest": "9" * 64, "succeeds": "A2"})
grant(d, st, q)
check("invariant: prior window not terminal blocked", win(d, st, q, "verifier", "m-new")[0] == "blocked")
d, st, q = world(); grant(d, st, q); st.append(res(8, "verifier", "m-extra"))
check("invariant: a lineage request outside the window after baseline blocked", win(d, st, q, "verifier", "m-new")[0] == "blocked")

# --- make_allowance ---------------------------------------------------------
d, st, q = world(); st.save_queue({"questions": [dict(q, status="ready-verify", attempts={})]})
q2 = st.queue()["questions"][0]
if rc.next_action(q2) == "verifier":
    try:
        doc = ma.build(d, "q2", "A3", 30, "m-new", ryan="novita/ling-3.1-flash", now=T0)
        check("make_allowance: successor with ryan built only for the assignments ryan model (fixture ryan is nemotron, so refused)", False)
    except SystemExit as e:
        check("make_allowance: ryan model != assignments ryan model refused", "ryan model" in str(e) or "not a valid" in str(e) or "assignments" in str(e))
    try:
        doc = ma.build(d, "q2", "A3", 30, "m-new", ryan=fx.NEM, now=T0)
        check("make_allowance: ryan = assignments model builds [verifier,ryan] with succeeds", doc["body"]["roles"] == ["verifier", "ryan"] and doc["body"]["succeeds"]["id"] == "A2" and doc["body"]["max_counts"]["verifier"] == 5)
    except SystemExit as e:
        check("make_allowance: built (%s)" % e, False)
else:
    print("SKIP  make_allowance build (fixture item not at verifier step: %s)" % rc.next_action(q2))

# --- pins ---------------------------------------------------------------------
check("pin: patched ryan_cycle.py md5", md5("runner/ryan_cycle.py") == "7aa68e610e7e9da3659b592fb98a96f2")
check("pin: patched make_allowance.py md5", md5("runner/make_allowance.py") == "e81caf38b546ee4b94f1de34dea4ac42")
shutil.rmtree(tmp, ignore_errors=True)
print("ALL PASS" if not fails else "FAILED: %s" % fails); sys.exit(1 if fails else 0)
