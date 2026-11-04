# Review findings

- Batch: turn 1 @ 6ea218cefdb39ff1e76cf54f06bb9c40916f3c80 (review target: commit 4f71227eca4a71d2a69b54945ad822dfbc91daeb)
- Reviewer: reviewer seat (assistant-mediated queue transport, Christina's side)

## Findings

| # | Type | Severity | Priority | Owner gate | Finding | Suggested fix |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | remaining-work | major | p2 | no | No head/turn binding on queued responses: `launcher respond` queues a response without recording the head/turn_seq it was reasoned against, and `seat --once` applies the queued line even after the bus moved (reproduced: queued, then STATE moved by an operator commit, seat applied the stale response exit 0 with no mismatch detected). A stale reasoned response can be applied silently; protection is operator procedure only. | Stamp the current head/turn_seq into the queue line at respond time; runtime refuses or flags on mismatch. |
| 2 | defect | minor | p3 | no | `launcher respond` commits with `git add -A`, sweeping unrelated dirty files into the operator queue commit (reproduced: an unrelated junk.txt was committed alongside the queue line). | Stage only the queue file itself (git add -- review/.live-1-reviewer.jsonl) instead of git add -A. |
| 3 | remaining-work | minor | p3 | no | `launcher prompt` has an undocumented local side effect: first render persists the per-clone session id (.git/team-seat-NAME.instance), though the command is presented as a read-only rendering. | Document the side effect in docs/launcher.md, or create the id lazily at seat run. |

## What the Reviewer actually did

- Reproduced: re-ran `python3 -m unittest discover -s tests` at head 6ea218cefdb39ff1e76cf54f06bb9c40916f3c80 (launcher code identical to target 4f71227eca4a71d2a69b54945ad822dfbc91daeb): 55 tests, OK. Reproduced finding 1 in a local scratch repo (queue a response, move STATE, `seat --once` applies it with no staleness check) and finding 2 (unrelated dirty file swept into the respond operator commit). Ran the actual conformance checker on this artifact before queueing: exit 0.
- Probed: `launcher prompt` first render persists .git/team-seat-reviewer.instance (finding 3); `launcher respond` rejects non-queue seats and invalid JSON (suite tests test_respond_rejects_*); commit-msg guard rejects an off-turn `TURN: reviewer` commit (exit 1) and accepts the `operator:` prefix (exit 0) on the rehearsal/live-1 clone; absent queue file is created by respond via makedirs.
- Read only: the 4f71227 diff source (QueueAdapter peek/consume parity with the mock script queue, _confirm_landed ancestry check before reset, stable per-clone session ids, supervisor EXTERNAL_TYPES exclusion) and the docs claims in README.md, docs/launcher.md and docs/proposed-vs-tested.md - found accurate and honestly labeled: assistant-mediated transport, not a live-model call, not heterogeneous platforms, not unattended operation.

## Verdict recommendation

pass with fixes

## Escalated to QC

Finding 1 (no head/turn binding) is consequential for any multi-operator run: a stale reasoned response can be applied against a moved bus with no mechanical check. QC should rule whether the procedural mitigation (operator captures remote head/turn/seq at prompt time, re-checks after respond, HALTs on any mismatch) is an accepted limit for this rehearsal or must become mechanism.
