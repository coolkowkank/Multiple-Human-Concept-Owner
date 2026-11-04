# Proposal: first live adopter-AI cycle (bounded, free-only)

Status: PROPOSED 2026-11-04, not run. Awaiting main's bounded GO.

## Exact concept and target
- Concept (the whole .team/brief.md content): "Build a tiny Python
  library providing add(a, b) with one passing pytest-style test, in a
  fresh repository." Deliberately small: the run tests the TEAM
  MECHANISM with a live model, not model coding strength.
- Target: a DISPOSABLE local-only git repo under /tmp (no GitHub
  remote, no pushes, no remote writes of any kind). Everything the
  team produces stays in that repo's .team record and working tree.
- No operator content fixes mid-run: if the model's output is wrong,
  the run records the failure; humans do not repair files for it.
- No Instinct-specific glue: seats run only via the repo's own
  `launcher` CLI with http adapters; the operator sets env (API key
  from the vault into the process env, never into files/logs) and
  starts the supervisor.

## Seat -> model mapping (all on Cerebras free trial, gpt-oss-120b)
coordinator, builder, reviewer, qc, records: each an `http` adapter
with base_url https://api.cerebras.ai, model gpt-oss-120b,
api_key_env CEREBRAS_API_KEY, max_tokens 4096 (OUTPUT cap per response
only - NOT an input cap and NOT a spend cap), reasoning_effort low,
call_budget per below, usage_log .team/usage/<seat>.jsonl.

## Request caps (request count, not dollars)
Per seat: coordinator 6, builder 6, reviewer 4, qc 2, records 2 = 20
provider requests total. Why 20 is expected sufficient: the scripted
rehearsal cycle completes in exactly 6 seat responses (1 coordinator
draft + 1 builder + 1 reviewer + 1 qc + 1 records + 1 coordinator
close). Recorded live runs of the standalone executor showed 1-3
responses per seat task on this model family; the caps allow every
seat one retry/format-correction round plus headroom for one
coordinator re-assignment, roughly 3x the scripted minimum. If caps
prove insufficient, that is itself a recorded finding (ESCALATE),
never a silent top-up.
Persistence: the cap is derived from each seat's usage log at adapter
startup, so supervisor restarts, seat crashes and resumes do not reset
it (tested offline); a seat at cap fails closed and the supervisor
escalates instead of completing.

## Rate coordination
Cerebras free trial: 5 requests/min PER MODEL at the organization
level - all five seats share one model, so the global rate is 5 RPM
across the whole team, not per seat. Mitigation: the adapter already
honors 429 + Retry-After with backoff (each retry consumes the
budget), and the turn token naturally serializes seat work (one seat
acts at a time), so expected request rate is well under 5 RPM.

## Stop conditions (whichever first)
1. DONE: coordinator closes with QC PASS at a named commit (success).
2. ESCALATE: any seat budget exhausted, supervisor stall escalation,
   or restart limit hit (failure artifact preserved as-is).
3. Wall kill: supervisor --max-seconds 1800; stall-timeout 300s.

## Cost verification (no paid fallback)
- Vendor docs (inference-docs.cerebras.ai/support/rate-limits): the
  Free Trial tier is hard rate-limited (5 RPM / 30K TPM / 1M TPD per
  model); pay-as-you-go is a separate Developer tier.
- The proposal uses ONLY the existing free account/key already in the
  vault - no new account, no access changes, no payment method added.
  If the account were on a paid tier, the same 20-request cap still
  bounds requests; expected token volume (<20 responses x ~1-2K
  tokens) is far inside free-tier limits. Residual check at GO time:
  confirm in the Cerebras console that no payment method is attached
  (cannot be debited). Requesty standby routes are NOT used here.

## Final artifact
The disposable repo's .team record: LOG.jsonl, STATE.json, gates,
usage/*.jsonl per seat, batch commit SHAs - plus a summary appended to
docs/proposed-vs-tested.md stating the outcome either way. A PASS is
one cycle, not proof of generality.

## Review (post-run, read-only)
Independent reviewer: Christina's Instinct, scoped static review of
the run RECORD only - turn-token order, one handoff per turn, verify
commands runtime-executed with real exit codes, budget never exceeded,
usage totals vs the 20-request cap, no human content edits. Verdict
VERIFIED / FIX_NEEDED / ESCALATE via the docs/review-loop.md pattern.

## Explicitly not in scope
No paid routes, no remote pushes, no main merge, no access changes, no
history rewrite, no retries beyond the adapter 429 policy, no
Instinct-specific model glue, no operator content repair.
