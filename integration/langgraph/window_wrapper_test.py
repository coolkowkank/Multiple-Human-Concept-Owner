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
receipt = b'{"kind":"pending-window","k":2,"note":"synthetic test receipt"}'
rh = hashlib.sha256(receipt).hexdigest(); nonce = secrets.token_hex(32)
MARK = os.path.join(mk("m"), "ran"); touch = [sys.executable, "-c", "open(%r,'w').write('x')" % MARK]
def run(st, planned=1):
    return br.run(st, touch, 5, planned=planned, log_dir=L, cap=fh.HTTP_LIFETIME_CAP)
st = mk("S1")
fh.open_window(L, 2, nonce, hashlib.sha256(b"cfg").hexdigest(), rh, "0")
a = fh.FencedHttpAdapter("http://127.0.0.1:1", "m-a", "WK", "e1", 9, 16, 1, None); a.reserve()
r = run(st)
check("window open but receipt missing locally: refused, no spawn", r[0] == "refused" and "receipt missing" in r[1]["reason"] and not os.path.exists(MARK))
open(os.path.join(st, "window-receipt-%s.json" % nonce), "wb").write(b"tampered")
r = run(st)
check("receipt hash mismatch refused", r[0] == "refused" and "hash does not match" in r[1]["reason"] and not os.path.exists(MARK))
open(os.path.join(st, "window-receipt-%s.json" % nonce), "wb").write(receipt)
r = run(st, planned=2)
check("planned beyond the window's remaining refused", r[0] == "refused" and "remaining" in r[1]["reason"] and not os.path.exists(MARK))
r = run(st, planned=1)
check("matching receipt + room: spawns", r[0] == "clean" and os.path.exists(MARK))
os.remove(MARK); a.reserve()   # window now exhausted
r = run(mk("S2"), planned=1)
check("exhausted window refused before spawn", r[0] == "refused" and "exhausted" in r[1]["reason"] and not os.path.exists(MARK))
cp = os.path.join(L, fh.CONTROL_NAME); sv = open(cp).read(); os.remove(cp)
r = run(mk("S3"), planned=1)
check("control file gone: refused (no window)", r[0] == "refused" and not os.path.exists(MARK))
open(cp, "w").write(sv)
shutil.rmtree(tmp)
print("FAILED" if FAIL else "ALL PASS"); sys.exit(1 if FAIL else 0)
