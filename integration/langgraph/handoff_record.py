"""handoff/v1: a runtime-observed handoff record, kept apart from model claims.

PURE module (stdlib only, imports nothing from launcher). Not wired into the
runtime: the integration contract is at the bottom of this docstring.

FACTS vs CLAIMS
- `facts` hold only what the runtime itself observed and passes in: the bus
  HEAD it started from, the paths its own git capture found changed AFTER the
  verify command ran and BEFORE the commit (with mode and blob id), the exit
  code of the subprocess it ran, and the validated next seat.
- `claims` hold model-written text only as length + sha256 (+ labelled
  heuristic flags). The text itself stays where it already is (log body,
  STATE status_line). A claim is never evidence and is never merged into facts.

WHAT THE RECORD PROVES AND WHAT IT DOES NOT  (also stored in every record as
`evidence_limits`)
- It binds a commit to the file set and blob ids the runtime observed on disk
  after verify. It does NOT prove those are the files the model declared:
  `undeclared` lists observed paths the model did not declare, and a verify
  command can change files, so the observation is post-verify by construction.
- It does NOT prove the verify exit code means the tests passed: the command
  is chosen by the model and a subprocess controls its own exit code and
  output. Only the command's sha256/length and the tail's sha256 are kept.
- gitignored paths are not observed. Pre-existing dirty paths are reported
  (`preexisting_dirty`), and the seat commit (git add -A) sweeps them in.
- A commit cannot contain its own hash, so `head` is not in the record;
  check_commit() binds record.base -> commit afterwards, read-only.
- A missing record is NEVER accepted evidence: row_evidence() returns
  "no_record". A cap never truncates: an over-cap list becomes a count + a
  sha256 over the full canonical list (recomputable from the commit) and the
  record says listed=false; if it still cannot fit, building fails.

INTEGRATION CONTRACT (implementation lane; none of this is done here)
 bus.transact has NO rollback (only transact_paths restores), so nothing here may raise inside
 a transaction to "undo" writes, and a reporting failure must never trigger a replay.
 1. Capture is bounded (MAX_ENTRIES=200 paths, MAX_FILE_BYTES per file, one hashing subprocess).
    Use safe_capture(repo) -> ("ok", entries) | ("no_record", code); it never raises.
 2. After verify, once the seat's writes are done: safe_capture, then safe_build({...}). base and
    turn_seq are those of THIS attempt as supplied by the runtime.
 3. On ("ok", rec): append_log(..., record=rec) as an additive key on the kind=handoff row.
    On ("no_record", code): append_log(..., **no_record_fields(code)). The turn proceeds as
    normal: no raise, no restore, no retry, no replay of the model call because of reporting.
 4. The only error surface is a fixed code from ERROR_CODES: never a path, exception text or model text.
 5. Gate files and any other path under .team/ except the two BUS_FILES are ordinary observed
    paths: they appear as observed, and as `undeclared` unless the seat declared them. Only the
    two bus files are excluded.
 6. Verifiers call row_evidence(row) and check_commit(repo, commit, record). no_record, with or
    without record_error, is NEVER accepted evidence.
 7. prompt_log_tail renders only ts/seat/kind/body, so no prompt and no audit prompt hash changes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess

SCHEMA = "handoff/v1"
BUS_FILES = (".team/STATE.json", ".team/LOG.jsonl")
MAX_RECORD_BYTES = 4096
MAX_INLINE = 40
MAX_PATH = 512
MAX_ENTRIES = 200          # hard cap on observed paths: a handoff touching more is refused (no_record), never partly recorded
MAX_FILE_BYTES = 8 * 1024 * 1024   # per-file read bound for hashing
EVIDENCE_LIMITS = [
    "observed = worktree vs base after verify and before commit; bus files STATE.json/LOG.jsonl excluded",
    "gitignored paths are not observed",
    "verify command is model-chosen; exit code is not proof tests passed; only command and tail hashes kept",
    "head is not recorded (a commit cannot contain its own hash); use check_commit",
    "claims are model text kept as length+sha256 only and are not evidence",
]
FLAGS = ("claims_pass_without_passing_verify",)     # heuristic string match, labelled as such
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_STATUS = ("A", "M", "D", "T")
_MODES = ("100644", "100755", "120000")
_SEAT = re.compile(r"^[A-Za-z0-9._:@-]{1,128}$")
_PASS_WORDS = re.compile(r"\b(pass(ed|es)?|green|all tests)\b", re.I)


def _sha(text):
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def path_ok(p):
    if not isinstance(p, str) or not p or len(p) > MAX_PATH or p.startswith("/") or "\\" in p:
        return False
    if any(ord(c) < 32 or ord(c) == 127 for c in p):
        return False
    parts = p.split("/")
    return all(x not in ("", ".", "..") for x in parts) and parts[0] != ".git"


def entry_ok(e):
    return (isinstance(e, dict) and set(e) == {"path", "status", "mode", "blob"} and path_ok(e["path"])
            and e["status"] in _STATUS and e["mode"] in _MODES
            and ((e["status"] == "D" and e["blob"] is None) or (e["status"] != "D" and isinstance(e["blob"], str) and bool(_HEX40.match(e["blob"])))))


def _list_form(items, key=None):
    """Deterministic list-or-digest. Never truncates: past MAX_INLINE it is digest only."""
    ordered = sorted(items, key=key) if key else sorted(items)
    form = {"count": len(ordered), "digest": hashlib.sha256(_canon(ordered).encode()).hexdigest(), "listed": len(ordered) <= MAX_INLINE}
    if form["listed"]:
        form["items"] = ordered
    return form


def _verify_facts(v):
    if v is None or v.get("ran") is not True:
        return {"ran": False, "exit_code": None, "sandboxed": None, "command_sha256": None, "command_len": None, "tail_lines": None, "tail_sha256": None}
    cmd, tail = v.get("command"), v.get("tail") or ""
    return {"ran": True, "exit_code": v.get("exit_code"), "sandboxed": v.get("sandboxed"),
            "command_sha256": _sha(cmd) if isinstance(cmd, str) else None,
            "command_len": len(cmd) if isinstance(cmd, str) else None,
            "tail_lines": len(tail.splitlines()) if isinstance(tail, str) else None,
            "tail_sha256": _sha(tail) if isinstance(tail, str) else None}


def _all_listed(rec):
    return all(rec["facts"][k]["listed"] for k in ("observed", "declared_writes", "undeclared", "preexisting_dirty"))


def build_record(obs):
    """obs is supplied by the runtime. Returns (record, errors); record is None on any error."""
    errs = []
    if not isinstance(obs, dict):
        return None, ["observation is not an object"]
    seat, seq, base = obs.get("seat"), obs.get("turn_seq"), obs.get("base")
    if not (isinstance(seat, str) and _SEAT.match(seat)): errs.append("seat invalid")
    if not (_int(seq) and 0 <= seq < 10 ** 9): errs.append("turn_seq invalid")
    if not (isinstance(base, str) and _HEX40.match(base)): errs.append("base is not a full 40-hex commit id")
    nxt = obs.get("next")
    if nxt is not None and not (isinstance(nxt, str) and _SEAT.match(nxt)): errs.append("next invalid")
    if not isinstance(obs.get("status"), str) or not obs["status"] or len(obs["status"]) > 32: errs.append("status invalid")
    if not isinstance(obs.get("gate_opened"), bool): errs.append("gate_opened must be a bool")
    if not _int(obs.get("correction_rounds")) or not 0 <= obs["correction_rounds"] < 1000: errs.append("correction_rounds invalid")
    declared = obs.get("declared_writes")
    if not isinstance(declared, list) or not all(path_ok(p) for p in declared) or len(set(declared)) != len(declared): errs.append("declared_writes: invalid or duplicate path")
    entries = obs.get("observed")
    if not isinstance(entries, list) or len(entries) > MAX_ENTRIES or not all(entry_ok(e) for e in entries):
        errs.append("observed: invalid entry")
    elif len({e["path"] for e in entries}) != len(entries): errs.append("observed: duplicate path")
    elif any(e["path"] in BUS_FILES for e in entries): errs.append("observed must exclude the bus files")
    pre = obs.get("preexisting_dirty")
    if not isinstance(pre, list) or not all(path_ok(p) for p in pre) or len(set(pre)) != len(pre): errs.append("preexisting_dirty: invalid or duplicate path")
    v = obs.get("verify")
    if v is not None:
        if not isinstance(v, dict) or not isinstance(v.get("ran"), bool): errs.append("verify invalid")
        elif v["ran"] and not (_int(v.get("exit_code")) and -255 <= v["exit_code"] <= 255): errs.append("verify.exit_code must be an int in [-255,255] when ran")
        elif v["ran"] and not isinstance(v.get("sandboxed"), bool): errs.append("verify.sandboxed must be a bool when ran")
        elif v["ran"] and not isinstance(v.get("command"), str): errs.append("verify.command must be a string when ran")
    summary, status_line = obs.get("summary"), obs.get("status_line")
    for name, val in (("summary", summary), ("status_line", status_line)):
        if val is not None and not isinstance(val, str): errs.append(f"{name} must be a string or null")
    if errs:
        return None, errs
    decl = set(declared)
    obs_paths = {e["path"] for e in entries}
    vf = _verify_facts(v)
    flags = []
    text = " ".join(t for t in (summary, status_line) if t)
    if _PASS_WORDS.search(text) and not (vf["ran"] and vf["exit_code"] == 0):
        flags.append(FLAGS[0])
    def mk(inline):
        return {
            "schema": SCHEMA,
            "facts": {
                "seat": seat, "turn_seq": seq, "base": base, "next": nxt, "status": obs["status"],
                "gate_opened": obs["gate_opened"], "correction_rounds": obs["correction_rounds"],
                "verify": vf,
                "declared_writes": _list_form(declared) if inline else _digest_only(declared),
                "observed": _list_form(entries, key=lambda e: e["path"]) if inline else _digest_only(entries, key=lambda e: e["path"]),
                "undeclared": _list_form(sorted(obs_paths - decl)) if inline else _digest_only(sorted(obs_paths - decl)),
                "preexisting_dirty": _list_form(pre) if inline else _digest_only(pre),
            },
            "claims": {"summary_len": len(summary) if summary is not None else None, "summary_sha256": _sha(summary) if summary is not None else None,
                       "status_line_len": len(status_line) if status_line is not None else None, "status_line_sha256": _sha(status_line) if status_line is not None else None,
                       "flags": flags, "flags_basis": "heuristic string match; never evidence"},
            "evidence_limits": list(EVIDENCE_LIMITS),
        }
    rec = mk(True)
    if len(encode(rec)) > MAX_RECORD_BYTES:
        rec = mk(False)
    if len(encode(rec)) > MAX_RECORD_BYTES:
        return None, [f"record exceeds {MAX_RECORD_BYTES} bytes even in digest-only form; refusing instead of truncating"]
    return rec, []


def _digest_only(items, key=None):
    f = _list_form(items, key)
    f["listed"] = False; f.pop("items", None)
    return f


def encode(rec):
    return _canon(rec).encode()


def _validate_list(name, f, item_ok, key):
    errs = []
    if not isinstance(f, dict) or set(f) - {"count", "digest", "listed", "items"} or not {"count", "digest", "listed"} <= set(f):
        return [f"{name}: bad shape"]
    if not (_int(f["count"]) and 0 <= f["count"] <= MAX_ENTRIES) or not (isinstance(f["digest"], str) and _HEX64.match(f["digest"])) or not isinstance(f["listed"], bool):
        return [f"{name}: bad count/digest/listed"]
    if f["listed"]:
        items = f.get("items")
        if not isinstance(items, list) or len(items) != f["count"] or f["count"] > MAX_INLINE or not all(item_ok(i) for i in items):
            return [f"{name}: listed items invalid or count mismatch"]
        if items != sorted(items, key=key) or len({_canon(i) if isinstance(i, dict) else i for i in items}) != len(items):
            errs.append(f"{name}: items not sorted/unique")
        if hashlib.sha256(_canon(items).encode()).hexdigest() != f["digest"]:
            errs.append(f"{name}: digest does not match the listed items")
    elif "items" in f:
        errs.append(f"{name}: items present while listed=false")
    return errs


def validate_record(rec):
    """Strict schema check; returns a list of problems (empty = well formed, NOT = true)."""
    if not isinstance(rec, dict) or set(rec) != {"schema", "facts", "claims", "evidence_limits"} or rec.get("schema") != SCHEMA:
        return ["not a handoff/v1 record"]
    if rec["evidence_limits"] != EVIDENCE_LIMITS:
        return ["evidence_limits missing or altered"]
    if len(encode(rec)) > MAX_RECORD_BYTES:
        return [f"record larger than {MAX_RECORD_BYTES} bytes"]
    f, c = rec["facts"], rec["claims"]
    keys = {"seat", "turn_seq", "base", "next", "status", "gate_opened", "correction_rounds", "verify", "declared_writes", "observed", "undeclared", "preexisting_dirty"}
    if not isinstance(f, dict) or set(f) != keys:
        return ["facts: unexpected or missing keys"]
    errs = []
    if not (isinstance(f["seat"], str) and _SEAT.match(f["seat"])): errs.append("seat")
    if not (_int(f["turn_seq"]) and 0 <= f["turn_seq"] < 10 ** 9): errs.append("turn_seq")
    if not (isinstance(f["base"], str) and _HEX40.match(f["base"])): errs.append("base")
    if f["next"] is not None and not (isinstance(f["next"], str) and _SEAT.match(f["next"])): errs.append("next")
    if not isinstance(f["status"], str) or not f["status"] or len(f["status"]) > 32: errs.append("status")
    if not isinstance(f["gate_opened"], bool): errs.append("gate_opened")
    if not (_int(f["correction_rounds"]) and 0 <= f["correction_rounds"] < 1000): errs.append("correction_rounds")
    v = f["verify"]
    vkeys = {"ran", "exit_code", "sandboxed", "command_sha256", "command_len", "tail_lines", "tail_sha256"}
    if not isinstance(v, dict) or set(v) != vkeys or not isinstance(v["ran"], bool):
        errs.append("verify shape")
    elif v["ran"]:
        if not (_int(v["exit_code"]) and -255 <= v["exit_code"] <= 255): errs.append("verify.exit_code")
        if not isinstance(v["sandboxed"], bool): errs.append("verify.sandboxed")
        for k in ("command_sha256", "tail_sha256"):
            if not (isinstance(v[k], str) and _HEX64.match(v[k])): errs.append(f"verify.{k}")
        if not (_int(v["command_len"]) and v["command_len"] >= 0 and _int(v["tail_lines"]) and v["tail_lines"] >= 0): errs.append("verify lengths")
    elif any(v[k] is not None for k in vkeys - {"ran"}):
        errs.append("verify: fields set while ran=false")
    errs += _validate_list("declared_writes", f["declared_writes"], path_ok, lambda x: x)
    errs += _validate_list("observed", f["observed"], entry_ok, lambda e: e["path"] if isinstance(e, dict) else "")
    errs += _validate_list("undeclared", f["undeclared"], path_ok, lambda x: x)
    errs += _validate_list("preexisting_dirty", f["preexisting_dirty"], path_ok, lambda x: x)
    ckeys = {"summary_len", "summary_sha256", "status_line_len", "status_line_sha256", "flags", "flags_basis"}
    if not isinstance(c, dict) or set(c) != ckeys:
        errs.append("claims: unexpected or missing keys")
    else:
        if not isinstance(c["flags"], list) or any(x not in FLAGS for x in c["flags"]): errs.append("claims.flags")
        for a, b in (("summary_len", "summary_sha256"), ("status_line_len", "status_line_sha256")):
            if (c[a] is None) != (c[b] is None) or (c[a] is not None and not (_int(c[a]) and c[a] >= 0 and isinstance(c[b], str) and _HEX64.match(c[b]))): errs.append(f"claims.{a}")
    return errs


def row_evidence(row):
    """('record_ok'|'no_record'|'invalid_record', problems) for a LOG row. No record is never ok."""
    if not isinstance(row, dict) or row.get("kind") != "handoff":
        return "invalid_record", ["not a handoff row"]
    if "record" not in row or row["record"] is None:
        code = row.get("record_error")
        return "no_record", ["handoff row carries no record: not evidence" + (f" (record_error={code})" if code in ERROR_CODES else "")]
    probs = validate_record(row["record"])
    if not probs:
        f = row["record"]["facts"]
        if f["seat"] != row.get("seat"): probs.append("record seat differs from the row seat")
        if "turn_seq" in row and f["turn_seq"] != row["turn_seq"]: probs.append("record turn_seq differs from the row turn_seq")
    return ("invalid_record", probs) if probs else ("record_ok", [])


# ---------------------------------------------------------------- git (read-only)
def _git(repo, *args, inp=None):
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True, input=inp, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    return p.returncode, p.stdout


class CaptureRefused(ValueError):
    """capture could not represent the worktree exactly. .code is a fixed, sanitized token (no paths, no text)."""
    def __init__(self, code):
        super().__init__(code); self.code = code


ERROR_CODES = ("capture_no_head", "capture_git_failed", "capture_too_many_entries", "capture_unrepresentable",
               "capture_file_too_large", "capture_hash_failed", "build_invalid", "build_too_large", "capture_error")


def _lstat_kind(repo, rel):
    full = os.path.join(repo, rel)
    st = os.lstat(full)
    if stat.S_ISLNK(st.st_mode):
        return "120000", full
    if not stat.S_ISREG(st.st_mode):
        raise CaptureRefused("capture_unrepresentable")
    if st.st_size > MAX_FILE_BYTES:
        raise CaptureRefused("capture_file_too_large")
    return ("100755" if st.st_mode & 0o111 else "100644"), full


def capture_worktree(repo):
    """Read-only: paths whose worktree state differs from HEAD (tracked changes incl. staged, plus
    untracked non-ignored files), each with status/mode/blob. Bus files excluded.
    Cost is bounded: more than MAX_ENTRIES paths, a file over MAX_FILE_BYTES, or anything not exactly
    representable (submodule, special file, undecodable path) raises CaptureRefused(code) BEFORE any
    hashing; it never returns partial facts. Regular files are hashed in ONE git subprocess
    (hash-object --stdin-paths, same filters as git add, no -w); symlinks by target in-process."""
    rc, head = _git(repo, "rev-parse", "--verify", "HEAD")
    if rc != 0:
        raise CaptureRefused("capture_no_head")
    out = {}
    rc, raw = _git(repo, "diff", "--raw", "-z", "--no-renames", "--no-abbrev", "HEAD")
    if rc != 0:
        raise CaptureRefused("capture_git_failed")
    parts = raw.split(b"\0")
    i = 0
    try:
        while i + 1 < len(parts) and parts[i]:
            meta, path = parts[i].decode(), parts[i + 1].decode("utf-8", "strict")
            i += 2
            out[path] = meta.split()[4][0]
        rc, un = _git(repo, "ls-files", "--others", "--exclude-standard", "-z")
        if rc != 0:
            raise CaptureRefused("capture_git_failed")
        for p in un.split(b"\0"):
            if p:
                out[p.decode("utf-8", "strict")] = "A"
    except (UnicodeDecodeError, IndexError):
        raise CaptureRefused("capture_unrepresentable")
    paths = sorted(p for p in out if p not in BUS_FILES)
    if len(paths) > MAX_ENTRIES:
        raise CaptureRefused("capture_too_many_entries")
    entries, to_hash = [], []
    for path in paths:
        # git hash-object --stdin-paths C-unquotes a leading double quote: refuse, never hash a different file
        if not path_ok(path) or out[path] not in _STATUS or path.startswith('"'):
            raise CaptureRefused("capture_unrepresentable")
        st = out[path]
        if st == "D":
            rc, tree = _git(repo, "ls-tree", "HEAD", "--", path)
            mode = tree.split()[0].decode() if tree.strip() else "100644"
            entries.append({"path": path, "status": "D", "mode": mode if mode in _MODES else "100644", "blob": None})
            continue
        try:
            mode, full = _lstat_kind(repo, path)
        except OSError:
            raise CaptureRefused("capture_unrepresentable")
        if mode == "120000":
            data = os.readlink(full).encode()
            blob = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
            entries.append({"path": path, "status": st, "mode": mode, "blob": blob})
        else:
            entries.append({"path": path, "status": st, "mode": mode, "blob": None})
            to_hash.append(path)
    if to_hash:
        rc, hashed = _git(repo, "hash-object", "--stdin-paths", inp=("\n".join(to_hash) + "\n").encode())
        lines = hashed.decode().split()
        if rc != 0 or len(lines) != len(to_hash) or not all(_HEX40.match(x) for x in lines):
            raise CaptureRefused("capture_hash_failed")
        by = dict(zip(to_hash, lines))
        for e in entries:
            if e["path"] in by:
                e["blob"] = by[e["path"]]
    return entries


def safe_capture(repo):
    """('ok', entries) or ('no_record', code). Never raises; code is one of ERROR_CODES (no paths, no text)."""
    try:
        return "ok", capture_worktree(repo)
    except CaptureRefused as e:
        return "no_record", e.code
    except Exception:
        return "no_record", "capture_error"


def safe_build(obs):
    """('ok', record) or ('no_record', code). Never raises; the error text is dropped, only a fixed code survives."""
    try:
        rec, errs = build_record(obs)
    except Exception:
        return "no_record", "build_invalid"
    if rec is not None:
        return "ok", rec
    return "no_record", "build_too_large" if any("exceeds" in x for x in errs) else "build_invalid"


def no_record_fields(code):
    """additive LOG-row keys for a handoff whose record could not be made. Not evidence."""
    return {"record": None, "record_error": code if code in ERROR_CODES else "capture_error"}


def check_commit(repo, commit, rec):
    """Read-only. Returns {'status': 'match'|'mismatch'|'unverifiable', 'problems': [...]}.
    'match' means: commit's single parent is rec.base, its changed non-bus paths equal what the
    runtime observed (status, mode, blob), and STATE.json at the commit has the record's turn_seq
    and next. It does NOT mean tests passed or that the declared writes were the only changes."""
    probs = validate_record(rec)
    if probs:
        return {"status": "mismatch", "problems": ["record invalid: " + p for p in probs]}
    if not (isinstance(commit, str) and _HEX40.match(commit)):
        return {"status": "unverifiable", "problems": ["commit must be a full 40-hex id"]}
    f = rec["facts"]
    rc, out = _git(repo, "rev-list", "--parents", "-n", "1", commit)
    if rc != 0 or not out.strip():
        return {"status": "unverifiable", "problems": ["commit not found in this repository"]}
    ids = out.decode().split()
    if len(ids) != 2:
        return {"status": "mismatch", "problems": [f"commit must have exactly one parent (has {len(ids) - 1})"]}
    if ids[1] != f["base"]:
        return {"status": "mismatch", "problems": ["commit parent is not record.base"]}
    rc, raw = _git(repo, "diff-tree", "-r", "-z", "--raw", "--no-renames", "--no-abbrev", ids[1], commit)
    if rc != 0:
        return {"status": "unverifiable", "problems": ["git diff-tree failed"]}
    parts = raw.split(b"\0"); got = []; i = 0
    while i + 1 < len(parts) and parts[i]:
        m = parts[i].decode().lstrip(":").split()
        path = parts[i + 1].decode("utf-8", "replace"); i += 2
        if path in BUS_FILES:
            continue
        st = m[4][0]
        newmode, newblob = m[1], m[3]
        got.append({"path": path, "status": st, "mode": (m[0] if st == "D" else newmode), "blob": None if st == "D" else newblob})
    got.sort(key=lambda e: e["path"])
    o = f["observed"]
    problems = []
    if o["listed"]:
        want = o["items"]
        gp, wp = {e["path"]: e for e in got}, {e["path"]: e for e in want}
        for p in sorted(set(gp) - set(wp)): problems.append(f"committed but not observed: {p}")
        for p in sorted(set(wp) - set(gp)): problems.append(f"observed but not committed: {p}")
        for p in sorted(set(gp) & set(wp)):
            if gp[p] != wp[p]: problems.append(f"differs from observation (status/mode/blob): {p}")
    else:
        if len(got) != o["count"] or hashlib.sha256(_canon(got).encode()).hexdigest() != o["digest"]:
            problems.append("committed non-bus changes do not match the observed digest")
    rc, st = _git(repo, "show", f"{commit}:.team/STATE.json")
    try:
        state = json.loads(st.decode()) if rc == 0 else None
    except ValueError:
        state = None
    if not isinstance(state, dict):
        problems.append("STATE.json at the commit is missing or unreadable")
    else:
        if state.get("turn_seq") != f["turn_seq"]: problems.append("STATE.json turn_seq differs from the record")
        if state.get("turn") != f["next"]: problems.append("STATE.json turn differs from record.next")
    return {"status": "mismatch" if problems else "match", "problems": problems}


def pin_check(reviewed_commit, reviewer_record):
    """R4, callable only (not a gate): a reviewer/qc record is pinned to `reviewed_commit` when its
    base is that commit and its own verify ran with an int exit code. Returns problems; empty = pinned.
    base is the bus HEAD when the reviewer's turn applied, so it equals the reviewed commit only if
    nothing landed in between."""
    probs = validate_record(reviewer_record)
    if probs:
        return ["record invalid"] + probs
    f = reviewer_record["facts"]
    out = []
    if not (isinstance(reviewed_commit, str) and _HEX40.match(reviewed_commit)): out.append("reviewed_commit must be a full 40-hex id")
    elif f["base"] != reviewed_commit: out.append("reviewer record base is not the reviewed commit")
    if not f["verify"]["ran"]: out.append("reviewer record has no verify run of its own")
    return out
