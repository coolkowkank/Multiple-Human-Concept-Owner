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
import urllib.request
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
from launcher.adapters import HttpAdapter, MockAdapter, QueueAdapter
import fenced_http
from fenced_http import FencedHttpAdapter

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
SAFE_CONSTRUCTORS = {"mock": MockAdapter, "queue": QueueAdapter,
                     "http": FencedHttpAdapter}
ALLOWED_ADAPTERS = set(SAFE_CONSTRUCTORS)

# The "http" type is NOT open: a seat spec is accepted only if it is the
# exact fenced shape below (fixed router endpoint, exact price-0 model
# allowlist, zero-cost enforcement, bounded request count with a durable
# usage log OUTSIDE the repo, no extra keys). Any other http spec is
# refused at execution and at the seat boundary, so a swapped roster
# cannot reach a paid model or another host. Allowlist membership is a
# listing fact (price 0 in the router's public listing), not a
# qualification of the model.
HTTP_FREE_BASE = "https://router.requesty.ai/v1"
HTTP_FREE_MODELS = frozenset({"nvidia/nemotron-3-ultra-550b-a55b",
                              "novita/ling-3.1-flash"})
HTTP_KEY_ENV = "REQUESTY_API_KEY"
HTTP_MAX_BUDGET = 8
HTTP_MAX_TOKENS = 8000
HTTP_SPEC_KEYS = {"type", "base_url", "model", "api_key_env", "timeout",
                  "max_tokens", "reasoning_effort", "call_budget",
                  "usage_log", "log_epoch", "require_zero_cost"}


def _http_spec_refusal(spec: dict, repo: str) -> str:
    """'' if spec is the exact fenced free-route shape, else a reason."""
    ad = spec.get("adapter", {}) if isinstance(spec, dict) else {}
    if ad.get("type") != "http":
        return ""
    def isint(v, lo, hi):
        return (isinstance(v, int) and not isinstance(v, bool)
                and lo <= v <= hi)
    if set(ad) - HTTP_SPEC_KEYS:
        return "unknown http spec keys"
    if ad.get("base_url") != HTTP_FREE_BASE:
        return "base_url is not the fixed router endpoint"
    if ad.get("model") not in HTTP_FREE_MODELS:
        return "model is not on the exact price-0 allowlist"
    if ad.get("api_key_env") != HTTP_KEY_ENV:
        return "api_key_env is not the fixed key variable"
    if ad.get("require_zero_cost") is not True:
        return "require_zero_cost must be true"
    if not isint(ad.get("call_budget"), 1, HTTP_MAX_BUDGET):
        return "call_budget must be an int in 1..%d" % HTTP_MAX_BUDGET
    if not isint(ad.get("max_tokens"), 1, HTTP_MAX_TOKENS):
        return "max_tokens must be an int in 1..%d" % HTTP_MAX_TOKENS
    if "timeout" in ad and not isint(ad["timeout"], 1, 300):
        return "timeout must be an int in 1..300"
    if ad.get("reasoning_effort", "low") not in ("low", "medium", "high"):
        return "invalid reasoning_effort"
    ep = ad.get("log_epoch")
    if not isinstance(ep, str) or not fenced_http.EPOCH_RE.match(ep):
        return "log_epoch must match [a-z0-9-]{1,32}"
    if ad.get("usage_log") != fenced_http.log_path(ad["model"], ep):
        return "usage_log must be the fixed derived path for model+epoch"
    return ""

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


def init_repo(repo: str, queue_seats=(), http_seats=None) -> None:
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
    http_seats = dict(http_seats or {})
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.name", "lg-demo"], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.email", "lg@example.com"], check=True)
    run("init", "--default-roster", "--repo", repo)

    bus = Bus(repo, BRANCH)
    roster = bus.roster()
    scripts = _scripts()
    os.makedirs(os.path.join(repo, ".team", "queues"), exist_ok=True)
    for name in roster["seats"]:
        if name in http_seats:
            # Model-backed seat: fenced http spec (see _http_spec_refusal);
            # an invalid spec is refused at execution, not here.
            roster["seats"][name]["adapter"] = dict(http_seats[name])
            continue
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

SEAT_INPUTS = (".team/STATE.json", ".team/roster.json",
               ".team/brief.md", ".team/CONTROL.json")


def _seat_scope(roster: dict, seat: str) -> list:
    """The exact committed files that drive this seat's construction and
    prompt: the four bus inputs plus the seat's queue file when the
    committed spec is a queue adapter. Mock/queue specs carry no other
    file paths (script/legacy adapters are refused outright)."""
    scope = list(SEAT_INPUTS)
    spec = roster.get("seats", {}).get(seat, {})
    if spec.get("adapter", {}).get("type") == "queue":
        q = spec.get("adapter", {}).get("path")
        if isinstance(q, str) and q:
            scope.append(q)
    return scope


def _context_digest(repo: str, roster: dict, seat: str) -> str:
    """Digest of the COMMITTED context this seat was constructed and
    prompted from: the brief bytes and the seat's FULL roster spec
    (adapter params, allowed paths, everything - not just the type).
    Captured at construction and re-compared at every boundary check.
    A committed brief edit with no instruction_seq bump, or a committed
    spec change (e.g. allowed_paths emptied), lands legally in git and
    passes the dirty fence - but the seat still holds the OLD prompt
    and adapter, so applying its response would act on stale context.
    The digest mismatch refuses exactly that. Queue files are NOT in
    the digest: mid-turn queue commits are ordinary, and the queue
    `_queue` binding checks own queue staleness."""
    import hashlib
    proc = subprocess.run(["git", "-C", repo, "show",
                           "HEAD:.team/brief.md"],
                          capture_output=True, text=True)
    brief = proc.stdout if proc.returncode == 0 else None
    body = {"brief": brief,
            "spec": roster.get("seats", {}).get(seat)}
    return hashlib.sha256(json.dumps(body, sort_keys=True,
                                     ensure_ascii=True).encode()
                          ).hexdigest()


def _scoped_dirty(repo: str, paths) -> str:
    """'' if every scoped input matches HEAD, else a short reason.

    The seat runtime constructs its adapter and prompt inputs (roster
    spec, brief, queue lines) from WORKTREE files, and the bus commit
    stages everything in the tree. A dirty input of the same class - a
    locally edited roster naming a script adapter, a hand-edited brief
    (no instruction_seq bump), a raw queue edit - would pass a
    committed-view fence yet drive construction and be swept into the
    turn commit. COMMITTED changes are fine (committed reads and the
    queue-binding staleness checks handle them, and mid-turn queue
    commits are permitted); UNCOMMITTED divergence on a seat input is
    refused. Scoped to the seat's exact inputs, not the whole repo:
    unrelated scratch elsewhere does not block a turn."""
    proc = subprocess.run(["git", "-C", repo, "status", "--porcelain",
                           "--"] + list(paths),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return f"git status failed: {proc.stderr.strip()[:80]}"
    out = proc.stdout.strip()
    return (f"uncommitted seat input: {out.splitlines()[0][:80]}"
            if out else "")


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
    """Operator commit under the SAME per-repo action lock the seats
    hold through apply+commit (accepted upstream e881384): a control
    change is either fully before a seat's final under-lock control
    read or fully after its commit, closing the pause-then-apply race
    the pre-lock design could only narrow.

    Uses the accepted Bus.transact_paths: clean-index precheck BEFORE
    mutation, declared-path byte restoration on failure. Scope limits
    (accepted, documented): the lock is advisory and covers this
    checkout's cooperating writers only - direct git writes and OTHER
    clones are not isolated; a seat may hold the lock through
    verification (up to 600s) while the writer timeout is 30s, so a
    pause during verification surfaces as BusError (not silent, not
    instant); push-retry is at-least-once, not exactly-once."""
    bus = Bus(repo, BRANCH)
    with bus.action_lock():
        return bus.transact_paths(message, paths, mutate)


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


def _http_seat_spec(model, epoch, budget, max_tokens=6000):
    return {"type": "http", "base_url": HTTP_FREE_BASE, "model": model,
            "api_key_env": HTTP_KEY_ENV, "require_zero_cost": True,
            "call_budget": budget, "max_tokens": max_tokens, "timeout": 280,
            "reasoning_effort": "low", "log_epoch": epoch,
            "usage_log": fenced_http.log_path(model, epoch)}


def operator_set_http_seat(repo: str, seat: str, model: str, epoch: str,
                           budget: int, max_tokens: int = 6000) -> None:
    """Operator roster commit: make `seat` a fenced http seat. The spec is
    the exact shape _http_spec_refusal accepts (validated here too); the
    lifetime cap and log identity live in fenced_http, so this cannot
    create budget. Seat-only: other seats are untouched."""
    repo = os.path.abspath(repo)
    spec = _http_seat_spec(model, epoch, budget, max_tokens)
    why = _http_spec_refusal({"adapter": spec}, repo)
    if why:
        raise SystemExit(f"refused: {why}")

    def mutate():
        path = os.path.join(repo, ".team", "roster.json")
        with open(path) as fh:
            roster = json.load(fh)
        roster["seats"][seat]["adapter"] = spec
        with open(path, "w") as fh:
            json.dump(roster, fh, indent=2)

    _operator_transact(repo, f"operator: seat {seat} -> fenced http "
                             f"({model}, epoch {epoch}, budget {budget})",
                       [".team/roster.json"], mutate)


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


def _adapter_type_ok(adapter, spec_type):
    """Exact preselected constructor; for http ONLY, the opt-in audit
    wrapper is allowed when it wraps exactly a FencedHttpAdapter."""
    if type(adapter) is SAFE_CONSTRUCTORS[spec_type]:
        return True
    if spec_type == "http":
        from audit_wiring import AuditedFenced
        return (type(adapter) is AuditedFenced
                and type(adapter.inner) is FencedHttpAdapter)
    return False


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

    def __init__(self, inner, bus: Bus, seat: str, instruction_seq: int,
                 context_digest=None):
        self._inner = inner
        self._bus = bus
        self._seat = seat
        self._instruction_seq = instruction_seq
        if context_digest is None:
            roster = _committed_json(bus.repo, ".team/roster.json")
            if not isinstance(roster, dict):
                roster = {}
            context_digest = _context_digest(bus.repo, roster, seat)
        self._context_digest = context_digest

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
        # All three committed-view reads happen under the SAME action
        # lock the operator writers and the seat transaction use, so
        # state, control and roster are one coherent snapshot - never
        # split across a racing operator commit. Re-entrant: the seat
        # already holds this lock when the pre_apply hook calls us.
        with self._bus.action_lock():
            live = _committed_json(self._bus.repo, ".team/STATE.json")
            if not isinstance(live, dict):  # non-dict: clean refusal
                live = {}
            control = read_control(self._bus.repo)
            roster = _committed_json(self._bus.repo, ".team/roster.json")
            if not isinstance(roster, dict):  # non-dict: clean refusal
                roster = {}
            dirty = _scoped_dirty(self._bus.repo,
                                  _seat_scope(roster, self._seat))
            if dirty:
                raise SeatError(
                    f"{self._seat} refused at seat boundary: {dirty}")
            now_digest = _context_digest(self._bus.repo, roster,
                                         self._seat)
        if now_digest != self._context_digest:
            raise SeatError(
                f"{self._seat} refused at seat boundary: committed "
                f"context changed since construction (brief or seat "
                f"spec moved without an instruction_seq bump) - this "
                f"response was produced against stale context")
        if live.get("status") != "running":
            raise SeatError(
                f"{self._seat} refused at seat boundary: bus status "
                f"is {live.get('status')!r}, not running")
        if live.get("turn") != self._seat:
            raise SeatError(
                f"{self._seat} refused at seat boundary: turn is "
                f"{live.get('turn')!r}")
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
        spec = roster.get("seats", {}).get(self._seat, {})
        spec_type = spec.get("adapter", {}).get("type")
        why = _http_spec_refusal(spec, self._bus.repo)
        if why:
            raise SeatError(
                f"{self._seat} refused at seat boundary: http spec: {why}")
        if (spec_type not in SAFE_CONSTRUCTORS
                or not _adapter_type_ok(self._inner, spec_type)):
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

    # Fence 0: dirty seat INPUTS - a locally edited roster, brief or
    # queue line would drive construction and be swept into the turn
    # commit. Scoped to this seat's exact inputs; committed changes
    # (mid-turn queue commits) and unrelated files do not block.
    committed_roster = _committed_json(repo, ".team/roster.json")
    if not isinstance(committed_roster, dict):
        committed_roster = {}
    dirty = _scoped_dirty(repo, _seat_scope(committed_roster, seat))
    if dirty:
        return {"seat_error": f"{seat} refused at execution: {dirty}"}

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
    why = _http_spec_refusal(bus.roster().get("seats", {}).get(seat, {}),
                             repo)
    if why:
        return {"seat_error": f"{seat} refused at execution: http spec: "
                              f"{why}"}
    seat_obj = Seat(bus, seat)
    adapter = getattr(seat_obj, "adapter", None)
    if spec_type == "http":
        # The runtime built the generic HttpAdapter from the spec; it is
        # never called. Replace it with the fenced single-request adapter.
        if type(adapter) is not HttpAdapter:
            return {"seat_error": f"{seat} refused at execution: unexpected "
                                  f"constructed adapter for http spec"}
        from launcher.runtime import verify_sandbox_ready
        if not verify_sandbox_ready():
            return {"seat_error": f"{seat} refused at execution: model-"
                                  "backed seat requires LG_VERIFY_SANDBOX "
                                  "and the sandbox shim (fail closed)"}
        ad = spec["adapter"]
        adapter = FencedHttpAdapter(
            HTTP_FREE_BASE, ad["model"], ad["api_key_env"], ad["log_epoch"],
            ad["call_budget"], ad["max_tokens"], ad.get("timeout", 300),
            ad.get("reasoning_effort", "low"))
        seat_obj.adapter = adapter
    if (adapter is None
            or type(adapter) is not SAFE_CONSTRUCTORS[spec_type]):
        return {"seat_error": f"{seat} refused at execution: constructed "
                              f"adapter is {type(adapter).__name__}, not "
                              f"the preselected "
                              f"{SAFE_CONSTRUCTORS[spec_type].__name__}"}
    # Boundary guard: re-validates status/turn/control/adapter at the
    # actual adapter call, after the lease claim (see GuardedAdapter).
    if spec_type == "http" and os.environ.get("LG_AUDIT_DIR"):
        from audit_wiring import AuditedFenced
        adapter = AuditedFenced(adapter, seat_obj, os.environ["LG_AUDIT_DIR"])
    guard = GuardedAdapter(
        adapter, bus, seat, read_control(repo)["instruction_seq"],
        context_digest=_context_digest(repo, committed_roster, seat))
    seat_obj.adapter = guard
    # Accepted upstream pre_apply hook (e881384): runs INSIDE the seat
    # transaction - after the under-lock fresh state re-read and the
    # queue-binding checks, BEFORE any write/verify/handoff. Raising
    # SeatError aborts with no residue; the queue line is not consumed.
    # This closes the residual window between the post-call check and
    # apply/commit that the pre-hook design documented as open.
    seat_obj.pre_apply = lambda s, st, resp: guard.boundary_check()

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
    print(f"run[{thread_id}]: this status is the team CYCLE only. Quality is "
          f"unproven unless `langgraph_team.py status` allows closeout.",
          flush=True)


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


# ---------- reproducible multi-seat live entry --------------------------------
# `langgraph_team.py live LANE DB CONFIG [THREAD]`. Operator-owned, never run
# inside a seat. Refuses BEFORE any seat change or request unless: the config
# is a private file outside the lane, the verify sandbox is ready, every
# seat model is on the fixed allowlist and the router's CURRENT listing shows
# price 0 for it. The key is read from a private file, held only in this
# process's environment during the run, never printed, written or exported.
# Lifetime budget cannot be created here (fenced_http owns it).

LIVE_CFG_KEYS = {"key_file", "seats", "brief_extra_file", "stop_after", "preflight"}
LIVE_PREFLIGHT_KEYS = {"anchor_file", "expected_min_reserves", "allow_fresh"}
LIVE_SEAT_KEYS = {"model", "epoch", "budget", "max_tokens"}


def _private_regular(path, what):
    import stat as _s
    st = os.lstat(path)
    if (not _s.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
            or st.st_mode & 0o077):
        raise SystemExit(f"refused: {what} must be a regular file owned by "
                         f"the operator with mode 0600")


def _fresh_free_listing(key, models):
    """GET <router>/models with the key and require, for each model, a row
    whose input and output price are exactly 0. Returns {model: (in, out)}."""
    import math
    req = urllib.request.Request(
        HTTP_FREE_BASE + "/models",
        headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
    try:
        with fenced_http._opener().open(req, timeout=30) as r:
            body = r.read(8 * 1024 * 1024 + 1)
    except Exception as exc:
        raise SystemExit("refused: could not read the router listing "
                         f"({type(exc).__name__})")
    if len(body) > 8 * 1024 * 1024:
        raise SystemExit("refused: listing too large")
    try:
        rows = json.loads(body.decode("utf-8"))["data"]
        by_id = {m["id"]: m for m in rows if isinstance(m, dict)}
    except Exception:
        raise SystemExit("refused: listing not in the expected shape")
    out = {}
    for m in sorted(models):
        row = by_id.get(m)
        if row is None:
            raise SystemExit(f"refused: {m} is not in the current listing")
        prices = []
        for f in ("input_price", "output_price"):
            try:
                v = float(row[f])
            except (KeyError, TypeError, ValueError):
                raise SystemExit(f"refused: {m} has no usable {f}")
            if not math.isfinite(v) or v != 0.0:
                raise SystemExit(f"refused: {m} is not price 0 in the "
                                 f"current listing")
            prices.append(v)
        out[m] = tuple(prices)
    return out


def _closeout(repo):
    """End-of-run operator closeout (shared by run and live)."""
    import done_gate
    st = done_gate.finalize(repo, BRANCH, os.environ.get("LG_OPERATOR_CONFIG"))
    print("closeout: " + json.dumps(st, sort_keys=True), flush=True)
    if st["closeout_allowed"] or os.environ.get("LG_ALLOW_UNPROVEN") == "1":
        return 0
    return 3   # cycle ended but closeout is NOT allowed (quality unproven)


def live_entry(repo, db, config_path, thread_id="live-1") -> int:
    from launcher.runtime import verify_sandbox_ready
    repo = os.path.abspath(repo)
    roster_path = os.path.join(repo, ".team", "roster.json")
    if not os.path.isfile(roster_path):
        raise SystemExit("refused: lane not initialized (run init first)")
    lane = os.path.realpath(repo) + os.sep
    _private_regular(config_path, "config")
    with open(config_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    if not isinstance(cfg, dict) or set(cfg) - LIVE_CFG_KEYS or "seats" not in cfg \
            or "key_file" not in cfg:
        raise SystemExit("refused: config keys must be a subset of "
                         f"{sorted(LIVE_CFG_KEYS)} and include key_file, seats")
    for pth in (config_path, cfg["key_file"], cfg.get("brief_extra_file") or config_path):
        if (os.path.realpath(pth) + os.sep).startswith(lane):
            raise SystemExit("refused: config, key and brief file must be outside the lane")
    _private_regular(cfg["key_file"], "key_file")
    if not verify_sandbox_ready():
        raise SystemExit("refused: the verify sandbox is not ready "
                         "(set LG_VERIFY_SANDBOX=1 with the shim present)")
    with open(roster_path) as fh:
        roster = json.load(fh)
    seats = cfg["seats"]
    if not isinstance(seats, dict) or not seats:
        raise SystemExit("refused: seats must be a non-empty object")
    specs = {}
    for seat, s in seats.items():
        if seat not in roster["seats"]:
            raise SystemExit(f"refused: unknown seat {seat!r}")
        if not isinstance(s, dict) or set(s) - LIVE_SEAT_KEYS \
                or not {"model", "epoch", "budget"} <= set(s):
            raise SystemExit(f"refused: seat {seat!r} needs model, epoch, budget "
                             f"(optional max_tokens) and nothing else")
        specs[seat] = _http_seat_spec(s["model"], s["epoch"], s["budget"],
                                      s.get("max_tokens", 6000))
        why = _http_spec_refusal({"adapter": specs[seat]}, repo)
        if why:
            raise SystemExit(f"refused: seat {seat!r}: {why}")
    extra = None
    if cfg.get("brief_extra_file"):
        _private_regular(cfg["brief_extra_file"], "brief_extra_file")
        with open(cfg["brief_extra_file"], encoding="utf-8") as fh:
            extra = fh.read(16385)
        if len(extra) > 16384:
            raise SystemExit("refused: brief_extra_file over 16KB")
    stop_after = cfg.get("stop_after", 0)
    if not isinstance(stop_after, int) or isinstance(stop_after, bool) or stop_after < 0:
        raise SystemExit("refused: stop_after must be a non-negative int")
    # read-only lifetime reserve preflight (reserve_preflight.py). It reserves
    # nothing; Fenced still owns atomic reservation and the cap. NOT atomic
    # across processes: run one live entry at a time (seats run serially).
    pfc = cfg.get("preflight", {})
    if not isinstance(pfc, dict) or set(pfc) - LIVE_PREFLIGHT_KEYS:
        raise SystemExit("refused: preflight keys must be a subset of "
                         f"{sorted(LIVE_PREFLIGHT_KEYS)}")
    anchor = None
    if pfc.get("anchor_file"):
        if (os.path.realpath(pfc["anchor_file"]) + os.sep).startswith(lane):
            raise SystemExit("refused: anchor_file must be outside the lane")
        _private_regular(pfc["anchor_file"], "anchor_file")
        with open(pfc["anchor_file"], encoding="utf-8") as fh:
            anchor = json.load(fh)
    emr = pfc.get("expected_min_reserves")
    if emr is not None and (not isinstance(emr, int) or isinstance(emr, bool) or emr < 0):
        raise SystemExit("refused: expected_min_reserves must be a non-negative int")
    if pfc.get("allow_fresh") not in (None, True, False):
        raise SystemExit("refused: allow_fresh must be a bool")
    import reserve_preflight
    planned = sum(sp["call_budget"] for sp in specs.values())
    pf = reserve_preflight.preflight(planned, anchor=anchor,
                                     allow_fresh=bool(pfc.get("allow_fresh")),
                                     expected_min_reserves=emr)
    print(f"live: reserve preflight status={pf['status']} planned={planned} "
          f"recorded_reserves={pf['reserves_total']} remaining={pf['remaining']} "
          f"cap={pf['cap']} (read-only; not a reservation, not atomic)", flush=True)
    if pf["status"] != "ok_to_plan":
        raise SystemExit("refused: reserve preflight " + pf["status"] + ": "
                         + "; ".join(pf["problems"])[:300])
    with open(cfg["key_file"], encoding="utf-8") as fh:
        key = fh.read().strip()
    if not key:
        raise SystemExit("refused: empty key")
    listing = _fresh_free_listing(key, {sp["model"] for sp in specs.values()})
    for m, (i, o) in listing.items():
        print(f"live: listing {m} input_price={i} output_price={o} "
              f"(router listing, not billing proof)", flush=True)
    for seat, sp in specs.items():          # only now touch the lane
        if roster["seats"][seat].get("adapter") != sp:
            s = seats[seat]
            operator_set_http_seat(repo, seat, s["model"], s["epoch"],
                                   s["budget"], s.get("max_tokens", 6000))
    if extra:
        with open(os.path.join(repo, ".team", "brief.md"), encoding="utf-8") as fh:
            brief = fh.read()
        if extra not in brief:
            operator_update_instructions(repo, brief + extra,
                                         note="operator reply rules")
    os.environ[HTTP_KEY_ENV] = key
    try:
        run_graph(repo, db, stop_after, thread_id)
    finally:
        os.environ.pop(HTTP_KEY_ENV, None)
    bus_state = Bus(repo, BRANCH).state().get("status")
    if bus_state != "done":
        print(f"live: run stopped with bus status {bus_state!r}; no closeout evaluated",
              flush=True)
        return 0
    return _closeout(repo)


def status_cmd(argv) -> int:
    """Safe closeout status. Default (no operator record) = quality unproven,
    exit 1. With --record/--key-file/--checker-id/--path it delegates to
    done_gate (signed evidence re-verified at read time)."""
    repo = argv[0]
    if "--record" not in argv:
        import json as _j
        import done_gate
        cc, note = done_gate._cycle_complete_at_head(os.path.abspath(repo), BRANCH)
        print(_j.dumps({"cycle_complete": cc, "terminal_done": False,
                        "closeout_allowed": False, "reason": "no operator record",
                        "label": "cycle complete, quality unproven" if cc
                        else "cycle not complete"}, sort_keys=True))
        return 1
    import done_gate
    if any(a.split("=")[0] in ("--repo", "--branch") for a in argv[1:]):
        print("status: --repo/--branch are fixed by the launcher", file=sys.stderr)
        return 2
    return done_gate.main(["--repo", repo, "--branch", BRANCH] + argv[1:])


def main(argv) -> int:
    if len(argv) > 4 and argv[1] == "live":
        return live_entry(argv[2], argv[3], argv[4],
                          argv[5] if len(argv) > 5 else "live-1")
    if len(argv) > 2 and argv[1] == "status":
        return status_cmd(argv[2:])
    phase, repo, db = argv[1], argv[2], argv[3]
    numeric = phase in ("run", "verify")
    stop_after = int(argv[4]) if numeric and len(argv) > 4 else 0
    thread_id = argv[5] if numeric and len(argv) > 5 else "team-demo-1"
    if phase == "init":
        init_repo(repo)
        return 0
    if phase == "init-http":
        seat, model, usage_log = argv[4], argv[5], argv[6]
        init_repo(repo, http_seats={seat: {
            "type": "http", "base_url": HTTP_FREE_BASE, "model": model,
            "api_key_env": HTTP_KEY_ENV, "require_zero_cost": True,
            "call_budget": 2, "max_tokens": 6000, "timeout": 280,
            "reasoning_effort": "low",
            "log_epoch": usage_log,
            "usage_log": fenced_http.log_path(model, usage_log)}})
        return 0
    if phase == "run":
        run_graph(repo, db, stop_after, thread_id)
        # Operator-owned closeout. LG_OPERATOR_CONFIG is a PATH to an operator
        # config outside the lane (never the key). Unset = quality unproven.
        if not (stop_after and Bus(os.path.abspath(repo), BRANCH).state().get("status") != "done"):
            return _closeout(repo)
        return 0
    if phase == "verify":
        return 0 if verify(repo, db, thread_id, expect_resume=True) else 1
    raise SystemExit(f"unknown phase {phase}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
