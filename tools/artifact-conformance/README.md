# Artifact conformance checker

Checks that a **completed** review artifact - batch handoff, QC verdict,
review findings, decision record, delegation record, gated-run evidence -
satisfies the structural contract of its template in `templates/`.

```sh
python3 tools/artifact-conformance/check.py <artifact-file> <type> [--decisions DIR]
python3 tools/artifact-conformance/test_check.py   # run the test suite
```

Types: `batch-handoff`, `qc-verdict`, `review-findings`, `decision-record`,
`delegation-record`, `gated-run-evidence`. Exit 0 conformant, 1 violations
listed, 2 usage error. Stdlib only, no third-party dependencies.

## What it checks

- No template placeholders left unfilled - backticked or raw
  angle-bracket tokens both count as unfilled
- Full 40-hex commit SHAs where a head is recorded (never an abbreviation)
- A verify command with an integer exit code from actually running it
- Per-suite `name: pass/fail` lines on batch handoffs
- Environment labeled mock / local / hosted plus account type
- `owner_basis` cites a decision-record ID, or is exactly
  "none - no gated items" (looser wordings such as "none whatsoever" are
  rejected); with `--decisions DIR` the cited DR-IDs must exist in the
  supplied decision records (cross-file resolution)
- Reproduced / Probed / Read-only honesty lines present and non-empty
- Every stated limit resolved as accept / waive / must fix
- Defect vs remaining-work typed separately, with severity and priority
- Decision records: required fields filled, and a locator containing a link
  must be marked public or owner-agreed (public-safe provenance)

## What it cannot check (non-goals)

Structural conformance is not semantic truth. This tool does not and cannot
establish:

- **Authenticity** - a filled field may still be fabricated: the SHA may
  name the wrong commit, the exit code may never have been observed, the
  owner quote may be invented. Authenticity stays with review seats
  re-running the verify command on the named head.
- **Security or correctness proof** - a conformant artifact says nothing
  about whether the system is safe or correct.
- **Transport or turn-token enforcement** - out of scope here, and bounded
  on the runtime side too: `launcher/conformance.py` inspects and reports
  after the fact, its commit-msg hook is client-side and bypassable, and
  turn_seq fencing reconciles rather than prevents. Neither layer is a
  proof of transport enforcement.

These limits are accepted as stated: the checker is a tripwire for
structure, one layer under human review, not a replacement for it.

## Interface

Consumes the evidence-interface v0.1 field names verbatim
(`docs/evidence-interface.md`): `owner_basis`, turn sequencing, head,
verify command, environment. Any interface change is joint - both sides
agree before either side's tooling changes.

## Fixtures

`fixtures/valid/` holds one conformant synthetic artifact per type;
`fixtures/invalid/` holds one seeded violation per case. All fixtures are
synthetic - no real project data, no real owner words, no real channels.
