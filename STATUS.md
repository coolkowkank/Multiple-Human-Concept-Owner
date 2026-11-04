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

| ID | Finding | State |
| --- | --- | --- |
| P1 | Recovery blocker: stale first queue line kept; re-`respond` appended behind it; seat refuses same stale line forever | fixed-unverified |
| P2 | Head binding incomplete: `_queue.head` stored but only turn/seq compared; head-only operator commit still applied | fixed-unverified |
| P3 | `commit_paths` committed the whole pre-staged index, not just its paths | fixed-unverified |
| P4 | `init` and gate-answer routes still used `git add -A`; audit wording corrected | fixed-unverified |

P1-P4 fixes: P1 `respond` refuses to queue behind stale lines;
`--discard-stale` is the verified recovery. P2 full head check
(ancestor + queue-files-only diff). P3 pre-staged index is refused,
never swept. P4 `init` and gate answers stage exactly their files.
Regression tests pin each. Independent re-review pending; states move
to `verified` only after it.

## Provider routes (credential-level validation only)

No provider is team-ready until a bounded live test passes. Keys live
in the owner's vault, never in the repo.

| Provider | State |
| --- | --- |
| Groq | Free plan owner-confirmed; `/models` OK; bounded 2-turn live test passed with honest termination gap ([evidence/groq-1](https://github.com/coolkowkank/Multiple-Human-Concept-Owner/tree/evidence/groq-1/evidence/groq-1)); `openai/gpt-oss-20b` observed 8000 TPM / 1000 RPD |
| Requesty | `/models` OK (808 models, free tier present); free tier 200 req/day + 20/min per org, shared pool, no card, no expiry (vendor docs); no inference yet |
| Cerebras | `/models` OK (`qwen-3.8-27b`, `gpt-oss-120b`); plan/credits not established; no inference |
| Gemini | Free tier exists per vendor docs (AI Studio; free content may train products); no key collected |

## Proven vs not

Proven: queue mechanism - cross-clone handoffs, leases, stale
refusal + recovery, conformance checks (70 tests). One bounded Groq
live exchange.

Not proven: unattended/parallel operation, live models closing cycles
(no DONE status line observed), multi-day runs, heterogeneous
autonomy.

## Next actions

1. Independent read-only re-review of the P1-P4 fixes (this head).
2. Then, under a fresh explicit go-ahead: bounded live cycle on the
   fixed head, live-1 protocol, hard stop.
3. Open gaps before any unattended claim: cooperative local leases;
   best-effort relay; supervisor restart untested; models may not
   close cycles; unsandboxed `verify_command` shell; manual
   prompt-size budgeting. (429 backoff with Retry-After landed in
   `HttpAdapter`, regression-tested against a stub server.)
