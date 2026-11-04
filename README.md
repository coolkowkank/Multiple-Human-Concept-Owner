# Autonomous AI-Human Teamwork - Work in Progress and Intended Operating Model

## Project Under Construction

**[Open the project site](https://coolkowkank.github.io/Multiple-Human-Concept-Owner/)** - menu to the team, Legacy Members, timeline, and Gantt chart with S-curve. Updated hourly when the project evidence changes.

<details>
<summary><b>Project Under Construction</b> - current team, timeline, Legacy Members, Gantt and S-curve (click to expand)</summary>

### Current Project Team

*Latest update: 2026-11-04 20:57 EET. [Static full view](https://coolkowkank.github.io/Multiple-Human-Concept-Owner/progress/team/) (selectable text, responsive cards; picture below is the fallback). Builder 2 carries the former Recovery Executor WP4/WP9 work, with no model configured. Bill accepts individually scoped read-only review requests and returns verdicts. No second Coordinator Assistant. Ryan's Researcher produces findings, his Verifier checks references, then Ryan reviews verified output. Researcher provisionally uses Nemotron-3 Ultra, Ryan and his Verifier provisionally use Ling 3.1 Flash in separate executions. All are UNQUALIFIED / PAUSED, not running. The Coordinator selects and assigns models; Ryan does not. One Researcher diagnostic produced an unverified draft with an incorrect claim. Two Verifier attempts failed; no verdict or Ryan review, no qualified cycle. Eva remains blocked pending integration acceptance and a qualified route. Sam remains beside the Coordinator; Ryan is a side branch, not a serial manager.*

![Current Project Team](https://github.com/coolkowkank/Multiple-Human-Concept-Owner/raw/b1e02e69c17bb0971530135e4034f7a873c8901d/docs/progress/team.png)

### Coordinator work timeline

**[Open the interactive timeline](https://coolkowkank.github.io/Multiple-Human-Concept-Owner/progress/timeline/)** (hosted on GitHub Pages; [same page as a File](https://files.instinct.com/9ikwv5puwqvj-coordinator-work-timeline)) - time on the X-axis, pick a day, zoom, filter by kind of work, and click an event for its status and evidence links.

*Snapshot as of 2026-11-04 20:57 EET, not a live feed. Markers are recorded commit times on `main`, `Research_lab` and project branches. A check that finds no change leaves no record, so it is not drawn. The chart publications lane lists recorded publications only, not proof of scheduled checks. Triggered work has no schedule. Each day's picture is posted at the end of the day and kept in [the archive](docs/progress/archive/README.md). Data: [events.json](docs/progress/timeline/events.json).*

### Legacy Members

*As of 2026-11-04 19:52 EET. [Scrollable full view](https://coolkowkank.github.io/Multiple-Human-Concept-Owner/progress/legacy-members/) (sideways and down, header and first column stay put). Full table with instance IDs, blueprints and rules: [registry](https://github.com/coolkowkank/Multiple-Human-Concept-Owner/blob/team-launcher/docs/team/registry.md). `*` marks an instance with repo evidence of work. Backup coverage for model failures is a known gap.*

| Role | Member | Status | Assignment | Model / provider | Blueprint | Parallels |
| --- | --- | --- | --- | --- | --- | --- |
| Coordinator | Telkomsel | active | coordination, assignments, acceptance | not project-configured | - | 1* |
| Builder | Alex | active | reviewer-skip guard attempt closed, not delivered | gpt-oss-120b, Groq free | [builder](https://github.com/coolkowkank/Multiple-Human-Concept-Owner/blob/team-launcher/docs/team/blueprints/builder.md) | 1* |
| Independent reviewer | Bill | active | pinned-commit review | not project-configured | - | 1* |
| Researcher | Nora | active | sourced findings on Research_lab | Nemotron-3 Ultra 550B, Requesty free | [researcher](https://github.com/coolkowkank/Multiple-Human-Concept-Owner/blob/team-launcher/docs/team/blueprints/researcher.md) | 1* |
| Evidence verifier | Eva | blocked | integration review pending; not running | Gemma historical trial, cooldown | [evidence-verifier](https://github.com/coolkowkank/Multiple-Human-Concept-Owner/blob/team-launcher/docs/team/blueprints/evidence-verifier.md) | 1* |
| Team Resources | Ryan | active | model route checks, replacement proposals (free resources only) | not project-configured | [team-resources](https://github.com/coolkowkank/Multiple-Human-Concept-Owner/blob/team-launcher/docs/team/blueprints/team-resources.md) | 1* |
| Coordinator Assistant | Sam (status drafts) | active | status drafts only, every draft reviewed, publication separate | google/gemma-4-31b-it, Requesty free | [coordinator-assistant](https://github.com/coolkowkank/Multiple-Human-Concept-Owner/blob/team-launcher/docs/team/blueprints/coordinator-assistant.md) | 1* |
| Reference-project members (Bill-QC, joe-agent, Claude) | - | unknown | none here | - | leads only, see registry | - |

### Project progress

*As of 2026-11-04 20:57 EET. Weighted milestone progress is **62.5%**, including 50% credit for partial work. This is not independently verified completion. No autonomous end-to-end run has passed yet.*

**Research work packages: RW1-RW6**. RW1-RW6 are rows in the same Gantt, after the WPs; research dependencies/details below do not add milestone credit. Dates are evidenced publications/replays, not continuous work time; no RW deadlines were specified. [Plan](https://github.com/coolkowkank/Multiple-Human-Concept-Owner/blob/Research_lab/research/PLAN.md) · [Status and dependencies](https://coolkowkank.github.io/Multiple-Human-Concept-Owner/progress/charts/)

| ID | Research work | Current research state | Dependencies / related work |
|---|---|---|---|
| RW1 | Reliable handoffs | S3 design published; pending review | Builder validator; incident/replay fixture; RW3 token data; WP4, WP9; WP8a literature, WP8b experiments |
| RW2 | Independent review and acceptance gates | S2 sources/findings; comparison not run | Reviewer agreement on input format; pin/gate workstream; WP5, WP7, WP4; WP8a literature |
| RW3 | Token efficiency | Baseline note published; pending review; savings unmeasured | Read-only ledger export; RW1/RW2 variants; matched comparison with equal acceptance outcome; WP9; WP8b experiments |
| RW4 | Stall and liveness detection | S4 partial offline replay; E4b blocked on data | Builder repair; defined liveness/wait signal; histories with real stall, wait and long multi-call turn; WP5; WP8b experiment E4 |
| RW5 | Prior art in public systems | S2 notes; partial level-2 read, no tested adoption decision | None; feeds RW1-RW4. Re-pin implementation and write adopt/skip decisions; Supports RW1-RW4, no separate WP credit |
| RW6 | Rate-limit-aware provider routing | S0 placeholder; not started | Research scope must be assigned; no date committed; WP6 context only |

**Individual jobs are in the same Gantt diagram**, after WP and RW rows. The chart includes latch revisions, independent reviews, performance analysis and Builder 2 work (formerly Recovery Executor). Markers show dated outputs or reviews only, not continuous runtime, idle time or extra milestone credit. Coordinator coordination is excluded.


![Gantt chart](https://github.com/coolkowkank/Multiple-Human-Concept-Owner/raw/b1e02e69c17bb0971530135e4034f7a873c8901d/docs/progress/gantt.png)

![Progress S-curve](https://github.com/coolkowkank/Multiple-Human-Concept-Owner/raw/b1e02e69c17bb0971530135e4034f7a873c8901d/docs/progress/s-curve.png)

**[Open the Gantt chart and S-curve as a page](https://coolkowkank.github.io/Multiple-Human-Concept-Owner/progress/charts/)** (click a row for status and evidence). The page and these pictures change only when the project evidence changes; a check that finds nothing new leaves them as they are.

The large icon on each Gantt row is the accountable current owner (a role assignment, not authorship). Small icons are contributors. A legend under the chart gives names and roles. Telkomsel, Alex, Nora and Bill are project aliases for the four roles, not separate GitHub accounts. Nora (Researcher) uses the owner's @coolkowkank account through a shared research token that Eva (Evidence verifier) may also use, by the owner's grant, with the role as commit author, so each has a role icon instead of an avatar.

Only milestones backed by passing tests or an independent review count. The dashed lines are tentative estimates, not commitments or predictions of clock times. The pink baseline was frozen at 14:40 on 2026-11-04 and is never edited, so slips against it stay visible. No plan existed before that. See [how progress is measured](docs/progress/README.md).

</details>

*Repository: `coolkowkank/Multiple-Human-Concept-Owner` - a reusable blueprint for human-led AI project teams: roles, coordination, handoffs, independent review, and project setup.*

A reusable setup blueprint for running any project with a concept-led human team and a managed AI delivery team. It is project-, model- and framework-agnostic: copy this into a new project, fill in the placeholders, and the working setup is ready.

This is a blueprint, not a running system: roles, rules, templates and diagrams. It does not connect anyone's accounts or instantiate a live team.

## The goal

The goal is autonomous AI-human teamwork with very rare routine human supervision, led by a delegated AI Coordinator. Humans agree the concept, written brief and boundaries, retaining concept, scope, spending and go-live decisions. Within explicit delegated authority, one Coordinator manages planning, assignment, delivery, review and recovery through one work queue. The team handles routine handoffs and recoverable failures; humans are involved only for decisions outside the agreed brief or authority, genuine concept conflicts, or exceptions the team cannot safely resolve. Independent QC stays separate from the Builder, and a failed verdict stands until resolved.

This is the intended operating model, not a claim of proven unattended delivery. See [docs/proposed-vs-tested.md](docs/proposed-vs-tested.md) for demonstrated use and remaining gaps.

## The two levels

1. **Concept level - the humans.** The concept owners (four humans in the reference design, all with an equal say) agree the concept together, in writing. Each human's personal robot captures their discussion into one agreed brief: `concept_to_coordinator.md`. Scope, spend and go-live decisions stay at this level.
2. **Delivery level - the robots.** A Coordinator reads its orders from the brief and manages every delivery role. The team is expandable: add robots as the project needs, each with a role, a model and a human owner.

![Team formation](diagrams/formation-chart.svg)

## Roles

| Role | Model seat | Responsibility |
| --- | --- | --- |
| Coordinator | Personal assistant | Reads the agreed brief, assigns work, runs the one queue, relays to the humans. It relays; it does not decide the concept. |
| Personal robots | Personal assistant | One per human. Captures its owner's discussion into the brief; can clarify directly with the Coordinator, never overriding the brief. |
| Builder | Personal assistant | The sole writer: implements one batch per written turn token, so every change is traceable and no two AIs write at once. |
| Reviewer | Personal assistant | Checks every routine batch and returns written findings; escalates the consequential ones to QC. |
| Records | Personal assistant | Archives hand-offs, findings, verdicts and the concept change history, so any human can reconstruct what happened. |
| Architect | High-impact reasoning seat | Turns the agreed brief into the architecture, specs and acceptance criteria every batch is built and judged against. |
| Independent QC | High-impact reasoning seat | Verdict on the consequential calls: milestones, high-risk cross-cutting changes, material architecture or spec changes, and unresolved critical findings. A fail stands - the Coordinator cannot override it. |

### Capacity rules

- **One main delivery job per assistant.** A second job is allowed only while it is mostly idle; if it becomes busy, make a reallocation decision instead of letting it compete with the main job.
- A role circle is a responsibility, not necessarily a separate assistant. Sharing a human owner does not mean two roles share the same assistant.
- Independent QC stays separate from Builder. Sharing must never turn self-review into independent approval.
- Each personal assistant keeps its own-human interaction, discussion capture and relay responsibility. A delivery assignment must leave that relationship available.

## How the delivery team works

![Delivery flow](diagrams/delivery-flow.svg)

- Architect and Builder: specs, constraints and design questions, both ways.
- Builder and Reviewer: implementation one way, findings and fixes the other.
- Reviewer to QC: critical findings and milestone evidence. QC's verdict goes to the Coordinator, and a fail stands.
- Architect, Builder, Reviewer and QC write decisions, results and handoffs to Records.
- The Coordinator assigns work, sets priorities and resolves conflicts. Peers do not reassign each other.
- Humans need only two interaction lines into the delivery team: the Coordinator and QC. Everything else flows through the brief.

## Quick start

1. Create a new, empty project repository (for example "WORK").
2. Open a Coordinator session in an AI assistant that can read this repository and read/write your project repository. Give it your project repository URL and paste the contents of [templates/coordinator-starter-prompt.md](templates/coordinator-starter-prompt.md).
3. The Coordinator checks its actual access first, then sets this blueprint up inside your project repository without overwriting anything, helps the owners agree the brief, and writes a short prompt for each other role. You open one new session per role, paste its prompt, and bring the reply back.

Pasting the prompt grants no access, and one chat session cannot start or connect others. The humans open and relay the role sessions. The Coordinator marks a seat ready or access verified only after it has seen it work. The steps below are the manual version of the same process.

## Adopting this blueprint

1. Name the concept owners and agree the concept in writing: copy `templates/concept_to_coordinator.md` and fill it in together.
2. Assign the delivery seats: one main job per assistant, model per seat, human owner per seat. Keep QC independent from Builder.
3. Set up the working artifacts: the brief, the turn-token handoff (`templates/batch-handoff.md`), review findings (`templates/review-findings.md`) and QC verdicts (`templates/qc-verdict.md`).
4. Before relying on any autonomous session, confirm the session-to-repo handoff mechanism - how a session receives a batch and returns work - and each session's actual access. This blueprint does not set that up or verify it.
5. Start the first batch: Coordinator issues the turn token, Builder writes, Reviewer checks, QC gates the consequential calls, Records archives.

## Operating rules

See [docs/operating-rules.md](docs/operating-rules.md) for the full rule set carried over from the reference project: written turn tokens, written findings, QC gates, recorded concept changes, human-level scope/spend/go-live decisions, and role rotation on long projects. For how the Coordinator acts on each owner's recorded delegation and asks only when blocked, see [docs/delegation.md](docs/delegation.md) (proposed, untested).

## For research use

This blueprint keeps a clear trail: [references](docs/references.md) for the public sources behind each idea, a versioned [design-decision log](docs/design-decisions.md), and an honest [proposed vs tested](docs/proposed-vs-tested.md) map. It claims no novelty: every component has a public precedent; the combination is what remains to be tested.

## Background

This is harness engineering: designing the instructions, context, checks and feedback loops around AI work so it produces reliable results, rather than changing the model itself. The high-impact reasoning seats are where judgment moves the whole project; routine throughput never waits on them. See <https://martinfowler.com/articles/harness-engineering.html> for the terminology.
