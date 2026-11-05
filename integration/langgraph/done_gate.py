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


CHECKER_ID_TAG = b"lg-sandboxed-checker/v1\n"
PROBE = (
    "import os, socket, json\n"
    "r = {}\n"
    "def blocked(path):\n"
    "    try: open(path, 'rb'); return False\n"
    "    except OSError: return True\n"
    "r['paths'] = all(blocked(p) for p in json.loads(os.environ['PROBE_PATHS']) )\n"
    "s = socket.socket(); s.settimeout(2)\n"
    "try: s.connect(('1.1.1.1', 53)); r['net'] = False\n"
    "except OSError: r['net'] = True\n"
    "r['no_home'] = not os.path.exists('/home')\n"
    "print(json.dumps(r))\n")


def checker_id_of(script):
    import hashlib
    return hashlib.sha256(CHECKER_ID_TAG + open(script, "rb").read()).hexdigest()


def _sandbox_cmd(export_dir, script, timeout):
    # bwrap + prlimit; only /usr, the export (ro, as /work), the checker script
    # (ro) and an empty /tmp are visible. No operator dir, key, config, record
    # dir, home or network. Same user, not a kernel-bug boundary.
    return ["/usr/bin/env", "-i", "PATH=/usr/bin:/bin", "prlimit", "--cpu=%d" % max(5, min(timeout, 60)),
            "--as=1073741824", "--nproc=64", "--fsize=4194304", "--",
            "bwrap", "--unshare-all", "--die-with-parent", "--new-session",
            "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib",
            "--symlink", "usr/lib64", "/lib64", "--symlink", "usr/bin", "/bin",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
            "--ro-bind", export_dir, "/work", "--ro-bind", script, "/chk/checker.py",
            "--chdir", "/work", "/usr/bin/python3", "-E", "-s", "-B", "/chk/checker.py", "/work"]


def _bounded_run(cmd, timeout, env, cap_out=65536, cap_err=16384):
    """Streaming read with hard caps; kills the process group on overflow or timeout."""
    import select, signal, time
    pr = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=env, start_new_session=True)
    out, err = b"", b""
    deadline = time.monotonic() + timeout
    fds = {pr.stdout.fileno(): "o", pr.stderr.fileno(): "e"}
    try:
        while fds:
            left = deadline - time.monotonic()
            if left <= 0:
                raise ValueError("checker timed out")
            for fd in select.select(list(fds), [], [], min(left, 0.5))[0]:
                chunk = os.read(fd, 8192)
                if not chunk:
                    fds.pop(fd); continue
                if fds[fd] == "o":
                    out += chunk
                    if len(out) > cap_out: raise ValueError("checker stdout over cap")
                else:
                    err += chunk
                    if len(err) > cap_err: raise ValueError("checker stderr over cap")
        pr.wait(timeout=max(0.1, deadline - time.monotonic()))
    except BaseException:
        try: os.killpg(pr.pid, signal.SIGKILL)
        except OSError: pass
        pr.wait()
        raise
    return pr.returncode, out


def _no_dups(pairs):
    d = {}
    for k, v in pairs:
        if k in d: raise ValueError("duplicate JSON key")
        d[k] = v
    return d


def _run_checker(repo, artifact_paths, script, timeout, protect_paths):
    """Run the operator's checker script on a clean export of the COMMITTED
    files INSIDE bwrap (enforced here, not declared). A probe first proves
    in the same sandbox that the key/config/record paths are unreadable and the
    network is down; any doubt refuses. The checker prints exactly
    {"accepted": true|false}; the parent signs. Same-user bwrap, not a
    hardened boundary against kernel bugs."""
    import tempfile, shutil
    if not os.path.exists("/usr/bin/bwrap"):
        raise ValueError("bwrap not available: refusing to run a checker unsandboxed")
    files = committed_files(repo, artifact_paths)
    d = tempfile.mkdtemp(prefix="lg-export-"); os.chmod(d, 0o700)
    pf = os.path.join(d, ".probe.py")
    try:
        for rel, content in files.items():
            dst = os.path.join(d, rel); os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "w", encoding="utf-8") as fh: fh.write(content)
        with open(pf, "w") as fh: fh.write(PROBE)
        # probe: same sandbox, probe script as the checker; paths passed by bwrap-free env is
        # not possible (env -i), so embed them in the probe source instead
        with open(pf, "w") as fh:
            fh.write(PROBE.replace("os.environ['PROBE_PATHS']", repr(json.dumps(list(protect_paths)))))
        rc, o = _bounded_run(_sandbox_cmd(d, pf, 20), 25, {"PATH": "/usr/bin:/bin"})
        pj = json.loads(o.decode("utf-8"), object_pairs_hook=_no_dups) if rc == 0 else {}
        if pj.get("paths") is not True or pj.get("net") is not True or pj.get("no_home") is not True:
            raise ValueError("sandbox probe failed: refusing to run the checker")
        os.unlink(pf)
        rc, o = _bounded_run(_sandbox_cmd(d, script, timeout), timeout + 5, {"PATH": "/usr/bin:/bin"})
        if rc != 0:
            raise ValueError(f"checker exited {rc}")
        out = json.loads(o.decode("utf-8"), object_pairs_hook=_no_dups)
        if not isinstance(out, dict) or set(out) != {"accepted"} or not isinstance(out["accepted"], bool):
            raise ValueError("checker output not exactly {accepted: bool}")
        return out["accepted"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _finalize_core(repo, branch, config_path):
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
        script, cid, paths = cfg["checker_script"], cfg["checker_id"], cfg["artifact_paths"]
        if not (isinstance(script, str) and os.path.isabs(script) and os.path.isfile(script)
                and not os.path.islink(script) and isinstance(cid, str) and cid
                and isinstance(paths, list) and paths):
            raise ValueError("bad config fields")
        if checker_id_of(script) != cid:
            raise ValueError("checker_id does not match the checker script bytes")
        lane = os.path.realpath(repo) + os.sep
        for pth in (config_path, cfg["key_file"], cfg["record_dir"], script):
            if (os.path.realpath(pth) + os.sep).startswith(lane) or os.path.realpath(pth) == lane[:-1]:
                raise ValueError("config, key, record dir and checker must be outside the lane")
        _private_file(cfg["key_file"])
        key = open(cfg["key_file"], "rb").read()   # exact bytes, no stripping
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
            accepted = _run_checker(repo, paths, script, min(int(cfg.get("timeout", 60)), 300),
                                    [config_path, cfg["key_file"], os.path.join(cfg["record_dir"], "x"), os.path.dirname(os.path.abspath(config_path))])
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


# ---------------------------------------------------------------------------
# Opt-in pin-consistency REPORT (RW2). NOT an acceptance gate.
#
# `pinned` means only that the committed history is consistent with a named
# reviewer turn that sits directly on the configured reviewed commit and left
# a committed verdict file, while the checked artifact is unchanged since that
# commit. It does NOT mean the tests passed, that the review was independent
# (a reviewer seat name is a claim), or that the reviewer approved: the
# verdict text is never read. terminal_done, closeout_allowed, cycle_complete
# and the label are never touched by this report.
# Limits: check-then-read (history can move between reads; HEAD is re-read at
# the end and a move yields `unverifiable`), record_ok is shape only (so
# check_commit is part of the report), and the record is runtime-observed,
# not tested-tree proof.
# ---------------------------------------------------------------------------
PIN_SCHEMA = "pin-consistency/v1"
PIN_NOTE = ("identity consistency report only: not an acceptance gate, not proof that tests passed, "
            "not independent review, and the verdict text was not read")
_HEX40_RE = None


class _PinUnverifiable(Exception):
    pass


def _pg(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True)
    return r.returncode, r.stdout


def _safe_rel(p):
    return (isinstance(p, str) and p and not p.startswith("/") and ".." not in p.split("/")
            and "\\" not in p and "\0" not in p and "\n" not in p)


def _pin_cfg(cfg):
    import re
    if not isinstance(cfg, dict) or set(cfg) - {"reviewed_commit", "reviewer_seats", "verdict_path"}:
        raise _PinUnverifiable("pin_check must be an object with only reviewed_commit, reviewer_seats, verdict_path")
    rc, seats, vp = cfg.get("reviewed_commit"), cfg.get("reviewer_seats"), cfg.get("verdict_path")
    if not (isinstance(rc, str) and re.fullmatch(r"[0-9a-f]{40}", rc)):
        raise _PinUnverifiable("reviewed_commit must be a full lowercase 40-hex id")
    seat_ok = lambda s: isinstance(s, str) and re.fullmatch(r"[A-Za-z0-9._:@-]{1,128}", s)
    if not (isinstance(seats, list) and seats and all(seat_ok(s) for s in seats)):
        raise _PinUnverifiable("reviewer_seats must be a non-empty list of seat names")
    if not _safe_rel(vp) or vp.startswith(".team/"):
        raise _PinUnverifiable("verdict_path must be a safe repo-relative path outside .team/")
    return rc, list(seats), vp


def pin_consistency(repo, branch, pin_cfg, artifact_paths):
    """Return the `pin_consistency` report object. Never raises. status is
    `pinned`, `not_pinned` (with reasons) or `unverifiable`."""
    repo = os.path.abspath(repo)
    out = {"schema": PIN_SCHEMA, "status": "unverifiable", "reasons": [], "not_acceptance": True, "note": PIN_NOTE}
    try:
        import handoff_record as hr
        reviewed, seats, vpath = _pin_cfg(pin_cfg)
        if not (isinstance(artifact_paths, list) and artifact_paths and all(_safe_rel(p) for p in artifact_paths)):
            raise _PinUnverifiable("artifact_paths must be a non-empty list of safe paths")
        out.update(reviewed_commit=reviewed, verdict_path=vpath)
        head0 = head_sha(repo)
        cur = _pg(repo, "rev-parse", "--abbrev-ref", "HEAD")[1].decode().strip()
        if cur != branch:
            raise _PinUnverifiable("HEAD is on %r, expected %r" % (cur, branch))
        rc, _ = _pg(repo, "cat-file", "-e", reviewed + "^{commit}")
        if rc != 0:
            raise _PinUnverifiable("reviewed_commit is not a commit in this repository")
        reasons = []
        rc, _ = _pg(repo, "merge-base", "--is-ancestor", reviewed, "HEAD")
        if rc == 1:
            reasons.append("reviewed_commit is not an ancestor of HEAD")
        elif rc != 0:
            raise _PinUnverifiable("git merge-base failed")
        rc, plog = _pg(repo, "show", "HEAD:.team/LOG.jsonl")
        if rc != 0:
            raise _PinUnverifiable("no committed .team/LOG.jsonl at HEAD")
        head_lines = set(plog.split(b"\n"))
        rc, revl = _pg(repo, "rev-list", "--parents", "HEAD")
        if rc != 0:
            raise _PinUnverifiable("git rev-list failed")
        cands = []
        for line in revl.decode().splitlines():
            ids = line.split()
            if len(ids) == 2 and ids[1] == reviewed:
                subj = _pg(repo, "log", "-1", "--format=%s", ids[0])[1].decode().strip()
                for s in seats:
                    if subj == "TURN: %s acting" % s:
                        cands.append((ids[0], s))
        if not cands:
            reasons.append("no configured reviewer turn commit sits directly on reviewed_commit")
        elif len(cands) > 1:
            reasons.append("ambiguous: %d reviewer turn commits sit on reviewed_commit" % len(cands))
        elif not reasons:
            commit, seat = cands[0]
            out.update(reviewer_commit=commit, reviewer_seat=seat)
            rc1, clog = _pg(repo, "show", commit + ":.team/LOG.jsonl")
            rc2, blog = _pg(repo, "show", reviewed + ":.team/LOG.jsonl")
            if rc1 != 0 or rc2 != 0:
                raise _PinUnverifiable("LOG not readable at the reviewer commit or its parent")
            if not clog.startswith(blog):
                reasons.append("LOG is not append-only at the reviewer commit")
            else:
                new = [l for l in clog[len(blog):].split(b"\n") if l.strip()]
                rows = []
                for l in new:
                    try:
                        row = json.loads(l)
                    except ValueError:
                        reasons.append("an appended LOG line at the reviewer commit is not JSON"); continue
                    if isinstance(row, dict) and row.get("kind") == "handoff" and row.get("seat") == seat:
                        rows.append((row, l))
                if len(rows) != 1:
                    reasons.append("reviewer commit appended %d handoff rows for seat %s (need exactly 1)" % (len(rows), seat))
                else:
                    row, rawline = rows[0]
                    kind, probs = hr.row_evidence(row)
                    if kind != "record_ok":
                        reasons.append("handoff row is %s: %s" % (kind, "; ".join(probs)))
                    else:
                        rec = row["record"]
                        reasons += ["pin_check: " + p for p in hr.pin_check(reviewed, rec)]
                        cc = hr.check_commit(repo, commit, rec)
                        if cc["status"] != "match":
                            reasons += ["check_commit %s: %s" % (cc["status"], "; ".join(cc["problems"]))]
                        if rawline not in head_lines:
                            reasons.append("the handoff row is not in the committed LOG at HEAD")
                        o = rec["facts"]["observed"]
                        if not o["listed"]:
                            reasons.append("observed paths are digest-only: verdict_path cannot be established")
                        else:
                            hit = [e for e in o["items"] if e["path"] == vpath and e["status"] in ("A", "M")]
                            if not hit:
                                reasons.append("verdict_path was not added or modified in the reviewer turn")
                            else:
                                out["verdict_blob"] = hit[0]["blob"]
        for p in artifact_paths:
            a = _pg(repo, "rev-parse", reviewed + ":" + p)
            b = _pg(repo, "rev-parse", "HEAD:" + p)
            if a[0] != 0 or b[0] != 0:
                reasons.append("artifact path missing at reviewed_commit or HEAD: " + p)
            elif a[1] != b[1]:
                reasons.append("artifact changed since reviewed_commit: " + p)
        if out.get("verdict_blob"):
            v = _pg(repo, "rev-parse", "HEAD:" + vpath)
            if v[0] != 0:
                reasons.append("verdict_path is missing at HEAD")
            elif v[1].decode("ascii", "replace").strip() != out["verdict_blob"]:
                reasons.append("verdict_path at HEAD differs from the blob observed in the reviewer turn")
        if head_sha(repo) != head0:
            raise _PinUnverifiable("HEAD moved during the check")
        out["head"] = head0
        out["reasons"] = reasons
        out["status"] = "not_pinned" if reasons else "pinned"
    except _PinUnverifiable as e:
        out["status"], out["reasons"] = "unverifiable", [str(e)]
    except Exception as e:   # fail closed, no echo of file content
        out["status"], out["reasons"] = "unverifiable", ["check failed: " + type(e).__name__]
    return out


def finalize(repo, branch, config_path):
    """finalize_core plus the optional operator-configured pin_consistency report.
    With no `pin_check` in the operator config the core result is returned untouched."""
    res = _finalize_core(repo, branch, config_path)
    try:
        _private_file(config_path)
        cfg = json.load(open(config_path, encoding="utf-8"))
        if not isinstance(cfg, dict) or "pin_check" not in cfg:
            return res
        pin, paths = cfg["pin_check"], cfg.get("artifact_paths")
    except Exception:
        return res
    out = dict(res)
    out["pin_consistency"] = pin_consistency(repo, branch, pin, paths)
    return out


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
    key = open(a.key_file, "rb").read()   # exact bytes, no stripping (raw keys may end in whitespace bytes)
    st = completion_status(a.repo, a.branch, a.record, a.path, operator_key=key,
                           expected_operator_checker_id=a.checker_id)
    print(json.dumps(st, sort_keys=True))
    return 0 if st["closeout_allowed"] else 1


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    raise SystemExit(main(sys.argv[1:]))
