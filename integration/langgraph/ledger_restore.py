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
import hashlib, io, json, os, re, stat, tarfile

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
            expected_seq, expected_total):
    """Verify, then materialize into a NEW empty dir (0700). Returns the
    window_status info. All expected_* come from the private File; any
    mismatch raises RestoreRefused and leaves nothing behind."""
    if not isinstance(tar_bytes, (bytes, bytearray)) or len(tar_bytes) > MAX_TAR:
        raise RestoreRefused("bundle missing or too large")
    if hashlib.sha256(tar_bytes).hexdigest() != expected_sha256:
        raise RestoreRefused("bundle sha256 does not match the private record")
    if os.path.lexists(dest_dir) and (os.path.islink(dest_dir) or not os.path.isdir(dest_dir)
                                      or os.listdir(dest_dir)):
        raise RestoreRefused("destination exists and is not an empty directory")
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
    os.makedirs(dest_dir, mode=0o700, exist_ok=True)
    os.chmod(dest_dir, 0o700)
    try:
        for fn, data in files.items():
            fd = os.open(os.path.join(dest_dir, fn), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
        c = fh.read_control(dest_dir)
        if c["problems"] or not c["windows"]:
            raise RestoreRefused("restored control invalid or has no window")
        w = c["windows"][-1]
        if w["receipt_hash"] != expected_receipt_hash:
            raise RestoreRefused("last receipt hash differs from the private record (older or foreign bundle)")
        if w["seq"] != expected_seq:
            raise RestoreRefused("window seq differs from the private record")
        res, halted, ok, hs, tips = fh._log_scan(dest_dir)
        if not ok:
            raise RestoreRefused("restored log chain broken")
        if res + c["floor"] != expected_total:
            raise RestoreRefused("reserve total differs from the private record (rollback or extra)")
        okw, why, info = fh.window_status(dest_dir)
        if not okw and why != "window exhausted":
            raise RestoreRefused("window check: " + why)
        return info
    except BaseException:
        for fn in list(os.listdir(dest_dir)):
            os.remove(os.path.join(dest_dir, fn))
        os.rmdir(dest_dir)
        raise
