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
        "signed_operator_result": signed_operator_result,
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


def _private_parent(path):
    d = os.path.dirname(os.path.abspath(path))
    if os.path.islink(d):
        return "record directory is a symlink"
    st = os.lstat(d)
    if st.st_uid != os.getuid() or (st.st_mode & 0o077):
        return "record directory must be owned by this user with mode 0700"
    return None


def completion_status(repo, branch, record_path, artifact_paths, *,
                      operator_key, expected_operator_checker_id):
    """What user-facing closeout must use. The record's own flags are NEVER
    trusted: the stored signed operator result is re-verified here with the
    operator key and re-evaluated by evaluate_done against the artifact hash
    recomputed now from the committed files. artifact_paths comes from the
    CALLER (operator config) and must equal the record's list, so a record
    cannot choose a smaller file set. Missing/bad key, bad signature, other
    HEAD, other checker, other paths, replay on a changed artifact: not allowed.
    cycle_complete and terminal_done are returned separately."""
    repo = os.path.abspath(repo)
    cc, note = _cycle_complete_at_head(repo, branch)
    out = {"cycle_complete": cc, "terminal_done": False, "closeout_allowed": False,
           "label": "cycle complete, quality unproven" if cc else "cycle not complete",
           "reason": note}
    try:
        _verify_pin()
        bad = _private_parent(record_path)
        if bad:
            out["reason"] = bad; return out
        if os.path.islink(record_path):
            out["reason"] = "record is a symlink"; return out
        with open(record_path, encoding="utf-8") as fh:
            rec = json.load(fh)
        if rec.get("schema") != RECORD_SCHEMA:
            raise ValueError("unknown record schema")
        if sorted(artifact_paths or []) != rec.get("artifact_paths"):
            out["reason"] = "artifact path list differs from the record"; return out
        if rec.get("head") != head_sha(repo):
            out["reason"] = "record is for a different HEAD"; return out
        _, sha = current_artifact(repo, artifact_paths)
        ev = evaluate_done(cc, None, None, sha, rec.get("signed_operator_result"),
                           operator_key=operator_key,
                           expected_operator_checker_id=expected_operator_checker_id)
        if ev.get("terminal_done") is True:
            out.update(terminal_done=True, closeout_allowed=True, reason=None,
                       label="operator terminal check passed (bounded evidence, not proof)")
        else:
            out["reason"] = "; ".join(ev.get("reasons") or ["evidence not accepted"])
    except (OSError, ValueError):
        out["reason"] = out["reason"] or "no usable operator record"
    return out


def _private_file(path):
    """Config/key files: regular file, not a symlink, owned by us, no group/other access."""
    st = os.lstat(path)
    import stat as _s
    if not _s.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ValueError(f"{os.path.basename(path)}: must be a regular file owned by the operator with mode 0600")


def _run_checker(repo, artifact_paths, cmd, timeout):
    """Run the operator's checker on a clean export of the COMMITTED files.
    Child gets a scrubbed env (no keys, no seat env) and never sees the signing
    key; it prints {"accepted": true|false}. NOT a hardened sandbox: it is a
    plain subprocess under the operator's user with a timeout and output cap."""
    import tempfile, shutil
    files = committed_files(repo, artifact_paths)
    d = tempfile.mkdtemp(prefix="lg-export-"); os.chmod(d, 0o700)
    try:
        for rel, content in files.items():
            dst = os.path.join(d, rel); os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "w", encoding="utf-8") as fh: fh.write(content)
        pr = subprocess.run(list(cmd) + [d], cwd=d, stdin=subprocess.DEVNULL,
                            capture_output=True, timeout=timeout,
                            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
        if pr.returncode != 0:
            raise ValueError(f"checker exited {pr.returncode}")
        out = json.loads(pr.stdout[:65536].decode("utf-8"))
        if not isinstance(out, dict) or not isinstance(out.get("accepted"), bool):
            raise ValueError("checker output not {accepted: bool}")
        return out["accepted"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def finalize(repo, branch, config_path):
    """Operator-owned closeout at the END of a run. Default is fail closed:
    no/invalid config, checker failure or timeout = 'cycle complete, quality
    unproven'. Config (JSON, 0600, outside the lane): checker_cmd (absolute
    argv0), checker_id, artifact_paths, key_file (0600), record_dir (0700),
    optional timeout. The signing key is read here only; the checker
    never gets it. The runtime bus DONE is not changed by this."""
    from launcher.quality_gate import sign_operator
    repo = os.path.abspath(repo)
    cc, _ = _cycle_complete_at_head(repo, branch)
    unproven = {"cycle_complete": cc, "terminal_done": False, "closeout_allowed": False,
                "label": "cycle complete, quality unproven" if cc else "cycle not complete"}
    try:
        if not config_path:
            return dict(unproven, reason="no operator config")
        _private_file(config_path)
        cfg = json.load(open(config_path, encoding="utf-8"))
        cmd, cid, paths = cfg["checker_cmd"], cfg["checker_id"], cfg["artifact_paths"]
        if not (isinstance(cmd, list) and cmd and all(isinstance(x, str) for x in cmd)
                and os.path.isabs(cmd[0]) and isinstance(cid, str) and cid
                and isinstance(paths, list) and paths):
            raise ValueError("bad config fields")
        lane = os.path.realpath(repo) + os.sep
        for pth in (config_path, cfg["key_file"], cfg["record_dir"], cmd[0]):
            if (os.path.realpath(pth) + os.sep).startswith(lane) or os.path.realpath(pth) == lane[:-1]:
                raise ValueError("config, key, record dir and checker must be outside the lane")
        _private_file(cfg["key_file"])
        key = open(cfg["key_file"], "rb").read().strip()
        if len(key) < 16:
            raise ValueError("key too short")
        bad = _private_parent(os.path.join(cfg["record_dir"], "x"))
        if bad:
            raise ValueError(bad)
        head = head_sha(repo)
        rec_path = os.path.join(cfg["record_dir"], f"done-{head[:12]}.json")
        if not cc:
            return dict(unproven, reason="cycle not complete; checker not run")
        if not os.path.lexists(rec_path):
            accepted = _run_checker(repo, paths, cmd, min(int(cfg.get("timeout", 60)), 300))
            _, sha = current_artifact(repo, paths)
            sig = sign_operator(key, {"hash_scheme": HASH_SCHEME, "artifact_sha256": sha,
                                      "accepted": accepted,
                                      "state": "accepted" if accepted else "rejected",
                                      "checker_id": cid})
            operator_close(repo, branch, paths, sig, operator_key=key,
                           expected_operator_checker_id=cid, record_path=rec_path)
        return completion_status(repo, branch, rec_path, paths, operator_key=key,
                                 expected_operator_checker_id=cid)
    except Exception as exc:   # fail closed; never echo key material
        return dict(unproven, reason=f"operator finalization failed closed: {type(exc).__name__}: {str(exc)[:120]}")


def main(argv):
    """Public closeout entry point: prints JSON, exit 0 only if closeout is
    allowed. The key is read from a file (never argv/env); keep it outside
    the lane and every seat's reach."""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True); ap.add_argument("--branch", required=True)
    ap.add_argument("--record", required=True); ap.add_argument("--key-file", required=True)
    ap.add_argument("--checker-id", required=True)
    ap.add_argument("--path", action="append", required=True)
    a = ap.parse_args(argv)
    key = open(a.key_file, "rb").read().strip()
    st = completion_status(a.repo, a.branch, a.record, a.path, operator_key=key,
                           expected_operator_checker_id=a.checker_id)
    print(json.dumps(st, sort_keys=True))
    return 0 if st["closeout_allowed"] else 1


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    raise SystemExit(main(sys.argv[1:]))
