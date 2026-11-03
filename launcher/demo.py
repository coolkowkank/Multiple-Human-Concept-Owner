"""Self-checking demo: a full team cycle with scripted mock seats.

Runs the real seat loop, bus, guard hook and turn protocol in a fresh
git repo - no keys, no spend. Proves the mechanism (turn token,
handoffs, verification re-run, archive, close rule). Says nothing about
model quality or unattended week-long operation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from .bus import Bus
from .cli import default_roster
from .runtime import Seat

APP = "def add(a, b):\n    return a + b\n"
TEST = ("import sys, os\nsys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))\n"
        "from app import add\nassert add(2, 3) == 5\nprint('ok')\n")


def _scripts():
    return {
        "coordinator": [
            {"summary": "drafted numbered acceptance criteria from the brief",
             "writes": {".team/ACCEPTANCE.md": "# Acceptance criteria\n1. src/app.py provides add(a,b)\n2. python3 tests/test_app.py exits 0\n"},
             "verify_command": None, "handoff": "builder",
             "status_line": "criteria drafted, builder on turn"},
            {"summary": "QC passed all criteria; closing the team",
             "writes": {}, "verify_command": None, "handoff": None,
             "status_line": "DONE - QC pass at head, builder confirmed"},
        ],
        "builder": [
            {"summary": "implemented add() with a test",
             "writes": {"src/app.py": APP, "tests/test_app.py": TEST},
             "verify_command": "python3 tests/test_app.py",
             "handoff": "reviewer",
             "status_line": "batch built and verified"},
        ],
        "reviewer": [
            {"summary": "re-ran builder verify at same head: green; no findings",
             "writes": {"review/findings-1.md": "# Findings batch 1\nNone. Reproduced: python3 tests/test_app.py exit 0.\n"},
             "verify_command": "python3 tests/test_app.py",
             "handoff": "qc",
             "status_line": "review green, QC on turn"},
        ],
        "qc": [
            {"summary": "verdict PASS on evidence at head",
             "writes": {"review/qc-verdict-1.md": "# QC verdict\nPASS. Verify re-run exit 0 at head.\n"},
             "verify_command": "python3 tests/test_app.py",
             "handoff": "records",
             "status_line": "QC PASS, records archiving"},
        ],
        "records": [
            {"summary": "archived batch 1 handoffs, findings and verdict",
             "writes": {"records/archive-1.md": "# Archive batch 1\ncriteria -> build -> review -> QC PASS\n"},
             "verify_command": None, "handoff": "coordinator",
             "status_line": "batch 1 archived"},
        ],
    }


def run_demo(directory):
    repo = os.path.abspath(directory)
    shutil.rmtree(repo, ignore_errors=True)
    os.makedirs(repo)
    env = dict(os.environ)
    pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = pkg_parent + os.pathsep + env.get("PYTHONPATH", "")
    argv = [sys.executable, "-m", "launcher"]

    def run(*args):
        proc = subprocess.run(argv + list(args), cwd=repo, env=env,
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit(f"demo step failed: {' '.join(args)}\n{proc.stderr}")
        return proc

    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.name", "demo"], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.email", "demo@example.com"], check=True)
    run("init", "--default-roster", "--repo", repo)

    # Load the roster and give each seat its scripted adapter.
    bus = Bus(repo, "team-work")
    roster = bus.roster()
    scripts = _scripts()
    for name, spec in roster["seats"].items():
        spec["adapter"] = {"type": "mock", "script": scripts[name]}
    with open(os.path.join(repo, ".team", "roster.json"), "w") as fh:
        import json
        json.dump(roster, fh, indent=2)

    # Seed: the owners' brief is in, the first turn goes to the coordinator.
    with open(os.path.join(repo, ".team", "brief.md"), "w") as fh:
        fh.write("# Brief\nBuild a tiny add(a,b) library with a passing test.\n")
    state = bus.state()
    state["turn"] = "coordinator"
    state["status"] = "running"
    bus.write_state(state)
    bus.commit_all("human: brief agreed, first turn issued")

    checks = []

    # Run the team: poll every seat until the status is done.
    seats = {name: Seat(bus, name) for name in roster["seats"]}
    for _ in range(50):
        if bus.state()["status"] == "done":
            break
        acted = any(seat.act_once() for seat in seats.values())
        if not acted:
            break

    state = bus.state()
    checks.append(("team reached DONE", state["status"] == "done"))
    checks.append(("turn is none after close", state["turn"] is None))
    checks.append(("app exists", os.path.exists(os.path.join(repo, "src/app.py"))))
    checks.append(("QC verdict written",
                   os.path.exists(os.path.join(repo, "review/qc-verdict-1.md"))))
    checks.append(("archive written",
                   os.path.exists(os.path.join(repo, "records/archive-1.md"))))
    kinds = [e["kind"] for e in bus.log()]
    checks.append(("five handoffs logged", kinds.count("handoff") >= 5))
    verify_lines = [e for e in bus.log() if "exit=0" in e.get("body", "")]
    checks.append(("verify exit codes recorded", len(verify_lines) >= 3))
    hook = os.path.join(repo, ".git", "hooks", "commit-msg")
    checks.append(("guard hook installed", os.path.exists(hook)))
    proc = subprocess.run(["git", "-C", repo, "log", "--oneline"],
                          capture_output=True, text=True)
    checks.append(("every batch committed", proc.stdout.count("TURN:") >= 5))

    width = max(len(name) for name, _ in checks)
    ok = True
    print(f"demo repo: {repo}")
    for name, passed in checks:
        ok = ok and passed
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
    print("demo:", "all checks passed" if ok else "FAILURES ABOVE")
    if not ok:
        raise SystemExit(1)
