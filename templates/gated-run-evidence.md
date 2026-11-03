# Gated run evidence

> The fixed evidence shape for any run that needed an owner decision: hosted
> initializations, live smoke tests, paid runs, data changes. Written by the
> acting seat during the run, checked by QC. A run without its decision
> record is a blocker, not an oversight to repair later.

| Field | Value |
| --- | --- |
| Decision record | `<DR-ID covering this run, from templates/decision-record.md>` |
| Target and scope | `<what was run, against what>` |
| Environment | `<mock / local / hosted + account type used>` |
| Counts before / after | `<rows, objects or resources, both sides of the run>` |
| Test identity | `<verify command + full head SHA, per docs/evidence-interface.md section 3>` |
| Rows / objects touched | |
| Cleanup | `<cleanup action or query, and its observed result>` |
| Not proven | `<what this run did not establish>` |
| No-secrets check | `<confirmation that no credential or private data reached the repo, logs or evidence>` |

## Rules

- Name the environment and account type on every run. A local proof is not a
  hosted proof: in the reference project a hosted initialization failed on a
  permission step that local runs, executed as a superuser, had bypassed.
- Acceptance criteria in the brief name the environment where proof is
  required; evidence from a weaker environment does not close them.
- Spend-bearing reruns stay inside the owner-set envelope in the delegation
  record; the envelope is cited here by ID.
