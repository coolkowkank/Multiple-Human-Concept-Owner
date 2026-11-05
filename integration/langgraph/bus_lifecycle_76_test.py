"""Offline end-to-end lifecycle probe for the exit-76 (push outcome unknown)
path: REAL `launcher seat --once` subprocesses, a real mock queue adapter,
real local bare remotes. The ambiguous push is real too: two push URLs, the
first accepts, the second's pre-receive hook rejects - the client sees a
failed push while the first destination has the commit. No mocking of git,
no network, no provider, no account.

Questions answered with running code, not reading:
A. handoff to the next seat: after exit 76, does the kept commit move the
   turn, and do later supervisor polls write, push, restart or replay
   anything for the removed seat?
B. self-handoff (turn STAYS with the removed seat): same questions, plus
   what an operator relaunch of that seat does (lease claim is in the kept
   commit).
"""
import json, os, shutil, subprocess, sys, tempfile
os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import langgraph_team as lt  # noqa: E402
from launcher.bus import Bus, LOG  # noqa: E402
from launcher.supervisor import Supervisor  # noqa: E402

ok = True
def check(name, cond):
    global ok
    ok = ok and bool(cond)
    print(("PASS  " if cond else "FAIL  ") + name, flush=True)

def git(repo, *a, check=True):
    p = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise SystemExit(f"git {' '.join(a)} failed: {p.stderr}")
    return p

def head(repo): return git(repo, "rev-parse", "HEAD").stdout.strip()
def tip(remote): return git(remote, "rev-parse", "team-work").stdout.strip()

def bare(path, reject=False):
    subprocess.run(["git", "init", "-q", "--bare", "-b", "team-work", path], check=True)
    if reject:
        hook = os.path.join(path, "hooks", "pre-receive")
        open(hook, "w").write("#!/bin/sh\necho simulated rejection >&2\nexit 1\n")
        os.chmod(hook, 0o755)
    return path

def respond(repo, seat, resp):
    f = os.path.join(tempfile.gettempdir(), f"resp76-{os.getpid()}.json")
    json.dump(resp, open(f, "w"))
    env = dict(os.environ); env["PYTHONPATH"] = HERE + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run([sys.executable, "-m", "launcher", "respond", seat, "--file", f,
                        "--repo", repo, "--branch", lt.BRANCH], capture_output=True, text=True, env=env)
    os.unlink(f)
    if p.returncode != 0:
        raise SystemExit("respond failed: " + p.stdout + p.stderr)

def seat_once(repo, seat):
    env = dict(os.environ); env["PYTHONPATH"] = HERE + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run([sys.executable, "-m", "launcher", "seat", seat, "--once",
                           "--repo", repo, "--branch", lt.BRANCH],
                          capture_output=True, text=True, env=env, timeout=120)

def lane(tmp, name):
    r = os.path.join(tmp, name); db = os.path.join(tmp, name + ".sqlite")
    lt.init_repo(r, queue_seats=("builder",))
    lt.run_graph(r, db, stop_after=1, thread_id=name)
    assert Bus(r, lt.BRANCH).state()["turn"] == "builder"
    return r

APP = "def add(a, b):\n    return a + b\n"
TEST = "from src.app import add\nassert add(2, 3) == 5\nprint('ok')\n"

def scenario(tmp, name, handoff):
    """Run one seat turn with a mixed-destination push. Returns dict."""
    r = lane(tmp, name)
    resp = {"summary": f"{name} turn", "writes": {"src/app.py": APP, "tests/test_app.py": TEST},
            "verify_command": "python3 tests/test_app.py", "handoff": handoff,
            "status_line": "built"}
    respond(r, "builder", resp)
    acc = bare(os.path.join(tmp, name + "-acc.git"))
    rej = bare(os.path.join(tmp, name + "-rej.git"), reject=True)
    git(r, "remote", "add", "origin", acc)
    git(r, "push", "-q", "origin", lt.BRANCH)
    git(r, "config", "--add", "remote.origin.pushurl", acc)
    git(r, "config", "--add", "remote.origin.pushurl", rej)
    before = head(r)
    proc = seat_once(r, "builder")
    return dict(repo=r, acc=acc, rej=rej, before=before, proc=proc)

def polls(repo, removed_seat, bus_push_counter):
    """Reap a 76 exit, then run later stall polls on the real repo.
    Returns (started, gates_after_first_poll, gates_after_second_poll)."""
    bus = Bus(repo, lt.BRANCH)
    real_push = bus.push
    def counted():
        bus_push_counter[0] += 1
        return real_push()
    bus.push = counted
    sup = object.__new__(Supervisor)
    sup.bus = bus
    sup.repo = repo
    sup.stall_timeout = 5
    sup.poll = 1
    sup.restarts = {}
    sup._stalled_seats = set()
    sup._torn_blocked = frozenset()
    class P:
        returncode = 76
        def poll(self):
            return 76
    sup.procs = {removed_seat: P()}
    started = []
    sup.start_seat = lambda n: started.append(n)
    sup._reap_and_restart()
    state = bus.state()
    future = __import__("time").time() + 3600
    sup._check_stall(state, now=future)
    g1 = len(bus.pending_gates())
    sup._check_stall(bus.state(), now=future + 10)
    g2 = len(bus.pending_gates())
    return started, g1, g2

tmp = tempfile.mkdtemp()
try:
    # ---- A: handoff to the next seat -------------------------------------
    s = scenario(tmp, "a", "reviewer")
    r, proc = s["repo"], s["proc"]
    check("A: seat exits 76 (typed code, sanitized line)", proc.returncode == 76
          and "STOPPED (push_outcome_unknown)" in proc.stderr)
    st = Bus(r, lt.BRANCH).state()
    check("A: kept commit moved the turn to the next seat", st["turn"] == "reviewer")
    check("A: no reset (HEAD~1 is the pre-run head)", git(r, "rev-parse", "HEAD~1").stdout.strip() == s["before"])
    check("A: queue consumed inside the kept commit",
          open(os.path.join(r, ".team", "queues", "builder.jsonl")).read().strip() == "")
    check("A: lease claim is inside the kept commit", st["leases"].get("builder") is not None)
    check("A: first destination has the commit, second does not",
          tip(s["acc"]) == head(r) and git(s["rej"], "rev-parse", "--verify", "-q", "team-work", check=False).returncode != 0)
    acc_tip, rej_has = tip(s["acc"]), git(s["rej"], "rev-parse", "--verify", "-q", "team-work", check=False).returncode
    pushes = [0]
    started, g1, g2 = polls(r, "builder", pushes)
    check("A: supervisor removed the 76 seat, never restarted it", started == [])
    check("A: future stall polls did NOT push (escalation stayed local)", pushes[0] == 0 and tip(s["acc"]) == acc_tip)
    check("A: the kept commit was not carried anywhere new", git(s["rej"], "rev-parse", "--verify", "-q", "team-work", check=False).returncode == rej_has)
    check("A: stall escalation fires once (latch), then stops", g1 >= 1 and g2 == g1)

    # ---- B: self-handoff, the turn stays with the removed seat ------------
    s = scenario(tmp, "b", "builder")
    r, proc = s["repo"], s["proc"]
    check("B: seat exits 76 on self-handoff too", proc.returncode == 76)
    st = Bus(r, lt.BRANCH).state()
    check("B: the turn STAYS with the removed seat (the exception case)", st["turn"] == "builder")
    acc_tip = tip(s["acc"])
    pushes = [0]
    started, g1, g2 = polls(r, "builder", pushes)
    check("B: removed seat never restarted even though it still holds the turn", started == [])
    check("B: stall polls wrote no push and carried nothing (gate is local)", pushes[0] == 0 and tip(s["acc"]) == acc_tip)
    check("B: stall escalation fires once (latch), then stops", g1 >= 1 and g2 == g1)
    head_before_relaunch = head(r)
    proc2 = seat_once(r, "builder")
    check("B: operator relaunch from the same clone stops on the consumed queue "
          "(no response to apply, no replay)",
          proc2.returncode != 0 and "response queue empty" in (proc2.stdout + proc2.stderr))
    check("B: relaunch made no turn commit and pushed nothing new",
          tip(s["acc"]) == acc_tip and git(s["rej"], "rev-parse", "--verify", "-q", "team-work", check=False).returncode != 0
          and git(r, "diff", "--name-only", head_before_relaunch, "HEAD").stdout.split() in ([LOG], []))
    check("B: the applied effect is unchanged (no re-apply)",
          open(os.path.join(r, "src", "app.py")).read() == APP)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nBUS LIFECYCLE 76:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
raise SystemExit(0 if ok else 1)
