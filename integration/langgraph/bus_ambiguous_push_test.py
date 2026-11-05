"""Offline: bus push whose outcome is ambiguous. Disposable local bare
remote only; no network, provider or account. A push that errors may still
have landed. When the remote cannot be read, absence is NOT proven, so the
bus must keep the local commit and stop (BusPushUnknown): no reset, no
retry, no repeated external effect. Retry stays only for a provable failure."""
import os, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import launcher.bus as busmod  # noqa: E402
from launcher.bus import Bus, BusError  # noqa: E402

ok = True
def check(name, cond):
    global ok
    ok = ok and bool(cond)
    print(("PASS  " if cond else "FAIL  ") + name, flush=True)

def sh(*a, cwd=None):
    return subprocess.run(a, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()

def lanes(tmp, name):
    remote = os.path.join(tmp, name + ".git"); repo = os.path.join(tmp, name)
    sh("git", "init", "-q", "--bare", "-b", "team-work", remote)
    sh("git", "clone", "-q", remote, repo)
    for k, v in (("user.name", "t"), ("user.email", "t@example.invalid")):
        sh("git", "-C", repo, "config", k, v)
    sh("git", "-C", repo, "checkout", "-q", "-b", "team-work")
    open(os.path.join(repo, "base.txt"), "w").write("base\n")
    sh("git", "-C", repo, "add", "-A"); sh("git", "-C", repo, "commit", "-qm", "base")
    sh("git", "-C", repo, "push", "-q", "origin", "team-work")
    return remote, repo

def remote_head(remote): return sh("git", "-C", remote, "rev-parse", "team-work")
def local_head(repo): return sh("git", "-C", repo, "rev-parse", "HEAD")

def run(tmp, name, method, push_mode, blind):
    """push_mode: 'lands_then_errors' | 'rejected_then_ok'.
    blind: None | 'ls-remote' | 'fetch' (that git call fails)."""
    remote, repo = lanes(tmp, name)
    bus = Bus(repo, branch="team-work", retries=3)
    calls = {"mut": 0, "push": 0}
    real_push = bus.push
    def push():
        calls["push"] += 1
        if push_mode == "lands_then_errors":
            real_push()
            raise BusError("simulated lost ack after the push landed")
        if calls["push"] == 1:
            raise BusError("simulated rejected push (nothing landed)")
        real_push()
    bus.push = push
    real_git = busmod._git
    def blind_git(r, *a, check=True):
        if blind and a and a[0] == blind and calls["push"] >= 1:
            p = subprocess.CompletedProcess(["git", *a], 1, "", "simulated unreachable")
            if check: raise BusError("git " + " ".join(a) + " failed: unreachable")
            return p
        return real_git(r, *a, check=check)
    busmod._git = blind_git
    def mutate():
        calls["mut"] += 1
        open(os.path.join(repo, "eff.txt"), "a").write("effect\n")
    err = None
    try:
        if method == "transact":
            bus.transact("msg", mutate)
        else:
            bus.transact_paths("msg", ["eff.txt"], mutate)
    except BaseException as e:  # noqa: BLE001
        err = e
    finally:
        busmod._git = real_git
    return err, calls, remote, repo

tmp = tempfile.mkdtemp(prefix="busamb-")
try:
    for method in ("transact", "transact_paths"):
        for blind in ("ls-remote", "fetch"):
            tag = f"{method}/landed-then-error/{blind}-fails"
            # fetch only matters when the remote tip differs from our head:
            # advance the remote with another writer so ls-remote sha != head.
            err, c, remote, repo = run(tmp, f"{method}-{blind}", method, "lands_then_errors", blind)
            if blind == "fetch":
                pass  # head==remote sha is provable landed without fetch (see below)
                check(f"{tag}: remote already has our head, provably landed, no retry",
                      err is None and c["mut"] == 1 and local_head(repo) == remote_head(remote))
            else:
                check(f"{tag}: raises BusPushUnknown", isinstance(err, busmod.BusPushUnknown))
                check(f"{tag}: local commit retained (not reset)",
                      sh("git", "-C", repo, "log", "-1", "--format=%s") == "msg")
                check(f"{tag}: effect ran exactly once, no retry", c["mut"] == 1 and c["push"] == 1)
                check(f"{tag}: the commit really is on the remote", local_head(repo) == remote_head(remote))
        # readable remote, landed: success, one effect
        err, c, remote, repo = run(tmp, f"{method}-ok", method, "lands_then_errors", None)
        check(f"{method}/landed-then-error/remote readable: kept, one effect, no error",
              err is None and c["mut"] == 1 and local_head(repo) == remote_head(remote))
        # provable failure: retry unchanged
        err, c, remote, repo = run(tmp, f"{method}-rej", method, "rejected_then_ok", None)
        check(f"{method}/provable rejection: retried and landed (retry unchanged)",
              err is None and c["mut"] == 2 and c["push"] == 2 and local_head(repo) == remote_head(remote))
        # rejected and remote unreadable: absence unproven -> unknown, no retry
        err, c, remote, repo = run(tmp, f"{method}-rejblind", method, "rejected_then_ok", "ls-remote")
        check(f"{method}/rejected but remote unreadable: unknown, no reset, no retry",
              isinstance(err, busmod.BusPushUnknown) and c["mut"] == 1 and c["push"] == 1
              and sh("git", "-C", repo, "log", "-1", "--format=%s") == "msg")
    # remote advanced by another writer, ours landed beneath it; fetch fails
    for method in ("transact", "transact_paths"):
        remote, repo = lanes(tmp, f"{method}-adv")
        other = os.path.join(tmp, f"{method}-other")
        sh("git", "clone", "-q", remote, other)
        for k, v in (("user.name", "o"), ("user.email", "o@example.invalid")):
            sh("git", "-C", other, "config", k, v)
        bus = Bus(repo, branch="team-work"); n = {"m": 0}
        real_git = busmod._git
        def push(bus=bus, remote=remote, other=other, repo=repo):
            sh("git", "-C", repo, "push", "-q", "origin", "team-work")
            sh("git", "-C", other, "pull", "-q", "--rebase", "origin", "team-work")
            open(os.path.join(other, "o.txt"), "w").write("o\n")
            sh("git", "-C", other, "add", "-A"); sh("git", "-C", other, "commit", "-qm", "other")
            sh("git", "-C", other, "push", "-q", "origin", "team-work")
            raise BusError("simulated lost ack")
        bus.push = push
        def bg(r, *a, check=True):
            if a and a[0] == "fetch" and n["m"] >= 1:
                if check: raise BusError("fetch failed")
                return subprocess.CompletedProcess(["git", *a], 1, "", "x")
            return real_git(r, *a, check=check)
        busmod._git = bg
        def mutate(repo=repo):
            n["m"] += 1; open(os.path.join(repo, "eff.txt"), "a").write("e\n")
        try:
            try:
                (bus.transact("msg", mutate) if method == "transact"
                 else bus.transact_paths("msg", ["eff.txt"], mutate))
                err = None
            except BaseException as e:  # noqa: BLE001
                err = e
        finally:
            busmod._git = real_git
        check(f"{method}/remote moved on, fetch fails: unknown, commit kept, one effect",
              isinstance(err, busmod.BusPushUnknown) and n["m"] == 1
              and sh("git", "-C", repo, "log", "-1", "--format=%s") == "msg")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nBUS AMBIGUOUS PUSH:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
raise SystemExit(0 if ok else 1)
