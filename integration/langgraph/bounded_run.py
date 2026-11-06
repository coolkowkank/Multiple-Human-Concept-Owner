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
 3. Mandatory read-only reserve_preflight before spawn. The supported path is
    run_live(): the wrapper builds `python3 langgraph_team.py live LANE DB
    CONFIG THREAD` itself and derives per-epoch lifetime budgets from that
    same config plus the lane's own roster through the SAME function
    (reserve_preflight.live_epoch_budgets) live_entry uses, so the accounting
    binds the actual child entry. Arbitrary argv (`raw`) takes only a flat
    planned count and makes no such binding. Unknown/cli adapters, shared log
    files and malformed budgets are refused. The
    pre-run ledger snapshot is the anchor for the post-run scan, so deleted
    or truncated or rewritten logs block, and the last clean run's anchor
    guards the next start.
 4. Durable marker (atomic tmp+fsync+rename+fsync dir) written BEFORE spawn.
    Only state "clean" (or no state) allows a start. Every other state, and
    any "starting"/"running" found at the next start (wrapper died), refuses
    until `clear`. RECOVERABLE states (tree verified gone) clear with a
    reason; LOST-CONTAINMENT states (wrapper died, orphans-alive) do not clear
    in this tool at all unless the kernel boot id changed. No auto-resume, no
    retry, no repair of the lane or the ledger. A reserve with no result stays
    consumed/unknown. The ledger anchor survives every clear; allow_fresh is
    ignored once a state file exists.
 5. Any exception after spawn kills and reaps the tree before returning.
 6. PR_SET_PDEATHSIG(SIGKILL) on the direct child.

LIMITS (not claimed away):
 - If the WRAPPER ITSELF is SIGKILLed, only the direct child dies
   (PDEATHSIG). Scrubbed setsid grandchildren (the launcher's sandboxed
   verify: `env -i` + `bwrap --new-session`) are then invisible to this tool.
   bwrap's --die-with-parent very probably kills that payload (proxy-tested by
   a reviewer, not run through the real shim), but nothing here can verify it.
   So that state is deliberately left blocked: see clear().
 - Matching by numeric pid/pgid/sid and the run-id environ can false-block
   (pid reuse), never false-allow. The marker records the direct child only.
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
import fenced_http as fh  # noqa: E402

MAX_DEADLINE = 80           # s. Envelope: <=80 + TERM_GRACE 3 + KILL_BUDGET 6 + scans/writes, ~25 s margin under a 120 s tool limit
TERM_GRACE = 3.0
VERIFY_WAIT = 5.0
ENV_KEY = "LG_BOUNDED_RUN_ID"
EXIT = {"clean": 0, "refused": 10, "timeout": 11, "child-failed": 12,
        "needs-review": 13, "orphans-alive": 14, "internal": 15}
CLEAN = "clean"
PR_SET_PDEATHSIG = 1


def _boot_id():
    try:
        return open("/proc/sys/kernel/random/boot_id").read().strip() or None
    except OSError:
        return None


def _pidns():
    try:
        return os.readlink("/proc/self/ns/pid")
    except OSError:
        return None


# States after which the process tree is KNOWN contained and verified gone (or
# was never started). An ordinary clear (with a reason) may release these.
RECOVERABLE = ("timeout-killed", "wrapper-signaled", "child-failed", "needs-review",
               "unknown-reserve", "escaped-descendants-killed", "internal-error-after-spawn")
# Containment was lost or cannot be shown: a surviving descendant may exist
# that no scan can see (setsid + env-scrubbed). NOT clearable by a reason.
LOST_CONTAINMENT = ("wrapper-crashed-unknown", "starting", "running", "orphans-alive")


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


# ------------------------------------------------------- bound live entry
LIVE_ENTRY = os.path.join(HERE, "langgraph_team.py")


def _source_constant(name):
    """Read a literal constant from langgraph_team.py source with ast (no
    import: the entry needs langgraph, the wrapper must not)."""
    import ast
    tree = ast.parse(open(LIVE_ENTRY, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name:
            return ast.literal_eval(node.value)
    raise KeyError(name)


def live_binding(lane, db, config, thread="live-1"):
    """Bind the wrapper to the ACTUAL child entry: argv is built HERE as
    `python3 langgraph_team.py live LANE DB CONFIG THREAD` and the epoch
    budgets come from that same config + the lane's own .team/roster.json via
    the shared reserve_preflight.live_epoch_budgets, i.e. what live_entry
    will itself configure. No caller-supplied argv or roster path.
    Returns (argv, epoch_budgets, None) or (None, None, problem)."""
    try:
        lane = os.path.abspath(lane)
        rpath = os.path.join(lane, ".team", "roster.json")
        for pth, what in ((rpath, "roster"), (config, "config")):
            st = os.lstat(pth)
            if not stat.S_ISREG(st.st_mode):
                return None, None, "%s is not a regular file" % what
        if not os.path.isdir(os.path.join(lane, ".git")):
            return None, None, "lane is not a git repo"
        for tok in (db, thread):
            if not isinstance(tok, str) or not tok or tok.startswith("-") or "\0" in tok:
                return None, None, "db/thread must be plain non-empty arguments"
        cfg = json.load(open(config, encoding="utf-8"))
        roster = json.load(open(rpath, encoding="utf-8"))
        cfg_keys, seat_keys = _source_constant("LIVE_CFG_KEYS"), _source_constant("LIVE_SEAT_KEYS")
        if not isinstance(cfg, dict) or set(cfg) - cfg_keys or not isinstance(cfg.get("seats"), dict) \
                or not cfg["seats"]:
            return None, None, "config keys/seats do not match the entry's own rules"
        for name, sc in cfg["seats"].items():
            if name not in roster["seats"]:
                return None, None, "configured seat %r not in the lane roster" % (name,)
            if not isinstance(sc, dict) or set(sc) - seat_keys:
                return None, None, "configured seat %r has keys outside the entry's set" % (name,)
        eb, why = rp.live_epoch_budgets(cfg["seats"], roster["seats"], strict=True)
        if why:
            return None, None, why
    except (OSError, ValueError, KeyError, TypeError, SyntaxError) as exc:
        return None, None, "cannot ground the entry: %s" % type(exc).__name__
    argv = [sys.executable, LIVE_ENTRY, "live", lane, db, os.path.abspath(config), thread]
    return argv, eb, None


def live_config_hash(lane, config):
    """sha256 over the CONTENT the live entry will read: the config file
    bytes, the lane roster bytes, and the shared epoch-budget computation.
    Recomputed from disk at each call (the wrapper calls it right before
    spawn), so an edit after the window was opened is caught."""
    lane = os.path.abspath(lane)
    cb = open(config, "rb").read()
    rb = open(os.path.join(lane, ".team", "roster.json"), "rb").read()
    eb, why = rp.live_epoch_budgets(json.loads(cb)["seats"], json.loads(rb)["seats"], strict=True)
    if why:
        raise ValueError(why)
    h = hashlib.sha256()
    for part in (cb, rb, json.dumps(eb, sort_keys=True).encode()):
        h.update(hashlib.sha256(part).digest())
    return h.hexdigest()


def run_live(state_dir, lane, db, config, deadline, thread="live-1", env=None):
    """The supported path: bounded `langgraph_team.py live`, ledger = the
    entry's own default dir/cap, accounting from the entry's own inputs. No
    allow_fresh, no log-dir/cap override."""
    argv, eb, why = live_binding(lane, db, config, thread)
    if why:
        return "refused", {"reason": "entry binding: " + why}
    return run(state_dir, argv, deadline, epoch_budgets=eb if eb else None,
               planned=None if eb else 0, env=env, cwd=HERE,
               config_hash_fn=lambda: live_config_hash(lane, config))


def window_gate(state_dir, log_dir, planned, argv=None, epoch_budgets=None, config_hash_fn=None):
    """None or the reason to refuse BEFORE spawn. Requires the fence's own
    verified open window with room for the planned calls, and a local copy
    of the pending-window receipt that is PARSED and compared field by
    field to the window line and to this actual run: kind, seq, k, nonce,
    config_hash, prev_receipt_hash, argv_sha256, planned (or epoch_budgets,
    the shared config+roster computation), plus its sha256 = receipt_hash.
    The orchestrator must have written the receipt to a private Hosted
    File first; the wrapper only checks the local copy (it cannot see or
    prove the upload). Skipped only when fh.WINDOW_GATE is False (tests)."""
    if not fh.WINDOW_GATE:
        return None
    ok, why, info = fh.window_status(log_dir, check_run=False)
    if not ok:
        return why
    sm = fh.ledger_summary(log_dir)
    if not sm.get("consistent") or sm.get("over_cap"):
        return "ledger accounting not consistent (spent/committed) or over the cap: %r" % {k: sm.get(k) for k in ("spent", "committed", "over_cap")}
    w = fh.read_control(log_dir)["windows"][-1]
    tok = os.environ.get(fh.WINDOW_TOKEN_ENV)
    if not tok or hashlib.sha256(tok.encode()).hexdigest() != w["owner_hash"]:
        return "window owner token missing or wrong"
    if planned > info["k"] - info["used"]:
        return "planned %d exceeds the window's remaining %d" % (planned, info["k"] - info["used"])
    p = os.path.join(state_dir, "window-receipt-%s.json" % w["nonce"])
    try:
        st = os.lstat(p)
        if not stat.S_ISREG(st.st_mode) or st.st_size > 100_000:
            return "receipt is not a small regular file"
        raw = open(p, "rb").read()
    except OSError:
        return "pending-window receipt missing in the state dir"
    if hashlib.sha256(raw).hexdigest() != w["receipt_hash"]:
        return "receipt hash does not match the window line"
    try:
        r = json.loads(raw)
    except ValueError:
        return "receipt is not JSON"
    if not isinstance(r, dict) or r.get("kind") != "pending-window":
        return "receipt kind is not pending-window"
    for f in ("seq", "k", "nonce", "config_hash", "prev_receipt_hash", "owner_hash"):
        if r.get(f) != w[f]:
            return "receipt field %s differs from the window line" % f
    if config_hash_fn is not None:      # live entry: window config_hash must equal the content hash NOW
        try:
            now = config_hash_fn()
        except (OSError, ValueError, KeyError, TypeError):
            return "cannot recompute the config+roster content hash"
        if w["config_hash"] != now:
            return "config+roster content changed since the window was opened"
    if r.get("argv_sha256") != hashlib.sha256("\0".join(argv or []).encode()).hexdigest():
        return "receipt argv binding differs from this run"
    if epoch_budgets is not None:
        if r.get("epoch_budgets") != dict(epoch_budgets):
            return "receipt epoch_budgets differ from the live config+roster computation"
    elif r.get("planned") != planned:
        return "receipt planned differs from this run"
    return None


def close_window(log_dir, run_id):
    """Typed close, only called once the process tree is dead: burns the
    window's remaining K as spent-unknown so the window can never be
    reopened or reused (also what a restore does to an unclosed window).
    Returns None or a short failure text."""
    try:
        okw, whyw, _ = fh.window_status(log_dir)
        w = fh.read_control(log_dir)["windows"][-1]
        if w["kind"] != "window-open":
            return None
        rh = hashlib.sha256((w["receipt_hash"] + ":close:" + run_id).encode()).hexdigest()
        nn = hashlib.sha256(("close:" + w["nonce"] + run_id).encode()).hexdigest()
        fh.burn_window(log_dir, nn, w["config_hash"], rh, w["receipt_hash"])
        return None
    except (fh.FenceRefused, OSError, IndexError) as exc:
        return "window close failed: %s" % str(exc)[:80]


# --------------------------------------------------------------------- run
def run(state_dir, argv, deadline, *, planned=None, epoch_budgets=None,
        log_dir=None, cap=None, allow_fresh=False, env=None, cwd=None,
        config_hash_fn=None):
    """Returns (outcome, detail dict). Never spawns unless every gate passed.
    Exactly one of planned (a flat call count) or epoch_budgets must be
    given. Generic argv is for tests/operators and makes no claim that the
    child's own ledger use matches; run_live() is the bound entry."""
    t_start = time.monotonic()

    def refuse(why, **kw):
        return "refused", dict(reason=why, **kw)
    if not argv or not all(isinstance(a, str) and a for a in argv):
        return refuse("empty or malformed argv")
    if not (isinstance(deadline, (int, float)) and not isinstance(deadline, bool)
            and 0 < deadline <= MAX_DEADLINE):
        return refuse("deadline must be in (0, %d] seconds" % MAX_DEADLINE)
    if (planned is None) == (epoch_budgets is None):
        return refuse("give exactly one of planned or epoch_budgets (ambiguous/missing accounting input)")
    if planned is not None and not (isinstance(planned, int) and not isinstance(planned, bool) and planned >= 0):
        return refuse("planned must be a non-negative int")
    if epoch_budgets is not None:
        planned = sum(epoch_budgets.values()) if isinstance(epoch_budgets, dict) and epoch_budgets else None
        if planned is None:
            return refuse("epoch_budgets must be a non-empty dict")
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
                          allow_fresh=bool(allow_fresh and doc is None), epoch_budgets=epoch_budgets)
        if pf["status"] != "ok_to_plan":
            _subreaper_off()
            return refuse("preflight %s" % pf["status"], problems=pf.get("problems"))
        why = window_gate(state_dir, log_dir or fh.HTTP_LOG_DIR, planned, argv, epoch_budgets, config_hash_fn)
        if why:
            _subreaper_off()
            return refuse("window gate: " + why)
        base_unmatched = _unmatched(pf)
        pre_anchor = _anchor(pf)
        run_id = secrets.token_hex(8)
        wpid = os.getpid()
        base = {"v": 3, "run_id": run_id, "wrapper_pid": wpid,
                "boot_id": _boot_id(), "pidns": _pidns(), "anchor": pre_anchor,
                "wrapper_start": (_stat_fields(wpid) or {}).get("start"),
                "argv_sha256": hashlib.sha256("\0".join(argv).encode()).hexdigest(),
                "deadline_s": deadline, "child_pid": None, "child_pgid": None,
                "started_at": time.time()}
        if fh.WINDOW_GATE:
            try:
                w_ = fh.read_control(log_dir or fh.HTTP_LOG_DIR)["windows"][-1]
                fh.bind_run(log_dir or fh.HTTP_LOG_DIR, w_["nonce"], run_id, os.path.join(state_dir, "lock"))
            except (fh.FenceRefused, OSError, IndexError) as exc:
                _subreaper_off()
                return refuse("run bind refused: %s" % str(exc)[:80])
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
                p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, env=cenv, cwd=cwd,
                                     start_new_session=True, close_fds=True,
                                     pass_fds=(lockfd,), preexec_fn=pdeathsig)
            except OSError as exc:
                _write_state(state_dir, dict(base, state=CLEAN, anchor=pre_anchor,
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
            close_note = None
            if fh.WINDOW_GATE and not left_alive:
                close_note = close_window(log_dir or fh.HTTP_LOG_DIR, run_id)
                if close_note and state == CLEAN:
                    state, why, kind = "needs-review", close_note, "needs-review"
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
                _write_state(state_dir, dict(base,
                             state="internal-error-after-spawn" if not left_alive else "orphans-alive",
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
    """Human-only release of a blocked state. A reason string never erases
    uncertainty:
      - RECOVERABLE states (tree verified gone or never started) are released
        with a written reason, when no survivor is visible and the lock is free.
      - LOST_CONTAINMENT states (wrapper died mid-run, orphans-alive) are NOT
        released by this interface unless the machine has rebooted since the
        marker was written (a different kernel boot_id: every process of the
        old boot is gone). A scrubbed setsid descendant is invisible to any
        scan here, so no flag, reason or acknowledgement can establish that it
        is dead. Otherwise the state stays blocked; recovery needs a separate
        manual policy outside this tool.
    The ledger anchor survives every clear and allow_fresh is never honored
    again after a state file exists. Nothing here touches the ledger or lane."""
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
        st = doc["state"]
        ident = "run_id=%s child_pid=%s state=%s" % (doc.get("run_id"), doc.get("child_pid"), st)
        if st in LOST_CONTAINMENT:
            old, now = doc.get("boot_id"), _boot_id()
            if not (old and now and old != now):
                return False, ("refused: %s lost containment (unmonitored descendants may still run, "
                               "invisible to any scan). Not clearable by a reason in this tool; "
                               "needs a reboot or a separate manual recovery policy." % ident)
        elif st not in RECOVERABLE:
            return False, "refused: unknown state %r is not clearable" % st
        s = survivors(doc.get("run_id"), doc.get("child_pgid"))
        if s:
            return False, "survivors still alive: %s" % s
        _write_state(state_dir, {"v": 3, "state": CLEAN, "run_id": doc.get("run_id"),
                                 "boot_id": _boot_id(), "pidns": _pidns(),
                                 "anchor": doc.get("anchor"), "cleared_from": st,
                                 "reason": "cleared by operator: %s (was %s)" % (reason.strip(), st)})
        return True, "cleared (%s)" % ident
    finally:
        os.close(lockfd)


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    lv = sub.add_parser("live", help="bounded `langgraph_team.py live` (the supported path)")
    lv.add_argument("--state-dir", required=True)
    lv.add_argument("--deadline", type=float, required=True)
    lv.add_argument("--lane", required=True); lv.add_argument("--db", required=True)
    lv.add_argument("--config", required=True); lv.add_argument("--thread", default="live-1")
    r = sub.add_parser("raw", help="generic argv with a flat planned count (tests/operators; no entry binding)")
    r.add_argument("--state-dir", required=True)
    r.add_argument("--deadline", type=float, required=True)
    r.add_argument("--planned", type=int, required=True)
    r.add_argument("--log-dir"); r.add_argument("--cap", type=int)
    r.add_argument("child", nargs=argparse.REMAINDER)
    s = sub.add_parser("status"); s.add_argument("--state-dir", required=True)
    c = sub.add_parser("clear")
    c.add_argument("--state-dir", required=True); c.add_argument("--reason", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "status":
        doc, prob = _read_state(a.state_dir)
        rec = None if doc is None else ("clean" if doc["state"] == CLEAN else
                                         "recoverable" if doc["state"] in RECOVERABLE else "lost-containment")
        print(json.dumps({"state": doc, "problem": prob, "class": rec}, sort_keys=True))
        return 0 if doc is None or doc["state"] == CLEAN else 1
    if a.cmd == "clear":
        ok, msg = clear(a.state_dir, a.reason)
        print(msg)
        return 0 if ok else 1
    try:
        if a.cmd == "live":
            kind, detail = run_live(a.state_dir, a.lane, a.db, a.config, a.deadline, a.thread)
        else:
            child = a.child[1:] if a.child[:1] == ["--"] else a.child
            kind, detail = run(a.state_dir, child, a.deadline, planned=a.planned,
                               log_dir=a.log_dir, cap=a.cap)
    except Exception as exc:    # fail closed on anything unexpected
        kind, detail = "internal", {"reason": "wrapper error: %s" % type(exc).__name__}
    print("BOUNDED_RUN_RESULT " + json.dumps(dict(detail, outcome=kind), sort_keys=True, default=str),
          file=sys.stderr)
    return EXIT[kind]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
