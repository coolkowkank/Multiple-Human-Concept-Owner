#!/usr/bin/env python3
"""Concept-cycle proof: CONCEPT_WORKED_EXAMPLE.md as a runnable check.

Drives the full concept-in/team-out story through the real CLIs, exactly
as the doc walks it by hand:

  concept_scaffold.py (conform PASS, first turn issued)
  -> for each of coordinator, builder, reviewer, qc, records:
       langgraph_team.py run stops gracefully with the explicit WAITING
       surface; launcher respond queues the operator-authored response
  -> final resume runs to status=done
  -> closeout is honest: cycle complete, quality unproven
  -> every artifact committed; no provider ledger under a fake HOME

Offline after the venv install: no keys, no model calls. Seats move only
on the operator-authored responses below, queued through the reviewed
`launcher respond` boundary.

Run (needs the venv from requirements.txt, like parallel_team.py):
    python3 concept_cycle.py /tmp/lg-concept-cycle
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FAIL = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    if not cond:
        FAIL.append(name)


APP = ("def km_to_mi(km):\n    return km * 0.621371\n\n"
       "def mi_to_km(mi):\n    return mi / 0.621371\n\n"
       "def kg_to_lb(kg):\n    return kg * 2.20462\n\n"
       "def lb_to_kg(lb):\n    return lb / 2.20462\n")
TEST = ("import sys, os\nsys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))\n"
        "from convert import km_to_mi, mi_to_km, kg_to_lb, lb_to_kg\n"
        "assert abs(km_to_mi(1) - 0.621371) < 1e-9\n"
        "assert abs(mi_to_km(1) - 1.60934) < 1e-3\n"
        "assert abs(kg_to_lb(1) - 2.20462) < 1e-9\n"
        "assert abs(lb_to_kg(1) - 0.453593) < 1e-6\n"
        "print('ok')\n")

RESPONSES = {
    "coordinator": {
        "summary": "drafted acceptance criteria from the concept",
        "writes": {".team/ACCEPTANCE.md":
                   "# Acceptance criteria\n1. converts km<->mi and kg<->lb\n"
                   "2. test suite green\n"},
        "verify_command": None, "handoff": "builder",
        "status_line": "criteria drafted, builder on turn"},
    "builder": {
        "summary": "implemented the converter with tests",
        "writes": {"src/convert.py": APP, "tests/test_convert.py": TEST},
        "verify_command": "python3 tests/test_convert.py",
        "handoff": "reviewer", "status_line": "batch built and verified"},
    "reviewer": {
        "summary": "re-ran builder verify: green; no findings",
        "writes": {"review/findings-1.md": "# Findings batch 1\nNone.\n"},
        "verify_command": "python3 tests/test_convert.py",
        "handoff": "qc", "status_line": "review green"},
    "qc": {
        "summary": "verdict PASS on the cycle evidence",
        "writes": {"review/qc-verdict-1.md": "# QC verdict 1\nPASS.\n"},
        "verify_command": "python3 tests/test_convert.py",
        "handoff": "records", "status_line": "QC PASS"},
    "records": {
        "summary": "archived batch 1; closing the cycle",
        "writes": {"records/archive-1.md":
                   "# Archive 1\nBatch 1 closed: converter + tests, QC PASS.\n"},
        "verify_command": None, "handoff": None,
        "status_line": "DONE - cycle 1 QC pass"},
}

SEAT_ORDER = ["coordinator", "builder", "reviewer", "qc", "records"]


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "/tmp/lg-concept-cycle"
    root = os.path.abspath(root)
    if os.path.exists(root) and os.listdir(root):
        raise SystemExit(f"refused: {root} is non-empty; delete it by hand")
    os.makedirs(root, exist_ok=True)
    repo = os.path.join(root, "unit-converter")
    db = os.path.join(root, "cp.sqlite")
    thread = "concept-cycle-1"

    home = os.path.join(root, "home")
    os.makedirs(home, exist_ok=True)
    env = dict(os.environ, HOME=home)

    def run(argv):
        return subprocess.run([sys.executable, *argv], cwd=HERE, env=env,
                              capture_output=True, text=True)

    # 1. Concept in: scaffold through the real CLI.
    concept = os.path.join(root, "concept.md")
    with open(concept, "w") as fh:
        fh.write("# Concept\nA CLI unit converter (km<->mi, kg<->lb) "
                 "with tests.\n")
    p = run(["concept_scaffold.py", repo, "--concept-file", concept])
    check("scaffold: conform PASS, first turn issued",
          p.returncode == 0 and "conformance: PASS" in p.stdout
          and "Scaffolded concept team" in p.stdout)
    with open(os.path.join(repo, ".team", "brief.md")) as fh:
        check("concept is the brief, verbatim",
              "unit converter" in fh.read())

    # 2. Team out: the run / wait / respond / resume rhythm per seat.
    for seat in SEAT_ORDER:
        p = run(["langgraph_team.py", "run", repo, db, "0", thread])
        check(f"run waits explicitly at {seat} (graceful, exit 0)",
              p.returncode == 0
              and f"WAITING for an operator response for seat '{seat}'"
              in p.stdout
              and "stopped gracefully while waiting" in p.stdout
              and "REFUSED" not in p.stdout)
        resp = os.path.join(root, f"resp-{seat}.json")
        with open(resp, "w") as fh:
            json.dump(RESPONSES[seat], fh)
        p = run(["-m", "launcher", "respond", seat,
                 "--repo", repo, "--file", resp])
        check(f"respond {seat}: queued, bound to turn/seq/head",
              p.returncode == 0 and f"bound to turn='{seat}'" in p.stdout)

    # 3. Final resume runs to done.
    p = run(["langgraph_team.py", "run", repo, db, "0", thread])
    check("final resume reaches status=done",
          "status=done" in p.stdout and p.returncode == 3)
    check("closeout honest: cycle complete, quality unproven",
          '"cycle_complete": true' in p.stdout
          and "quality unproven" in p.stdout)

    # 4. Evidence committed in the project repo.
    for path, needle in [
            (".team/ACCEPTANCE.md", "km<->mi"),
            ("src/convert.py", "def km_to_mi"),
            ("tests/test_convert.py", "assert"),
            ("review/findings-1.md", "None"),
            ("review/qc-verdict-1.md", "PASS"),
            ("records/archive-1.md", "QC PASS")]:
        full = os.path.join(repo, path)
        ok = os.path.exists(full) and needle in open(full).read()
        check(f"artifact committed: {path}", ok)
    log = subprocess.run(["git", "-C", repo, "log", "--oneline"],
                         capture_output=True, text=True).stdout
    check("every seat turn committed (5 TURN commits)",
          log.count("TURN:") >= 5)

    # 5. No model was contacted anywhere.
    check("no provider ledger under the fake HOME",
          not os.path.exists(os.path.join(home, ".lg-http-usage")))

    print("CONCEPT CYCLE: " + ("FAILED" if FAIL else "ALL CHECKS PASSED"))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
