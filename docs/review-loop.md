# Groq <-> Independent Reviewer Loop (v3, peer-agreed route)

Bounded review/fix loop with no per-round mediation. Coordinator checks
only the finished result or an escalation.

## Roles
- Model (Groq gpt-oss-120b): fixes review findings via its OWN tool calls
  (write_file/git_commit/git_push via tools/self-commit-executor.py) on
  live/groq-dev-3. Author: Groq (gpt-oss-120b model).
- Independent reviewer: publishes findings + scoped verdicts on the
  peer-owned branch review/groq-dev-3. Never edits the model's files;
  never takes coordinator task assignments.
- Coordinator (instinct-telkomsel): transport + records + provider
  execution. Reports VERIFIED result or ESCALATE. Never edits feedback.

## Transport (public, immutable)
- review/groq-dev-3 (PEER branch): .team/review/FEEDBACK-c1.md ..c3.md -
  one file per cycle, IMMUTABLE after publication. Each names the reviewed
  commit SHA, findings, and a scoped verdict: VERIFIED | FIX_NEEDED | ESCALATE.
- live/groq-dev-3 (model branch): LOOP.json (coordinator-owned):
  {"state": ..., "cycle": N, "pinned_sha": ..., "api_used": N,
   "feedback_sha": ...}. States: REVIEW_REQUESTED -> FEEDBACK_READY ->
   FIX_COMMITTED -> VERIFIED; ESCALATE anytime.
- live/groq-dev-3-records: operator per-event transcripts ONLY.

## Cycle (max 3)
1. Model commit lands; coordinator pins its SHA in LOOP.json
   (state=REVIEW_REQUESTED).
2. Reviewer publishes FEEDBACK-cN.md on review/groq-dev-3; coordinator
   sets feedback_sha + state=FEEDBACK_READY.
3. Coordinator runs ONE attempt: the model receives the feedback file
   VERBATIM with its immutable SHA (never an edited verdict) and fixes
   via its own tool calls; state=FIX_COMMITTED.
4. Reviewer re-reviews the new pinned SHA: VERIFIED (loop ends) or
   FIX_NEEDED (next cycle) or ESCALATE.
5. Terminal condition: when the budget or cycle cap is reached, the LAST
   fix still receives independent review WITHOUT any extra provider call
   (no fourth cycle). The reviewer publishes an immutable terminal
   .team/review/RESULT.md on review/groq-dev-3 (final scoped verdict or
   ESCALATE reason). An unresolved FIX_NEEDED at the cap is ESCALATE,
   never silently closed.

## Bounds
- GLOBAL BUDGET: 6 provider/API rounds TOTAL across the ENTIRE loop
  (peer-agreed). At most 3 review cycles within that budget.
- Every attempted provider request counts, including failed/error/blocked
  calls and probes. The executor never retries automatically.
- Enforcement: harness refuses requests beyond the remaining budget
  (budget_stop recorded, fail-closed); coordinator passes only the
  remaining budget into each attempt. Counter: LOOP.json "api_used",
  reconciled against per-event transcripts on the records branch.
- Free plan only. No main merge, no access changes, no paid routes, no
  history rewrite.
- Fail-closed: any capture failure halts the run before the next API call.
- Provenance labels per commit: model-authored + harness-executed vs
  operator record-keeping are always distinguished; an author label alone
  is not proof of model execution (the transcript is the evidence).
