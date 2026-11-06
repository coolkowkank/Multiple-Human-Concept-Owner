"""Wrapper pre-spawn window gate: offline tests, argv is a harmless touch."""
import hashlib, json, os, secrets, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bounded_run as br, fenced_http as fh
FAIL = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: FAIL.append(n)
tmp = tempfile.mkdtemp(); os.environ["WK"] = "x"
def mk(tag):
    d = os.path.join(tmp, tag); os.makedirs(d, mode=0o700); return d
L = mk("L"); fh.HTTP_LOG_DIR = L
nonce = secrets.token_hex(32); CFG = hashlib.sha256(b"cfg").hexdigest()
MARK = os.path.join(mk("m"), "ran"); touch = [sys.executable, "-c", "open(%r,'w').write('x')" % MARK]
def mkreceipt(**kw):
    r = {"kind": "pending-window", "seq": 1, "k": 2, "nonce": nonce, "config_hash": CFG, "prev_receipt_hash": "0",
         "argv_sha256": hashlib.sha256("\0".join(touch).encode()).hexdigest(), "planned": 1, "note": "synthetic test receipt"}
    r.update(kw); return json.dumps(r, sort_keys=True).encode()
receipt = mkreceipt(); rh = hashlib.sha256(receipt).hexdigest()
def run(st, planned=1):
    return br.run(st, touch, 5, planned=planned, log_dir=L, cap=fh.HTTP_LIFETIME_CAP)
st = mk("S1")
fh.open_window(L, 2, nonce, CFG, rh, "0")
a = fh.FencedHttpAdapter("http://127.0.0.1:1", "m-a", "WK", "e1", 9, 16, 1, None); a.reserve()
r = run(st)
check("window open but receipt missing locally: refused, no spawn", r[0] == "refused" and "receipt missing" in r[1]["reason"] and not os.path.exists(MARK))
open(os.path.join(st, "window-receipt-%s.json" % nonce), "wb").write(b"tampered")
r = run(st)
check("receipt hash mismatch refused", r[0] == "refused" and "hash does not match" in r[1]["reason"] and not os.path.exists(MARK))
# receipts whose own hash matches the window line cannot be swapped, so test field binding with a second window dir
for tag, kw in (("argv", dict(argv_sha256="0" * 64)), ("planned", dict(planned=2)), ("kind", dict(kind="x"))):
    L2 = mk("F" + tag); fh.HTTP_LOG_DIR = L2
    rc = mkreceipt(**kw); fh.open_window(L2, 2, nonce, CFG, hashlib.sha256(rc).hexdigest(), "0")
    fh.FencedHttpAdapter("http://127.0.0.1:1", "m-a", "WK", "e1", 9, 16, 1, None).reserve()
    s2 = mk("FS" + tag); open(os.path.join(s2, "window-receipt-%s.json" % nonce), "wb").write(rc)
    r = br.run(s2, touch, 5, planned=1, log_dir=L2, cap=fh.HTTP_LIFETIME_CAP)
    check("receipt field binding refuses (%s) with matching hash, no spawn" % tag, r[0] == "refused" and "window gate" in r[1]["reason"] and not os.path.exists(MARK))
for tag, kw in (("seq", dict(seq=2)), ("k", dict(k=3)), ("config", dict(config_hash="1" * 64)), ("prev", dict(prev_receipt_hash="2" * 64))):
    L2 = mk("G" + tag); fh.HTTP_LOG_DIR = L2
    rc = mkreceipt(**kw); fh.open_window(L2, 2, nonce, CFG, hashlib.sha256(rc).hexdigest(), "0")
    fh.FencedHttpAdapter("http://127.0.0.1:1", "m-a", "WK", "e1", 9, 16, 1, None).reserve()
    s2 = mk("GS" + tag); open(os.path.join(s2, "window-receipt-%s.json" % nonce), "wb").write(rc)
    r = br.run(s2, touch, 5, planned=1, log_dir=L2, cap=fh.HTTP_LIFETIME_CAP)
    check("receipt window-line binding refuses (%s)" % tag, r[0] == "refused" and "differs" in r[1]["reason"] and not os.path.exists(MARK))
fh.HTTP_LOG_DIR = L
open(os.path.join(st, "window-receipt-%s.json" % nonce), "wb").write(receipt)
r = run(st, planned=2)
check("planned beyond the window's remaining refused", r[0] == "refused" and "remaining" in r[1]["reason"] and not os.path.exists(MARK))
r = run(st, planned=1)
check("matching parsed receipt + room: spawns", r[0] == "clean" and os.path.exists(MARK))
os.remove(MARK)
check("after the tree is dead the window is typed-closed (remaining K burnt, nothing reusable)",
      fh.read_control(L)["windows"][-1]["kind"] == "window-burn" and fh.window_status(L)[1] == "no window open")
r = run(mk("S2"), planned=1)
check("closed window refused before spawn (direct live cannot reuse it)", r[0] == "refused" and not os.path.exists(MARK))
cp = os.path.join(L, fh.CONTROL_NAME); sv = open(cp).read(); os.remove(cp)
r = run(mk("S3"), planned=1)
check("control file gone: refused (no window)", r[0] == "refused" and not os.path.exists(MARK))
open(cp, "w").write(sv)
shutil.rmtree(tmp)
print("FAILED" if FAIL else "ALL PASS"); sys.exit(1 if FAIL else 0)
