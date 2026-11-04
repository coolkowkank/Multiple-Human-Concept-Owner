# WP8a: F2 and F3 full-text source check (Researcher agent, 2026-11-04 17:5x EET)
Status: independently VERIFIED 2026-11-04 - an independent verifier (not the Eva seat model) read both full PDFs (R2 sec 3.16/4.2; R3 Table 6 raw rows) and confirmed every proposed correction, with two small refinements (56% is over all 54 cycles, not the mirage rate; 37.5% body vs 38% abstract for rejected improvements). Corrections applied to 2026-11-04-initial-literature-scan.md in the same commit. Original note below, author text unchanged. Fetched with the coordinator web fetch tool; no model calls.
Frozen criterion (progress README line 20): citations resolve, key numbers match sources, class/limits/proposed experiment labelled. F1 was already checked (Eva review 1). This note covers F2 and F3.

## F2 = R2, arXiv 2607.25152 (PDF https://arxiv.org/pdf/2607.25152, fetched OK, ~50 KB text)
Read: abstract, "Draft note", sec 1 and 1.1-1.2 (intro), sec 2-3 partial. Sec 3.16 heading found but its body was cut off in the fetched text (only "The measurements reported in this p"). Sec 3.16 text is NOT read; the scope limit rests on the Draft note.
| Published claim | Source check | Verdict |
| 54 cycles, agent claimed improvement in all | Abstract: "claimed its change was an improvement in all 54 cycles" | MATCH |
| 56% of cycles measured delta zero or below | Abstract: "56 percent of those cycles had a measured delta of zero or below" | MATCH |
| In-band judge accepted 44% regressions | Abstract: strongest in-band judge "accepted cycles of which 44 percent were real-world regressions and rejected 38 percent of real improvements" | MATCH, wording fix: 44% of ACCEPTED cycles were regressions; also state 38% of real improvements were rejected |
| Gap closed when success verifiable from artifact | Abstract: mirage "vanished to 0", gap within registered threshold (H2) | MATCH |
| Preliminary single-deployment pilot, generalization deferred | Draft note: preliminary draft, controlled pilot plus anonymized single-deployment field observation, generalization to multiple models and tasks deferred | MATCH (Eva C5 SUPPORTED) |
| X1: "56% also appears in the intro" | Searched fetched text: 56 appears only in the abstract. Intro sec 1/1.1 does not state it | NOT FOUND. Remove the phrase from the artifact |
Extra limits from the paper: one real frontier agent, pilot scale (sign-only variant means 110.0 vs 113.0), auxiliary mechanisms (append-only logs, file handoff) are "design notes ... not individually validated". Do not cite those as measured.

## F3 = R3, HSC-Bench, arXiv 2610.36523 (HTML https://arxiv.org/html/2610.36523; PDF fetch returned no content)
Read: intro, sec 3 (task construction), sec 4.1, sec 5 (results, 5.2), Table 2 and Figure 4 captions. Not read: appendices, Table 6 raw rows.
| Published claim | Source check | Verdict |
| Structured state improved repository recovery for all six receivers | Sec 5.2: "improves repository evidence recovery across all six receivers", line-F1 gains 0.114-0.162, repo-level bootstrap intervals above zero | MATCH; add the range |
| Continuation improved for most | Sec 5.2: five receivers also improve in overall mean score | MATCH ("five of six") |
| State built by fixed model GPT-4.1 | Sec 3 and 4.1: GPT-4.1 builds summaries and structured state, no access to reference annotations | MATCH |
New limits to add: (1) state and recent-transcript contexts are matched at the same visible token count, so the gain is not from more tokens; (2) absolute line-F1 stays low (0.189-0.263 with state), so the gain is relative; (3) gains are uneven: 91 of 300 repo tasks improve for all six receivers, 48 of 739 continuation tasks do; (4) path retention 12.6% (recent) vs 93.0% (state), earlier-only evidence 0% vs 92.7%; (5) tasks are benchmark tasks, not multi-seat launcher runs. Not evidence that our launcher handoff works.

## Coverage of Eva audit
Eva reviews 1 and 2 covered 14 claims (12 supported, 1 partial, C5 resolved after PDF). Those verdicts rest on coordinator-fetched passages. They do not cover the details above (38% rejection, X1 absence, matched-token limit). The loop is closed for that publication round but is not a standing pass. Eva should review this note.

## What remains for WP8a (who)
1. Eva: audit this note's F2/F3 rows against coordinator-fetched passages (R2 sec 3.16 body and R3 sec 5.2 Table 6 are the missing reads).
2. Coordinator/executor: apply the F2 wording fix and drop X1 in the published scan; publish this note.
3. Researcher: add the R3 matched-token limit to REFERENCES once reviewed.
No experiment data needed (WP8b is separate).
