"""Bundle/restore offline fault tests (temp dirs, synthetic data)."""
import hashlib, io, os, secrets, shutil, sys, tarfile, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fenced_http as fh, ledger_restore as lr

import hashlib as _hl
TOKEN = "test-owner-token"; OWN = _hl.sha256(TOKEN.encode()).hexdigest(); os.environ["FENCE_WINDOW_TOKEN"] = TOKEN
_ow = fh.open_window
fh.open_window = lambda *a, **k: _ow(*a, owner_hash=k.pop("owner_hash", OWN), **k)
FAIL = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: FAIL.append(n)
def refused(f):
    try: f(); return False
    except (lr.RestoreRefused, fh.FenceRefused): return True
tmp = tempfile.mkdtemp(); os.environ["WK"] = "x"
S = os.path.join(tmp, "src"); os.makedirs(S, mode=0o700); fh.HTTP_LOG_DIR = S
H = lambda s: hashlib.sha256(s.encode()).hexdigest()
fh.import_historic_floor(S, 4, 1, 3, ["old-model.o1.jsonl"], external_manifest_present=False)
fh.open_window(S, 3, secrets.token_hex(32), H("c"), H("r1"), "0")
a = fh.FencedHttpAdapter("http://127.0.0.1:1", "m-a", "WK", "e1", 9, 16, 1, None); a.reserve(); a.reserve()
import bounded_run as br
check("close_window burns the remaining K=1 as a typed superseding burn", br.close_window(S, "run1") is None and fh.read_control(S)["burnt"] == 1)
LASTR = fh.read_control(S)["windows"][-1]["receipt_hash"]
raw, sha = lr.bundle(S)
raw2, sha2 = lr.bundle(S)
check("bundle deterministic", raw == raw2 and sha == sha2)
# an unclosed-window bundle taken before close (kept for the refusal test)
_so = os.path.join(tmp, "so"); shutil.copytree(S, _so); _c = os.path.join(_so, fh.CONTROL_NAME); _l = open(_c).read().splitlines(True); open(_c, "w").write("".join(_l[:-1]))
raw_open, sha_open = lr.bundle(_so)
args = dict(expected_sha256=sha, expected_receipt_hash=LASTR, expected_seq=2, expected_total=7)
D = os.path.join(tmp, "d1"); info = lr.restore(raw, D, **args)
check("good restore of a CLOSED window: no window open, floor+burn+reserves counted, mode 0700", fh.window_status(D)[1] == "no window open" and os.stat(D).st_mode & 0o777 == 0o700
      and fh._read_all(D) == (7, False, True))
check("reserve_states carry typed floor and burn entries", sorted(set(fh.reserve_states(D).values()) - {"reserved-not-started"}) == ["burnt-unknown", "historic-settled", "historic-unknown"])
check("restoring a bundle with an UNCLOSED window as-is is refused (never reusable)", refused(lambda: lr.restore(raw_open, os.path.join(tmp, "uo"), expected_sha256=sha_open, expected_receipt_hash=H("r1"), expected_seq=1, expected_total=6)))
check("restore into non-empty dir refused", refused(lambda: lr.restore(raw, D, **args)))
def bad(**kw):
    a2 = dict(args); a2.update(kw); d = os.path.join(tmp, "x" + secrets.token_hex(3))
    r = refused(lambda: lr.restore(kw.pop("_raw", raw) if False else raw, d, **a2)); return r and not os.path.exists(d)
check("wrong sha refused, nothing left", bad(expected_sha256=H("z")))
check("older receipt (rollback to earlier bundle) refused", bad(expected_receipt_hash=H("r0")))
check("wrong seq refused", bad(expected_seq=3))
check("total mismatch (rolled back / extra) refused", bad(expected_total=6) and bad(expected_total=8))
# tampered bundle with matching claimed sha: truncated log
def retar(mut):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as t:
        for fn in sorted(os.listdir(S)):
            data = open(os.path.join(S, fn), "rb").read(); data = mut(fn, data)
            if data is None: continue
            ti = tarfile.TarInfo(fn); ti.size = len(data); t.addfile(ti, io.BytesIO(data))
    r = out.getvalue(); return r, hashlib.sha256(r).hexdigest()
tr, ts = retar(lambda fn, d: d[:d.rfind(b"\n", 0, len(d) - 1) + 1] if fn.endswith(".jsonl") else d)
check("log truncated inside bundle refused even with matching sha", refused(lambda: lr.restore(tr, os.path.join(tmp, "t1"), **dict(args, expected_sha256=ts))))
tr, ts = retar(lambda fn, d: None if fn == "_control.ctl" else d)
check("bundle without control refused", refused(lambda: lr.restore(tr, os.path.join(tmp, "t2"), **dict(args, expected_sha256=ts))))
out = io.BytesIO()
with tarfile.open(fileobj=out, mode="w") as t:
    ti = tarfile.TarInfo("../evil.jsonl"); ti.size = 1; t.addfile(ti, io.BytesIO(b"x"))
r = out.getvalue()
check("path-escape member refused", refused(lambda: lr.restore(r, os.path.join(tmp, "t3"), **dict(args, expected_sha256=hashlib.sha256(r).hexdigest()))) and not os.path.exists(os.path.join(tmp, "evil.jsonl")))
out = io.BytesIO()
with tarfile.open(fileobj=out, mode="w") as t:
    ti = tarfile.TarInfo("a.b.jsonl"); ti.type = tarfile.SYMTYPE; ti.linkname = "/etc/passwd"; t.addfile(ti)
r = out.getvalue()
check("symlink member refused", refused(lambda: lr.restore(r, os.path.join(tmp, "t4"), **dict(args, expected_sha256=hashlib.sha256(r).hexdigest()))))
check("bundle refuses unexpected file in source dir", (lambda: (open(os.path.join(S, "notes.txt"), "w").write("x"), refused(lambda: lr.bundle(S)))[1])())

# ---- crash-point evidence: where the pending K / nonce is burnt and bound
def fresh(tag):
    d = os.path.join(tmp, tag); os.makedirs(d, mode=0o700); fh.HTTP_LOG_DIR = d
    fh.import_historic_floor(d, 4, 1, 3, ["old-model.o1.jsonl"], external_manifest_present=False); return d
def new_adapter(m="m-a", e="e1"): return fh.FencedHttpAdapter("http://127.0.0.1:1", m, "WK", e, 9, 16, 1, None)
# P1: receipt uploaded for window 1 (K=2), crash BEFORE open_window; ledger lost. Only the pre-window bundle exists.
d = fresh("p1"); pre, pre_sha = lr.bundle(d)
D1 = os.path.join(tmp, "p1r")
PEND = dict(k=2, nonce=secrets.token_hex(32), config_hash=H("c"), receipt_hash=H("rP1"), tar_sha256=pre_sha,
            prev_receipt_hash="0", seq=1, tips=fh._log_scan(d)[4])
check("pending receipt not binding this bundle (wrong tar sha) refused", refused(lambda: lr.restore(pre, os.path.join(tmp, "pb"), expected_sha256=pre_sha, expected_receipt_hash="0", expected_seq=0, expected_total=4, recover="pending", pending=dict(PEND, tar_sha256=H("x")))))
check("pending receipt with wrong seq / prev / tips refused", all(refused(lambda kw=kw: lr.restore(pre, os.path.join(tmp, "pb2"), expected_sha256=pre_sha, expected_receipt_hash="0", expected_seq=0, expected_total=4, recover="pending", pending=dict(PEND, **kw))) for kw in (dict(seq=2), dict(prev_receipt_hash=H("q")), dict(tips={"a.b.jsonl": H("t")}))))
lr.restore(pre, D1, expected_sha256=pre_sha, expected_receipt_hash="0", expected_seq=0, expected_total=4,
           recover="pending", pending=PEND)
fh.HTTP_LOG_DIR = D1
check("P1: pending K=2 burnt as spent-unknown (4+2), no window open, reserve refused", fh._read_all(D1)[0] == 6 and fh.window_status(D1)[1] == "no window open"
)
try: new_adapter().reserve(); r_ok = False
except fh.FenceRefused as e: r_ok = "no window open" in str(e)
check("P1: reserve after recovery refused", r_ok)
fh.open_window(D1, 1, secrets.token_hex(32), H("c"), H("rP1b"), H("rP1"))
w = fh.read_control(D1)["windows"]
check("P1: next window base includes burnt K and chains off the burnt receipt", w[-1]["base"] == 6 and w[-1]["prev_receipt_hash"] == H("rP1") and w[-1]["seq"] == 2)
# P2: window opened + post-open bundle uploaded, run made reserves, ledger lost before post-run bundle.
d = fresh("p2"); fh.open_window(d, 3, secrets.token_hex(32), H("c"), H("rP2"), "0")
po, po_sha = lr.bundle(d)
a2 = new_adapter(); a2.reserve(); a2.reserve()       # reserves that are LOST with the sandbox
D2 = os.path.join(tmp, "p2r")
try:
    lr.restore(po, D2, expected_sha256=po_sha, expected_receipt_hash=H("rP2"), expected_seq=1, expected_total=4)
    plain_open = True
except lr.RestoreRefused: plain_open = False
check("P2: restore WITHOUT recovery of the post-open bundle is refused (it would look like an unused window)", not plain_open and not os.path.exists(D2))
lr.restore(po, D2, expected_sha256=po_sha, expected_receipt_hash=H("rP2"), expected_seq=1, expected_total=4,
           recover="post-open", burn=dict(nonce=secrets.token_hex(32), config_hash=H("c"), receipt_hash=H("rP2b")))
fh.HTTP_LOG_DIR = D2
check("P2: recovery burns the whole remaining K=3 (4+3), window closed", fh._read_all(D2)[0] == 7 and fh.window_status(D2)[1] == "no window open")
c2 = fh.read_control(D2)
check("P2: burn line supersedes (not double counted in committed) and binds receipt chain", c2["windows"][-1]["supersedes"] is True and c2["windows"][-1]["prev_receipt_hash"] == H("rP2"))
fh.open_window(D2, 3, secrets.token_hex(32), H("c"), H("rP2c"), H("rP2b"))
check("P2: a fresh window is possible only up to the remaining cap (4+3 burnt-open + 3 = 10)", fh.read_control(D2)["windows"][-1]["base"] == 7)
# P3: post-run bundle exists: plain restore, window state preserved
d = fresh("p3"); fh.open_window(d, 2, secrets.token_hex(32), H("c"), H("rP3"), "0"); a3 = new_adapter(); a3.reserve()
br.close_window(d, "run3"); r3 = fh.read_control(d)["windows"][-1]["receipt_hash"]
pr, pr_sha = lr.bundle(d)
D3 = os.path.join(tmp, "p3r")
lr.restore(pr, D3, expected_sha256=pr_sha, expected_receipt_hash=r3, expected_seq=2, expected_total=6)
check("P3: post-run (closed) restore: 1 reserve + 1 burnt remainder counted, no window open", fh._read_all(D3)[0] == 6 and fh.window_status(D3)[1] == "no window open")
# bad recovery inputs
check("post-open recovery without an open window refused (mode disagrees with record)", refused(lambda: lr.restore(pre, os.path.join(tmp, "q1"), expected_sha256=pre_sha, expected_receipt_hash="0", expected_seq=0, expected_total=4, recover="post-open", burn=dict(nonce=secrets.token_hex(32), config_hash=H("c"), receipt_hash=H("z")))))
Dq = os.path.join(tmp, "q2")
lr.restore(pre, Dq, expected_sha256=pre_sha, expected_receipt_hash="0", expected_seq=0, expected_total=4, recover="pending", pending=dict(PEND, k=9, nonce=secrets.token_hex(32)))
fh.HTTP_LOG_DIR = Dq; sq = fh.ledger_summary(Dq)
check("pending liability past the cap is still RECORDED (spent 13), flagged over_cap, consistent", sq["spent"] == 13 and sq["over_cap"] and sq["consistent"])
try: new_adapter().reserve(); okq = False
except fh.FenceRefused as e: okq = "no window open" in str(e)
check("and future use is halted (no window can open over the cap)", okq and refused(lambda: fh.open_window(Dq, 1, secrets.token_hex(32), H("c"), H("q"), PEND["receipt_hash"])) is not None)
check("recover mode that disagrees with the verified record is refused", refused(lambda: lr.restore(pre, os.path.join(tmp, "q3"), expected_sha256=pre_sha, expected_receipt_hash="0", expected_seq=0, expected_total=4, recover="post-open", burn=dict(nonce=secrets.token_hex(32), config_hash=H("c"), receipt_hash=H("z")))))
check("newest private receipt two windows ahead (gap) refused", refused(lambda: lr.restore(pre, os.path.join(tmp, "q4"), expected_sha256=pre_sha, expected_receipt_hash="0", expected_seq=0, expected_total=4, pending=dict(PEND, seq=2))))
shutil.rmtree(tmp)
print("FAILED" if FAIL else "ALL PASS"); sys.exit(1 if FAIL else 0)
