# Rehearsal brief - i2i-2

Single actual-runtime cross-operator cycle, window to 04:50 EET hard
stop. Base: team-launcher 33df600 (peer-accepted). Protocol:
docs/i2i-rehearsal-protocol.md, scope change accepted: single cycle, no
separate probe, no re-seeded faults.

Side A (instinct-telkomsel): coordinator, builder.
Side B (instinct-christina): reviewer, qc.
Token order: coordinator -> builder -> reviewer -> qc -> close.

Batch: fix the genuine i2i-1 review finding - handoff_counts must skip
and report malformed LOG lines instead of raising, with a regression
test. Mock adapters with script_path queues; every seat turn through
`launcher seat --once`; commit-msg hook installed and verified both
sides. HALT on any turn failure - reconcile before any further action.
Known accepted-base limitation: Cli/Http adapter consume bug tracked
for post-cycle fix; mock seats only this cycle.
