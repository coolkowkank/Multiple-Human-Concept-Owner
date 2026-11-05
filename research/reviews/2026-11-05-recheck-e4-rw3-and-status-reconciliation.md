# Independent recheck of E4 and RW3, plus RW status reconciliation (2026-11-05)

Who: the concept-owner product lane (an AI agent, not the Researcher seat, not Eva). **This is not an Eva verdict and does not close the "pending Eva review" label on those findings.** No model or provider call. All numbers below come from files read at the pinned commits named here.
Scope: recompute two published findings from their own recorded data, then compare PLAN.md and README status lines with what exists on `Research_lab` at b0e4ebf.

## 1. E4 replay (findings/2026-11-04-e4-stall-rule-replay.md)
- Re-ran `python3 research/findings/e4_replay.py` at b0e4ebf. Output matches the finding: A_bug flags 11:12:59 builder, 11:19:29 coordinator, 11:19:54 qc (observed log stall rows 11:12:59, 11:19:30, 11:19:55); A_fixed none; B none; handoff-to-handoff seconds 23, 394, 24, 38, 31, 16, max 394 against the 900 s window.
- `sha256(recorded-requesty-LOG.jsonl)` = 5ba8359c...f852, 15 LOG lines (7 of them are kind=handoff rows), as stated. The file is byte-identical to `.team/LOG.jsonl` on `live/requesty-tinylib-experiment` at e51fae66afce4d1ae2bd8ef2e2ac011c692b03ca.
- Not rechecked: the supervisor.py source claims at commit 0fa083a, the holder inference (derived from consecutive handoffs), and the truth labels (derived from the same log). The finding's own limits stand: N=1 history, A_fixed and B not discriminated.

## 2. RW3 baseline (findings/2026-11-04-rw3-token-baseline-requesty-run.md)
- Read `.team/usage/{coordinator,builder,qc}.log` at e51fae6 and rebuilt the table. All 7 rows match (time, seat, prompt, completion, reasoning, total), all outcome "ok", attempt 1, model google/gemma-4-31b-it. Per-row prompt + completion = total.
- Totals: prompt 5,831, completion 4,408, reasoning 3,751, total 10,239. Matches.
- Derived: prompt 56.9% (note: 57%), completion 43.1% (43%), reasoning 85.1% of completion (85%) and 36.6% of all (37%), visible completion 657 tokens = 6.4%. Prompt grows 430 to 1151 (+721, about 120 per call average). All match.
- Handoff text lengths in the recorded LOG (15 lines, 7 handoff rows): 43, 64, 64, 66, 222, 255, 288 characters, consistent with the note's "43-288".
- `cost` is 0 in every usage record. That is the provider-reported field, not independently verified cost.
- Not rechecked: the note's two [H] ideas stay as the note labels them (reasoning-effort control UNVERIFIED in provider docs; the prompt share was not split by source). The recheck confirms arithmetic only, not the interpretation.

## 3. Status reconciliation (delivered / stale / real gap)
Sources: research/PLAN.md and research/README.md at b0e4ebf, the README table on `live/operator-done`, the findings list on `Research_lab`, and `live/rw5-openhands` 9a1762e.

| Item | What the docs say | What exists (evidence) | Class |
|---|---|---|---|
| PLAN.md header: "all WPs at S0-S2, no experiment has run" | stale | E4a offline replay exists (findings/2026-11-04-e4-stall-rule-replay.md, rerun above) | **Stale** |
| RW4 in PLAN.md: "S0 (no finding)" | stale | design finding (2026-11-04-rw4-liveness-progress-design.md) and E4a published | **Stale** |
| RW5 in PLAN.md: "S0-S1, none examined" | stale | a pinned level-2 note on OpenHands at upstream commit c3985a4 exists on `live/rw5-openhands` (not on Research_lab); its source claims were checked against the pinned file by the reviewer lane. It covers RW4 only. The older N1 text on Research_lab (unpinned branch main, no commit recorded) is not relied on here | **Stale**, but see next row |
| RW5 acceptance ("RW1, RW2 and RW4 each have a level-2 design compared with ours, adopt/skip") | open | only the RW4 slice (OpenHands) has a written adopt/skip. Nothing for RW1 or RW2 | **Real gap** |
| RW6 in PLAN.md and the README table: "S0 placeholder, not started" | stale in form | a note exists (2026-11-04-rw6-model-selection-under-fixed-harness.md), but it covers model selection under a fixed harness (preprint claims, none reproduced). PLAN's RW6 question is rate-limit-aware provider routing | **Stale label and a scope mismatch**: the routing question has no finding |
| RW3 | baseline published, savings unmeasured | arithmetic rechecked above | **Delivered (baseline, N=1)**; real gap: per-source prompt split and any matched comparison with equal acceptance outcome |
| RW1 | spec published; handoff validator is product code | spec exists. The product-side handoff record is a separate lane's work. I did not verify the PLAN acceptance items (null-handoff replay rejected; N rehearsal handoffs with zero manual recovery) against the research record | **Delivered as design**; acceptance not verified here |
| RW4 | E4b blocked on data | no recorded history with a real stall, a declared wait or a long multi-call turn exists. Scripted mock runs are not that | **Real gap (data)** |
| "Pending Eva review" on RW1 spec, RW3 baseline, E4 | open | this note rechecks two of them mechanically. Eva is blocked on a route | **Real gap**: semantic citation review of the RW1 spec and the RW4 design (R9, S7, S8) is not done by anyone yet |

Edits this implies, for the Researcher/coordinator to decide (I did not change PLAN.md or README): refresh the PLAN.md header and the RW4, RW5 and RW6 state lines to point at the files above; rename or split RW6 so the routing question and the model-selection note are not confused.

## Limits
Mechanical recheck of recorded data only. N=1 history and N=1 run. Nothing here tests a rule on new data or adopts anything.
