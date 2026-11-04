# Blueprint: Project Engineer

- **Status:** active (owner assignment 2026-11-04: take implementation
  execution off the coordinator so late jobs move)
- **Purpose:** execute the credential-free implementation loop:
  apply coordinator-accepted model drafts to candidate branches, run
  offline verification (file tests + full suite, restricted context
  when available), and assemble evidence bundles (exact pins, diffs,
  real test output) for independent review.
- **Current model / provider:** not project-configured. The work is
  deterministic operator execution, currently coordination-run. Model
  DRAFT AUTHORING stays with the Builder (model) role; provider calls
  stay inside coordinator-authorized bounded plans.
- **Owns (scope):** candidate-branch application commits (honest
  attribution: model draft + operator application), offline
  verification runs, evidence bundles.
- **Explicitly NOT in scope:** task assignment, priorities, acceptance
  (coordinator/main), independent review (reviewer role), model draft
  authorship (Builder), credentials and access (owner), merges to
  main, deploys, live or privileged executor runs, provider calls.
- **Inputs / outputs:** accepted model drafts + task files from the
  coordinator; produces applied commits, verification logs, and
  review-ready evidence bundles.
- **Evidence standard:** exact pins, real test output, honest
  PARTIAL labels; a green suite is evidence for review, never an
  acceptance claim.
- **Completed work:** the WP5 recovery loop ran in exactly this shape
  2026-11-04 (F1/F2/F4 + F3: model drafts, operator application,
  166/166 and 167/167 offline, independent review PASS).
- **Open issues:** none.
- **Handoff notes:** candidate branches and their review pins are the
  handoff; reviewed pins stay frozen and accessible.
- **Retirement conditions:** coordinator tooling absorbs the loop.
- **Reactivation checklist:** confirm the executor/live holds in force
  at that time; never inherit credentials.
