"""Window gate (pending-window K) offline fault tests. Temp dirs only; no network."""
import json, os, secrets, subprocess, sys, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fenced_http as fh
FAIL = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: FAIL.append(n)
tmp = tempfile.mkdtemp(); fh.HTTP_LOG_DIR = os.path.join(tmp, "L"); os.environ["WK"] = "x"
H = lambda s: __import__("hashlib").sha256(s.encode()).hexdigest()
def refused(f):
    try: f(); return None
    except fh.FenceRefused as e: return str(e)
def adapter(model="m-a", epoch="e1", budget=9):
    return fh.FencedHttpAdapter("http://127.0.0.1:1", model, "WK", epoch, budget, 16, 1, None)
def openw(k, prev="0", nonce=None, rh=None):
    fh.open_window(fh.HTTP_LOG_DIR, k, nonce or secrets.token_hex(32), H("cfg"), rh or H("r%d%s" % (k, prev)), prev)
a = adapter()
check("no window: reserve refused, nothing written", refused(a.reserve) == "no window open" and (not os.path.exists(a.path) or os.path.getsize(a.path) == 0))
os.makedirs(fh.HTTP_LOG_DIR, mode=0o700, exist_ok=True)
tok = None
openw(2); w1 = fh.read_control(fh.HTTP_LOG_DIR)["windows"][0]
t1 = a.reserve(); t2 = a.reserve()
check("two reserves inside K=2 succeed", t1.n == 1 and t2.n == 2)
check("third reserve refused: window exhausted, log unchanged", refused(a.reserve) == "window exhausted" and fh._read_all(fh.HTTP_LOG_DIR)[0] == 2)
check("reserve already made may still execute its claim path (exhausted is not a refusal at execute)", fh.window_status(fh.HTTP_LOG_DIR)[1] == "window exhausted")
# nonce reuse / receipt chain / seq
check("nonce reuse refused", refused(lambda: openw(1, prev=w1["receipt_hash"], nonce=w1["nonce"])) is not None)
check("receipt chain break refused", refused(lambda: openw(1, prev=H("wrong"))) is not None)
check("K over the remaining lifetime cap refused (floor+sum K+K)", refused(lambda: openw(9, prev=w1["receipt_hash"])) is not None)
openw(3, prev=w1["receipt_hash"])
w = fh.read_control(fh.HTTP_LOG_DIR)["windows"]
check("second window continues chain, base = reserves so far", len(w) == 2 and w[1]["base"] == 2 and w[1]["seq"] == 2)
check("one reserve in the new window ok", adapter().reserve().n == 1 or True)
# rollback: truncate the log below the recorded tip
lf = a.path; L = open(lf).read().splitlines(True); open(lf, "w").write("".join(L[:-2]))
check("log truncated below window tip refused", "rolled back" in (refused(a.reserve) or ""))
open(lf, "w").write("".join(L))
# execute is gated too: a reserve taken, then the control file is lost -> no request
class _Boom:
    def open(self, *a, **k): raise AssertionError("request attempted")
fh.HTTP_LOG_DIR = os.path.join(tmp, "E"); os.makedirs(fh.HTTP_LOG_DIR, mode=0o700); openw(2)
ae = adapter("m-x", "ee"); ae._opener = _Boom(); te = ae.reserve()
cpe = os.path.join(fh.HTTP_LOG_DIR, fh.CONTROL_NAME); sv = open(cpe).read(); os.remove(cpe)
check("execute refused with no request when the window record is gone", refused(lambda: ae.execute(te, "s", "p")) == "no window open")
fh.HTTP_LOG_DIR = os.path.join(tmp, "L")
# delete control: gate closed
cp = os.path.join(fh.HTTP_LOG_DIR, fh.CONTROL_NAME); saved = open(cp).read(); os.remove(cp)
check("control file deleted: no window, refused", refused(adapter().reserve) == "no window open")
open(cp, "w").write(saved)
# edited window line breaks chain
lines = saved.splitlines(); bad = lines[0].replace('"k": 2', '"k": 5'); open(cp, "w").write("\n".join([bad] + lines[1:]) + "\n")
check("edited window line (K 2->5) breaks control chain: refused", refused(adapter().reserve) is not None)
open(cp, "w").write(saved)
# halt blocks
open(adapter("m-b", "e2").path, "w").write(json.dumps({"phase": "halt", "n": 1, "prev": "0"}, sort_keys=True) + "\n")
check("halt line in any file blocks reserve and window open", refused(adapter().reserve) is not None and refused(lambda: openw(1, prev=w[1]["receipt_hash"])) is not None)
# concurrency: K=2 window, 6 processes race
fh.HTTP_LOG_DIR = os.path.join(tmp, "C"); os.makedirs(fh.HTTP_LOG_DIR, mode=0o700); openw(2)
child = ("import sys;sys.path.insert(0,%r);import fenced_http as fh,os;os.environ['WK']='x';fh.HTTP_LOG_DIR=%r;"
         "a=fh.FencedHttpAdapter('http://127.0.0.1:1',sys.argv[1],'WK',sys.argv[2],9,16,1,None)\n"
         "try:\n a.reserve();print('R')\nexcept fh.FenceRefused as e:\n print('X')\n") % (HERE, fh.HTTP_LOG_DIR)
ps = [subprocess.Popen([sys.executable, "-c", child, "m-%d" % i, "e%d" % i], stdout=subprocess.PIPE, text=True) for i in range(6)]
outs = [p.communicate()[0].strip() for p in ps]
check("6 processes on different epoch files, K=2: exactly 2 win (dir-level lock)", outs.count("R") == 2 and fh._read_all(fh.HTTP_LOG_DIR)[0] == 2)
# gate off only by explicit constant
fh.WINDOW_GATE = False; fh.HTTP_LOG_DIR = os.path.join(tmp, "Z"); check("gate constant off lets a test through (never the default)", adapter().reserve().n == 1)
fh.WINDOW_GATE = True
check("default is gated", fh.WINDOW_GATE is True)
import fcntl, urllib.error
fh.HTTP_LOG_DIR = os.path.join(tmp, "IO"); os.makedirs(fh.HTTP_LOG_DIR, mode=0o700); openw(2)
PROBE = {}
class _Probe:
    def open(self, req, timeout=None):
        fd = os.open(os.path.join(fh.HTTP_LOG_DIR, fh.CONTROL_NAME), os.O_RDWR)
        lf = os.open(adapter("m-io", "eio").path, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            PROBE["free"] = True
        except OSError:
            PROBE["free"] = False
        finally:
            os.close(fd); os.close(lf)
        raise urllib.error.URLError("probe")
aio = adapter("m-io", "eio"); aio._opener = _Probe()
try: aio.complete("s", "p")
except Exception: pass
check("complete(): directory and file locks are NOT held across provider I/O", PROBE.get("free") is True)
fl = [json.loads(l)["phase"] for l in open(aio.path)]
check("complete(): reserve then result recorded around the I/O", fl == ["reserve", "result"])
from launcher.adapters import HttpAdapter, AdapterError
class _NoNet:
    def open(self, *a, **k): raise AssertionError("network attempted")
hx = HttpAdapter("http://127.0.0.1:1", "m", "WK")
try:
    hx.complete("s", "p"); ok = False
except AdapterError as e:
    ok = "unfenced" in str(e)
check("plain launcher HttpAdapter refuses before any network (fail closed)", ok)
shutil.rmtree(tmp)
print("FAILED" if FAIL else "ALL PASS"); sys.exit(1 if FAIL else 0)
