"""Fenced single-request HTTP adapter for the LangGraph seat boundary.

Replaces the project's generic HttpAdapter on this path (the runtime
builds an HttpAdapter from the spec; langgraph_team swaps it for this
class before any call, so the generic adapter never sends anything).

Properties (each has a test in http_fence_test.py):
- ONE request per complete(); no retries, no backoff.
- Durable reserve line is written (flock + fsync) BEFORE the request. A
  crash, malformed 200, timeout or socket error leaves the reserve in
  place, so the attempt stays counted across restarts.
- Redirects are never followed (a 3xx is an error), so the Authorization
  header cannot be forwarded to another host. System proxies are ignored.
- Lifetime cap across ALL log files in the fixed log directory
  (HTTP_LIFETIME_CAP): changing the epoch/path cannot reset it. Deleting
  the log directory still resets it - operator-level, not prevented here.
- Log lines are hash-chained; a broken chain refuses further calls.
  Tail truncation is NOT detected.
- Response must report an explicit numeric cost of exactly 0, else the
  adapter halts (a halt line blocks all later calls). The pre-call basis
  is only the fixed host plus the exact model allowlist (listing fact).
- Error text never includes provider bodies; logs hold only attempt
  number, model, status class, sanitized usage numbers. No key, no
  prompt, no completion text.
"""
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request

from launcher.adapters import Adapter, AdapterError, parse_response

HTTP_LOG_DIR = os.path.join(os.path.expanduser("~"), ".lg-http-usage")
HTTP_LIFETIME_CAP = 10   # 8 -> 10, forward-only: 8 historic + at most 2 new
MAX_BODY = 2_000_000
EPOCH_RE = re.compile(r"^[a-z0-9-]{1,32}$")
USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens", "cost")


def log_path(model, epoch):
    slug = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")
    return os.path.join(HTTP_LOG_DIR, f"{slug}.{epoch}.jsonl")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                       _NoRedirect())


def _num_ok(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v) and v >= 0)


CONTROL_NAME = "_control.ctl"
FLOOR_PROVENANCE = "operator-reported from transcript; original chain not recovered"
_LOG_NAME = re.compile(r"^[a-z0-9-]+\.[a-z0-9-]{1,32}\.jsonl$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _isint(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def read_control(dirpath):
    """Typed control lines (hash-chained) in dir/_control.ctl. Read-only.
    -> {"problems": [...], "floor": int, "floor_line": dict|None,
        "windows": [dict], "tip": sha|"0"}. Any problem means the caller
    must refuse; nothing here repairs or guesses. A missing or empty file
    is "no import, no window" (floor 0).
    Kinds: 'historic-floor' (first and only once: count of reserves from
    a chain that was NOT recovered, typed as operator-reported, with how
    many are unknown vs settled and which epoch files it covers) and
    'window-open' (see open_window)."""
    out = {"problems": [], "floor": 0, "floor_line": None, "windows": [],
           "tip": "0", "tips_ok": True, "burnt": 0}
    p = os.path.join(dirpath, CONTROL_NAME)
    if not os.path.lexists(p):
        return out
    try:
        st = os.lstat(p)
        if not os.path.isfile(p) or os.path.islink(p) or st.st_size > 1_000_000:
            out["problems"].append("control file is not a plain small file")
            return out
        data = open(p, "rb").read()
    except OSError:
        out["problems"].append("control file unreadable")
        return out
    if data and not data.endswith(b"\n"):
        out["problems"].append("control file has a partial last line")
    prev, nonces = "0", set()
    for i, raw in enumerate(data.split(b"\n")):
        if not raw.strip():
            continue
        try:
            e = json.loads(raw)
        except ValueError:
            out["problems"].append("control line %d is not JSON" % (i + 1))
            break
        if not isinstance(e, dict) or e.get("prev") != prev:
            out["problems"].append("control chain broken at line %d" % (i + 1))
            break
        prev = hashlib.sha256(raw.rstrip(b"\n")).hexdigest()
        k = e.get("kind")
        if k == "historic-floor":
            cf = e.get("covered_files")
            if i != 0 or out["floor_line"] is not None:
                out["problems"].append("historic-floor must be the first and only floor line")
            elif not (_isint(e.get("count"), 0, 1000)
                      and _isint(e.get("unknown"), 0, 1000)
                      and _isint(e.get("settled"), 0, 1000)
                      and e["unknown"] + e["settled"] == e["count"]
                      and e.get("provenance") == FLOOR_PROVENANCE
                      and isinstance(cf, list) and len(cf) <= 64
                      and all(isinstance(x, str) and _LOG_NAME.match(x) for x in cf)
                      and len(set(cf)) == len(cf)):
                out["problems"].append("malformed historic-floor line")
            else:
                out["floor"], out["floor_line"] = e["count"], e
        elif k in ("window-open", "window-burn"):
            ok = ((k == "window-open" and isinstance(e.get("owner_hash"), str) and bool(_HEX64.match(e["owner_hash"]))
                   or k == "window-burn" and isinstance(e.get("supersedes"), bool))
                  and _isint(e.get("seq"), 1, 10 ** 6) and e["seq"] == len(out["windows"]) + 1
                  and _isint(e.get("k"), 0 if k == "window-burn" else 1, HTTP_LIFETIME_CAP)
                  and _isint(e.get("base"), 0, 10 ** 6)
                  and isinstance(e.get("nonce"), str) and _HEX64.match(e["nonce"])
                  and e["nonce"] not in nonces
                  and all(isinstance(e.get(f), str) and _HEX64.match(e[f])
                          for f in ("config_hash", "receipt_hash"))
                  and isinstance(e.get("prev_receipt_hash"), str)
                  and (e["prev_receipt_hash"] == "0" or _HEX64.match(e["prev_receipt_hash"]))
                  and isinstance(e.get("tips"), dict)
                  and all(_LOG_NAME.match(str(a)) and isinstance(b, str) and (b == "0" or _HEX64.match(b))
                          for a, b in e["tips"].items())
                  and (not out["windows"] or e["base"] >= out["windows"][-1]["base"]
                       and e["prev_receipt_hash"] == out["windows"][-1]["receipt_hash"])
                  and (out["windows"] or e["prev_receipt_hash"] == "0"))
            if not ok:
                out["problems"].append("malformed or out-of-sequence window-open line %d" % (i + 1))
            else:
                nonces.add(e["nonce"]); out["windows"].append(e)
                if k == "window-burn":
                    out["burnt"] += e["k"]
        else:
            out["problems"].append("unknown control kind at line %d" % (i + 1))
        if out["problems"]:
            break
    out["tip"] = prev
    return out


def _fsync_dir(dirpath):
    fd = os.open(dirpath, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _append_control(dirpath, entry):
    """Caller holds the dir lock. Appends one chained control line, fsync."""
    c = read_control(dirpath)
    if c["problems"]:
        raise FenceRefused("control file invalid; refusing")
    e = dict(entry, prev=c["tip"])
    p = os.path.join(dirpath, CONTROL_NAME)
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        before = os.fstat(fd).st_size
        os.write(fd, (json.dumps(e, sort_keys=True) + "\n").encode())
        os.fsync(fd)
        _fsync_dir(dirpath)
        c2 = read_control(dirpath)
        if c2["problems"]:       # invalid line: take it back out before anyone else reads it
            os.ftruncate(fd, before); os.fsync(fd)
            raise FenceRefused("control line rejected: " + c2["problems"][0][:80])
    finally:
        os.close(fd)


class _DirLock:
    """Directory-level exclusive flock (one lock for ALL epoch files and
    the control file), so cross-file counting and the append are atomic
    across processes. Lock file is the control file itself (empty = no
    import)."""
    def __init__(self, dirpath):
        os.makedirs(dirpath, mode=0o700, exist_ok=True)
        self.fd = os.open(os.path.join(dirpath, CONTROL_NAME), os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX)

    def close(self):
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def import_historic_floor(dirpath, count, unknown, settled, covered_files, *, external_manifest_present):
    """One-time, offline import of the operator-REPORTED count of reserves
    from a chain that was lost. It forges no old hash chain and does not
    claim the old log was recovered: the line carries a fixed provenance
    string. Refused if any control line or any log already exists (so it
    can only be the first thing in a fresh ledger dir). Never called by a
    runtime path. Unknown stays unknown: 'unknown' calls count as spent.
    external_manifest_present is REQUIRED and must be the orchestrator's
    verified answer to "does the private File already hold a ledger
    manifest/bundle?". True refuses: a fresh dir plus a fresh floor would
    otherwise reset a ledger that exists elsewhere (use restore). The fence
    cannot check this itself; it is a single-writer, no-CAS procedure."""
    if external_manifest_present is not False:
        raise FenceRefused("external manifest present or unknown; restore, do not re-import a floor")
    with _DirLock(dirpath):
        if os.path.getsize(os.path.join(dirpath, CONTROL_NAME)) or any(
                f.endswith(".jsonl") for f in os.listdir(dirpath)):
            raise FenceRefused("ledger dir is not fresh; floor import refused")
        _append_control(dirpath, {"kind": "historic-floor", "count": count,
                                  "unknown": unknown, "settled": settled,
                                  "covered_files": sorted(covered_files),
                                  "provenance": FLOOR_PROVENANCE})
        c = read_control(dirpath)
        if c["problems"]:
            os.truncate(os.path.join(dirpath, CONTROL_NAME), 0)
            raise FenceRefused("floor line malformed; nothing imported")


WINDOW_TOKEN_ENV = "FENCE_WINDOW_TOKEN"
WINDOW_GATE = True     # every reserve must fall inside an open, verified window
WINDOW_REFUSALS = ("no window open", "window exhausted", "ledger rolled back")


def _log_scan(dirpath):
    """-> (reserves_in_logs, halted, ok, {file: set(line sha256)}, {file: tip})."""
    res, halted, ok, hs, tips = 0, False, True, {}, {}
    for fn in sorted(os.listdir(dirpath)) if os.path.isdir(dirpath) else []:
        if not fn.endswith(".jsonl"):
            continue
        prev, seen = "0", set()
        for raw in open(os.path.join(dirpath, fn), "rb"):
            if not raw.strip():
                continue
            try:
                e = json.loads(raw)
                if e.get("prev") != prev:
                    ok = False
            except ValueError:
                ok = False; e = {}
            prev = hashlib.sha256(raw.rstrip(b"\n")).hexdigest()
            seen.add(prev)
            res += e.get("phase") == "reserve"
            halted = halted or e.get("phase") == "halt"
        hs[fn], tips[fn] = seen, prev
    return res, halted, ok, hs, tips


def window_status(dirpath, check_token=True):
    """Read-only. -> (ok, why, info). ok means the LAST window is open,
    its history is intact (every recorded log tip is still a line hash of
    its file, total reserves never fell below the window base) and
    reserves-in-window < K. Never repairs."""
    c = read_control(dirpath)
    if c["problems"]:
        return False, "control file invalid", {}
    if not c["windows"]:
        return False, "no window open", {}
    w = c["windows"][-1]
    if w["kind"] == "window-burn":
        return False, "no window open", {}
    committed = c["floor"] + sum(x["k"] for x in c["windows"]
                                 if not (x["kind"] == "window-burn" and x["supersedes"]))
    if committed > HTTP_LIFETIME_CAP:
        return False, "committed liability exceeds the cap; future use halted", {}
    if check_token:
        tok = os.environ.get(WINDOW_TOKEN_ENV)
        if not tok or hashlib.sha256(tok.encode()).hexdigest() != w["owner_hash"]:
            return False, "window owner token missing or wrong (stale or foreign use)", {}
    res, halted, ok, hs, tips = _log_scan(dirpath)
    if not ok:
        return False, "usage log chain broken", {}
    total = res + c["floor"] + c["burnt"]
    for w2 in c["windows"]:
        for fn, tip in w2["tips"].items():
            if tip != "0" and tip not in hs.get(fn, set()):
                return False, "ledger rolled back or rewritten (recorded tip missing in %s)" % fn, {}
    if total < w["base"]:
        return False, "ledger rolled back (total below window base)", {}
    used = total - w["base"]
    info = {"seq": w["seq"], "k": w["k"], "used": used, "total": total, "halted": halted}
    if used >= w["k"]:
        return False, "window exhausted", info
    return True, "", info


def open_window(dirpath, k, nonce, config_hash, receipt_hash, prev_receipt_hash, owner_hash):
    """Record a window-open line. Offline/orchestrator-side: the CALLER
    must already have durably written the pending-window receipt (hash
    given here) to private storage BEFORE calling this and before any
    spawn; the fence cannot verify that upload (no network, no tools
    CLI). Refused when: a log chain or control is bad, a halt exists, the
    floor + the K of every window opened so far + this K exceeds the
    lifetime cap (each window's planned K is burnt whether or not it was
    spent), the nonce was used, or the receipt chain does not continue."""
    with _DirLock(dirpath):
        c = read_control(dirpath)
        if c["problems"]:
            raise FenceRefused("control file invalid; refusing")
        res, halted, ok, hs, tips = _log_scan(dirpath)
        if not ok or halted:
            raise FenceRefused("ledger not clean; refusing to open a window")
        committed = c["floor"] + sum(w["k"] for w in c["windows"]
                                     if not (w["kind"] == "window-burn" and w["supersedes"]))
        if committed + k > HTTP_LIFETIME_CAP:
            raise FenceRefused("window K exceeds the remaining lifetime cap")
        if c["windows"] and c["windows"][-1]["kind"] == "window-open":
            # an unclosed window still holds liability (its unspent K): it must be
            # typed-closed (burn_window) first, never silently replaced
            raise FenceRefused("previous window is not closed; close or burn it first")
        if c["windows"]:
            okw, why, _ = window_status(dirpath)
            if not okw and why != "no window open":
                raise FenceRefused("previous window unusable: " + why)
        _append_control(dirpath, {"kind": "window-open", "seq": len(c["windows"]) + 1,
                                  "k": k, "base": res + c["floor"] + c["burnt"], "nonce": nonce,
                                  "config_hash": config_hash, "receipt_hash": receipt_hash,
                                  "prev_receipt_hash": prev_receipt_hash, "tips": tips,
                                  "owner_hash": owner_hash})
        c2 = read_control(dirpath)
        if c2["problems"]:
            raise FenceRefused("window line rejected: " + c2["problems"][0])


def burn_window(dirpath, nonce, config_hash, receipt_hash, prev_receipt_hash, *,
                pending_k=None):
    """Recovery after a lost ledger. Appends a 'window-burn' line that
    counts calls as SPENT-UNKNOWN and closes any open window:
    - pending_k=None: supersede the last OPEN window; burns its remaining
      K - used (the run may have made reserves we can no longer see).
    - pending_k=K: a pending-window receipt exists in private storage but
      no window line survived (crash after the receipt upload, before or
      after open_window, ledger lost). The whole K is burnt and counts
      toward the lifetime cap.
    Nothing is erased or replayed; a burn is never undone."""
    with _DirLock(dirpath):
        c = read_control(dirpath)
        if c["problems"]:
            raise FenceRefused("control file invalid; refusing")
        res, halted, ok, hs, tips = _log_scan(dirpath)
        if not ok:
            raise FenceRefused("ledger chain broken; refusing")
        total = res + c["floor"] + c["burnt"]
        if pending_k is None:
            if not c["windows"] or c["windows"][-1]["kind"] != "window-open":
                raise FenceRefused("no open window to supersede")
            w = c["windows"][-1]
            k = max(0, w["k"] - max(0, total - w["base"]))
            sup = True
        else:
            k, sup = pending_k, False
            # genuine pending liability is ALWAYS recorded, even past the cap; the fence then
            # halts future use (window_status: committed > cap) instead of erasing accounting
        _append_control(dirpath, {"kind": "window-burn", "seq": len(c["windows"]) + 1,
                                  "k": k, "base": total, "nonce": nonce,
                                  "config_hash": config_hash, "receipt_hash": receipt_hash,
                                  "prev_receipt_hash": prev_receipt_hash, "supersedes": sup,
                                  "tips": tips})


def ledger_summary(dirpath):
    """The ONE accounting formula (readers and tests use this).
    spent     = log reserves + historic floor + burnt K (spent-unknown)
    committed = floor + K of every window-open + K of every NON-superseding
                burn (a pending receipt burnt whole). A superseding burn is
                the unspent remainder of a window already counted in
                committed, so it is in 'spent' but never added to
                'committed' again (no double count).
    Invariants: spent <= committed (a window cannot spend beyond its K);
    when the last window is closed/burnt, spent == committed (nothing
    forgotten: every committed K is accounted as spent or burnt);
    committed <= HTTP_LIFETIME_CAP is reported as over_cap, NOT as inconsistency:
    real liability stays recorded even if the cap constant is later lowered,
    and the fence halts future use instead (window_status)."""
    c = read_control(dirpath)
    if c["problems"]:
        return {"ok": False, "problems": c["problems"]}
    res, halted, ok, hs, tips = _log_scan(dirpath)
    spent = res + c["floor"] + c["burnt"]
    committed = c["floor"] + sum(w["k"] for w in c["windows"]
                                 if not (w["kind"] == "window-burn" and w["supersedes"]))
    last_open = bool(c["windows"]) and c["windows"][-1]["kind"] == "window-open"
    consistent = (ok and spent <= committed + 0
                  and (last_open or not c["windows"] or spent == committed))
    if not c["windows"]:
        consistent = bool(ok)
    return {"ok": ok, "log_reserves": res, "historic_floor": c["floor"], "burnt_unknown": c["burnt"],
            "spent": spent, "committed": committed, "windows": [
                {"seq": w["seq"], "kind": w["kind"], "k": w["k"], "supersedes": w.get("supersedes")}
                for w in c["windows"]], "last_window_open": last_open, "consistent": bool(consistent),
            "over_cap": committed > HTTP_LIFETIME_CAP,
            "halted": halted}


def _read_all(dirpath):
    """-> (reserves_total, halted, chain_ok) over every log in the dir,
    plus the typed historic floor from the control file. An invalid
    control file makes chain_ok False."""
    reserves, halted, ok = 0, False, True
    if not os.path.isdir(dirpath):
        return 0, False, True
    ctl = read_control(dirpath)
    if ctl["problems"]:
        ok = False
    reserves = ctl["floor"] + ctl["burnt"]     # imported floor and burnt windows count as spent
    for fn in sorted(os.listdir(dirpath)):
        if not fn.endswith(".jsonl"):
            continue
        prev = "0"
        with open(os.path.join(dirpath, fn), "rb") as fh:
            for raw in fh:
                if not raw.strip():
                    continue
                try:
                    e = json.loads(raw)
                    if e.get("prev") != prev:
                        ok = False
                except ValueError:
                    ok = False
                    e = {}
                prev = hashlib.sha256(raw.rstrip(b"\n")).hexdigest()
                if e.get("phase") == "reserve":
                    reserves += 1
                if e.get("phase") == "halt":
                    halted = True
    return reserves, halted, ok


class FenceRefused(AdapterError):
    """Raised BEFORE the reserve line is written: nothing was reserved
    and no request was made (known not-sent). Still an AdapterError with
    the same message complete() always used."""


class Reservation:
    """One shared reserve line, identified by a random rid and bound to
    the canonical log path (model + epoch) and n. Single use, enforced
    twice: an in-process lock around the used flag, and DURABLY in the
    log: execute() appends a hash-chained `exec` claim under the log
    flock BEFORE any I/O and refuses a rid that already has an exec,
    exec-refused or result line. States seen in the log for one rid:
    reserve only = the fence never started a request (consumed, known
    not sent by this fence); reserve+exec-refused = refused before start;
    reserve+exec without result = started, outcome unknown (never
    re-executed); reserve+exec+result = settled."""
    def __init__(self, model, n, rid, path):
        self.model, self.n, self.rid, self.path = model, n, rid, path
        self.used = False
        self.lock = threading.Lock()


def reserve_states(dirpath=None):
    """{key: state} over the shared log dir. Only a reserve written by
    the explicit reserve()/execute() protocol (via=reserve) can be
    'reserved-not-started'. Other states: refused-before-start,
    started-unsettled, settled. A reserve written by complete()
    (via=complete) or a legacy line with no via marker could have sent a
    request without leaving an exec line, so until a result exists it is
    'unknown-complete-path' / 'unknown-legacy', never not-started. Legacy
    lines without a rid are keyed 'legacy:<file>:<n>'."""
    out, d = {}, dirpath or HTTP_LOG_DIR
    if not os.path.isdir(d):
        return out
    ctl = read_control(d)
    fl = ctl["floor_line"]
    if fl:       # typed, never 'not-started': operator-reported, original chain not recovered
        for i in range(fl["unknown"]):
            out["floor-unknown:%d" % i] = "historic-unknown"
        for i in range(fl["settled"]):
            out["floor-settled:%d" % i] = "historic-settled"
    for w in ctl["windows"]:
        if w["kind"] == "window-burn":
            for i in range(w["k"]):
                out["burn:%d:%d" % (w["seq"], i)] = "burnt-unknown"
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".jsonl"):
            continue
        for raw in open(os.path.join(d, fn), "rb"):
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            ph = e.get("phase")
            key = e.get("rid") or "legacy:%s:%s" % (fn, e.get("n"))
            if ph == "reserve":
                via = e.get("via")
                out[key] = ("reserved-not-started" if via == "reserve"
                            else "unknown-complete-path" if via == "complete"
                            else "unknown-legacy")
            elif ph == "exec-refused" and out.get(key) == "reserved-not-started":
                out[key] = "refused-before-start"
            elif ph == "exec" and out.get(key) == "reserved-not-started":
                out[key] = "started-unsettled"
            elif ph == "result" and key in out:
                out[key] = "settled"
    return out


class _LogHandle:
    """Log file plus the held directory lock; close() releases both."""
    def __init__(self, fh, dl):
        self._fh, self._dl = fh, dl
        self.seek, self.read, self.write = fh.seek, fh.read, fh.write
        self.flush, self.fileno = fh.flush, fh.fileno

    def close(self):
        try:
            self._fh.close()
        finally:
            self._dl.close()


class FencedHttpAdapter(Adapter):
    REPORTS_PROVIDER_USAGE = True

    def __init__(self, base_url, model, api_key_env, epoch, call_budget,
                 max_tokens, timeout, reasoning_effort, opener=None):
        if not EPOCH_RE.match(str(epoch)):
            raise AdapterError("bad log epoch")
        self.base_url, self.model = base_url.rstrip("/"), model
        self.api_key_env, self.epoch = api_key_env, epoch
        self.call_budget, self.max_tokens = call_budget, max_tokens
        self.timeout, self.effort = timeout, reasoning_effort
        self.path = log_path(model, epoch)
        self._opener = opener or _opener()
        self.last_call = None

    def _append(self, fh, entry):
        fh.seek(0)
        data = fh.read()
        lines = [l for l in data.split(b"\n") if l.strip()]
        prev = hashlib.sha256(lines[-1]).hexdigest() if lines else "0"
        entry = dict(entry, prev=prev)
        fh.seek(0, os.SEEK_END)
        fh.write((json.dumps(entry, sort_keys=True) + "\n").encode())
        fh.flush()
        os.fsync(fh.fileno())

    def _open_log(self):
        os.makedirs(HTTP_LOG_DIR, mode=0o700, exist_ok=True)   # private: reserve_preflight refuses group/other-accessible dirs
        dl = _DirLock(HTTP_LOG_DIR)        # one directory-level lock first, then the file lock
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
            fh = os.fdopen(fd, "r+b")
            fcntl.flock(fh, fcntl.LOCK_EX)    # exclusive writer
        except BaseException:
            dl.close(); raise
        return _LogHandle(fh, dl)

    def complete(self, system, prompt):
        r = self._core(system, prompt)
        if r["cost_halt"]:
            raise AdapterError("cost not reported as exactly zero; halted")
        if r["text"] is None:
            raise AdapterError("no usable response (%s)" % r["cls"])
        return self._parse(r["text"])

    # ---- raw path: reserve() then execute(token), used by the runner lane
    def reserve(self):
        """Run every pre-request check (key present, chain, halt, cap,
        per-model budget) and write the shared reserve line under the log
        lock. Raises FenceRefused (nothing written, known not-sent) or
        returns a single-use Reservation. No request is made here."""
        if not os.environ.get(self.api_key_env):
            raise FenceRefused("missing API key env var")
        rid = secrets.token_hex(8)
        fh = self._open_log()
        try:
            n = self._check_and_reserve(fh, rid, "reserve")
        finally:
            fh.close()
        return Reservation(self.model, n, rid, self.path)

    def execute(self, token, system, prompt):
        """Make the ONE request for a Reservation from reserve() and
        settle it in the log. Returns the raw transport result:
        {kind, code, content, usage, cost_signal, cls, n, finish_reason}.
        kind 'ok' = HTTP 200, usable content, explicit zero cost; 'http'
        = a 4xx status; 'unknown' = redirect, 5xx, malformed/empty 200,
        timeout, socket error, or any other post-reserve outcome. A
        nonzero or invalid cost (200, or in a bounded error body) writes
        a shared halt. Raw HTTP success is not parsed-JSON success.
        The reserve is the only authority: a used, forged, foreign or
        already-settled token raises FenceRefused with no request. The
        log lock is NOT held across the request here (complete() holds
        it); a concurrent process can therefore append its own lines
        meanwhile, and a halt written meanwhile does not cancel this
        already-reserved request."""
        if not isinstance(token, Reservation) or token.model != self.model \
                or token.path != self.path:
            raise FenceRefused("reservation unusable")
        with token.lock:                       # in-process check-and-set
            if token.used:
                raise FenceRefused("reservation unusable")
            token.used = True
        key = os.environ.get(self.api_key_env)
        fh = self._open_log()                  # claim under the log flock
        try:
            seen, vias = set(), set()
            for l in open(self.path, "rb"):
                try:
                    e = json.loads(l)
                except ValueError:
                    continue
                if e.get("rid") == token.rid:
                    seen.add(e.get("phase"))
                    if e.get("phase") == "reserve":
                        vias.add(e.get("via"))
            why = None
            if "reserve" not in seen or vias != {"reserve"}:
                why = "reservation not in the log"
                seen.discard("reserve")
            elif seen & {"exec", "exec-refused", "result"}:
                raise FenceRefused("reservation already claimed or settled")
            elif not key:
                why = "missing API key env var"
            else:
                total, halted, chain_ok = _read_all(HTTP_LOG_DIR)
                if not chain_ok:
                    why = "usage log chain broken; refusing"
                elif halted:
                    why = "adapter halted earlier; refusing"
                elif WINDOW_GATE:
                    okw, whyw, _ = window_status(HTTP_LOG_DIR)
                    if not okw and whyw != "window exhausted":
                        why = whyw     # exhausted is fine here: this reserve may be the last one
            if why:
                if "reserve" in seen:
                    self._append(fh, {"phase": "exec-refused",
                                      "rid": token.rid, "n": token.n,
                                      "why": why[:60]})
                raise FenceRefused(why)
            self._append(fh, {"phase": "exec", "rid": token.rid,
                              "n": token.n, "model": self.model})
        finally:
            fh.close()
        io = self._io(key, system, prompt)
        fh = self._open_log()
        try:
            r = self._record(fh, token.n, io, halt_on_err_cost=True,
                             rid=token.rid)
        finally:
            fh.close()
        return self._raw_result(r)

    def _raw_result(self, r):
        code, cls = r["code"], r["cls"]
        if r["cost_halt"]:
            cs = "nonzero" if (r["usage"] or {}).get("cost") else "invalid"
            kind = "ok" if r["text"] is not None else "unknown"
        elif cls == "http" and code is not None and 400 <= code < 500:
            kind, cs = "http", r["err_cost"]
        elif cls in ("http", "redirect"):    # 5xx, 3xx: outcome unknown
            kind, cs = "unknown", r["err_cost"]
        elif r["text"] is not None:
            kind, cs = "ok", "zero"
        else:
            kind, cs = "unknown", ("zero" if r["usage"] and
                                   r["usage"].get("cost") == 0 else None)
        if r["err_cost"] in ("nonzero", "invalid"):
            cs = r["err_cost"]
        return {"kind": kind, "code": code or 0, "content": r["text"] or "",
                "usage": r["usage"], "cost_signal": cs, "cls": cls,
                "finish_reason": r["finish_reason"], "n": r["n"]}

    # ---- shared pieces (complete() uses all three, behavior unchanged)
    def _check_and_reserve(self, fh, rid, via):
        total, halted, chain_ok = _read_all(HTTP_LOG_DIR)
        if not chain_ok:
            raise FenceRefused("usage log chain broken; refusing")
        if WINDOW_GATE:
            okw, whyw, _ = window_status(HTTP_LOG_DIR)
            if not okw:
                raise FenceRefused(whyw[:80])
        if halted:
            raise FenceRefused("adapter halted earlier; refusing")
        ctl = read_control(HTTP_LOG_DIR)
        fl = ctl["floor_line"]
        if fl and os.path.basename(self.path) in fl["covered_files"]:
            raise FenceRefused("epoch file is covered by the historic floor; new epoch required")
        mine = sum(1 for l in open(self.path, "rb")
                   if b'"phase": "reserve"' in l)
        if mine >= self.call_budget or total >= HTTP_LIFETIME_CAP:
            raise FenceRefused("request budget exhausted; refusing")
        n = mine + 1
        self._append(fh, {"phase": "reserve", "n": n, "rid": rid, "via": via,
                          "model": self.model})   # BEFORE any I/O
        return n

    def _io(self, key, system, prompt):
        cls, usage, code, text = "unknown", None, None, None
        err_cost, fin = None, None
        try:
            payload = {"model": self.model,
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": prompt}],
                       "max_completion_tokens": self.max_tokens,
                       "reasoning_effort": self.effort}
            req = urllib.request.Request(
                self.base_url + "/chat/completions",
                data=json.dumps(payload).encode(), method="POST",
                headers={"content-type": "application/json",
                         "authorization": "Bearer " + key,
                         "user-agent": "lg-fenced-http/0.1"})
            try:
                with self._opener.open(req, timeout=self.timeout) as r:
                    code = r.status
                    raw = r.read(MAX_BODY + 1)
            except urllib.error.HTTPError as e:
                code = e.code
                cls = "redirect" if 300 <= e.code < 400 else "http"
                raw = None
                try:    # bounded read, cost signal only (no text kept)
                    buf, dl = b"", time.monotonic() + 5
                    while len(buf) < 2000 and time.monotonic() < dl:
                        c = e.read(min(256, 2000 - len(buf)))
                        if not c:
                            break
                        buf += c
                    eb = json.loads(buf)
                    eu = eb.get("usage") if isinstance(eb, dict) else None
                    if isinstance(eu, dict) and "cost" in eu:
                        err_cost = ("invalid" if not _num_ok(eu["cost"])
                                    else "zero" if eu["cost"] == 0
                                    else "nonzero")
                except Exception:
                    pass
            if raw is not None:
                if code != 200 or len(raw) > MAX_BODY:
                    cls = "bad-status-or-size"
                else:
                    d = json.loads(raw)
                    u = d.get("usage") if isinstance(d, dict) else None
                    if isinstance(u, dict):
                        usage = {k: u[k] for k in USAGE_KEYS
                                 if k in u and _num_ok(u[k])}
                    cls = "ok-shape"
                    fr = d["choices"][0].get("finish_reason")
                    fin = fr if fr in ("stop", "length", "content_filter",
                                       "tool_calls", "function_call",
                                       "error") else None
                    ch = d["choices"][0]["message"]["content"]
                    if not isinstance(ch, str) or not ch.strip():
                        cls = "empty-content"
                    else:
                        text = ch
        except Exception as e:   # malformed body, timeout, socket, shape
            if cls == "unknown":
                cls = "error:" + type(e).__name__
        return {"cls": cls, "usage": usage, "code": code, "text": text,
                "err_cost": err_cost, "finish_reason": fin}

    def _record(self, fh, n, io, halt_on_err_cost=False, rid=None):
        cls, usage, code, text = io["cls"], io["usage"], io["code"], io["text"]
        cost = (usage or {}).get("cost")
        cost_known_zero = cost == 0 and isinstance(cost, (int, float))
        outcome = {"phase": "result", "n": n, "rid": rid,
                   "model": self.model,
                   "status": code, "class": cls, "usage": usage,
                   "cost_zero": bool(cost_known_zero)}
        self._append(fh, outcome)
        if code == 200 and usage:
            # the request happened and the provider reported usage:
            # keep that evidence even if the reply is unusable or the
            # cost check below halts (never reads as "no call")
            self.last_call = {"origin": "provider", "response_id": None,
                              "usage": usage}
        res = {"n": n, "code": code, "cls": cls, "usage": usage,
               "text": text, "cost_halt": False,
               "err_cost": io["err_cost"], "finish_reason": io["finish_reason"]}
        if code == 200 and not cost_known_zero:
            self._append(fh, {"phase": "halt", "n": n,
                              "why": "cost missing or nonzero"})
            res["cost_halt"] = True
            return res
        if halt_on_err_cost and io["err_cost"] in ("nonzero", "invalid"):
            self._append(fh, {"phase": "halt", "n": n,
                              "why": "error-body cost nonzero or invalid"})
        if text is not None:
            self.last_call = {"origin": "provider", "response_id": None,
                              "usage": usage}
        return res

    def _core(self, system, prompt):
        self.last_call = None
        key = os.environ.get(self.api_key_env)
        if not key:
            raise FenceRefused("missing API key env var")
        fh = self._open_log()
        try:
            rid = secrets.token_hex(8)
            n = self._check_and_reserve(fh, rid, "complete")
        finally:
            fh.close()          # locks are NOT held across provider I/O
        io = self._io(key, system, prompt)
        fh = self._open_log()   # reacquire to record the result
        try:
            return self._record(fh, n, io, rid=rid)
        finally:
            fh.close()

    def _parse(self, text):
        try:
            return parse_response(text)
        except AdapterError as exc:
            # no raw model text in the error (it reaches traces) and no
            # raw= attribute (nothing is preserved from this adapter).
            # A contract-format failure keeps the runtime's exact
            # prefix so its ONE bounded format-correction round can
            # fire; the per-seat call_budget still caps total requests.
            if str(exc).startswith("model output is not JSON"):
                raise AdapterError(
                    "model output is not JSON: the reply was not one "
                    "bare object or one json fence (raw text withheld "
                    "by the fenced adapter)") from None
            raise AdapterError("response is not the required "
                               "structured format") from None
