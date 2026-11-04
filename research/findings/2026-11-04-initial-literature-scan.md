# Initial literature scan (Researcher)

Author: Researcher role (Instinct research agent). Date: 2026-11-04.
Evidence classes: [PR] peer-reviewed, [PP] preprint, [H] hypothesis (untested here).
References: see ../REFERENCES.md (IDs R#). Read-depth is stated per claim.
Papers are not proof our implementation works. Each item needs a test and Reviewer sign-off before adoption. Builder owns product code.

Observed project gaps: G1 manual null-handoff recovery; G2 premature stall flag; G3 push/acceptance before independent verification; G4 token cost of handoffs and history.

## F1 - Separate critic reviewing task + changes (G3, G4)
- Source [R1]: Rethinking Verification in Agent Harnesses, [PP] https://arxiv.org/abs/2610.34577 (read: abstract, sec 3, sec 5.3-5.4)
- Studied: 17 designs, 7 frontier coding models, Terminal-Bench, SWE-bench Verified, VisualBench.
- Finding [R1 sec 5.4, Fig 4]: a separate critic in fresh context raised accuracy +5.9-9.5 pts (TB) and +3.9-6.6 (SWE) at 1.13-1.25x / 1.00-1.04x cost. Critic input of task requirements + changes beat full trajectory (trajectory critics cost 29-43% more). One critic is a good default; extra rounds/critics show diminishing returns.
- Limits: frontier models, one provider, benchmarks. Fresh-context and separate-model effects are not isolated by what was read.
- Experiment E1 [H]: Reviewer receives spec + diff + test output only. Compare findings and tokens vs history-fed review.

## F2 - Self-verdict gates degrade (G3)
- Source [R2]: When Do Agent Loops Mistake Stagnation for Progress?, [PP, preliminary draft] https://arxiv.org/abs/2607.25152 (read: abstract, intro, draft note, sec 3.16; the 56%/44% figures are from the abstract only, abstract-only claim)
- Finding: in a 54-cycle pilot, 56% of agent-claimed improvements had zero/negative measured delta; an in-band judge accepted 44% regressions. Gap closed when success was verifiable from the artifact.
- Limits [R2 draft note, sec 3.16]: single agent, pilot; authors defer multi-model generalization.
- Use: supports pushes gated on pinned HEAD + real test output, not model self-report.

## F3 - Structured handoff state (G1, G4)
- Source: Benchmarking Task Takeover Across Agent Handoffs (HSC-Bench), [PP] https://arxiv.org/abs/2610.36523 (html read)
- Finding [R3 sec 5.2]: structured state improved repo evidence recovery for all six receivers and continuation for most.
- Limits [R3 sec 3.3/4.1]: state built by a fixed model (GPT-4.1) in the benchmark; benchmark tasks.
- Experiment E2 [H]: fixed schema (base/head, changed files, test output, failed attempts, open findings, next owner) + validator rejecting empty handoffs. Replay the null-handoff incident; compare tokens vs free text.

## Open / not supported
- G2 stall detection: no verified source. [R4] "When Agents Do Not Stop" https://arxiv.org/html/2607.01641 (read: intro, sec III) addresses unbounded loops, not premature stalls. [H] judge stall on state change + owner liveness, not elapsed time. Untested. Experiment E3: replay premature-stall case.
- Provisional, abstract only [R6, R5, R7]: https://arxiv.org/abs/2609.04270 ; https://arxiv.org/abs/2603.04582 ; MAST https://proceedings.neurips.cc/paper_files/paper/2025/hash/b1041e52d3be19f0a9bc491657488e4a-Abstract-Datasets_and_Benchmarks_Track.html
