"""Durable provider-request budget ledger (offline support module).

Project support tooling - NOT integrated into the executor, NOT rolled out.
Integration (tools/self-commit-executor.py) is a separate authorized step.

Guarantees (local POSIX filesystem, process-crash scope only):
- A reservation is durable BEFORE any transport is attempted.
- A crash at any point in the write path leaves the ledger valid:
  old bytes or new bytes, never empty/partial. Failure before os.replace
  leaves the ledger unchanged; failure at the post-replace directory fsync
  raises and the caller MUST halt without sending and without resetting
  anything (durability is old-or-new; the consumed reservation, if
  visible, stays consumed).
- A malformed, empty, corrupt, legacy-schema, negative-count,
  duplicate-id or count-inconsistent ledger fails CLOSED on load:
  no request may be sent, the file is left untouched, and there is no
  silent budget reset. Fresh start exists only via init_ledger(), which
  refuses to touch an existing path; deleting the ledger is a visible
  operator act, never a reset.
- Cross-process serialization uses a SEPARATE stable lock file
  (locking the ledger itself breaks across os.replace inode swaps).

Accounting (conservative by construction): every reservation consumes
budget and is never refunded. States per reservation (UUID-keyed,
transitions by UUID only, illegal transitions rejected):
  reserved -> transport_started -> completed | unknown
  transport_started is written durably BEFORE the request is sent.
Terminology: completed_transports = local transport finished (NOT proof
of provider receipt or billing); possibly_sent = transport_started +
unknown; reserved_only = no transport_started recorded (a workflow
invariant, NOT external proof nothing was sent). A dead owner's
transport_started entries are swept to unknown on the next reserve.

Non-claims: no power-loss or fsync-lie durability; flock is unreliable
on NFS; no semantic judgment about the requests; schema v1 is
incompatible with legacy {"used", "history"} ledgers, which enter only
through an explicit operator import with recorded counts (not provided
here). Stdlib only, no network.
"""
import fcntl, json, math, os, stat, time, uuid

VERSION = 1
STATES = ("reserved", "transport_started", "completed", "unknown")
NEXT = {"reserved": ("transport_started",),
        "transport_started": ("completed", "unknown"),
        "completed": (), "unknown": ()}


class LedgerError(RuntimeError):
    """Every error is fail-closed: caller must not send a provider request."""


# fault-injection seams (tests override these)
_fsync = lambda fd: os.fsync(fd)
_replace = lambda a, b: os.replace(a, b)
_hook = lambda stage: None


def _fsync_dir(path):
    fd = os.open(os.path.dirname(os.path.abspath(path)), os.O_RDONLY)
    try:
        _fsync(fd)
    finally:
        os.close(fd)


class _Lock:
    """Lock on a SEPARATE stable file, never the ledger (its inode changes on replace)."""
    def __init__(self, path):
        self.p = path + ".lock"

    def __enter__(self):
        self.fd = os.open(self.p, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)


def _validate(d):
    if not isinstance(d, dict) or d.get("version") != VERSION:
        raise LedgerError("bad schema/version")
    g = d.get("global_cap")
    if not (isinstance(g, int) and not isinstance(g, bool) and g >= 0):
        raise LedgerError("bad global_cap")
    rc = d.get("run_caps", {})
    if not isinstance(rc, dict) or any(
            not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in rc.values()):
        raise LedgerError("bad run_caps")
    ents = d.get("entries")
    if not isinstance(ents, list):
        raise LedgerError("entries not a list")
    seen = set()
    for e in ents:
        if not isinstance(e, dict) or e.get("state") not in STATES:
            raise LedgerError("bad entry/state")
        u = e.get("id")
        if not isinstance(u, str) or u in seen:
            raise LedgerError("missing/duplicate reservation id")
        try:
            uuid.UUID(u)
        except ValueError:
            raise LedgerError("id not a uuid")
        seen.add(u)
        if not isinstance(e.get("run"), str):
            raise LedgerError("entry without run scope")
        st = e["state"]
        if st != "reserved" and "started_utc" not in e:
            raise LedgerError("state without started_utc")
        if st == "completed" and "completed_utc" not in e:
            raise LedgerError("completed without ts")
    c = d.get("counts")
    if c != _counts(ents):
        raise LedgerError("counts disagree with entries")
    if any(v < 0 for v in c["global"].values()):
        raise LedgerError("negative count")
    for k in ("last_call_epoch", "rate_reset_until_epoch"):
        v = d.get(k)
        if v is not None and not (isinstance(v, (int, float)) and math.isfinite(v) and v >= 0):
            raise LedgerError("bad " + k)
    if d["counts"]["global"]["spent"] > g:
        raise LedgerError("spent exceeds global_cap (tampered/cap lowered)")
    return d


def _counts(ents):
    def zero():
        return {s: 0 for s in STATES} | {"spent": 0}
    out = {"global": zero(), "runs": {}}
    for e in ents:
        for sc in (out["global"], out["runs"].setdefault(e["run"], zero())):
            sc[e["state"]] += 1
            sc["spent"] += 1   # every reservation consumes budget
    return out


def _load(path):
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        raise LedgerError(
            f"ledger {path} missing; explicit init_ledger() required (no implicit fresh start)")
    if not raw.strip():
        raise LedgerError("ledger empty; failing closed")
    try:
        d = json.loads(raw)
    except Exception:
        raise LedgerError("ledger corrupt; failing closed")
    return _validate(d)


def _store(path, d):
    d["counts"] = _counts(d["entries"])
    _validate(d)
    # preserve existing permission metadata across the replace
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        mode = 0o600
    tmp = f"{path}.tmp.{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.fchmod(fd, mode)
        _hook("tmp_opened")
        with os.fdopen(fd, "w") as f:
            json.dump(d, f)
            f.flush()
            _hook("tmp_written")
            _fsync(f.fileno())
        _hook("tmp_fsynced")
        _replace(tmp, path)
        _hook("replaced")
        _fsync_dir(path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def init_ledger(path, global_cap, run_caps=None):
    """Only way to create a ledger. Refuses to overwrite ANY existing file."""
    with _Lock(path):
        if os.path.lexists(path):
            raise LedgerError("ledger exists; refusing re-init")
        _store(path, {"version": VERSION, "global_cap": global_cap,
                      "run_caps": run_caps or {}, "entries": []})


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def reserve(path, run, min_interval=0.0, now=None):
    """Durably record a reservation BEFORE any transport. Returns (uuid, wait_s)."""
    with _Lock(path):
        d = _load(path)
        now = now or time.time()
        _sweep_dead(d)
        c = d["counts"]
        if c["global"]["spent"] >= d["global_cap"]:
            raise LedgerError("global budget exhausted")
        cap = d["run_caps"].get(run)
        if cap is not None and c["runs"].get(run, {}).get("spent", 0) >= cap:
            raise LedgerError(f"run budget exhausted: {run}")
        wait = 0.0
        if d.get("last_call_epoch") and min_interval > 0:
            wait = max(wait, min_interval - (now - d["last_call_epoch"]))
        if d.get("rate_reset_until_epoch"):
            wait = max(wait, d["rate_reset_until_epoch"] - now)
        wait = max(0.0, wait)
        rid = str(uuid.uuid4())
        d["entries"].append({
            "id": rid, "run": run, "state": "reserved", "pid": os.getpid(),
            "reserved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))})
        d["last_call_epoch"] = now + wait
        _store(path, d)          # raises => no request may be sent
        return rid, wait


def _sweep_dead(d):
    """Owner died mid-flight: reserved stays (never sent, still counted);
    transport_started -> unknown."""
    for e in d["entries"]:
        if e["state"] == "transport_started" and not _pid_alive(e.get("pid", -1)):
            e["state"] = "unknown"
            e["note"] = "owner exited without completion"


def transition(path, rid, new, extra=None):
    with _Lock(path):
        d = _load(path)
        for e in d["entries"]:
            if e["id"] == rid:
                if new not in NEXT[e["state"]]:
                    raise LedgerError(f"illegal {e['state']}->{new}")
                e["state"] = new
                ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                if new == "transport_started":
                    e["started_utc"] = ts
                if new == "completed":
                    e["completed_utc"] = ts
                    e.update(extra or {})
                if new == "unknown":
                    e["note"] = (extra or {}).get("note", "transport error, outcome ambiguous")
                _store(path, d)
                return
        raise LedgerError("unknown reservation id")


# Intended call order in the executor's api() (integration, NOT done here):
#   rid, wait = reserve(path, run); sleep(wait);
#   transition(path, rid, "transport_started")   # durable BEFORE the request
#   ... perform request ...
#   success -> transition(path, rid, "completed", {"http": status})
#   failure/exception -> transition(path, rid, "unknown")
# No refunds: every consumed reservation stays consumed.


def summary(path):
    with _Lock(path):
        return _load(path)["counts"]
