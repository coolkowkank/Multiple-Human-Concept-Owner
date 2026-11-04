# Proposal: durable-ledger integration into the executor

Status: DESIGN ONLY, no code GO. Date: 2026-11-04. Author: coordinator.
Module under integration: tools/durable_ledger.py @ aacfe446dd78f60c082849b68a4abd608ae2e898
(branch live/executor-ledger-v4), independently reviewed 2026-11-04 and
accepted as STANDALONE OFFLINE EVIDENCE ONLY (27 distinct tests;
SIGKILL old-or-new durability, concurrency cap and init race reproduced).
This design covers the review's integration requirements plus the
reservation/transport lifecycle. Executor target: tools/self-commit-executor.py
@ 4a95bf557b399fd2be0296cd308bb142e5224cdd (frozen v3 pin, itself No-GO).
The gate hold still blocks any real publication path and live
qualification; this integration does not change that.

## Correction to a prior claim
The module commit message said "permission metadata preserved". Only the
permission BITS (mode) are verified-preserved across replace; uid/gid
are NOT (the replace creates a new inode owned by the writing user).
The docstring fix rides this integration pass; the reviewed pin stays
byte-identical until GO.

## Module hardening required before integration (draft patch exists,
uncommitted, coordinator-held; to be applied in the integration pass and
re-reviewed as one unit)
1. Reject symlink ledger paths and st_nlink != 1 (atomic-replace
   semantics would not hold); checked at init/reserve/reconcile/summary.
2. Entry validation extended: pid must be a non-negative int;
   reserved_utc/started_utc/completed_utc must parse as UTC timestamps.
3. Orphan cleanup: stale .tmp.<pid> files removed under the lock during
   reserve() and reconcile().
4. New reconcile(): dead-owner sweep + orphan cleanup without reserving,
   for run start and closeout reporting.

## Reservation/transport lifecycle in api()
1. rid, wait = reserve(path, run) - durable BEFORE anything else.
   LedgerError OR OSError here: halt the run, NO request sent, no reset;
   the batch closes with its reserved counts reported.
2. Sleep the returned wait (pacing is enforced by the integration, not
   the module; min_interval and rate_reset_until_epoch both honored).
3. transition(rid, "transport_started") - durable BEFORE the request.
4. Perform the request.
5. Response received: transition(rid, "completed", {"http": status}).
   Any exception, timeout or ambiguous failure:
   transition(rid, "unknown"). A crash between 3 and 5 leaves
   transport_started, swept to unknown by the next reserve/reconcile.
6. If transition itself raises LedgerError/OSError (incl. the post-replace
   dir-fsync ambiguity): halt, no further sends; the reservation may be
   consumed and STAYS consumed; the run is reported with unknown outcomes.
The executor must catch OSError as well as LedgerError at every ledger
call site - fsync/replace failures surface as OSError, and both mean
halt/no-send.

## Reporting taxonomy (unchanged, enforced in closeout)
reserved (durable upper bound) / completed_transports (local transport
finished; NOT provider receipt or billing) / unknown_outcome. Possibly-
sent = transport_started + unknown. Legacy b5/b6/b7 ledgers are NOT
imported silently; any import is an explicit operator act with recorded
counts, outside this pass.

## Review-requirement dispositions
- OSError catching: covered above (every call site).
- Wait enforcement: step 2; a send before the wait elapses is an
  integration bug the executor tests must catch.
- Dead-owner staleness: summary() may show stale transport_started
  between an owner's death and the next reserve; documented in the
  module docstring, and run start/closeout use reconcile() for an
  honest view. Missing-pid entries are treated as dead (conservative
  sweep to unknown, still counted) - never deleted, never a reset.
- Python >= 3.9: module uses only 3.9-compatible stdlib (dict-merge |
  operator is 3.9-OK; no zoneinfo/tomllib); integration tests run on
  the oldest supported interpreter.
- Metadata: mode only (see correction above).
- Symlink/hardlink: rejected, not just scoped (hardening item 1).
- Pid/timestamp validation and orphan cleanup: hardening items 2-3.

## Tests for the integration pass (all new, distinct methods)
- api()-level: crash between reserve and transport_started; crash
  between transport_started and send; halt on OSError at each ledger
  call site; wait enforced (mock clock, assert no early send); closeout
  report matches ledger taxonomy exactly.
- Module-level: symlink/hardlink rejection; pid/timestamp validation
  corpus; orphan cleanup; reconcile() sweep honesty.
- Reuse of the 27 existing module tests as the regression floor.

## Non-claims and holds
No rollout, no live provider calls, no batch authority, no gate
implementation (trust boundary unresolved), no claim that integration
makes the executor accepted: the whole assembly needs its own
independent review after implementation.
