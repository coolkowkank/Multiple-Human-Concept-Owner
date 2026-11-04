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
| reviewer-1 | Independent reviewer | Bill (@instinct-christina) | active | pinned-commit peer review | not project-configured | - | 1* | 2026-11-04 (WP7 review exchange) |
| researcher-1 | Researcher | Nora | active | sourced literature findings, Research_lab | Nemotron-3 Ultra 550B via Requesty free route | [researcher](blueprints/researcher.md) | 1* | 2026-11-04 (RW5, author corrections 61143ba) |
| verifier-1 | Evidence verifier | Eva | active | citation/evidence verification of Research_lab publications | google/gemma-4-31b-it via Requesty free route | [evidence-verifier](blueprints/evidence-verifier.md) | 1* | 2026-11-04 (reviews 3ecde66, 3aff4c6) |
| resources-1 | Team Resources | Ryan | active | model route availability + cap-aware replacement proposals; member-performance analysis + workflow proposals (chain: assistant -> coordinator -> owner, no auto-adoption); dedicated Researcher+Verifier support REQUESTED by owner (model assignments unresolved; no standing seat or running verifier now). Completed 2026-11-04: one performance-analysis loop done by operator research plus independent operator source/citation verification, with one Groq gpt-oss-120b second-opinion sample (3076 tokens, cost 0 as provider-reported; not a blanket no-cost claim) | not project-configured (deterministic checks; no model qualified for Researcher/Verifier functions; fresh verified-free qualification and a new cap are required before any model assignment (blocked, no new calls)) | [team-resources](blueprints/team-resources.md) | 1* | 2026-11-04 (owner assignment; availability record created) |
| assistant-1 | Coordinator Assistant | Sam | active | GitHub Pages project status: Gantt/S-curve, team, timeline - hourly changes-only | google/gemma-4-31b-it via Requesty price-0 route - narrow fixed-template status-draft only, one reviewed sample 2026-11-04, per-draft coordinator review mandatory; publication stays coordination-run | [coordinator-assistant](blueprints/coordinator-assistant.md) | 1* | 2026-11-04 (status-draft assignment) |
| assistant-2 | Coordinator Assistant | unassigned (owner has not named) | vacant | manages Recovery Executors: assignments, priorities, blockers; peer of assistant-1 (not under Sam); proposes only, technical acceptance stays with independent review; unresolved decisions go to the Coordinator | none configured (no model qualified; authorizes no provider calls) | [coordinator-assistant-recovery-management](blueprints/coordinator-assistant-recovery-management.md) | - | 2026-11-04 (owner direction, role defined, nobody holds it) |
| recovery-1 | Recovery Executor | unassigned | active | WP4 closeout (fixed-runtime tinylib run: no manual recovery, Reviewer engaged) + WP9 lower-token handoff savings measurement; reports to assistant-2 (role vacant, so until it is held, escalations go to the Coordinator); transferred from Coordinator per owner 2026-11-04 (Slack 1793807666.323859 / 1793807753.116989) | not project-configured (operator execution; NO model assigned or qualified - any model step needs its own verified-free bounded cap) | [recovery-executor](blueprints/recovery-executor.md) | 1* | 2026-11-04 (WP4/WP9 transfer) |
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
