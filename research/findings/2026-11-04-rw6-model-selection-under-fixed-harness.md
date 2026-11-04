# RW6: How model selection affects performance under a given harness

Literature note, 2026-11-04. Every number below is what the cited preprint reports. None of it was reproduced here, and peer-review status of these preprints is not independently established. This note measures nothing about this project and does not pick any model. Each source was checked against its original PDF by an independent reader.

## Bottom line

Fixing the harness does not remove model differences. Differences depend on the harness and the tasks, and model rankings can reverse across harnesses. Scores, valid completion, tokens and cost should be measured separately. Results from swapping the harness are not estimates of the gain from swapping the model.

## Evidence

**M1. arXiv 2610.00917** (Table 1, section 4.1; methods p3). Terminal-Bench 4, same 63 tasks, models Claude Opus5 and GPT-6 Astra.
- OpenHands: Claude 36/63 (57.14%), GPT 31/63 (49.21%), Claude +7.94 pp.
- PI: Claude 19/63 (30.16%), GPT 38/63 (60.32%), Claude -30.16 pp.
- One observed crossed interaction. It is not evidence of repeatability or significance. Terminal-Bench 4 is binary; other benchmarks in the paper allow partial reward, so not every score is a solve rate. The best harness changes with the benchmark for 4 of 5 models (Table 3).
- Cost (section 4.3): GPT on PI $4.66 per task at 60.32% versus DSH $19.94 at 52.38%. These are OpenRouter API prices including auxiliary calls, not billed savings.

**M3. arXiv 2610.04433** (section 4.2, Fig 2, Appendix F, Table 1). Hard-45 task subset.
- Median task-outcome discordance: 13% for reruns, 13% for harness swaps, 22% for model pairs sharing a harness (up to 56%). Over 7 rerun pairs of the 5 crossed models the median rerun figure is 16%. The 22% counts tasks whose outcome flips in either direction. It is not a 22 percentage-point score gain.
- It is not an exact causal decomposition, a universal noise floor or a significance cutoff.
- Equivalence was tested within +-5 pp only for Claude Code versus mini-SWE-agent on two Qwen models, with paired task counts of 444 and 445 as reported by the checker. It does not bound all pairs. OpenCode loses up to 9.2 pp. The cost gap of up to about 3x is repriced list-price usage, not billed.

**M5. arXiv 2609.11987** (Tables 3-5, sections 2.3). Same model, native versus neutral harness.
- Average difference unresolved: Opus -1.25 pp, CI [-10, +7.5]; GPT +1.25 pp, CI [-4.4, +6.9]. This is not equivalence. The paper says it does not establish equivalence and gives no transportable probability.
- The 80-task pool was chosen from 256 by an outcome-informed screen that raised discordant tasks from 9.4% to 30%. The repository (n=61) versus contest (n=19) sign split was made after seeing the results: Opus -9.0 pp CI [-17.2, -0.8] on repository tasks, contest +23.7 pp. It is post hoc and exploratory.
- The +1.25 pp GPT figure is a pass/fail task mean. Counting all non-pass outcomes, the checker reports GPT at about +0.6 pp.
- A private task suite does not prove the data is contamination-free. The cost ratios have unresolved Opus billing. This is same-model harness evidence, not model-selection evidence.

**M2. arXiv 2609.32459** (sections 4.4 and 5.1.1, Fig 5, Table 4).
- Fixed OpenCode, Qwen3-Max to Qwen3.7-Max: tool calls per task 39.87 to 72.23.
- Separately, OpenCode's advantage over mini-SWE-agent fell from about 6 pp to 2.67 pp across those two models. The DeepSeek trend is non-monotonic. The introduction's leaderboard gaps (19.4 and 22.8 pp) are cited from elsewhere, not from this experiment.

**M6. arXiv 2610.32483** (introduction p2, section 4.1 pp5-6, section 5.3 p8). 4 models by 4 harnesses on 4 benchmarks (3 by 4 on two of them), 4 repetitions. Harness rankings vary by model and benchmark. Task score and valid completion rate can favor different pairings. Valid completion rate (VCR) is a normal evaluable completion, irrespective of correctness. The benchmarks cover tool use, planning, multimodal work and artifact handoff, not only coding. 52,168 trajectories include native and stress settings.

**M7. arXiv 2608.26218** (Table 2, sections 4.1-4.2). A harness treatment (mechanical shortening plus stalled-work handling) raised the fraction of failing tests repaired (F2PF) from 28% to 49% on 169 tasks at a 20,480-token window; solves rose 43 to 72. F2PF is not a pass rate. This is a harness effect, not model selection.

## Not used

- arXiv 2607.22585 (claims of about 40x tokens per solved task): internal inconsistencies. The abstract says the largest-gap interval excludes zero while section 4.1 gives -8 pp, CI [-18, 0], and solved counts in Tables 2 and 4 disagree. No quantitative claim is taken from it until reconciled.
- Dropped wording: "harness gaps are small at frontier level", "any single-run model comparison is inside noise", "all studies use coding benchmarks".
- Not read: arXiv 2610.32131. A claim that weaker models are more harness-sensitive is secondhand and stays a hypothesis.

## Hypotheses for a project (nothing measured here)

- H1: a model chosen for a role should be checked inside the same harness it will run in. Rankings from other harnesses may not transfer (M1).
- H2: track task completion, reference accuracy, valid completion (no empty handoff or timeout) and prompt, reasoning and visible tokens as separate measures.

## If an experiment is run later

Pin the launcher version. Use paired outcomes per task. Declare scoring and timeout handling in advance. Record versions and budgets. Report per-cell rerun variation. A gap beyond the rerun range is not a significance test, and 3 repeats are not a power guarantee. A non-significant result means no resolved difference at that precision, not equality. Request counts cannot be estimated until tasks and turns per task are fixed.

## Sources

- https://arxiv.org/abs/2610.00917
- https://arxiv.org/abs/2610.04433
- https://arxiv.org/abs/2609.11987
- https://arxiv.org/abs/2609.32459
- https://arxiv.org/abs/2610.32483
- https://arxiv.org/abs/2608.26218
- https://arxiv.org/abs/2607.22585 (not used)
