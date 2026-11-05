"""Operator-side DONE-quality hook (generic, offline-tested).

The bus status "done" only means the role CYCLE completed (cycle_complete).
terminal_done additionally needs externally produced, signed quality
evidence for the exact committed artifact. This module never runs a
checker and never sees the checker's code: the operator runs their own
(private) check outside the lane and the seats, and passes the signed
result here. A seat cannot produce it because the HMAC key lives only in
the operator process (never in a seat env, the lane repo or a message).

Records this module writes carry operator_terminal_check_passed=True ONLY when evaluate_done
ran against signed external evidence bound to the artifact that is
committed at the recorded HEAD. Any cycle that finished without this call
has no such record (historical runs stay false). The runtime itself still sets bus status done unconditionally (runtime_blocks_done is false in every record); this hook is an operator-called check plus completion_status(), which is what user-facing closeout must use.

Evidence is bounded (an operator check or a mutation gate), not proof of
correctness, and a checker for one function says nothing about general
quality.
"""
import json, os, subprocess

from launcher.bus import Bus
from launcher.quality_gate import artifact_sha256, evaluate_done, HASH_SCHEME

RECORD_SCHEMA = "operator-done-record/v1"
# launcher/quality_gate.py is vendored BYTE-EXACT from the accepted
# live/quality-gate fb8350df817abc589b66aab3dd10bf62b7773c4c.
QUALITY_GATE_MD5 = "9de29c89f52245cacce2f82ed5138c89"


def _verify_pin():
    import hashlib
    got = hashlib.md5(open(os.path.join(os.path.dirname(
        os.path.abspath(__file__)), "launcher", "quality_gate.py"), "rb").read()).hexdigest()
    if got != QUALITY_GATE_MD5:
        raise RuntimeError("vendored launcher/quality_gate.py md5 mismatch")



def committed_files(repo, paths):
    """Exact file contents committed at HEAD for the given repo-relative paths.
    Worktree edits are ignored; missing or unsafe paths raise ValueError."""
    if not paths:
        raise ValueError("artifact path list is empty")
    files = {}
    for p in paths:
        if (not isinstance(p, str) or not p or p.startswith("/")
                or ".." in p.split("/") or "\\" in p):
            raise ValueError("unsafe artifact path")
        r = subprocess.run(["git", "-C", repo, "show", "HEAD:" + p],
                           capture_output=True)
        if r.returncode != 0:
            raise ValueError("artifact path not committed at HEAD: " + p)
        try:
            files[p] = r.stdout.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("artifact file is not utf-8 text: " + p)
    return files


def head_sha(repo):
    return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def current_artifact(repo, paths):
    files = committed_files(repo, paths)
    return files, artifact_sha256(files)


def _cycle_complete_at_head(repo, branch):
    """(cycle_complete, note) from .team/STATE.json COMMITTED at HEAD, and
    only if HEAD is on the expected branch. Never the worktree file."""
    cur = subprocess.run(["git", "-C", repo, "rev-parse", "--abbrev-ref", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    if cur != branch:
        return False, "HEAD is on %r, expected %r" % (cur, branch)
    r = subprocess.run(["git", "-C", repo, "show", "HEAD:.team/STATE.json"],
                       capture_output=True)
    if r.returncode != 0:
        return False, "no committed .team/STATE.json at HEAD"
    try:
        st = json.loads(r.stdout.decode("utf-8"))
    except ValueError:
        return False, "committed STATE.json is not JSON"
    return (isinstance(st, dict) and st.get("status") == "done"), None


def operator_close(repo, branch, artifact_paths, signed_operator_result, *,
                   operator_key, expected_operator_checker_id, record_path):
    """Evaluate terminal DONE and write the record. Returns the record.

    cycle_complete is read from the bus (status == done), never from seat
    text. The artifact hash is computed here from the committed files, never
    taken from the evidence. The key is only used for verification and is
    never written."""
    _verify_pin()
    if os.path.exists(record_path) or os.path.islink(record_path):
        raise FileExistsError("record already exists; refusing to overwrite")
    repo = os.path.abspath(repo)
    rp = os.path.realpath(record_path)
    if rp.startswith(os.path.realpath(repo) + os.sep):
        raise ValueError("record path must be outside the lane repo")
    head0 = head_sha(repo)
    cycle_complete, state_note = _cycle_complete_at_head(repo, branch)
    try:
        files, sha = current_artifact(repo, artifact_paths)
        err = None
    except ValueError as exc:
        files, sha, err = {}, None, str(exc)
    ev = evaluate_done(
        cycle_complete, None, None, sha,
        signed_operator_result,
        operator_key=operator_key,
        expected_operator_checker_id=expected_operator_checker_id)
    if head_sha(repo) != head0:   # lane moved while evaluating: do not trust
        ev = dict(ev); ev["terminal_done"] = False
        ev["reasons"] = list(ev.get("reasons", [])) + ["HEAD moved during evaluation"]
    enforced = bool(sha) and signed_operator_result is not None and err is None
    rec = {
        "schema": RECORD_SCHEMA,
        "head": head0, "hash_scheme": HASH_SCHEME,
        "artifact_sha256": sha, "artifact_paths": sorted(files),
        "artifact_error": err,
        "cycle_complete": cycle_complete, "cycle_complete_note": state_note,
        "runtime_blocks_done": False,
        "quality": ev.get("quality"), "terminal_done": ev.get("terminal_done") is True,
        "reasons": ev.get("reasons", []),
        "expected_operator_checker_id": expected_operator_checker_id,
        "operator_terminal_check_passed": enforced and ev.get("terminal_done") is True,
        "note": "bounded operator evidence, not proof of correctness; "
                "a checker for one function is not general quality",
    }
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(record_path)),
                               prefix=".rec-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2, sort_keys=True); fh.write("\n")
            fh.flush(); os.fsync(fh.fileno())
        os.link(tmp, record_path)   # fails if anything (even a symlink) is there
    except FileExistsError:
        raise FileExistsError("record already exists; refusing to overwrite") from None
    finally:
        try: os.unlink(tmp)
        except OSError: pass
    return rec


def completion_status(repo, branch, record_path):
    """What user-facing closeout must use. Returns cycle_complete and
    terminal_done SEPARATELY; closeout_allowed is true only when a record
    exists whose head equals the current HEAD, whose artifact hash still
    matches the committed files, and which passed the operator terminal
    check. Anything missing, stale or unreadable is not allowed."""
    cc, note = _cycle_complete_at_head(os.path.abspath(repo), branch)
    out = {"cycle_complete": cc, "terminal_done": False, "closeout_allowed": False,
           "label": "cycle complete, quality unproven" if cc else "cycle not complete",
           "reason": note}
    try:
        with open(record_path, encoding="utf-8") as fh:
            rec = json.load(fh)
        if rec.get("schema") != RECORD_SCHEMA:
            raise ValueError("unknown record schema")
        if rec.get("head") != head_sha(os.path.abspath(repo)):
            out["reason"] = "record is for a different HEAD"; return out
        _, sha = current_artifact(os.path.abspath(repo), rec.get("artifact_paths") or [])
        if sha != rec.get("artifact_sha256"):
            out["reason"] = "artifact changed since the record"; return out
        if cc and rec.get("terminal_done") is True and rec.get("operator_terminal_check_passed") is True:
            out.update(terminal_done=True, closeout_allowed=True,
                       label="operator terminal check passed (bounded evidence, not proof)", reason=None)
        else:
            out["reason"] = "record does not show a passed terminal check"
    except (OSError, ValueError):
        out["reason"] = out["reason"] or "no usable operator record"
    return out
