"""Offline tests for reserve_preflight (read-only). Synthetic logs in temp dirs
shaped like Fenced's (hash-chained reserve/result/halt lines). Never touches
~/.lg-http-usage and makes no provider calls. Logs here are written by the test,
not by Fenced; a cross-check against real Fenced writes uses a fake opener."""
import hashlib, json, os, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import reserve_preflight as rp  # noqa: E402

ok = True
def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name)
    ok = ok and bool(cond)

def mk():
    d = tempfile.mkdtemp(); os.chmod(d, 0o700); return d

def write(d, fname, entries, tamper=None):
    prev, lines = "0", []
    for e in entries:
        e = dict(e, prev=prev)
        raw = json.dumps(e, sort_keys=True).encode()
        lines.append(raw); prev = hashlib.sha256(raw).hexdigest()
    p = os.path.join(d, fname)
    open(p, "wb").write(b"".join(l + b"\n" for l in lines)); os.chmod(p, 0o600)
    return p

def rr(n, model="m/free"):
    return [{"phase": "reserve", "n": n, "model": model},
            {"phase": "result", "n": n, "model": model, "status": 200, "class": "ok-shape",
             "usage": {"cost": 0, "total_tokens": 5}, "cost_zero": True}]

M = "m-free.e1.jsonl"
def seq(k, model="m/free"):
    return [x for i in range(1, k + 1) for x in rr(i, model)]

def snap_all(d):
    return {n: os.path.getsize(os.path.join(d, n)) for n in os.listdir(d)}

tmp = []
def newdir():
    d = mk(); tmp.append(d); return d

# --- good path and read-only guarantee
d = newdir(); write(d, M, seq(3)); before = snap_all(d)
r = rp.preflight(2, log_dir=d, cap=8)
check("verified 3 of 8, plan 2 -> ok_to_plan", r["status"] == "ok_to_plan" and r["reserves_total"] == 3 and r["remaining"] == 5)
check("plan beyond remaining -> over_cap", rp.preflight(6, log_dir=d, cap=8)["status"] == "over_cap")
check("preflight wrote nothing", snap_all(d) == before and sorted(os.listdir(d)) == [M])
check("exit code semantics via main", rp.main(["--planned", "1", "--log-dir", d, "--cap", "8"]) == 0
      and rp.main(["--planned", "9", "--log-dir", d, "--cap", "8"]) == 1)

# --- reserve without result counts as spent (crash in flight)
d = newdir(); write(d, M, seq(2) + [{"phase": "reserve", "n": 3, "model": "m/free"}])
r = rp.preflight(1, log_dir=d, cap=4)
check("unmatched reserve is counted spent", r["reserves_total"] == 3 and r["files"][0]["unmatched_reserves"] == 1
      and r["remaining"] == 1 and r["status"] == "ok_to_plan")

# --- unestablished: missing / empty dir
nd = os.path.join(tempfile.gettempdir(), "no-such-ledger-xyz")
check("missing dir is unestablished, never zero spent", rp.preflight(1, log_dir=nd, cap=8)["status"] == "unestablished"
      and rp.preflight(1, log_dir=nd, cap=8)["reserves_total"] is None)
r = rp.preflight(1, log_dir=nd, cap=8, allow_fresh=True)
check("allow_fresh is an operator assertion, labelled", r["status"] == "ok_to_plan" and r.get("fresh_asserted_by_operator") is True)
check("allow_fresh cannot override an expected minimum", rp.preflight(1, log_dir=nd, cap=8, allow_fresh=True, expected_min_reserves=7)["status"] == "unestablished")
d = newdir()
check("empty existing dir is unestablished", rp.preflight(1, log_dir=d, cap=8)["status"] == "unestablished")
check("deletion vs expected 7: refuse", (lambda: (write(d, M, seq(2)), rp.preflight(1, log_dir=d, cap=8, expected_min_reserves=7)["status"])[1])() == "refuse")

# --- integrity
def refused(entries, fname=M, **kw):
    d = newdir(); write(d, fname, entries); return rp.preflight(1, log_dir=d, cap=8, **kw)
def has(r, s): return any(s in p for p in r["problems"])
check("halt line refuses", has(refused(seq(1) + [{"phase": "halt", "n": 1, "why": "x"}]), "halt"))
check("duplicate reserve n", has(refused(rr(1) + [rr(1)[0]]), "duplicate reserve"))
check("n out of sequence", has(refused(rr(1) + rr(3)), "out of sequence"))
check("result without reserve", has(refused([rr(1)[1]]), "without a prior reserve"))
check("model does not match filename", has(refused(seq(1, "other/model")), "does not match log name"))
check("bad usage numbers", has(refused([rr(1)[0], dict(rr(1)[1], usage={"cost": -1})]), "malformed usage"))
check("bool n refused", has(refused([{"phase": "reserve", "n": True, "model": "m/free"}]), "bad n"))
check("unknown phase", has(refused([{"phase": "mystery", "n": 1}]), "unknown phase"))
check("over cap recorded", has(refused(seq(9)), "exceed the cap"))
d = newdir(); p = write(d, M, seq(2)); L = open(p, "rb").read().split(b"\n")
open(p, "wb").write(b"\n".join([L[0]] + L[2:]))   # delete a middle line
check("deleted middle line breaks chain", has(rp.preflight(1, log_dir=d, cap=8), "chain broken"))
d = newdir(); p = write(d, M, seq(2)); open(p, "ab").write(b"not json\n")
check("garbage line", has(rp.preflight(1, log_dir=d, cap=8), "non-JSON"))
d = newdir(); p = write(d, M, seq(2)); open(p, "ab").write(b'{"phase": "reserve"')
check("partial last line", has(rp.preflight(1, log_dir=d, cap=8), "partial last line"))
d = newdir(); write(d, M, seq(1)); open(os.path.join(d, "notes.txt"), "w").write("x")
check("foreign file in ledger dir", has(rp.preflight(1, log_dir=d, cap=8), "unexpected non-log file"))
d = newdir(); write(d, M, seq(1)); os.symlink(os.path.join(d, M), os.path.join(d, "m-free.e2.jsonl"))
check("symlinked log refused", has(rp.preflight(1, log_dir=d, cap=8), "not a regular file"))
d = newdir(); write(d, "BadName.jsonl", seq(1))
check("bad file name", has(rp.preflight(1, log_dir=d, cap=8), "does not match slug.epoch"))
d = newdir(); write(d, M, seq(1)); os.chmod(d, 0o755)
check("group/other-accessible dir refused", has(rp.preflight(1, log_dir=d, cap=8), "accessible to group/other"))
real = newdir(); write(real, M, seq(1)); ln = os.path.join(tempfile.mkdtemp(), "lnk"); os.symlink(real, ln)
check("symlinked log dir flagged", has(rp.preflight(1, log_dir=ln, cap=8), "symlink"))
check("bad planned_calls / cap never open the gate", all(rp.preflight(x, log_dir=real, cap=8)["status"] == "refuse"
      for x in (-1, "2", True, 1.5, None)) and rp.preflight(1, log_dir=real, cap=-1)["status"] == "refuse")

# --- multiple logs: cap is across all files, like Fenced
d = newdir(); write(d, "m-free.e1.jsonl", seq(4)); write(d, "n-free.e2.jsonl", seq(3, "n/free"))
r = rp.preflight(1, log_dir=d, cap=8)
check("lifetime count spans all logs", r["reserves_total"] == 7 and r["remaining"] == 1 and r["status"] == "ok_to_plan")
check("7 of 8 + plan 2 -> over_cap", rp.preflight(2, log_dir=d, cap=8)["status"] == "over_cap")

# --- anchor: tail truncation and rewrite
d = newdir(); p = write(d, M, seq(3)); a = rp.snapshot(rp.preflight(1, log_dir=d, cap=8))
check("snapshot taken from verified result", a is not None and a["files"][M]["lines"] == 6)
check("anchor matches unchanged log", rp.preflight(1, log_dir=d, cap=8, anchor=a)["status"] == "ok_to_plan")
write(d, M, seq(3) + rr(4))   # legitimate growth keeps the anchored prefix
check("anchor accepts append-only growth", rp.preflight(1, log_dir=d, cap=8, anchor=a)["status"] == "ok_to_plan")
write(d, M, seq(2))           # valid-looking shorter log: chain is fine, tail truncated
r = rp.preflight(1, log_dir=d, cap=8, anchor=a)
check("tail truncation: invisible without anchor, refused with it",
      rp.preflight(1, log_dir=d, cap=8)["status"] == "ok_to_plan" and r["status"] == "refuse" and has(r, "tail truncation"))
write(d, M, [dict(x, status=500) if x.get("phase") == "result" else x for x in seq(3)])   # rewritten history, same length
check("rewritten history diverges from anchor", has(rp.preflight(1, log_dir=d, cap=8, anchor=a), "diverges"))
os.unlink(os.path.join(d, M)); write(d, "z-free.e9.jsonl", seq(1, "z/free"))
check("anchored log deleted/replaced", has(rp.preflight(1, log_dir=d, cap=8, anchor=a), "anchored log missing"))
check("bad anchor refused", rp.preflight(1, log_dir=d, cap=8, anchor={"schema": "x"})["status"] == "refuse")
check("snapshot of a refused result is None", rp.snapshot(refused(seq(9))) is None)

# --- CLI: a configured anchor file that is null / non-object must refuse, never read as "no anchor"
d = newdir(); write(d, M, seq(2))
for bad in ("null", "[]", '"x"', "", "{}"):
    af = os.path.join(newdir(), "a.json"); open(af, "w").write(bad)
    check("CLI anchor file %r refuses" % bad,
          rp.main(["--planned", "1", "--log-dir", d, "--cap", "8", "--anchor-file", af]) == 1)
good_snap = rp.snapshot(rp.preflight(1, log_dir=d, cap=8))
for name, bad in (("files {}", {"schema": rp.SCHEMA, "files": {}}), ("files null", {"schema": rp.SCHEMA, "files": None}),
                  ("files []", {"schema": rp.SCHEMA, "files": []}), ("no files key", {"schema": rp.SCHEMA}),
                  ("entry lines 0", {"schema": rp.SCHEMA, "files": {M: {"lines": 0, "tip_sha256": "0" * 64}}}),
                  ("entry bad tip", {"schema": rp.SCHEMA, "files": {M: {"lines": 2, "tip_sha256": "zz"}}}),
                  ("entry bool lines", {"schema": rp.SCHEMA, "files": {M: {"lines": True, "tip_sha256": "0" * 64}}})):
    af = os.path.join(newdir(), "a.json"); json.dump(bad, open(af, "w"))
    check("CLI valid-schema anchor with %s refuses" % name,
          rp.main(["--planned", "1", "--log-dir", d, "--cap", "8", "--anchor-file", af]) == 1
          and rp.preflight(1, log_dir=d, cap=8, anchor=bad)["status"] == "refuse")
# control: a well-formed anchor over a LONGER ledger than the current one is a truncation and must refuse
dt = newdir(); write(dt, M, seq(1))
af = os.path.join(newdir(), "a.json"); json.dump(good_snap, open(af, "w"))
check("CLI well-formed anchor, truncated ledger refuses", rp.main(["--planned", "1", "--log-dir", dt, "--cap", "8", "--anchor-file", af]) == 1)
check("CLI well-formed anchor, matching ledger passes", rp.main(["--planned", "1", "--log-dir", d, "--cap", "8", "--anchor-file", af]) == 0)
check("CLI missing anchor file refuses",
      rp.main(["--planned", "1", "--log-dir", d, "--cap", "8", "--anchor-file", d + "/nope.json"]) == 1)
af = os.path.join(newdir(), "a.json"); json.dump(rp.snapshot(rp.preflight(1, log_dir=d, cap=8)), open(af, "w"))
check("CLI valid anchor file passes", rp.main(["--planned", "1", "--log-dir", d, "--cap", "8", "--anchor-file", af]) == 0)

# --- advisory writer detection
import fcntl
d = newdir(); p = write(d, M, seq(1)); fh = open(p, "r+b"); fcntl.flock(fh, fcntl.LOCK_EX)
r = rp.preflight(1, log_dir=d, cap=8)
check("active writer is reported, read still works", r["files"][0]["writer_active"] is True and r["reserves_total"] == 1)
fh.close()

# --- real Fenced writes parse cleanly (cross-check against the actual writer, fake opener, no network)
import fenced_http as fh_mod
class _Resp:
    status = 200
    def __init__(s, b): s.b = b
    def read(s, n=-1): return s.b
    def __enter__(s): return s
    def __exit__(s, *a): return False
class _Op:
    def open(self, req, timeout=None):
        return _Resp(json.dumps({"choices": [{"message": {"content": json.dumps({"summary": "x"})}}],
                                 "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "cost": 0}}).encode())
d = newdir(); old = fh_mod.HTTP_LOG_DIR; fh_mod.HTTP_LOG_DIR = d
os.environ["TEST_KEY_PF"] = "k"
try:
    ad = fh_mod.FencedHttpAdapter("http://127.0.0.1:1", "m/free", "TEST_KEY_PF", "e1", 5, 10, 5, "low", opener=_Op())
    ad.complete("s", "p"); ad.complete("s", "p")
    r = rp.preflight(1, log_dir=d, cap=8)
    check("real Fenced log verifies: 2 reserves, 0 unmatched", r["status"] == "ok_to_plan" and r["reserves_total"] == 2
          and r["files"][0]["unmatched_reserves"] == 0)
    check("preflight agrees with Fenced's own count", fh_mod._read_all(d)[0] == r["reserves_total"])
finally:
    fh_mod.HTTP_LOG_DIR = old; os.environ.pop("TEST_KEY_PF", None)

# --- same-epoch accounting (resume after a mid-attempt kill)
# 9 historic reserves elsewhere + coordinator 1/3 + builder 1/4 consumed; cap 20.
d = newdir()
write(d, "old-model.h1.jsonl", seq(9, "old/model"))
write(d, "coord-m.c1.jsonl", seq(1, "coord/m"))
write(d, "build-m.b1.jsonl", [{"phase": "reserve", "n": 1, "model": "build/m", "via": "complete"}])
EB = {"coord-m.c1.jsonl": 3, "build-m.b1.jsonl": 4, "rev-m.r1.jsonl": 2, "qc-m.q1.jsonl": 2}
r = rp.preflight(11, log_dir=d, cap=20)
check("naive planned 11 vs remaining 9 -> over_cap (the old resume refusal)", r["status"] == "over_cap" and r["remaining"] == 9)
r = rp.preflight(11, log_dir=d, cap=20, epoch_budgets=EB)
check("epoch budgets charge only what remains per epoch: needed 9 -> ok_to_plan",
      r["status"] == "ok_to_plan" and r["needed_calls"] == 9 and r["remaining"] == 9)
EB2 = dict(EB, **{"rev-m.r1.jsonl": 3})
check("one more real call than remaining -> still over_cap (never lowers real demand)",
      rp.preflight(11, log_dir=d, cap=20, epoch_budgets=EB2)["status"] == "over_cap")
check("a spent epoch is not credited to another epoch file",
      rp.preflight(0, log_dir=d, cap=20, epoch_budgets={"coord-m.c2.jsonl": 3, "build-m.b1.jsonl": 4,
                   "rev-m.r1.jsonl": 3, "qc-m.q1.jsonl": 3})["needed_calls"] == 12)
check("over-spent epoch counts zero, never negative",
      rp.preflight(0, log_dir=d, cap=20, epoch_budgets={"old-model.h1.jsonl": 2})["needed_calls"] == 0)
for bad in ({}, {"x": 3}, {"coord-m.c1.jsonl": -1}, {"coord-m.c1.jsonl": True}, {"coord-m.c1.jsonl": None}, []):
    check("malformed epoch_budgets %r refuses" % (bad,), rp.preflight(1, log_dir=d, cap=20, epoch_budgets=bad)["status"] == "refuse")
write(d, "build-m.b1.jsonl", [{"phase": "reserve", "n": 1, "model": "build/m"}, {"phase": "halt", "n": 1}])
check("a halt line still refuses with epoch budgets", rp.preflight(1, log_dir=d, cap=20, epoch_budgets=EB)["status"] == "refuse")
d = newdir()
check("fresh dir, epoch budgets, allow_fresh -> needed is the sum",
      rp.preflight(5, log_dir=os.path.join(d, "none"), cap=20, allow_fresh=True, epoch_budgets=EB)["needed_calls"] == 11)
d = newdir(); write(d, "coord-m.c1.jsonl", seq(1, "coord/m"))
check("CLI: --epoch-budget accepted, exit 0", rp.main(["--planned", "9", "--log-dir", d, "--cap", "3", "--epoch-budget", "coord-m.c1.jsonl=3"]) == 0)
check("CLI: malformed budget refuses", rp.main(["--planned", "1", "--log-dir", d, "--cap", "3", "--epoch-budget", "coord-m.c1.jsonl=abc"]) == 1)
check("without epoch_budgets behaviour is unchanged (no needed_calls key effect)",
      rp.preflight(3, log_dir=d, cap=3)["status"] == "over_cap")

for t in tmp: shutil.rmtree(t, ignore_errors=True)
print("\nRESERVE PREFLIGHT TESTS:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
raise SystemExit(0 if ok else 1)
