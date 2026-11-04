# Ryan continuous pipeline (offline build, not running)

Status: runner built and mock-tested only. No live call has been made. Live
use waits for independent review, a fresh price-0 check on exact model ids,
and reconciliation of the shared free-request pool. Nothing here shows a
model is assigned or running.

Order: Researcher output -> Verifier checks that references support the
claims -> Ryan reviews verified output for usefulness. Failed or incomplete
checks go back for one correction round before Ryan sees anything.

- `tools/ryan_cycle.py`: one request per step; reserve-before-call ledger.
- Caps: 4 cycles/day, 6 requests/cycle, 24/day combined; 10 s spacing.
- Any 429, unknown outcome, auth error or cost above 0 pauses the pipeline.
  Resuming needs a human-sourced note, never a timer.
- Ryan picks models for the other roles (`assignments.json`). The runner
  accepts a pick only if the exact id is price 0 in a fresh listing, the
  verifier differs in model and family from the researcher, and the route
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
- Ryan's allocation request counts 1 of the 24 requests and 1 of the 4
  daily question slots, leaving 3 research questions that day.
- Outputs end at `ready-for-chain`.

If the queue entry vanishes during a request, the runner halts; recovery is explicit (human clear after reading runs/).
