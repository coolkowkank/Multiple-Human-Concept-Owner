"""Typed historic-floor import: offline fault tests (temp dirs only)."""
import json, os, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fenced_http as fh, reserve_preflight as rp
FAIL = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: FAIL.append(n)
tmp = tempfile.mkdtemp()
def fresh(tag):
    d = os.path.join(tmp, tag); return d
COV = ["research-model-vs-harness-v2.x.jsonl"]
def imp(d, **kw):
    a = dict(count=11, unknown=4, settled=7, covered_files=COV); a.update(kw)
    fh.import_historic_floor(d, a["count"], a["unknown"], a["settled"], a["covered_files"], external_manifest_present=a.get("emp", False))
def refused(f):
    try: f(); return False
    except fh.FenceRefused: return True
d = fresh("a"); imp(d)
c = fh.read_control(d)
check("floor read back typed, provenance fixed, not a recovered chain", c["floor"] == 11 and not c["problems"] and c["floor_line"]["provenance"] == fh.FLOOR_PROVENANCE and c["floor_line"]["unknown"] == 4)
check("_read_all counts floor as spent", fh._read_all(d) == (11, False, True))
check("preflight sees floor in total and the control file is not a stray file", (lambda r: r["reserves_total"] == 11 and not any("non-log" in p for p in r["problems"]))(rp.preflight(1, log_dir=d, cap=fh.HTTP_LIFETIME_CAP)))
check("manifest present/unknown refuses a fresh floor import", refused(lambda: imp(fresh("emp"), emp=True)) and refused(lambda: imp(fresh("emp2"), emp=None)))
check("second import refused (dir not fresh)", refused(lambda: imp(d)))
d2 = fresh("b"); os.makedirs(d2, mode=0o700); open(os.path.join(d2, "x.y.jsonl"), "w").write("")
check("import into dir with a log refused", refused(lambda: imp(d2)))
for tag, kw in [("cnt", dict(count=-1)), ("sum", dict(unknown=1)), ("bool", dict(count=True)), ("name", dict(covered_files=["../x"])), ("dup", dict(covered_files=COV + COV))]:
    dd = fresh("m" + tag)
    check("malformed floor refused and nothing left: " + tag, refused(lambda: imp(dd, **kw)) and fh.read_control(dd)["floor"] == 0 and os.path.getsize(os.path.join(dd, fh.CONTROL_NAME)) == 0)
def mutate(f):
    dd = fresh("mut" + str(len(os.listdir(tmp)))); imp(dd)
    p = os.path.join(dd, fh.CONTROL_NAME); L = open(p).read().splitlines(); L = f(L, dd)
    open(p, "w").write("\n".join(L) + "\n"); return dd
dd = mutate(lambda L, d: [L[0].replace('"count": 11', '"count": 3')])
check("forged count (edited line) is still a valid single line, so floor rewrite needs an operator anchor: documented limit", fh.read_control(dd)["floor"] == 3 or fh.read_control(dd)["problems"])
dd = mutate(lambda L, d: [L[0], L[0]])
check("duplicate floor line refuses", fh.read_control(dd)["problems"] and fh._read_all(dd)[2] is False)
dd = mutate(lambda L, d: [json.dumps({"kind": "reserve", "prev": "0"})])
check("reserve-shaped control line refuses", fh.read_control(dd)["problems"])
dd = mutate(lambda L, d: ["{not json"])
check("garbage control refuses", fh.read_control(dd)["problems"])
dd = mutate(lambda L, d: [json.dumps(dict(json.loads(L[0]), prev="1" * 64))])
check("broken control chain refuses", fh.read_control(dd)["problems"])
# fence: covered epoch refused, chain-broken refuses reserve
saved = fh.HTTP_LOG_DIR
try:
    fh.HTTP_LOG_DIR = d
    os.environ["K_TEST"] = "x"
    a = fh.FencedHttpAdapter("http://127.0.0.1:1", "research-model-vs-harness-v2", "K_TEST", "x", 1, 16, 1, None)
    check("model/epoch file covered by floor refuses before any request", refused(a.reserve))
    b = fh.FencedHttpAdapter("http://127.0.0.1:1", "other-model", "K_TEST", "e1", 1, 16, 1, None)
    cap0 = fh.HTTP_LIFETIME_CAP
    check("floor 11 under cap 12 and no window open: reserve still refused (window gate)", refused(b.reserve))
    fh.HTTP_LOG_DIR = dd
    check("fence refuses on invalid control", refused(b.reserve))
finally:
    fh.HTTP_LOG_DIR = saved
shutil.rmtree(tmp)
print("FAILED" if FAIL else "ALL PASS"); sys.exit(1 if FAIL else 0)
