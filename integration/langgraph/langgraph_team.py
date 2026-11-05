"""LangGraph orchestration of the accepted team seat loop (project @ 46fa728).

Division of responsibility:
- LangGraph owns scheduling, conditional routing, parallel lane execution
  and durable checkpoints (SqliteSaver; enforced OUTSIDE the team repo so
  the bus never commits it).
- The project's own code keeps owning turn mechanics: lease, prompt build,
  adapter call, roster/verify validation, guard-hook commit, handoff and
  archive (launcher.runtime.Seat over the git bus). The seat set is read
  from the project's roster (launcher.cli.default_roster), not hardcoded.

Execution-time fences (not just sync-time checks):
- seat_node re-reads bus state and roster IMMEDIATELY before acting: the
  run must be status "running", the written turn must name this seat, and
  the roster adapter spec must be type "mock". Then the Seat is
  CONSTRUCTED and the constructed adapter instance must be a MockAdapter
  before act_once runs - a roster change between sync and execution (or a
  resumed pending seat after an operator halt/roster edit) cannot reach a
  non-mock adapter. Refusals are recorded and route to the terminal node.
- A halted/closed/paused team state routes to a terminal node; this graph
  never clears a halt or flips status itself. No provider call is possible
  from this graph: every adapter that is not MockAdapter is refused.

Known limits (stated, not fixed here):
- stop_after is a GRACEFUL stop at a node boundary after N seat actions.
  It is not crash simulation and not exactly-once: the git bus and the
  sqlite checkpoint are two stores with no atomic commit across them. A
  crash between a seat's bus commit and the checkpoint write can replay a
  sync; the bus (turn token, leases, head bindings) is what makes that
  safe, not LangGraph.
- SEAT_GATE is process-local and optional: it caps concurrent seat
  ACTIONS inside this one process. A single seat action can make more
  than one adapter call (format-correction round), so the gate is NOT a
  provider budget and NOT a real request-concurrency control. No
  RequestBudget, allowance window or completion guard is wired in here;
  the Ryan runner (tools/ryan_cycle.py) and the allowance mechanism are
  untouched.
- Resume continuity proven so far is a narrow NEW-process sqlite demo.
  Team-state durability (turn, artifacts, evidence) is the git bus;
  LangGraph checkpoints cover orchestration state only. InMemorySaver is
  never used for a persistence claim. This is not live readiness.

Phases (separate OS processes on purpose, to prove restart):
  init    - fresh demo repo, scripted mock queues, first turn issued
  run     - execute the graph; --stop-after N stops gracefully
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
from typing import Annotated, TypedDict

from launcher.bus import Bus
from launcher.cli import default_roster
from launcher.demo import _scripts
from launcher.runtime import Seat, SeatError

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

BRANCH = "team-work"
# Seat set grounded in the project registry, not invented here.
SEATS = tuple(default_roster().keys())

# Shared cross-lane concurrency cap: one gate for ALL seat actions in
# this process. Optional and process-local - see module docstring for
# exactly why this is NOT a provider budget or request-concurrency
# control.
SEAT_GATE = None          # optional threading.BoundedSemaphore
GATE_MONITOR = None       # optional GateMonitor

# A sibling marker file (never inside the repo: commit_all would sweep it
# and the guard would reject seat commits) proving a directory is one of
# our fresh demo repos, so init never deletes anything else.
MARKER_SUFFIX = ".lg-demo-fresh"


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
    seat_error: str | None
    max_steps: int


# ---------- repo setup ----------------------------------------------------

def _init_safe(repo: str) -> None:
    """Fail closed unless `repo` is a safe fresh demo location."""
    forbidden = {"/", os.path.expanduser("~"), os.path.abspath(os.getcwd())}
    if repo in forbidden:
        raise SystemExit(f"init refused: {repo} is a forbidden location")
    marker = repo + MARKER_SUFFIX
    if os.path.exists(repo):
        if not os.path.isdir(repo):
            raise SystemExit(f"init refused: {repo} exists and is not a dir")
        if os.listdir(repo):
            # Never clear or re-init a non-empty directory, marked or not.
            # Recreating a used demo is a conscious manual delete.
            raise SystemExit(
                f"init refused: {repo} is non-empty; delete it by hand if "
                f"it is really disposable")
    else:
        os.makedirs(repo)


def init_repo(repo: str) -> None:
    repo = os.path.abspath(repo)
    _init_safe(repo)
    env = dict(os.environ)
    argv = [sys.executable, "-m", "launcher"]

    def run(*args):
        proc = subprocess.run(argv + list(args), cwd=repo, env=env,
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit(f"init step failed: {' '.join(args)}\n{proc.stderr}")

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
    # Mark only AFTER successful init: the marker says this directory is a
    # disposable fresh demo this tool created.
    with open(repo + MARKER_SUFFIX, "w") as fh:
        fh.write("fresh langgraph demo repo; safe for this tool to recreate\n")
    print(f"init: repo ready at {repo}", flush=True)


# ---------- graph nodes ---------------------------------------------------

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
    if state.get("seat_error"):
        return "terminal"
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
    """Act one seat, with execution-time fences against every TOCTOU the
    sync-time checks could miss."""
    repo = state["repo"]
    bus = Bus(repo, BRANCH)

    # Fence 1: re-read live state at execution time - a resumed pending
    # seat after an operator halt, or a turn that moved since sync, is
    # refused here, not at the stale sync snapshot.
    live = bus.state()
    if live.get("status") != "running":
        return {"seat_error": f"{seat} refused at execution: bus status "
                              f"is {live.get('status')!r}, not running"}
    if live.get("turn") != seat:
        return {"seat_error": f"{seat} refused at execution: turn is "
                              f"{live.get('turn')!r}"}

    # Fence 2: re-read the roster adapter spec at execution time, then
    # fence the CONSTRUCTED adapter instance - even a roster swapped
    # between this check and Seat construction cannot reach act_once
    # with a non-mock adapter.
    spec = bus.roster().get("seats", {}).get(seat, {})
    spec_type = spec.get("adapter", {}).get("type")
    if spec_type != "mock":
        return {"seat_error": f"{seat} refused at execution: roster "
                              f"adapter is {spec_type!r}, not mock"}
    seat_obj = Seat(bus, seat)
    adapter = getattr(seat_obj, "adapter", None)
    if adapter is None or type(adapter).__name__ != "MockAdapter":
        return {"seat_error": f"{seat} refused at execution: constructed "
                              f"adapter is {type(adapter).__name__}, not "
                              f"MockAdapter"}

    if SEAT_GATE is not None:
        SEAT_GATE.acquire()
    if GATE_MONITOR is not None:
        GATE_MONITOR.enter()
    try:
        acted = seat_obj.act_once()
    except SeatError as exc:
        # The project's own machinery refused (stale queued response,
        # lease, verify failure, ...). Record; never swallow.
        rec = (f"[pid {os.getpid()} tid {threading.get_ident()}] "
               f"seat={seat} REFUSED {exc}")
        print(f"  step: {rec}", flush=True)
        return {"steps": [rec],
                "seat_error": f"{seat} refused by project machinery: {exc}"}
    finally:
        if GATE_MONITOR is not None:
            GATE_MONITOR.exit()
        if SEAT_GATE is not None:
            SEAT_GATE.release()
    head = subprocess.run(
        ["git", "-C", repo, "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True).stdout.strip()
    rec = (f"[pid {os.getpid()} tid {threading.get_ident()}] "
           f"seat={seat} acted={acted} head={head}")
    print(f"  step: {rec}", flush=True)
    return {"steps": [rec]}


def terminal_node(state: TeamState) -> dict:
    if state.get("seat_error"):
        outcome = f"terminal: {state['seat_error']}"
    elif state["status"] != "running":
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


def _check_paths(repo: str, checkpoint_db: str) -> tuple[str, str]:
    repo_abs = os.path.abspath(repo)
    db_abs = os.path.abspath(checkpoint_db)
    if os.path.commonpath([repo_abs, db_abs]) == repo_abs:
        raise SystemExit(
            f"refused: checkpoint db {db_abs} is inside the team repo "
            f"{repo_abs}; the bus would commit it (git add -A)")
    return repo_abs, db_abs


def run_graph(repo: str, checkpoint_db: str, stop_after: int,
              thread_id: str) -> None:
    repo_abs, db_abs = _check_paths(repo, checkpoint_db)
    conn = sqlite3.connect(db_abs, check_same_thread=False)
    saver = SqliteSaver(conn)
    app = build_graph(saver)
    config = {"configurable": {"thread_id": thread_id}}
    existing = saver.get_tuple(config)
    if existing is None:
        initial = {"repo": repo_abs, "checkpoint_db": db_abs,
                   "status": "", "turn": None, "adapter_types": {},
                   "steps": [], "outcome": None, "seat_error": None,
                   "max_steps": 50}
    else:
        # Identity match, fail closed: a stored thread must name the SAME
        # repo and checkpoint file the caller asked to run. Resuming a
        # different repo because a thread_id was reused is never allowed.
        stored = existing.checkpoint.get("channel_values", {})
        if (os.path.abspath(stored.get("repo", "")) != repo_abs
                or os.path.abspath(stored.get("checkpoint_db", "")) != db_abs):
            raise SystemExit(
                f"refused: thread {thread_id!r} is bound to repo "
                f"{stored.get('repo')!r} / db {stored.get('checkpoint_db')!r}"
                f", not {repo_abs!r} / {db_abs!r}")
        initial = None  # resume from the durable checkpoint
        print(f"run[{thread_id}]: resuming from checkpoint "
              f"{existing.checkpoint['id']}", flush=True)
    seat_steps = 0
    for chunk in app.stream(initial, config, stream_mode="updates"):
        if any(k.startswith("seat_") for k in chunk):
            seat_steps += 1
            if stop_after and seat_steps >= stop_after:
                print(f"run[{thread_id}]: stopped gracefully after "
                      f"{seat_steps} seat actions (checkpoint durable in "
                      f"{db_abs}; graceful stop, not crash simulation)",
                      flush=True)
                return
    final = app.get_state(config).values
    print(f"run[{thread_id}]: finished. status={final['status']} "
          f"outcome={final.get('outcome') or 'reached END (done)'}", flush=True)


# ---------- verification ----------------------------------------------------

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
