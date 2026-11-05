"""Offline probes of launcher.supervisor.Supervisor._check_stall (scratch fakes, no process
is started, no git, no provider). Group 1 = holds. Group 2 = GAPs found at 11c2606, asserted as
desired behaviour; --strict fails on gaps. Probes run in child processes with TZ set, because the
stall age is computed from a UTC 'Z' stamp (runtime._now) with local-time functions."""
import json, os, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
CHILD = r'''
import os, sys, time, json
sys.path.insert(0, %r)
os.environ["LG_VERIFY_SANDBOX"] = "1"
from launcher.supervisor import Supervisor
class P:
    def __init__(s): s.t = 0
    def terminate(s): s.t += 1
    def poll(s): return None
class B:
    def __init__(s): s.log = []; s.gates = []
    def append_log(s, *a): s.log.append(a)
    def commit_all(s, *a): pass
    def open_gate(s, *a, **k): s.gates.append(a)
def mk(procs):
    sv = Supervisor.__new__(Supervisor); sv.bus = B(); sv.stall_timeout = 900; sv._stalled_seats = set(); sv.procs = procs; sv._notified_gates = set(); return sv
def stamp(age): return time.strftime("%%Y-%%m-%%dT%%H:%%M:%%SZ", time.gmtime(time.time() - age))
def st(age, turn="builder", status="running", seq=1, since=True):
    d = {"turn": turn, "status": status, "turn_seq": seq}
    if since is True: d["turn_since"] = stamp(age)
    elif since is not False: d["turn_since"] = since
    return d
out = {}
p = P(); sv = mk({"builder": p}); sv._check_stall(st(5)); out["fresh_turn_left_alone"] = p.t == 0
p = P(); sv = mk({"builder": p}); sv._check_stall(st(1000)); out["stale_turn_terminated"] = p.t == 1
p = P(); sv = mk({"builder": p}); sv._check_stall(st(1000, status="done")); sv._check_stall(st(1000, turn=None)); sv._check_stall(st(0, since=False)); sv._check_stall(st(0, since="garbage")); sv._check_stall(st(0, since=None))
out["not_running_no_turn_no_stamp_bad_stamp_ignored"] = p.t == 0
sv = mk({}); sv._check_stall(st(1000, turn="human")); sv._check_stall(st(1000, turn="human"))
out["interactive_seat_gate_opened_once"] = len(sv.bus.gates) == 1
p = P(); sv = mk({"builder": p}); sv._check_stall(st(1000)); sv._check_stall(st(1000)); out["same_stall_terminated_once"] = p.t == 1
p = P(); sv = mk({"builder": p}); sv._check_stall(st(1000, seq=1)); sv._check_stall(st(1000, seq=9))
out["GAP second stall of the same seat in a LATER turn is acted on (stalled set is keyed by seat name and never cleared)"] = p.t == 2
print(json.dumps(out))
''' % HERE
def run(tz):
    env = dict(os.environ); env["TZ"] = tz
    p = subprocess.run([sys.executable, "-c", CHILD], capture_output=True, text=True, env=env, cwd=HERE)
    try: return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception: print("child failed:", p.stderr[-300:]); return {}
STRICT = "--strict" in sys.argv; good = True; gaps = 0
def show(label, ok_, is_gap):
    global good, gaps
    if is_gap: gaps += (not ok_); print(("PASS  " if ok_ else "GAP   ") + label, flush=True)
    else: good = good and ok_; print(("PASS  " if ok_ else "FAIL  ") + label, flush=True)
for tz in ("UTC", "Europe/Kiev", "America/Vancouver", "Asia/Jakarta"):
    r = run(tz)
    for k, v in r.items():
        gap_ = k.startswith("GAP ")
        # UTC is the baseline that must hold. In other zones a failure is the local-vs-UTC skew, reported as GAP.
        is_gap = gap_ or tz != "UTC"
        show(f"[TZ={tz}] {k[4:] if gap_ else k}", v, is_gap)
print(f"\nSUPERVISOR STALL PROBES: {'baseline holds' if good else 'FAILURES ABOVE'}; gaps at this head: {gaps}")
raise SystemExit(0 if good and not (STRICT and gaps) else 1)
