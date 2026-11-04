# Proposal: deterministic log reconciliation instead of a model role

Status: PROPOSAL, unbuilt. Date: 2026-11-04. Author: coordinator
(support tooling design). Serves WP9 evidence measurement and batch
closeout bookkeeping. Decided after the 2026-11-04 Coordinator Assistant
qualification trial (recorded in docs/team/blueprints/coordinator-assistant.md):
the trialed model showed good uncertainty discipline on one small task
but an empty answer, a truncated table, quote-fidelity flaws and 4-11x
reasoning-token overhead on the real workload - so the recurring
reconciliation job goes to a deterministic script with a small review
step, not to a model instance.

## Problem
Every batch closeout needs the same table: one row per ledger
reservation and per API call, with outcome
(reserved_only / completed_transport / error_transport / unknown),
verbatim evidence fields, and token usage totals. Today this is done by
hand. It must never infer completions, and every non-unknown row must
cite verbatim evidence.

## Design: tools/extract_log_evidence.py (stdlib only, offline)
Inputs: a budget ledger JSON, the executor transcript event log, the
run stdout log. All three hashed (sha256) into the output header.
Rules:
- api_response events with a usage block => completed_transport, quoting
  the id/usage fields verbatim.
- api_response events with an error object, or a fatal provider-error
  traceback in the run log => error_transport, quoted verbatim.
- ledger reservations with no matching response event => unknown.
  Sequence matching is by order only; a reservation is never matched to
  a response on inference.
- Token usage totals are sums over evidenced usage blocks only, split
  prompt/completion; no estimated or prorated numbers.
Output: a markdown table + the input hashes + a coverage note listing
anything the logs do NOT cover (e.g. reservations without events).

## Review step (small, human/coordinator)
The coordinator spot-checks a bounded sample (at least the first, last
and any error rows) against the raw artifacts before the table enters a
closeout record. The script is deterministic, so a found discrepancy is
a script bug to fix, not a judgment call to negotiate.

## Why deterministic (trial evidence, 2026-11-04)
A free-tier reasoning model was trialed on exactly this job (5
attempts, cost 0): one clean small-task answer with flawed "verbatim"
quotes, one empty answer (reasoning exhausted the token budget), one
table truncated at 7.5 of 8 rows. Raw reasoning-vs-visible token counts:
8/0, 2771/678, 4000/0, 7327/673. A deterministic extractor is free,
auditable, and cannot paraphrase a quote.

## Non-claims
- No semantic judgment about model output quality; this reconciles
  transports and tokens only.
- Coverage is limited to the executor log formats as of
  live/executor-hardening-v3 (4a95bf5) and the batch 12-13 artifacts;
  format changes need extractor changes.
- completed_transport remains a local-transport fact, never provider
  receipt or billing proof.

## Implementation
Would be Project support tooling (stdlib, offline, tests first),
requiring its own authorization; not started. The v4 durable ledger's
transport_started/completed states make this extraction exact for
future batches; the b5-b13 artifacts remain partially underdetermined
by their formats and the extractor must say so where they are.
