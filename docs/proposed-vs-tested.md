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

## Model-issued commits, identity and first-edit failure (4 Nov 2026, live/groq-dev-4)

- First live model edit (e056ae9) replaced a 110-line findings doc with a
  7-line summary: an over-deletion the review loop caught. The model then
  restored the full doc and added only its entry (ac295a9), and the
  reviewer supplied the final transport wording (applied in 015e551).
  Lesson: first model output is not final output; immutable feedback plus
  re-review is what made the fix verifiable.
- Identity separation proven live (5ca0261): one model attempt issued
  write_file, git_commit and git_push in three provider calls (this model
  emitted exactly one tool call per response; not assumed universal).
  Resulting commit: author "Groq (gpt-oss-120b model)" on the shared
  bot's account-linked noreply, committer coolkowkank-bot, push
  authenticated by the bot credential, remote head verified by the
  operator. Public git shows author/committer/content; which credential
  authenticated a push is operator-verified, not git-provable.
- Failure mode kept visible: the same demo first ran with a 1-call
  budget and stopped after write_file only (budget_stop recorded; no
  commit, no push). A budget stop is not a completion. One other attempt
  spent its third call on an HTTP 429 (free-plan rate limit) and stopped.
- Capability is not authority: holding a provider or push token only
  makes a run possible. Generic onboarding must derive the committer
  identity from the verified token account (or explicit config) - the
  executor hardcodes no identity and refuses otherwise - so another
  user's token never silently attributes work to this project's bot.

## Token efficiency, measured from records (4 Nov 2026)

Recorded provider usage (usage fields in the per-event transcripts on
live/groq-dev-3-records):

- The executor used to request a trailing summary round after a
  successful push. Measured waste: 1,078 of 3,653 total tokens (attempt
  bot-auth-test) and 1,921 of 8,036 (attempt loop-c1) went to a final
  no-tool-call summary response.
- The prompt grows every round because the full history is resent; the
  largest single growth step is the model's own write_file arguments
  echoed back (loop-c1 round 3 prompt 1,629 tokens vs 1,021 the round
  before, after a 576-completion-token file write).

Changes (tests 9-11 in tests/test_self_commit_executor.py):

- The run ends automatically on a successful git_push; the system prompt
  tells the model no summary is needed after it.
- After a successful write_file, the file content is elided from the
  in-memory history sent to later rounds (a placeholder points at the
  transcript; the full bytes stay in the recorded transcript and every
  elision is itself recorded).

Not changed: review feedback still reaches the model VERBATIM; budget
accounting (every attempted request counts), fail-closed capture and
provenance trailers are unchanged. Savings beyond the trailing-round
figures above are estimates until a future run records new usage; none
are claimed here.

## Standby provider routes, qualified (4 Nov 2026)

Probe-verified with the account's stored keys; free routes only; 4 provider
requests total, each a single small tool-calling probe (a real capability
check, since the executor route depends on tool calls):

- Cerebras: key valid; models listed gpt-oss-120b and qwen-3.8-27b. Free
  Trial tier limits (vendor docs, inference-docs.cerebras.ai/support/rate-limits):
  5 requests/min, 30K uncached tokens/min, 1M tokens/day per model.
  gpt-oss-120b returned a valid tool call (181 tokens total).
- Requesty (router): key valid; 815 routed models listed, 13 of them
  zero-price. Tool calls verified at cost 0 on google/gemma-4-31b-it
  (125 tokens) and novita/ling-3.1-flash (299 tokens). Free tier per
  requesty.ai/pricing: 200 requests/day on free models, no card. One
  listed free model (nvidia/nemotron-3-super-120b-a12b) returned 404 at
  completion time: a listing is not availability.

Both routes are STANDBY only: qualified, not assigned active work. Using
either as a Builder or reviewer route still needs the owner-scoped task,
per-run budget and the same capture/budget guards as the Groq route.

## Acceptance target (owner-stated 4 Nov 2026)

The end goal: someone with their own AI clones this repo, runs it, and a
team is set up in their target repository; they hand the Coordinator the
concept in the agreed .md brief and leave; the Coordinator manages team
dynamics and keeps working while the concept is unchanged, asking only
when genuinely blocked or a concept-level decision is needed, inside
agreed permissions and budgets, stopping when done.

Status: NOT MET. The current hands-on runs (this repo's own development)
required per-round steering and are not evidence of that autonomy. The
fresh-clone, concept-to-result test - a new adopter's own AI running one
full batch cycle with no Instinct-specific help - remains the open test
("Next useful test" above). Nothing here claims it has passed.

## Unattended-run call budgets (4 Nov 2026, branch team-launcher)

Toward the acceptance target above: the `http` seat adapter now takes an
optional per-seat provider call budget (`call_budget`) and usage record
(`usage_log`) in the roster spec. Every attempted request counts -
successes, HTTP errors, 429 retries, unreachable transport - checked
before the request is issued; at the cap the seat fails closed with
AdapterError, which the supervisor treats as a seat failure (restart
limit, then escalation), never as done work. The count is derived from
the usage log at adapter startup, so supervisor restarts and resumes do
not reset it (single-session lease keeps one writer per seat), and a
budget without a usage log is refused as misconfiguration. `launcher
launch` refuses http seats without a budget unless the operator
explicitly passes --allow-unbounded; legacy rosters still run everywhere
else but are UNSUITABLE for unattended runs. Each attempt appends one
JSON line (ts, model, attempt, outcome, provider usage) so token spend
is measured from the record. Fixture-tested offline
(HttpAdapterBudgetTests, 4 tests): refusal beyond the cap issues no
request, 429 retries consume budget, usage lines record every attempt,
roster spec wiring. Not yet exercised: a live unattended run under a
budget. The fresh-clone adopter command path (clone -> init into a
separate target repo -> layout/guard/brief installed -> status) is
covered offline by FreshCloneAdopterTests, and a REAL supervised runtime
cycle on a fresh target (FreshTargetFullCycleTests: init via CLI,
scripted rehearsal roster installed up front - no per-turn injection -
then `launcher launch` spawns the seat processes to DONE with the guard
hook active) now passes; it is rehearsal seats, NOT a real adopter-AI
test. One adopter-path gap was found and fixed doing this: `launch` never
issued the first turn token (the demo seeded it by hand); the supervisor
now issues the first turn to the coordinator when the brief is present
and the state is still forming, and stays forming (with a gate) when the
brief is empty. The bounded live proposal is
docs/proposals/live-requesty-cycle.md (not run): disposable LOCAL-ONLY
target repo (no remote writes), five seats on Requesty ZERO-PRICE models
(google/gemma-4-31b-it - zero-price in the account's own model listing
and "cost": 0 observed on this account's probes), 20-request global cap
split per seat and persisted across restarts via the usage logs, 1800s
wall stop, DONE/ESCALATE/wall-kill stop conditions, read-only peer
review of the record afterward. The Cerebras variant
(docs/proposals/live-cerebras-cycle.md) is ON HOLD: its free tier is
$5 credits against a verified payment method, credits are spend, and
whether this account's earlier probe consumed credit is unverified
without a console/ledger check. Legacy behavior is unchanged when the keys are absent - existing
rosters keep working, but unattended autonomous runs should set budgets.

## WP9 usage join (offline, unwired)

`launcher/usage_join.py` joins prompt-audit rows to usage evidence by the LOCAL
`call_id` minted before any I/O. `PromptAuditAdapter` now adds an optional
`reported` object to the `adapter_call_returned` row (existing fields and
`provider_tokens: null` unchanged): `origin` (set by the adapter class, never by
provider content), `response_id_sha256` (only for ids matching
`^[A-Za-z0-9._:-]{1,128}$`; raw ids are never stored), and `reported_usage`
(plain non-negative ints below 1e9, else a status marker).

Provider fields are REPORTED, not verified: the body `id` is an opaque response
id, not proven request or billing identity; a provider id is optional and its
absence does not block counting reported usage. A repeated id across calls
blocks totals. Mock rows never produce provider totals. Wiring in `HttpAdapter`
only exposes `last_call`; no runtime path enables this by default. No provider
call has been made through it and no savings are measured or claimed.
Requesty lane gap (precise): the Ryan-lane Requesty transport already returns
sanitized provider-reported `usage` in its own result and ledger (keyed by its
ledger rid), and sends no client request id and captures no body id. What is
unresolved is the product wrapper interface: that transport is not an
`HttpAdapter`, so it does not set `last_call` or the class capability, and its
usage does not reach `PromptAuditAdapter` `reported` evidence or the call_id
join. Absence of a provider id is not absence of usage; connecting the two is a
separate, unreviewed change.

Amendments after independent review: the join field is named
`response_id_sha256` (sha256 of the provider-reported response id, not a vendor
request id). The audit wrapper trusts `last_call` only when the adapter CLASS
sets `REPORTS_PROVIDER_USAGE = True` (instance data cannot claim it). Join
counts use the wrapper bound (plain int, 0 <= n < 1e9); non-dict or non-string
`call_id` rows are ignored and counted, never raised on; invalid JSON lines in
the CLI abort with a message. CLI sources: audit-derived usage is added to the
USAGE file, and a call_id present in both gives `error:duplicate_usage`.
All token figures are provider-REPORTED, not verified.

## WP9 Builder audit runner: recovery rules (offline, unwired)

`launcher/builder_audit.py` takes an exclusive `<record>.reserve` file before
its one call. The reserve is never deleted automatically and never reset by the
runner. If a run crashes after reserving, or the record write fails after a call,
a human must inspect the audit file, decide whether a call was made and
whether it was paid, and record that decision before removing the reserve.
Removing it without that check can double-spend a capped call. A corrupt audit
file stops the runner before any reserve or call. Provenance is `fake` (totals
always unknown) or `provider_unverified` (reported usage, not verified).
