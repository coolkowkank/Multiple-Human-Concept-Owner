"""PROPOSAL (not applied to the WIP branch): with HTTP_LIFETIME_CAP = 12 and the typed floor 11, exactly one K=1 window can ever open."""
import hashlib, os, secrets, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fenced_http as fh, bounded_run as br
import window_test_support as wts
FAIL = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: FAIL.append(n)
def refused(f):
    try: f(); return None
    except fh.FenceRefused as e: return str(e)
TOKEN = "cap12-token"; OWN = hashlib.sha256(TOKEN.encode()).hexdigest(); os.environ["FENCE_WINDOW_TOKEN"] = TOKEN; os.environ["WK"] = "x"
H = lambda s: hashlib.sha256(s.encode()).hexdigest()
tmp = tempfile.mkdtemp(); d = os.path.join(tmp, "L"); os.makedirs(d, mode=0o700); fh.HTTP_LOG_DIR = d
check("cap constant is 12", fh.HTTP_LIFETIME_CAP == 12)
fh.import_historic_floor(d, 11, 4, 7, ["research-model-vs-harness-v2.x.jsonl"], external_manifest_present=False)
check("K=2 refused (11+2 > 12)", refused(lambda: fh.open_window(d, 2, secrets.token_hex(32), H("c"), H("r0"), "0", OWN)) is not None)
fh.open_window(d, 1, secrets.token_hex(32), H("c"), H("r1"), "0", OWN); wts.bind_live_run(d)
a = fh.FencedHttpAdapter("http://127.0.0.1:1", "m-a", "WK", "e1", 9, 16, 1, None)
check("exactly one reserve inside the K=1 window", a.reserve().n == 1 and "exhausted" in (refused(a.reserve) or ""))
br.close_window(d, "r")
s = fh.ledger_summary(d)
check("after close: spent == committed == 12, consistent, not over cap", (s["spent"], s["committed"], s["consistent"], s["over_cap"]) == (12, 12, True, False))
check("no second window of any K can ever open", refused(lambda: fh.open_window(d, 1, secrets.token_hex(32), H("c"), H("r2"), fh.read_control(d)["windows"][-1]["receipt_hash"], OWN)) is not None)
shutil.rmtree(tmp)
print("FAILED" if FAIL else "ALL PASS"); sys.exit(1 if FAIL else 0)
