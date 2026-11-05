"""Offline: push-destination semantics, exact-ref parsing, caller behavior.
Disposable local bare repos only; no network, provider or account.

Covers what the first ambiguous-push test did not:
- exact-refname parsing: a look-alike ref (refs/heads/x/team-work) is NOT
  evidence the commit landed;
- the push URL, not the fetch URL, decides where a push goes;
- with several push URLs, landed needs ALL of them, provable absence needs
  ALL read clean and lacking it, anything else is UNKNOWN;
- cli answer must NOT restore its snapshot after BusPushUnknown (the commit
  is kept; restoring would dirty the worktree against HEAD);
- the supervisor never restarts a seat that exited EXIT_PUSH_UNKNOWN.

Note: lanes get DISTINCT base content (git is content-addressed; two lanes
with identical trees and messages would share commit SHAs and fake a
"landed" result).
"""
import contextlib, io, json, os, shutil, subprocess, sys, tempfile, types
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import launcher.bus as busmod  # noqa: E402
from launcher.bus import Bus, BusError, BusPushUnknown, EXIT_PUSH_UNKNOWN  # noqa: E402
import launcher.cli as cli  # noqa: E402
from launcher.supervisor import Supervisor  # noqa: E402

ok = True
def check(name, cond):
    global ok
    ok = ok and bool(cond)
    print(("PASS  " if cond else "FAIL  ") + name, flush=True)

def sh(*a, cwd=None):
    return subprocess.run(a, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()

def bare(path):
    sh("git", "init", "-q", "--bare", "-b", "team-work", path)
    return path

def lanes(tmp, name, init=True):
    remote = bare(os.path.join(tmp, name + ".git")); repo = os.path.join(tmp, name)
    sh("git", "clone", "-q", remote, repo)
    for k, v in (("user.name", "t"), ("user.email", "t@example.invalid")):
        sh("git", "-C", repo, "config", k, v)
    sh("git", "checkout", "-q", "-b", "team-work", cwd=repo)
    if init:
        open(os.path.join(repo, "base.txt"), "w").write("base %s\n" % name)
        sh("git", "add", "-A", cwd=repo); sh("git", "commit", "-qm", "base", cwd=repo)
        sh("git", "push", "-q", "origin", "team-work", cwd=repo)
    return remote, repo

def head(repo): return sh("git", "-C", repo, "rev-parse", "HEAD")

tmp = tempfile.mkdtemp(prefix="busdest-")
try:
    # 1. exact-ref parse: decoy refs/heads/x/team-work exists, real branch
    #    provably absent -> provable absence, NOT a false "landed".
    remote, repo = lanes(tmp, "decoy")
    sh("git", "-C", remote, "update-ref", "refs/heads/x/team-work",
       sh("git", "-C", remote, "rev-parse", "team-work"))
    out = sh("git", "-C", repo, "ls-remote", "origin", "refs/heads/team-work")
    bus = Bus(repo, branch="team-work", retries=1)
    open(os.path.join(repo, "e.txt"), "w").write("x\n")
    sh("git", "add", "e.txt", cwd=repo); sh("git", "commit", "-qm", "e", cwd=repo)
    check("decoy refs/heads/x/team-work is not matched by the exact query",
          "x/team-work" not in out)
    check("decoy present, branch absent: provably absent (False)",
          bus._landed_at("origin", head(repo), "refs/heads/team-work") is False)

    # 2. the push URL decides where a push goes, not the fetch URL.
    r2 = bare(os.path.join(tmp, "pushdest.git"))
    remote, repo = lanes(tmp, "pushurl")
    sh("git", "-C", repo, "config", "remote.origin.pushurl", r2)
    bus = Bus(repo, branch="team-work", retries=3)
    calls = {"mut": 0}
    real_push = bus.push
    def push():
        real_push()
        raise BusError("simulated lost ack after the push landed")
    bus.push = push
    def mut():
        calls["mut"] += 1
        open(os.path.join(repo, "e.txt"), "a").write("x\n")
    try:
        bus.transact_paths("m", ["e.txt"], mut)
        err = None
    except BaseException as e:  # noqa: BLE001
        err = e
    check("pushurl set: landed is judged at the PUSH url (sha equality, no fetch)",
          err is None and calls["mut"] == 1
          and sh("git", "-C", r2, "rev-parse", "team-work") == head(repo))
    check("the fetch URL never received it (push went to pushurl)",
          sh("git", "-C", remote, "rev-parse", "team-work") != head(repo))

    # 2b. pushurl provably lacks it -> False -> retry stays allowed.
    r3 = bare(os.path.join(tmp, "emptydest.git"))
    remote, repo = lanes(tmp, "pushurl3")
    sh("git", "-C", repo, "config", "remote.origin.pushurl", r3)
    bus = Bus(repo, branch="team-work", retries=1)
    open(os.path.join(repo, "e.txt"), "w").write("x\n")
    sh("git", "add", "e.txt", cwd=repo); sh("git", "commit", "-qm", "e", cwd=repo)
    check("pushurl provably lacks it (empty): provable absence even though the fetch url has history",
          bus._confirm_landed() is False)

    # 3. two push URLs disagree -> unknown, no reset, no retry.
    r4, r5 = bare(os.path.join(tmp, "dest4.git")), bare(os.path.join(tmp, "dest5.git"))
    remote, repo = lanes(tmp, "multi")
    sh("git", "-C", repo, "config", "--add", "remote.origin.pushurl", r4)
    sh("git", "-C", repo, "config", "--add", "remote.origin.pushurl", r5)
    calls = {"mut": 0}
    bus = Bus(repo, branch="team-work", retries=3)
    def push():
        sh("git", "-C", repo, "push", "-q", r4, "team-work")
        raise BusError("second destination unreachable")
    bus.push = push
    def mut():
        calls["mut"] += 1
        open(os.path.join(repo, "e.txt"), "a").write("x\n")
    try:
        bus.transact_paths("m", ["e.txt"], mut)
        err = None
    except BaseException as e:  # noqa: BLE001
        err = e
    check("two push URLs disagree (landed at one, absent at the other): UNKNOWN",
          isinstance(err, BusPushUnknown))
    check("multi-dest unknown: commit kept, one effect, no retry",
          calls["mut"] == 1
          and sh("git", "-C", repo, "log", "-1", "--format=%s") == "m")

    # 3b. all destinations read clean and lacking -> provable absence -> retry.
    r6, r7 = bare(os.path.join(tmp, "dest6.git")), bare(os.path.join(tmp, "dest7.git"))
    remote, repo = lanes(tmp, "multi2")
    sh("git", "-C", repo, "config", "--add", "remote.origin.pushurl", r6)
    sh("git", "-C", repo, "config", "--add", "remote.origin.pushurl", r7)
    n = {"m": 0, "p": 0}
    bus = Bus(repo, branch="team-work", retries=3)
    def push2():
        n["p"] += 1
        if n["p"] == 1:
            raise BusError("rejected by both")
        sh("git", "-C", repo, "push", "-q", r6, "team-work")
        sh("git", "-C", repo, "push", "-q", r7, "team-work")
    bus.push = push2
    def mut2():
        n["m"] += 1
        open(os.path.join(repo, "e.txt"), "a").write("x\n")
    bus.transact_paths("m", ["e.txt"], mut2)
    check("all destinations provably lack it: retry unchanged (2 effects, landed at both)",
          n["m"] == 2
          and sh("git", "-C", r6, "rev-parse", "team-work") == head(repo)
          and sh("git", "-C", r7, "rev-parse", "team-work") == head(repo))

    # 4. cli answer: BusPushUnknown must NOT restore the ANSWERS snapshot.
    remote, repo = lanes(tmp, "answer", init=False)
    bus = Bus(repo, branch="team-work")
    bus.init_layout()
    sh("git", "-C", repo, "push", "-q", "origin", "team-work")
    bus.transact_paths("operator: gate asked", [".team/gates/PENDING.jsonl"],
                       lambda: bus.open_gate("reviewer", "ship?"))
    real_git = busmod._git
    def bg(r, *a, check=True):
        if a and a[0] in ("push", "ls-remote"):
            if check:
                raise BusError("git " + a[0] + " failed: simulated")
            return subprocess.CompletedProcess(["git", *a], 1, "", "simulated")
        return real_git(r, *a, check=check)
    busmod._git = bg
    args = types.SimpleNamespace(repo=repo, branch="team-work",
                                 gate_id="g1", answer="yes")
    errbuf = io.StringIO()
    try:
        with contextlib.redirect_stderr(errbuf):
            cli.cmd_answer(args)
        raised = None
    except BaseException as e:  # noqa: BLE001
        raised = e
    finally:
        busmod._git = real_git
    disk = open(os.path.join(repo, ".team/gates/ANSWERS.jsonl")).read()
    head_content = sh("git", "-C", repo, "show", "HEAD:.team/gates/ANSWERS.jsonl")
    check("cli answer raises after BusPushUnknown", isinstance(raised, BusPushUnknown))
    check("cli answer: worktree answer file matches the KEPT commit (no snapshot restore)",
          disk.rstrip("\n") == head_content.rstrip("\n") and "yes" in disk)
    check("cli answer: stderr says committed locally / unknown / do not repeat",
          "committed locally" in errbuf.getvalue() and "unknown" in errbuf.getvalue())

    # 5. supervisor: EXIT_PUSH_UNKNOWN is never auto-restarted, no bus write.
    class P:
        returncode = EXIT_PUSH_UNKNOWN
        def poll(self):
            return EXIT_PUSH_UNKNOWN
    sup = object.__new__(Supervisor)
    sup.procs = {"builder": P()}
    sup.restarts = {}
    sup._torn_blocked = frozenset()
    sup._stalled_seats = set()
    class BoomBus:
        def __getattr__(self, k):
            raise AssertionError("bus touched: " + k)
    sup.bus = BoomBus()
    started = []
    sup.start_seat = lambda n: started.append(n)
    sup._reap_and_restart()
    check("supervisor: exit 76 seat removed and NOT restarted, no bus write",
          "builder" not in sup.procs and not started)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nBUS PUSH DESTINATIONS:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
raise SystemExit(0 if ok else 1)
