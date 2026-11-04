# Project status: team launcher

Living tracker for findings and ongoing work. Finding IDs are stable
across updates. States: `open` / `fixed-unverified` (fix + regression
test landed, independent review pending) / `verified` (independently
reproduced). Frozen evidence branches never change: `rehearsal/i2i-1`,
`rehearsal/i2i-2`, `rehearsal/live-1`, `evidence/groq-1`.

New to the repo? Read `HANDOFF.md` first, then only what your task
needs.

## Findings

### Cycle live-1 (evidence frozen on branch `rehearsal/live-1`)

Independent QC verdict: **PASS on the bounded review batch only - NOT
readiness for parallel or unattended operation.**
[review findings](https://github.com/coolkowkank/Multiple-Human-Concept-Owner/blob/rehearsal/live-1/review/live-1-findings.md)
·
[QC verdict](https://github.com/coolkowkank/Multiple-Human-Concept-Owner/blob/rehearsal/live-1/review/live-1-qc.md)

| ID | Sev | Finding | State |
| --- | --- | --- | --- |
| F1 | major | Queued responses unbound to bus state; stale apply possible | verified subcase: turn/seq stale refusal + queue preservation (`9407acc`, cross-clone proof `a80255f`); full head binding tracked as P2 |
| F2 | minor | `respond` swept untracked dirt via `git add -A` | verified subcase: untracked dirt not swept (`9407acc`); pre-staged index case tracked as P3 |
| F3 | minor | Prompt render wrote session-id file as side effect | verified, fixed `9407acc` (lazy ids, independently reproduced) |
| F4 | minor | `respond` hinted fixed branch, not actual checkout | verified, fixed `9407acc` (independently reproduced) |

### Patch review of `9407acc` (independent, read-only)

Second review round (`dbeb842`, independent, read-only): P2
**verified**. P3 **verified** with residual R3. P4 `init` **verified**;
gate-answer route broken (R2). P1 **partial** - residual R1. No
overall PASS.

| ID | Finding | State |
| --- | --- | --- |
| P1 | Recovery blocker: stale first queue line kept; re-`respond` appended behind it | partial: turn/seq recovery verified; residual R1 |
| P2 | Head binding incomplete: only turn/seq compared | verified (`dbeb842`) |
| P3 | `commit_paths` committed the whole pre-staged index | verified (`dbeb842`); residual R3 |
| P4 | `init` and gate-answer routes used `git add -A` | init verified (`dbeb842`); answer broken (R2) |
| R1 | `respond` stale scan checked only turn/seq, not head; `--discard-stale` could not drop a head-stale line | verified (`a0b1b699` review, scoped to the reproduced interactions) |
| R2 | Gate-answer message lacked the required prefix; the installed hook rejected it, leaving ANSWERS staged | verified (`a0b1b699` review, scoped; hook-installed CLI reproduced) |
| R3 | Pre-staged refusal ran after the queue append: uncommitted residue, duplicate on retry | verified (`a0b1b699` review, scoped) |
| R4 | Outside-domain dirt failed the guard only after mutation, leaving advanced uncommitted state | verified (`a0b1b699` review, scoped; in-domain dirt is intentionally swept, not isolated) |

R1-R4 **verified (scoped)** by the independent review of `a0b1b699`
(76 tests, installed-hook CLI), non-regressed at `bc9eb48`. The
`a0b1b699` review found N1, fixed in `3017bbd` and **verified
(scoped)** by the independent review of `bc9eb48` (82 tests,
installed-hook): the original SeatError surfaces, the error-record
commit is LOG-only (no sweep), the index stays clean, recovery
works, pre-staged record refusal preserves the index, and a guard
rejection unstages its own LOG append. Caveat from that review: an
unstaged LOG append may remain when the record is refused - not a
blanket no-effect.

| ID | Finding | State |
| --- | --- | --- |
| N1 | Loop mode (no `--once`): the error-record commit used `commit_all` with a guard-rejected message - swept dirt, masked the original SeatError behind a BusError, left staged residue blocking `respond`. `--once` was unaffected | verified-scoped (`bc9eb48` review; fix `3017bbd`: LOG-only `commit_paths` + `TURN:` token message + original error re-raised) |
| M1 | The N1 LOG-only error commit moves head, so a queued response bound to the pre-error head goes stale; discard/requeue recovers | open-minor (documented interaction from the `bc9eb48` review; the head binding is intentionally NOT weakened - discard with `--discard-stale` and requeue) |

Not a clean pass: the reviews confirm scoped fixes only. The newer
adapter changes (max_tokens a29f7c5, reasoning_effort bc9eb48) are
fixture-tested but NOT peer-verified. Remote provider runs, loop-mode
endurance, and crash/restart cycles remain unproven.

## Provider routes (credential-level validation only)

No provider is team-ready until a bounded live test passes. Keys live
in the owner's vault, never in the repo.

| Provider | State |
| --- | --- |
| Groq | Free plan owner-confirmed; `/models` OK; bounded 2-turn live test passed with honest termination gap ([evidence/groq-1](https://github.com/coolkowkank/Multiple-Human-Concept-Owner/tree/evidence/groq-1/evidence/groq-1)); `openai/gpt-oss-20b` observed 8000 TPM / 1000 RPD. Note: the model's TURN commits landed in a scratch test repo; this repo holds exported artifacts only - NOT proof of a live provider pushing to this repo |
| Requesty | `/models` OK (808 models, free tier present); free tier 200 req/day + 20/min per org, shared pool, no card, no expiry (vendor docs); no inference yet |
| Cerebras | `/models` OK (`qwen-3.8-27b`, `gpt-oss-120b`); plan/credits not established; no inference |
| Gemini | Free tier exists per vendor docs (AI Studio; free content may train products); no key collected |

## Proven vs not

Proven: queue mechanism - cross-clone handoffs, leases, stale
refusal + recovery, conformance checks. Test counts are pinned per
code state: 82 tests green at `bc9eb48` (2026-11-04, developer run;
independently reproduced in the `bc9eb48` review). One bounded Groq
live exchange in a scratch repo (artifacts exported here, not a live
push to this repo).

Not proven: unattended/parallel operation, live models closing cycles
(no DONE status line observed), multi-day runs, heterogeneous
autonomy. The format-correction round (strict revalidation after one
re-ask, replacing a prose-salvage heuristic that review rejected as
intent-unsafe) and the path-guard correction round are fixture-tested
only - NOT live-verified, NOT peer-reviewed.

## Next actions

1. Under a fresh explicit go-ahead: bounded live cycle on the
   reviewed head, live-1 protocol, hard stop.
2. Resolve M1 (queued response goes head-stale after a LOG-only error
   commit): today the operator discards with `--discard-stale` and
   requeues; decide whether the runtime should offer that recovery
   itself - without weakening the head binding.
3. Open gaps before any unattended claim: cooperative local leases;
   best-effort relay; models may not close cycles; unsandboxed
   `verify_command` shell; manual prompt-size budgeting (now estimated: `launcher prompt --measure`, chars/4 heuristic - an estimate, never an exact tokenizer count). Closed from
   this list: 429 backoff with Retry-After. Scoped coverage only:
   one orphaned-lease fixture proves a new supervisor's seat stops
   instead of duplicating a turn; full crash/restart cycles and
   endurance remain untested.
