"""Offline tests for bounded_run. Scratch dirs, fake children, no provider, no
network, no live ledger, no real ~/.lg-http-usage. Every spawned process is
reaped or killed by this test."""
import hashlib, json, os, shutil, signal, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bounded_run as br  # noqa: E402

ok = True
def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name, flush=True); ok = ok and bool(cond)

tmps = []
def mk():
    d = tempfile.mkdtemp(); os.chmod(d, 0o700); tmps.append(d); return d
def write_log(d, fname, entries):
    prev, out = "0", b""
    for e in entries:
        raw = json.dumps(dict(e, prev=prev), sort_keys=True).encode()
        out += raw + b"\n"; prev = hashlib.sha256(raw).hexdigest()
    p = os.path.join(d, fname); open(p, "wb").write(out); os.chmod(p, 0o600)
LOG = "m-free.e1.jsonl"
def ledger(n_done=1):
    d = mk(); es = []
    for i in range(1, n_done + 1):
        es += [{"phase": "reserve", "n": i, "model": "m/free", "via": "complete"},
               {"phase": "result", "n": i, "model": "m/free", "status": 200, "class": "ok-shape",
                "usage": {"cost": 0}, "cost_zero": True}]
    write_log(d, LOG, es); return d

# child-side ledger appender (chained, flock) as source text
APPEND = r'''
import hashlib, json, os, fcntl, sys
p = os.path.join(sys.argv[1], "m-free.e1.jsonl")
def add(e):
    fh = open(p, "r+b"); fcntl.flock(fh, fcntl.LOCK_EX)
    lines = [l for l in fh.read().split(b"\n") if l.strip()]
    prev = hashlib.sha256(lines[-1]).hexdigest() if lines else "0"
    fh.seek(0, 2); fh.write((json.dumps(dict(e, prev=prev), sort_keys=True) + "\n").encode()); fh.flush(); os.fsync(fh.fileno()); fh.close()
def n_res(): return sum(1 for l in open(p, "rb") if b'"phase": "reserve"' in l)
'''
def py(code, *args):
    return [sys.executable, "-c", APPEND + code, *args]

def W(state, argv, deadline, **kw):
    kw.setdefault("planned", 1)
    return br.run(state, argv, deadline, **kw)

# ---- gates before spawn
st, L = mk(), ledger(1); MARK = os.path.join(mk(), "ran")
touch = [sys.executable, "-c", "open(%r,'w').write('x')" % MARK]
r = W(st, touch, 5, log_dir=L, cap=5)
check("clean child: outcome clean, state clean, ran", r[0] == "clean" and os.path.exists(MARK)
      and br._read_state(st)[0]["state"] == "clean")
check("no tmp leftovers in state dir", not [f for f in os.listdir(st) if f.endswith(".tmp")])
os.remove(MARK)
r = W(st, touch, 5, log_dir=L, cap=1)
check("preflight over_cap refuses and spawns nothing", r[0] == "refused" and "over_cap" in r[1]["reason"] and not os.path.exists(MARK))
r = W(st, touch, 5, log_dir=mk(), cap=5)
check("empty ledger dir (unestablished) refuses, nothing spawned", r[0] == "refused" and not os.path.exists(MARK))
check("missing preflight inputs refuse", br.run(st, touch, 5, log_dir=L, cap=5)[0] == "refused" and not os.path.exists(MARK))
for bad in (0, -1, br.MAX_DEADLINE + 1, True, "5"):
    check("deadline %r refused" % (bad,), W(st, touch, bad, log_dir=L, cap=5)[0] == "refused")
check("empty argv refused", W(st, [], 5, log_dir=L, cap=5)[0] == "refused")
check("nothing ran through any refusal", not os.path.exists(MARK))
bad_st = mk(); os.chmod(bad_st, 0o755)
check("state dir with group/other access refused", W(bad_st, touch, 5, log_dir=L, cap=5)[0] == "refused")
real = mk(); lnk = os.path.join(mk(), "lnk"); os.symlink(real, lnk)
check("symlinked state dir refused", W(lnk, touch, 5, log_dir=L, cap=5)[0] == "refused")
cs = mk(); open(os.path.join(cs, "state.json"), "w").write("{not json")
check("corrupt state.json refuses", W(cs, touch, 5, log_dir=L, cap=5)[0] == "refused" and not os.path.exists(MARK))

# ---- marker is durable before the child runs
st, L = mk(), ledger(1); out = os.path.join(mk(), "seen")
code = "import json,sys;open(sys.argv[2],'w').write(open(os.path.join(sys.argv[3],'state.json')).read())"
r = W(st, py("pass\n" + code, L, out, st), 5, log_dir=L, cap=5)
seen = json.load(open(out))
check("marker existed (starting/running) before the child's first line, with wrapper pid + argv hash",
      seen["state"] in ("starting", "running") and seen["wrapper_pid"] == os.getpid() and len(seen["argv_sha256"]) == 64)

# ---- deadline, TERM ignore, group kill, block until cleared
st, L = mk(), ledger(1)
t0 = time.monotonic(); r = W(st, [sys.executable, "-c", "import time; time.sleep(60)"], 1.5, log_dir=L, cap=5)
check("deadline kill: outcome timeout, elapsed bounded", r[0] == "timeout" and time.monotonic() - t0 < 1.5 + br.TERM_GRACE + 3)
check("timeout leaves non-clean state", br._read_state(st)[0]["state"] == "timeout-killed")
MARK2 = os.path.join(mk(), "ran2"); touch2 = [sys.executable, "-c", "open(%r,'w').write('x')" % MARK2]
check("next start refused without spawning", W(st, touch2, 5, log_dir=L, cap=5)[0] == "refused" and not os.path.exists(MARK2))
check("clear needs a real reason", br.clear(st, "x")[0] is False)
check("clear with reason works, then run allowed", br.clear(st, "operator read preflight, lane untouched")[0]
      and W(st, touch2, 5, log_dir=L, cap=5)[0] == "clean" and os.path.exists(MARK2))
check("clear on a clean state does nothing", br.clear(st, "nothing to clear here")[0] is False)

st = mk()
ign = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
t0 = time.monotonic(); r = W(st, [sys.executable, "-c", ign], 1.0, log_dir=L, cap=5)
check("child ignoring SIGTERM is SIGKILLed after the grace", r[0] == "timeout" and not r[1]["survivors"]
      and time.monotonic() - t0 < 1.0 + br.TERM_GRACE + 3)

st = mk(); pidf = os.path.join(mk(), "gc")
gc = ("import subprocess,sys,time;"
      "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
      "open(%r,'w').write(str(p.pid));time.sleep(60)" % pidf)
r = W(st, [sys.executable, "-c", gc], 1.5, log_dir=L, cap=5)
gpid = int(open(pidf).read())
time.sleep(0.2)
alive = os.path.exists("/proc/%d" % gpid) and br._stat_fields(gpid) and br._stat_fields(gpid)["state"] not in ("Z", "X")
check("same-group grandchild is killed with the group", r[0] == "timeout" and not alive and not r[1]["survivors"])

# ---- escaped descendant (setsid, env kept): killed by the survivor scan, never clean
st = mk(); pidf = os.path.join(mk(), "esc")
esc = ("import subprocess,sys,time;"
       "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(25)'],start_new_session=True,close_fds=False);"
       "open(%r,'w').write(str(p.pid));time.sleep(0.3)" % pidf)
r = W(st, [sys.executable, "-c", esc], 5, log_dir=L, cap=5)
epid = int(open(pidf).read()); time.sleep(0.2)
ef = br._stat_fields(epid)
check("escaped setsid descendant (env kept) is found and killed; state non-clean",
      r[0] == "needs-review" and r[1]["state"] == "escaped-descendants-killed" and (ef is None or ef["state"] in ("Z", "X")))
check("and blocked next", W(st, touch, 5, log_dir=L, cap=5)[0] == "refused" and not os.path.exists(MARK))
check("human clear works once nothing lives", br.clear(st, "escaped child killed by wrapper, lane untouched")[0])
# unkillable survivor (simulated): orphans-alive, blocks, clear refused while it persists
st = mk(); real_wait = br._wait_gone; real_sv = br.survivors
br._wait_gone = lambda run_id, pgid, secs: [os.getpid() + 7777777]
r = W(st, [sys.executable, "-c", "pass"], 5, log_dir=L, cap=5)
br._wait_gone = real_wait
check("survivors that cannot be killed -> orphans-alive, blocks", r[0] == "orphans-alive"
      and br._read_state(st)[0]["state"] == "orphans-alive")
br.survivors = lambda run_id, pgid: [4242424]
check("clear refused while a survivor is reported", br.clear(st, "survivor still reported by scan")[0] is False)
br.survivors = real_sv
check("clear allowed when the scan is empty", br.clear(st, "scan empty, lane untouched, operator")[0])

# ---- post-run ledger classification
st, L = mk(), ledger(1)
r = W(st, py("add({'phase':'reserve','n':2,'model':'m/free','via':'complete'})", L), 5, log_dir=L, cap=9)
check("new reserve without result -> not clean (unknown-reserve), exit-0 child notwithstanding",
      r[0] == "needs-review" and r[1]["state"] == "unknown-reserve" and r[1]["new_unmatched"] == 1)
check("and blocked next", W(st, touch, 5, log_dir=L, cap=9)[0] == "refused")
st, L = mk(), ledger(1)
r = W(st, py("add({'phase':'reserve','n':2,'model':'m/free','via':'complete'});add({'phase':'result','n':2,'model':'m/free','status':200,'class':'ok-shape','usage':{'cost':0},'cost_zero':True})", L), 5, log_dir=L, cap=9)
check("settled reserve+result -> clean", r[0] == "clean")
st, L = mk(), ledger(1)
r = W(st, py("open(p,'ab').write(b'{\"phase\": \"reserve\"')", L), 5, log_dir=L, cap=9)
check("torn last line -> needs-review", r[0] == "needs-review" and "partial" in r[1]["reason"])
st, L = mk(), ledger(1)
r = W(st, py("add({'phase':'halt','n':1,'why':'cost'})", L), 5, log_dir=L, cap=9)
check("halt line written -> needs-review", r[0] == "needs-review")
st, L = mk(), ledger(1)
r = W(st, [sys.executable, "-c", "raise SystemExit(3)"], 5, log_dir=L, cap=5)
check("nonzero exit -> child-failed, blocked", r[0] == "child-failed" and r[1]["exit_code"] == 3
      and W(st, touch, 5, log_dir=L, cap=5)[0] == "refused")
# baseline: a historic unmatched reserve does not poison later clean runs
st = mk(); L = mk()
write_log(L, LOG, [{"phase": "reserve", "n": 1, "model": "m/free", "via": "complete"}])
check("historic unmatched reserve is baseline, run still clean",
      W(st, touch, 5, log_dir=L, cap=5)[0] == "clean")

# ---- epoch budgets (accounting dependency) through the gate
st = mk(); L = mk()
write_log(L, LOG, [{"phase": "reserve", "n": 1, "model": "m/free", "via": "complete"},
                   {"phase": "result", "n": 1, "model": "m/free", "status": 200, "class": "ok-shape", "usage": {"cost": 0}, "cost_zero": True}])
write_log(L, "o-free.e0.jsonl", [x for i in (1, 2) for x in ({"phase": "reserve", "n": i, "model": "o/free"},
          {"phase": "result", "n": i, "model": "o/free", "status": 200, "class": "ok-shape", "usage": {"cost": 0}, "cost_zero": True})])
check("resume gate: same-epoch budgets fit remaining (cap 5, 3 used, needs 2)",
      br.run(st, touch, 5, epoch_budgets={LOG: 3}, log_dir=L, cap=5)[0] == "clean")
st = mk()
check("naive planned=3 would have been refused (cap 5, 3 used)", br.run(st, touch, 5, planned=3, log_dir=L, cap=5)[0] == "refused")

# ---- wrapper killed mid-run
if os.path.exists(MARK): os.remove(MARK)
def spawn_wrapper(state, L, child, deadline="30"):
    return subprocess.Popen([sys.executable, os.path.join(HERE, "bounded_run.py"), "run", "--state-dir", state,
                             "--deadline", deadline, "--planned", "1", "--log-dir", L, "--cap", "5", "--"] + child,
                            stderr=subprocess.PIPE)
def wait_state(state, want, secs=10):
    end = time.time() + secs
    while time.time() < end:
        d, _ = br._read_state(state)
        if d and d["state"] == want and d.get("child_pid"):
            return d
        time.sleep(0.05)
    return None

st, L = mk(), ledger(1)
w = spawn_wrapper(st, L, [sys.executable, "-c", "import time; time.sleep(60)"])
d = wait_state(st, "running")
check("wrapper subprocess reached running with child pid recorded", d is not None)
cpid = d["child_pid"]
w.kill(); w.wait(); time.sleep(0.4)
cf = br._stat_fields(cpid)
check("PDEATHSIG: direct child died when the wrapper was SIGKILLed", cf is None or cf["state"] in ("Z", "X"))
r = W(st, touch, 5, log_dir=L, cap=5)
check("restart after wrapper crash refuses and records wrapper-crashed-unknown",
      r[0] == "refused" and br._read_state(st)[0]["state"] == "wrapper-crashed-unknown" and not os.path.exists(MARK))

# wrapper killed while a same-group grandchild exists: lock/survivors keep refusing
st, L = mk(), ledger(1); pidf = os.path.join(mk(), "g2")
gc2 = ("import subprocess,sys,time;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(25)']);"
       "open(%r,'w').write(str(p.pid));time.sleep(60)" % pidf)
w = spawn_wrapper(st, L, [sys.executable, "-c", gc2]); d = wait_state(st, "running")
time.sleep(0.5); g2 = int(open(pidf).read())
w.kill(); w.wait(); time.sleep(0.4)
r = W(st, touch, 5, log_dir=L, cap=5)
check("grandchild survives wrapper kill (PDEATHSIG is direct-child only) but the start is refused",
      r[0] == "refused" and (os.path.exists("/proc/%d" % g2)))
check("clear refused while that grandchild lives", br.clear(st, "attempt while grandchild lives")[0] is False)
os.kill(g2, signal.SIGKILL); time.sleep(0.3)
check("cleared once it is gone", br.clear(st, "grandchild reaped by test, lane untouched")[0])

# ---- overlap
st, L = mk(), ledger(1)
w = spawn_wrapper(st, L, [sys.executable, "-c", "import time; time.sleep(20)"], "30"); wait_state(st, "running")
r = W(st, touch, 5, log_dir=L, cap=5)
check("overlapping start refused while one wrapper runs", r[0] == "refused" and "lock" in r[1]["reason"] and not os.path.exists(MARK))
w.send_signal(signal.SIGTERM)
try:
    w.wait(timeout=br.TERM_GRACE + br.VERIFY_WAIT + 4)
except subprocess.TimeoutExpired:
    w.kill(); w.wait()
d, _ = br._read_state(st)
check("wrapper SIGTERM: child group killed, state wrapper-signaled (blocks)", d["state"] == "wrapper-signaled"
      and not br.survivors(d["run_id"], d["child_pgid"]))

# ---- CLI exit codes and status
st, L = mk(), ledger(1)
cli = [sys.executable, os.path.join(HERE, "bounded_run.py")]
p = subprocess.run(cli + ["run", "--state-dir", st, "--deadline", "5", "--planned", "1", "--log-dir", L, "--cap", "5", "--", "true"],
                   capture_output=True, text=True)
check("CLI clean exit 0 and result line", p.returncode == 0 and "BOUNDED_RUN_RESULT" in p.stderr)
p = subprocess.run(cli + ["run", "--state-dir", st, "--deadline", "1", "--planned", "1", "--log-dir", L, "--cap", "5", "--", "sleep", "30"],
                   capture_output=True, text=True)
check("CLI timeout exit 11", p.returncode == 11)
p = subprocess.run(cli + ["status", "--state-dir", st], capture_output=True, text=True)
check("CLI status exit 1 while blocked", p.returncode == 1 and "timeout-killed" in p.stdout)
p = subprocess.run(cli + ["run", "--state-dir", st, "--deadline", "1", "--planned", "1", "--log-dir", L, "--cap", "5", "--", "true"],
                   capture_output=True, text=True)
check("CLI refused exit 10", p.returncode == 10)

for t in tmps: shutil.rmtree(t, ignore_errors=True)
print("\nBOUNDED RUN TESTS:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
raise SystemExit(0 if ok else 1)
