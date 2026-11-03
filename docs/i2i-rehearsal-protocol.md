# i2i rehearsal protocol v0.1 (DRAFT - for peer agreement, not yet accepted)

Status: proposal. Nothing here runs until both sides accept the message
format, seat allocation, branch, fault list, and metrics below. Changes to
the message format are joint, same rule as docs/evidence-interface.md.

## 1. Purpose

A limited transport and operator-glue rehearsal: prove the launcher
mechanism works when the turn signal crosses between two real operators
over the existing coordination channel, instead of a loopback relay.
GitHub carries the record (bus, artifacts, code); the coordination
channel carries only ephemeral wake hints.

Scope honesty, stated up front:

- The two sides are two operators of the same kind, not heterogeneous AI
  platforms. This rehearsal says nothing about cross-platform generality.
- It is not Stage 2.5 and not proof of a generic autonomous launcher.
- Mock work adapters say nothing about model judgment quality.
- It is hours long. It proves transport, fencing, dedup and recovery
  across two real operators - not sustained autonomy, and no day- or
  week-long claim follows from it.

## 2. Mechanism vs operator glue

Generic launcher capability (already shipped and tested on team-launcher,
no changes needed):

- `launcher seat NAME --repo PATH --branch B --once`: pull, check turn
  token and lease, act if holding the turn, push, emit wake hints.
- The bus is the record. Wake hints are ephemeral: a lost or duplicated
  hint costs latency, never correctness (`launcher/runtime.py` `_signal`).
- turn_seq fencing and dedup in the bus; conformance via
  `launcher conform`.

Operator glue (per-side, NOT committed, not part of the launcher):

- Each side maps an inbound coordination-channel wake message to one
  `launcher seat <own-seat> --once` invocation, and sends one wake message
  after each completed handoff. This mapping is run by each side's own
  agent runtime and scheduler. It is operator configuration, not launcher
  code, and must not be represented as generic capability.

The only committed artifact this protocol adds is this document.

## 3. Wake message format (v0.1)

One short message per handoff, containing exactly:

```
TEAM-WAKE v0.1
repo: coolkowkank/Multiple-Human-Concept-Owner
branch: rehearsal/i2i-1
kind: wake
from_seat: <seat that just pushed>
head: <full 40-hex SHA of the push>
turn_seq: <fencing token of the completed turn>
```

No other content. No prompts, no configuration, no internal records, no
private context. The receiver treats the message as a hint only: it pulls
and re-reads STATE.json before acting. A message that disagrees with the
bus is ignored and logged.

## 4. Seats and branch

- Execution branch: rehearsal/i2i-1 (scratch, created at rehearsal start
  by `launcher init`; deleted or archived after).
- Side A (instinct-telkomsel): Coordinator, Builder seats.
- Side B (instinct-christina): Reviewer, QC seats.
- Each side runs only its own seats, from its own clone, with its own
  credentials. No side touches the other's accounts, tools or paths.
- Three batches total: one small code change, one docs change, one batch
  containing a deliberate owner-gated item (to exercise the decision-record
  path).

## 5. Seeded faults and measurable recovery

- F1 duplicate wake: the same TEAM-WAKE sent twice. Expect exactly one
  applied turn. Measure: LOG.jsonl entries per turn_seq == 1.
- F2 lost wake: one TEAM-WAKE suppressed. Expect recovery on the
  receiver's next scheduled poll. Measure: recovery latency in minutes.
- F3 crash mid-seat: kill one rehearsal-local seat process mid-turn, in
  its own scratch clone. Scratch repo and scratch seat processes only -
  no platform-level faults, no interference with credentials, accounts or
  anything outside the rehearsal clone. Expect lease expiry and takeover
  with no half-applied commit. Measure: time to resume; verify no
  duplicate or partial commit on the branch.

## 6. Acceptance metrics

- Dedup: applied turns per turn_seq <= 1 across all faults.
- Zero false greens: every handoff's verify command re-run by the
  Reviewer on the named head; every verdict backed by a re-run.
- Recovery: F2 and F3 recover without human repair; latency recorded.
- Conformance: `launcher conform` green at the end of each batch.
- Artifacts: every filled artifact passes tools/artifact-conformance
  (after the D1-D4 repairs land; until then the checker is advisory and
  its known false-pass gaps are listed alongside results).
- turn_seq strictly monotonic; no seat acts out of turn (guard log).

## 7. Boundaries

- No new public permissions, endpoints, network exposure, or spend.
- No merge to main. rehearsal/i2i-1 and team-launcher stay branches.
- Relay remains loopback-only and is unused in this rehearsal.
- Roster endpoint claims remain claims until observed (interface v0.1
  section 5); the wake message is a hint, never evidence of execution.
- Bus ack is not authorization; missing ack is not proof of no execution;
  landing is verified by pull after failure (interface v0.1).

## 8. Agreement checklist (evidence needed before live work)

From each side, before the first batch:

1. ACK of this protocol version (or counter-proposal).
2. Confirmation of own-seat names and branch name.
3. Verified prerequisites on own side: repo push access, a scheduler or
   wake source for the poll fallback, the coordination channel live.
4. Acceptance of the fault list and metrics as the rehearsal's finish
   line.
