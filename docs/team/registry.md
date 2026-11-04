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
| builder-1 | Builder | Alex (@coolkowkank-bot) | active | reviewer-skip guard (batch 7, in flight) | Groq openai/gpt-oss-120b, free tier | [builder](blueprints/builder.md) | 1* | 2026-11-04 (batches 1-7 records) |
| reviewer-1 | Independent reviewer | Bill (@instinct-christina) | active | pinned-commit peer review | not project-configured | - | 1* | 2026-11-04 (WP7 review exchange) |
| researcher-1 | Researcher | Nora | active | sourced literature findings, Research_lab | Nemotron-3 Ultra 550B via Requesty free route | [researcher](blueprints/researcher.md) | 1* | 2026-11-04 (RW5, author corrections 61143ba) |
| verifier-1 | Evidence verifier | Eva | active | citation/evidence verification of Research_lab publications | google/gemma-4-31b-it via Requesty free route | [evidence-verifier](blueprints/evidence-verifier.md) | 1* | 2026-11-04 (reviews 3ecde66, 3aff4c6) |
| resources-1 | Team Resources | Maya | vacant | none - registry/blueprint maintenance once qualified | unassigned (qualification trial required first) | [team-resources](blueprints/team-resources.md) | - | - |
| assistant-1 | Coordinator Assistant | unassigned | vacant | none - handoff tracking / status-evidence gathering once assigned | unassigned | [coordinator-assistant](blueprints/coordinator-assistant.md) | - | - |
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
