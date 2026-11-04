# Blueprint: Recovery Executor

- **Status:** active (owner assignment 2026-11-04, Slack
  1793807666.323859 and 1793807753.116989: WP4 and WP9 transfer off
  the Coordinator, who executes zero WP jobs while any job is late).
- **Instance:** recovery-1, alias unassigned.
- **Purpose:** finish the two late work packages the Coordinator was
  carrying, with measured evidence, not status prose.
- **Current model / provider:** NONE. Operator execution only. No
  model is assigned or qualified for this role; any model step needs
  its own verified-free route, a bounded cap approved per task, and
  per-draft review. This role label authorizes no provider calls.

## Scope (transferred facts)

- **WP4 'Requesty tiny-library run'** (partial, weight 7): prior run
  live/requesty-tinylib-experiment @
  e51fae66afce4d1ae2bd8ef2e2ac011c692b03ca reached DONE but needed
  manual recovery (null-handoff deadlock) and skipped the Reviewer
  seat. Acceptance gap: a run on the fixed runtime (accepted base
  26ff4bc; the gate-latch follow-up is NOT yet accepted) that completes
  without manual recovery and engages Reviewer. Recheck the frozen
  criterion before planning.
- **WP9 'Lower-token handoffs'** (in_progress, weight 5): delta-only
  handoff rule adopted; one run logged 11,607 tokens, composition only.
  Acceptance gap: MEASURED savings - needs prompt-source
  instrumentation and a comparison run. Design inputs: RW1 handoff
  validator spec + RW3 token baseline (Research_lab 328cec7, pending
  independent review).

## Working rules

1. Ground the frozen criteria in the repo before acting; do not work
   from summaries.
2. Existing authorized routes and caps only; no new provider calls,
   credentials, merges or security changes without explicit owner
   approval through the review chain.
3. Savings and completion claims must be measured and independently
   reviewed before any credit; composition is not a saving.
4. Proposals route Sam -> Coordinator -> owner (see team-resources
   blueprint); money, security and merges stay owner-only.
