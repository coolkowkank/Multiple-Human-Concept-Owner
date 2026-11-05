"""Cooperative owner-liveness declaration (RW4). Offline, no network.

A seat process declares, before each bounded blocking step (one adapter
complete() or one verify run), "I am in step X for turn T and my own bound
ends at D". The supervisor reads it and treats the owner as live only
while the declaration matches the CURRENT turn identity, the process the
supervisor itself started and the lease holder, and now <= D.

This is cooperative evidence from a same-user process. It is NOT a proof
of progress, does not renew or protect the lease, and does not stop
another launcher from running. A missing, malformed, stale or mismatched
declaration means "unknown", never "live".
"""
import json
import math
import os
import re
import stat

VERSION = 1
MAX_STEP_SECONDS = 7200        # a declared bound above this is malformed
MAX_FILE = 4096
FUTURE_SKEW = 5.0
PHASES = ("adapter", "verify")
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _path(repo, seat):
    git_dir = os.path.join(repo, ".git")
    if not isinstance(seat, str) or not _NAME.match(seat) or seat in (".", "..") \
            or not os.path.isdir(git_dir) or os.path.islink(git_dir):
        return None
    return os.path.join(git_dir, f"lg-live-{seat}.json")


def write_declaration(repo, seat, state, holder, phase, seconds, now):
    """Best-effort atomic private write. Returns True when written. Never
    raises: a failed write means the supervisor sees 'unknown'."""
    try:
        path = _path(repo, seat)
        if path is None or phase not in PHASES:
            return False
        seconds = float(seconds)
        if not (0 < seconds <= MAX_STEP_SECONDS) or not math.isfinite(seconds):
            return False
        doc = {"v": VERSION, "seat": seat, "pid": os.getpid(),
               "turn": state.get("turn"), "turn_seq": state.get("turn_seq"),
               "turn_since": state.get("turn_since"), "holder": holder,
               "phase": phase, "written_at": float(now),
               "deadline": float(now) + seconds}
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            os.unlink(tmp)
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(json.dumps(doc))
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return True
    except Exception:
        return False


def clear_declaration(repo, seat):
    """Best-effort: remove only OUR declaration (same pid)."""
    try:
        path = _path(repo, seat)
        if path is None:
            return
        d = read_declaration(repo, seat)
        if d is not None and d.get("pid") == os.getpid():
            os.unlink(path)
    except Exception:
        pass


def read_declaration(repo, seat):
    """The parsed dict of a private regular file owned by this user, else
    None (missing, symlink, wrong owner/mode, oversize, not a JSON object)."""
    try:
        path = _path(repo, seat)
        if path is None:
            return None
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as fh:
            st = os.fstat(fh.fileno())
            if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
                    or st.st_mode & 0o077 or st.st_size > MAX_FILE):
                return None
            doc = json.loads(fh.read(MAX_FILE + 1).decode("utf-8"))
        return doc if isinstance(doc, dict) else None
    except Exception:
        return None


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) \
        and math.isfinite(x)


def liveness(state, decl, now, proc_pid):
    """Pure. Returns (verdict, reason), verdict in live | overrun | unknown.

    live: a valid declaration bound to this turn identity, this supervisor-
    started process and the lease holder, with now <= its own deadline.
    overrun: valid and bound but now is past its own deadline.
    unknown: anything else (never treated as live)."""
    if not isinstance(decl, dict):
        return "unknown", "no declaration"
    turn = state.get("turn")
    if decl.get("v") != VERSION or decl.get("seat") != turn:
        return "unknown", "declaration is for another seat or version"
    if proc_pid is None or isinstance(proc_pid, bool) \
            or decl.get("pid") != proc_pid or isinstance(decl.get("pid"), bool):
        return "unknown", "declaration is not from the supervisor-started process"
    if (decl.get("turn") != turn or decl.get("turn_seq") != state.get("turn_seq")
            or decl.get("turn_since") != state.get("turn_since")
            or not isinstance(decl.get("turn_since"), str)):
        return "unknown", "declaration is for a different turn"
    lease = (state.get("leases") or {}).get(turn)
    if isinstance(lease, dict) and decl.get("holder") != lease.get("holder"):
        return "unknown", "declaration holder differs from the lease holder"
    if decl.get("phase") not in PHASES:
        return "unknown", "declaration phase is not recognised"
    w, d = decl.get("written_at"), decl.get("deadline")
    if not (_num(w) and _num(d)) or not (0 < d - w <= MAX_STEP_SECONDS):
        return "unknown", "declaration bound is malformed or unbounded"
    if w > now + FUTURE_SKEW:
        return "unknown", "declaration is stamped in the future"
    if now <= d:
        return "live", f"inside its declared {decl['phase']} bound"
    return "overrun", f"past its own declared {decl['phase']} bound"
