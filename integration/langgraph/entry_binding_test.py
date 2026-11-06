"""Entry-read config+roster byte binding. Offline: calls _bind_entry_content and live_entry's first lines only."""
import fcntl, hashlib, json, os, secrets, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fenced_http as fh, reserve_preflight as rp, langgraph_team as lt, bounded_run as br
import window_test_support as wts
FAIL = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: FAIL.append(n)
tmp = tempfile.mkdtemp(); os.environ["WK"] = "x"
TOKEN = "entry-token"; OWN = hashlib.sha256(TOKEN.encode()).hexdigest(); os.environ["FENCE_WINDOW_TOKEN"] = TOKEN
L = os.path.join(tmp, "L"); os.makedirs(L, mode=0o700); fh.HTTP_LOG_DIR = L
roster = json.dumps({"seats": {"s1": {"adapter": {"type": "http", "model": "m/x", "log_epoch": "e1", "call_budget": 1}}}}).encode()
cfg = json.dumps({"seats": {"s1": {"model": "m/x", "epoch": "e1", "budget": 1}}}).encode()
def refused(f):
    try: f(); return None
    except SystemExit as e: return str(e)
check("no window: entry refuses before any work", "window gate" in (refused(lambda: lt._bind_entry_content(cfg, roster)) or ""))
h = rp.entry_content_hash(cfg, roster)
n = secrets.token_hex(32); fh.open_window(L, 1, n, h, hashlib.sha256(b"r").hexdigest(), "0", OWN)
check("window open but no live run bound: refuses", "window gate" in (refused(lambda: lt._bind_entry_content(cfg, roster)) or ""))
wts.bind_live_run(L)
check("exact bytes: accepted", refused(lambda: lt._bind_entry_content(cfg, roster)) is None)
check("one extra byte in config: refused", "differ" in (refused(lambda: lt._bind_entry_content(cfg + b" ", roster)) or ""))
check("one extra byte in roster: refused", "differ" in (refused(lambda: lt._bind_entry_content(cfg, roster + b" ")) or ""))
check("same JSON, different bytes (key order/whitespace): refused", "differ" in (refused(lambda: lt._bind_entry_content(json.dumps(json.loads(cfg), indent=1).encode(), roster)) or ""))
check("wrapper and entry compute the same hash", h == rp.entry_content_hash(cfg, roster))
lane = os.path.join(tmp, "lane"); os.makedirs(os.path.join(lane, ".team")); open(os.path.join(lane, ".team", "roster.json"), "wb").write(roster)
cp = os.path.join(tmp, "cfg.json"); open(cp, "wb").write(cfg)
check("bounded_run.live_config_hash equals the entry's hash", br.live_config_hash(lane, cp) == h)
# brief_extra_file binding
bf = os.path.join(tmp, "brief.txt"); open(bf, "wb").write(b"task: assess docs"); os.chmod(bf, 0o600)
cfgb = json.dumps({"seats": {"s1": {"model": "m/x", "epoch": "e1", "budget": 1}}, "brief_extra_file": bf}).encode()
hb = rp.entry_content_hash(cfgb, roster, b"task: assess docs")
check("brief bytes change the hash; no-brief differs from empty brief", hb != rp.entry_content_hash(cfgb, roster, b"task: assess docs!") and rp.entry_content_hash(cfg, roster) != rp.entry_content_hash(cfg, roster, b""))
open(cp, "wb").write(cfgb)
check("wrapper hash reads the brief file bytes", br.live_config_hash(lane, cp) == hb)
open(bf, "wb").write(b"task: DIFFERENT"); check("brief edited after window open: wrapper hash changes", br.live_config_hash(lane, cp) != hb)
open(bf, "wb").write(b"task: assess docs")
check("entry bind: window hash without brief refuses entry that reads a brief", "differ" in (refused(lambda: lt._bind_entry_content(cfgb, roster, b"task: assess docs")) or ""))
def refused_any(f):
    try: f(); return None
    except Exception as e: return type(e).__name__
# bounded private read (shared by wrapper and entry)
def verr(f):
    try: f(); return None
    except ValueError as e: return str(e)
rd = lambda p: rp.read_private_regular(p, "brief_extra_file", 16384)
check("read ok on exact bytes", rd(bf) == b"task: assess docs")
fifo = os.path.join(tmp, "fifo"); os.mkfifo(fifo, 0o600)
import time as _t; t0 = _t.time(); r = verr(lambda: rd(fifo))
check("FIFO refused without blocking", r and "regular" in r and _t.time() - t0 < 2)
sl = os.path.join(tmp, "sl"); os.symlink(bf, sl); check("symlink refused (not followed)", "regular" in (verr(lambda: rd(sl)) or ""))
check("relative path refused", "absolute" in (verr(lambda: rd("brief.txt")) or ""))
check("missing file -> clean ValueError, not FileNotFoundError", "cannot be read" in (verr(lambda: rd(os.path.join(tmp, "nope"))) or ""))
big = os.path.join(tmp, "big"); open(big, "wb").write(b"x" * 16385); os.chmod(big, 0o600); check("over 16384 bytes refused", "over" in (verr(lambda: rd(big)) or ""))
ok16 = os.path.join(tmp, "ok16"); open(ok16, "wb").write(b"x" * 16384); os.chmod(ok16, 0o600); check("exactly 16384 accepted", len(rd(ok16)) == 16384)
wm = os.path.join(tmp, "wm"); open(wm, "wb").write(b"x"); os.chmod(wm, 0o644); check("mode beyond 0600 refused", "0600" in (verr(lambda: rd(wm)) or ""))
cfgf = json.dumps({"seats": {"s1": {"model": "m/x", "epoch": "e1", "budget": 1}}, "brief_extra_file": fifo}).encode(); open(cp, "wb").write(cfgf)
t0 = _t.time(); w = refused_any(lambda: br.live_config_hash(lane, cp)); check("wrapper hash over a FIFO brief: clean ValueError, no block", w == "ValueError" and _t.time() - t0 < 2)
# entry: missing / relative brief -> clean SystemExit before any other work
for nm, path in (("missing", os.path.join(tmp, "gone")), ("relative", "brief.txt"), ("fifo", fifo)):
    cx = json.dumps({"seats": {"s1": {"model": "m/x", "epoch": "e1", "budget": 1}}, "brief_extra_file": path}).encode()
    cpx = os.path.join(tmp, "cx.json"); open(cpx, "wb").write(cx); os.chmod(cpx, 0o600)
    t0 = _t.time(); m = refused(lambda: lt.live_entry(lane, os.path.join(tmp, "dbx"), cpx))
    check("live_entry %s brief: clean SystemExit, no block" % nm, m and m.startswith("refused") and _t.time() - t0 < 2)
shutil.rmtree(tmp)
print("FAILED" if FAIL else "ALL PASS"); sys.exit(1 if FAIL else 0)
