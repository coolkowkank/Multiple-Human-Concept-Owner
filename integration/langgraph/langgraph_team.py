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
  the roster adapter spec must be an allowed type. Then the Seat is
  CONSTRUCTED and the constructed adapter's exact class identity is
  verified against the PRESELECTED safe constructor for that spec (the
  imported class object itself, not a forgeable __name__ string). And
  because act_once claims the seat lease inside its transaction - moving
  the bus to held before the adapter runs - a GuardedAdapter wrapper
  re-validates status/turn/adapter identity at the adapter call itself,
  after that acquire, at the real mutation boundary; a failed check
  raises SeatError and rolls the transaction back. Refusals are recorded
  and route to the terminal node.
- Allowed adapter types: "mock" (scripted, local) and "queue" (operator-
  fed local JSONL through the project's own `launcher respond` channel,
  stale-bound by turn/seq/head - zero network). Everything else
  (http/cli/live model adapters) is refused: no provider call is possible
  from this graph.
- A halted/closed/paused team state routes to a terminal/paused node;
  this graph never clears a halt or flips status itself.

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
import time
from typing import Annotated, TypedDict

from launcher.bus import Bus
from launcher.cli import default_roster
from launcher.demo import _scripts
from launcher.runtime import Seat, SeatError
from launcher.adapters import MockAdapter, QueueAdapter

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

# Adapter types this graph will execute: scripted local mocks and the
# project's operator queue channel (local JSONL, bound to turn/seq/head,
# stale-refused by the runtime - the accepted live-1 "honest glue"; zero
# network). Everything else is refused at sync AND at execution.
# The value is the PRESELECTED safe constructor for that spec type: the
# actual imported class object. Class identity is not forgeable the way
# type(x).__name__ is, and only these two constructors can ever produce
# an adapter this graph will execute - no registry lookup, no spec
# string that could resolve to a provider-calling class.
SAFE_CONSTRUCTORS = {"mock": MockAdapter, "queue": QueueAdapter}
ALLOWED_ADAPTERS = set(SAFE_CONSTRUCTORS)

# Operator control plane. ONE channel: .team/CONTROL.json inside the git
# bus, mutated only through operator: commits (guard-exempt operational
# commits, same class the project already uses for human:/operator:
# records). Not a competing state path: every seat and every sync reads
# the same committed bus state.
CONTROL_PATH = ".team/CONTROL.json"
PAUSE_MAX_WAITS = 60  # 60 x 0.5s = 30s still-paused timeout


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
    control_mode: str
    instruction_seq: int
    pause_waits: int


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


def init_repo(repo: str, queue_seats=()) -> None:
    repo = os.path.abspath(repo)
    _init_safe(repo)
    env = dict(os.environ)
    # Self-contained: the vendored launcher/ sits next to this file, so
    # put that directory first on the subprocess import path. No
    # external checkout or PYTHONPATH setup is needed.
    here = os.path.dirname(os.path.realpath(__file__))
    env["PYTHONPATH"] = here + os.pathsep + env.get("PYTHONPATH", "")
    argv = [sys.executable, "-m", "launcher"]

    def run(*args):
        proc = subprocess.run(argv + list(args), cwd=repo, env=env,
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit(f"init step failed: {' '.join(args)}\n{proc.stderr}")

    queue_seats = set(queue_seats or ())
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.name", "lg-demo"], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.email", "lg@example.com"], check=True)
    run("init", "--default-roster", "--repo", repo)

    bus = Bus(repo, BRANCH)
    roster = bus.roster()
    scripts = _scripts()
    os.makedirs(os.path.join(repo, ".team", "queues"), exist_ok=True)
    for name in roster["seats"]:
        if name in queue_seats:
            # Operator-fed seat: responses arrive through the project's
            # own `launcher respond` channel, bound to turn/seq/head and
            # stale-refused by the runtime like any live-1 queue seat.
            roster["seats"][name]["adapter"] = {
                "type": "queue", "path": f".team/queues/{name}.jsonl"}
            continue
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
    with open(os.path.join(repo, CONTROL_PATH), "w") as fh:
        json.dump({"mode": "run", "instruction_seq": 1,
                   "note": "initial brief"}, fh, indent=2)
    bus.commit_all("human: brief agreed, first turn issued")
    # Mark only AFTER successful init: the marker says this directory is a
    # disposable fresh demo this tool created.
    with open(repo + MARKER_SUFFIX, "w") as fh:
        fh.write("fresh langgraph demo repo; safe for this tool to recreate\n")
    print(f"init: repo ready at {repo}", flush=True)


# ---------- operator controls (assign / pause / update / resume) ----------

def _committed_json(repo: str, path: str):
    """JSON document as COMMITTED at HEAD, or None. Worktree edits that
    were never committed are invisible, like read_control."""
    proc = subprocess.run(["git", "-C", repo, "show", f"HEAD:{path}"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def read_control(repo: str) -> dict:
    """The graph obeys the COMMITTED control only (git show HEAD:...),
    never the worktree file: an operator change that failed to commit -
    or any hand-edit left dirty in the worktree - is invisible to the
    team. Control takes effect exactly at commit order, so a seat and an
    operator commit racing see one coherent state.

    Schema-strict and fail-CLOSED: anything but a dict with an explicit
    known mode and an integer instruction_seq - missing file, bad JSON,
    wrong type, unknown mode, missing/bool seq - is a HOLD, never run."""
    try:
        proc = subprocess.run(
            ["git", "-C", repo, "show", f"HEAD:{CONTROL_PATH}"],
            capture_output=True, text=True)
        if proc.returncode != 0:
            raise ValueError(f"no committed control: {proc.stderr.strip()}")
        c = json.loads(proc.stdout)
        if (not isinstance(c, dict)
                or c.get("mode") not in ("run", "pause")
                or not isinstance(c.get("instruction_seq"), int)
                or isinstance(c.get("instruction_seq"), bool)):
            raise ValueError(f"invalid control schema: {c!r}")
        return {"mode": c["mode"], "instruction_seq": c["instruction_seq"],
                "note": str(c.get("note", ""))}
    except (OSError, ValueError):
        return {"mode": "pause", "instruction_seq": 1,
                "note": "control missing/unreadable/invalid: fail-closed hold"}


def _write_control(repo: str, **changes) -> dict:
    c = read_control(repo)
    c.update(changes)
    with open(os.path.join(repo, CONTROL_PATH), "w") as fh:
        json.dump(c, fh, indent=2)
    return c


def _operator_transact(repo: str, message: str, paths, mutate):
    """Operator commit with coherent failure semantics:
    - precheck the index BEFORE touching the worktree (a pre-staged
      scratch file must fail the control change BEFORE CONTROL.json is
      dirtied, not after);
    - on ANY failure restore the target files from HEAD, so a failed
      control change never leaves a dirty worktree value the graph
      could read (read_control only trusts HEAD, but other readers -
      and the next operator call - should see a clean tree too).
    """
    bus = Bus(repo, BRANCH)
    bus.assert_index_clean(message)
    try:
        return bus.transact_paths(message, paths, mutate)
    except Exception:
        # Restore worktree AND index for exactly these paths from HEAD
        # (the precheck guarantees HEAD is the pre-change state).
        # Concurrency note: restoration is not race-safe against a
        # simultaneous seat commit; the coherent fix is the upstream
        # shared repo lock (executor-owned, already requested).
        subprocess.run(
            ["git", "-C", repo, "checkout", "HEAD", "--"] + list(paths),
            check=False)
        raise


def operator_pause(repo: str, note="operator pause") -> None:
    # transact_paths, never commit_all: an operator commit must not sweep
    # an in-flight seat's worktree changes into the control commit.
    repo = os.path.abspath(repo)
    _operator_transact(
        repo, f"operator: pause - {note}", [CONTROL_PATH],
        lambda: _write_control(repo, mode="pause", note=note))


def operator_resume(repo: str, note="operator resume") -> None:
    repo = os.path.abspath(repo)
    _operator_transact(
        repo, f"operator: resume - {note}", [CONTROL_PATH],
        lambda: _write_control(repo, mode="run", note=note))


def operator_update_instructions(repo: str, text: str,
                                 note="instructions updated") -> int:
    """Rewrite the brief and bump instruction_seq. This is an ordinary
    non-queue commit, so every queued response bound to the old head is
    stale by the project's own head-binding rule and will be refused at
    apply time - old instructions can never be applied after an update."""
    repo = os.path.abspath(repo)

    def mutate():
        with open(os.path.join(repo, ".team", "brief.md"), "w") as fh:
            fh.write(text)
        return _write_control(
            repo,
            instruction_seq=read_control(repo)["instruction_seq"] + 1,
            note=note)

    c = _operator_transact(
        repo, f"operator: {note}", [".team/brief.md", CONTROL_PATH], mutate)
    return c["instruction_seq"]


def operator_assign(repo: str, brief: str, seat: str,
                    note="new assignment") -> None:
    """Assign new work: fresh brief, turn to the named seat, team back to
    running - through the same bus commit path as the human seed."""
    repo = os.path.abspath(repo)
    bus = Bus(repo, BRANCH)

    def mutate():
        with open(os.path.join(repo, ".team", "brief.md"), "w") as fh:
            fh.write(brief)
        state = bus.state()
        state["turn"] = seat
        state["status"] = "running"
        bus.write_state(state)
        _write_control(
            repo,
            instruction_seq=read_control(repo)["instruction_seq"] + 1,
            note=note)

    _operator_transact(repo, f"operator: assign to {seat} - {note}",
                       [".team/brief.md", ".team/STATE.json", CONTROL_PATH],
                       mutate)


# ---------- graph nodes ---------------------------------------------------

def sync_node(state: TeamState) -> dict:
    bus = Bus(state["repo"], BRANCH)
    s = bus.state()
    roster = bus.roster()
    control = read_control(state["repo"])
    return {
        "status": s.get("status"),
        "turn": s.get("turn"),
        "adapter_types": {n: spec.get("adapter", {}).get("type")
                          for n, spec in roster.get("seats", {}).items()},
        "control_mode": control["mode"],
        "instruction_seq": control["instruction_seq"],
    }


def route_after_sync(state: TeamState) -> str:
    if state.get("seat_error"):
        return "terminal"
    if state["status"] == "done":
        return END
    if state["status"] != "running":
        return "terminal"  # halted or any non-running state: never touched
    if state.get("control_mode") == "pause":
        # Operator hold: wait in the paused node, checkpoint durable,
        # until resume or the still-paused timeout.
        return "paused" if state.get("pause_waits", 0) < PAUSE_MAX_WAITS else "terminal"
    if len(state["steps"]) >= state["max_steps"]:
        return "terminal"
    turn = state["turn"]
    if turn not in SEATS:
        return "terminal"
    if state["adapter_types"].get(turn) not in ALLOWED_ADAPTERS:
        return "terminal"  # provider-calling adapter: not authorized here
    return f"seat_{turn}"


# verify_command payloads may run with shell=True inside the seat
# runtime. This screen is a SHALLOW guard, not a sandbox: only simple
# local test-runner commands pass, and it says nothing about what a
# vetted command itself does. Authorship of mock/queue payloads is a
# trust decision by the operator, not authenticated provenance.
_VERIFY_CMD_ALLOWED = ("python3", "python", "pytest")
_VERIFY_CMD_METACHARS = set(";&|`$<>\n\r")


def _screen_verify_command(cmd, seat: str) -> None:
    if cmd is None:
        return
    if (not isinstance(cmd, str) or not cmd.strip()
            or any(c in _VERIFY_CMD_METACHARS for c in cmd)):
        raise SeatError(
            f"{seat} refused response: verify_command {str(cmd)[:40]!r} "
            f"is not a simple command (no shell metacharacters allowed)")
    tokens = cmd.split()
    if (tokens[0] not in _VERIFY_CMD_ALLOWED
            or any(t.startswith("/") or ".." in t for t in tokens)):
        raise SeatError(
            f"{seat} refused response: verify_command must start with "
            f"{_VERIFY_CMD_ALLOWED} and stay relative to the repo")


class GuardedAdapter:
    """Boundary guard wrapped around the constructed adapter.

    Seat.act_once() invokes the adapter INSIDE its transaction, after
    claim_lease. Checks that ran before act_once therefore have a
    window: an operator pause/halt, instruction update, or roster swap
    landing between the pre-checks and the actual adapter call would
    still be acted on. This guard re-validates at the adapter call
    itself - the real mutation boundary - including the operator
    CONTROL mode and instruction_seq, so a pause issued while this seat
    waited on the seat gate is still honored.

    Exact guarantee on refusal: SeatError propagates out of mutate()
    BEFORE this turn's commit, so the in-memory lease/turn changes are
    never committed. The git bus transact is pull/commit/push/retry -
    it is NOT isolation and NOT rollback of already-committed state;
    nothing in this turn has committed yet when the guard raises.
    """

    def __init__(self, inner, bus: Bus, seat: str, instruction_seq: int):
        self._inner = inner
        self._bus = bus
        self._seat = seat
        self._instruction_seq = instruction_seq

    def __getattr__(self, name):  # consume(), attributes: pass through
        return getattr(self._inner, name)

    def boundary_check(self) -> None:
        """Refuse unless the seat may act RIGHT NOW: bus running, turn
        names this seat, operator control is run at the instruction_seq
        this step started with, and the roster spec still resolves to
        the preselected safe constructor. Called before the adapter
        runs, again after it returns, and at the pre-apply hook.

        All three reads (state, control, roster) are the COMMITTED
        view: an uncommitted hand-edit left in the worktree cannot
        authorize a seat action."""
        live = _committed_json(self._bus.repo, ".team/STATE.json")
        if not isinstance(live, dict):  # non-dict JSON: no action, clean refusal
            live = {}
        if live.get("status") != "running":
            raise SeatError(
                f"{self._seat} refused at seat boundary: bus status "
                f"is {live.get('status')!r}, not running")
        if live.get("turn") != self._seat:
            raise SeatError(
                f"{self._seat} refused at seat boundary: turn is "
                f"{live.get('turn')!r}")
        control = read_control(self._bus.repo)
        if control["mode"] != "run":
            raise SeatError(
                f"{self._seat} refused at seat boundary: operator "
                f"control mode is {control['mode']!r} "
                f"({control['note']})")
        if control["instruction_seq"] != self._instruction_seq:
            raise SeatError(
                f"{self._seat} refused at seat boundary: instructions "
                f"moved to seq {control['instruction_seq']}, this seat "
                f"step started at seq {self._instruction_seq}")
        roster = _committed_json(self._bus.repo, ".team/roster.json")
        if not isinstance(roster, dict):  # non-dict JSON: no action, clean refusal
            roster = {}
        spec = roster.get("seats", {}).get(self._seat, {})
        spec_type = spec.get("adapter", {}).get("type")
        if (spec_type not in SAFE_CONSTRUCTORS
                or type(self._inner) is not SAFE_CONSTRUCTORS[spec_type]):
            raise SeatError(
                f"{self._seat} refused at seat boundary: adapter "
                f"{type(self._inner).__name__} is not the preselected "
                f"constructor for spec {spec_type!r}")

    def complete(self, system, prompt):
        self.boundary_check()
        response = self._inner.complete(system, prompt)
        # A pause/update/halt landing DURING the adapter call is caught
        # here, before the response may be applied.
        self.boundary_check()
        if type(self._inner) is QueueAdapter:
            # Queue is an EFFECTS channel, not inherently bound: the
            # runtime's stale-binding check only fires when a _queue
            # block exists, so a raw unbound line would be applied
            # unconditionally. Require the operator-channel binding
            # (turn/turn_seq/head) here. Peek-only: the line is NOT
            # consumed on refusal, the queue is preserved.
            binding = response.get("_queue") if isinstance(response, dict) else None
            if (not isinstance(binding, dict)
                    or not all(k in binding
                               for k in ("turn", "turn_seq", "head"))):
                raise SeatError(
                    f"{self._seat} refused at adapter boundary: queued "
                    f"response carries no _queue binding "
                    f"(turn/turn_seq/head); queue it through "
                    f"`launcher respond`, not by hand")
        if isinstance(response, dict):
            _screen_verify_command(response.get("verify_command"), self._seat)
        return response


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
    # with a provider-calling adapter.
    spec = bus.roster().get("seats", {}).get(seat, {})
    spec_type = spec.get("adapter", {}).get("type")
    if spec_type not in ALLOWED_ADAPTERS:
        return {"seat_error": f"{seat} refused at execution: roster "
                              f"adapter is {spec_type!r}, not one of "
                              f"{sorted(ALLOWED_ADAPTERS)}"}
    seat_obj = Seat(bus, seat)
    adapter = getattr(seat_obj, "adapter", None)
    if (adapter is None
            or type(adapter) is not SAFE_CONSTRUCTORS[spec_type]):
        return {"seat_error": f"{seat} refused at execution: constructed "
                              f"adapter is {type(adapter).__name__}, not "
                              f"the preselected "
                              f"{SAFE_CONSTRUCTORS[spec_type].__name__}"}
    # Boundary guard: re-validates status/turn/control/adapter at the
    # actual adapter call, after the lease claim (see GuardedAdapter).
    seat_obj.adapter = GuardedAdapter(
        adapter, bus, seat, read_control(repo)["instruction_seq"])

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
           f"seat={seat} acted={acted} head={head} "
           f"seq={state.get('instruction_seq')}")
    print(f"  step: {rec}", flush=True)
    return {"steps": [rec]}


def paused_node(state: TeamState) -> dict:
    waits = state.get("pause_waits", 0) + 1
    if waits == 1:
        print("  paused: operator hold in effect; waiting for resume "
              "(checkpoint durable)", flush=True)
    time.sleep(0.5)
    return {"pause_waits": waits}


def terminal_node(state: TeamState) -> dict:
    if state.get("seat_error"):
        outcome = f"terminal: {state['seat_error']}"
    elif state["status"] != "running":
        outcome = f"terminal: bus status is {state['status']!r} (not touched)"
    elif state.get("control_mode") == "pause":
        outcome = (f"terminal: still paused after {PAUSE_MAX_WAITS} waits; "
                   f"checkpoint durable - resume later")
    elif len(state["steps"]) >= state["max_steps"]:
        outcome = f"terminal: step cap {state['max_steps']} reached"
    elif state["turn"] not in SEATS:
        outcome = f"terminal: no seat owns turn {state['turn']!r}"
    else:
        outcome = (f"terminal: adapter for {state['turn']} is "
                   f"{state['adapter_types'].get(state['turn'])!r} - only "
                   f"mock (scripted) and queue (operator-fed, stale-bound) "
                   f"seats are allowed; provider-calling/live adapters are "
                   f"not authorized in this graph")
    print(f"  {outcome}", flush=True)
    return {"outcome": outcome}


def build_graph(saver: SqliteSaver):
    g = StateGraph(TeamState)
    g.add_node("sync", sync_node)
    for seat in SEATS:
        g.add_node(f"seat_{seat}", lambda s, _seat=seat: seat_node(_seat, s))
    g.add_node("terminal", terminal_node)
    g.add_node("paused", paused_node)
    g.add_edge(START, "sync")
    g.add_conditional_edges(
        "sync", route_after_sync,
        {**{f"seat_{s}": f"seat_{s}" for s in SEATS},
         "paused": "paused", "terminal": "terminal", END: END})
    for seat in SEATS:
        g.add_edge(f"seat_{seat}", "sync")
    g.add_edge("paused", "sync")
    g.add_edge("terminal", END)
    return g.compile(checkpointer=saver)


def _check_paths(repo: str, checkpoint_db: str) -> tuple[str, str]:
    # Canonical paths only: a symlinked parent would let one directory
    # alias another, bypassing both the db-outside-repo check below and
    # the resume identity check (same repo, two lexical spellings).
    repo_abs = os.path.realpath(repo)
    db_abs = os.path.realpath(checkpoint_db)
    if (os.path.abspath(repo) != repo_abs
            or os.path.abspath(checkpoint_db) != db_abs):
        raise SystemExit(
            f"refused: non-canonical path (symlink or alias): "
            f"{repo!r} resolves to {repo_abs!r}, "
            f"{checkpoint_db!r} resolves to {db_abs!r}; run against the "
            f"canonical location")
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
                   "max_steps": 50, "control_mode": "run",
                   "instruction_seq": 1, "pause_waits": 0}
    else:
        # Identity match, fail closed: a stored thread must name the SAME
        # repo and checkpoint file the caller asked to run. Resuming a
        # different repo because a thread_id was reused is never allowed.
        stored = existing.checkpoint.get("channel_values", {})
        if (os.path.realpath(stored.get("repo", "")) != repo_abs
                or os.path.realpath(stored.get("checkpoint_db", ""))
                != db_abs):
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
