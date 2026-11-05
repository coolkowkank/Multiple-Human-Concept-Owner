"""Offline: RW1 null-handoff incident. A response that would leave the bus
with no turn holder (null handoff, no DONE) or crash after mutation (bad
types) is refused BEFORE any write. Real git lane, no provider, no model."""
import os as _os; _os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import json, os, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import langgraph_team as lt  # noqa: E402
from launcher.bus import Bus  # noqa: E402
from launcher.runtime import Seat, SeatError  # noqa: E402
ok = True
def check(n, c):
    global ok; ok = ok and bool(c); print(("PASS  " if c else "FAIL  ") + n, flush=True)
def git(r, *a): return subprocess.run(["git", "-C", r, *a], capture_output=True, text=True).stdout
def attempt(tmp, name, resp):
    r = os.path.join(tmp, name); lt.init_repo(r)
    b = Bus(r, lt.BRANCH); s = Seat(b, "coordinator", instance_id="A")
    s.adapter.consume = lambda: None
    s._call_adapter = lambda state: dict(resp)
    head, st0 = git(r, "rev-parse", "HEAD"), b.state()
    try: s.act_once(); err = None
    except SeatError as e: err = str(e)
    except Exception as e: err = "CRASH " + repr(e)
    return r, b, err, head, st0
tmp = tempfile.mkdtemp()
try:
    base = {"summary": "x", "writes": {".team/NOTE.md": "n\n"}, "verify_command": None}
    r, b, err, h, st0 = attempt(tmp, "a", dict(base, handoff=None, status_line="still working"))
    check("null handoff without DONE: refused with a clear SeatError", err and "no turn holder" in err)
    check("no residue: head, state and worktree unchanged, file not written, turn stays", git(r, "rev-parse", "HEAD") == h and b.state() == st0 and not os.path.exists(os.path.join(r, ".team/NOTE.md")) and git(r, "status", "--porcelain").strip() == "")
    r, b, err, h, st0 = attempt(tmp, "b", dict(base, handoff=None))
    check("null handoff with no status_line at all: refused", err and "no turn holder" in err)
    r, b, err, h, st0 = attempt(tmp, "c", dict(base, handoff=None, status_line="DONE: cycle closed"))
    st = b.state(); check("null handoff with DONE status_line: accepted, status done, no turn holder by design", err is None and st["status"] == "done" and st["turn"] is None)
    r, b, err, h, st0 = attempt(tmp, "d", dict(base, handoff="builder", status_line="handing over"))
    check("named seat: accepted, turn moves", err is None and b.state()["turn"] == "builder")
    r, b, err, h, st0 = attempt(tmp, "e", dict(base, handoff="builder", status_line="DONE early"))
    check("DONE with a named seat: unchanged behaviour (done wins, turn null)", err is None and b.state()["status"] == "done")
    for nm, bad in (("list", ["builder"]), ("dict", {"a": 1}), ("int", 3), ("empty string", ""), ("unknown seat", "nobody")):
        r, b, err, h, st0 = attempt(tmp, "h-" + nm.split()[0], dict(base, handoff=bad, status_line="x"))
        check(f"handoff {nm}: clean SeatError (no TypeError crash), no residue", err and "CRASH" not in err and git(r, "rev-parse", "HEAD") == h and b.state() == st0 and not os.path.exists(os.path.join(r, ".team/NOTE.md")))
    for nm, bad in (("int", 5), ("list", ["DONE"]), ("dict", {})):
        r, b, err, h, st0 = attempt(tmp, "s-" + nm, dict(base, handoff="builder", status_line=bad))
        check(f"status_line {nm}: clean SeatError before any write", err and "CRASH" not in err and "status_line" in err and git(r, "rev-parse", "HEAD") == h and not os.path.exists(os.path.join(r, ".team/NOTE.md")))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nHANDOFF VALIDATION:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
raise SystemExit(0 if ok else 1)
