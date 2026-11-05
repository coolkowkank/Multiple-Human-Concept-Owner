"""Operator-side DONE-quality hook (generic, offline-tested).

The bus status "done" only means the role CYCLE completed (cycle_complete).
terminal_done additionally needs externally produced, signed quality
evidence for the exact committed artifact. This module never runs a
checker and never sees the checker's code: the operator runs their own
(private) check outside the lane and the seats, and passes the signed
result here. A seat cannot produce it because the HMAC key lives only in
the operator process (never in a seat env, the lane repo or a message).

Records this module writes carry gate_enforced=True ONLY when evaluate_done
ran against signed external evidence bound to the artifact that is
committed at the recorded HEAD. Any cycle that finished without this call
keeps gate_enforced=false (historical runs stay false).

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
    state = Bus(repo, branch).state()
    cycle_complete = state.get("status") == "done"
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
        "cycle_complete": cycle_complete,
        "quality": ev.get("quality"), "terminal_done": ev.get("terminal_done") is True,
        "reasons": ev.get("reasons", []),
        "expected_operator_checker_id": expected_operator_checker_id,
        "gate_enforced": enforced and ev.get("terminal_done") is True,
        "note": "bounded operator evidence, not proof of correctness; "
                "a checker for one function is not general quality",
    }
    tmp = record_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=2, sort_keys=True); fh.write("\n")
        fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, record_path)
    return rec
