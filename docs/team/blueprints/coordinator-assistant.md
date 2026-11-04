# Blueprint: Coordinator Assistant

- **Member name:** Sam (owner-named 2026-11-04). Gemma is the
  status-draft MODEL, not the member name. Sam has no separate chat
  account; instructions route through the coordinator.

- **Status:** active (dedicated assignment from the owner, 2026-11-04:
  keep the GitHub Pages project status current - Gantt chart, S-curve,
  team, timeline)
- **Purpose:** owns status-evidence collection and status publication
  for the project Pages site, so the coordinator can focus on
  assignments, priorities and acceptance.
- **Current model / provider:** google/gemma-4-31b-it via the
  Requesty price-0 route, for the narrow fixed-template STATUS-DRAFT
  job only: one bounded attempt, one coordinator-reviewed usable
  sample (2026-11-04, cost 0). This is NOT a general qualification:
  every draft is coordinator-reviewed before use, and publication
  stays with the coordination-run operator flow. The hourly
  changes-only maintenance itself is unchanged by the draft role.
- **Owns (scope):** project status evidence (scores, pins, timeline
  events) and its publication to GitHub Pages within existing grants;
  writes proposals, not decisions.
- **Explicitly NOT in scope:** task assignment, priorities, acceptance,
  gates, credentials, merges - all stay with the coordinator/owner.
- **Inputs / outputs:** coordinator-supplied status facts and pins;
  produces status summaries, status-delta drafts and Pages updates with
  evidence links.
- **Evidence standard:** every status claim carries its source pin;
  unknowns are reported as unknowns.
- **Completed work:** ongoing Pages status maintenance (hourly,
  changes-only) under the coordinator's maintenance process; see the
  timeline/charts commit history.
- **Qualification trial 2026-11-04 (heavy-log workload, NOT the active
  scope):** one bounded free-only trial (5 attempts, Requesty cost 0)
  of nvidia/nemotron-3.5-lightning-30b-a3b on log-reconciliation tasks.
  Result: good uncertainty discipline on one small task, but quote
  fidelity flawed (analysis presented as verbatim quotes), one empty
  answer and one truncated table on the realistic workload, reasoning
  overhead 4-11x visible output. Decision (coordinator, 2026-11-04):
  not qualified for heavy log reconciliation; that workload goes to a
  deterministic extractor instead - see
  docs/proposals/deterministic-log-reconciliation.md. This trial does
  NOT block the active status-publication scope: the failed workload
  was whole-log analysis, not the short structured-status drafting this
  role actually does. First candidate nvidia/nemotron-3-super-120b-a12b
  was listed free but uncallable (404). Same-day org usage floor 26
  requests, daily reset boundary unknown.

## Handoff contract: status maintenance (project-level, portable)

- **Cadence:** hourly, changes-only; day-end archive preserved.
- **Input (small, structured; no chat transcripts):** (a) git log since
  the last published source pin for each watched ref (main,
  team-launcher, Research_lab, live/*, records); (b) the current team
  registry SHA; (c) coordinator-supplied project status facts.
- **Output (fixed template):** proposed status/evidence deltas, each
  citing its source SHA. Baselines, acceptance criteria, partial scores
  and autonomy credit stay unchanged unless the coordinator explicitly
  supplies the change.
- **Regeneration rules:** the team visual regenerates only on a
  team/registry change; timeline and Legacy changes come only from
  source refs; otherwise only evidence text and the as-of marker move.
- **Publication:** the coordinator reviews each delta; publication runs
  through the existing authorized operator flow. The status role never
  touches credentials, tokens, provider configuration, or merges.
- **Role separation:** STATUS-DRAFT (small fixed-template drafting; a
  project model may hold it after its own bounded trial) is separate
  from the publish operator (the existing authorized maintenance flow).

- **Open issues:** external-model activation for short status-delta
  drafting needs its own bounded trial on that small job (structured
  input under ~2KB, fixed-template output, per-task coordinator
  review), with a fresh explicit attempt cap - the earlier 6-attempt
  grant is closed and is not reused.
- **Handoff notes:** hourly changes-only cadence and day-end archive
  rules are preserved exactly; activation does not add a second
  maintainer or watcher.
- **Retirement conditions:** workload ends or is absorbed back by the
  coordinator.
- **Reactivation checklist:** fit re-check; qualification trial if
  model/provider/terms changed; no credential inheritance.
