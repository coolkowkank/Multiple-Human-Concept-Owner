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
def plant_qc_pass(b, r):
    """Reviewer-skip guard (2026-11-05): DONE needs a fresh QC PASS verdict."""
    head = git(r, "rev-parse", "HEAD").strip()
    b.append_log("qc", "verdict", "verdict PASS at head " + head + ": planted")
    b.commit_all("human: plant QC verdict")
def attempt(tmp, name, resp, plant=False):
    r = os.path.join(tmp, name); lt.init_repo(r)
    b = Bus(r, lt.BRANCH)
    if plant: plant_qc_pass(b, r)
    s = Seat(b, "coordinator", instance_id="A")
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
    st = b.state(); check("null handoff with DONE status_line but no QC verdict: refused, routed to qc", err is None and st["status"] != "done" and st["turn"] == "qc")
    r, b, err, h, st0 = attempt(tmp, "d", dict(base, handoff="builder", status_line="handing over"))
    check("named seat: accepted, turn moves", err is None and b.state()["turn"] == "builder")
    r, b, err, h, st0 = attempt(tmp, "e", dict(base, handoff="builder", status_line="DONE early"))
    check("DONE with a named seat: refused as ambiguous, no residue, turn stays", err and "ambiguous" in err and git(r, "rev-parse", "HEAD") == h and b.state() == st0 and not os.path.exists(os.path.join(r, ".team/NOTE.md")))
    for form in ("DONE", "DONE.", "DONE - QC pass at head", "DONE: cycle closed", "DONE\tx"):
        r, b, err, h, st0 = attempt(tmp, "f-" + str(abs(hash(form))), dict(base, handoff=None, status_line=form), plant=True)
        check(f"exact DONE form {form!r}: accepted and closes with a fresh QC verdict", err is None and b.state()["status"] == "done" and b.state()["turn"] is None)
    for form in ("DONEZO", "DONE2", "DONE_not", "DONEBUT keep going", "done", " DONE", "NOT DONE"):
        r, b, err, h, st0 = attempt(tmp, "g-" + str(abs(hash(form))), dict(base, handoff=None, status_line=form))
        check(f"{form!r} is not DONE: null handoff refused, no residue", err and "no turn holder" in err and b.state() == st0)
        r, b, err, h, st0 = attempt(tmp, "i-" + str(abs(hash(form))), dict(base, handoff="builder", status_line=form))
        check(f"{form!r} with a named seat: continues normally, status not done", err is None and b.state()["status"] != "done" and b.state()["turn"] == "builder")
    for nm, bad in (("list", ["builder"]), ("dict", {"a": 1}), ("int", 3), ("empty string", ""), ("unknown seat", "nobody")):
        r, b, err, h, st0 = attempt(tmp, "h-" + nm.split()[0], dict(base, handoff=bad, status_line="x"))
        check(f"handoff {nm}: clean SeatError (no TypeError crash), no residue", err and "CRASH" not in err and git(r, "rev-parse", "HEAD") == h and b.state() == st0 and not os.path.exists(os.path.join(r, ".team/NOTE.md")))
    for nm, bad in (("int", 5), ("list", ["DONE"]), ("dict", {})):
        r, b, err, h, st0 = attempt(tmp, "s-" + nm, dict(base, handoff="builder", status_line=bad))
        check(f"status_line {nm}: clean SeatError before any write", err and "CRASH" not in err and "status_line" in err and git(r, "rev-parse", "HEAD") == h and not os.path.exists(os.path.join(r, ".team/NOTE.md")))
    bad = {"gate str": {"gate": "why"}, "gate list": {"gate": ["q"]}, "gate no question": {"gate": {"options": ["a"]}},
           "gate question int": {"gate": {"question": 5}}, "gate options str": {"gate": {"question": "q", "options": "ab"}},
           "summary int": {"summary": 5}, "summary empty": {"summary": "  "}, "summary missing": {"summary": None},
           "writes list": {"writes": ["a"]}, "writes value int": {"writes": {".team/NOTE.md": 5}}, "writes str": {"writes": "x"}}
    for nm, over in bad.items():
        r, b, err, h, st0 = attempt(tmp, "z-" + nm.replace(" ", "_"), dict(base, handoff="builder", status_line="s", **over))
        check(f"malformed {nm}: clean SeatError before any write, no residue (used to crash after writing for gate/writes types)",
              err and "CRASH" not in err and git(r, "rev-parse", "HEAD") == h and b.state() == st0 and not os.path.exists(os.path.join(r, ".team/NOTE.md")))
    r, b, err, h, st0 = attempt(tmp, "z-good", dict(base, handoff="builder", status_line="s", gate={"question": "ok?", "options": ["y", "n"], "recommendation": "y"}))
    check("well-formed gate still accepted", err is None and len(b.pending_gates()) == 1)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nHANDOFF VALIDATION:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
raise SystemExit(0 if ok else 1)
