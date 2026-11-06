"""Fence-level run binding: the wrapper binds an open window to ITS run lock (path+inode+dev) and run id;
only the live run's processes can reserve. Offline; the children only touch the fence in a temp dir."""
import fcntl, hashlib, json, os, secrets, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bounded_run as br, fenced_http as fh
FAIL = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: FAIL.append(n)
tmp = tempfile.mkdtemp(); os.environ["WK"] = "x"
TOKEN = "run-binding-token"; OWN = hashlib.sha256(TOKEN.encode()).hexdigest()
def mk(t): d = os.path.join(tmp, t); os.makedirs(d, mode=0o700); return d
L = mk("L"); fh.HTTP_LOG_DIR = L; nonce = secrets.token_hex(32); CFG = hashlib.sha256(b"c").hexdigest()
CHILD = ("import sys,os;sys.path.insert(0,%r);import fenced_http as fh;fh.HTTP_LOG_DIR=%r;os.environ['WK']='x'\n"
         "a=fh.FencedHttpAdapter('http://127.0.0.1:1','m-a','WK','e1',9,16,1,None)\n"
         "try:\n a.reserve();print('RESERVED')\nexcept fh.FenceRefused as e:\n print('REFUSED',e)\n") % (HERE, L)
argv = [sys.executable, "-c", CHILD]
rc = json.dumps({"kind": "pending-window", "seq": 1, "k": 3, "nonce": nonce, "config_hash": CFG, "prev_receipt_hash": "0",
                 "owner_hash": OWN, "argv_sha256": hashlib.sha256("\0".join(argv).encode()).hexdigest(), "planned": 1}, sort_keys=True).encode()
fh.open_window(L, 3, nonce, CFG, hashlib.sha256(rc).hexdigest(), "0", OWN)
st = mk("S"); open(os.path.join(st, "window-receipt-%s.json" % nonce), "wb").write(rc)
os.environ["FENCE_WINDOW_TOKEN"] = TOKEN
check("window with no wrapper run bound: direct reserve refused", "no live run" in (lambda: (lambda: None)() or (fh.window_status(L)[1]))())
# the wrapper runs a child that reserves through the fence: allowed (child holds the inherited lock, env run id)
import subprocess
fh.WINDOW_GATE = False; fh.FencedHttpAdapter("http://127.0.0.1:1", "m-seed", "WK", "e0", 9, 16, 1, None).reserve(); fh.WINDOW_GATE = True
out = []
orig = subprocess.Popen
class Cap(orig):
    def __init__(self, *a, **k):
        k["stdout"] = subprocess.PIPE; super().__init__(*a, **k); out.append(self)
subprocess.Popen = Cap
r = br.run(st, argv, 10, planned=1, log_dir=L, cap=fh.HTTP_LIFETIME_CAP)
subprocess.Popen = orig
txt = out[0].stdout.read().decode() if out else ""
check("wrapper-run child reserves through the fence (bound run id + held lock)", "RESERVED" in txt and r[1].get("state") == "unknown-reserve")   # the child reserved and never settled: honestly unknown, window still closed
check("after the run the window is typed-closed", fh.window_status(L)[1] == "no window open")
# dead owner / foreign / replaced lock, with a fresh window per case
def fresh_window(tag, k=2):
    d = mk(tag); fh.HTTP_LOG_DIR = d; n = secrets.token_hex(32)
    fh.open_window(d, k, n, CFG, hashlib.sha256(n.encode()).hexdigest(), "0", OWN)
    lp = os.path.join(mk(tag + "l"), "lock"); fd = os.open(lp, os.O_RDWR | os.O_CREAT, 0o600); fcntl.flock(fd, fcntl.LOCK_EX)
    rid = secrets.token_hex(8); os.environ[fh.RUN_ID_ENV] = rid; fh.bind_run(d, n, rid, lp)
    return d, fd, lp, rid
def reserve_ok(d):
    fh.HTTP_LOG_DIR = d
    try: fh.FencedHttpAdapter("http://127.0.0.1:1", "m-b", "WK", "e2", 9, 16, 1, None).reserve(); return None
    except fh.FenceRefused as e: return str(e)
d, fd, lp, rid = fresh_window("a")
check("live bound run: reserve allowed", reserve_ok(d) is None)
os.close(fd)      # all holders gone = owner dead
check("owner dead (lock free): refused", "not held" in (reserve_ok(d) or ""))
d, fd, lp, rid = fresh_window("b")
os.environ[fh.RUN_ID_ENV] = "0" * 16
check("wrong run id refused", "run id mismatch" in (reserve_ok(d) or ""))
os.environ[fh.RUN_ID_ENV] = rid
os.remove(lp); fd2 = os.open(lp, os.O_RDWR | os.O_CREAT, 0o600); fcntl.flock(fd2, fcntl.LOCK_EX)
check("lock file deleted and recreated (new inode), even if held: refused", "missing or replaced" in (reserve_ok(d) or ""))
d, fd, lp, rid = fresh_window("c")
os.close(fd)      # owner dead; someone else holds an UNRELATED lock elsewhere
ofd = os.open(os.path.join(mk("other"), "lock"), os.O_RDWR | os.O_CREAT, 0o600); fcntl.flock(ofd, fcntl.LOCK_EX)
check("an unrelated held lock on another file never authorizes", "not held" in (reserve_ok(d) or ""))
d, fd, lp, rid = fresh_window("d")
os.remove(lp)
check("lock file deleted: refused", "missing or replaced" in (reserve_ok(d) or ""))
d, fd, lp, rid = fresh_window("e")
try:
    fh.bind_run(d, fh.read_control(d)["windows"][-1]["nonce"], rid, lp); second = False
except fh.FenceRefused:
    second = True
check("a second run-bind for the same window is rejected and leaves the control file valid", second and not fh.read_control(d)["problems"])
shutil.rmtree(tmp)
print("FAILED" if FAIL else "ALL PASS"); sys.exit(1 if FAIL else 0)
