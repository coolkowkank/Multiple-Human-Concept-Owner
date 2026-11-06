"""Hard wall-clock wrapper for ONE foreground invocation (offline tool).

New labeled implementation. It is NOT a recovery of any earlier local work,
it makes no provider call itself, and it is not an execution approval.

It runs an argv (for example `python3 -m launcher seat NAME --once`) in its
own session under a hard deadline, and fails closed:

 1. Exclusive run lock (flock) taken by the wrapper and INHERITED by the
    child. A descendant that keeps the inherited fd keeps the lock after the
    wrapper dies, so a second wrapper cannot overlap it.
 2. Read-only reserve_preflight gate before spawn (planned calls or
    epoch_budgets). Anything but ok_to_plan refuses; nothing is spawned.
 3. Durable marker (atomic tmp+fsync+rename+fsync dir) written BEFORE spawn.
    Only state "clean" (or no state) allows a start. Every other state, and
    any "starting"/"running" found at the next start (wrapper itself died),
    refuses until a human runs `clear` with a reason. No auto-resume, no
    retry, no repair of the lane or the ledger.
 4. Deadline: SIGTERM to the process group, short grace, SIGKILL, then verify
    the group and every process carrying this run's id are gone.
 5. PR_SET_PDEATHSIG(SIGKILL) on the direct child: if the wrapper is killed,
    the direct child dies too. Grandchildren are covered only by the group
    kill, the inherited lock and the survivor scan, not by PDEATHSIG.
 6. After exit: a post-run ledger scan. Torn line, broken chain, halt or any
    NEW unmatched reserve leaves a non-clean state (unknown stays consumed).

CHILD CONTRACT (not universal): the child must not daemonize, double-fork
with setsid, scrub its environment, or close inherited fds on purpose. Such a
process can escape the group kill. It is still detected if it keeps the run
id in its environment (survivor scan) or the lock fd (lock), but a process
that does all of these deliberately is NOT bounded. Linux /proc only.
A process in uninterruptible sleep cannot be killed; the wrapper then reports
orphans-alive and keeps refusing.

The deadline cannot exceed MAX_DEADLINE (fits a 120 s foreground tool limit
with the kill grace and the post-run scan). Killing the client does not
cancel a provider request: a killed call stays consumed/unknown in the
ledger exactly as before.
"""
import ctypes
import fcntl
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import time
import secrets

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import reserve_preflight as rp  # noqa: E402

MAX_DEADLINE = 100          # seconds; + TERM grace + verify + scan < 120 s
TERM_GRACE = 3.0
VERIFY_WAIT = 5.0
ENV_KEY = "LG_BOUNDED_RUN_ID"
EXIT = {"clean": 0, "refused": 10, "timeout": 11, "child-failed": 12,
        "needs-review": 13, "orphans-alive": 14, "internal": 15}
CLEAN = "clean"
PR_SET_PDEATHSIG = 1


# ---------------------------------------------------------------- state dir
def _prep_dir(d):
    os.makedirs(d, mode=0o700, exist_ok=True)
    st = os.lstat(d)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise RuntimeError("state dir is a symlink or not a directory")
    if st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise RuntimeError("state dir must be owned by this user and mode 0700")


def _fsync_dir(d):
    fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_state(d, doc):
    """Atomic: tmp in the same dir, fsync file, rename, fsync dir."""
    doc = dict(doc, updated_at=time.time())
    tmp = os.path.join(d, "state.json.%d.tmp" % os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(doc, sort_keys=True))
        fh.flush()
        os.fsync(fh.fileno())
    os.rename(tmp, os.path.join(d, "state.json"))
    _fsync_dir(d)
    _history(d, doc)
    return doc


def _history(d, doc):
    fd = os.open(os.path.join(d, "history.jsonl"),
                 os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "ab") as fh:
        fh.write((json.dumps({k: doc.get(k) for k in
                  ("state", "run_id", "wrapper_pid", "child_pid", "child_pgid",
                   "argv_sha256", "deadline_s", "reason", "updated_at")},
                  sort_keys=True) + "\n").encode())
        fh.flush()
        os.fsync(fh.fileno())


def _read_state(d):
    """-> (doc|None, problem|None). Missing is fine; unreadable refuses."""
    p = os.path.join(d, "state.json")
    if not os.path.lexists(p):
        return None, None
    try:
        st = os.lstat(p)
        if not stat.S_ISREG(st.st_mode):
            return None, "state.json is not a regular file"
        doc = json.load(open(p, encoding="utf-8"))
        if not isinstance(doc, dict) or not isinstance(doc.get("state"), str):
            return None, "state.json is malformed"
        return doc, None
    except (OSError, ValueError):
        return None, "state.json is unreadable"


def _lock(d):
    fd = os.open(os.path.join(d, "lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    os.set_inheritable(fd, True)
    return fd


# --------------------------------------------------------- process scanning
def _stat_fields(pid):
    try:
        raw = open("/proc/%d/stat" % pid, "rb").read().decode("utf-8", "replace")
        rest = raw[raw.rindex(")") + 2:].split()
        return {"state": rest[0], "ppid": int(rest[1]), "pgrp": int(rest[2]),
                "sid": int(rest[3]), "start": int(rest[19])}
    except (OSError, ValueError, IndexError):
        return None


def survivors(run_id, pgid):
    """Live (non-zombie) processes in the run's group/session or carrying its
    run id in their environment. Excludes this process."""
    out = []
    needle = ("%s=%s" % (ENV_KEY, run_id)).encode() + b"\0"
    for name in os.listdir("/proc"):
        if not name.isdigit() or int(name) == os.getpid():
            continue
        pid = int(name)
        f = _stat_fields(pid)
        if f is None or f["state"] in ("Z", "X"):
            continue
        hit = bool(pgid) and (f["pgrp"] == pgid or f["sid"] == pgid)
        if not hit and run_id:
            try:
                hit = needle in open("/proc/%d/environ" % pid, "rb").read()
            except OSError:
                hit = False
        if hit:
            out.append(pid)
    return out


def _wait_gone(run_id, pgid, seconds):
    end = time.monotonic() + seconds
    while True:
        s = survivors(run_id, pgid)
        if not s or time.monotonic() >= end:
            return s
        time.sleep(0.05)


def _killpg(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _pdeathsig():
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0)
    if os.getppid() == 1:       # wrapper already gone
        os._exit(111)


# ------------------------------------------------------------------- ledger
def _unmatched(pf):
    return sum(x.get("unmatched_reserves", 0) for x in pf.get("files", []))


def _scan(planned, log_dir, cap, epoch_budgets, allow_fresh):
    return rp.preflight(planned, log_dir=log_dir, cap=cap, allow_fresh=allow_fresh,
                        epoch_budgets=epoch_budgets)


# --------------------------------------------------------------------- run
def run(state_dir, argv, deadline, *, planned=None, epoch_budgets=None,
        log_dir=None, cap=None, allow_fresh=False, env=None):
    """Returns (outcome, detail dict). Never spawns unless every gate passed."""
    def refuse(why, **kw):
        return "refused", dict(reason=why, **kw)
    if not argv or not all(isinstance(a, str) and a for a in argv):
        return refuse("empty or malformed argv")
    if not (isinstance(deadline, (int, float)) and not isinstance(deadline, bool)
            and 0 < deadline <= MAX_DEADLINE):
        return refuse("deadline must be in (0, %d] seconds" % MAX_DEADLINE)
    if planned is None and epoch_budgets is None:
        return refuse("a preflight is mandatory: give planned or epoch_budgets")
    try:
        _prep_dir(state_dir)
    except (OSError, RuntimeError) as exc:
        return refuse("state dir: %s" % exc)
    lockfd = _lock(state_dir)
    if lockfd is None:
        return refuse("run lock held: another wrapper or a surviving descendant is running")
    spawned = False
    try:
        doc, prob = _read_state(state_dir)
        if prob:
            return refuse(prob)
        if doc is not None and doc["state"] != CLEAN:
            prev = doc["state"]
            if prev in ("starting", "running"):
                _write_state(state_dir, dict(doc, state="wrapper-crashed-unknown",
                             reason="previous wrapper died while %s" % prev))
                prev = "wrapper-crashed-unknown"
            s = survivors(doc.get("run_id"), doc.get("child_pgid"))
            return refuse("previous run is %s; a human must clear it" % prev,
                          survivors=s, prev_run_id=doc.get("run_id"))
        pf = _scan(planned if planned is not None else 0, log_dir, cap,
                   epoch_budgets, allow_fresh)
        if pf["status"] != "ok_to_plan":
            return refuse("preflight %s" % pf["status"], problems=pf.get("problems"))
        base_unmatched = _unmatched(pf)
        run_id = secrets.token_hex(8)
        base = {"v": 1, "run_id": run_id, "wrapper_pid": os.getpid(),
                "wrapper_start": (_stat_fields(os.getpid()) or {}).get("start"),
                "argv_sha256": hashlib.sha256("\0".join(argv).encode()).hexdigest(),
                "deadline_s": deadline, "child_pid": None, "child_pgid": None,
                "started_at": time.time()}
        _write_state(state_dir, dict(base, state="starting"))      # BEFORE spawn
        cenv = dict(env if env is not None else os.environ)
        cenv[ENV_KEY] = run_id
        flagged = {"sig": None}
        old = {}
        for sg in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            old[sg] = signal.signal(sg, lambda n, f: flagged.__setitem__("sig", n))
        try:
            try:
                p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, env=cenv,
                                     start_new_session=True, close_fds=True,
                                     pass_fds=(lockfd,), preexec_fn=_pdeathsig)
            except OSError as exc:
                _write_state(state_dir, dict(base, state=CLEAN,
                             reason="spawn failed before any child ran: %s" % type(exc).__name__))
                return refuse("spawn failed: %s" % type(exc).__name__)
            spawned = True
            pgid = p.pid
            _write_state(state_dir, dict(base, state="running", child_pid=p.pid,
                                         child_pgid=pgid))
            end = time.monotonic() + deadline
            outcome, rc = None, None
            while True:
                if flagged["sig"] is not None:
                    outcome = "wrapper-signaled"
                    break
                left = end - time.monotonic()
                if left <= 0:
                    outcome = "deadline"
                    break
                try:
                    rc = p.wait(timeout=min(0.2, left))
                    outcome = "exited"
                    break
                except subprocess.TimeoutExpired:
                    continue
            if outcome != "exited":
                _killpg(pgid, signal.SIGTERM)
                try:
                    rc = p.wait(timeout=TERM_GRACE)
                except subprocess.TimeoutExpired:
                    pass
                _killpg(pgid, signal.SIGKILL)
                try:
                    rc = p.wait(timeout=VERIFY_WAIT)
                except subprocess.TimeoutExpired:
                    pass
            left_alive = _wait_gone(run_id, pgid, VERIFY_WAIT if outcome != "exited" else 1.0)
            first_alive = list(left_alive)
            if left_alive:                          # try once more, then give up
                _killpg(pgid, signal.SIGKILL)
                for pid in left_alive:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass
                left_alive = _wait_gone(run_id, pgid, VERIFY_WAIT)
            post = _scan(0, log_dir, cap, epoch_budgets, allow_fresh)
            post_ok = post["status"] in ("ok_to_plan", "over_cap")
            new_unmatched = _unmatched(post) - base_unmatched
            if left_alive:
                state, why, kind = "orphans-alive", "survivors %s" % left_alive, "orphans-alive"
            elif outcome == "deadline":
                state, why, kind = "timeout-killed", "deadline %ss hit" % deadline, "timeout"
            elif outcome == "wrapper-signaled":
                state, why, kind = "wrapper-signaled", "wrapper got signal %s" % flagged["sig"], "timeout"
            elif first_alive:
                state, why, kind = "escaped-descendants-killed", (
                    "child left process(es) %s alive after exit (contract violation); killed" % first_alive), "needs-review"
            elif rc != 0:
                state, why, kind = "child-failed", "exit code %s" % rc, "child-failed"
            elif not post_ok:
                state, why, kind = "needs-review", "post-run ledger scan: %s %s" % (
                    post["status"], post.get("problems")), "needs-review"
            elif new_unmatched > 0:
                state, why, kind = "unknown-reserve", "%d new reserve(s) without result" % new_unmatched, "needs-review"
            else:
                state, why, kind = CLEAN, "child exited 0, ledger verified, no new unmatched reserve", "clean"
            final = _write_state(state_dir, dict(base, state=state, reason=why,
                                 child_pid=p.pid, child_pgid=pgid, exit_code=rc))
            return kind, dict(state=state, reason=why, run_id=run_id, exit_code=rc,
                              survivors=left_alive, new_unmatched=new_unmatched)
        finally:
            for sg, h in old.items():
                signal.signal(sg, h)
    finally:
        os.close(lockfd)     # descendants that inherited the fd keep the lock


def clear(state_dir, reason):
    """Human-only. Needs the lock (no live descendant holds it), no survivors,
    and a written reason. Archives the old state in history. Does not touch
    the ledger or the lane."""
    if not (isinstance(reason, str) and len(reason.strip()) >= 8):
        return False, "a written reason (8+ chars) is required"
    try:
        _prep_dir(state_dir)
    except (OSError, RuntimeError) as exc:
        return False, "state dir: %s" % exc
    lockfd = _lock(state_dir)
    if lockfd is None:
        return False, "run lock held: a wrapper or surviving descendant is alive"
    try:
        doc, prob = _read_state(state_dir)
        if prob:
            return False, prob
        if doc is None or doc["state"] == CLEAN:
            return False, "nothing to clear"
        s = survivors(doc.get("run_id"), doc.get("child_pgid"))
        if s:
            return False, "survivors still alive: %s" % s
        _write_state(state_dir, {"v": 1, "state": CLEAN, "run_id": doc.get("run_id"),
                                 "reason": "cleared by operator: %s (was %s)" % (reason.strip(), doc["state"])})
        return True, "cleared"
    finally:
        os.close(lockfd)


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--state-dir", required=True)
    r.add_argument("--deadline", type=float, required=True)
    r.add_argument("--planned", type=int)
    r.add_argument("--epoch-budget", action="append", metavar="FILE=N")
    r.add_argument("--log-dir"); r.add_argument("--cap", type=int)
    r.add_argument("--allow-fresh", action="store_true")
    r.add_argument("child", nargs=argparse.REMAINDER)
    s = sub.add_parser("status"); s.add_argument("--state-dir", required=True)
    c = sub.add_parser("clear")
    c.add_argument("--state-dir", required=True); c.add_argument("--reason", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "status":
        doc, prob = _read_state(a.state_dir)
        print(json.dumps({"state": doc, "problem": prob}, sort_keys=True))
        return 0 if doc is None or doc["state"] == CLEAN else 1
    if a.cmd == "clear":
        ok, msg = clear(a.state_dir, a.reason)
        print(msg)
        return 0 if ok else 1
    child = a.child[1:] if a.child[:1] == ["--"] else a.child
    eb = None
    if a.epoch_budget:
        eb = {}
        for item in a.epoch_budget:
            k, _, v = item.rpartition("=")
            try:
                eb[k] = int(v)
            except ValueError:
                eb[k] = None
    try:
        kind, detail = run(a.state_dir, child, a.deadline, planned=a.planned,
                           epoch_budgets=eb, log_dir=a.log_dir, cap=a.cap,
                           allow_fresh=a.allow_fresh)
    except Exception as exc:    # fail closed on anything unexpected
        kind, detail = "internal", {"reason": "wrapper error: %s" % type(exc).__name__}
    print("BOUNDED_RUN_RESULT " + json.dumps(dict(detail, outcome=kind), sort_keys=True, default=str),
          file=sys.stderr)
    return EXIT[kind]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
