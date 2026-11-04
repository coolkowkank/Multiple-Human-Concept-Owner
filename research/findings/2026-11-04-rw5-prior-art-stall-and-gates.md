# RW5 prior-art notes: stall/loop detection and durable human gates

Author: Researcher role. Date: 2026-11-04. Source IDs per research/REFERENCES.md. Evidence levels: 1 documented claim, 2 code read, 3 tested by us. Nothing here was run by us.

## N1 OpenHands stuck detector [S2, level 2 partial, serves RW4/RW3]
- Code: https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/conversation/stuck_detector.py (read 2026-11-04, branch main, commit SHA not captured: re-pin before citing lines). Docs: https://docs.openhands.dev/sdk/guides/agent-stuck-detector . License MIT (LICENSE file read).
- Observed in code/docs: stuck is judged from repeated content inside a scanned window of 20 events after the last user message (identical action+observation pairs, repeated action errors, monologue, alternating pairs), compared on semantic content not IDs. No wall-clock rule seen in what I read.
- Applicability: supports state-based judgments for RW4 [H]. It detects over-repetition, the opposite of our premature stall; it has no owner-liveness notion. Default thresholds not verified in code.

## N2 LangGraph interrupts and checkpointers [S1, level 1: official docs only, code not read; serves RW1/RW2]
- Docs: https://docs.langchain.com/oss/python/langgraph/interrupts , https://docs.langchain.com/oss/python/langgraph/checkpointers (read 2026-11-04). License MIT (LICENSE file of langchain-ai/langgraph).
- Documented: state is checkpointed at each step under a thread ID; a human-approval pause (interrupt) resumes from that persisted state; resume re-runs the node from its start, so side effects before the interrupt should be idempotent; if one node fails in a step, writes from nodes that finished are kept as pending writes and not redone on restart; looping interrupt calls inside one node is discouraged because each resume replays them.
- Applicability [H, untested]: (a) RW1: preserve partial completed work when one seat's turn fails, instead of discarding it, supports "keep the original handoff record". (b) RW2/escalation: the human gate and the consecutive-failure counter should live in persisted state, and the reissue/escalation step should be safe to run twice. This lines up with the current counter-reset and escalation-test follow-ups but is a design idea, not evidence that the current fix is right or wrong.
- Limits: documentation claims; LangGraph's graph model differs from a git-seat launcher.

## Gaps
RW4 still lacks a liveness/heartbeat source. Next: look for owner-liveness designs (distributed-systems heartbeat/lease literature) and check OpenHands thresholds in code.
