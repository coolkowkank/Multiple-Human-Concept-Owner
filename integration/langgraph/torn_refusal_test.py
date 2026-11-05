"""Offline, real processes in scratch lanes (mock adapter, no provider, no
ledger, no project lease): the typed torn-state refusal. No LOG growth, no
restart loop, no bus write by the supervisor; other exits are unaffected."""
import os as _os; _os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import hashlib, json, os, signal, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import langgraph_team as lt  # noqa: E402
from launcher.runtime import EXIT_TORN_STATE  # noqa: E402
ok = True
def check(n, c):
    global ok; ok = ok and bool(c); print(("PASS  " if c else "FAIL  ") + n, flush=True)
def git(r, *a): return subprocess.run(["git", "-C", r, *a], capture_output=True, text=True).stdout
PROCS = []
def popen(args, **kw):
    p = subprocess.Popen(args, start_new_session=True, **kw); PROCS.append(p); return p
def env():
    e = dict(os.environ); e["PYTHONPATH"] = HERE + os.pathsep + e.get("PYTHONPATH", ""); return e
def run(args, timeout=60):
    p = popen([sys.executable, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env())
    try: o, e = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL); p.communicate(); raise
    return p.returncode, o, e
def snap(r):
    h = {}
    for rel in (".team/STATE.json", ".team/LOG.jsonl", ".team/gates/PENDING.jsonl"):
        h[rel] = hashlib.sha256(open(os.path.join(r, rel), "rb").read()).hexdigest()
    return h, git(r, "status", "--porcelain"), git(r, "rev-parse", "HEAD"), git(r, "diff", "--cached", "--name-only")
tmp = tempfile.mkdtemp()
def torn_lane(n):
    r = os.path.join(tmp, n); lt.init_repo(r)
    rc, o, e = run([os.path.join(HERE, "crash_driver.py"), r, "before_commit", "crash"])
    assert rc == -9, rc
    return r
try:
    # 1. one-shot and loop seat processes: typed exit, nothing written
    r = torn_lane("a"); before = snap(r)
    rc, o, e = run(["-m", "launcher", "seat", "builder", "--once", "--repo", r, "--branch", lt.BRANCH])
    check("seat --once: exit status is the typed code", rc == EXIT_TORN_STATE and "BLOCKED (torn_control_state)" in e)
    rc, o, e = run(["-m", "launcher", "seat", "builder", "--poll", "1", "--repo", r, "--branch", lt.BRANCH])
    check("seat loop: typed exit, one sanitized stderr line, no stdout", rc == EXIT_TORN_STATE and e.count("BLOCKED") == 1 and not o)
    for _ in range(3): run(["-m", "launcher", "seat", "builder", "--poll", "1", "--repo", r, "--branch", lt.BRANCH])
    check("repeated refusals: LOG/STATE/gates bytes, status, HEAD and index identical (no dirt growth)", snap(r) == before)
    check("no 'error' row appended and no gate opened", '"kind": "error"' not in open(os.path.join(r, ".team/LOG.jsonl")).read() and not open(os.path.join(r, ".team/gates/PENDING.jsonl")).read().strip())
    # 2. supervisor over the same torn lane: no restart loop, no bus write
    sup = popen([sys.executable, "-m", "launcher", "launch", "--repo", r, "--branch", lt.BRANCH, "--poll", "1", "--max-seconds", "12"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env())
    try: so, se = sup.communicate(timeout=40)
    except subprocess.TimeoutExpired:
        os.killpg(sup.pid, signal.SIGKILL); sup.communicate(); so = se = "TIMEOUT"
    check("supervisor ends normally on its bound and prints exactly one [blocked] line for the refusing seat (other idle seats are not terminated)",
          "supervisor: timeout" in so and so.count("[blocked]") == 1 and "seat builder" in so)
    check("supervisor did not restart, commit, gate or log: tree identical", snap(r) == before and "restart" not in open(os.path.join(r, ".team/LOG.jsonl")).read())
    # 3. other exits unaffected: out-of-domain dirt is the OLD refusal, error row appended, exit != typed code
    r2 = os.path.join(tmp, "b"); lt.init_repo(r2)
    open(os.path.join(r2, "stray.txt"), "w").write("x")
    rc, o, e = run(["-m", "launcher", "seat", "coordinator", "--poll", "1", "--repo", r2, "--branch", lt.BRANCH])
    check("a different refusal keeps its old behaviour: nonzero, not the typed code, error row recorded",
          rc not in (0, EXIT_TORN_STATE) and '"kind": "error"' in open(os.path.join(r2, ".team/LOG.jsonl")).read())
    # 4. transient window: dirt that clears within the recheck does not refuse
    r3 = torn_lane("c")
    import threading
    sys.path.insert(0, HERE)
    from launcher.bus import Bus
    from launcher.runtime import Seat
    s = Seat(Bus(r3, lt.BRANCH), "builder", poll_interval=1); s.torn_recheck_seconds = 1.5
    threading.Timer(0.5, lambda: git(r3, "checkout", "--", ".team")).start()
    try: s._preflight_dirt_check(); cleared = True
    except Exception as ex: cleared = False
    check("control dirt that clears during the bounded recheck is not refused", cleared)

    # 5. same-poll ordering (fakes, no processes): a 75 exit anywhere in the poll blocks
    #    every write, whichever seat the reap loop reaches first
    from launcher.supervisor import Supervisor
    class FP:
        def __init__(s, rc): s.rc = rc; s.returncode = rc; s.pid = 1
        def poll(s): return s.rc
        def terminate(s): pass
    class FB:
        def __init__(s, kinds): s.w = []; s.kinds = kinds
        def append_log(s, *a): s.w.append(("log",) + a)
        def commit_all(s, m): s.w.append(("commit", m))
        def open_gate(s, *a, **k): s.w.append(("gate",))
        def roster(s): return {"seats": {k: {"adapter": {"type": v}} for k, v in s.kinds.items()}}
        def state(s): return {"turn": "x", "status": "running"}
    def mksup(kinds, procs):
        sv = Supervisor.__new__(Supervisor); sv.bus = FB(kinds); sv.repo = tmp
        sv.stall_timeout = 900; sv._stalled_seats = set(); sv.procs = procs; sv._notified_gates = set()
        sv.restarts = {}; sv.restart_limit = 5; sv.started = []; sv.start_seat = lambda n: sv.started.append(n)
        return sv
    import io, contextlib
    for other_kind in ("mock", "http"):
        for order in (("a", "b"), ("b", "a")):
            procs = {"a": FP(1), "b": FP(EXIT_TORN_STATE)}
            procs = {k: procs[k] for k in order}      # 'a' = the other seat (exit 1), 'b' = the seat that exited 75
            sv = mksup({"a": other_kind, "b": "mock"}, procs)
            with contextlib.redirect_stdout(io.StringIO()) as out: sv._reap_and_restart()
            check(f"other seat ({other_kind}, exit 1) + a 75 seat, order {order}: no restart, no log/commit/gate, both dropped, console only",
                  sv.started == [] and sv.bus.w == [] and not sv.procs and out.getvalue().count("[blocked]") == 2)
    sv = mksup({"a": "mock"}, {"a": FP(1)})
    with contextlib.redirect_stdout(io.StringIO()): sv._reap_and_restart()
    check("control: with no 75 exit the same mock exit still restarts normally", sv.started == ["a"] and len(sv.bus.w) == 2)
finally:
    for p in PROCS:
        if p.poll() is None:
            try: os.killpg(p.pid, signal.SIGKILL)
            except OSError: pass
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
