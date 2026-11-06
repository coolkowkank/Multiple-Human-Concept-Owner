"""Hard wall-clock wrapper for ONE foreground invocation (offline tool).

New labeled implementation. It is NOT a recovery of any earlier local work,
it makes no provider call itself, and it is not an execution approval.

It runs an argv (for example `python3 -m launcher seat NAME --once`) in its
own session under a hard deadline, and fails closed:

 1. Containment: the wrapper becomes a child SUBREAPER (prctl). Every
    orphaned descendant, including setsid / double-forked / `env -i`
    scrubbed / bwrap'd processes, reparents to the wrapper and is therefore
    found by walking the ppid chain in /proc, not by pgid, sid or
    environment. On deadline or exit the wrapper SIGSTOPs then SIGKILLs the
    whole tree, repeats until empty, reaps, and fails if anything remains.
    If the subreaper facility is unavailable the wrapper REFUSES to spawn.
 2. Mutual exclusion: the wrapper holds an exclusive flock through cleanup
    and the final marker write. (The lock fd is inherited only by the direct
    child; close_fds launchers do not pass it on, so overlap protection is the
    wrapper's own lock plus the marker, not descendant fd inheritance.)
 3. Mandatory read-only reserve_preflight before spawn. Accounting input is
    exactly one of `planned` or a `roster` (.team/roster.json) from which
    per-epoch lifetime budgets are derived for EVERY http seat; unknown or cli
    adapter types, shared log files and malformed budgets are refused. The
    pre-run ledger snapshot is the anchor for the post-run scan, so deleted
    or truncated or rewritten logs block, and the last clean run's anchor
    guards the next start.
 4. Durable marker (atomic tmp+fsync+rename+fsync dir) written BEFORE spawn.
    Only state "clean" (or no state) allows a start. Every other state, and
    any "starting"/"running" found at the next start (wrapper died), refuses
    until a human runs `clear` with a reason. No auto-resume, no retry, no
    repair of the lane or the ledger. A reserve with no result stays
    consumed/unknown.
 5. Any exception after spawn kills and reaps the tree before returning.
 6. PR_SET_PDEATHSIG(SIGKILL) on the direct child.

LIMITS (not claimed away):
 - If the WRAPPER ITSELF is SIGKILLed, only the direct child dies
   (PDEATHSIG). Grandchildren that are setsid'd and env-scrubbed (for
   example the launcher's sandboxed verify: `env -i` + `bwrap --new-session`)
   are then no longer findable by this tool. Their containment in that case
   rests on bwrap's own --die-with-parent (read in source, not executed here).
   The marker still blocks the next start; clear is refused while the group,
   session or run-id scan sees anything alive.
 - PID reuse: matching by numeric pid/pgid can false-block, never false-allow.
 - Killing the client does not cancel a provider request: a killed call stays
   consumed/unknown exactly as before.
 - Linux /proc only; a process in uninterruptible sleep cannot be killed and
   is reported as orphans-alive.
 - Envelope: MAX_DEADLINE 80 + TERM_GRACE 3 + KILL_BUDGET 6 + preflight/scan/
   fsync time (small, unmeasured on a loaded host) stays well under a 120 s
   foreground tool limit. A call needing more than ~80 s of model time cannot
   complete under this wrapper.
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

MAX_DEADLINE = 80           # s. Envelope: <=80 + TERM_GRACE 3 + KILL_BUDGET 6 + scans/writes, ~25 s margin under a 120 s tool limit
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


def _killpg(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


# ------------------------------------------------------------------- ledger
def _unmatched(pf):
    return sum(x.get("unmatched_reserves", 0) for x in pf.get("files", []))


# ------------------------------------------------------------- containment
PR_SET_CHILD_SUBREAPER = 36
PR_GET_CHILD_SUBREAPER = 37
KILL_BUDGET = 6.0           # hard cap on the whole kill-and-reap phase


def _prctl(op, arg=0):
    libc = ctypes.CDLL(None, use_errno=True)
    if op == PR_GET_CHILD_SUBREAPER:
        v = ctypes.c_int(0)
        if libc.prctl(op, ctypes.byref(v), 0, 0, 0) != 0:
            return None
        return v.value
    return libc.prctl(op, arg, 0, 0, 0)


def _subreaper_on():
    """Make this process the reaper of every orphaned descendant, so a
    double-forked, setsid'd or env-scrubbed process is still a descendant in
    /proc (ppid chain) of the wrapper. Returns False when unsupported."""
    try:
        return _prctl(PR_SET_CHILD_SUBREAPER, 1) == 0 and _prctl(PR_GET_CHILD_SUBREAPER) == 1
    except Exception:
        return False


def _subreaper_off():
    try:
        _prctl(PR_SET_CHILD_SUBREAPER, 0)
    except Exception:
        pass


def _ppid_map():
    m = {}
    for name in os.listdir("/proc"):
        if name.isdigit():
            f = _stat_fields(int(name))
            if f is not None:
                m[int(name)] = f
    return m


def _children_of(root, m=None):
    m = m or _ppid_map()
    return [pid for pid, f in m.items() if f["ppid"] == root]


def descendants(root, exclude_roots=(), m=None):
    """Every live (non-zombie) transitive child of root by ppid chain,
    ignoring the subtrees of exclude_roots."""
    m = m or _ppid_map()
    kids = {}
    for pid, f in m.items():
        kids.setdefault(f["ppid"], []).append(pid)
    out, stack, skip = [], list(kids.get(root, [])), set(exclude_roots)
    while stack:
        pid = stack.pop()
        if pid in skip:
            continue
        if m[pid]["state"] not in ("Z", "X"):
            out.append(pid)
        stack.extend(kids.get(pid, []))
    return out


def _reap(pids):
    for pid in pids:
        try:
            os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            pass


def kill_tree(root, exclude_roots, run_id, pgid, budget=KILL_BUDGET):
    """SIGSTOP then SIGKILL every descendant of the wrapper (the wrapper is a
    subreaper, so orphans count), plus group/session/env matches, repeating
    until none remain or the budget is spent. Returns the leftovers."""
    end = time.monotonic() + budget
    left = []
    while True:
        m = _ppid_map()
        tgt = set(descendants(root, exclude_roots, m))
        tgt.update(p for p in survivors(run_id, pgid) if p not in set(exclude_roots))
        if not tgt:
            return []
        for sig in (signal.SIGSTOP, signal.SIGKILL):     # stop first: no forking race
            for pid in tgt:
                try:
                    os.kill(pid, sig)
                except OSError:
                    pass
        _reap(tgt)
        left = sorted(tgt)
        if time.monotonic() >= end:
            m = _ppid_map()
            return [p for p in left if p in m and m[p]["state"] not in ("Z", "X")]
        time.sleep(0.03)


# ------------------------------------------------------------------ roster
HTTP_MAX_BUDGET = 8      # source: langgraph_team.HTTP_MAX_BUDGET
_EPOCH = __import__("re").compile(r"^[a-z0-9-]{1,32}$")
_SPEND_FREE_TYPES = ("mock", "queue")


def epoch_budgets_from_roster(path):
    """Source-grounded epoch budgets: {'slug.epoch.jsonl': call_budget} for
    EVERY http seat in <lane>/.team/roster.json (the same file
    langgraph_team's live preflight reads). Refuses, never guesses: unknown
    or cli adapter types (an unbounded spend path), a bad budget, a
    usage_log that is not the derived slug.epoch.jsonl, or two seats sharing
    a log file. Returns (dict_or_None, problem_or_None)."""
    import re
    try:
        doc = json.load(open(path, encoding="utf-8"))
        seats = doc["seats"]
        if not isinstance(seats, dict):
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        return None, "roster unreadable or has no seats object"
    out = {}
    for name, rs in seats.items():
        ad = rs.get("adapter") if isinstance(rs, dict) else None
        if not isinstance(ad, dict):
            return None, "seat %r has no adapter object" % (name,)
        kind = ad.get("type", "mock")
        if kind in _SPEND_FREE_TYPES:
            continue
        if kind != "http":
            return None, "seat %r adapter type %r is not covered; refusing" % (name, kind)
        b, ep, model, ul = (ad.get("call_budget"), ad.get("log_epoch"),
                            ad.get("model"), ad.get("usage_log"))
        if not (isinstance(b, int) and not isinstance(b, bool) and 1 <= b <= HTTP_MAX_BUDGET):
            return None, "seat %r call_budget is not an int in 1..%d" % (name, HTTP_MAX_BUDGET)
        if not (isinstance(ep, str) and _EPOCH.match(ep) and isinstance(model, str) and isinstance(ul, str)):
            return None, "seat %r has a malformed model/log_epoch/usage_log" % (name,)
        slug = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")
        fn = "%s.%s.jsonl" % (slug, ep)
        if os.path.basename(ul) != fn:
            return None, "seat %r usage_log is not the derived %s" % (name, fn)
        if fn in out:
            return None, "seats share log file %s; ambiguous budget, refusing" % fn
        out[fn] = b
    return out, None


# --------------------------------------------------------------------- run
def run(state_dir, argv, deadline, *, planned=None, roster=None,
        log_dir=None, cap=None, allow_fresh=False, env=None):
    """Returns (outcome, detail dict). Never spawns unless every gate passed.
    Exactly one of planned (a flat call count) or roster (source-grounded
    epoch budgets from .team/roster.json) must be given."""
    t_start = time.monotonic()

    def refuse(why, **kw):
        return "refused", dict(reason=why, **kw)
    if not argv or not all(isinstance(a, str) and a for a in argv):
        return refuse("empty or malformed argv")
    if not (isinstance(deadline, (int, float)) and not isinstance(deadline, bool)
            and 0 < deadline <= MAX_DEADLINE):
        return refuse("deadline must be in (0, %d] seconds" % MAX_DEADLINE)
    if (planned is None) == (roster is None):
        return refuse("give exactly one of planned or roster (ambiguous/missing accounting input)")
    if planned is not None and not (isinstance(planned, int) and not isinstance(planned, bool) and planned >= 0):
        return refuse("planned must be a non-negative int")
    epoch_budgets = None
    if roster is not None:
        epoch_budgets, prob = epoch_budgets_from_roster(roster)
        if prob:
            return refuse("roster: " + prob)
        planned = sum(epoch_budgets.values())
        if not epoch_budgets:
            epoch_budgets = None
    try:
        _prep_dir(state_dir)
    except (OSError, RuntimeError) as exc:
        return refuse("state dir: %s" % exc)
    lockfd = _lock(state_dir)
    if lockfd is None:
        return refuse("run lock held: another wrapper (or a leftover holder) is running")
    child_started = False
    try:
        doc, prob = _read_state(state_dir)
        if prob:
            return refuse(prob)
        anchor = None
        if doc is not None and doc["state"] != CLEAN:
            prev = doc["state"]
            if prev in ("starting", "running"):
                _write_state(state_dir, dict(doc, state="wrapper-crashed-unknown",
                             reason="previous wrapper died while %s" % prev))
                prev = "wrapper-crashed-unknown"
            s = survivors(doc.get("run_id"), doc.get("child_pgid"))
            return refuse("previous run is %s; a human must clear it" % prev,
                          survivors=s, prev_run_id=doc.get("run_id"))
        if doc is not None and isinstance(doc.get("anchor"), dict):
            anchor = doc["anchor"]     # captured after the last clean run
        if not _subreaper_on():
            return refuse("containment unavailable: cannot become a child subreaper; "
                          "refusing (a full descendant tree cannot be bounded)")
        pf = rp.preflight(planned, log_dir=log_dir, cap=cap, anchor=anchor,
                          allow_fresh=allow_fresh, epoch_budgets=epoch_budgets)
        if pf["status"] != "ok_to_plan":
            _subreaper_off()
            return refuse("preflight %s" % pf["status"], problems=pf.get("problems"))
        base_unmatched = _unmatched(pf)
        pre_anchor = _anchor(pf)
        run_id = secrets.token_hex(8)
        wpid = os.getpid()
        base = {"v": 2, "run_id": run_id, "wrapper_pid": wpid,
                "wrapper_start": (_stat_fields(wpid) or {}).get("start"),
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
        pre_kids = set(_children_of(wpid))      # not ours to kill (in-process use)

        def pdeathsig():
            libc = ctypes.CDLL(None, use_errno=True)
            libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0)
            if os.getppid() != wpid:            # wrapper already gone
                os._exit(111)
        pgid = None
        p = None
        try:
            try:
                p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, env=cenv,
                                     start_new_session=True, close_fds=True,
                                     pass_fds=(lockfd,), preexec_fn=pdeathsig)
            except OSError as exc:
                _write_state(state_dir, dict(base, state=CLEAN, anchor=anchor,
                             reason="spawn failed before any child ran: %s" % type(exc).__name__))
                return refuse("spawn failed: %s" % type(exc).__name__)
            child_started = True
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
            first_alive = sorted(set(descendants(wpid, pre_kids)) | set(survivors(run_id, pgid)))
            left_alive = kill_tree(wpid, pre_kids, run_id, pgid)
            if rc is None:
                try:
                    rc = p.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
            post = rp.preflight(0 if epoch_budgets is None else planned, log_dir=log_dir, cap=cap,
                                anchor=pre_anchor, allow_fresh=False, epoch_budgets=epoch_budgets)
            post_ok = post["status"] in ("ok_to_plan", "over_cap")
            new_unmatched = _unmatched(post) - base_unmatched
            if left_alive:
                state, why, kind = "orphans-alive", "survivors %s" % left_alive, "orphans-alive"
            elif outcome == "deadline":
                state, why, kind = "timeout-killed", "deadline %ss hit" % deadline, "timeout"
            elif outcome == "wrapper-signaled":
                state, why, kind = "wrapper-signaled", "wrapper got signal %s" % flagged["sig"], "timeout"
            elif first_alive and outcome == "exited":
                state, why, kind = "escaped-descendants-killed", (
                    "child left process(es) %s alive after exit; killed" % first_alive), "needs-review"
            elif rc != 0:
                state, why, kind = "child-failed", "exit code %s" % rc, "child-failed"
            elif not post_ok:
                state, why, kind = "needs-review", "post-run ledger scan vs pre-run anchor: %s %s" % (
                    post["status"], post.get("problems")), "needs-review"
            elif new_unmatched > 0:
                state, why, kind = "unknown-reserve", "%d new reserve(s) without result" % new_unmatched, "needs-review"
            else:
                state, why, kind = CLEAN, "child exited 0, ledger verified, no new unmatched reserve", "clean"
            extra = {"anchor": _anchor(post)} if state == CLEAN else {}
            _write_state(state_dir, dict(base, state=state, reason=why, child_pid=p.pid,
                                         child_pgid=pgid, exit_code=rc, **extra))
            return kind, dict(state=state, reason=why, run_id=run_id, exit_code=rc,
                              survivors=left_alive, new_unmatched=new_unmatched,
                              elapsed=round(time.monotonic() - t_start, 2))
        except BaseException as exc:
            # any failure after spawn: contain first, then record, never leave a child
            left_alive = []
            try:
                if pgid is not None:
                    _killpg(pgid, signal.SIGKILL)
                left_alive = kill_tree(wpid, pre_kids, run_id, pgid)
            except BaseException:
                left_alive = ["unknown"]
            try:
                _write_state(state_dir, dict(base, state="internal-error-after-spawn",
                             reason="%s after spawn; group killed, survivors %s" % (type(exc).__name__, left_alive),
                             child_pid=getattr(p, "pid", None), child_pgid=pgid))
            except BaseException:
                pass        # marker stays starting/running: next start records wrapper-crashed-unknown
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            return "internal", dict(reason="%s after spawn; contained" % type(exc).__name__,
                                    survivors=left_alive)
        finally:
            for sg, h in old.items():
                signal.signal(sg, h)
            _subreaper_off()
    finally:
        os.close(lockfd)


def _anchor(pf):
    """Operator-style anchor from a verified scan: per-file lines + chain tip
    (files with at least one line), or None."""
    a = rp.snapshot(pf)
    if not a:
        return None
    a["files"] = {k: v for k, v in a["files"].items() if v["lines"] >= 1}
    return a if a["files"] else None


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
    r.add_argument("--roster", help="<lane>/.team/roster.json; derives epoch budgets for every http seat")
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
    try:
        kind, detail = run(a.state_dir, child, a.deadline, planned=a.planned, roster=a.roster,
                           log_dir=a.log_dir, cap=a.cap,
                           allow_fresh=a.allow_fresh)
    except Exception as exc:    # fail closed on anything unexpected
        kind, detail = "internal", {"reason": "wrapper error: %s" % type(exc).__name__}
    print("BOUNDED_RUN_RESULT " + json.dumps(dict(detail, outcome=kind), sort_keys=True, default=str),
          file=sys.stderr)
    return EXIT[kind]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
