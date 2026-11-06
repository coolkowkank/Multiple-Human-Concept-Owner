"""Offline end-to-end with EVERY guard ON (WINDOW_GATE True, typed floor, cap 12, run-bound window,
entry content hash incl. brief bytes, fresh price-0 listing, no_verify_command, one-call budget) against a
LOCAL stub router. Only HTTP_FREE_BASE is pointed at the stub, inside this process. No provider, no key.
Limit: the wrapper's process spawn is not exercised (the entry runs in-process with the run-bind helper)."""
import os; os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import hashlib, http.server, json, secrets, subprocess, sys, tempfile, threading
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import fenced_http as fh
assert fh.WINDOW_GATE is True
import langgraph_team as lt, pack, reserve_preflight as rp, bounded_run as br, window_test_support as wts
fh.HTTP_LIFETIME_CAP = 12          # the cap-12 proposal value, set in-process; the WIP constant stays 10
REPO = subprocess.run(["git", "-C", HERE, "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
COMMIT = subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
MODEL = "novita/ling-3.1-flash"; BODIES = []; REPLY = {}
FAIL = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: FAIL.append(n)
class H(http.server.BaseHTTPRequestHandler):
    def log_message(s, *a): pass
    def _send(s, b): s.send_response(200); s.send_header("content-type", "application/json"); s.end_headers(); s.wfile.write(json.dumps(b).encode())
    def do_GET(s): s._send({"data": [{"id": MODEL, "input_price": "0", "output_price": "0"}]})
    def do_POST(s):
        BODIES.append(json.loads(s.rfile.read(int(s.headers.get("content-length", 0)))))
        s._send({"id": "f", "choices": [{"message": {"content": REPLY["text"]}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0}})
tmp = tempfile.mkdtemp(); srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
lt.HTTP_FREE_BASE = "http://127.0.0.1:%d/v1" % srv.server_address[1]
TOKEN = "gate-on-token"; OWN = hashlib.sha256(TOKEN.encode()).hexdigest(); os.environ["FENCE_WINDOW_TOKEN"] = TOKEN
H_ = lambda s: hashlib.sha256(s.encode()).hexdigest()
brief, texts = pack.build(REPO, COMMIT)
sent = [s.strip() for s in texts["docs/operating-rules.md"].split("\n") if len(s.strip()) > 30][0]
assessment = json.dumps({"first_brief": "Convert units.", "gaps": [{"file": "docs/operating-rules.md", "quote": sent, "question": "Who closes the batch?"}]})
good = json.dumps({"summary": "assessed", "writes": {pack.OUT_PATH: assessment}, "verify_command": None, "handoff": "builder", "gate": None, "status_line": "assessed"})
def setup(tag, window=True, tamper_brief=False):
    L = os.path.join(tmp, "L" + tag); os.makedirs(L, mode=0o700); fh.HTTP_LOG_DIR = L
    fh.import_historic_floor(L, 11, 4, 7, ["old.e0.jsonl"], external_manifest_present=False)
    cd = os.path.join(tmp, "cfg" + tag); os.makedirs(cd); os.chmod(cd, 0o700)
    kf = os.path.join(cd, "k"); open(kf, "w").write("fake-key\n"); os.chmod(kf, 0o600)
    bf = os.path.join(cd, "brief.md"); open(bf, "wb").write(brief); os.chmod(bf, 0o600)
    c = {"key_file": kf, "brief_extra_file": bf, "stop_after": 1, "preflight": {}, "no_verify_command": True,
         "seats": {"coordinator": {"model": MODEL, "epoch": "e" + tag, "budget": 1, "max_tokens": 4096}}}
    cp = os.path.join(cd, "c.json"); open(cp, "w").write(json.dumps(c)); os.chmod(cp, 0o600)
    lane = os.path.join(tmp, "lane" + tag); lt.init_repo(lane)
    h = br.live_config_hash(lane, cp)
    if window:
        fh.open_window(L, 1, secrets.token_hex(32), h, H_("rcpt" + tag), "0", OWN); wts.bind_live_run(L)
    if tamper_brief:
        open(bf, "ab").write(b" ")
    return L, lane, cp
def go(lane, cp, tag):
    del BODIES[:]; REPLY["text"] = good
    try: rc = lt.live_entry(lane, os.path.join(tmp, "db" + tag), cp, allow_fresh=True)
    except SystemExit as e: rc = "exit:%s" % e.code
    return rc
os.environ.pop(fh.RUN_ID_ENV, None)
L, lane, cp = setup("a", window=False); rc = go(lane, cp, "a")
check("no window: the entry refuses before any request (gate ON)", str(rc).startswith("exit:") and not BODIES)
L, lane, cp = setup("b"); rc = go(lane, cp, "b")
check("window open, run-bound, exact bytes: one POST, graceful stop, assessment written and scored pass", rc == 0 and len(BODIES) == 1 and pack.score(pack.read_output(lane) or "", texts)["pass"])
s = fh.ledger_summary(L)
check("ledger: floor 11 + exactly 1 reserve = 12 spent, committed 12, consistent (K=1 window consumed)", (s["spent"], s["committed"], s["consistent"]) == (12, 12, True))
del BODIES[:]; REPLY["text"] = good
lane_b = os.path.join(tmp, "laneb")
try: lt.live_entry(lane_b, os.path.join(tmp, "dbb2"), os.path.join(tmp, "cfgb", "c.json"), allow_fresh=True); rerun = "returned"
except SystemExit as ex: rerun = str(ex.code)
check("a second entry in the same consumed window: refused, no further POST: " + rerun[:90], not BODIES and rerun.startswith("refused"))
br.close_window(L, "run")
check("typed close after the run: no window open, spent == committed == 12", fh.window_status(L)[1] == "no window open" and fh.ledger_summary(L)["spent"] == 12 == fh.ledger_summary(L)["committed"])
try:
    fh.open_window(L, 1, secrets.token_hex(32), H_("cfg"), H_("r2"), fh.read_control(L)["windows"][-1]["receipt_hash"], OWN); again = True
except fh.FenceRefused: again = False
check("a second K=1 window cannot open (cap 12 reached)", again is False)
L, lane, cp = setup("c", tamper_brief=True); rc = go(lane, cp, "c")
check("brief edited after the window opened: entry refuses (content hash), no POST", str(rc).startswith("exit:") and not BODIES)
print("LIMITS: the wrapper's real spawn/process-tree path is not run here; the entry runs in-process with the run-bind helper.")
print("FAILED" if FAIL else "ALL PASS"); sys.exit(1 if FAIL else 0)
