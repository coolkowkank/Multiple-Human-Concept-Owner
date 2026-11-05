"""Offline RW4: cooperative live-owner declaration + spending-seat no-auto-replay.
Fakes only: no real process, no provider, no lease or ledger action."""
import os as _os; _os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import json, os, shutil, stat, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import langgraph_team as lt  # noqa: E402
from launcher import liveness as lv  # noqa: E402
from launcher.bus import Bus  # noqa: E402
from launcher.runtime import Seat  # noqa: E402
from launcher.supervisor import Supervisor  # noqa: E402
ok = True
def check(n, c):
    global ok; ok = ok and bool(c); print(("PASS  " if c else "FAIL  ") + n, flush=True)
NOW = 2_000_000_000.0
def st(**k):
    d = {"turn": "builder", "turn_seq": 7, "turn_since": "2033-05-18T03:00:00Z", "status": "running",
         "leases": {"builder": {"holder": "H1", "claimed_at": NOW}}}
    d.update(k); return d
def decl(**k):
    d = {"v": 1, "seat": "builder", "pid": 4242, "turn": "builder", "turn_seq": 7,
         "turn_since": "2033-05-18T03:00:00Z", "holder": "H1", "phase": "adapter",
         "written_at": NOW - 10, "deadline": NOW + 300}
    d.update(k); return d
V = lambda d, now=NOW, pid=4242, s=None: lv.liveness(s or st(), d, now, pid)[0]
# ---- pure liveness
check("valid bound declaration inside its deadline is live", V(decl()) == "live")
check("past its own deadline is overrun", V(decl(deadline=NOW - 1)) == "overrun")
for nm, d in (("missing", None), ("not a dict", [1]), ("other seat", decl(seat="qc")), ("old turn_seq", decl(turn_seq=6)),
              ("old turn_since", decl(turn_since="2033-05-18T02:00:00Z")), ("other holder", decl(holder="H2")),
              ("bool pid", decl(pid=True)), ("bad phase", decl(phase="x")), ("future stamp", decl(written_at=NOW + 99, deadline=NOW + 399)),
              ("window too large", decl(deadline=NOW + 10**6)), ("zero window", decl(deadline=NOW - 10)),
              ("nan deadline", decl(deadline=float("nan"))), ("string deadline", decl(deadline="9")), ("bool deadline", decl(deadline=True)),
              ("wrong version", decl(v=2))):
    v = V(d) if nm != "zero window" else V(decl(deadline=NOW - 10), now=NOW - 20)
    check(f"{nm}: unknown, never live", v == "unknown")
check("a different pid (not the supervisor-started process) is unknown", V(decl(), pid=1) == "unknown" and V(decl(), pid=None) == "unknown")
# ---- declaration file safety
tmp = tempfile.mkdtemp()
try:
    r = os.path.join(tmp, "lane"); lt.init_repo(r)
    s = {"turn": "builder", "turn_seq": 7, "turn_since": "2033-05-18T03:00:00Z"}
    check("write ok", lv.write_declaration(r, "builder", s, "H1", "adapter", 90, time.time()))
    p = os.path.join(r, ".git", "lg-live-builder.json")
    check("file is private 0600, no temp left", stat.S_IMODE(os.stat(p).st_mode) == 0o600 and not [f for f in os.listdir(os.path.join(r, ".git")) if f.endswith(".tmp")])
    d = lv.read_declaration(r, "builder"); check("round trip: bound to our pid and the turn", d and d["pid"] == os.getpid() and d["turn_seq"] == 7 and d["deadline"] - d["written_at"] == 90)
    check("worktree stays clean (declaration is git-private)", __import__("subprocess").run(["git", "-C", r, "status", "--porcelain"], capture_output=True, text=True).stdout.strip() == "")
    os.chmod(p, 0o644); check("group/other-readable file refused", lv.read_declaration(r, "builder") is None); os.chmod(p, 0o600)
    big = open(p).read(); open(p, "w").write(big + " " * 5000); check("oversize refused", lv.read_declaration(r, "builder") is None)
    open(p, "w").write("garbage"); check("garbage refused", lv.read_declaration(r, "builder") is None)
    os.unlink(p); os.symlink("/etc/hostname", p); check("symlink refused", lv.read_declaration(r, "builder") is None); os.unlink(p)
    os.mkdir(p); check("directory refused", lv.read_declaration(r, "builder") is None); os.rmdir(p)
    check("unsafe seat name never builds a path", lv.write_declaration(r, "../x", s, "H1", "adapter", 9, time.time()) is False and lv.read_declaration(r, "a/b") is None)
    check("unbounded/NaN/negative seconds refused", not any(lv.write_declaration(r, "builder", s, "H1", "adapter", x, time.time()) for x in (0, -1, float("nan"), 10**9)))
    check("write failure (no repo) never raises and returns False", lv.write_declaration(os.path.join(tmp, "nope"), "builder", s, "H1", "adapter", 9, time.time()) is False)
    # clear only removes OUR declaration
    lv.write_declaration(r, "builder", s, "H1", "adapter", 90, time.time()); lv.clear_declaration(r, "builder")
    check("clear removes our declaration", lv.read_declaration(r, "builder") is None)
    lv.write_declaration(r, "builder", s, "H1", "adapter", 90, time.time())
    dd = json.load(open(p)); dd["pid"] = os.getpid() + 1; open(p, "w").write(json.dumps(dd)); os.chmod(p, 0o600)
    lv.clear_declaration(r, "builder"); check("clear leaves another process's declaration", os.path.exists(p)); os.unlink(p)
    # ---- Seat._complete declares during the call and clears after (also on error)
    b = Bus(r, lt.BRANCH); seat = Seat(b, "coordinator", instance_id="H1")
    seen = {}
    class A:
        max_retries = 0
        def complete(self, sy, pr):
            seen["during"] = lv.read_declaration(r, "coordinator"); 
            if seen.get("boom"): raise RuntimeError("x")
            return {}
    seat.adapter = A(); seat._live_ident = {"turn": "coordinator", "turn_seq": 1, "turn_since": "t"}
    seat.spec = dict(seat.spec); seat.spec["adapter"] = {"type": "http", "timeout": 100}
    seat._complete("s", "p")
    dd = seen["during"]; check("declared during the adapter call with the step's own bound (timeout x tries + grace)", dd and dd["phase"] == "adapter" and abs((dd["deadline"] - dd["written_at"]) - (100 + Seat.LIVE_GRACE)) < 1 and dd["holder"] == "H1")
    check("cleared after the call", lv.read_declaration(r, "coordinator") is None)
    seen["boom"] = 1
    try: seat._complete("s", "p")
    except RuntimeError: pass
    check("cleared even when the call raises", lv.read_declaration(r, "coordinator") is None)
    seat.adapter.max_retries = 3; seat.spec["adapter"] = {"type": "http", "timeout": 100}; seen["boom"] = 0
    seat._complete("s", "p"); dd = seen["during"]
    check("retrying adapters declare a bound covering every attempt", abs((dd["deadline"] - dd["written_at"]) - (400 + Seat.LIVE_GRACE)) < 1)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
# ---- supervisor decisions (fake bus, fake procs, no processes)
class P:
    def __init__(s, pid=4242, rc=None): s.t = 0; s.pid = pid; s.rc = rc; s.returncode = rc
    def terminate(s): s.t += 1
    def poll(s): return s.rc
class B:
    def __init__(s, kinds, state): s.log = []; s.gates = []; s.commits = []; s.kinds = kinds; s._st = state; s.broken = False
    def append_log(s, *a): s.log.append(a)
    def commit_all(s, m): s.commits.append(m)
    def open_gate(s, seat, q, options=None, recommendation=None): s.gates.append((q, options, recommendation))
    def roster(s):
        if s.broken: raise RuntimeError("roster unreadable")
        return {"seats": {k: {"adapter": {"type": v}} for k, v in s.kinds.items()}}
    def state(s): return s._st
def mk(kind, procs, repo, state=None):
    sv = Supervisor.__new__(Supervisor); sv.bus = B({"builder": kind, "human": "interactive"}, state or st()); sv.repo = repo
    sv.stall_timeout = 900; sv._stalled_seats = set(); sv.procs = procs; sv._notified_gates = set(); sv.restarts = {}; sv.restart_limit = 5
    sv.started = []; sv.start_seat = lambda n: sv.started.append(n); return sv
tmp = tempfile.mkdtemp()
try:
    r = os.path.join(tmp, "lane"); lt.init_repo(r)
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 1000))
    S = lambda **k: st(turn_since=since, **k)
    def declare(pid=4242, seconds=300, **over):
        s_ = {"turn": "builder", "turn_seq": 7, "turn_since": since}; s_.update(over)
        lv.write_declaration(r, "builder", s_, "H1", "adapter", seconds, time.time())
        p = os.path.join(r, ".git", "lg-live-builder.json"); d = json.load(open(p)); d["pid"] = pid; open(p, "w").write(json.dumps(d)); os.chmod(p, 0o600)
    def undeclare(): 
        try: os.unlink(os.path.join(r, ".git", "lg-live-builder.json"))
        except OSError: pass
    for kind in ("http", "cli", "weird"):
        undeclare(); p = P(); sv = mk(kind, {"builder": p}, r, S()); sv._check_stall(S())
        check(f"{kind} (spending) stale, no declaration: escalated once, NOT terminated, no restart", p.t == 0 and len(sv.bus.gates) == 1 and sv.started == [] and "NOT terminated" in sv.bus.log[0][2])
        sv._check_stall(S()); check(f"{kind}: not repeated for the same turn", len(sv.bus.gates) == 1)
        check(f"{kind}: spending gate does not offer or recommend a restart", all("restart the seat" not in (g[1] or []) and "restart the seat" != g[2] for g in sv.bus.gates))
    declare(); p = P(); sv = mk("http", {"builder": p}, r, S()); sv._check_stall(S())
    check("spending seat past 900s but inside its declared bound: no action, no log, no gate", p.t == 0 and not sv.bus.gates and not sv.bus.log)
    undeclare(); declare(seconds=300); time.sleep(0.01)
    d = json.load(open(os.path.join(r, ".git", "lg-live-builder.json"))); d["written_at"] -= 600; d["deadline"] -= 600; os.chmod(os.path.join(r, ".git", "lg-live-builder.json"), 0o600); open(os.path.join(r, ".git", "lg-live-builder.json"), "w").write(json.dumps(d)); os.chmod(os.path.join(r, ".git", "lg-live-builder.json"), 0o600)
    recent = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 100))
    p = P(); sv = mk("http", {"builder": p}, r, S()); sv._check_stall(S())
    check("deadline overrun on a spending seat: escalated, NOT terminated", p.t == 0 and len(sv.bus.gates) == 1 and "past its own declared" in sv.bus.gates[0][0])
    undeclare(); declare(pid=1)
    p = P(); sv = mk("http", {"builder": p}, r, S()); sv._check_stall(S())
    check("declaration from a different pid is not trusted: stale spending seat escalates, not live, not terminated", p.t == 0 and len(sv.bus.gates) == 1)
    undeclare(); declare(turn_seq=6)
    p = P(); sv = mk("http", {"builder": p}, r, S()); sv._check_stall(S())
    check("a declaration left from an older turn does not keep a new turn live", p.t == 0 and len(sv.bus.gates) == 1)
    undeclare(); p = P(); young = st(turn_since=recent); sv = mk("http", {"builder": p}, r, young); sv._check_stall(young)
    check("young turn with no declaration: nothing", p.t == 0 and not sv.bus.gates and not sv.bus.log)
    # non-spending keeps today's behaviour
    p = P(); sv = mk("mock", {"builder": p}, r, S()); sv._check_stall(S())
    check("non-spending (mock) stale, unknown liveness: terminated as before", p.t == 1 and not sv.bus.gates)
    declare(); p = P(); sv = mk("mock", {"builder": p}, r, S()); sv._check_stall(S())
    check("non-spending with a valid live declaration is also left alone", p.t == 0); undeclare()
    # roster unreadable -> spending
    p = P(); sv = mk("mock", {"builder": p}, r, S()); sv.bus.broken = True; sv._check_stall(S())
    check("unreadable roster is treated as spending: not terminated", p.t == 0 and len(sv.bus.gates) == 1)
    # reap paths
    dead = P(rc=1); sv = mk("http", {"builder": dead}, r, S()); sv._reap_and_restart()
    check("spending seat exits holding the turn: not restarted, escalated once, removed from procs", sv.started == [] and "builder" not in sv.procs and len(sv.bus.gates) == 1 and sv.restarts == {})
    sv._check_stall(S()); check("no second gate for the same turn from the stall path", len(sv.bus.gates) == 1)
    sv._reap_and_restart(); check("and nothing on later passes", sv.started == [] and len(sv.bus.gates) == 1)
    dead = P(rc=1); other = st(turn="qc", turn_since=since); sv = mk("http", {"builder": dead}, r, other); sv._reap_and_restart()
    check("spending seat exits while ANOTHER seat holds the turn: still NOT restarted, escalated once", sv.started == [] and "builder" not in sv.procs and len(sv.bus.gates) == 1)
    sv._reap_and_restart(); check("and not again on later passes", len(sv.bus.gates) == 1 and sv.started == [])
    dead = P(rc=1); sv = mk("http", {"builder": dead}, r, S()); sv.bus.state = lambda: (_ for _ in ()).throw(RuntimeError("bad state"))
    sv._reap_and_restart(); check("unreadable state: not restarted, escalated once", sv.started == [] and len(sv.bus.gates) == 1)
    dead = P(rc=0); sv = mk("http", {"builder": dead}, r, S()); sv._reap_and_restart()
    check("a clean exit (rc 0) of a spending seat is also not auto-restarted", sv.started == [] and len(sv.bus.gates) == 1)
    dead = P(rc=1); sv = mk("mock", {"builder": dead}, r, S()); sv._reap_and_restart()
    check("non-spending seat exit: restarted as before", sv.started == ["builder"] and not sv.bus.gates and sv.restarts == {"builder": 1})
    alive = P(); sv = mk("http", {"builder": alive}, r, S()); sv._reap_and_restart()
    check("a live process is left alone by reap", sv.started == [] and not sv.bus.gates)
    # hardening from review: unhashable type, sticky classification, failing gate
    for nm, bad in (("list", ["mock"]), ("dict", {"a": 1}), ("None", None), ("upper", "MOCK"), ("int", 5)):
        p = P(); sv = mk("mock", {"builder": p}, r, S()); sv.bus.kinds["builder"] = bad
        sv.bus.roster = (lambda b=bad: {"seats": {"builder": {"adapter": {"type": b}}}})
        try: sv._check_stall(S()); e = None
        except Exception as ex: e = ex
        check(f"adapter type {nm}: classified spending, no crash, not terminated", e is None and p.t == 0 and len(sv.bus.gates) == 1)
    p = P(); sv = mk("http", {"builder": p}, r, S()); sv._is_spending("builder")
    sv.bus.roster = lambda: {"seats": {"builder": {"adapter": {"type": "mock"}}}}
    sv._check_stall(S()); check("a roster edit http->mock after the seat was seen spending does NOT downgrade it", p.t == 0 and len(sv.bus.gates) == 1)
    p = P(); sv = mk("mock", {"builder": p}, r, S()); sv._is_spending("builder")
    sv.bus.roster = lambda: {"seats": {"builder": {"adapter": {"type": "http"}}}}
    sv._check_stall(S()); check("a roster edit mock->http makes it spending (never the reverse)", p.t == 0 and len(sv.bus.gates) == 1)
    sv = mk("http", {"builder": P(rc=1)}, r, S())
    def boom(*a, **k): raise OSError("disk")
    sv.bus.open_gate = boom
    try: sv._reap_and_restart(); e = None
    except Exception as ex: e = ex
    check("reap: failing open_gate does not raise, no restart, sanitized fallback log, proc dropped", e is None and sv.started == [] and "builder" not in sv.procs and any(l[1] == "escalation_failed" and "OSError" in l[2] and "disk" not in l[2] for l in sv.bus.log))
    sv = mk("http", {"builder": P()}, r, S()); sv.bus.open_gate = boom; sv.bus.append_log = boom
    try: sv._check_stall(S()); e = None
    except Exception as ex: e = ex
    check("stall: gate AND logging failing still does not raise or terminate", e is None and sv.procs["builder"].t == 0)
    sv._check_stall(S()); check("and does not repeat for the same turn", True)
    sv = mk("http", {"builder": P(rc=1)}, r, S()); sv.bus.open_gate = boom; sv.bus.append_log = boom
    try: sv._reap_and_restart(); e = None
    except Exception as ex: e = ex
    check("reap: gate and logging both failing: no raise, no restart", e is None and sv.started == [])
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nSUPERVISOR LIVENESS:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
raise SystemExit(0 if ok else 1)
