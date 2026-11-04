# Continuing this project (for any AI or agent)

Read order: (1) this file, (2) `STATUS.md` (the tracker: finding IDs,
states, next actions), (3) only the files your task needs. Do not
re-read history: frozen branches are snapshots, `STATUS.md` carries
the current truth with exact commit refs.

## Where things live (task -> file map)

| You need | Read |
| --- | --- |
| Current findings, states, next actions | `STATUS.md` |
| Bus: STATE/LOG/commits/races, staging | `launcher/bus.py` |
| Seat runtime: turns, leases, queue binding | `launcher/runtime.py` |
| CLI commands (`prompt`/`respond`/`seat`/...) | `launcher/cli.py` |
| Adapters: mock/queue/cli/http | `launcher/adapters.py` |
| Supervisor + relay/webhook wakes | `launcher/supervisor.py` |
| Operator guide, staging/binding semantics | `docs/launcher.md` |
| Team protocol and templates | `docs/delegation.md`, `templates/` |
| Artifact conformance rules + checker | `tools/artifact-conformance/` |
| Live cycle evidence (frozen, read-only) | branches `rehearsal/*`, `evidence/groq-1` |
| Regression proof for a finding | `tests/test_launcher.py` (unit), `tests/test_integration.py` (cross-clone) |

## Facts

- Working branch: `team-launcher`. Code `launcher/`, tests `tests/`,
  docs `docs/`, evidence interface `tools/artifact-conformance/`.
- Run tests: `python3 -m unittest discover -s tests` (82 green at
  `bc9eb48`, 2026-11-04; repin when code changes, don't leave a bare
  count).
- Commits require a prefix: `TURN: <seat>` for runtime turns, or
  `operator:` / `human:` / `supervisor:` (pre-commit guard).
- `.team/STATE.json`: `status` running/done, `turn`, `turn_seq`.
  Closing a cycle: DONE status_line -> status=done, turn=null; the
  conformance checker rejects anything less.
- Queue seats: `launcher prompt NAME` renders context;
  `launcher respond NAME --file r.json` queues a response bound to
  turn/turn_seq/head; the seat refuses stale bindings. Recovery:
  `respond --discard-stale`. Session ids are lazy and per-clone.

## Authority limits (do not widen without explicit owner go-ahead)

- No merge to `main`, no security/access changes, no spending or paid
  provider routes, no unattended/parallel live runs.
- Frozen branches are read-only evidence; never retrofit them.
- Secrets only via the owner's vault; never in repo, logs, or chat.
- Provider access validation is non-inference (`/models`) until a
  bounded live test is explicitly approved.

## Claims discipline

- Live-model TURN commits land in scratch test repos; this repo's
  evidence branches hold exported artifacts. Never describe exported
  evidence as a live provider pushing to this repo.


Mechanism fixes are not autonomy. Mark results open / fixed-unverified
/ verified honestly; an independent review moves states, not the
implementer.
