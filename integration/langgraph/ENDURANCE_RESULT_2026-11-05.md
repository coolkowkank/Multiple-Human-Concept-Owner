# Mock endurance experiment (scratch, scripted, no provider)

Script: `endurance_experiment.py`. A real `launcher launch` supervisor and five real seat processes ran N=3 full cycles (coordinator, builder, reviewer, qc, records, then a final coordinator DONE): 16 turns, real verify runs, real git commits, scripted MOCK adapters. No provider, key, ledger or project lease. Success criteria C1-C5 are written in the script before the runs.

## Results
Pre-fix and post-fix runs are separate. The counts below are what happened, not rates.
- PRE-FIX (head b5b77c1), 5 runs in total, 3 of them concurrent: 1 early run hit a real defect. A seat crashed with `git ... index.lock: File exists` while committing (a next seat started on the previous holder's uncommitted handoff in the shared worktree and raced the commit). The supervisor restarted it and the team still finished, but that run also had a harness error (my own test run left `__pycache__`), so it is not counted as a success. The other pre-fix runs did not show it. It is timing-dependent, and no rate is claimed.
- Fix: a seat that sees `turn == itself` now takes the repo action lock briefly and re-reads state before its preflight (`runtime.py`), so the previous holder's apply-to-commit window has finished. Regression: `handoff_race_test.py` (fails with the lock lines removed, passes with them).
- POST-FIX (head 640ced1): 3 clean runs and 1 kill run, all SUCCESS. Each had 16 turns, 19 commits (20 with the kill run), a clean tree, 0 error rows, 0 gates, no stale declaration, turn_seq +1 per turn, per-batch files present, and the cumulative test re-run green. Clean runs: 0 restart rows, about 62s wall, LOG about 32 KB.
- Kill run: one ACTUAL SIGKILL of the builder seat process while it was inside its batch-2 verify. The supervisor logged `seat builder exited -9; restart 1`, the turn replayed, and the run finished with the same assertions. The builder session id stayed stable across the restart. The script field `builder_handoffs_total` (named ..._batch2 in the first runs) counts every builder handoff row; equal to N means the replayed turn produced one handoff, not two.

## What this is not
- The action lock times out after 30s (BusError). A seat waiting on it for longer exits through the normal error path; the new wait does not change that timeout. Separate clones with a remote do not share this lock at all, and the lock is advisory and cooperative, so another process can ignore it.
- 16 turns, about a minute, scripted mock answers. Not model quality, not long-duration endurance, not provider failures, not push or remote behaviour, not unattended safety.
- The kill hit a non-spending mock seat inside verify. A spending seat would not be restarted (it escalates). The race rate before the fix is unknown. The 3 concurrent early runs shared CPU, so timings are not benchmarks.
- No automatic recovery policy was changed.
