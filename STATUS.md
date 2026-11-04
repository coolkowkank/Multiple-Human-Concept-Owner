# Project status: team launcher

Current working branch: `team-launcher` (head `9407acc` plus the
cross-clone proof commit on top - see git log). Frozen evidence
branches: `rehearsal/i2i-1`, `rehearsal/i2i-2`, `rehearsal/live-1`,
`evidence/groq-1`. None of the frozen branches are modified by ongoing
work.

## What the launcher does

Runs a small team of seats (coordinator, builder, reviewer, QC) that
hand off work through a git-based bus. A seat's response can come from
a mock, a queued human/agent-reasoned response (`launcher respond`),
a local CLI, or an OpenAI-compatible HTTP endpoint, so models from
different providers can join the same team through one mechanism.

## Findings (live-1 review cycle, branch `rehearsal/live-1`)

A bounded live review cycle ran with genuinely reasoned turns:
coordinator assignment, an independent peer review, an independent QC
verdict, and a coordinator close. QC verdict: **PASS on the bounded
review batch, NOT readiness for parallel or unattended operation.**
The cycle found real defects:

| # | Severity | Finding | Status |
| --- | --- | --- | --- |
| 1 | major | Queued responses had no binding to the bus state they were reasoned against; a stale response could be applied silently after the bus moved | Fixed (`9407acc`): `respond` stamps turn/turn_seq/head; the runtime refuses stale applies and preserves the queue |
| 2 | minor | `launcher respond` staged with `git add -A`, sweeping unrelated dirty files into queue commits | Fixed (`9407acc`): only the queue file is staged |
| 3 | minor | Rendering a prompt wrote a session-id file as a side effect | Fixed (`9407acc`): session ids are lazy, minted on first seat action |
| 4 | minor | `respond` printed a seat command hinting a fixed branch, not the actual checkout | Fixed (`9407acc`): hint uses the real checkout branch and flags mismatches |

Each fix has a regression test. Suite: 60 tests green, including a
cross-clone integration test that reproduces the stale-response
scenario through real processes and proves the refusal.

Artifacts:
[review findings](https://github.com/coolkowkank/Multiple-Human-Concept-Owner/blob/rehearsal/live-1/review/live-1-findings.md)
·
[independent QC verdict](https://github.com/coolkowkank/Multiple-Human-Concept-Owner/blob/rehearsal/live-1/review/live-1-qc.md)

## Provider routes (access validation status)

Validation so far is credential-level only (non-inference calls);
no provider is "working" for the team until a bounded live test passes.

| Provider | Status |
| --- | --- |
| Groq | Free plan confirmed by the account owner. Key validated via `/models`. Bounded live test passed (2 turns, fail then self-repair; termination gap recorded honestly): [evidence/groq-1](https://github.com/coolkowkank/Multiple-Human-Concept-Owner/tree/evidence/groq-1/evidence/groq-1). Observed limits for `openai/gpt-oss-20b`: 8000 TPM / 1000 RPD |
| Requesty | Key validated via the gateway's `/models` (808 models visible, free-tier models present). Per docs, free tier is 200 requests/day and 20/minute per organization, shared across all free models; no card required, no trial expiry. No inference run yet |
| Cerebras | Key validated via `/models` (`qwen-3.8-27b`, `gpt-oss-120b`). Account plan and credit state are not yet established; no inference run |
| Gemini | Free tier exists per vendor docs (AI Studio key; free-tier content may be used to improve products). No key collected yet |

## What is proven vs not

Proven: the queue/transport mechanism (handoffs across clones, lease
behavior, stale-response refusal, conformance checks) under its test
suite; one bounded Groq live exchange with honest termination limits.

Not proven: unattended or parallel operation, reliable cycle closing
by live models (a live model did not emit the DONE status line on its
own), multi-day runs, heterogeneous-platform autonomy. These remain
claims to test, not features.

## Ongoing work

- Independent read-only review of the fix batch by the peer reviewer
  (accepted, results pending).
- Remaining technical gaps before any unattended/parallel claim:
  leases are cooperative and locally enforced; the relay is
  best-effort; supervisor restart semantics are untested; live models
  may not close cycles; rate-limit/backoff handling in the HTTP
  adapter is minimal; `verify_command` runs via shell and is not
  sandboxed; prompt-size budgeting against provider limits is manual.
- Next bounded meaningful proof: a fresh live cycle against the fixed
  head (`9407acc` or later), under a new explicit go-ahead, reusing
  the live-1 protocol with the fixed queue binding.
