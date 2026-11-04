# RW3 baseline: token use by component in the one recorded multi-seat run

Author: Researcher agent (offline arithmetic on public records; no model call; no Nora/Eva authorship; pending Eva review). Date: 2026-11-04 ~17:32.
Source: usage logs .team/usage/{coordinator,builder,qc}.log and LOG.jsonl on branch live/requesty-tinylib-experiment @ e51fae66afce4d1ae2bd8ef2e2ac011c692b03ca (same run as E4). Model recorded in the logs: google/gemma-4-31b-it. All 7 calls outcome "ok".

## Data (per call, from the logs)
| time UTC | seat | prompt | completion | of which reasoning | total |
|---|---|---|---|---|---|
| 11:12:55 | coordinator | 430 | 338 | 265 | 768 |
| 11:13:18 | builder | 514 | 447 | 273 | 961 |
| 11:19:52 | coordinator | 804 | 564 | 494 | 1368 |
| 11:20:15 | qc | 891 | 515 | 410 | 1406 |
| 11:20:54 | coordinator | 1015 | 1255 | 1181 | 2270 |
| 11:21:25 | builder | 1026 | 892 | 804 | 1918 |
| 11:21:41 | coordinator | 1151 | 397 | 324 | 1548 |
Totals: prompt 5,831; completion 4,408; reasoning 3,751; total 10,239 (sums re-added and match).

## Derived (arithmetic on the table)
- Prompt = 57% of all tokens; completion 43%; reasoning tokens = 85% of completion and 37% of all tokens.
- Visible completion (completion minus reasoning) = 657 tokens = 6.4% of all tokens. The handoff text in LOG.jsonl is 43-288 characters per handoff.
- Prompt size grows from 430 to 1151 tokens over the 7 calls (+721, about +120 per call on average; not uniform).

## What this suggests [H, from one run, one model]
- Composition only, not measured compression potential. Visible output is 6.4% of tokens, but handoff text also feeds later prompts, so the 57% prompt share may contain repeated handoffs. This run did not split prompt tokens by source (system, task, history, repeated handoffs). Whether shorter handoff wording would save more than 6% is NOT measured. Status: pending review before any public recommendation.
- If the provider exposes a control for reasoning effort for this model, it may be a bigger lever than wording; UNVERIFIED (not checked in provider docs).
- Prompt growth supports the rolling-history/pinned-requirements idea (RW3) and a structured handoff (RW1) that replaces re-sending history, but this run shows only the growth, not the saving.

## Limits
N=1 run, 7 calls, tiny task (tinylib.add); one model; reasoning share varies with model and task; the logs count tokens per call but not per message type beyond the seat. Not applicable to Groq gpt-oss-120b batches (different usage records, executor rounds). Needs Eva check of table vs logs (the raw logs are public at the pinned commit).
