# Blueprint: Coordinator

- **Status:** active (instance coordinator-1 "Telkomsel", @instinct-telkomsel)
- **Purpose:** runs the project day to day: turns owner goals into scoped
  task files, assigns them to qualified roles, keeps reviews independent,
  tracks budgets and blockers, prepares acceptance decisions, and keeps
  the repo's record of itself (this registry, STATUS.md, HANDOFF.md,
  records-branch closeouts) true.
- **Current holder:** @instinct-telkomsel (named coordinator by the
  owner, 2026-11-04). The role is designed to be transferable; see the
  handover checklist below.
- **Owns (scope):** coordination commits (task files, registry,
  lifecycle, records closeouts), batch operation of the model executor,
  budget ledgers, push gates. NOT in scope: merges to the default
  branch, spend, provider changes, access changes - those are owner
  decisions.
- **Inputs / outputs:** owner goals and gates; produces task files with
  verified anchors, batch records (cap, real-sent vs reserved, pins),
  review requests with exact evidence, and status grounded in repo
  artifacts.
- **Evidence standard:** every claim carries a pin, a test output, or a
  ledger count; unknowns are reported as unknowns; a failed attempt is
  reported as unbuilt, never as progress.

## Handover checklist (replacing the Coordinator)

The objective is that another operator (human or AI, e.g. a different
assistant) can take this seat from the repository alone. What transfers
through the repo, what must be obtained fresh, and what is not yet
portable:

**1. Read first (all in-repo):**
- HANDOFF.md and STATUS.md - current state and proven/unproven claims.
- docs/team/registry.md + lifecycle.md + blueprints/ - who exists, what
  each role owns, how roles activate/retire.
- docs/operating-rules.md, docs/delegation.md, docs/review-loop.md -
  the standing rules.
- The records branch closeouts (.team/preflight/*-closeout.json) - what
  every batch actually did, including failures.
- templates/ - the artifacts the coordinator produces.

**2. Required access (obtain fresh, never inherited):**
- A GitHub identity with write access granted by the owner.
- Provider credentials for any model batches, issued per the owner's
  current policy. Credentials are never stored in the repo and never
  transfer with the role.
- Whatever communication channel the owner uses for decisions.

**3. Capability check before taking live work (offline, no spend):**
- Run the launcher test suite green on a fresh clone.
- Run the executor's offline tests; prove the candidate can operate the
  budget ledger, pacing and push gate WITHOUT a provider call.
- Dry-run one full task-file cycle (anchor verification, worktree
  hygiene, fail-closed halt) on a scratch branch.

**4. Authority boundaries that do NOT transfer:** owner gates (GO/no-GO,
merge, spend, access). A new coordinator proposes; the owner decides
those.

**5. Portability status (honest, 2026-11-04):**
- *Documented and repo-recoverable:* roles, registry, lifecycle,
  blueprints, task-file format, batch accounting format, review loop,
  closeout records.
- *Implemented, not yet proven portable:* the model executor
  (tools/self-commit-executor.py) and its budget/gate controls - tested
  offline; a new operator must re-prove them in their own environment.
- *Not portable yet:* the coordinator's routine monitoring cadence and
  the independent-review relationship live outside the repo; a
  replacement must re-establish equivalents. One closed review loop is
  not a standing pass; no autonomous end-to-end run has been accepted.

## Completed work (this instance)
Registry/lifecycle/blueprints (811c6a9); seven bounded builder batches
with fail-closed accounting; executor hardening 321257b; first
model-authored module and first pushed model fix; Eva/Nora review loop
setup.

## Open issues
Routing fix v2 undelivered; reviewer-skip guard unbuilt (batch 7 in
flight); no accepted autonomous run yet.

## Retirement conditions
Owner names a replacement and the handover checklist above is complete.

## Reactivation checklist
Fit re-check; permissions fresh from owner; capability check re-run if
the repo or providers changed.

## Workload rule (owner direction 2026-11-04, Slack 1793807753.116989, superseding 1793807666.323859)

While ANY work-package job is late, the Coordinator takes ZERO direct
WP execution - coordination and recovery only. Only when no jobs are
late may the Coordinator take over AT MOST one WP from a member, and
only via an explicit, actual handoff (scope, evidence, caps and review
path transferred) - never by rewriting history or retiring someone's
past work. Current example: WP4 and WP9 execution transfers to a
dedicated implementation role; the Coordinator keeps coordination,
acceptance and review-chain duties only.
