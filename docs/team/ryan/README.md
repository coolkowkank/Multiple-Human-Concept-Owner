# Ryan continuous pipeline (offline build, not running)

Status: PAUSED after the first live attempt (see incident-1.md): one
allocation request ended with an unknown outcome. No assignment exists and
nothing is running. Earlier text below describes the design.

Update 2026-11-04 20:09 EET: the operator authorised ONE bounded diagnostic
Researcher attempt (cause of the earlier unknown outcome still unknown, no
provider clearance claimed). It returned a well-formed draft: HTTP ok, cost 0,
prompt 1207 / completion 1423 (reasoning 798) / total 2630 tokens, one request.
The output is UNVERIFIED model output (runs/research-model-vs-harness/). The
model is not qualified. The pipeline is PAUSED again by policy: no verifier,
review, retry or schedule runs without a report and a new operator decision.

Update 2026-11-04 19:54 EET: the operator assigned provisional models
(researcher nvidia/nemotron-3-ultra-550b-a55b, verifier and Ryan review
novita/ling-3.1-flash) with `assign_manual()`, no model call. See
`assignments.json`. They are NOT qualified or benchmarked, the pipeline is
still PAUSED and nothing is running. Verifier and Ryan review share a model
in separate executions, with no independence claim between them.

Original status: runner built and mock-tested only. Live
use waits for independent review, a fresh price-0 check on exact model ids,
and reconciliation of the shared free-request pool. Nothing here shows a
model is assigned or running.

Order: Researcher output -> Verifier checks that references support the
claims -> Ryan reviews verified output for usefulness. Failed or incomplete
checks go back for one correction round before Ryan sees anything.

- `tools/ryan_cycle.py`: one request per step; reserve-before-call ledger.
- Caps: 4 cycles/day, 6 requests/cycle, 24/day combined; 10 s spacing.
  A question may use at most 5 requests (clean path 3), so a question stays within the
  6-request cycle; budget exhausted means needs-human, with no
  promised correction for every seat.
- Any 429, unknown outcome, auth error or cost above 0 pauses the pipeline.
  Resuming needs a human-sourced note, never a timer.
- Ryan does NOT pick or change models (revoked 2026-11-04 19:44 EET).
  The operator writes `assignments.json` with `assign_manual()` (no model
  request, decided_by main, source_ref required); `allocate()` is a
  disabled stub and `step()` refuses a file not made by the operator. A
  manual assignment is accepted only if the exact id is price 0 in a fresh listing, the
  verifier differs in exact model and in the listing's own model_lab field from the researcher (an id prefix is a reseller name, never a family; unknown lab fails closed), and the route
  record is not blocked.
- Job-description scan (`jobdesc_scan`) is change-driven and uses no model
  call; it measures bytes only (chars/4 is a heuristic, not tokens).
- Policy drafts by Ryan follow the existing approval chain. No automatic
  adoption; no override of owner, spending or security holds.
- Route record gate: a role model (and Ryan's bootstrap model) must be
  recorded under its exact id with status working or untested (untested =
  human-recorded, first cycle tests it); unrecorded ids are unknown, not
  working. Blocked statuses and blocked providers refuse.
- Price gate: input and output price must be present, numeric and 0.
  Missing pricing is unknown, not free.
- Verifier SUPPORTED verdicts must give a source id from the finding and a
  quote that is a verbatim substring (whitespace/case-normalized, 8+ chars) of that passage (mechanical check;
  whether it supports the claim stays model judgment).
- Gate + reserve + queue/assignment writes run under a flock transaction
  lock (never held across a model request; the bounded listing GET runs inside it so the price check and reserve stay atomic). Rejected verifier/Ryan replies are
  retried once with the rejection reason.
- Allocation by a model request no longer exists. Incident 1 (history)
  used 1 of the 24 requests and 1 of the 4 daily question slots.
- Outputs end at `ready-for-chain`.

If the queue entry vanishes during a request, the runner halts; recovery is explicit (human clear after reading runs/).
