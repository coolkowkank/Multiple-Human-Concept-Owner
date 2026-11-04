# Groq <-> Independent Reviewer Loop (v1 proposal)

Bounded review/fix loop on live/groq-dev-3 with no per-round mediation.
Coordinator checks only the finished result or an escalation.

## Roles
- Model (Groq gpt-oss-120b): fixes review findings via its OWN tool calls
  (write_file/git_commit/git_push through the capture-cleared executor,
  tools/self-commit-executor.py). Author: Groq (gpt-oss-120b model).
- Independent reviewer: reads the pinned commit, writes findings + verdict.
  Never edits the model's files; never takes coordinator task assignments.
- Coordinator (instinct-telkomsel): transport + records only. Reports
  VERIFIED result or ESCALATE to the owner channel. Never edits feedback.

## Transport (public files, .team/review/ on live/groq-dev-3)
- LOOP.json: {"state": ..., "cycle": 1-3, "pinned_sha": ..., "notes": ...}
- FEEDBACK.md: reviewer-written findings for the model (input to next fix).
- States: REVIEW_REQUESTED -> FEEDBACK_READY -> FIX_COMMITTED -> VERIFIED
  Any state -> ESCALATE (with reason) at any time.

## Cycle
1. Model's commit lands; coordinator sets REVIEW_REQUESTED + pinned_sha.
2. Reviewer inspects the pinned SHA, pushes FEEDBACK.md + state=FEEDBACK_READY.
3. Coordinator runs ONE bounded attempt: task = FEEDBACK.md content;
   model self-commits/pushes the fix; state=FIX_COMMITTED.
4. Reviewer re-reviews: VERIFIED (loop ends) or new FEEDBACK (cycle+1).

## Bounds
- Max 3 cycles, then ESCALATE. Each attempt: <=6 API rounds, free plan only.
- No main merge, no access changes, no paid routes, no history rewrite.
- Per-event transcripts: live/groq-dev-3-records (operator record-keeping).
- Fail-closed: any capture failure halts the run before the next API call.
