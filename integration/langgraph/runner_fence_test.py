"""Offline tests: the runner roles' live post can only go through the
fenced adapter and the shared lifetime cap. Isolated temp roots and a
temp shared log dir, a local fake server, a fake key. No provider, no
real history, no real key. Scripted results, not model output."""
import os as _os; _os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import http.server, json, os, shutil, sys, tempfile, threading, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fenced_http as fh
fh.WINDOW_GATE = False  # window gate is covered by window_gate_test.py; this suite tests other properties
import runner_lane as rl
import ryan_cycle as rc
import runner_lane_demo_fixtures as fx

HITS, MODE = [], {"k": "ok"}
GOOD = json.dumps({"findings": [{"id": "C1", "claim": "a",
        "sources": ["P1"], "status": "SUPPORTED_BY_PACKET"}], "summary": "s"})

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", 0)))
        HITS.append(1)
        k = MODE["k"]
        if k == "drop":
            self.connection.close(); return
        if k == "302":
            self.send_response(302); self.send_header("location", "http://127.0.0.1:1/x")
            self.send_header("content-length", "0"); self.end_headers(); return
        code = {"429": 429, "err-cost": 500, "503": 503, "400": 400}.get(k, 200)
        content = "not json at all" if k == "nonjson" else GOOD
        cost = {"nonzero": 0.5, "err-cost": 0.2, "nocost": None}.get(k, 0)
        u = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
        if cost is not None: u["cost"] = cost
        body = json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                           "usage": u}).encode()
        self.send_response(code); self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body))); self.end_headers()
        self.wfile.write(body)

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]
os.environ["FAKE_KEY_ENV"] = "fake-not-a-secret"
tmp = tempfile.mkdtemp()
fails = []
def check(n, c):
    print(("PASS  " if c else "FAIL  ") + n, flush=True)
    if not c: fails.append(n)

def fresh(tag, q=None, assign=None):
    fh.HTTP_LOG_DIR = os.path.join(tmp, "shared-" + tag)
    HITS.clear(); MODE["k"] = "ok"
    d = fx.root_with(q or fx.OPEN_Q, assign or fx.ASSIGN, tmp)
    att = []
    post = rl.FencedRunner(d, att, BASE, "FAKE_KEY_ENV", "t" + tag,
                           allowed_models=fx.ALLOWED)
    return d, att, post

def shared_lines():
    out = []
    if os.path.isdir(fh.HTTP_LOG_DIR):
        for fn in sorted(os.listdir(fh.HTTP_LOG_DIR)):
            out += [json.loads(l) for l in open(os.path.join(fh.HTTP_LOG_DIR, fn)) if l.strip()]
    return out
def seed_shared(n, halt=False):
    os.makedirs(fh.HTTP_LOG_DIR, mode=0o700, exist_ok=True)
    path = os.path.join(fh.HTTP_LOG_DIR, "seed.jsonl")
    import hashlib
    prev, lines = "0", []
    for i in range(n):
        raw = json.dumps({"phase": "reserve", "n": i + 1, "model": "m", "prev": prev}, sort_keys=True)
        prev = hashlib.sha256(raw.encode()).hexdigest(); lines.append(raw)
    if halt:
        raw = json.dumps({"phase": "halt", "n": 1, "prev": prev}, sort_keys=True); lines.append(raw)
    open(path, "w").write("\n".join(lines) + "\n")
def run(d, att, post, **kw):
    return rl.live_runner_step(d, fx.FRESH, fx.RECORD, post, now=fx.T0, clock=lambda: fx.T0, **kw)
def phases(d): return [e["phase"] for e in rc.Store(d).ledger()]

# never the independent path
def boom(*a, **k): raise AssertionError("http_post_factory used")
rc.http_post_factory = boom

d, att, post = fresh("ok")
r = run(d, att, post)
sl = shared_lines()
check("F1 success: one request, runner reserved+result ok", len(HITS) == 1 and phases(d) == ["reserved", "result"] and rc.Store(d).ledger()[1]["outcome"] == "ok")
check("F1 shared log has reserve+exec+result (same single request), used 1", [e["phase"] for e in sl] == ["reserve", "exec", "result"] and r["shared"] == {"before_used": 0, "after_used": 1})
check("F1 step applied from raw content", r["step"] is not None and r["step"].get("action") != "needs-human")

d, att, post = fresh("cap"); seed_shared(fh.HTTP_LIFETIME_CAP)
r = run(d, att, post)
check("F2 shared cap reached -> preflight refuses: no runner reserve, no request", r["refused"] and HITS == [] and phases(d) == [])

d, att, post = fresh("capm1"); seed_shared(fh.HTTP_LIFETIME_CAP - 1)
r = run(d, att, post)
check("F2c one slot below the cap: exactly one request, shared used reaches the cap", len(HITS) == 1 and r["shared"]["after_used"] == fh.HTTP_LIFETIME_CAP)
r2 = run(d, att, post)
check("F2c the next request is refused at the cap (no second request)", len(HITS) == 1 and r2["refused"])

d, att, post = fresh("shalt"); seed_shared(1, halt=True)
r = run(d, att, post)
check("F2b shared halt -> preflight refuses, no request", r["refused"] and HITS == [] and phases(d) == [])

d, att, post = fresh("race1")
def poison(): seed_shared(fh.HTTP_LIFETIME_CAP)
r = run(d, att, post, before_io=poison)
led = rc.Store(d).ledger()
check("F3 cap lost after preflight, before gate: gate reserve refuses, runner records factual not_sent, 0 requests, no shared reserve",
      HITS == [] and [e["phase"] for e in led] == ["reserved", "halt", "result", "halt"] and led[2]["outcome"] == "not_sent"
      and att[0]["known_not_sent"] is True and r["shared"]["after_used"] == fh.HTTP_LIFETIME_CAP)

d, att, post = fresh("race1b")
def poison_halt(): seed_shared(1, halt=True)
r = run(d, att, post, before_io=poison_halt)
led = rc.Store(d).ledger()
check("F3b shared halt appears after preflight: not_sent, 0 requests", HITS == [] and led[2]["outcome"] == "not_sent")

d, att, post = fresh("race2")
inner = post.post
def racing(*a, **k):
    seed_shared(fh.HTTP_LIFETIME_CAP); return inner(*a, **k)   # lost AFTER the shared reserve
post.post = racing
r = run(d, att, post)
check("F4 cap exhaustion after the reserve does not block the reserved request (halt would, see F18); exactly one request", len(HITS) == 1 and phases(d)[:2] == ["reserved", "result"])

# token discipline (durable, log-level)
import copy, subprocess
MN = "nvidia/nemotron-3-ultra-550b-a55b"
def newad(ep): return fh.FencedHttpAdapter(BASE, MN, "FAKE_KEY_ENV", ep, 8, 64, 5, "low")
fh.HTTP_LOG_DIR = os.path.join(tmp, "shared-tok"); HITS.clear(); MODE["k"] = "ok"
ad = newad("tk")
tok = ad.reserve()
check("F13 reserve alone makes no request, one reserve line with a rid, state reserved-not-started",
      HITS == [] and [e["phase"] for e in shared_lines()] == ["reserve"] and fh.reserve_states() == {tok.rid: "reserved-not-started"})
r1 = ad.execute(tok, "s", "p")
check("F13 execute: exec claim before result, state settled", r1["kind"] == "ok" and [e["phase"] for e in shared_lines()] == ["reserve", "exec", "result"] and fh.reserve_states()[tok.rid] == "settled")
for label, mk in (("same object", lambda: tok), ("copied object", lambda: copy.copy(tok)),
                  ("rebuilt object, same rid", lambda: fh.Reservation(MN, tok.n, tok.rid, tok.path))):
    try:
        ad.execute(mk(), "s", "p"); ok_ = False
    except fh.FenceRefused:
        ok_ = True
    check("F13 reuse refused (%s), still one request" % label, ok_ and len(HITS) == 1)
try:
    ad.execute(fh.Reservation(MN, 5, "deadbeefdeadbeef", ad.path), "s", "p"); forged = False
except fh.FenceRefused:
    forged = True
check("F13 forged rid (no reserve line) refused, no exec line written", forged and len(HITS) == 1 and sum(1 for e in shared_lines() if e["phase"] == "exec") == 1)

# concurrency: one reserve, many threads with copied/forged/rebuilt tokens
fh.HTTP_LOG_DIR = os.path.join(tmp, "shared-conc"); HITS.clear()
ad = newad("cc"); tok = ad.reserve()
outs = []
def worker(i):
    t_ = tok if i == 0 else (copy.copy(tok) if i % 2 else fh.Reservation(MN, tok.n, tok.rid, tok.path))
    try:
        ad.execute(t_, "s", "p"); outs.append("ran")
    except fh.FenceRefused:
        outs.append("refused")
ths = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
[x.start() for x in ths]; [x.join() for x in ths]
check("F16 8 threads, separate token objects, one reserve: exactly one request, one exec line, one result",
      outs.count("ran") == 1 and len(HITS) == 1 and sum(1 for e in shared_lines() if e["phase"] == "exec") == 1 and sum(1 for e in shared_lines() if e["phase"] == "result") == 1)
# second PROCESS with the same rid
child = ("import sys,os;sys.path.insert(0,%r);import fenced_http as fh;fh.WINDOW_GATE=False;fh.HTTP_LOG_DIR=%r;"
         "os.environ['FAKE_KEY_ENV']='x';ad=fh.FencedHttpAdapter(%r,%r,'FAKE_KEY_ENV','cc',8,64,5,'low');"
         "t=fh.Reservation(%r,%d,%r,ad.path)\ntry:\n ad.execute(t,'s','p');print('RAN')\nexcept fh.FenceRefused:\n print('REFUSED')\n"
         % (HERE, fh.HTTP_LOG_DIR, BASE, MN, MN, tok.n, tok.rid))
pr = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True, timeout=30)
check("F16 second process with the same rid refused, still one request", "REFUSED" in pr.stdout and len(HITS) == 1)

# crash states
fh.HTTP_LOG_DIR = os.path.join(tmp, "shared-crash"); HITS.clear()
ad = newad("cr"); t1 = ad.reserve()          # crash before execute
st = fh.reserve_states()
check("F17 reserve with no exec: reserved-not-started (fence never began a request), cap consumed (used 1)", st == {t1.rid: "reserved-not-started"} and fh._read_all(fh.HTTP_LOG_DIR)[0] == 1 and HITS == [])
t2 = ad.reserve()
orig_io = ad._io
def dying(*a, **k): raise SystemExit("simulated crash after exec claim")
ad._io = dying
try:
    ad.execute(t2, "s", "p")
except SystemExit:
    pass
ad._io = orig_io
check("F17 crash after exec claim: started-unsettled (possibly sent, unknown), never re-executed",
      fh.reserve_states()[t2.rid] == "started-unsettled")
try:
    ad.execute(fh.Reservation(MN, t2.n, t2.rid, t2.path), "s", "p"); again = False
except fh.FenceRefused:
    again = True
check("F17 rerun after crash refused, 0 requests", again and HITS == [])

# complete() crash and legacy lines are never "not started"
fh.HTTP_LOG_DIR = os.path.join(tmp, "shared-cc2"); HITS.clear()
ad = newad("cx")
def dying2(*a, **k): raise SystemExit("simulated kill inside complete()")
ad._io = dying2
try:
    ad.complete("s", "p")
except SystemExit:
    pass
st = fh.reserve_states()
check("F19 killed complete(): reserve has no exec line but state is unknown-complete-path, never reserved-not-started", list(st.values()) == ["unknown-complete-path"])
crid = list(st)[0]
ad._io = ad.__class__._io.__get__(ad)
try:
    ad.execute(fh.Reservation(MN, 1, crid, ad.path), "s", "p"); ex = False
except fh.FenceRefused:
    ex = True
check("F19 execute() on a complete()-path reserve is refused, 0 requests", ex and HITS == [])
os.makedirs(fh.HTTP_LOG_DIR, exist_ok=True)
open(os.path.join(fh.HTTP_LOG_DIR, "old.jsonl"), "w").write(json.dumps({"phase": "reserve", "n": 1, "model": "m", "prev": "0"}, sort_keys=True) + "\n")
check("F19 legacy rid-less reserve is unknown-legacy", "unknown-legacy" in fh.reserve_states().values())

# halt rechecked under the claim lock
fh.HTTP_LOG_DIR = os.path.join(tmp, "shared-halt"); HITS.clear()
ad = newad("hl"); t3 = ad.reserve()
os.makedirs(fh.HTTP_LOG_DIR, exist_ok=True)
import hashlib as _h
hl = json.dumps({"phase": "halt", "n": 1, "prev": "0"}, sort_keys=True)
open(os.path.join(fh.HTTP_LOG_DIR, "other.jsonl"), "w").write(hl + "\n")
try:
    ad.execute(t3, "s", "p"); refused = False
except fh.FenceRefused:
    refused = True
check("F18 halt written after the reserve stops the request (exec-refused, known not sent), 0 requests",
      refused and HITS == [] and fh.reserve_states()[t3.rid] == "refused-before-start")

# seam dependency: if the pinned runner stops calling before_io, no request
d, att, post = fresh("noseam")
_orig = rc.step
rc.step = lambda root, p, lm, now, rec, clock=None, before_io=None: _orig(root, p, lm, now, rec, clock=clock)
r = run(d, att, post)
rc.step = _orig
check("F14 before_io seam not called: no request, Halt, runner reserve left without a result (operator reconcile)", HITS == [] and r["halted"] and phases(d) == ["reserved"])

d, att, post = fresh("429"); MODE["k"] = "429"
r = run(d, att, post)
check("F5 429: one request, runner halts, shared reserve kept, no retry", len(HITS) == 1 and phases(d)[-1] == "halt" and r["halted"])
r2 = run(d, att, post)
check("F5 second step blocked by runner halt, still one request", len(HITS) == 1 and r2["halted"])

d, att, post = fresh("cost"); MODE["k"] = "nonzero"
r = run(d, att, post)
check("F6 nonzero cost: shared halt line + runner halt", len(HITS) == 1 and any(e["phase"] == "halt" for e in shared_lines()) and phases(d)[-1] == "halt")
r2 = run(d, att, post)
check("F6 later step refused by shared halt (no request)", len(HITS) == 1 and r2["refused"])

d, att, post = fresh("nocost"); MODE["k"] = "nocost"
r = run(d, att, post)
check("F6b missing cost field: halts (unknown cost stays consumed)", len(HITS) == 1 and phases(d)[-1] == "halt" and any(e["phase"] == "halt" for e in shared_lines()))

d, att, post = fresh("drop"); MODE["k"] = "drop"
r = run(d, att, post)
led = rc.Store(d).ledger()
check("F7 dropped connection: unknown, consumed, halt, one request", len(HITS) == 1 and led[1]["outcome"] == "unknown" and phases(d)[-1] == "halt" and att[0]["known_not_sent"] is False)

d, att, post = fresh("nonjson"); MODE["k"] = "nonjson"
r = run(d, att, post)
check("F8 raw 200 non-JSON: transport ok, runner format precheck fails (distinct from transport)", len(HITS) == 1 and att[0]["kind"] == "ok" and r["step"]["action"] == "precheck-failed")
ad = fh.FencedHttpAdapter(BASE, "nvidia/nemotron-3-ultra-550b-a55b", "FAKE_KEY_ENV", "tc", 8, 64, 5, "low")
try:
    ad.complete("s", "p"); ok = False
except fh.AdapterError as e:
    ok = "not JSON" in str(e)
check("F8 complete() on same reply still raises not-JSON (behavior unchanged)", ok)

d, att, post = fresh("gemma", assign={**fx.ASSIGN, "models": {**fx.ASSIGN["models"], "researcher": "google/gemma-4-31b-it"}})
r = run(d, att, rl.FencedRunner(d, att, BASE, "FAKE_KEY_ENV", "tg"))
check("F9 non-allowlisted model: known not_sent by fence, 0 requests", HITS == [] and att and att[0]["cause"] == "model-not-allowlisted" and rc.Store(d).ledger()[2]["outcome"] == "not_sent")

d, att, post = fresh("gem")
st = rc.Store(d)
for e in ({"phase": "reserved", "rid": "g-0", "ts": rc.iso(fx.T0 - 99), "qid": "q1", "role": "verifier", "model": "google/gemma-4-31b-it"},
          {"phase": "result", "rid": "g-0", "ts": rc.iso(fx.T0 - 98), "qid": "q1", "role": "verifier", "model": "google/gemma-4-31b-it", "outcome": "unknown", "usage": None},
          {"phase": "halt", "ts": rc.iso(fx.T0 - 97), "reason": "unknown transport outcome g-0"}):
    st.append(e)
before = open(st.lpath, "rb").read()
r = run(d, att, post)
check("F10 prior unknown outcome + halt stands: no request, ledger bytes unchanged, no clearing", HITS == [] and r["halted"] and open(st.lpath, "rb").read() == before)

for mode, label in (("503", "5xx"), ("302", "redirect")):
    d, att, post = fresh("m" + mode); MODE["k"] = mode
    r = run(d, att, post)
    led = rc.Store(d).ledger()
    check("F15 %s: unknown outcome, runner halts, one request, shared reserve kept" % label,
          len(HITS) == 1 and led[1]["outcome"] == "unknown" and phases(d)[-1] == "halt" and att[0]["kind"] == "unknown")
d, att, post = fresh("m500c"); MODE["k"] = "err-cost"
r = run(d, att, post)
check("F15 500 with nonzero error-body cost: halts BOTH ledgers", len(HITS) == 1 and phases(d)[-1] == "halt" and any(e["phase"] == "halt" for e in shared_lines()))
d, att, post = fresh("m400"); MODE["k"] = "400"
r = run(d, att, post)
check("F15 400: runner halts on http 400, one request", len(HITS) == 1 and phases(d)[-1] == "halt" and att[0]["kind"] == "http")
# error-body cost (non-200 with nonzero cost) and finish_reason pass-through
MODE["k"] = "err-cost"
fh.HTTP_LOG_DIR = os.path.join(tmp, "shared-ec")
ad = fh.FencedHttpAdapter(BASE, "nvidia/nemotron-3-ultra-550b-a55b", "FAKE_KEY_ENV", "ec", 8, 64, 5, "low")
r = ad.execute(ad.reserve(), "s", "p")
check("F12 non-200 body with nonzero cost is surfaced (runner will halt)", r["kind"] == "unknown" and r["cost_signal"] == "nonzero" and any(e["phase"] == "halt" for e in shared_lines()))
MODE["k"] = "ok"
fh.HTTP_LOG_DIR = os.path.join(tmp, "shared-ec2")
r = ad.execute(ad.reserve(), "s", "p")
check("F12 finish_reason passed through", r["kind"] == "ok" and r["finish_reason"] == "stop")
import ast
tree = ast.parse(open(os.path.join(HERE, "runner_lane.py")).read())
names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
check("F11 runner_lane code never references http_post_factory (AST)", "http_post_factory" not in names)

shutil.rmtree(tmp, ignore_errors=True)
print("FAILED: %s" % fails if fails else "all passed")
sys.exit(1 if fails else 0)
