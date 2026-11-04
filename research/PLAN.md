# Research_lab plan

Owner: Researcher role. Updated: 2026-11-04. Builder owns product code; this plan proposes, it does not change the product.
Evidence classes: [PR] peer-reviewed, [PP] preprint, [H] hypothesis. A paper never proves our implementation works.
A line is "closed" only with a tested result or an explicit stop reason. Adoption needs a test plus independent Reviewer sign-off.

## Mission
Reduce the observed failures of the team launcher with literature-backed, testable proposals, at low token cost.

## Problems, objectives, measures

### P1 Reliable handoffs (gap G1: manual null-handoff recovery)
- Objective: no handoff reaches the next seat empty or missing base/head, test output, open findings, or next owner.
- Proposal E2 [H, from HSC-Bench https://arxiv.org/abs/2610.36523]: fixed handoff schema + validator that rejects incomplete handoffs.
- Success: replay of the null-handoff incident is rejected automatically; zero manual recovery in N consecutive rehearsal handoffs; handoff tokens vs free text measured, not assumed.
- State: literature scanned, nothing tested. Next: draft the schema fields and a replay fixture for Builder/Reviewer to evaluate.

### P2 Effective independent review (gap G3: Reviewer bypass, push before tests)
- Objective: no acceptance and no push without an external check (pinned HEAD, real test output) and a Reviewer verdict on the same pin.
- Proposals: E1 [H, from https://arxiv.org/abs/2610.34577] Reviewer input = task spec + diff + test output, not full history. Supporting evidence for external gates: https://arxiv.org/abs/2607.25152 ([PP], preliminary).
- Success: on the same Builder change set, spec+diff review finds at least the defects history-fed review finds, with fewer review tokens. Report both counts.
- Open: fresh-context vs separate-model effect is not isolated in the sources; if we want to claim either, we need an ablation on our own tasks (small N, label as anecdotal).
- State: gate already built by Builder/coordinator; review-input experiment untested.

### P3 Lower token use (gap G4)
- Objective: lower tokens per handoff and per review without losing requirements or findings.
- Proposals: E3a measure baseline tokens per message type from the ledger (data we already have); E3b compare schema handoffs and spec+diff review against baseline; E3c read context-management work (https://arxiv.org/abs/2610.34425, https://arxiv.org/html/2608.21690) for rolling-history design.
- Success: measured token deltas with the same acceptance outcome. No savings claimed without measurement.
- State: E3c papers abstract-only; ledger baseline not collected. Next: E3a (needs ledger export from Builder workflow, read-only).

### P4 Premature stall flag (gap G2)
- Objective: stall flagged only when state is unchanged and the owner is not live; never from elapsed time alone.
- Sources: none verified for premature-stall design ("When Agents Do Not Stop" https://arxiv.org/html/2607.01641 covers unbounded loops, the opposite problem). Hypothesis [H]: state-change + owner-liveness rule. Next: targeted search for liveness/heartbeat and progress-detection work in distributed systems and agent orchestration; if nothing applicable, stop this line and say so.
- Success: replay of the premature-stall case does not flag; a genuinely idle seat does.

### P5 Prior art in public systems (cross-cutting; feeds P1-P4)
- Objective: find working designs for handoff state, review gates, stall/liveness and token control, and judge which are worth adapting.
- Evidence ladder, recorded per source: (1) marketed claim (README/blog) < (2) examined implementation (read the code/version) < (3) tested behavior (run or replayed by us). Never present level 1 as level 3.
- Per source record: URL, commit/tag read, date checked, license (check the LICENSE file; code and docs licenses can differ), what it does for P1-P4, tradeoffs, applicability to a GitHub-centered seat-based launcher, evidence level.
- Reuse rule: take ideas and cite them. Copy code only if the license permits and attribution is kept; no private or proprietary content.
- Candidate list (license file read 2026-11-04; implementation NOT yet examined, so all are level 1):
  - langchain-ai/langgraph https://github.com/langchain-ai/langgraph - MIT. Look at: checkpointed state, interrupts/human review, stall handling.
  - OpenHands/OpenHands https://github.com/OpenHands/OpenHands - MIT. Look at: agent controller stuck detection, context condensation.
  - crewAIInc/crewAI https://github.com/crewAIInc/crewAI - MIT-style text seen (confirm). Look at: task handoff/context passing.
  - FoundationAgents/MetaGPT https://github.com/FoundationAgents/MetaGPT - MIT. Look at: role-structured documents as handoff artifacts.
  - openai/swarm https://github.com/openai/swarm - MIT. Look at: handoff-as-function pattern (lightweight, educational).
  - microsoft/autogen https://github.com/microsoft/autogen - root LICENSE seen is CC BY 4.0 (docs); code license not yet confirmed.
- Success: for P1 and P2 and P4, at least one examined (level 2) design compared with ours, with a written adopt/skip decision and reason; adoption only after a test.
- State: candidates listed, none examined. Next: read OpenHands stuck-detection and context condensation (serves P4 and P3), then LangGraph checkpoint/interrupt model (P1, P2).

## R&D loop (applies to every P)
1. Problem: an observed failure with evidence (incident, commit, log).
2. Research: papers and public systems (P5), evidence level recorded.
3. Bounded experiment: written before running: hypothesis, fixed baseline, one change, sample size, token/request budget, stop rule. Executable work goes through Builder/coordinator and file ownership; the Researcher writes proposals and analysis, not product code.
4. Measure: pre-declared metric, raw counts, baseline vs change. Small N is labeled anecdotal.
5. Decide: Reviewer sign-off on the same pinned commit, then adopt, reject, or park. Adoption is the coordinator's and Builder's change, not the Researcher's.
6. Record: every experiment gets a file in research/experiments/ (hypothesis, setup, result, decision), including negative and inconclusive results. A rejected idea stays on record with the reason.
Experiments need no extra budget or security authority: free tier only, no merges, no secrets in artifacts, published only through the agreed relay.

## Priority and cadence
Order: P2 and P1 (acceptance risk), P3 (user priority), P4 (needs sources first). P5 runs inside each: use it to supply level-2 examples.
Each cycle (daily, cost-aware, web tools only, no model calls): advance one open question, record a result or a stop reason, add new sources only if they bear on P1-P4. Report to coordinator only material insights, a stopped line, or a proposal ready for Builder/Reviewer. No digest.

## Limits
Benchmarks use frontier models via other providers; our free-tier models may differ. Preprints may change. No paid access used.
