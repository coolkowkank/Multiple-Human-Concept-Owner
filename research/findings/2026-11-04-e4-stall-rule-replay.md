# E4 (WP8b): offline stall-rule replay, v2 (fair comparison)

Status: PARTIAL OFFLINE RUN of the harness on one recorded history; design otherwise unrun. Author: Researcher agent (no Nora/Nemotron/Eva authorship; pending Eva review). Date: 2026-11-04.
Links: finding findings/2026-11-04-rw4-liveness-progress-design.md [R9, S7]; REFERENCES.md; plan RW4. Supersedes the 16:40 draft (which used self-authored fixtures and unequal windows).

## Pinned sources (read 2026-11-04 ~16:41)
- launcher/supervisor.py last changed at commit 0fa083a0585f6d8bb4ee9f1e7c82fa8efe06a0e0 on live/builder-deadlock-fix (branch head 2024e2d3f12dcfbfa89c78e992027f681d69b118). Contents read: docstring (stall = "no bus write within stall_timeout"), `_check_stall` (compares only against state["turn_since"]), `poll=5`, default `stall_timeout=900`, `_stalled_seats` set that is never cleared.
- launcher/bus.py last changed at commit 37eb7352cde19ef0ef4f0dc928c600d367620bce (same branch): `append_log(seat, kind, body, turn_seq)`.
- Recorded history: branch live/requesty-tinylib-experiment @ e51fae66afce4d1ae2bd8ef2e2ac011c692b03ca, .team/LOG.jsonl (15 rows), copied here as recorded-requesty-LOG.jsonl, sha256 5ba8359c84892268f71a8211c60c9860895cedeb4d509042df42d52f3861f852. Context: docs/proposals/groq-deadlock-fix.md.

## Rules (equal 900 s window for all; poll 5 s)
- A_bug: current behaviour in a UTC+2 container (age inflated by 7200 s).
- A_fixed: age since turn_since in UTC (the UTC fix).
- B: age since max(turn_since, last progress event by the holder) >= window, only if running, not in a declared wait, seat reachable.
- Declared wait: NOT defined from runtime facts. The launcher source I read has no wait state (status values seen: forming, running, done). So B's wait exemption is a proposal that would need a new state; the replay does not use it.

## What the replay shows (python3 e4_replay.py, deterministic)
- Validation of the replay model: A_bug replays to flags at 11:12:59 builder, 11:19:29 coordinator, 11:19:54 qc; the log has supervisor "stall" rows at 11:12:59, 11:19:30, 11:19:55. Matches within 1 s (poll alignment), including the once-per-seat suppression from `_stalled_seats`.
- A_fixed and B: zero flags. Handoff-to-handoff times: 23, 394, 24, 38, 31, 16 s; the 394 s gap is the null-handoff period (turn None, which the stall path does not evaluate; it is a routing failure, not a stall). Max active turn 38 s versus the 900 s window.
- Therefore the recorded history supports ONE conclusion: the UTC bug caused 3 false stall flags (confirmed by replay reproducing the log), and the UTC fix removes them. It does NOT discriminate A_fixed from B.

## Truth labels (declared)
- Rule: a flag is false if the holder's age since its turn start, computed in UTC, is under the window at flag time. Deterministic from the log, not an independent human judgment. Independent check wanted: Eva or a human spot-check of the three flagged turns against the log. True stalls in this history: none known (the 394 s hang was a null-turn deadlock).

## Progress writes during long calls (open question, now answered for this data)
In the recorded run each turn is one model call; seats wrote their only log row (handoff) at completion; usage logs (.team/usage/*.log) have one entry per call at completion. No mid-turn progress events exist. So rule B's progress signal adds nothing over A in this data, and B would need a new intra-turn heartbeat/progress write (Builder work) before it can differ from A. Whether longer, multi-call turns write events is unknown: no such recorded history exists on the branches I checked.

## Real data available and missing
Available: 1 multi-seat bus history (above). live/groq-dev-3 and review/groq-dev-3 have a 1-row LOG (no usable timeline). Other branches checked (groq-dev-4, reviewer-skip-guard, team-launcher, main, records branches) have no .team LOG/STATE files or only batch transcripts, which are executor request rounds, not seat turns.
Missing: any history with a genuinely stalled seat, any long multi-call turn, any declared wait; independent truth labels.

## Revised experiment
E4a (done, offline): replay confirms the timezone false-stall mechanism and its removal by A_fixed (N=1 history, 3 false flags, anecdotal).
E4b (blocked on data): compare A_fixed vs B on histories that contain (i) long multi-call turns, (ii) a real stall, (iii) a wait. Needs new recorded runs or an intra-turn progress write first. Do not choose B over A_fixed on current evidence.
Next-version candidate [H]: keep A_fixed; add a per-turn progress/heartbeat log write only if long-turn false stalls appear in future runs; define wait states from actual runtime features (e.g. ledger pacing sleep) before exempting them.

## Limits
N=1 history; 3 flags; truth labels derived from the same log; replay assumes holders inferred from consecutive handoffs (derived, not stored in the log); R9 and S7 are proposal/vendor docs. Re-pin SHAs before citing lines.
