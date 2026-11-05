# LangGraph team orchestration (integration in progress)

**Status: work in progress. Mock (scripted) adapters only - no live model
calls, no live named team, no paid hosting. Not merged readiness; this
branch exists so the work is visible and reviewable.**

## What this is

An orchestration layer that drives the project's existing team machinery
(`launcher.runtime.Seat` over the git bus) through a LangGraph state graph
(LangGraph 1.2.19):

- LangGraph owns scheduling, conditional routing, parallel lane execution
  and durable checkpoints (`SqliteSaver`, stored OUTSIDE the team repo so
  the bus never commits it).
- The project's own code keeps owning turn mechanics: lease, prompt build,
  adapter call, roster/verify validation, guard-hook commit, handoff and
  archive. The seat set is read from the project's roster
  (`launcher.cli.default_roster`), not hardcoded here.

Files:

- `langgraph_team.py` - single-lane orchestrator: sync gate, per-seat
  nodes, blocked terminal for any non-mock adapter or non-running state,
  interruption/resume from durable checkpoints.
- `parallel_team.py` - parent graph running several independent lanes
  concurrently, with one shared seat gate capping simultaneous seat
  actions across all lanes, plus a deterministic no-network overlap test.

## What has been demonstrated (mock, no network, no keys, no spend)

- Full five-seat cycle per lane, verified against the project's own demo
  checks (turn token, handoffs, verify exit codes, guard hook, QC verdict,
  archive).
- Interruption after N seat actions and resume in a NEW OS process from
  the sqlite checkpoint (step trace records both pids).
- Three lanes genuinely overlapping in wall-clock time; shared seat gate
  high-water exactly at its cap; controlled 5-branch overlap test.
- Dependency edges preserved: within a lane the single turn token still
  serializes coordinator -> builder -> reviewer -> qc -> records. Only
  independent lanes overlap.

## What this is NOT

- Not the named team (Nora, Eva, Ryan, Alex, Bill, Sam) running. Wiring a
  named member means giving a seat a live adapter (a provider route or an
  operator queue). This graph structurally refuses non-mock adapters
  (they route to a blocked terminal), and no named member currently holds
  a qualified route or authorized budget. Parallel live model execution
  has not happened and is not claimed.
- Not a 24/7 service, not a resident process guarantee, not an
  architecture migration. The Ryan runner (`tools/ryan_cycle.py`), the
  RequestBudget composition and the allowance mechanism are untouched and
  not wired in here.
- No provider budgets, halts, rosters or routes are changed. The seat
  gate is the single point where a shared budget control would attach if
  live seats are ever authorized - one shared control, never per-lane
  multiplied allowances.

## How to run (local, no keys)

Requires the project checkout on `PYTHONPATH` and `pip install langgraph
langgraph-checkpoint-sqlite` (Python >= 3.10):

```
python integration/langgraph/langgraph_team.py init /tmp/demo/lane-a /tmp/demo/db-a.sqlite
python integration/langgraph/langgraph_team.py run  /tmp/demo/lane-a /tmp/demo/db-a.sqlite 2 team-demo-a   # interrupt after 2
python integration/langgraph/langgraph_team.py init /tmp/demo/lane-b /tmp/demo/db-b.sqlite
python integration/langgraph/langgraph_team.py init /tmp/demo/lane-c /tmp/demo/db-c.sqlite
python integration/langgraph/parallel_team.py /tmp/demo   # resumes lane-a, runs all lanes, verifies
```

Developed and tested against the project head `46fa728`. This branch adds
`integration/langgraph/` only; no existing file is modified.
