"""Offline bundle/restore for the fence ledger dir (control file + logs).

The route for a lost or replaced ledger dir: the orchestrator keeps the
latest bundle (a plain tar) and its sha256 in a PRIVATE Hosted File, by
revision id. Restore takes the tar plus the values the caller read from
that File (expected sha256, last receipt hash, window seq, total reserves)
and refuses anything that does not match. Nothing here talks to the
network or to storage; it cannot prove that the private File holds the
latest revision, only that the tar equals what the caller says it holds.
Never overwrites a non-empty destination. Never repairs or resets.
"""
import fcntl, hashlib, io, json, os, re, stat, tarfile

import fenced_http as fh

MAX_TAR = 5_000_000
MAX_MEMBERS = 70
_NAME = re.compile(r"^(_control\.ctl|[a-z0-9-]+\.[a-z0-9-]{1,32}\.jsonl)$")


class RestoreRefused(Exception):
    pass


def bundle(src_dir):
    """-> (tar bytes, sha256). Deterministic: sorted, mtime 0, mode 0600,
    owner 0. Refuses a dir that does not verify (invalid control, broken
    chain, halted is allowed: a halt is part of the record)."""
    c = fh.read_control(src_dir)
    if c["problems"]:
        raise RestoreRefused("control invalid: " + c["problems"][0])
    _, _, ok, _, _ = fh._log_scan(src_dir)
    if not ok:
        raise RestoreRefused("log chain broken")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as t:
        for fn in sorted(os.listdir(src_dir)):
            if not _NAME.match(fn):
                raise RestoreRefused("unexpected file in ledger dir: " + fn)
            p = os.path.join(src_dir, fn)
            if not stat.S_ISREG(os.lstat(p).st_mode):
                raise RestoreRefused("not a regular file: " + fn)
            data = open(p, "rb").read()
            ti = tarfile.TarInfo(fn); ti.size = len(data); ti.mode = 0o600; ti.mtime = 0
            ti.uid = ti.gid = 0; ti.uname = ti.gname = ""
            t.addfile(ti, io.BytesIO(data))
    raw = buf.getvalue()
    return raw, hashlib.sha256(raw).hexdigest()


def restore(tar_bytes, dest_dir, *, expected_sha256, expected_receipt_hash,
            expected_seq, expected_total, recover=None, pending=None, burn=None):
    """Verify, then materialize into a NEW empty dir (0700). Returns the
    window_status info. All expected_* come from the private File; any
    mismatch raises RestoreRefused and leaves nothing behind.

    Crash points (the bundle in the private File always predates the loss):
      recover=None       the bundle is a POST-RUN (or pre-first-window)
                         bundle and nothing newer exists: restore as is.
      recover="pending"  the File's newest record is a pending-window
                         receipt (uploaded BEFORE open_window) with no
                         bundle after it: the window may have been opened
                         and may have run. pending={k,nonce,config_hash,
                         receipt_hash} is burnt in full as spent-unknown.
      recover="post-open" the newest bundle was taken after open_window
                         but no post-run bundle exists: the run may have
                         made reserves that are gone. The window's whole
                         remaining K is burnt as spent-unknown (burn=
                         {nonce,config_hash,receipt_hash}).
    After either burn no window is open; a new one needs a new receipt,
    and its base includes the burnt calls."""
    if not isinstance(tar_bytes, (bytes, bytearray)) or len(tar_bytes) > MAX_TAR:
        raise RestoreRefused("bundle missing or too large")
    if hashlib.sha256(tar_bytes).hexdigest() != expected_sha256:
        raise RestoreRefused("bundle sha256 does not match the private record")
    files = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(bytes(tar_bytes)), mode="r:") as t:
            ms = t.getmembers()
            if len(ms) > MAX_MEMBERS:
                raise RestoreRefused("too many members")
            for m in ms:
                if not m.isreg() or not _NAME.match(m.name) or m.name in files or m.size > MAX_TAR:
                    raise RestoreRefused("bad member: %r" % m.name[:40])
                files[m.name] = t.extractfile(m).read()
    except tarfile.TarError:
        raise RestoreRefused("not a readable tar")
    if "_control.ctl" not in files:
        raise RestoreRefused("no control file in bundle")
    # claim the destination atomically: mkdir fails if it exists (no clobber); an
    # existing EMPTY dir is accepted only under an exclusive non-blocking flock
    # taken before writing, so two restores cannot interleave.
    try:
        os.mkdir(dest_dir, 0o700)
        claim = os.open(dest_dir, os.O_RDONLY)
    except FileExistsError:
        if os.path.islink(dest_dir) or not os.path.isdir(dest_dir):
            raise RestoreRefused("destination exists and is not an empty directory")
        claim = os.open(dest_dir, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    try:
        fcntl.flock(claim, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(claim); raise RestoreRefused("destination is being restored by another process")
    if os.listdir(dest_dir):
        os.close(claim); raise RestoreRefused("destination exists and is not an empty directory")
    os.chmod(dest_dir, 0o700)
    try:
        for fn, data in files.items():
            fd = os.open(os.path.join(dest_dir, fn), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
        fh._fsync_dir(dest_dir)
        c = fh.read_control(dest_dir)
        if c["problems"]:
            raise RestoreRefused("restored control invalid")
        w = c["windows"][-1] if c["windows"] else None
        if (w["receipt_hash"] if w else "0") != expected_receipt_hash:
            raise RestoreRefused("last receipt hash differs from the private record (older or foreign bundle)")
        if (w["seq"] if w else 0) != expected_seq:
            raise RestoreRefused("window seq differs from the private record")
        # recovery mode is DERIVED from the verified bundle and the newest private record, never guessed
        lastseq = w["seq"] if w else 0
        if isinstance(pending, dict) and isinstance(pending.get("seq"), int):
            if pending["seq"] == lastseq + 1:
                derived = "pending"
            elif pending["seq"] > lastseq + 1:
                raise RestoreRefused("newest private receipt is more than one window ahead of the bundle (gap)")
            else:
                derived = "post-open" if (w and w["kind"] == "window-open") else "none"
        else:
            derived = "post-open" if (w and w["kind"] == "window-open") else "none"
        if recover not in (None, "pending", "post-open", "none") or (recover is not None and recover != derived):
            raise RestoreRefused("recover mode %r disagrees with the verified record (derived %r)" % (recover, derived))
        recover = None if derived == "none" else derived
        if w and w["kind"] == "window-open" and recover is None:
            raise RestoreRefused("bundle holds an unclosed window; it can only be restored as exhausted, never reusable")
        res, halted, ok, hs, tips = fh._log_scan(dest_dir)
        if not ok:
            raise RestoreRefused("restored log chain broken")
        if res + c["floor"] + c["burnt"] != expected_total:
            raise RestoreRefused("reserve total differs from the private record (rollback or extra)")
        okw, why, info = fh.window_status(dest_dir)
        if w and w["kind"] == "window-open" and not okw and why != "window exhausted":
            raise RestoreRefused("window check: " + why)
        prev_r = w["receipt_hash"] if w else "0"
        try:
            if recover == "pending":
                _res, _h, _ok, _hs, _tips = fh._log_scan(dest_dir)
                if not (isinstance(pending, dict) and pending.get("tar_sha256") == expected_sha256
                        and pending.get("prev_receipt_hash") == prev_r
                        and pending.get("seq") == (w["seq"] if w else 0) + 1
                        and pending.get("tips") == _tips):
                    raise RestoreRefused("pending receipt does not bind this bundle (tar sha, prev receipt, seq, tips)")
                fh.burn_window(dest_dir, pending["nonce"], pending["config_hash"],
                               pending["receipt_hash"], prev_r, pending_k=pending["k"])
            elif recover == "post-open":
                fh.burn_window(dest_dir, burn["nonce"], burn["config_hash"],
                               burn["receipt_hash"], prev_r)
        except (fh.FenceRefused, KeyError, TypeError) as e:
            raise RestoreRefused("burn refused: " + str(e)[:80])
        sm = fh.ledger_summary(dest_dir)
        if not sm.get("consistent"):
            raise RestoreRefused("restored ledger accounting is inconsistent (spent/committed): %r" % {k: sm.get(k) for k in ("spent", "committed")})
        return info
    except BaseException:
        os.close(claim); claim = None
        # cleanup only what THIS call wrote, and only while we hold the dest lock-free
        # fresh dir (nothing else may use it: it did not exist or was empty)
        for fn in list(files):
            try:
                os.remove(os.path.join(dest_dir, fn))
            except FileNotFoundError:
                pass
        try:
            os.rmdir(dest_dir)
        except OSError:
            pass            # someone else wrote there: leave their files, fail closed
        raise
    finally:
        if claim is not None:
            os.close(claim)
