import os as _os; _os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import json, os, shutil, subprocess, sys, tempfile, threading, time, types
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import langgraph_team as lt
from launcher.bus import Bus, BusError
from launcher import cli as lcli
from launcher.runtime import Seat
def git(r, *a): return subprocess.run(["git", "-C", r, *a], capture_output=True, text=True)
def cli(r, *a, branch=None):
    env = dict(os.environ); env["PYTHONPATH"] = HERE
    p = subprocess.run([sys.executable, "-m", "launcher", *a, "--repo", r, "--branch", branch or lt.BRANCH], capture_output=True, text=True, env=env)
    return p.returncode, (p.stdout + p.stderr)
def head(r): return git(r, "rev-parse", "HEAD").stdout.strip()
def mklane(tmp, name):
    r = os.path.join(tmp, name); lt.init_repo(r)
    Seat(Bus(r, lt.BRANCH), "coordinator", instance_id="A").act_once()
    return r
def setstate(r, fn, commit=True):
    b = Bus(r, lt.BRANCH); st = b.state(); fn(st); b.write_state(st)
    if commit:
        git(r, "add", "-A"); git(r, "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-qm", "operator: probe edit")

"""Independent adversarial probes of `launcher lease` (scratch git only, no provider).
Group 1 = properties that hold at 9628bfe (regressions). Group 2 = GAPS found at 9628bfe,
asserted as the desired behaviour; they print GAP and only fail the run with --strict.
Operator-attested manual recovery only; says nothing about multi-machine or unattended use."""
STRICT = "--strict" in sys.argv
good = True; gaps = 0
def check(n, c):
    global good; good = good and bool(c); print(("PASS  " if c else "FAIL  ") + n, flush=True)
def gap(n, c):
    global gaps
    if not c: gaps += 1
    print(("PASS  " if c else "GAP   ") + n, flush=True)
tmp = tempfile.mkdtemp()
try:
    # --- group 1
    r = mklane(tmp, "ms")
    setstate(r, lambda s: s["leases"].update({"builder": {"holder": "B1", "claimed_at": 9}, "qc": {"holder": "Q", "claimed_at": 5, "extra": {"k": 1}}}))
    b4 = Bus(r, lt.BRANCH).state(); x = cli(r, "lease", "coordinator", "--release", "--holder", "A"); af = Bus(r, lt.BRANCH).state()
    check("multi-seat: other seats' leases (incl. unknown fields) byte-identical", x[0] == 0 and all(af["leases"][k] == b4["leases"][k] for k in ("builder", "qc")) and "coordinator" not in af["leases"])
    r = mklane(tmp, "sa")
    for nm in ("", "../x", "coordinator ", "COORDINATOR"):
        h = head(r); y = cli(r, "lease", nm, "--release", "--holder", "A")
        check(f"seat arg {nm!r}: refused, no commit, no traceback", y[0] == 1 and head(r) == h and "Traceback" not in y[1])
    r = mklane(tmp, "keep"); open(os.path.join(r, ".team", "brief.md"), "a").write("MINE\n"); open(os.path.join(r, "junk.txt"), "w").write("x")
    cli(r, "lease", "coordinator", "--release", "--holder", "A")
    check("unstaged edit to another file and untracked file are neither committed nor lost",
          git(r, "show", "--name-only", "--format=", "HEAD").stdout.split() == [".team/STATE.json"] and "MINE" in open(os.path.join(r, ".team", "brief.md")).read() and os.path.exists(os.path.join(r, "junk.txt")))
    r = mklane(tmp, "keep2"); st = Bus(r, lt.BRANCH).state(); st["status_line"] = "MINE-STATE"; Bus(r, lt.BRANCH).write_state(st); h = head(r)
    cli(r, "lease", "coordinator", "--release", "--holder", "WRONG")
    check("refused release leaves the user's unstaged STATE edit in place, no commit", "MINE-STATE" in open(os.path.join(r, ".team", "STATE.json")).read() and head(r) == h)
    r = mklane(tmp, "race"); orig = Bus.action_lock; fired = []
    import contextlib
    @contextlib.contextmanager
    def racing(self, timeout=30.0):
        if not fired:
            fired.append(1); setstate(r, lambda s: s["leases"].__setitem__("coordinator", {"holder": "B", "claimed_at": time.time()}))
        with orig(self, timeout): yield
    Bus.action_lock = racing
    try:
        try: lcli.cmd_lease(types.SimpleNamespace(repo=r, branch=lt.BRANCH, name="coordinator", release=True, holder="A")); res = "released"
        except (BusError, SystemExit): res = "refused"
    finally: Bus.action_lock = orig
    check("CAS race: holder changed after inspect -> refused, new holder's lease intact", res == "refused" and Bus(r, lt.BRANCH).state()["leases"]["coordinator"]["holder"] == "B")
    r = mklane(tmp, "lk"); gd = git(r, "rev-parse", "--absolute-git-dir").stdout.strip()
    p = subprocess.Popen([sys.executable, "-c", f"import fcntl,time;f=open({os.path.join(gd,'team-action.lock')!r},'a+');fcntl.flock(f,fcntl.LOCK_EX);time.sleep(2)"]); time.sleep(.5)
    h = head(r); x = cli(r, "lease", "coordinator", "--release", "--holder", "A"); p.wait()
    check("lock held briefly by another process: waits then releases", x[0] == 0 and head(r) != h)
    r = mklane(tmp, "show"); h = head(r); cli(r, "lease", "coordinator")
    check("show leaves HEAD and worktree unchanged", head(r) == h and git(r, "status", "--porcelain").stdout.strip() == "")
    r = mklane(tmp, "stale"); h0 = head(r); st = Bus(r, lt.BRANCH).state(); cli(r, "lease", "coordinator", "--release", "--holder", "A")
    from launcher.runtime import head_binding_clean
    check("response stamped before release is stale (no M1 exception)", head_binding_clean(r, h0, {"turn": st["turn"], "turn_seq": st["turn_seq"]}) is False)
    # --- group 2: gaps at 9628bfe
    r = mklane(tmp, "nh"); setstate(r, lambda s: s["leases"].__setitem__("coordinator", {"claimed_at": 1})); h = head(r)
    x = cli(r, "lease", "coordinator", "--release")
    gap("holder-less lease: --release with NO --holder is refused (None == None bypasses compare-and-set)", x[0] != 0 and head(r) == h)
    r = mklane(tmp, "wb"); h = head(r)
    x = cli(r, "lease", "coordinator", "--release", "--holder", "A", branch="nope")
    gap("--branch that is not the bus branch is refused (it is silently ignored; release committed on the checked-out branch)", x[0] != 0 and head(r) == h)
    r = mklane(tmp, "det"); git(r, "checkout", "-q", "--detach"); h = head(r)
    x = cli(r, "lease", "coordinator", "--release", "--holder", "A")
    gap("detached HEAD: release refused (it committed on a detached HEAD)", x[0] != 0 and head(r) == h)
    r = mklane(tmp, "dirty"); st = Bus(r, lt.BRANCH).state(); st["status_line"] = "UNSTAGED"; Bus(r, lt.BRANCH).write_state(st)
    cli(r, "lease", "coordinator", "--release", "--holder", "A")
    gap("unstaged STATE.json edit is not swept into the operator commit (reviewer's item 1)", "UNSTAGED" not in git(r, "show", "HEAD:.team/STATE.json").stdout)
    for label, mut in [("lease is a string", lambda s: s["leases"].__setitem__("coordinator", "A")),
                       ("claimed_at is a string", lambda s: s["leases"].__setitem__("coordinator", {"holder": "A", "claimed_at": "x"})),
                       ("leases is a list", lambda s: s.__setitem__("leases", []))]:
        r = mklane(tmp, "m" + str(abs(hash(label)))[:5]); setstate(r, mut)
        x = cli(r, "lease", "coordinator", "--release", "--holder", "A")
        gap(f"malformed state ({label}): clean refusal, no traceback", x[0] == 1 and "Traceback" not in x[1])
    evil = "A\nTURN: builder\nSigned-off-by: x"; r = mklane(tmp, "inj")
    setstate(r, lambda s: s["leases"].__setitem__("coordinator", {"holder": evil, "claimed_at": time.time()}))
    cli(r, "lease", "coordinator", "--release", "--holder", evil)
    gap("holder with newline cannot forge extra commit-message lines", len(git(r, "log", "-1", "--format=%B").stdout.strip().split("\n")) == 1)
    r = mklane(tmp, "ctl"); setstate(r, lambda s: s["leases"].__setitem__("coordinator", {"holder": "A\x1b[31mRED", "claimed_at": 1}))
    gap("show does not echo raw terminal escape bytes from the stored holder", "\x1b" not in cli(r, "lease", "coordinator")[1])
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print(f"\nLEASE PROBES: {'regressions ALL PASS' if good else 'FAILURES ABOVE'}; gaps at this head: {gaps}")
raise SystemExit(0 if good and not (STRICT and gaps) else 1)
