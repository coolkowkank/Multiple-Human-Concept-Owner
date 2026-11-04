# Proposed vs tested

An honest map of what this blueprint is built on. It claims no novelty and no comparative performance.

## Established practice (proven elsewhere)

- One authoritative written specification, versioned changes, recorded decisions: decades of RFC and Architecture Decision Record practice.
- Single-writer control, required review before merge: standard branch protection and code review gates.
- Role-based AI teams with structured handoffs: MetaGPT and ChatDev, published with public code and benchmarks.
- Enforcement of architectural rules by linters and structural tests rather than instructions alone: published harness-engineering accounts (see references).

## Carried over from a reference project (worked there, once)

- The coordination method: a Coordinator managing all delivery roles, written turn tokens, written findings, independent QC verdicts. This ran in the reference project this blueprint was distilled from. One project is not proof of generality.
- The delegation record and the ask-only-when-blocked practice (`docs/delegation.md`): used in the reference project in a form specific to it; the generic text here has not been run elsewhere.

## Proposed here (untested)

- The blueprint itself: whether a new team can start a different project from these documents without explanation.
- The multi-owner concept level with per-owner personal robots: each component has public precedent (see references), but the combination has not been found published and has not been tested here.
- The session-to-repo handoff for autonomous high-impact seats: not set up or verified; confirm the mechanism and each session's actual access before relying on it.
- Multi-owner standing delegation (`docs/delegation.md`): each owner's own delegation, with their own limits and gates, applied by one Coordinator across owners. Untested until a fresh team has run it. It is prompt-level policy, not an enforced runtime capability.
- The capacity rule as an enforced constraint: currently a written convention, not tooling.

## Next useful test

Whether a fresh team can adopt this blueprint on a new project and run one full batch cycle - brief, turn token, build, review, QC gate, records - without outside explanation.

## Team launcher runtime (added 4 Nov 2026, branch team-launcher)

Tested by the mechanism and integration suites (46 tests) and the self-checking demo, all
on mock adapters in local git repos: turn-token enforcement (off-turn
and out-of-path commits rejected), single-session leases, adapter crash
leaving the turn for retry with no duplicate write, verify exit codes
recorded per batch, gate open/answer cycle, supervisor crash-restart
with escalation after the restart limit, relay wake/long-poll/auth and
silent fallback to git polling; cross-clone handoff through a shared
remote with exactly-once verification; a supervised run with live relay
and webhook receivers; conformance checker acceptance/rejection;
false-green recording (a seat's prose claim cannot change the recorded
exit code).

The cli and http adapters are exercised through the real seat path
(lease, apply, LOG, recorded exit) against local fixtures only - a
fixture command and a loopback fixture HTTP server, NOT live models.
The relay remains loopback-only.

The queue adapter (responses reasoned outside the process: interactive
paste or assistant-mediated agents) plus the `prompt`/`respond`
operator commands are exercised through the real seat path in the
suite, including consume-once, empty-queue retry, stable per-clone
session ids against the single-session lease, and supervisor
exclusion. One local assistant-mediated cycle (4 turns, fizzbuzz
batch) ran with every response reasoned at turn time and every verify
command executed by the runtime, closing DONE with conformance PASS.
That cycle used ONE reasoner for all seats and manual transport: it is
evidence the harness applies genuinely-reasoned work, NOT of
autonomous model judgment, heterogeneous platforms, or unattended
operation.

## Two-operator rehearsal cycle (4 Nov 2026, branches rehearsal/i2i-1 and rehearsal/i2i-2)

One bounded cycle, two real operators (two same-kind Instincts - NOT
heterogeneous platforms), all seat content static operator-authored
mock material - NOT model judgment. Observed: one handoff per turn_seq
(1-4, strictly increasing), one lease per seat turn, per-turn queues
consumed once each, runtime-executed verify commands with real recorded
exit codes at every seat, independent re-run of the builder's verify by
the reviewer, a QC gate whose FAIL stands. One real procedure failure
(dirty tree blocking the seat's pull) was caught by the HALT rule
before any mutation - it preceded mutation and is not transaction-race
evidence; race recovery is covered by simulated tests only.

FAILED acceptance metric, kept visible: the QC verdict FAILED the
all-artifact metric - review/batch-1-findings.md is structurally
nonconformant (invalid finding types, missing Reproduced:/Probed:
entries). The original is preserved unedited; a correction needs a
future agreed turn. The batch code verdict (a genuine earlier review
finding fixed and regression-covered) stands.

NOT exercised or proven: real duplicate-wake and crash faults (F1/F3),
independent QC (same worker held Reviewer and QC, disclosed), live
models, cross-platform generality, any sustained or unattended run.
i2i-1 additionally gave: fallback receipt after a withheld wake hint
(~13 min, operator-measured, not server-authoritative), one diagnosed
direct-record-mutation deviation (no lease - visible in the record),
and two checker repairs (turn_seq rule vs the interface, guard vs
runtime-provenance limits). A closed cycle must now be marked done;
i2i-2's final state (turn null, status active) predates that check.

Proposed, not started: a real-model rehearsal (routes in
docs/launcher.md), the staged fault-injection and days-long soak tests
(method: MAS-FIRE and chaos-engineering sources in docs/references.md).
No sustained unattended run has happened; nothing here claims one.

## Self-commit executor (added 4 Nov 2026, branch team-launcher + live/groq-dev-3)

- Fixture-tested offline (tests/test_self_commit_executor.py, no provider):
  fail-closed capture at startup and mid-round, global call budget counted
  before each request, malformed tool arguments recorded and fed back,
  non-JSON HTTP error capture, exactly one checkpoint per event.
- Live-verified once (4 Nov 2026): a model issued write/commit/push tool
  calls that produced commit b993bd2 on live/groq-dev-3; transcript on the
  branch. One success is not proof of reliability.
- Known accounting gap: pre-fix runs (attempts 13-14) lost crashed-run
  call records to a sandbox reset; only the 3 successful attempt-14 calls
  are log-verified. Earlier totals are reconstruction, marked as such in
  .team/ATTEMPTS.md.
- Peer-reviewed: capture mechanics cleared in scoped static review;
  MAX_CALLS enforcement not independently reproduced by the reviewer.

## Token-only GitHub push transport (2026-11-04)

- Capability: token-only GitHub push transport for standalone runs (tools/setup_push_auth.py + repo-local git credential helper reading a 0600 token file; no GitHub password involved).
- Status: developer-reported live verification on 2026-11-04: setup checks identified the token account and its repo push permission; the developer reports model-issued commit/push using the bot-token helper, with e056ae9 and ac295a9 present remotely. Public Git confirms the commits and their content, not the authenticated pusher; the independent reviewer did not execute the setup or witness the pushes.
- Limits: token scopes are the capability ceiling; human project authorization is the operating boundary. Author (per-model name), committer and pusher identities stay separate (docs/design-decisions.md D14).