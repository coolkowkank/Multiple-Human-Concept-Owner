# WP4 / WP9 recovery handoff

2026-11-04. RecoveryExecutor implementation support, operator-authored.
No external project-model execution, provider call or savings claim.
Coordinator retains coordination/acceptance, not implementation.

## Frozen state and scope

- WP4: partial, weight 7. Original tiny-library run at
  `e51fae66afce4d1ae2bd8ef2e2ac011c692b03ca` reached DONE after manual
  null-handoff recovery and without a Reviewer turn. No new completion credit.
- WP9: in progress, weight 5. Delta-only rule adopted; reported batch-7
  11,607 tokens is composition, not savings. RW3 is a DIFFERENT seven-call
  tiny-library run: 5,831 prompt + 4,408 completion = 10,239 total;
  3,751 reasoning is INCLUDED in completion, not additional.
- Accepted offline runtime base: `26ff4bce5666afd6a3dbefbce7fe0d3d4a36e341`.
  Latch follow-up `09b76be0efd3bf405b4e45d43d336030b4b619ae` was awaiting
  independent review at handoff. Do not imply acceptance from test count.
- Privileged self-commit executor / live ledger path stays held.
- No merge, deploy, paid route, new access or credential retrieval here.

## Offline implementation delivered

`launcher/prompt_audit.py` adds an opt-in exact renderer audit and an adapter
wrapper. It leaves `runtime.py`, `adapters.py` and the existing executor
untouched to avoid another active writer's critical repair.

Each source has ordered character offsets, Unicode character count, UTF-8 byte
count and SHA-256. Exact concatenation is checked against the existing renderer;
renderer drift or mismatched actual call input is refused. Content is not
copied into the report. Full-prompt chars/4 estimates are clearly labelled
heuristics, not provider tokens. No estimated per-source tokens are summed.

The adapter wrapper records actual adapter invocations if explicitly installed
by a later reviewed integration. It changes neither system nor task text,
response, budgets nor retries. Correction suffixes are separately accounted;
each correction is another invocation. It does not count underlying HTTP
attempts: one adapter invocation may retry transport. Join to adapter usage
records only after adding a reviewed explicit request identifier; timestamp or
sequence proximity alone is not a reliable join.

Single writer only. Not a transport/budget/authorization ledger. Recording
failure before the call prevents it; recording failure after the call may mean
the adapter returned and MUST NOT cause an automatic replay.
`AuditRecordAfterSuccess` is a distinct exception with `retry_safe=False`,
`adapter_returned=True` and the local call ID. It is not transport/billing proof.
If error-record writing fails, the original adapter exception remains the raised
exception and the audit-write failure is chained as its cause. Crash after a start
record leaves outcome unknown. The wrapper delegates queue consume. Hash-only
logging is not permission to audit private material; scope stays public project.

Usage: supply the exact `task_prompt` input object as JSON on stdin to
`python3 -m launcher.prompt_audit`. The CLI is offline and emits hashes/counts.
It is not wired into a live roster. There are no model calls in this command.

## WP4: concrete next run, NOT authorized by this document

1. Independent reviewer names accepted runtime + reviewer-skip guard pins and
   verifies their composition. The frozen project chart states Reviewer-skip
   guard unbuilt; do not assume either accepted null-handoff fix or latch fix
   supplies the guard. Resolve this prerequisite before any run.
2. RecoveryExecutor prepares a NEW scratch target and roster with
   Coordinator -> Builder -> Reviewer -> QC -> Coordinator evidence at one
   application commit. Reviewer must independently rerun the exact test command;
   no manual turn repair, omitted seat, or DONE-only proof.
3. Confirm runtime ownership/single writer, offline suite, guards, response
   contract, allowed paths, aggregate budget and abort procedure at final pin.
4. Ask through the Sam -> Coordinator -> owner chain for ONE fresh run envelope:
   provider/model and current free-route terms, explicit total request cap
   INCLUDING retries/corrections, token/rate limits, time window, sequential
   concurrency=1, allowed target branch/paths, and review route. Old per-seat
   roster caps are evidence only, NOT available budget. Do not interpret
   concurrency cooldown/429 as daily quota exhaustion; quota remains unknown.
5. No fallback/probes unless included in that envelope. Halt on 429/challenge,
   unexpected charge, missing usage evidence or guard failure. Do not reuse the
   held executor. If no separately accepted path exists, live work stays blocked.
6. Record immutable run head, every attempt/outcome/usage including unknowns,
   Reviewer and QC verdicts and manual interventions (including none).
   Independent acceptance determines WP4, never this implementation author.

## WP9: matched comparison protocol, NOT authorized live calls

Stage A (now): test unchanged renderer auditing offline. Stage B (after review):
wire audit context at actual prompt construction and explicit request IDs into
usage records, proving correction/transport accounting with fake adapters.
Stage C (after new scoped approval): run baseline and delta variants on the same
pinned task set, model, runtime, response contract, requirements, safety text,
review route, completion/token caps, and rate settings. Counterbalance order
across task pairs; preserve independent Reviewer/QC checks. Do not compress
requirements, permissions, budgets, failure findings or source evidence.

Per pair record task/prompt hashes and source sizes, actual provider prompt,
completion and reasoning usage, every failed/unknown attempt, correction count,
transport requests, wall time, independent correctness and acceptance outcomes.
Report paired differences, sample size, failures, and uncertainty. Do not equate
chars/4 reduction with billed savings, remove failed pairs, treat reasoning as
additional to completion, or claim equal quality without independent evidence.
If usage on errors is missing, totals are observed successful usage only and
cost/savings remain incomplete. No numeric savings target or result exists yet.

RW1 is a proposed handoff validator; first compare it with the accepted
null-handoff repair. No duplicate behavior or automatic correction call is
adopted here. RW3 source composition supports measurement, not compression proof.

## Review/publication handoff

Implementation owner: RecoveryExecutor. Existing authorized publisher handles
transport only to an isolated WIP branch. This document grants no publishing or
provider authority. Independent review is required before integration; no main
merge or milestone update requested. Local branch base: team-launcher 96775af.

Observed public source locations (branch names, not invented deep links):
- https://github.com/coolkowkank/Multiple-Human-Concept-Owner
- Remote refs read directly with git: main (`docs/progress/progress.json`,
  `docs/progress/README.md`), Research_lab (`research/findings/2026-11-04-rw1-handoff-validator-spec.md`,
  `research/findings/2026-11-04-rw3-token-baseline-requesty-run.md`),
  live/requesty-tinylib-experiment (`.team/LOG.jsonl`, roster, brief, usage logs).


## Independent-review follow-up (2026-11-04)

The original 3cb4fcc was accepted for narrow offline opt-in/unwired use only,
with independently reproduced 16 focused and 212 full-suite passes. This
forward follow-up addresses the two error-signalling findings and adds system
renderer-drift coverage. Live wiring remains a separate reviewed step.

Before any matched live comparison, freeze an approved task list and sample
size, not a stopping rule based on favorable results. Use an initial bounded
pilot solely to estimate paired variance and failure rates; report it as a
pilot, not a powered savings claim. A later confirmatory sample size must be
chosen from pilot variance, a predeclared minimum useful difference and desired
confidence/power, subject to a separately approved call budget. If that budget
cannot support the sample, report imprecision rather than widen the budget.
No numeric sample size or live run is authorized here.

Assign neutral output IDs and have independent correctness judges blind to
variant/order and token usage, using one frozen rubric. Keep the mapping for
reconciliation after verdicts; document any unavoidable unblinding. Retain all
predeclared pairs. If only one variant errors, show that pair in the primary
attempted-pair results as a discordant failure, not a paired successful saving.
Report acceptance/error counts for all attempted tasks; successful-completion
paired token differences are a separate conditional analysis with the exact
eligible-pair denominator. Do not impute missing error tokens as zero. Report
observed usage and unknown usage separately; no unconditional savings or
non-inferiority claim can follow from incomplete usage/correctness evidence.

## WP4 source reconciliation and offline acceptance matrix

Read public refs at 18:15 EET: reviewer-skip branch
`55e7c7ef785fdb0eceb78208c0fb501ca3243e72` contains only a task, not guard
implementation; accepted latch v5 candidate
`561f2e5cc4eb84b4cdcbacd81394a882495b8704` still has unconditional DONE in
runtime.py. The older task is QC-only and does not prove Reviewer participation.
No provider authority question is ready until this gap and composition are
resolved. This is prerequisite preparation, not a guard implementation.

Minimum offline matrix for the eventual composed candidate:
- DONE without Reviewer evidence: refuse completion, even with QC PASS.
- DONE without QC PASS: refuse completion, even with Reviewer evidence.
- Reviewer and QC evidence for different application states: refuse.
- Both pass at the same frozen application pin: eligible, subject to all other
  acceptance criteria and independent reproduction. A seat name or prose claim
  is not authenticated execution evidence by itself.
- Application files change after verdicts: invalidate both verdicts.
- Evidence/log-only commits: must not accidentally invalidate unchanged
  application evidence. Freeze the application-path/tree binding definition
  and record both commit provenance and application digest. No naive equality
  with the latest moving repository HEAD.
- Missing Reviewer/QC seat, stale evidence or ambiguous application binding:
  fail closed and expose the missing prerequisite; never silently skip a seat.
- Actual run report must distinguish unattended runtime recovery from operator
  repair. Offline matrix success alone is not an autonomous WP4 result.
