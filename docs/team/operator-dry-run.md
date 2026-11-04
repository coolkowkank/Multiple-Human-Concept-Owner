# Fresh-operator dry run

Offline proof that a new operator (human or AI) can run this project's
harness before touching live work. Every step is local: no provider
calls, no credentials, no spend. Verified 2026-11-04 on a depth-1 clone
of team-launcher @ 83e33bc.

## 1. Clone and run the full suite

    git clone --depth 1 --branch team-launcher \
      https://github.com/coolkowkank/Multiple-Human-Concept-Owner.git
    cd Multiple-Human-Concept-Owner
    python3 -m unittest discover -s tests

Expected: `Ran 181 tests` / `OK` (60s on a laptop; count as of 83e33bc -
recompute against your pin, do not trust this number at a later commit).

## 2. Run the model-executor's offline tests

    python3 -m unittest tests.test_self_commit_executor

Expected: `Ran 37 tests` / `OK`. These use a fake API and scratch git
remotes: budget ledger, fail-closed halts, push gate, placeholder
refusal. If these pass, the operator can run the budget/gate machinery
without a provider.

## 3. Run the scripted demo team

    python3 -c "from launcher.demo import run_demo; import tempfile; run_demo(tempfile.mkdtemp())"

Expected: 9 x `PASS`, then `demo: all checks passed`. (Note:
`python3 -m launcher.demo` runs silently - the demo entry point is
`run_demo(directory)`, there is no `__main__` guard. Verified
2026-11-04.)

## 4. Scratch task cycle (optional, still offline)

On a scratch branch, rehearse the coordinator motions: verify a task
file's anchors against the pinned source, create an isolated worktree,
confirm the push gate refuses a push when unset (fail-closed), and
inspect a durable budget ledger. No push to shared branches, no branch
deletion.

## What this proves and what it does not

Proves: the candidate can reproduce the repo's own checks and operate
the safety machinery offline. Does NOT prove: live provider operation,
independent-review coverage, or autonomous end-to-end delivery - those
need their own evidence after the dry run (see
blueprints/coordinator.md, handover checklist).
