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
  fences (below), durable resume, graceful stop.
- `parallel_team.py` - parent graph running several independent lanes
  concurrently, with one shared seat gate capping simultaneous seat
  actions across all lanes, plus a deterministic no-network overlap test.

## Execution-time safety fences

Sync-time checks alone would be racy, so `seat_node` re-verifies
IMMEDIATELY before acting:

1. Bus status must be `running` and the written turn must name this seat
   - a resumed pending seat after an operator halt is refused.
2. The roster adapter spec must be `mock`, AND the constructed adapter
   instance must be a `MockAdapter` - a roster swapped between sync and
   execution cannot reach a non-mock adapter. No provider call is
   possible from this graph.
3. Refusals (including `SeatError` from the project's own stale/lease/
   verify machinery) are recorded and route to the terminal node, never
   swallowed.
4. `run_graph` resumes a thread only if the stored repo and checkpoint
   path exactly match the requested ones (fail closed on identity
   mismatch).
5. `init_repo` refuses root/home/cwd, non-directories, and ANY non-empty
   directory; it never deletes data (recreating a demo is a manual
   delete).

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

Requires the project checkout on `PYTHONPATH` and `pip install langgraph
langgraph-checkpoint-sqlite` (Python >= 3.10):

```
python integration/langgraph/langgraph_team.py init /tmp/demo/lane-a /tmp/demo/db-a.sqlite
python integration/langgraph/langgraph_team.py run  /tmp/demo/lane-a /tmp/demo/db-a.sqlite 2 team-demo-a   # graceful stop after 2
python integration/langgraph/langgraph_team.py init /tmp/demo/lane-b /tmp/demo/db-b.sqlite
python integration/langgraph/langgraph_team.py init /tmp/demo/lane-c /tmp/demo/db-c.sqlite
python integration/langgraph/parallel_team.py /tmp/demo   # resumes lane-a, runs all lanes, verifies
```

Developed and tested against the project head `46fa728`. This branch adds
`integration/langgraph/` only; no existing file is modified.
