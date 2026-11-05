"""Offline: real subprocess SIGKILL of a seat at four points in a scratch lane
(mock adapter, no provider, no ledger, no project lease). Observes what a
restart does. Scratch lanes only; each child is its own process group and is
reaped by this test."""
import os as _os; _os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import json, os, subprocess, sys, tempfile, signal
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import langgraph_team as lt  # noqa: E402
ok = True
def check(n, c):
    global ok; ok = ok and bool(c); print(("PASS  " if c else "FAIL  ") + n, flush=True)
def git(r, *a): return subprocess.run(["git", "-C", r, *a], capture_output=True, text=True).stdout.strip()
def drive(r, point, mode, seat="coordinator"):
    p = subprocess.Popen([sys.executable, os.path.join(HERE, "crash_driver.py"), r, point, mode, seat],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try: out, _ = p.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL); p.communicate(); raise
    return p.returncode, out
def st(r): return json.load(open(os.path.join(r, ".team", "STATE.json")))
tmp = tempfile.mkdtemp()
def lane(n):
    r = os.path.join(tmp, n); lt.init_repo(r); return r
r = lane("a"); h = git(r, "rev-parse", "HEAD")
rc, _ = drive(r, "before_call", "crash")
check("kill before the adapter call: killed, tree and head untouched", rc == -9 and git(r, "rev-parse", "HEAD") == h and not git(r, "status", "--porcelain"))
rc, out = drive(r, "before_call", "run"); check("restart takes the turn cleanly", "acted=True" in out and st(r)["turn"] == "builder")
r = lane("b"); h = git(r, "rev-parse", "HEAD")
rc, _ = drive(r, "before_commit", "crash")
check("kill after apply, before commit: head unmoved, bus state uncommitted in the tree",
      rc == -9 and git(r, "rev-parse", "HEAD") == h and " M .team/STATE.json" in git(r, "status", "--porcelain").splitlines())
dirty = git(r, "status", "--porcelain")
rc, out = drive(r, "before_commit", "run", "builder")
check("the next seat REFUSES to start on uncommitted bus state, before any adapter call",
      "uncommitted coordination state" in out and "No model call" in out)
check("refusal changes nothing: same dirt, nothing staged, head unmoved", git(r, "status", "--porcelain") == dirty and not git(r, "diff", "--cached", "--name-only") and git(r, "rev-parse", "HEAD") == h)
rc, out = drive(r, "before_commit", "run", "coordinator")
check("the killed seat restarting is not the turn holder (turn moved in the uncommitted tree): no act", "acted=False" in out)
r = lane("c")
rc, _ = drive(r, "after_commit", "crash")
check("kill after commit: turn commit landed, tree clean, handoff recorded", rc == -9 and not git(r, "status", "--porcelain") and st(r)["turn"] == "builder")
r = lane("d"); h = git(r, "rev-parse", "HEAD")
rc, _ = drive(r, "during_verify", "crash")
check("kill during verify: head unmoved, only in-domain files left, stale live declaration left by the dead pid",
      rc == -9 and git(r, "rev-parse", "HEAD") == h and os.path.exists(os.path.join(r, ".git", "lg-live-coordinator.json"))
      and all(l[3:].startswith(".team/") for l in git(r, "status", "--porcelain").splitlines()))
rc, out = drive(r, "during_verify", "run")
check("restart re-runs the turn, commits, clears the stale declaration",
      "acted=True" in out and not os.path.exists(os.path.join(r, ".git", "lg-live-coordinator.json")) and not git(r, "status", "--porcelain"))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
