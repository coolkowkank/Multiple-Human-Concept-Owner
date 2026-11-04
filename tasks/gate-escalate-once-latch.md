# Builder task: escalate-once latch (gate dedup while a gate is unanswered)

Base branch: live/builder-f3-roster-fix @ 26ff4bce5666afd6a3dbefbce7fe0d3d4a36e341
(independent-review PASS, narrow acceptance). New work branch:
live/builder-gate-latch off that pin. You own: launcher/supervisor.py +
tests/test_deadlock_fix.py. Stdlib only.

## Defect (independent reviewer finding, 2026-11-04)
_escalate() opens a NEW gate plus a commit on EVERY poll while the
condition persists and the earlier gate is still unanswered. Paths that
reach it repeatedly: count>=2 consecutive routing failures
(pre-existing), and the F3 absent-coordinator-seat guard (count==1).
Result: gate spam - many duplicate gates and commits for one unresolved
condition.

## Approved repair (do not redesign)
Escalate-once latch: while any supervisor-opened gate is still pending,
_escalate must NOT open another gate. Check the bus's pending gates
(the supervisor already reads them in _report_gates via
bus.pending_gates()); if any gate opened by seat "supervisor" is still
unanswered, record a one-line log noting the suppressed duplicate and
skip the commit (nothing changed). The FIRST escalation for a condition
still opens exactly one gate with the existing message and commit.
Do not change gate content, options, routing, or the pending-gates
contract.

## Tests (tests/test_deadlock_fix.py)
- DummyBus gains pending_gates() returning its recorded opened gates
  (gates the supervisor opened and that remain unanswered).
- New test: two consecutive _check_stall calls that both reach
  _escalate -> exactly ONE gate opened; the second is logged as
  suppressed; no second commit (count commit_all calls).
- Existing tests keep passing; the F3 no-coordinator test now also
  asserts a second poll opens no additional gate.

## Out of scope
- Stall/restart escalation paths' content; human gate handling;
  anything beyond the dedup latch.

## Done when
File tests green; full suite green offline (operator runs it);
honest commit message ('TURN: builder' line); push gated as usual.
