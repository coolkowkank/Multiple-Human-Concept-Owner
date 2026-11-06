"""Offline tests for carry_history (synthetic manifests only)."""
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import carry_history as ch
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
M = {"schema": "carry-history/v1", "source": "synthetic test record", "recorded_reserves": 11, "cap_at_loss": 20,
     "unknown": [{"rid": "u1", "model": "m/free", "note": "consumed, outcome unknown"}], "settled": [{"rid": "s1", "model": "n/free"}]}
v = ch.assess(M, 20, 4)
check("fits: carried 11 + 4 <= 20, unknown echoed, never executable",
      v["status"] == "fits" and v["remaining"] == 9 and v["unknown_carried"][0]["rid"] == "u1" and v["executable"] is False)
v = ch.assess(M, 10, 1)
check("origin cap 10 cannot hold 11 carried: over_cap, min cap reported, unknown kept",
      v["status"] == "over_cap" and v["min_cap_needed"] == 12 and v["remaining"] == 0 and len(v["unknown_carried"]) == 1)
check("boundary: exactly fits", ch.assess(M, 15, 4)["status"] == "fits" and ch.assess(M, 14, 4)["status"] == "over_cap")
def mut(**kw): d = json.loads(json.dumps(M)); d.update(kw); return d
for nm, m in (("wrong schema", mut(schema="x")), ("missing source", mut(source=" ")),
              ("negative reserves", mut(recorded_reserves=-1)), ("bool reserves", mut(recorded_reserves=True)),
              ("extra key (e.g. a clear/forgive flag)", mut(forgive_unknown=True)),
              ("more listed than recorded", mut(recorded_reserves=1)),
              ("duplicate rid", mut(settled=[{"rid": "u1", "model": "n/free"}])),
              ("bad rid", mut(unknown=[{"rid": "a b", "model": "m"}])),
              ("entry with extra field", mut(unknown=[{"rid": "u1", "model": "m", "cleared": True}])),
              ("not a dict", [])):
    check("refuses: " + nm, ch.assess(m, 20, 1)["status"] == "refuse")
check("bad cap/planned refused", ch.assess(M, -1, 1)["status"] == "refuse" and ch.assess(M, 20, True)["status"] == "refuse")
check("no input reduces the unknown list", len(ch.assess(mut(unknown=[]), 20, 1)["unknown_carried"]) == 0
      and len(ch.assess(M, 20, 1)["unknown_carried"]) == 1)
d = tempfile.mkdtemp(); p = os.path.join(d, "m.json"); json.dump(M, open(p, "w"))
r = subprocess.run([sys.executable, os.path.join(HERE, "carry_history.py"), p, "20", "4"], capture_output=True, text=True)
check("CLI fits exit 0, executable false in output", r.returncode == 0 and '"executable": false' in r.stdout)
r = subprocess.run([sys.executable, os.path.join(HERE, "carry_history.py"), p, "10", "4"], capture_output=True, text=True)
check("CLI over_cap exit 1", r.returncode == 1)
src = open(os.path.join(HERE, "carry_history.py")).read()
check("module never touches a ledger dir (no fenced_http/HTTP_LOG_DIR/os.makedirs/open for write)",
      "fenced_http" not in src.split('"""', 2)[2] and "makedirs" not in src and "'w'" not in src and '"w"' not in src.split('"""', 2)[2])
print("\nCARRY HISTORY TESTS:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
raise SystemExit(0 if ok else 1)
