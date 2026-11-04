# Builder task: routing-failure handling correction - SUPERSEDED, DO NOT USE

**SUPERSEDED 2026-11-04 15:05 EET, before any launch: the reviewer retracted
the routing-semantics blocker. The coordinator-reissue pattern appears to
come from the approved original proposal, not from model invention. This
task v1 (63bc3c7) must not be worked. A reconciled task may follow after
source semantics are settled. F1/F2/F4 test-quality findings remain valid
and will be carried into any replacement task. Original v1 text preserved
below unedited for the record.**

---

# Builder task: routing-failure handling correction (v1)

Branch: live/builder-deadlock-fix (head 45cec13). You own:
launcher/supervisor.py + tests/test_deadlock_fix.py. Stdlib only.
Independent reviewer (Christina) BLOCKED acceptance of 45cec13 on these
findings; correct YOUR earlier work. Do not weaken test intent.

## Finding B (blocker): invented routing
_check_stall's routing-failure branch hardcodes a fallback:

    state["turn"] = "coordinator"
    state["turn_since"] = time.strftime(...)
    self.bus.write_state(state)

Assigning the turn to "coordinator" invents a routing decision the system
never made (no roster validation either). Remove the fallback ENTIRELY:
on a null-turn routing failure, append the loud "routing-failure" log and
leave state UNCHANGED (a first null may be transient). Never assign a turn
the routing layer did not produce.

## Finding F1: escalation test never reaches escalation
test_routing_failure_escalate calls _check_stall twice, but the first call
mutates turn to "coordinator", so the second call never re-enters the null
branch. After the fallback is removed, two consecutive null states really
are consecutive; assert escalation ACTUALLY happened (gate opened /
escalation log), not merely that no second routing-failure log appears.

## Finding F2: counter never resets on recovery
_routing_failure_count only increments. Reset it to 0 whenever a valid turn
is observed (status running WITH a turn), so one transient null followed by
recovery does not escalate later.

## Finding F3: no fallback under constraint
Do not replace the hardcoded coordinator with a roster-validated fallback
either. The constraint is: no invented routing at all. Loud log + transient
tolerance + escalation on repetition only.

## Finding F4: dead test scaffolding
tests setUp injects self.sup._routing_failures but the implementation uses
_routing_failure_count. Remove the dead injection; tests must exercise the
real counter.

## Semantics to preserve
- test_no_stall_utc and test_stall_detected_after_timeout stay green as-is.
- A single transient null does not escalate and does not stall the seat.
- test_routing_failure_first must now assert: loud routing-failure log AND
  turn stays null (no invented assignment), state otherwise unchanged.

## Done when
Full suite green in the worktree (operator runs it after you commit), your
commit message says exactly what changed ('TURN: builder' line required),
and you push (a push gate applies; if push is refused as gated, retry in a
later round - the operator opens it after the suite passes).
