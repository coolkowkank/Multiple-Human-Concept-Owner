# Team registry (Legacy Members)

Everyone who has been involved in this project: active members, defined
but vacant roles, and historical contributors. One row per member
instance. This file is the source of truth; the README renders from it.

**Status values**
- `active` - there is repo evidence of work by this instance. The `*` in
  the Parallels column marks active instances only; no placeholder
  instances are listed.
- `vacant` - the role is defined (blueprint exists) but no qualified
  model/person holds it. A vacant role does no work and appears in no
  chart as a member.
- `unknown / unconfirmed` - a historical contributor with no recorded
  departure and no documented activity after the date shown. Absence of
  newer activity is NOT proof of inactivity or retirement; nothing here
  invents a formal retirement.

**Instance IDs** are stable (role-short-name + number, e.g. `builder-1`).
A new parallel instance of the same role gets the next number and its own
row; the numbering is never reused after retirement.

| Instance | Role | Member | Status | Assignment (current) | Model / provider | Blueprint | Parallels | Last verified |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| coordinator-1 | Coordinator | Telkomsel (@instinct-telkomsel) | active | team coordination, assignments, acceptance prep | not project-configured | [coordinator](blueprints/coordinator.md) | 1* | 2026-11-04 (coordination commits on team-launcher) |
| builder-1 | Builder | Alex (@coolkowkank-bot) | active | reviewer-skip guard UNBUILT - batch 7 closed failed, held pending harness review | Groq openai/gpt-oss-120b, free tier | [builder](blueprints/builder.md) | 1* | 2026-11-04 (batches 1-7 records) |
| reviewer-1 | Independent reviewer | Bill (@instinct-christina) | active | pinned-commit peer review; also bounded read-only review route for builder-2 (accepted 2026-11-04, per-request scope, no standing work) | not project-configured | - | 1* | 2026-11-04 (WP7 review exchange) |
| researcher-1 | Researcher | Nora | active | sourced literature findings, Research_lab | Nemotron-3 Ultra 550B via Requesty free route | [researcher](blueprints/researcher.md) | 1* | 2026-11-04 (RW5, author corrections 61143ba) |
| verifier-1 | Evidence verifier | Eva | active | citation/evidence verification of Research_lab publications | google/gemma-4-31b-it via Requesty free route | [evidence-verifier](blueprints/evidence-verifier.md) | 1* | 2026-11-04 (reviews 3ecde66, 3aff4c6) |
| resources-1 | Team Resources | Ryan | active | model route availability + cap-aware replacement proposals; member-performance analysis + workflow proposals (chain: assistant -> coordinator -> owner, no auto-adoption); dedicated Researcher+Verifier support REQUESTED by owner; continuous runner built offline (mock-tested, awaiting independent review; no model assigned, nothing running); may draft project policy via the existing approval chain, no auto-adoption. Completed 2026-11-04: one performance-analysis loop done by operator research plus independent operator source/citation verification, with one Groq gpt-oss-120b second-opinion sample (3076 tokens, cost 0 as provider-reported; not a blanket no-cost claim) | not project-configured (deterministic checks; no model qualified for Researcher/Verifier functions; fresh verified-free qualification and a new cap are required before any model assignment (blocked, no new calls)) | [team-resources](blueprints/team-resources.md) | 1* | 2026-11-04 (owner assignment; availability record created) |
| assistant-1 | Coordinator Assistant | Sam | active | GitHub Pages project status: Gantt/S-curve, team, timeline - hourly changes-only | google/gemma-4-31b-it via Requesty price-0 route - narrow fixed-template status-draft only, one reviewed sample 2026-11-04, per-draft coordinator review mandatory; publication stays coordination-run | [coordinator-assistant](blueprints/coordinator-assistant.md) | 1* | 2026-11-04 (status-draft assignment) |
| assistant-2 | Coordinator Assistant | unassigned | cancelled before staffing | role defined 2026-11-04 (Slack 1793811994.355409) then cancelled by owner (Slack 1793812104.985419); never held, never did work; ID not reused | none | [coordinator-assistant-recovery-management](blueprints/coordinator-assistant-recovery-management.md) (cancelled, history) | - | 2026-11-04 (cancelled) |
| recovery-1 | Recovery Executor | unassigned | renamed to builder-2 | historical name only: same instance and work, renamed 2026-11-04 on owner direction (Slack 1793812104.985419); ID not reused | - | [recovery-executor](blueprints/recovery-executor.md) (history) | - | 2026-11-04 (rename) |
| builder-2 | Builder | unassigned (formerly recovery-1; not named by owner) | active | WP4 closeout (fixed-runtime tinylib run: no manual recovery, Reviewer engaged) + WP9 lower-token handoff savings measurement; transferred from Coordinator per owner 2026-11-04 (Slack 1793807666.323859 / 1793807753.116989); second Builder per owner 2026-11-04 (Slack 1793812104.985419). Review requests go to reviewer-1 Bill and Bill's verdicts return to builder-2, one pinned request at a time over the existing peer route; Bill accepted this review ROUTE 2026-11-04 19:09 as bounded, read-only code/test feedback plus re-review; each request names an immutable base, head, delta, acceptance criteria and public project evidence, and findings return to builder-2 for its own correction. NOT accepted: immediate audits, standing or unbounded work, provider/accounts/writes/merge/watch/spend, ownership, or session continuity | not project-configured (operator execution; NO model assigned or qualified - any model step needs its own verified-free bounded cap) | [builder](blueprints/builder.md), history: [recovery-executor](blueprints/recovery-executor.md) | 1* | 2026-11-04 (renamed from recovery-1, work and history carried over) |
| ref-bill-qc | QC (reference project) | Bill-QC | unknown / unconfirmed | none here | - | lead: BILL_LEGACY_EVALUATION.md | - | no activity documented after 2026-11-03 |
| ref-joe | Contributor (reference project) | joe-agent | unknown / unconfirmed | none here | - | lead: JOE_LEGACY_EVALUATION.md | - | no activity documented after 2026-11-03 |
| ref-claude | Evaluation author | Claude | unknown / unconfirmed | none here | - | lead: BILL_LEGACY_EVALUATION.md, JOE_LEGACY_EVALUATION.md | - | no activity documented after 2026-11-04 |

Notes:
- `reviewer-1` Bill (@instinct-christina) and historical `ref-bill-qc`
  Bill-QC are different stable identities: the first is this project's
  current independent reviewer; the second authored evaluation documents
  on the reference project. Do not merge the rows.
- The legacy evaluation documents are leads, not blueprints. They were
  written as retrospectives, not as role definitions.
- Activation, retirement and reactivation follow docs/team/lifecycle.md.
- Parallel instances are created only for genuinely independent work.
  Safety checks before a parallel activates: disjoint owned files AND no
  shared provider-quota collision (the Groq free tier is an org-level
  token budget - two Groq builders must be coordinator-serialized), no
  shared branch, no unmet dependency between the two work items.
