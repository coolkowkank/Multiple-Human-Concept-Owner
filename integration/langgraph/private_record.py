"""Private external record of the ledger: one source-project directory per Hosted File
revision. OFFLINE helper for the orchestrator procedure; it performs no network or File
call itself. A revision directory holds ONLY: ledger.tar (hash-chained control + usage
logs: hashes, counts, slugs; no prompts, keys or transcripts), receipt.json (the pending
window receipt, only for kind 'pending') and manifest.json. Nothing here is secret.

Fail closed: any missing, extra, malformed, mismatching or non-monotone item raises
RecordRefused; nothing is guessed or repaired. Not a CAS: 'latest' is only what the
separately kept locator says it is (see check_against_locator)."""
import hashlib, json, os

KINDS = ("pending", "closed")
FILES = {"pending": ("ledger.tar", "receipt.json", "manifest.json"),
         "closed": ("ledger.tar", "manifest.json")}


class RecordRefused(Exception):
    pass


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def stage(out_dir, kind, tar_bytes, *, rev_no, prev_revision_id, prev_manifest_sha,
          last_receipt_hash, seq, total, receipt=None):
    """Write a new revision directory (must not exist). Returns manifest sha256."""
    if kind not in KINDS:
        raise RecordRefused("unknown kind")
    if (kind == "pending") != isinstance(receipt, dict):
        raise RecordRefused("a pending revision needs a receipt, a closed one must not carry one")
    os.makedirs(out_dir, mode=0o700)
    rb = None
    if receipt is not None:
        rb = json.dumps(receipt, sort_keys=True).encode()
        for f in ("seq", "k", "nonce", "config_hash", "receipt_hash", "tar_sha256", "prev_receipt_hash", "tips"):
            if f not in receipt:
                raise RecordRefused("receipt lacks %s" % f)
        if receipt["tar_sha256"] != _sha(tar_bytes):
            raise RecordRefused("receipt does not bind this tar")
    m = {"kind": kind, "rev_no": rev_no, "prev_revision_id": prev_revision_id,
         "prev_manifest_sha": prev_manifest_sha, "tar_sha256": _sha(tar_bytes),
         "last_receipt_hash": last_receipt_hash, "seq": seq, "total": total,
         "receipt_sha256": _sha(rb) if rb else None}
    mb = json.dumps(m, sort_keys=True).encode()
    for name, data in (("ledger.tar", tar_bytes), ("receipt.json", rb), ("manifest.json", mb)):
        if data is None:
            continue
        fd = os.open(os.path.join(out_dir, name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
    return _sha(mb)


def finalize_receipt(body):
    """body: receipt fields WITHOUT receipt_hash. Returns the receipt with receipt_hash =
    sha256 of the canonical body (this is the hash open_window records)."""
    if "receipt_hash" in body:
        raise RecordRefused("body must not carry receipt_hash")
    r = dict(body); r["receipt_hash"] = _sha(json.dumps(body, sort_keys=True).encode())
    return r


def load(rev_dir):
    """Read and verify one revision directory. Returns dict(manifest, manifest_sha, tar, receipt)."""
    try:
        names = sorted(os.listdir(rev_dir))
        mb = open(os.path.join(rev_dir, "manifest.json"), "rb").read()
        m = json.loads(mb)
    except (OSError, ValueError):
        raise RecordRefused("manifest missing or unreadable")
    if not isinstance(m, dict) or m.get("kind") not in KINDS:
        raise RecordRefused("manifest malformed")
    if names != sorted(FILES[m["kind"]]):
        raise RecordRefused("unexpected or missing files: %s" % names)
    tar = open(os.path.join(rev_dir, "ledger.tar"), "rb").read()
    if _sha(tar) != m.get("tar_sha256"):
        raise RecordRefused("tar hash differs from manifest")
    receipt = None
    if m["kind"] == "pending":
        rb = open(os.path.join(rev_dir, "receipt.json"), "rb").read()
        if _sha(rb) != m.get("receipt_sha256"):
            raise RecordRefused("receipt hash differs from manifest")
        receipt = json.loads(rb)
        body = {k: v for k, v in receipt.items() if k != "receipt_hash"}
        if receipt.get("receipt_hash") != _sha(json.dumps(body, sort_keys=True).encode()):
            raise RecordRefused("receipt_hash is not the hash of the receipt body")
        if receipt.get("tar_sha256") != m["tar_sha256"] or receipt.get("seq") != m.get("seq", -9) + 1:
            raise RecordRefused("receipt does not bind the manifest's tar/seq")
    for f in ("rev_no", "seq", "total"):
        if not isinstance(m.get(f), int) or isinstance(m.get(f), bool) or m[f] < 0:
            raise RecordRefused("manifest field %s invalid" % f)
    return {"manifest": m, "manifest_sha": _sha(mb), "tar": tar, "receipt": receipt}


def same_revision(a, b):
    """True only if two loaded revisions are byte-identical records."""
    return a["manifest_sha"] == b["manifest_sha"] and a["tar"] == b["tar"] and a["receipt"] == b["receipt"]


def check_against_locator(rec, locator, revision_id):
    """locator = {file_id, revision_id, rev_no, manifest_sha} kept SEPARATELY from the File.
    The newest record is trusted only if it is exactly the one the locator names."""
    ok = (isinstance(locator, dict) and locator.get("revision_id") == revision_id
          and locator.get("rev_no") == rec["manifest"]["rev_no"]
          and locator.get("manifest_sha") == rec["manifest_sha"])
    if not ok:
        raise RecordRefused("newest File record is not the one the locator names (stale, hidden-newer, or wrong): fail closed")
    return True


def check_chain(newer, older_manifest_sha, older_revision_id):
    m = newer["manifest"]
    if m["rev_no"] < 1 or m["prev_manifest_sha"] != older_manifest_sha or m["prev_revision_id"] != older_revision_id:
        raise RecordRefused("revision chain does not link to the previous verified record")
    return True


def restore_args(rec):
    """kwargs for ledger_restore.restore(tar, dest, **kwargs): derived only from the verified record."""
    m = rec["manifest"]
    kw = dict(expected_sha256=m["tar_sha256"], expected_receipt_hash=m["last_receipt_hash"],
              expected_seq=m["seq"], expected_total=m["total"])
    if rec["receipt"] is not None:
        kw["pending"] = rec["receipt"]
    return rec["tar"], kw
