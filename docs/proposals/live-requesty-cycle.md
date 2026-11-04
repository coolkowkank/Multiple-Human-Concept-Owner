# Proposal: first live adopter-AI cycle via Requesty zero-price models

Status: PROPOSED 2026-11-04, not run. Awaiting bounded GO.

## Why this route
- Zero-price by listing AND by observed account behavior: the 13 models
  with input_price = output_price = 0 in the account's own /v1/models
  listing; the 2026-11-04 qualification probes on THIS account returned
  "cost": 0 for google/gemma-4-31b-it (125 tokens) and
  novita/ling-3.1-flash (299 tokens).
- Free tier (requesty.ai/pricing): 200 requests/day on free models, no
  credit card required. A 20-request run uses 10% of the daily free
  allowance and $0 at zero-price listing.
- Route pinning: seats name the exact model id; no routing policy or
  fallback is configured, so a listed model is the whole route. If the
  model errors, the adapter's 429/error handling applies and the budget
  counts it - no silent reroute to a paid model (fallback policies are
  opt-in router features this run does not enable).
- Billing model grounding (docs.requesty.ai/features/billing): Requesty
  bills from a PREPAID USD balance only - every request deducts its
  listed cost, and a request is REJECTED with HTTP 402 once the balance
  runs out. There is no postpaid invoicing of usage (pay-by-invoice is
  a top-up method, still prepaid), so an empty balance cannot accrue
  debt: paid requests fail instead. Auto top-up is opt-in and requires
  a saved payment method plus explicit configuration; this run changes
  no billing settings.
- Account reads attempted 2026-11-04 (read-only, authorized): the
  org-balance management API (api-v2.requesty.ai/v1/manage/org) refused
  this inference key - "API key does not have manage permissions" - and
  no console credentials are stored, so the current balance/payment
  state is unread by this run. The hard bound stands without it: 20
  requests x $0.00 listed price on pinned zero-price models = $0.00
  listed cost, and any non-zero-priced request would need balance the
  router would 402 if absent.

## Exact concept and target
Same as the held Cerebras proposal: brief = "Build a tiny Python library
providing add(a, b) with one passing pytest-style test, in a fresh
repository." Target = DISPOSABLE local-only git repo under /tmp (no
remote, no pushes, no remote writes). No operator content repair mid-run.
No Instinct-specific glue: seats run only via the repo's own launcher
CLI with http adapters; the API key enters the process env from the
operator's secure store, never files/logs.

## Seat -> model mapping (Requesty router, https://router.requesty.ai/v1)
All seats: google/gemma-4-31b-it (zero-price, tool calls verified on
this account, 262K context). Alternate if a seat errors twice:
novita/ling-3.1-flash (also zero-price, cost 0 verified) - a model swap
is a roster edit recorded in the run notes, not a scope change.
Each seat: max_tokens 4096 (OUTPUT cap per response only - NOT an input
cap, NOT a spend cap), reasoning_effort not set (model default),
call_budget per below, usage_log .team/usage/<seat>.jsonl.

## Request caps (request count, not dollars; dollars are $0 by listing)
Per seat: coordinator 6, builder 6, reviewer 4, qc 2, records 2 = 20
requests total. Justification: the scripted rehearsal cycle completes in
exactly 6 seat responses; recorded standalone runs of this model family
took 1-3 responses per seat task; caps allow one format-correction round
per seat plus one coordinator re-assignment (~3x the scripted minimum).
Insufficiency is a recorded ESCALATE, never a silent top-up. The cap is
derived from each seat's usage log at adapter startup, so supervisor
restarts, crashes and resumes do not reset it (tested offline); a seat
at cap fails closed and the supervisor escalates.
Prompt-size note: inputs are the fixed role contract + brief + bus
context (measured 60-260 tokens in probes; cycle prompts estimated <2K
tokens each - an estimate, labeled as such; actual sizes land in the
usage record).

## Rate coordination
Free-tier cap is account-wide: 200 requests/day across all free models.
The turn token serializes seat work (one seat acts at a time), so the
request rate is far under any per-minute limit; the adapter honors 429 +
Retry-After with backoff, retries consuming budget.

## Stop conditions (whichever first)
1. DONE: coordinator closes with QC PASS at a named commit (success).
2. ESCALATE: any seat budget exhausted, supervisor stall escalation,
   restart limit, or repeated model-format failure (failure artifact
   preserved as-is).
3. Wall kill: supervisor --max-seconds 1800; stall-timeout 300s.

## Final artifact
The disposable repo's .team record: LOG.jsonl, STATE.json, gates,
usage/*.jsonl per seat (including per-request "cost" where the router
returns it), batch commit SHAs - plus an honest outcome entry in
docs/proposed-vs-tested.md either way. A PASS is one cycle, not proof of
generality.

## Review (post-run, read-only)
Christina's Instinct: scoped static review of the run RECORD only -
turn-token order, one handoff per turn, verify commands runtime-executed
with real exit codes, budget never exceeded, usage totals vs the
20-request cap, per-request cost fields all 0, no human content edits.
Verdict VERIFIED / FIX_NEEDED / ESCALATE via docs/review-loop.md.

## Explicitly not in scope
No paid routes or paid models, no router fallback policies, no remote
pushes, no main merge, no access changes, no new accounts, no history
rewrite, no Instinct-specific model glue, no operator content repair.
Cerebras stays paused (separate held proposal).
