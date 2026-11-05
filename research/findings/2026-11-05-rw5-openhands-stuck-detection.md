# RW5 level-2 note: OpenHands stuck detection vs our RW4 (qualitative loops)

Date: 2026-11-05. Evidence level: **2 (source read at a recorded commit). Nothing was run or replayed: no level-3 claim.**
Scope: one comparison. No code adopted, no model or provider call made.

Relation to existing work: findings/2026-11-04-rw5-prior-art-stall-and-gates.md N1 read the same file from the UNPINNED branch main and recorded no commit. This note pins it to one commit and adds the side-by-side and adopt/skip decisions. Citation gate: every claim here comes from the files read at the commit below (my own read, not model memory); the coordinator's semantic check against the source is still required before publication.

## Source examined
- Repo: https://github.com/OpenHands/software-agent-sdk
- Commit: `c3985a4c1fc8ecb8fdc196610754a82aa0e3464a` (2026-10-29, "fix(sdk): distinguish validation loops from incremental repairs (#6278)"). It was the most recent commit returned by the GitHub commits API for that file path when I read it (2026-11-05); upstream may have moved since, and this note examines this pinned commit only.
- Files read at that commit: `openhands-sdk/openhands/sdk/conversation/stuck_detector.py` (about 515 lines) and `StuckDetectionThresholds` in `openhands-sdk/openhands/sdk/conversation/types.py`.
- License: `LICENSE` at the same commit starts "MIT License / Copyright (c) 2026 OpenHands contributors". We cite ideas only. Copying code would need MIT attribution and is not proposed.
- Not read: the code that calls the detector, the older `openhands/controller/stuck.py`, tests, docs pages. How the result is acted on is therefore unknown to us.

## What the detector does (read from source)
It scans a bounded window (20 events, only events after the last user message) of one agent's event stream and says "stuck" on any of:
1. Same action and same observation, `action_observation` = 4 times in a row (default).
2. Same failing action with an error each time; `action_error` = 3 default. Streak counts model responses, not parallel calls. Invalid calls are compared by validated arguments with some fields stripped, and different validator repairs at one location are not counted as a loop (the commit above).
3. Monologue: `monologue` = 3 consecutive agent messages with no user message or tool step between.
4. Alternating A,B,A,B: takes the last N actions and the last N observations (N = `alternating_pattern`) and requires action[i] equal to action[i+2], and the same for observations. The unit is N action/observation pairs, not N events.
5. Context-window error loop: the function is a stub that returns False (TODO in source). Not a working detector.
Equality ignores ids and metrics and compares content (action, observation, error text). A single nudge string is produced once per action-error streak (deduped by the error event id). Thresholds are configurable; defaults in `StuckDetectionThresholds`: action_observation 4, action_error 3, monologue 3, alternating_pattern 6.

## Our RW4 today (our own repo, not this note's evidence)
Delivered and independently accepted as parts: stall = elapsed time at a turn, with a bounded declaration (live/unknown/overrun), spending seats never auto-restarted or replayed. That answers "is the seat alive?". It does not answer "is the team looping while alive?". A seat can finish turns on time and hand back and forth with no change in the work. We have no detector for that. Also not done: rehearsal runs, live readiness, an unattended-operation claim.

## Comparison
| OpenHands idea | Applies to us? | Decision |
|---|---|---|
| Repetition = equal content across N consecutive steps, ids ignored | Yes in shape. Our steps are seat handoffs, and each handoff row can carry a handoff/v1 record with observed path/blob sets and a claim hash (length and sha256 only). Hash equality gives the same test without storing model text. | **Adopt the idea** as a proposal [H]: flag N consecutive handoffs whose observed set and summary hash repeat. |
| Alternating A,B,A,B | Yes: two seats passing work back and forth maps directly to this pattern. | **Adopt the idea** (same signal, period 2). |
| Window bounded and reset by a user message | Yes: reset on an operator or gate resolution, and window bounded so cost is fixed. | **Adopt the idea.** |
| One nudge per streak, deduped by the triggering event | Yes: matches our one gate per stalled identity. | **Adopt the idea.** Our action would be a gate for an operator, not a message to the model. |
| Configurable thresholds (defaults 4, 3, 3, 6) | Defaults are theirs with no evidence for our workload. | **Adopt configurability; skip their numbers.** Any threshold of ours must be set from our own rehearsal data (not yet collected). |
| Parallel calls counted as one response | No parallel tool calls in our turns. | **Skip.** |
| Monologue (agent message streak) | Our turns end in a handoff, so it has no equivalent. | **Skip.** |
| Context-window error loop | Stub in the source. | **Skip.** Nothing to learn from it. |
| Nudge text sent to the model | Would add to the model contract and change prompts. | **Skip.** Out of scope for us. |
| Their stuck handling (unknown here) | Not read. | **No decision.** For spending seats we never terminate or replay automatically. |

## Limits
- A repeated hash means "same observed files and same claim", not "no progress": legitimate retries after a rejected review can repeat. Treat a hit as a prompt for an operator decision, never as proof of a loop.
- Their thresholds were tuned for single-agent tool loops with another model stack. Level 2 only; we have not run their detector or ours on any trace.
- Handoff records from lanes without a record (no_record) give no signal, so a detector would be silent there.
- This note does not change acceptance status: RW4 stays "components delivered, qualitative-loop detection open, rehearsal and live readiness not done".

## Proposed next step (a proposal for the coordinator, not a commitment)
A read-only function over existing LOG rows with a declared bound that returns "repeat candidate" with the matching turn_seq values, tested on scratch fixtures that include a legitimate-retry case it must NOT flag. No wiring and no automatic action until reviewed.
