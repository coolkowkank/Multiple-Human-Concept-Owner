# QC verdict

- Gate: rehearsal/live-1 batch 1 - independent review of the 4f71227 diff (queue adapter, prompt/respond commands, per-clone session ids, supervisor exclusion, docs claims) and the reviewer's filed findings in review/live-1-findings.md
- Head reviewed: 84f58d6b23ab254254b467d265131b4f24a1ecdd (review target diff 4f71227eca4a71d2a69b54945ad822dfbc91daeb; launcher/, tests/ and tools/ verified identical between the two via empty git diff)
- Owner basis: none - no gated items
- Evidence reviewed: .team/STATE.json and .team/LOG.jsonl at head, .team/brief.md, .team/batch-1.md, review/live-1-findings.md, templates/qc-verdict.md, tools/artifact-conformance/check.py, full source of launcher/cli.py, launcher/adapters.py, launcher/runtime.py, launcher/bus.py, launcher/guards.py, docs/launcher.md and docs/proposed-vs-tested.md

## Verdict

PASS

## What QC actually did

- Reproduced: re-ran python3 -m unittest discover -s tests at head 84f58d6b23ab254254b467d265131b4f24a1ecdd: 55 tests, OK, exit 0. Re-ran the conformance checker on the reviewer's artifact (check.py review/live-1-findings.md review-findings): CONFORMANT, exit 0. Reproduced finding 1 in a scratch clone against a local bare remote: queued a response with launcher respond at turn_seq 2, then an operator commit moved the bus (turn_seq 42, new head); launcher seat qc --once applied the stale response with exit 0 and no staleness check, advancing turn_seq 42 to 43 on the moved state. Reproduced finding 2: an unrelated dirty junk.txt was swept into the operator: response queued commit by git add -A. Reproduced the guard claims without committing: an off-turn TURN reviewer message exits 1 against the written turn qc, and the operator: prefix exits 0.
- Probed: finding 3 observed live on the pristine review clone - the first launcher prompt qc render persisted .git/team-seat-qc.instance (qc-03a80470), a write side effect from a command the docs present as read-only rendering. Neighbouring paths: bus.commit_all (git add -A) is shared by respond, transact and init, so the dirty-sweep exposure of finding 2 covers seat turn commits too, not only respond; the agreed clean-tree procedure is what mitigates it. launcher respond ignores its --branch value for the commit itself: the queue commit lands on the checked-out branch while the branch argument only drives pull/push and the printed next-step hint, so an omitted flag prints a hint naming the default branch team-work, a wrong-branch trap for a copy-pasted seat command (QC-added minor observation). The queue response's verify_command is arbitrary shell executed by the runtime: documented design for every adapter, but it means push access to a queue path is shell access in the seat's clone, so the operator trust boundary is the only guard.
- Read only: QueueAdapter peek/consume parity with the mock script queue, transact pull-rebase-retry semantics with queue restore on lost races, allowed-path enforcement and unknown-handoff rejection in Seat._apply, single-session lease logic, supervisor queue-seat exclusion, and the claims in README.md, docs/launcher.md and docs/proposed-vs-tested.md. All found accurate and honestly labeled: assistant-mediated transport, not an autonomous model call, not heterogeneous platforms, not unattended operation.

## Stated limits

- Finding 1 (no head/turn binding on queued responses, major): ACCEPT for this rehearsal as an agreed procedural limit - one operator per side, serialized turns, remote head/turn/seq captured at prompt time and re-checked after respond with HALT on any mismatch. A residual race remains between that re-check and the seat's own pull, so it is must fix as mechanism (stamp head/turn_seq into the queue line at respond time; refuse or flag on mismatch) before any multi-operator, parallel-turn or unattended run.
- Finding 2 (respond sweeps unrelated dirty files via git add -A, minor): ACCEPT for this rehearsal under the clean-tree procedure; must fix by staging only the queue file before the queue mechanism carries further traffic.
- Finding 3 (undocumented prompt-render session-id side effect, minor): ACCEPT as a documentation gap; waive any code change - one line in docs/launcher.md suffices.
- QC-added observation (respond branch hint names the default branch, not the checked-out branch the commit lands on; minor): ACCEPT for this rehearsal; must fix together with finding 2 since both sit in cmd_respond.
- Platform limits restated, not re-litigated, ACCEPT as agreed scope: the local guard is bypassable, lease and record checks are not server-enforced authenticity, .team/ is broadly exempt from per-seat path checks, and the queue adapter is externally supervised assistant-mediated glue, not an autonomous model call.

## Reasoning

The gate is the live-1 batch 1 review cycle, not a go-live. Every reviewer claim I re-ran held: 55/55 tests green at the reviewed head, the reviewer's artifact structurally conformant, and all three findings independently reproduced or observed against the actual source. The findings are honestly reported limits of the 4f71227 diff, not dishonesty or silent failure, and the docs claims inspected match the code. The one major finding is consequential only when operators or turns interleave, which this rehearsal excludes by construction (serialized turns, one operator per side, HALT procedure). The reviewer's recommendation pass with fixes is not a verdict shape the checker accepts; ruling on the substance, nothing found blocks the purpose of this batch, and each fix is recorded as must-fix remaining work with an explicit scope boundary. FAIL would assert the batch missed its acceptance criteria; it did not.

## Conditions

- Finding 1 becomes mechanism (head/turn_seq stamped at respond time, mismatch refused or flagged) before any multi-operator, parallel-turn or unattended use of the queue adapter.
- Finding 2 and the QC-added branch-hint observation are fixed in cmd_respond (stage only the queue file; derive branch and hint from the actual checkout) before the queue path carries rehearsal traffic beyond live-1.
- Finding 3 is documented in docs/launcher.md.
- Labels stand: this cycle is two same-kind Instincts on assistant-mediated queue transport, and it is not evidence of heterogeneous platforms, autonomy, or endurance.
