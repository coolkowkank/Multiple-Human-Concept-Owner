# Batch handoff - turn token

> No AI writes without holding the written turn token. One batch per turn.
> With the launcher runtime the token is a mechanism: `.team/STATE.json`
> names the holder and the `turn_seq` fencing token, and the pre-commit
> guard rejects commits from any other seat or outside the seat's allowed
> paths (docs/evidence-interface.md section 1). Without the runtime, this
> file is the convention - and convention alone did not hold in the
> reference project.

TURN: <role or assistant holding the write turn>
Turn seq: <integer from STATE.json>

## Batch

- Issued by: Coordinator
- Assigned to: <assigned role>
- Batch scope: <what this batch changes, and nothing beyond it>
- Spec / acceptance criteria: <link or reference>
- Owner basis: <decision-record ID, or owner quote reference with channel +
  timestamp - required for any scope, spend or go-live item in this batch>

## Result

- Files changed: <list of files>
- Head: <full commit SHA>
- Verify command: <one shell command that runs every required suite>
- Exit code: <integer, from actually running it>
- Suites: <one line per suite: `name: pass/fail`>
- Environment: <mock / local / hosted + account type>
- Evidence: <links, screenshots, logs>

## Handoff

- Next: <next role>
- Open questions: <list, or none>

## Rules

- Green means the Reviewer re-ran the same verify command on the same head
  and recorded exit code 0. A subset suite is never reported as a full
  baseline; where CI covers the agreed branch, CI replaces the manual
  re-run.
- A decision needed mid-batch is raised as a question before the commit,
  not disclosed after it.
- A handback must carry new work, a verdict or a decision request - never
  an acknowledgement only.
