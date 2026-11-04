# Blueprint: Coordinator Assistant

- **Status:** vacant (role available under the owner's 2026-11-04
  dynamic-team approval; no instance until a clear workload exists)
- **Purpose:** takes over well-defined coordination support work -
  handoff tracking and status-evidence gathering - so the coordinator
  can focus on assignments and acceptance.
- **Current model / provider:** unassigned (qualification trial
  required first).
- **Owns (scope):** status/evidence collection and handoff logs;
  writes proposals, not decisions.
- **Explicitly NOT in scope:** task assignment, acceptance, gates,
  credentials, merges - all stay with the coordinator/owner.
- **Inputs / outputs:** coordinator-delegated tracking questions;
  produces status summaries with evidence links.
- **Evidence standard:** every status claim carries its source pin;
  unknowns are reported as unknowns.
- **Completed work:** none (vacant).
- **Qualification trial 2026-11-04 (NOT activated):** one bounded
  free-only trial (5 attempts, Requesty cost 0) of
  nvidia/nemotron-3.5-lightning-30b-a3b on log-reconciliation tasks.
  Result: good uncertainty discipline on one small task, but quote
  fidelity flawed (analysis presented as verbatim quotes), one empty
  answer and one truncated table on the realistic workload, reasoning
  overhead 4-11x visible output. Decision (coordinator, 2026-11-04):
  not activated; the recurring reconciliation workload goes to a
  deterministic extractor instead - see
  docs/proposals/deterministic-log-reconciliation.md. First candidate
  nvidia/nemotron-3-super-120b-a12b was listed free but uncallable
  (404). Same-day org usage floor 26 requests, daily reset boundary
  unknown.
- **Open issues:** role stays vacant until a workload exists that is
  model-shaped (judgment, not extraction) and a fresh bounded trial
  passes on it.
- **Handoff notes:** activate only when the tracking workload is real
  and recurring; follows the same registry/blueprint rules so its work
  can be handed over or resumed.
- **Retirement conditions:** workload ends or is absorbed back by the
  coordinator.
- **Reactivation checklist:** fit re-check; qualification trial if
  model/provider/terms changed; no credential inheritance.
