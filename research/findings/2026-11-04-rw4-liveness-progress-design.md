# RW4 finding: separate liveness from progress, and judge stall only when progress is expected

Author: Researcher role. Date: 2026-11-04. Source IDs: research/REFERENCES.md (R9, S7, S8 added below). Evidence class: design proposal [PP] + vendor docs; [H] for our application. Not tested by us.

## Problem
Observed: a seat was flagged stalled prematurely (RW4). Gap: no verified design for when "stalled" is allowed.

## Sources
- [R9] Agent Status Protocol (ASP), [PP] proposal, not a standard (document says so): https://arxiv.org/html/2610.21538 (read 2026-11-04: abstract, status note, sec 1.1, 5.1-5.3 state tables, 6.2-6.3, 7.2.1 first rules; sec 7.1 and later not read).
- [S7] Akka phi accrual failure detector docs (level 1): https://doc.akka.io/libraries/akka-core/current/typed/failure-detector.html (read 2026-11-04). It scores silence against the history of heartbeat arrivals, with an acceptable-pause margin, instead of one fixed timeout.
- [S8] Kubernetes Leases, docs listed https://kubernetes.io/docs/concepts/architecture/leases/ (not read; listed as candidate only).

## What the sources say [R9]
- Liveness (process alive) and progress (work advancing) are different. A hung main loop can keep a separate heartbeat thread "healthy" (sec 7.2.1).
- Heartbeats carry progressSeq, a counter incremented when a step completes (model call, tool call, message sent). Heartbeat comes from the main work loop (sec 6.3).
- unreachable = missed heartbeat, server-assigned. stalled = alive but progressSeq unchanged for stallAfterSec, and only if a task is in working/retrying, i.e. progress is expected (sec 5.2, 7.2.1). The server assigns both, so an agent is not trusted to report its own stall.
- Waiting states exist (awaiting-approval, delegated, queued, rate-limited, quota-exhausted, sec 5.2-5.3), which are not stalls.

## Proposal for our launcher [H]
1. Define a seat progress counter: increments on each completed step (turn written, test run, commit, message sent), recorded in repo/ledger state.
2. Flag stalled only if the seat's task is in a working state AND the counter is unchanged for a per-task window AND the seat is not in an explicit wait state (awaiting reviewer, rate-limited by the ledger pacing, quota). Never from elapsed time since turn start alone.
3. Keep "unreachable" (no signal) and "stalled" (signal, no progress) as separate states with separate actions.
4. Per-task window, with margin, instead of one global timeout. Optionally derive it from past step durations (idea from phi accrual) only after we have data.
5. The supervisor assigns stalled/unreachable, not the seat.

## Experiment E4 (proposed, Builder to execute)
Replay the premature-stall case and a genuinely idle seat: expected not-stalled for the first, stalled for the second, in the same timezone setup. Metrics: false positives/negatives over a fixed set of recorded turn histories; N small, label anecdotal. Success: zero false stall on active/waiting cases, correct flag on the idle case.

## Limits
ASP is an unreviewed proposal with its own illustrative implementations; I read no implementation. Phi accrual docs are a vendor description. Our seats are git-based turns, not services: heartbeat in this sense may need to be a ledger/commit signal. Nothing here shows the current UTC stall fix is wrong; it is a design reference.
