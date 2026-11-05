"""WP4 re-proof: one batch through the REAL launcher supervisor with
Reviewer and QC on the same application pin, unattended, under the
Reviewer-skip acceptance guard (accepted a1c36ce). Offline, scripted
mock queue adapters (no provider, no model): this proves the acceptance
FLOW and the guarded close on the exact pinned code, not any model's
ability. Disposable lane; evidence is the lane's own git/bus history.

Checks (written before the run):
 R1 supervisor reaches done with no human input (no gates answered).
 R2 seat order coordinator,builder,reviewer,qc,records,coordinator and
    turn_seq +1 per turn.
 R3 a QC-seat verdict row 'verdict PASS at head <sha>' exists, and the
    application (src/ + tests/) is IDENTICAL between that head and the
    final HEAD - Reviewer and QC ruled on the same application pin.
 R4 the close was guarded, not bypassed: no review-required rows, no
    error/restart rows, no pending gates.
 R5 evidence files exist and the final verify test passes when re-run.
"""
import json, os, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from launcher.bus import Bus
import langgraph_team as lt

APP = "def add(a, b):\n    return a + b\n"
TEST = ("import sys, os\nsys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))\n"
        "from app import add\nassert add(2, 3) == 5\nprint('ok')\n")
SEATS = ["coordinator", "builder", "reviewer", "qc", "records"]
SCRIPTS = {
 "coordinator": [
   {"summary": "dispatch batch 1 with numbered acceptance criteria",
    "writes": {".team/ACCEPTANCE-1.md": "# Acceptance criteria\n1. src/app.py provides add(a,b)\n2. python3 tests/test_app.py exits 0\n"},
    "verify_command": None, "handoff": "builder", "status_line": "batch 1 dispatched"},
   {"summary": "QC passed all criteria; closing the team",
    "writes": {}, "verify_command": None, "handoff": None,
    "status_line": "DONE - batch 1 accepted, guarded close"}],
 "builder": [
   {"summary": "implemented add() with a test",
    "writes": {"src/app.py": APP, "tests/test_app.py": TEST},
    "verify_command": "python3 tests/test_app.py", "handoff": "reviewer",
    "status_line": "batch 1 built and verified"}],
 "reviewer": [
   {"summary": "re-ran builder verify at the same head: green; no findings",
    "writes": {"review/findings-1.md": "# Findings batch 1\nNone. Reproduced: python3 tests/test_app.py exit 0 at the builder's commit.\n"},
    "verify_command": "python3 tests/test_app.py", "handoff": "qc",
    "status_line": "review green, QC on turn"}],
 "qc": [
   {"summary": "verdict PASS on evidence at head (verify re-run exit 0)",
    "writes": {"review/qc-verdict-1.md": "# QC verdict\nPASS. Verify re-run exit 0 at head.\n"},
    "verify_command": "python3 tests/test_app.py", "handoff": "records",
    "status_line": "QC PASS"}],
 "records": [
   {"summary": "archived batch 1 handoffs, findings and verdict",
    "writes": {"records/archive-1.md": "# Archive batch 1\ncriteria -> build -> review -> QC PASS -> guarded close\n"},
    "verify_command": None, "handoff": "coordinator", "status_line": "batch 1 archived"}],
}

def main():
    tmp = tempfile.mkdtemp(prefix="wp4-reproof-"); r = os.path.join(tmp, "lane")
    lt.init_repo(r)
    bus = Bus(r, lt.BRANCH)
    os.makedirs(os.path.join(r, ".team", "queues"), exist_ok=True)
    for s in SEATS:
        q = os.path.join(r, ".team", "queues", f"{s}.mock.jsonl")
        open(q, "w").write("".join(json.dumps(x) + "\n" for x in SCRIPTS[s]))
    bus.commit_all("operator: scripted queues for WP4 re-proof")
    env = dict(os.environ); env["PYTHONPATH"] = HERE + os.pathsep + env.get("PYTHONPATH", "")
    out_path = os.path.join(tmp, "supervisor.out")
    t0 = time.time()
    sup = subprocess.Popen([sys.executable, "-m", "launcher", "launch", "--repo", r,
                            "--branch", lt.BRANCH, "--poll", "1", "--max-seconds", "120"],
                           stdout=open(out_path, "w"), stderr=subprocess.STDOUT, env=env,
                           start_new_session=True)
    try:
        sup.wait(timeout=150)
    finally:
        if sup.poll() is None:
            os.killpg(sup.pid, 9); sup.wait()
    wall = round(time.time() - t0, 1)
    so = open(out_path).read()
    g = lambda *x: subprocess.run(["git", "-C", r, *x], capture_output=True, text=True).stdout
    st = bus.state(); log = bus.log()
    hs = [e for e in log if e.get("kind") == "handoff"]
    seats = [e.get("seat") for e in hs]
    seqs = [e.get("turn_seq") for e in hs]
    expect = SEATS + ["coordinator"]
    vs = [e for e in log if e.get("kind") == "verdict" and e.get("seat") == "qc"]
    import re as _re
    m = _re.match(r"verdict PASS at head ([0-9a-f]{40})\b", vs[-1].get("body", "")) if vs else None
    same_pin = bool(m) and g("diff", "--quiet", m.group(1), "HEAD", "--", "src", "tests") == "" \
        and subprocess.run(["git", "-C", r, "diff", "--quiet", m.group(1), "HEAD", "--", "src", "tests"]).returncode == 0 if m else False
    t = subprocess.run([sys.executable, "-B", "tests/test_app.py"], cwd=r, capture_output=True, text=True)
    res = {
      "wall_s": wall,
      "R1_supervisor_done": "supervisor: done" in so and st.get("status") == "done" and st.get("turn") is None,
      "R2_order_ok": seats == expect,
      "R2_seq_plus1": all(b - a == 1 for a, b in zip(seqs, seqs[1:])),
      "R3_qc_pass_row": bool(m), "R3_verdict_head": m.group(1) if m else None,
      "R3_same_application_pin": same_pin,
      "R4_review_required_rows": sum(1 for e in log if e.get("kind") == "review-required"),
      "R4_error_rows": sum(1 for e in log if e.get("kind") == "error"),
      "R4_restart_rows": sum(1 for e in log if e.get("kind") == "restart"),
      "R4_pending_gates": len(bus.pending_gates()),
      "R5_files_ok": all(os.path.exists(os.path.join(r, f)) for f in
          ("src/app.py", "tests/test_app.py", "review/findings-1.md",
           "review/qc-verdict-1.md", "records/archive-1.md", ".team/ACCEPTANCE-1.md")),
      "R5_final_verify_ok": t.returncode == 0 and "ok" in t.stdout,
      "commits": int(g("rev-list", "--count", "HEAD").strip()),
      "lane": r, "supervisor_out_tail": so.strip().splitlines()[-3:],
    }
    res["SUCCESS"] = (res["R1_supervisor_done"] and res["R2_order_ok"] and res["R2_seq_plus1"]
        and res["R3_qc_pass_row"] and res["R3_same_application_pin"]
        and res["R4_review_required_rows"] == 0 and res["R4_error_rows"] == 0
        and res["R4_restart_rows"] == 0 and res["R4_pending_gates"] == 0
        and res["R5_files_ok"] and res["R5_final_verify_ok"])
    print(json.dumps(res, indent=2))
    return 0 if res["SUCCESS"] else 1

if __name__ == "__main__":
    sys.exit(main())
