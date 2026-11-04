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
- Source [R2]: When Do Agent Loops Mistake Stagnation for Progress?, [PP] https://arxiv.org/abs/2607.25152 (full PDF text read and independently verified 2026-11-04, incl. sec 3.16 and 4.2, by an independent verifier reading the PDF directly - not Eva-model authorship. The earlier "56% also in the intro" remark (X1) was NOT FOUND in the source and is dropped)
- Finding: in a 54-cycle pilot the agent claimed improvement in all 54 cycles; 56% of ALL 54 cycles had measured delta zero or below (that share is over all cycles - it is NOT the mirage rate, which the paper defines over evaluator-accepted cycles, sec 3.15). The strongest in-band judge had 44% of its ACCEPTED cycles be real-world regressions, and it also rejected 38% of real improvements (37.5% in the body text). The stagnation gap closed when success was verifiable from the artifact.
- Limits [R2 draft note, sec 3.16, 4.2]: preliminary single-deployment pilot with one real frontier agent; pre-registration not completed (H3/HA2 not run); the "zero out-of-band mirage" result is a DEFINITION scope, not an empirical measurement; auxiliary mechanisms (append-only logs, file handoff) are design notes, not individually validated.
- Use: supports pushes gated on pinned HEAD + real test output, not model self-report.

## F3 - Structured handoff state (G1, G4)
- Source: Benchmarking Task Takeover Across Agent Handoffs (HSC-Bench), [PP] https://arxiv.org/abs/2610.36523 (html read)
- Finding [R3 sec 5.2, Table 6]: structured state improved repo evidence recovery for all six receivers, line-F1 gains 0.114-0.162; five of six receivers also improve in continuation (Kimi is the exception).
- Limits [R3 sec 3.3/4.1/5.2, Table 6]: bootstrap intervals are above zero only for the all-tasks and earlier-only-evidence aggregates; small subgroups cross 0. State and recent-transcript contexts are matched at the same visible token count, so the gain is not from more tokens; absolute line-F1 stays low (0.189-0.263 with state). State built by a fixed model (GPT-4.1); benchmark tasks, not multi-seat launcher runs - not evidence that our launcher handoff works.
- Experiment E2 [H]: fixed schema (base/head, changed files, test output, failed attempts, open findings, next owner) + validator rejecting empty handoffs. Replay the null-handoff incident; compare tokens vs free text.

## Open / not supported
- G2 stall detection: no verified source. [R4] "When Agents Do Not Stop" https://arxiv.org/html/2607.01641 (read: intro, sec III) addresses unbounded loops, not premature stalls. [H] judge stall on state change + owner liveness, not elapsed time. Untested. Experiment E3: replay premature-stall case.
- Provisional, abstract only [R6, R5, R7]: https://arxiv.org/abs/2609.04270 ; https://arxiv.org/abs/2603.04582 ; MAST https://proceedings.neurips.cc/paper_files/paper/2025/hash/b1041e52d3be19f0a9bc491657488e4a-Abstract-Datasets_and_Benchmarks_Track.html

