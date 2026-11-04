# Autonomous AI-Human Teamwork - Work in Progress and Intended Operating Model

## Project progress

*As of 2026-11-04 14:44 EET. Weighted milestone progress is **40.0%**, including 50% credit for partial work. This is not independently verified completion. No autonomous end-to-end run has passed yet.*

![Gantt chart](docs/progress/gantt.png?v=1444)

![Progress S-curve](docs/progress/s-curve.png?v=1444)

Only milestones backed by passing tests or an independent review count. The dashed lines are forecasts, not commitments, and no earlier plan existed to compare against. See [how progress is measured](docs/progress/README.md).

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
