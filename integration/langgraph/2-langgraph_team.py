"""LangGraph orchestration of the accepted team seat loop (project @ 46fa728).

Division of responsibility:
- LangGraph owns scheduling, conditional routing, parallel lane execution
  and durable checkpoints (SqliteSaver, a file OUTSIDE the team repo so
  the bus never commits it).
- The project's own code keeps owning turn mechanics: lease, prompt build,
  adapter call, roster/verify validation, guard-hook commit, handoff and
  archive (launcher.runtime.Seat over the git bus). Nothing here
  re-implements or bypasses those. The seat set comes from the project's
  own roster (launcher.cli.default_roster), not a hardcoded role list.

Hard limits of this integration:
- Mock (scripted) adapters only. Any seat whose roster adapter is not
  type "mock" routes to a blocked terminal: this graph cannot make a
  provider/model call. Live adapters, the Ryan runner (ryan_cycle.py),
  the RequestBudget composition and the allowance mechanism (v2 a8cae7a,
  under review) are untouched and NOT wired in.
- Parallelism is across INDEPENDENT lanes (separate tasks/repos). Within
  a lane the project's dependency edges hold: the single turn token
  serializes coordinator -> builder -> reviewer -> qc -> records, so
  verification still waits on the build and QC on the review. A shared
  seat gate (SEAT_GATE) caps how many seats across ALL lanes act at
  once - one shared control, not a per-lane allowance.
- A halted/closed team state routes to a terminal node; this graph never
  clears a halt or flips status itself.
- Durability claim is precise: LangGraph checkpoints the ORCHESTRATION
  state (which seat to schedule next, step trace). Team state (turn,
  artifacts, verify evidence) stays durable in the git bus, as before.
  InMemorySaver is never used for a persistence claim.

Phases (separate OS processes on purpose, to prove restart):
  init    - fresh demo repo, scripted mock queues, first turn issued
  run     - execute the graph; --stop-after N simulates an interruption
  verify  - demo-equivalent checks + LangGraph resume/step evidence
"""

from __future__ import annotations

import json
import operator
import os
import sqlite3
import subprocess
import sys
import threading
import time
from typing import Annotated, TypedDict

from launcher.bus import Bus
from launcher.cli import default_roster
from launcher.demo import _scripts
from launcher.runtime import Seat

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

BRANCH = "team-work"
# Seat set grounded in the project registry, not invented here.
SEATS = tuple(default_roster().keys())

# Shared cross-lane concurrency control: one gate for ALL seat actions in
# this process, however many lanes are running. A seat action is the unit
# that would spend a provider request in live mode, so this is the point
# where a shared budget control attaches. Mock mode spends nothing.
SEAT_GATE = None          # optional threading.BoundedSemaphore
GATE_MONITOR = None       # optional GateMonitor


class GateMonitor:
    def __init__(self):
        self.lock = threading.Lock()
        self.current = 0
        self.high_water = 0
        self.acquisitions = 0

    def enter(self):
        with self.lock:
            self.current += 1
            self.acquisitions += 1
            self.high_water = max(self.high_water, self.current)

    def exit(self):
        with self.lock:
            self.current -= 1


class TeamState(TypedDict):
    repo: str
    checkpoint_db: str
    status: str
    turn: str | None
    adapter_types: dict
    steps: Annotated[list, operator.add]
    outcome: str | None
    max_steps: int


# ---------- repo setup (mirrors launcher.demo, but file-backed queues so
# a NEW process resumes each seat's script where the last one stopped) --

def init_repo(repo: str) -> None:
    repo = os.path.abspath(repo)
    env = dict(os.environ)
    argv = [sys.executable, "-m", "launcher"]

    def run(*args):
        proc = subprocess.run(argv + list(args), cwd=repo, env=env,
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit(f"init step failed: {' '.join(args)}\n{proc.stderr}")

    subprocess.run(["rm", "-rf", repo], check=True)
    os.makedirs(repo)
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.name", "lg-demo"], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.email", "lg@example.com"], check=True)
    run("init", "--default-roster", "--repo", repo)

    bus = Bus(repo, BRANCH)
    roster = bus.roster()
    scripts = _scripts()
    os.makedirs(os.path.join(repo, ".team", "queues"), exist_ok=True)
    for name in roster["seats"]:
        queue = os.path.join(repo, ".team", "queues", f"{name}.mock.jsonl")
        with open(queue, "w") as fh:
            for response in scripts[name]:
                fh.write(json.dumps(response) + "\n")
        roster["seats"][name]["adapter"] = {
            "type": "mock", "script": [], "script_path": queue}
    with open(os.path.join(repo, ".team", "roster.json"), "w") as fh:
        json.dump(roster, fh, indent=2)
    with open(os.path.join(repo, ".team", "brief.md"), "w") as fh:
        fh.write("# Brief\nBuild a tiny add(a,b) library with a passing test.\n")
    state = bus.state()
    state["turn"] = "coordinator"
    state["status"] = "running"
    bus.write_state(state)
    bus.commit_all("human: brief agreed, first turn issued")
    print(f"init: repo ready at {repo}", flush=True)


# ---------- graph nodes --------------------------------------------------

def sync_node(state: TeamState) -> dict:
    bus = Bus(state["repo"], BRANCH)
    s = bus.state()
    roster = bus.roster()
    return {
        "status": s.get("status"),
        "turn": s.get("turn"),
        "adapter_types": {n: spec.get("adapter", {}).get("type")
                          for n, spec in roster.get("seats", {}).items()},
    }


def route_after_sync(state: TeamState) -> str:
    if state["status"] == "done":
        return END
    if state["status"] != "running":
        return "terminal"  # halted or any non-running state: never touched
    if len(state["steps"]) >= state["max_steps"]:
        return "terminal"
    turn = state["turn"]
    if turn not in SEATS:
        return "terminal"
    if state["adapter_types"].get(turn) != "mock":
        return "terminal"  # live/queue/cli adapter: not authorized here
    return f"seat_{turn}"


def seat_node(seat: str, state: TeamState) -> dict:
    if SEAT_GATE is not None:
        SEAT_GATE.acquire()
    if GATE_MONITOR is not None:
        GATE_MONITOR.enter()
    try:
        acted = Seat(Bus(state["repo"], BRANCH), seat).act_once()
    finally:
        if GATE_MONITOR is not None:
            GATE_MONITOR.exit()
        if SEAT_GATE is not None:
            SEAT_GATE.release()
    head = subprocess.run(
        ["git", "-C", state["repo"], "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True).stdout.strip()
    rec = (f"[pid {os.getpid()} tid {threading.get_ident()}] "
           f"seat={seat} acted={acted} head={head}")
    print(f"  step: {rec}", flush=True)
    return {"steps": [rec]}


def terminal_node(state: TeamState) -> dict:
    if state["status"] != "running":
        outcome = f"terminal: bus status is {state['status']!r} (not touched)"
    elif len(state["steps"]) >= state["max_steps"]:
        outcome = f"terminal: step cap {state['max_steps']} reached"
    elif state["turn"] not in SEATS:
        outcome = f"terminal: no seat owns turn {state['turn']!r}"
    else:
        outcome = (f"terminal: adapter for {state['turn']} is "
                   f"{state['adapter_types'].get(state['turn'])!r}, not mock - "
                   f"live model execution not authorized in this graph")
    print(f"  {outcome}", flush=True)
    return {"outcome": outcome}


def build_graph(saver: SqliteSaver):
    g = StateGraph(TeamState)
    g.add_node("sync", sync_node)
    for seat in SEATS:
        g.add_node(f"seat_{seat}", lambda s, _seat=seat: seat_node(_seat, s))
    g.add_node("terminal", terminal_node)
    g.add_edge(START, "sync")
    g.add_conditional_edges(
        "sync", route_after_sync,
        {**{f"seat_{s}": f"seat_{s}" for s in SEATS},
         "terminal": "terminal", END: END})
    for seat in SEATS:
        g.add_edge(f"seat_{seat}", "sync")
    g.add_edge("terminal", END)
    return g.compile(checkpointer=saver)


def run_graph(repo: str, checkpoint_db: str, stop_after: int,
              thread_id: str) -> None:
    conn = sqlite3.connect(checkpoint_db, check_same_thread=False)
    saver = SqliteSaver(conn)
    app = build_graph(saver)
    config = {"configurable": {"thread_id": thread_id}}
    existing = saver.get_tuple(config)
    if existing is None:
        initial = {"repo": os.path.abspath(repo), "checkpoint_db": checkpoint_db,
                   "status": "", "turn": None, "adapter_types": {},
                   "steps": [], "outcome": None, "max_steps": 50}
    else:
        initial = None  # resume from the durable checkpoint
        print(f"run[{thread_id}]: resuming from checkpoint "
              f"{existing.checkpoint['id']}", flush=True)
    seat_steps = 0
    for chunk in app.stream(initial, config, stream_mode="updates"):
        if any(k.startswith("seat_") for k in chunk):
            seat_steps += 1
            if stop_after and seat_steps >= stop_after:
                print(f"run[{thread_id}]: INTERRUPTED after {seat_steps} seat "
                      f"actions (checkpoint durable in {checkpoint_db})",
                      flush=True)
                return
    final = app.get_state(config).values
    print(f"run[{thread_id}]: finished. status={final['status']} "
          f"outcome={final.get('outcome') or 'reached END (done)'}", flush=True)


# ---------- verification ---------------------------------------------------

def verify(repo: str, checkpoint_db: str, thread_id: str,
           expect_resume: bool) -> bool:
    repo = os.path.abspath(repo)
    bus = Bus(repo, BRANCH)
    state = bus.state()
    checks = []
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

    conn = sqlite3.connect(checkpoint_db, check_same_thread=False)
    saver = SqliteSaver(conn)
    app = build_graph(saver)
    snap = app.get_state({"configurable": {"thread_id": thread_id}})
    steps = snap.values.get("steps", [])
    pids = {s.split("]")[0] for s in steps}
    checks.append(("langgraph step trace recorded", len(steps) >= 6))
    if expect_resume:
        checks.append(("resumed in a NEW process (two pids in trace)",
                       len(pids) == 2))
    n_checkpoints = sum(1 for _ in app.get_state_history(
        {"configurable": {"thread_id": thread_id}}))
    checks.append(("durable sqlite checkpoints present",
                   n_checkpoints >= len(steps)))

    width = max(len(n) for n, _ in checks)
    ok = True
    print(f"verification[{thread_id}]:")
    for name, passed in checks:
        ok = ok and passed
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
    print("langgraph step trace:")
    for s in steps:
        print(f"  {s}")
    print(f"verify[{thread_id}]:",
          "all checks passed" if ok else "FAILURES ABOVE", flush=True)
    return ok


def main(argv) -> int:
    phase, repo, db = argv[1], argv[2], argv[3]
    stop_after = int(argv[4]) if len(argv) > 4 else 0
    thread_id = argv[5] if len(argv) > 5 else "team-demo-1"
    if phase == "init":
        init_repo(repo)
        return 0
    if phase == "run":
        run_graph(repo, db, stop_after, thread_id)
        return 0
    if phase == "verify":
        return 0 if verify(repo, db, thread_id, expect_resume=True) else 1
    raise SystemExit(f"unknown phase {phase}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
