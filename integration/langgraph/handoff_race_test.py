"""Offline: the next seat must not start while the previous holder's
apply->commit window is open (shared worktree, same repo). Threads +
real git in a scratch lane, mock responses only, no provider."""
import os as _os; _os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import os, subprocess, sys, tempfile, threading, time, json
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import langgraph_team as lt  # noqa: E402
from launcher.bus import Bus  # noqa: E402
from launcher.runtime import Seat, TornStateError  # noqa: E402
ok = True
def check(n, c):
    global ok; ok = ok and bool(c); print(("PASS  " if c else "FAIL  ") + n, flush=True)
def git(r, *a): return subprocess.run(["git", "-C", r, *a], capture_output=True, text=True).stdout.strip()
tmp = tempfile.mkdtemp(); r = os.path.join(tmp, "l"); lt.init_repo(r)
b = Bus(r, lt.BRANCH); st = b.state(); st["turn"] = "reviewer"; b.write_state(st)
git(r, "add", "-A"); git(r, "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-qm", "operator: turn to reviewer")
def resp(nxt, f): return {"summary": "s", "writes": {f: "x\n"}, "verify_command": None, "handoff": nxt, "status_line": "ok"}
rev = Seat(Bus(r, lt.BRANCH), "reviewer", poll_interval=1); rev._call_adapter = lambda s: resp("qc", "review/f.md")
qc = Seat(Bus(r, lt.BRANCH), "qc", poll_interval=1); qc._call_adapter = lambda s: resp("records", "review/q.md"); qc.torn_recheck_seconds = 0
real_apply = rev._apply
def slow_apply(state, response):
    real_apply(state, response); time.sleep(2.0)   # handoff written to the worktree, commit still pending
rev._apply = slow_apply
res = {}
def run_rev(): res["rev"] = rev.act_once()
t = threading.Thread(target=run_rev); t.start()
deadline = time.time() + 20
while time.time() < deadline:
    try:
        if json.load(open(os.path.join(r, ".team/STATE.json"))).get("turn") == "qc" and "STATE.json" in git(r, "status", "--porcelain"): break
    except (ValueError, OSError): pass
    time.sleep(0.02)
check("setup: the worktree shows turn=qc while the commit is still pending", "STATE.json" in git(r, "status", "--porcelain") and t.is_alive())
t0 = time.time()
try: res["qc"] = qc.act_once(); err = None
except Exception as e: res["qc"] = None; err = e
t.join()
check("next seat waited for the previous commit instead of refusing or racing", err is None and res.get("qc") is True and time.time() - t0 > 0.5)
check("both turns landed in order, tree clean, no error rows", res.get("rev") is True and not git(r, "status", "--porcelain")
      and git(r, "log", "--format=%s", "-3").splitlines()[:2] == ["TURN: qc acting", "TURN: reviewer acting"]
      and '"kind": "error"' not in open(os.path.join(r, ".team/LOG.jsonl")).read())
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
