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
- Outputs end at `ready-for-chain`.
