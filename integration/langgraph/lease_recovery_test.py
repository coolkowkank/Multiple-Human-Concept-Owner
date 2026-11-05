"""Offline: bounded operator recovery for a successor session blocked by a
completed turn's lease. Real git lanes + real CLI; no provider, no model."""
import os as _os; _os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import json, os, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import langgraph_team as lt  # noqa: E402
from launcher.bus import Bus  # noqa: E402
from launcher.runtime import Seat, SeatError  # noqa: E402
ok = True
def check(n, c):
    global ok; ok = ok and bool(c); print(("PASS  " if c else "FAIL  ") + n, flush=True)
def git(r, *a): return subprocess.run(["git", "-C", r, *a], capture_output=True, text=True)
def cli(r, *a):
    env = dict(os.environ); env["PYTHONPATH"] = HERE + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run([sys.executable, "-m", "launcher", *a, "--repo", r, "--branch", lt.BRANCH], capture_output=True, text=True, env=env)
    return p.returncode, p.stdout + p.stderr
def give_turn_back(r):
    b = Bus(r, lt.BRANCH); st = b.state(); st["turn"] = "coordinator"; b.write_state(st)
    git(r, "add", "-A"); git(r, "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-qm", "operator: test turn back")
tmp = tempfile.mkdtemp()
try:
    r = os.path.join(tmp, "l"); lt.init_repo(r)
    check("A completes a turn and its lease persists", Seat(Bus(r, lt.BRANCH), "coordinator", instance_id="A").act_once()
          and Bus(r, lt.BRANCH).state()["leases"]["coordinator"]["holder"] == "A")
    give_turn_back(r)
    try: Seat(Bus(r, lt.BRANCH), "coordinator", instance_id="B").act_once(); refused = False
    except SeatError as e: refused = "already held by A" in str(e)
    check("successor session B is refused while A's lease is fresh (fail closed, reproduced)", refused)
    rc, out = cli(r, "lease", "coordinator"); check("lease shows the holder and does not mutate", rc == 0 and "holder=A" in out)
    h = git(r, "rev-parse", "HEAD").stdout
    rc, out = cli(r, "lease", "coordinator", "--release"); check("--release without --holder refused", rc == 1 and git(r, "rev-parse", "HEAD").stdout == h)
    rc, out = cli(r, "lease", "coordinator", "--release", "--holder", "WRONG"); check("--release with the wrong holder refused, no commit", rc == 1 and git(r, "rev-parse", "HEAD").stdout == h)
    rc, out = cli(r, "lease", "nobody", "--release", "--holder", "A"); check("--release of a non-existent lease refused", rc == 1)
    before = Bus(r, lt.BRANCH).state()
    rc, out = cli(r, "lease", "coordinator", "--release", "--holder", "A")
    after = Bus(r, lt.BRANCH).state()
    check("release with the exact holder succeeds", rc == 0 and "coordinator" not in after["leases"])
    check("release changes ONLY the leases entry (turn, seq, status, line untouched)",
          {k: v for k, v in after.items() if k != "leases"} == {k: v for k, v in before.items() if k != "leases"})
    check("one operator commit, STATE.json only, exact message",
          git(r, "diff", "--name-only", h.strip(), "HEAD").stdout.split() == [".team/STATE.json"]
          and git(r, "log", "-1", "--format=%s").stdout.startswith("operator: lease released for coordinator (holder A)"))
    check("B can now take the turn", Seat(Bus(r, lt.BRANCH), "coordinator", instance_id="B").act_once() is True
          and Bus(r, lt.BRANCH).state()["leases"]["coordinator"]["holder"] == "B")
    # stale queued response stays refused (head binding not weakened)
    from launcher.runtime import head_binding_clean
    check("a response stamped before the release is stale", head_binding_clean(r, h.strip(), {"turn": "coordinator", "turn_seq": 1}) is False)
    # dirty worktree is not swept
    open(os.path.join(r, "stray.txt"), "w").write("x"); git(r, "add", "stray.txt")
    give = cli(r, "lease", "coordinator", "--release", "--holder", "B")
    check("staged residue blocks the release (refused, not swept)", give[0] != 0 and "stray.txt" not in git(r, "show", "--name-only", "--format=", "HEAD").stdout)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nLEASE RECOVERY:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
raise SystemExit(0 if ok else 1)
