# Builder task: routing-failure counter + escalation test correction (v2)

Branch: live/builder-deadlock-fix. You own: launcher/supervisor.py +
tests/test_deadlock_fix.py. Stdlib only. Supersedes the withdrawn v1
(tasks/routing-failure-correction.md - DO NOT USE that file).

## Settled design (reviewer + coordinator reconciled 2026-11-04)
The supervisor's coordinator reissue on a running/null turn is
PROPOSAL-SPECIFIED behavior (docs/proposals/groq-deadlock-fix.md: "re-issue
the turn to the coordinator; escalate to a human gate after 2 consecutive
occurrences"), executed under bounded continuation. It stays. The log must
keep attributing the reissue to the supervisor; the model's original output
stays untouched. Do NOT change routing semantics in this task.

## Defects to fix (test/counter quality only, no semantics change)
1. F2 - "2 consecutive" is not implemented: _routing_failure_count only
   increments, so two non-consecutive nulls across a long run escalate.
   Reset the counter to 0 whenever _check_stall observes a valid turn
   (status running AND turn set). Keep: null,null -> escalate; null, valid
   turn, null -> count 1, no escalation.
2. F1 - the escalation test never reaches escalation: today the first
   call's reissue masks the second null. With the counter fixed, write the
   test so two CONSECUTIVE null states are actually observed and assert the
   escalation really happened (gate opened / escalation recorded), not
   merely that no second routing-failure log exists.
3. F4 - remove the dead setUp injection self.sup._routing_failures (the
   implementation uses _routing_failure_count); tests must exercise the
   real counter.
4. Regression the proposal demands: a null turn WITH status done (valid
   terminal state per runtime.py) must never enter the routing-failure
   path - add an explicit test.

## Explicitly out of scope (do not touch)
- The coordinator reissue itself (proposal-specified, reviewer-reconciled).
- runtime.py/adapters.py validation marker, cli.py default_roster/pycache:
  separate open follow-ups, tracked outside this task.

## Open question for the reviewer (do not guess)
If the roster ever lacks a "coordinator" seat, the reissue writes a turn to
a nonexistent seat. Check default_roster(): if coordinator is a guaranteed
invariant, note it in a comment; if not, flag it in your commit message for
the reviewer to assess - do not build a fallback.

## Done when
Full suite green (operator runs it after you commit), honest commit message
('TURN: builder' line), push (push gate applies; if refused as gated, retry
in a later round - the operator opens it after the suite passes).
