"""Offline lifecycle test of the private record procedure with a NO-CAS fake store
(revision ids are opaque; the store can hold hidden newer drafts). Synthetic data only."""
import hashlib, os, secrets, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fenced_http as fh, ledger_restore as lr, private_record as pr, bounded_run as br
import window_test_support as wts
FAIL = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: FAIL.append(n)
def refused(f, *ex):
    try: f(); return False
    except (pr.RecordRefused, lr.RestoreRefused, fh.FenceRefused) + ex: return True
H = lambda s: hashlib.sha256(s.encode()).hexdigest()
TOKEN = "pr-token"; OWN = hashlib.sha256(TOKEN.encode()).hexdigest(); os.environ["FENCE_WINDOW_TOKEN"] = TOKEN; os.environ["WK"] = "x"
tmp = tempfile.mkdtemp()
class Store:                       # fake hosted File: build -> opaque revision id; checkout by id; no-id = whatever "latest" is
    def __init__(s): s.revs = {}; s.latest = None; s.n = 0
    def build(s, src):
        s.n += 1; rid = "rev-%d-%s" % (s.n, secrets.token_hex(4)); s.revs[rid] = os.path.join(tmp, "store", rid)
        shutil.copytree(src, s.revs[rid]); s.latest = rid; return rid
    def checkout(s, rid=None):
        rid = rid or s.latest; d = os.path.join(tmp, "co", secrets.token_hex(4)); shutil.copytree(s.revs[rid], d); return rid, d
ST = Store()
L = os.path.join(tmp, "L"); os.makedirs(L, mode=0o700); fh.HTTP_LOG_DIR = L
fh.HTTP_LIFETIME_CAP = 12
fh.import_historic_floor(L, 11, 4, 7, ["old.e0.jsonl"], external_manifest_present=False)

def upload(kind, tar, **kw):
    d = os.path.join(tmp, "src", secrets.token_hex(4)); msha = pr.stage(d, kind, tar, **kw)
    rid = ST.build(d)
    _, back = ST.checkout(rid); rec = pr.load(back)                       # explicit-revision read-back
    assert rec["manifest_sha"] == msha
    _, lat = ST.checkout(None); assert pr.same_revision(rec, pr.load(lat))  # no-id latest read-back
    return rid, rec, {"revision_id": rid, "rev_no": kw["rev_no"], "manifest_sha": msha}
# rev1: initial closed record (floor only)
tar0, sha0 = lr.bundle(L)
rid1, rec1, LOC = upload("closed", tar0, rev_no=1, prev_revision_id=None, prev_manifest_sha=None, last_receipt_hash="0", seq=0, total=11)
# window: receipt first
nonce = secrets.token_hex(32); cfgh = H("cfg")
body = dict(kind="pending-window", seq=1, k=1, nonce=nonce, config_hash=cfgh, tar_sha256=sha0, prev_receipt_hash="0", tips=fh._log_scan(L)[4], owner_hash=OWN, argv_sha256=hashlib.sha256("\0".join(["entry", "live"]).encode()).hexdigest(), planned=1)
rcpt = pr.finalize_receipt(body)
rid2, rec2, LOC2 = upload("pending", tar0, rev_no=2, prev_revision_id=rid1, prev_manifest_sha=rec1["manifest_sha"], last_receipt_hash="0", seq=0, total=11, receipt=rcpt)
check("pending revision chains to the previous verified record", pr.check_chain(rec2, rec1, rid1))
check("locator naming the newest revision accepts it", pr.check_against_locator(rec2, LOC2, rid2))
# the seam with the wrapper: the record's raw receipt bytes ARE the local copy the wrapper hashes
sdir = os.path.join(tmp, "state"); os.makedirs(sdir, mode=0o700)
open(os.path.join(sdir, "window-receipt-%s.json" % nonce), "wb").write(rec2["receipt_raw"])
check("record receipt bytes hash to the receipt_hash the window line will carry", hashlib.sha256(rec2["receipt_raw"]).hexdigest() == rcpt["receipt_hash"])
fh.open_window(L, 1, nonce, cfgh, rcpt["receipt_hash"], "0", OWN); wts.bind_live_run(L)
check("wrapper window_gate accepts the local copy written from the record (receipt fields, argv, planned all match)", br.window_gate(sdir, L, 1, argv=["entry", "live"]) is None)
check("wrapper window_gate refuses when the local copy differs by one byte", (lambda: (open(os.path.join(sdir, "window-receipt-%s.json" % nonce), "ab").write(b" "), br.window_gate(sdir, L, 1, argv=["entry", "live"]))[1])() is not None)
open(os.path.join(sdir, "window-receipt-%s.json" % nonce), "wb").write(rec2["receipt_raw"])
a = fh.FencedHttpAdapter("http://127.0.0.1:1", "m-a", "WK", "e1", 9, 16, 1, None); a.reserve()
# crash cases all share the state "File newest = pending": restore must burn the whole pending K
def restore_from(rec):
    t, kw = pr.restore_args(rec); d = os.path.join(tmp, "r" + secrets.token_hex(3)); lr.restore(t, d, **kw); return d
dpend = restore_from(rec2)
s = fh.ledger_summary(dpend)
check("CRASH before upload (open_window ran, run may have happened) / post-upload skipped: restore from the pending record burns K=1 -> spent 12, consistent, no window can open",
      (s["spent"], s["committed"], s["consistent"]) == (12, 12, True) and fh.window_status(dpend)[1] == "no window open"
      and refused(lambda: fh.open_window(dpend, 1, secrets.token_hex(32), H("c"), H("r9"), rcpt["receipt_hash"], OWN)))
# normal path: close, bundle, upload closed
br.close_window(L, "run")
tar1, sha1 = lr.bundle(L); LR = fh.read_control(L)["windows"][-1]["receipt_hash"]
rid3, rec3, LOC3 = upload("closed", tar1, rev_no=3, prev_revision_id=rid2, prev_manifest_sha=rec2["manifest_sha"], last_receipt_hash=LR, seq=2, total=12)
dc = restore_from(rec3); sc = fh.ledger_summary(dc)
check("normal path: restore from the closed record equals the live ledger (spent 12, consistent)", (sc["spent"], sc["consistent"]) == (12, True))
check("restore result of pending record and closed record agree on total", s["spent"] == sc["spent"])
# omitted newest pending receipt: operator restores rev1 (closed, total 11) although a window may have run
d_old = restore_from(rec1)
check("OMISSION under-counts (restore of rev1 shows 11 though a call was reserved): code cannot see it", fh.ledger_summary(d_old)["spent"] == 11)
check("...but the separate locator refuses the stale record", refused(lambda: pr.check_against_locator(rec1, LOC3, rid1)))
# hidden newer draft: no-id checkout returns something the locator does not name
hid = os.path.join(tmp, "src", "hidden"); pr.stage(hid, "closed", tar1, rev_no=4, prev_revision_id=rid3, prev_manifest_sha=rec3["manifest_sha"], last_receipt_hash=LR, seq=2, total=12)
ridh = ST.build(hid); _, lat = ST.checkout(None); lrec = pr.load(lat)
check("hidden newer revision (no CAS): latest != locator -> refused, fail closed", refused(lambda: pr.check_against_locator(lrec, LOC3, ridh)))
ST.latest = rid3
# manifest unreachable / ambiguous / tampered
def mut(name, fn):
    d = os.path.join(tmp, "m" + secrets.token_hex(3)); shutil.copytree(os.path.join(tmp, "store", rid2), d); fn(d); return d
check("manifest missing -> refused", refused(lambda: pr.load(mut("m", lambda d: os.remove(os.path.join(d, "manifest.json"))))))
check("receipt missing from a pending revision -> refused", refused(lambda: pr.load(mut("r", lambda d: os.remove(os.path.join(d, "receipt.json"))))))
check("extra file -> refused", refused(lambda: pr.load(mut("x", lambda d: open(os.path.join(d, "notes.txt"), "w").write("x")))))
def flip(d):
    p = os.path.join(d, "ledger.tar"); b = bytearray(open(p, "rb").read()); b[100] ^= 1; open(p, "wb").write(bytes(b))
check("tar tampered -> refused", refused(lambda: pr.load(mut("t", flip))))
def rcpt_edit(d):
    import json; p = os.path.join(d, "receipt.json"); r = json.load(open(p)); r["k"] = 0; open(p, "w").write(json.dumps(r, sort_keys=True))
check("receipt edited (k lowered) -> refused", refused(lambda: pr.load(mut("e", rcpt_edit))))
check("chain break (wrong previous revision id) -> refused", refused(lambda: pr.check_chain(rec3, rec2, "wrong-id")))
def man(rec, **ch):
    m = dict(rec["manifest"]); m.update(ch); return {"manifest": m, "manifest_sha": rec["manifest_sha"], "tar": rec["tar"], "receipt": rec["receipt"]}
def linked(rec, **ch):
    m = man(rec, **ch); return m
check("same rev_no refused", refused(lambda: pr.check_chain(linked(rec3, rev_no=2, prev_manifest_sha=rec2["manifest_sha"], prev_revision_id=rid2), rec2, rid2)))
check("skipped rev_no refused", refused(lambda: pr.check_chain(linked(rec3, rev_no=4), rec2, rid2)))
check("older rev_no refused", refused(lambda: pr.check_chain(linked(rec3, rev_no=1), rec2, rid2)))
check("seq decrease refused (explicit)", refused(lambda: pr.check_chain(linked(rec3, seq=1), linked(rec2, rev_no=2, seq=5), rid2)))
check("total decrease refused", refused(lambda: pr.check_chain(linked(rec3, total=10), rec2, rid2)))
check("good next record accepted", pr.check_chain(rec3, rec2, rid2))
# fork guard: equal seq/total but a different, internally valid ledger
import io as _io, tarfile as _tf
def ledger_with(floor_unknown):
    d2 = os.path.join(tmp, "fk" + secrets.token_hex(3)); os.makedirs(d2, mode=0o700); fh.HTTP_LOG_DIR = d2
    fh.import_historic_floor(d2, 11, floor_unknown, 11 - floor_unknown, ["fork.e0.jsonl"], external_manifest_present=False)
    fh.HTTP_LOG_DIR = L; return lr.bundle(d2)[0]
fork_tar = ledger_with(3)
frec = pr.load(os.path.join(tmp, "store", rid1)); frec = dict(frec, tar=fork_tar)
check("fork: same seq/total, different valid ledger -> refused as non-extending", refused(lambda: pr.check_chain(dict(rec2, tar=fork_tar), rec1, rid1)))
check("append-only holds for the real next record", pr.check_append_only(rec1["tar"], rec3["tar"]))
check("append-only: shrinking (newer shorter than older) refused", refused(lambda: pr.check_append_only(rec3["tar"], rec1["tar"])))
check("append-only: unreadable tar refused", refused(lambda: pr.check_append_only(b"junk", rec1["tar"])))
import tarfile as _tfm, io as _iom
_b = _iom.BytesIO()
with _tfm.open(fileobj=_b, mode="w") as _t:
    for _ in range(2):
        _ti = _tfm.TarInfo("_control.ctl"); _ti.size = 1; _t.addfile(_ti, _iom.BytesIO(b"x"))
check("duplicate tar member names refused", refused(lambda: pr.check_append_only(_b.getvalue(), _b.getvalue())))
# pending receipt field tightening
import json as _j
def pend_mut(**ch):
    r = dict(rcpt); r.update(ch); body = {k: v for k, v in r.items() if k != "receipt_hash"}; r = pr.finalize_receipt(body)
    return refused(lambda: pr.stage(os.path.join(tmp, "src", "pm" + secrets.token_hex(3)), "pending", tar0, rev_no=2, prev_revision_id=rid1, prev_manifest_sha=rec1["manifest_sha"], last_receipt_hash="0", seq=0, total=11, receipt=r) and pr.load(os.path.join(tmp, "src")))
def load_pend(**ch):
    r = pr.finalize_receipt({k: v for k, v in dict(rcpt, **ch).items() if k != "receipt_hash"}); d = os.path.join(tmp, "src", "lp" + secrets.token_hex(3))
    try:
        pr.stage(d, "pending", tar0, rev_no=2, prev_revision_id=rid1, prev_manifest_sha=rec1["manifest_sha"], last_receipt_hash="0", seq=0, total=11, receipt=r); pr.load(d); return False
    except pr.RecordRefused: return True
check("pending: prev_receipt_hash must equal the manifest's last receipt", load_pend(prev_receipt_hash=H("zz")))
check("pending: k must be a positive int", load_pend(k=0) and load_pend(k="1") and load_pend(k=True))
check("pending: tips must be an object of strings ({} ok for a floor-only ledger)", load_pend(tips="") and load_pend(tips=[]) and load_pend(tips={"a": 1}) and not load_pend(tips={}))
check("pending: nonce/config_hash must be non-empty strings", load_pend(nonce="") and load_pend(config_hash=5))
check("pending: the good receipt loads", not load_pend())
# adoption rule: new revision uploaded, locator for it not yet stored
check("adopt: returns a candidate locator only after anchored locator and chain verify",
      pr.adopt(rec3, rid3, rec2, rid2, LOC2)["rev_no"] == 3)
check("adopt: anchored record not matching its locator -> refused (no fallback)", refused(lambda: pr.adopt(rec3, rid3, rec2, rid2, LOC)))
check("adopt: new record does not chain from the anchored one -> refused", refused(lambda: pr.adopt(rec3, rid3, rec1, rid1, LOC)))
check("adopt: skipping a revision (rev1 anchored, rev3 new) refused", refused(lambda: pr.adopt(rec3, rid3, rec1, rid1, dict(LOC, file_id="f"))))
check("a pending receipt with the wrong tar cannot be staged", refused(lambda: pr.stage(os.path.join(tmp, "src", "w"), "pending", tar1, rev_no=9, prev_revision_id=rid3, prev_manifest_sha="x", last_receipt_hash=LR, seq=2, total=12, receipt=rcpt)))
check("pending needs a receipt; closed must not carry one", refused(lambda: pr.stage(os.path.join(tmp, "src", "w2"), "pending", tar1, rev_no=9, prev_revision_id=None, prev_manifest_sha=None, last_receipt_hash=LR, seq=2, total=12)) and refused(lambda: pr.stage(os.path.join(tmp, "src", "w3"), "closed", tar1, rev_no=9, prev_revision_id=None, prev_manifest_sha=None, last_receipt_hash=LR, seq=2, total=12, receipt=rcpt)))
check("file modes 0600 / dir 0700 in staged revision", all(oct(os.stat(os.path.join(tmp, "store", rid2, f)).st_mode & 0o777) == "0o600" for f in os.listdir(os.path.join(tmp, "store", rid2))))
shutil.rmtree(tmp)
print("FAILED" if FAIL else "ALL PASS"); sys.exit(1 if FAIL else 0)
