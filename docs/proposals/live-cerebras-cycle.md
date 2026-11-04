# Proposal: first live adopter-AI cycle (bounded, free-only)

Status: PROPOSED 2026-11-04, not run. Requires owner review before execution.

## Purpose
First evidence toward the acceptance target (D18): one real batch cycle
driven by a model API through the real seat path - init in a fresh target
repo, brief in, coordinator assigns, builder implements with a real
verify command, reviewer re-runs it, QC verdict, records archive, DONE -
with no per-round human steering.

## Route and limits
- Provider: Cerebras free trial, model gpt-oss-120b (qualified
  2026-11-04: key valid, tool calls work; tier limits 5 RPM, 30K
  uncached TPM, 1M TPD).
- Seats via `http` adapters; EVERY seat gets `call_budget` +
  `usage_log` in the roster. Proposed global cap: 20 provider requests
  total (coordinator 6, builder 6, reviewer 4, qc 2, records 2),
  enforced per seat; any seat hitting its cap fails closed and the
  supervisor escalates. This is a REQUEST cap, not a token/money cap;
  token use is read from the usage record afterward.
- `max_tokens` 4096 and `reasoning_effort: low` per seat (token
  discipline from the executor measurements, 2026-11-04).
- Supervisor `--max-seconds 1800` wall-clock stop; stall-timeout 300s.

## Stop conditions (whichever first)
1. DONE with QC PASS at a named commit (success artifact).
2. Any seat budget exhausted or supervisor escalation (failure artifact:
   the bus record and usage logs show exactly where).
3. Wall-clock stop.

## Final artifact
The target repo's `.team/` record: LOG.jsonl, STATE.json, gate history,
usage/*.jsonl per seat, plus the batch commit SHAs. Published as
evidence in docs/proposed-vs-tested.md with the honest outcome either
way; a PASS is one cycle, not proof of generality.

## Review
Independent reviewer (Christina's Instinct, per the roster chart):
scoped static review of the run RECORD after the stop - turn-token
order, one handoff per turn, verify exit codes runtime-executed, budget
never exceeded, usage totals vs the 20-request cap. Verdict VERIFIED /
FIX_NEEDED / ESCALATE on the peer branch pattern from docs/review-loop.md.

## Explicitly not in scope
No paid routes, no retries beyond the adapter 429 policy, no main merge,
no access changes, no history rewrite. Legacy unbounded rosters are not
used. Secrets stay in env, never in git or logs.
