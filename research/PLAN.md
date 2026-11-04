# Research_lab plan (v3: research work packages)

Owner: Researcher role. Updated: 2026-11-04. Sources and read-depth: REFERENCES.md (IDs R#/S#). Experiments go in experiments/ and link back to findings and source IDs.
Evidence classes: [PR] peer-reviewed, [PP] preprint, [H] hypothesis. A paper never proves our implementation works.
Research progress and implementation progress are tracked separately. A "next-version candidate" below is a proposal for the coordinator and Builder, not a commitment, and a finding is not a delivered feature.
Builder owns product code. Free tier only, no merges, no secrets in artifacts.

## Mission
Reduce the observed failures of the team launcher with cited, testable proposals, at low token cost.

## Method (all work packages)
1. Problem with evidence (incident, commit, log). 2. Research (papers + public systems, evidence level recorded). 3. Bounded experiment written first: hypothesis, baseline, one change, sample size, budget, stop rule. 4. Measure with a pre-declared metric; small N is labeled anecdotal. 5. Reviewer sign-off on the same pinned commit, then adopt, reject or park (coordinator and Builder adopt, not the Researcher). 6. Record every result, including negative ones, in experiments/.

## Research states
S0 scoped | S1 sources read | S2 finding published | S3 experiment designed | S4 experiment run | S5 reviewed, decision recorded.
Current: all WPs at S0-S2 as listed. No experiment has run.

## RW1 Reliable handoffs
- Goal / question: can a fixed handoff schema with a validator prevent empty or incomplete handoffs (observed: manual null-handoff recovery)?
- Sources: R3 (sec 5.2). Finding F3 published (findings/2026-11-04-initial-literature-scan.md). State: S2.
- Next-version candidate [H]: handoff schema (base/head, changed files, test output, failed attempts, open findings, next owner) + validator that rejects incomplete handoffs.
- Tests / acceptance: replay of the null-handoff incident is rejected automatically; N consecutive rehearsal handoffs need zero manual recovery; tokens per handoff measured vs free text (RW3 data).
- Dependencies: Builder owns the validator; needs the incident record and a replay fixture.
- Limits: R3 state was built by a fixed model on benchmark tasks.

## RW2 Independent review and acceptance gates
- Goal / question: what review input and gating catch the most defects at the least cost, and stop acceptance without external evidence (observed: Reviewer bypass, push before tests)?
- Sources: R1 (sec 3, 5.4, Fig 4), R2 (abstract, draft note, sec 3.16; figures abstract-only), R6/R7 abstract-only. Finding F1, F2 published. State: S2.
- Next-version candidate [H]: Reviewer gets task spec + diff + test output, one critic per round; acceptance requires a Reviewer verdict on the same pinned commit as the passing test output.
- Tests / acceptance: on the same Builder change set, spec+diff review finds at least the defects history-fed review finds, with fewer tokens (report both counts); a change without matching pin cannot be marked accepted.
- Dependencies: Reviewer seat (Christina side) agreement on input format; pin/gate from the coordinator workstream.
- Limits: R1 used frontier models and benchmarks; fresh-context vs separate-model effect is not isolated by R1; R2 is a preliminary single-agent pilot.

## RW3 Token efficiency
- Goal / question: how much do handoffs, reviews and history cost per message type, and which changes cut that without losing requirements or findings?
- Sources: R1 (critic cost, sec 5.4), R3, R8 abstract-only. State: S1 (baseline not collected).
- Next-version candidate [H]: schema handoffs (RW1), spec+diff review (RW2), rolling history with pinned requirements.
- Tests / acceptance: per-message-type token baseline from the project ledger, then the same tasks with each change; accept only with equal acceptance outcome. No savings claimed before measurement.
- Dependencies: execution owner's read-only project ledger/token export (offered after the current repair).
- Limits: R8 not read beyond abstracts.

## RW4 Stall and liveness detection
- Goal / question: how to flag a genuinely stalled seat without flagging an active one (observed: premature stall)?
- Sources: none applicable verified. R4 covers unbounded loops, the opposite problem. State: S0 (no finding).
- Next-version candidate [H]: stall = no state change for a window AND owner not live; never elapsed time alone.
- Tests / acceptance: replay of the premature-stall case does not flag; a genuinely idle seat does.
- Dependencies: Builder repair of the stall logic; liveness signal definition.
- Next step: source search (distributed-systems liveness/heartbeat, orchestration frameworks via RW5). If nothing applicable, stop and say so.

## RW5 Prior art in public systems (feeds RW1-RW4)
- Goal / question: which public multi-agent systems solve handoff, review, stall and token control well, and what can we adapt?
- Evidence ladder: 1 marketed claim < 2 examined implementation (code at a recorded commit) < 3 tested behavior (run or replayed by us). Never present level 1 as level 3.
- Per-source record: URL, commit/tag, date, LICENSE file, tradeoffs, applicability to a GitHub-centered seat-based launcher. Reuse: cite ideas; copy code only if the license allows with attribution; no private or proprietary content.
- Candidates S1-S6 in REFERENCES.md (licenses read 2026-11-04; all level 1, none examined). State: S0-S1.
- Acceptance: for RW1, RW2 and RW4, at least one level-2 design compared with ours, with a written adopt/skip decision.
- Dependencies: none. Next: OpenHands stuck-detection and context condensation (RW4, RW3), then LangGraph checkpoint/interrupt model (RW1, RW2).

## RW6 Rate-limit-aware provider routing (placeholder, not started)
- Goal / question: how to spread free-tier requests across providers without losing request accounting or provenance.
- Sources: none gathered. State: S0. No findings are claimed. Scope owner is the coordinator workstream; I add research only if asked.

## Priority and cadence
Order: RW2, RW1 (acceptance risk), RW3, RW4, with RW5 supplying level-2 examples. Daily cycle (web tools only, no model calls) advances one open question, records a result or stop reason, and reports only material insights, stopped lines, or proposals ready for Builder/Reviewer.

## Limits
Benchmarks use frontier models via other providers; our free-tier models may differ. Preprints may change.
