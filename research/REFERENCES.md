# Research references (stable IDs)

Cite as [R#] with section/commit. "Read" = what the Researcher actually read on the date shown. Update the Read column when a source is read more fully.

| ID | Source | Class | Version/date | Read | Used for |
|---|---|---|---|---|---|
| R1 | Rethinking Verification in Agent Harnesses, https://arxiv.org/abs/2610.34577 (html https://arxiv.org/html/2610.34577) | PP | arXiv 2026-10-25, checked 2026-11-04 | Abstract, sec 3 (L3 definition), sec 5.3-5.4 | P2, P3: critic gains/cost (sec 5.4), critic input task+changes vs trajectory (sec 5.4), review depth/width (sec 5.4, Fig 4) |
| R2 | When Do Agent Loops Mistake Stagnation for Progress?, https://arxiv.org/abs/2607.25152 | PP, preliminary draft | arXiv 2026-07-27, checked 2026-11-04 | Abstract, intro, draft note, sec 3.16 (pilot scope). Results numbers (56%, 44%) read in the abstract only | P2: self-verdict gate weakness; scope limit: single agent pilot, generalization deferred |
| R3 | Benchmarking Task Takeover Across Agent Handoffs (HSC-Bench), https://arxiv.org/abs/2610.36523 (html https://arxiv.org/html/2610.36523) | PP, WWW 2027 listing | arXiv 2026-10-27, checked 2026-11-04 | Abstract, sec 1, 3, 4.1, 5.2 (structured state gains; line-F1 gain stated in sec 5.2) | P1, P3: structured handoff state |
| R4 | When Agents Do Not Stop (IAL-Scan), https://arxiv.org/html/2607.01641 | PP | arXiv 2026-07-02, checked 2026-11-04 | Intro, sec III (definition, threat model) | P4: NOT applicable to premature stalls (static detection of unbounded loops) |
| R5 | Why Do Multi-Agent LLM Systems Fail? (MAST), https://proceedings.neurips.cc/paper_files/paper/2025/hash/b1041e52d3be19f0a9bc491657488e4a-Abstract-Datasets_and_Benchmarks_Track.html ; code/data https://github.com/multi-agent-systems-failure-taxonomy/MAST | PR | NeurIPS 2025 D&B | Abstract only | Candidate incident taxonomy |
| R6 | Reviewer Capability Governs Rejection Targeting, Not Repair Skill, https://arxiv.org/abs/2609.04270 | PP | listing seen 2026-11-04 | Abstract only | P2, provisional |
| R7 | Self-Attribution Bias, https://arxiv.org/html/2603.04582v1 | PP | seen 2026-11-04 | Abstract only | P2, provisional |
| R8 | CTXAgent https://arxiv.org/abs/2610.34425 ; Context as an Environment https://arxiv.org/html/2608.21690 | PP | seen 2026-11-04 | Abstract only | P3, provisional |

Public systems (P5): record commit/tag, date, LICENSE file, evidence level (1 claim, 2 examined, 3 tested). None examined yet.
| ID | Repo | License file read 2026-11-04 | Level |
|---|---|---|---|
| S1 | https://github.com/langchain-ai/langgraph | MIT | 1 |
| S2 | https://github.com/OpenHands/OpenHands | MIT | 1 |
| S3 | https://github.com/crewAIInc/crewAI | MIT-style text, confirm | 1 |
| S4 | https://github.com/FoundationAgents/MetaGPT | MIT | 1 |
| S5 | https://github.com/openai/swarm | MIT | 1 |
| S6 | https://github.com/microsoft/autogen | root LICENSE is CC BY 4.0 (docs); code license unconfirmed | 1 |

Rules: each claim in findings/experiments carries [R#]/[S#] plus section or commit; each experiment file links back to the finding and source IDs; a claim whose source was read only at abstract level is marked "abstract only".

## Audit of research/findings/2026-11-04-initial-literature-scan.md (published b42f670)
- F1 numbers: matches R1 sec 5.4; add "[R1 sec 5.4, Fig 4]".
- F2 numbers (56%, 44%): abstract only [R2]; scope limit is in the draft note/sec 3.16. Mark "abstract only".
- F3: add "[R3 sec 5.2]"; state-builder model caveat is from R3 sec 3/4.1.
- Note has URLs but no section pointers or IDs: fix in the next bundle by adding [R#] tags.

## Work package map
RW1 handoffs: R3. RW2 review: R1, R2, R6, R7. RW3 tokens: R1, R3, R8. RW4 stall: none applicable (R4 excluded). RW5 prior art: S1-S6. RW6 routing: none.
