# LangGraph team orchestration (integration in progress)

**Status: work in progress. Mock (scripted) adapters only - no live model
calls, no live named team, no paid hosting. Not merged readiness; this
branch exists so the work is visible and reviewable.**

## What this is

An orchestration layer that drives the project's existing team machinery
(`launcher.runtime.Seat` over the git bus) through a LangGraph state graph
(LangGraph 1.2.19):

- LangGraph owns scheduling, conditional routing, parallel lane execution
  and durable checkpoints (`SqliteSaver`, enforced OUTSIDE the team repo
  so the bus never commits it; a checkpoint path inside the repo is
  refused).
- The project's own code keeps owning turn mechanics: lease, prompt build,
  adapter call, roster/verify validation, guard-hook commit, handoff and
  archive. The seat set is read from the project's roster
  (`launcher.cli.default_roster`), not hardcoded here.

Files:

- `langgraph_team.py` - single-lane orchestrator with execution-time
  fences (below), durable resume, graceful stop, and the operator control
  channel (assign / pause / update-instructions / resume).
- `parallel_team.py` - parent graph running several independent lanes
  concurrently, with one shared seat gate capping simultaneous seat
  actions across all lanes, plus a deterministic no-network overlap test.
- `controls_demo.py` - scripted operator-intervention run proving the
  four controls below.
- `launcher/` - vendored copy of the project's own seat runtime (bus,
  roster, adapters, CLI), copied byte-exact from
  `ryan-continuous-offline` @ 46fa7284a173c4b96a3a08c1ca8ffa22d6693391.
  Project code, unchanged; included so the documented commands run
  as-is. Scope note: this predates the later local allowance-window and
  verified-revision-binding increments (not yet pushed anywhere); none
  of those guards are integrated or claimed here.

## Execution-time safety fences

Sync-time checks alone would be racy, so `seat_node` re-verifies
IMMEDIATELY before acting:

1. Bus status must be `running` and the written turn must name this seat
   - a resumed pending seat after an operator halt is refused.
2. The roster adapter spec must be an allowed type: `mock` (scripted,
   local) or `queue`. A queue seat applies OPERATOR-AUTHORED responses
   queued through the project's own `launcher respond` channel. The
   queue is an EFFECTS channel, not inherently bound: the guard
   REQUIRES every queued response to carry the `_queue` binding
   (turn/turn_seq/head) at the adapter boundary - a raw hand-written
   line is refused and left unconsumed. Scope notes: (a) the
   independently reviewed boundary was mock-only; admitting `queue` is
   new in this increment and has not had the same independent review;
   (b) mock/queue payloads are trusted operator-authored fixtures -
   authorship is a trust decision, NOT authenticated provenance;
   (c) response `verify_command`s run with shell=True in the seat
   runtime, so the guard screens them against a conservative allowlist
   (simple python3/pytest commands, no shell metacharacters, relative
   paths only) - a SHALLOW guard, not a sandbox; (d) no zero-network
   claim is made for response payloads, only for the transport. The CONSTRUCTED adapter is then checked by exact class
   identity against the preselected safe constructor for that spec (the
   imported class object itself, not a forgeable `__name__` string).
   Provider-calling adapters (http/cli/live) are refused at sync and at
   execution. No provider call is possible from this graph.
3. A `GuardedAdapter` wrapper re-validates status, turn, OPERATOR
   CONTROL (mode and instruction_seq) and adapter identity AT the
   adapter call - inside the seat transaction, after the lease claim.
   An operator pause/halt, instruction update or roster swap landing
   between the pre-checks and the call (including a pause issued while
   the seat waited on the seat gate) raises `SeatError` BEFORE this
   turn's commit; the in-memory lease/turn changes are never committed.
   The bus transact itself is pull/commit/push/retry - no isolation,
   no rollback of already-committed state.
   The control file fails CLOSED: anything but an explicit dict with a
   known mode and integer instruction_seq - missing file, bad JSON,
   wrong type, unknown mode, missing/bool seq - means hold, never run.
   The graph reads control from the COMMITTED state (`git show HEAD:`),
   never the worktree: an uncommitted or failed control change is
   invisible; control takes effect exactly at commit order. Operator
   commits stage exactly their own paths (`transact_paths`), precheck a
   clean index BEFORE mutating, and restore the worktree from HEAD on
   failure, so a control commit can neither sweep an in-flight seat's
   changes nor leave a dirty control value behind.

   Control semantics, stated honestly: the guard checks at THREE points
   - before the adapter runs, after it returns, and (routed upstream,
   not yet landed) at the seat's pre-apply boundary inside
   `Seat.act_once`. A pause/update landing before or during an adapter
   call is refused; the residual window between the post-call check and
   the seat's apply/commit is microseconds but real until the upstream
   pre-apply hook exists, and closing it needs a repo-level lock shared
   by seat apply and operator commits (executor-owned launcher change,
   requested). Pause NEVER cancels in-flight work - it refuses
   application of responses that complete after it lands, and blocks
   the next seat action.
4. Refusals (including `SeatError` from the project's own stale/lease/
   verify machinery) are recorded and route to the terminal node, never
   swallowed.
5. Repo and checkpoint paths must be canonical: `realpath` is applied
   and any symlink/alias spelling is refused, so the checkpoint-outside-
  -repo and resume-identity checks cannot be bypassed by a linked
   parent directory.
6. `run_graph` resumes a thread only if the stored repo and checkpoint
   path exactly match the requested ones (fail closed on identity
   mismatch).
5. `init_repo` refuses root/home/cwd, non-directories, and ANY non-empty
   directory; it never deletes data (recreating a demo is a manual
   delete).

## Operator controls (assign / pause / update / resume)

One channel: `.team/CONTROL.json` inside the git bus, mutated only
through guard-exempt `operator:` commits - the same bus every seat and
sync reads, not a competing state path.

- PAUSE: control mode `pause` holds the graph in a paused node (durable
  checkpoint, no seat acts) until RESUME restores mode `run`.
- UPDATE INSTRUCTIONS: rewriting the brief bumps `instruction_seq` and is
  an ordinary non-queue commit - every queued in-flight response bound
  to the old head is then stale by the project's own head-binding rule
  and the seat REFUSES it (recorded, queue preserved for the operator).
  Old instructions can never be applied after an update.
- RESUME / resolution: the operator discards stale lines and re-queues
  through `launcher respond --discard-stale` (the project's CLI), then
  the team completes.
- ASSIGN: new brief + turn + status through the same operator commit
  path; a closed team runs the new assignment.

`controls_demo.py` proves all four on one lane: pause held mid-run, the
in-flight queued response refused as stale after the instruction update,
cycle 1 completed after operator resolution, and a second assignment
(subtract feature) ran end to end - 10/10 checks.

Caveat: these are mechanism demos on mock/queue lanes. The controls are
NOT yet reviewed or claimed safe as a live-intervention boundary for a
real model team.

## Demonstrated (mock, no network, no keys, no spend)

- Full five-seat cycle per lane, verified against the project's own demo
  checks (turn token, handoffs, verify exit codes, guard hook, QC verdict,
  archive) in three parallel lanes - 36/36 checks.
- Graceful stop after N seat actions and resume in a NEW OS process from
  the sqlite checkpoint (step trace records both pids).
- Lanes genuinely overlapping in wall-clock time; gate high-water exactly
  at its cap; deterministic 5-branch no-network overlap test.
- Fence probes: seat refused on wrong turn, after operator halt, on a
  swapped non-mock roster, on thread/repo identity mismatch, on a
  checkpoint path inside the repo, and init refused on unsafe paths.

## Known limits (stated, not fixed)

- Graceful stop is a node-boundary stop, not crash simulation and not
  exactly-once: the git bus and sqlite checkpoint are two stores with no
  atomic commit across them. The bus (turn token, leases, head bindings)
  is what makes replay safe, not LangGraph.
- The seat gate is process-local and optional and caps seat ACTIONS; a
  seat action can make several adapter calls, so it is NOT a provider
  budget or request-concurrency control. No RequestBudget, allowance
  window or completion guard is wired in; the Ryan runner and allowance
  mechanism are untouched.
- Resume evidence is a narrow new-process sqlite demo, not live
  readiness. Team-state durability is the git bus; LangGraph checkpoints
  cover orchestration state only.

## What this is NOT

- Not the named team (Nora, Eva, Ryan, Alex, Bill, Sam) running. Wiring a
  named member means giving a seat a live adapter (a provider route or an
  operator queue). This graph structurally refuses non-mock adapters, and
  no named member currently holds a qualified route or authorized budget.
  Parallel live model execution has not happened and is not claimed.
- Not a 24/7 service, not a resident process guarantee, not an
  architecture migration.
- No provider budgets, halts, rosters or routes are changed.

## How to run (local, no keys)

Self-contained: `launcher/` is vendored here, copied byte-exact from
this repo's `ryan-continuous-offline` branch at the accepted commit
46fa7284a173c4b96a3a08c1ca8ffa22d6693391 (the reviewed offline baseline - not
`main`). Only third-party installs needed (Python >= 3.10, tested on
3.10.12):

```
pip install langgraph==1.2.19 langgraph-checkpoint-sqlite==3.1.3
```

```
python integration/langgraph/langgraph_team.py init /tmp/demo/lane-a /tmp/demo/db-a.sqlite
python integration/langgraph/langgraph_team.py run  /tmp/demo/lane-a /tmp/demo/db-a.sqlite 2 team-demo-a   # graceful stop after 2
python integration/langgraph/langgraph_team.py init /tmp/demo/lane-b /tmp/demo/db-b.sqlite
python integration/langgraph/langgraph_team.py init /tmp/demo/lane-c /tmp/demo/db-c.sqlite
python integration/langgraph/parallel_team.py /tmp/demo   # resumes lane-a, runs all lanes, verifies
python integration/langgraph/controls_demo.py /tmp/lg-controls   # operator controls run
```

Developed and tested against the project head `46fa728`. This branch adds
`integration/langgraph/` only; no existing file is modified.
