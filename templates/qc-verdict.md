# QC verdict

> Independent QC rules on the consequential calls: milestones, high-risk
> cross-cutting changes, material architecture or spec changes, unresolved
> critical findings. A fail stands - the Coordinator cannot override it.
> Merge or go-live needs a QC pass.

- Gate: `<milestone / change under review>`
- Head reviewed: `<full commit SHA>`
- Owner basis: <decision-record IDs covering every gated item in scope; a
  gated item with no record is a blocker, not a pass>
- Evidence reviewed: `<evidence links>`

## Verdict

PASS / FAIL

## What QC actually did

- Reproduced: `<claims re-run, with the verify command, head and exit codes>`
- Probed: <neighbouring paths tested, and how. In the reference project the
  highest-value findings sat next to the fix, not in it>
- Read only: `<what was inspected but not executed>`

Scratch environments (a throwaway clone, a fake client, a local database)
are allowed for probing, provided nothing live is touched and they are
deleted afterwards.

## Stated limits

<Each open limit, with Accept / waive / must fix. The owner is asked once,
batched, with options and a recommendation (docs/delegation.md section 3).>

## Reasoning

`<why, tied to the acceptance criteria and the agreed brief>`

## Conditions

`<what must change for a FAIL to become a PASS, if anything>`
