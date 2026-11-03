# Evidence interface v0.1

> Status: v0.1, implemented by `launcher/` and consumed by the
> verification/evidence templates. Changes by agreement, versioned here.

This is the contract between the runtime and the review artifacts
(templates/batch-handoff.md, qc-verdict.md, review-findings.md,
decision-record.md, delegation-record.md, gated-run-evidence.md). The
runtime writes these fields; review seats and the guard read them.

## 1. Turn and fencing

- `STATE.json.turn` (string|null): the one seat allowed to write now.
- `STATE.json.turn_seq` (integer, +1 per handoff): the fencing token.
  Every handoff log entry carries its `turn_seq`. A writer must confirm,
  after its commit lands, that STATE still shows its own `turn_seq`
  advance; a writer that loses a commit race rebases and retries, and
  must not repeat already-committed writes (dedup by `turn_seq`).
- `STATE.json.turn_since` (UTC `YYYY-MM-DDTHH:MM:SSZ`): used only for
  stall detection, never as proof of work.

## 2. Message log (`LOG.jsonl`, append-only)

Each line: `{"ts", "seat", "kind", "body", "turn_seq?"}` with
`kind` in `message | handoff | finding | verdict | gate | answer |
status | error | restart | stall`.

An entry's presence in the log is an **acknowledgement of receipt by
the bus**, not authorization, not a turn transfer, and not proof the
named seat's model ran. A missing ack does not prove the remote side
did not act: senders retry with the same `turn_seq` and receivers
deduplicate on it.

## 3. Batch evidence fields (written per turn)

| Field | Format | Written by |
| --- | --- | --- |
| `head` | full commit SHA | runtime before verify |
| `verify_command` | one shell command | acting seat |
| `exit_code` | integer | runtime, from actually running it |
| `suites` | one line per suite: `<suite>: <pass>/<fail>` | acting seat |
| `environment` | `mock` / `local` / `hosted` + account type | acting seat |
| `owner_basis` | decision-record ID, or quoted owner words + channel + timestamp | acting seat, for any gated item |

A batch counts as green only when the Reviewer re-runs the same
`verify_command` on the same `head` and records exit 0 (Bill P3).

## 4. Gates (`gates/PENDING.jsonl`, `gates/ANSWERS.jsonl`)

Pending: `{"id", "ts", "seat", "question", "options", "recommendation"}`.
Answer: `{"id", "ts", "author", "answer"}`. A gate is open until an
answer with the same `id` exists. Scope, spend, access, merge/go-live
and brief changes must be gates, never seat decisions.

## 5. Roster and endpoint claims

`roster.json` seat fields: `role`, `allowed_paths`, `adapter`,
`human_owner`, `verified_endpoint`, `commit_identity`,
`last_verified_at`.

A roster entry is a **claim, not evidence**. `verified_endpoint` is
meaningful only with `last_verified_at` set by an observed action (a
readiness reply plus a real read or write seen on the bus), and review
seats treat unverified entries as unverified. Authenticated permission
evidence (who granted what, where) lives in decision records, not in
the roster.
