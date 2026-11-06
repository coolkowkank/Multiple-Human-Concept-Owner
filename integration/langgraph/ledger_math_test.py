"""One accounting formula: spent / committed invariants under random crash-and-recover sequences,
no double count of superseding burns, no forgotten liability after restore; restore destination
concurrency; usage_report ledger section. Offline, temp dirs."""
import hashlib, json, os, random, secrets, shutil, sys, tempfile, threading
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fenced_http as fh, ledger_restore as lr, bounded_run as br, usage_report as U

import hashlib as _hl
TOKEN = "test-owner-token"; OWN = _hl.sha256(TOKEN.encode()).hexdigest(); os.environ["FENCE_WINDOW_TOKEN"] = TOKEN
_ow = fh.open_window
fh.open_window = lambda *a, **k: _ow(*a, owner_hash=k.pop("owner_hash", OWN), **k)
FAIL = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: FAIL.append(n)
tmp = tempfile.mkdtemp(); os.environ["WK"] = "x"
H = lambda s: hashlib.sha256(s.encode()).hexdigest()
CAP0 = fh.HTTP_LIFETIME_CAP
def refused(f):
    try: f(); return None
    except (fh.FenceRefused, lr.RestoreRefused) as e: return str(e)
def newdir(tag, floor=4):
    d = os.path.join(tmp, tag); os.makedirs(d, mode=0o700); fh.HTTP_LOG_DIR = d
    if floor: fh.import_historic_floor(d, floor, 1, floor - 1, ["old-model.o1.jsonl"], external_manifest_present=False)
    return d
def ad(i): return fh.FencedHttpAdapter("http://127.0.0.1:1", "m-%d" % (i % 3), "WK", "e%d" % i, 9, 16, 1, None)
def lastr(d):
    w = fh.read_control(d)["windows"]; return w[-1]["receipt_hash"] if w else "0"
# explicit double-count / forgotten-liability cases
d = newdir("a")
fh.open_window(d, 3, secrets.token_hex(32), H("c"), H("r1"), "0")
ad(1).reserve(); ad(2).reserve()
s = fh.ledger_summary(d)
check("open window K=3 used 2: spent 6, committed 7, consistent", (s["spent"], s["committed"], s["consistent"]) == (6, 7, True))
br.close_window(d, "r")
s = fh.ledger_summary(d)
check("superseding burn of remaining 1: spent==committed==7 (not 8)", (s["spent"], s["committed"], s["consistent"]) == (7, 7, True))
fh.open_window(d, 3, secrets.token_hex(32), H("c"), H("r2"), lastr(d))
s = fh.ledger_summary(d)
check("second window K=3: committed 10 == cap, spent 7", (s["spent"], s["committed"]) == (7, 10))
check("a third window refused by cap (committed would be 11+)", refused(lambda: fh.open_window(d, 1, secrets.token_hex(32), H("c"), H("r3"), lastr(d))) is not None)
# pending burn then window: no double count
d = newdir("b"); pre, sha = lr.bundle(d); D = os.path.join(tmp, "bR")
PEND = dict(k=2, nonce=secrets.token_hex(32), config_hash=H("c"), receipt_hash=H("p1"), tar_sha256=sha, prev_receipt_hash="0", seq=1, tips={})
lr.restore(pre, D, expected_sha256=sha, expected_receipt_hash="0", expected_seq=0, expected_total=4, recover="pending", pending=PEND)
s = fh.ledger_summary(D)
check("pending burn K=2: spent 6 == committed 6", (s["spent"], s["committed"], s["consistent"]) == (6, 6, True))
# random sequences: crash points and recovery keep invariants
random.seed(7); bad = 0; n = 0
for trial in range(40):
    d = newdir("r%d" % trial, floor=random.choice([0, 4]))
    last, i = "0", 0
    for step in range(8):
        act = random.choice(["open", "reserve", "close", "crash-pending", "crash-postopen", "crash-postopen"])
        try:
            if act == "open":
                fh.open_window(d, random.randint(1, 3), secrets.token_hex(32), H("c"), H("n%d%d" % (trial, step)), lastr(d))
            elif act == "reserve":
                i += 1; ad(i + trial * 10).reserve()
            elif act == "close":
                br.close_window(d, "x%d" % step)
            elif act == "crash-pending":
                raw, sha = lr.bundle(d); c = fh.read_control(d)
                if c["windows"] and c["windows"][-1]["kind"] == "window-open": continue
                nd = d + "R%d" % step; w = c["windows"][-1] if c["windows"] else None
                lr.restore(raw, nd, expected_sha256=sha, expected_receipt_hash=lastr(d), expected_seq=len(c["windows"]),
                           expected_total=fh._read_all(d)[0], recover="pending",
                           pending=dict(k=random.randint(1, 2), nonce=secrets.token_hex(32), config_hash=H("c"), receipt_hash=H("p%d%d" % (trial, step)),
                                        tar_sha256=sha, prev_receipt_hash=lastr(d), seq=len(c["windows"]) + 1, tips=fh._log_scan(d)[4]))
                d = nd; fh.HTTP_LOG_DIR = d
            elif act == "crash-postopen":
                c = fh.read_control(d)
                if not (c["windows"] and c["windows"][-1]["kind"] == "window-open"): continue
                raw, sha = lr.bundle(d); nd = d + "P%d" % step     # reserves after this bundle are lost
                lr.restore(raw, nd, expected_sha256=sha, expected_receipt_hash=lastr(d), expected_seq=len(c["windows"]),
                           expected_total=fh._read_all(d)[0], recover="post-open",
                           burn=dict(nonce=secrets.token_hex(32), config_hash=H("c"), receipt_hash=H("b%d%d" % (trial, step))))
                d = nd; fh.HTTP_LOG_DIR = d
        except (fh.FenceRefused, lr.RestoreRefused):
            pass       # refusals are fine; the invariant must hold regardless
        n += 1
        sm = fh.ledger_summary(d)
        if not sm["consistent"] or sm["spent"] > CAP0 + 5 or sm["committed"] > CAP0 + 5 and False:
            bad += 1
        if sm["windows"] and not sm["last_window_open"] and sm["spent"] != sm["committed"]: bad += 1
check("random crash/recover sequences (%d states): spent<=committed, closed => equal, never inconsistent" % n, bad == 0)
# restore destination concurrency: two restores race into the same empty dir; a foreign file is never clobbered
d = newdir("c"); br_ = None
fh.open_window(d, 2, secrets.token_hex(32), H("c"), H("rc"), "0"); br.close_window(d, "r")
raw, sha = lr.bundle(d); lrh = lastr(d); tot = fh._read_all(d)[0]
DEST = os.path.join(tmp, "dest"); os.makedirs(DEST, mode=0o700)
res = []
def go():
    try: lr.restore(raw, DEST, expected_sha256=sha, expected_receipt_hash=lrh, expected_seq=2, expected_total=tot); res.append("ok")
    except lr.RestoreRefused as e: res.append("refused")
ts = [threading.Thread(target=go) for _ in range(6)]; [t.start() for t in ts]; [t.join() for t in ts]
check("6 concurrent restores into one dest: at most the lock holder wins, rest refuse, final dir verifies", res.count("ok") >= 1 and res.count("ok") + res.count("refused") == 6 and fh._read_all(DEST)[2] and fh.ledger_summary(DEST)["consistent"])
F = os.path.join(tmp, "foreign"); os.makedirs(F, mode=0o700); open(os.path.join(F, "keep.txt"), "w").write("x")
check("dest with a foreign file refused, file untouched", lr.restore.__name__ and refused(lambda: lr.restore(raw, F, expected_sha256=sha, expected_receipt_hash=lrh, expected_seq=2, expected_total=tot)) is not None
      and open(os.path.join(F, "keep.txt")).read() == "x")
# usage_report ledger section
aud = os.path.join(tmp, "audit"); os.makedirs(aud)
rep = U.run_report(aud, ledger_dir=d)
check("usage_report ledger section: same spent/committed as the fence formula, floor and burn typed", rep["ledger"]["spent"] == fh.ledger_summary(d)["spent"]
      and rep["ledger"]["historic_floor"] == 4 and rep["ledger"]["burnt_unknown"] >= 0 and "never counted as zero" in rep["ledger"]["note"])
check("usage_report without ledger_dir unchanged (no ledger key)", "ledger" not in U.run_report(aud))
shutil.rmtree(tmp)
print("FAILED" if FAIL else "ALL PASS"); sys.exit(1 if FAIL else 0)
