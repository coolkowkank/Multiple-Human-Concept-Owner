# Review findings

> The Reviewer returns written findings on every batch.

- Batch: `<reference + full head SHA>`
- Reviewer: `<reviewer seat>`

## Findings

| # | Type | Severity | Priority | Owner gate | Finding | Suggested fix |
| --- | --- | --- | --- | --- | --- | --- |

- Type: `defect` or `remaining-work`. Keep them separate: defect IDs are
  issued by QC; remaining-work rows get their own prefix and never mix into
  the defect table.
- Severity (impact) and Priority (order of work) are different columns.
  An owner priority marking is not an approval and not a waiver.
- Owner gate: `yes` when accepting or fixing this row needs an owner
  decision record (docs/delegation.md section 4); cite the DR-ID once it
  exists.

## What the Reviewer actually did

- Reproduced: `<claims re-run, with results>`
- Probed: `<neighbouring paths tested, and how>`
- Read only: `<what was inspected but not executed>`

## Verdict recommendation

`<pass / pass with fixes / escalate to QC>`

## Escalated to QC

`<which findings are consequential and why, or none>`
