"""Operator command/intervention controls demo (mock, no network, no keys).

Proves the four controls through the single bus control channel:
  PAUSE    - graph holds in the paused node while the operator interferes
  UPDATE   - an instruction commit makes every queued in-flight response
             stale by the project's own head-binding; the seat refuses it
  RESUME   - graph continues from its durable checkpoint after the hold
  ASSIGN   - operator issues a NEW task to a DONE team; it runs again

Run: python controls_demo.py /tmp/lg-controls
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

import langgraph_team as lt
from launcher.bus import Bus

APP1 = "def add(a, b):\n    return a + b\n"
TEST1 = ("import sys, os\nsys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))\n"
         "from app import add\nassert add(2, 3) == 5\nprint('ok')\n")
APP2 = "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n"
TEST2 = ("import sys, os\nsys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))\n"
         "from app import add, sub\nassert add(2, 3) == 5\nassert sub(5, 3) == 2\nprint('ok')\n")

BUILDER_R1 = {"summary": "implemented add() with a test",
              "writes": {"src/app.py": APP1, "tests/test_app.py": TEST1},
              "verify_command": "python3 tests/test_app.py",
              "handoff": "reviewer", "status_line": "batch built and verified"}
BUILDER_R2 = {"summary": "implemented sub() alongside add() with tests",
              "writes": {"src/app.py": APP2, "tests/test_app.py": TEST2},
              "verify_command": "python3 tests/test_app.py",
              "handoff": "reviewer", "status_line": "batch 2 built and verified"}

# Cycle-2 scripts appended to the mock queues for the non-queue seats.
CYCLE2 = {
    "coordinator": [
        {"summary": "drafted cycle-2 acceptance criteria",
         "writes": {".team/ACCEPTANCE2.md": "# Acceptance criteria 2\n1. sub(a,b)\n2. tests pass\n"},
         "verify_command": None, "handoff": "builder",
         "status_line": "criteria 2 drafted, builder on turn"},
        {"summary": "QC passed cycle 2; closing",
         "writes": {}, "verify_command": None, "handoff": None,
         "status_line": "DONE - cycle 2 QC pass"}],
    "reviewer": [
        {"summary": "re-ran builder verify for cycle 2: green",
         "writes": {"review/findings-2.md": "# Findings batch 2\nNone.\n"},
         "verify_command": "python3 tests/test_app.py",
         "handoff": "qc", "status_line": "review 2 green"}],
    "qc": [
        {"summary": "verdict PASS on cycle-2 evidence",
         "writes": {"review/qc-verdict-2.md": "# QC verdict 2\nPASS.\n"},
         "verify_command": "python3 tests/test_app.py",
         "handoff": "records", "status_line": "QC 2 PASS"}],
    "records": [
        {"summary": "archived batch 2",
         "writes": {"records/archive-2.md": "# Archive batch 2\n"},
         "verify_command": None, "handoff": "coordinator",
         "status_line": "batch 2 archived"}],
}


def respond(repo: str, seat: str, response: dict, discard: bool) -> None:
    """Queue an operator response through the project's own CLI."""
    f = os.path.join(repo, ".team", f"respond-{seat}.json")
    with open(f, "w") as fh:
        json.dump(response, fh)
    argv = [sys.executable, "-m", "launcher", "respond", seat,
            "--file", f, "--repo", repo, "--branch", lt.BRANCH]
    if discard:
        argv.append("--discard-stale")
    env = dict(os.environ)
    here = os.path.dirname(os.path.realpath(__file__))
    env["PYTHONPATH"] = here + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(argv, capture_output=True, text=True, env=env)
    print(f"  launcher respond {seat}: {proc.stdout.strip() or proc.stderr.strip()}")
    if proc.returncode != 0:
        raise SystemExit(f"respond failed: {proc.stderr}")
    os.remove(f)


def main(argv) -> int:
    base = os.path.abspath(argv[1])
    repo = os.path.join(base, "lane")
    db = os.path.join(base, "db.sqlite")
    fails = []

    def check(name, cond):
        print(("PASS  " if cond else "FAIL  ") + name, flush=True)
        if not cond:
            fails.append(name)

    if os.path.exists(base):
        if not os.path.isdir(base) or os.listdir(base):
            raise SystemExit(
                f"refused: {base} exists and is non-empty; this demo only "
                f"creates a FRESH directory - delete a used one by hand")
    else:
        os.makedirs(base)
    lt.init_repo(repo, queue_seats=("builder",))

    # Phase 1: coordinator acts, turn passes to the operator-fed builder.
    lt.run_graph(repo, db, stop_after=1, thread_id="ctrl-1")
    check("turn handed to builder", Bus(repo, lt.BRANCH).state()["turn"] == "builder")

    # Operator queues the builder response (bound to current head)...
    respond(repo, "builder", BUILDER_R1, discard=False)
    # ...then INTERFERES: pause, then rewrite instructions mid-flight.
    lt.operator_pause(repo, note="reviewing direction")
    lt.operator_update_instructions(
        repo, "# Brief v2\nHold the add() batch; direction under review.\n",
        note="instructions updated to v2")

    # RESUME request in a background thread: the graph must hold in the
    # paused node until the operator actually resumes.
    holder = threading.Thread(
        target=lt.run_graph, args=(repo, db, 0, "ctrl-1"), daemon=True)
    t0 = time.time()
    holder.start()
    time.sleep(2.0)
    running_during_pause = holder.is_alive()
    lt.operator_resume(repo, note="direction confirmed, continue")
    holder.join(timeout=30)
    pause_seconds = time.time() - t0
    check("graph held in paused node during operator pause",
          running_during_pause and pause_seconds >= 2.0)

    snap_steps = lt.build_graph(lt.SqliteSaver(__import__("sqlite3").connect(db))) \
        .get_state({"configurable": {"thread_id": "ctrl-1"}}).values
    trace = snap_steps.get("steps", [])
    outcome = snap_steps.get("outcome") or ""
    check("in-flight queued response REFUSED as stale after instruction update",
          any("REFUSED" in s and "stale" in s for s in trace) and "stale" in outcome)
    check("refusal preserved queue for operator (no silent apply)",
          not os.path.exists(os.path.join(repo, "src/app.py")))

    # Operator discards the stale line, re-queues against the new head,
    # and the team completes cycle 1 on a fresh thread.
    respond(repo, "builder", BUILDER_R1, discard=True)
    lt.run_graph(repo, db, stop_after=0, thread_id="ctrl-2")
    check("cycle 1 completed after operator resolution",
          Bus(repo, lt.BRANCH).state()["status"] == "done")

    # ASSIGN: operator issues new work to the closed team.
    for seat, responses in CYCLE2.items():
        q = os.path.join(repo, ".team", "queues", f"{seat}.mock.jsonl")
        with open(q, "a") as fh:
            for r in responses:
                fh.write(json.dumps(r) + "\n")
    Bus(repo, lt.BRANCH).commit_all("operator: cycle-2 mock scripts staged")
    lt.operator_assign(repo, "# Brief 2\nAdd sub(a,b) with tests.\n",
                       "coordinator", note="cycle 2: subtract feature")
    # Coordinator drafts cycle-2 criteria and hands to the builder; only
    # THEN can the operator queue a response bound to the builder's turn
    # (a response queued before its turn is born is stale on arrival).
    lt.run_graph(repo, db, stop_after=1, thread_id="ctrl-3")
    respond(repo, "builder", BUILDER_R2, discard=False)
    lt.run_graph(repo, db, stop_after=0, thread_id="ctrl-4")

    app = open(os.path.join(repo, "src/app.py")).read()
    check("assigned cycle 2 ran: sub() exists", "def sub(" in app)
    check("cycle 2 QC verdict written",
          os.path.exists(os.path.join(repo, "review/qc-verdict-2.md")))
    check("cycle 2 archived",
          os.path.exists(os.path.join(repo, "records/archive-2.md")))
    check("team DONE again after assignment",
          Bus(repo, lt.BRANCH).state()["status"] == "done")

    # Project-level checks still hold on the intervened repo.
    kinds = [e["kind"] for e in Bus(repo, lt.BRANCH).log()]
    check("handoffs logged across both cycles", kinds.count("handoff") >= 10)
    proc = subprocess.run(["git", "-C", repo, "log", "--format=%s"],
                          capture_output=True, text=True)
    check("operator commits recorded in bus history",
          proc.stdout.count("operator:") >= 5)

    print("\nCONTROLS DEMO:", "ALL CHECKS PASSED" if not fails else f"FAILURES {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
