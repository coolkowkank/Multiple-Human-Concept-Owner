# Autonomous AI-Human Teamwork - Blueprint and Team Launcher

*Repository: `coolkowkank/Multiple-Human-Concept-Owner` - a human-led AI project team you can actually launch: roles, coordination, handoffs, independent review, and a runtime that starts and supervises the team.*

Two things live here, developed together:

1. **The blueprint** - project-, model- and framework-agnostic roles, rules, templates and diagrams for a concept-led human team with a managed AI delivery team.
2. **The team launcher** (`launcher/`) - a working runtime that turns the blueprint's written conventions into enforced mechanism: a shared coordination bus, a written turn token checked on every commit, per-seat single-session leases, supervised seat processes with crash restart and stall escalation, and a human-gate queue. Stdlib-only Python: no install step between "here is the concept" and "the team is running".

## The goal

The goal is autonomous AI-human teamwork with very rare routine human supervision, led by a delegated AI Coordinator. Humans agree the concept, written brief and boundaries, retaining concept, scope, spending and go-live decisions. Within explicit delegated authority, one Coordinator manages planning, assignment, delivery, review and recovery through one work queue. The team handles routine handoffs and recoverable failures; humans are involved only for decisions outside the agreed brief or authority, genuine concept conflicts, or exceptions the team cannot safely resolve. Independent QC stays separate from the Builder, and a failed verdict stands until resolved.

The launcher exists to make starting instant: the humans give the concept and the boundaries, and the Coordinator seat gets the team working - no per-step relaying, no waking sessions by hand.

This is the intended operating model, not a claim of proven unattended delivery. See [docs/proposed-vs-tested.md](docs/proposed-vs-tested.md) for what is demonstrated, and the honesty split below.

## Requirements vs. implemented vs. tested

| Requirement (from the concept owners) | Status |
| --- | --- |
| Fast launch: concept in, team running | Implemented: `python3 -m launcher init / seat / launch / demo`; tested by the suite and demo on mock adapters |
| Agents communicate with each other, not through humans | Implemented: the git-backed bus (`LOG.jsonl`, turn token, gates) is the shared communication place; a lightweight relay for faster cross-platform messaging is in progress |
| AI from different platforms working together | Designed: any platform that can run a CLI command or answer an HTTP prompt can occupy a seat (adapter interface). GitHub is the team's main work platform - code, artifacts, the durable record - but communication is not limited to GitHub; the relay and adapter interface exist so seats on different platforms talk directly. Support beyond that (A2A protocol, MCP) is mapped in docs, not yet implemented |
| Days-to-week unsupervised operation with recovery | Partially implemented: supervisor restarts crashed seats, detects stalled turns, escalates to humans only at gates. Tested in short fault-injection runs (crash, restart, resume). **Not yet proven**: no sustained multi-day run has happened; a staged soak test is planned and will be reported honestly |
| Rare routine human supervision; human gates kept | Implemented: gates for scope, spend, access, merge/go-live; everything inside the brief proceeds without asking |

## What the four evaluations taught

The runtime targets exactly what the author-side evaluations of the reference project (`Joe_Evaluation.md`, `Bill_Evaluation.md`, `JOE_LEGACY_EVALUATION.md`, `BILL_LEGACY_EVALUATION.md`) found forcing routine human intervention:

- **Humans were the wake-up and liveness layer.** Seats either polled or waited for a prod; watchers expired silently. Now: seats poll the bus themselves, and the supervisor restarts crashed seats and escalates stalled turns.
- **Proving who authorized what cost rounds.** Now: owner basis is recorded at decision time (decision records, delegation records), and gated items without one are blockers, not surprises.
- **"Green" claims nobody re-ran.** Now: one machine-checkable verify command per batch with head hash, exit code and environment label; a batch is green only when the Reviewer re-runs it at the same commit.
- **The turn token was a convention.** Now: a commit-msg guard rejects off-turn commits and out-of-path writes mechanically.
- **"Done" was undefined.** Now: the brief carries a done definition, accepted residual limits and stop conditions.
- **Role changes left stale documents.** Now: one roster with verified endpoints and a seat-change checklist; a seat change takes effect only through an owner-recorded decision.

## Harness engineering grounding

This is harness engineering: designing the instructions, context, checks and feedback loops around AI work so it produces reliable results, rather than changing the model itself. Design choices here are grounded in public agent-harness research and practice - see [docs/references.md](docs/references.md) for the source list, including harness-engineering accounts (Martin Fowler), multi-agent framework practice (MetaGPT, ChatDev, LangGraph, AutoGen, CrewAI, OpenAI Agents SDK), agent-interoperability protocols (A2A, MCP), and reliable-agent principles (12-factor agents, Anthropic's agent patterns). The high-impact reasoning seats are where judgment moves the whole project; routine throughput never waits on them.

## The two levels

1. **Concept level - the humans.** The concept owners agree the concept together, in writing. Each human's personal robot captures their discussion into one agreed brief: `concept_to_coordinator.md`. Scope, spend and go-live decisions stay at this level.
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

## Quick start: run the demo

```sh
python3 -m launcher demo
```

Creates a fresh project repo, launches the full seat cycle (Coordinator drafts criteria, Builder implements with a real verify command, Reviewer re-runs it, QC passes, Records archives, team closes DONE) and prints self-checks. No keys, no spend, about a second.

## Quick start: launch a real team

1. `python3 -m launcher init --repo /path/to/project --branch team-work --default-roster`
2. Fill `.team/brief.md` (or start from `templates/concept_to_coordinator.md`) and `.team/roster.json`: name each seat's adapter - `mock` for rehearsal, `cli` for an installed agent CLI, `http` for a model API, `interactive` for a session a human pastes prompts into.
3. `python3 -m launcher launch --repo /path/to/project` - the supervisor starts every automated seat, restarts crashes, escalates stalls, and prints human gates as they open.
4. Watch progress with `python3 -m launcher status --repo /path/to/project`; answer gates with `python3 -m launcher answer <gate-id> "<decision>"`.

Seats on any platform join the same bus. The git repository is the durable record and work platform; direct seat-to-seat messaging beyond git (the relay) is being added so cross-platform seats coordinate without human relaying. Pasting a prompt grants no access: a seat's access is verified by observed action, not claimed (docs/evidence-interface.md §5).

## Adopting the blueprint without the runtime

1. Name the concept owners and agree the concept in writing: copy `templates/concept_to_coordinator.md` and fill it in together.
2. Assign the delivery seats: one main job per assistant, model per seat, human owner per seat (`templates/roster.md`). Keep QC independent from Builder.
3. Set up the working artifacts: the brief, the turn-token handoff (`templates/batch-handoff.md`), review findings (`templates/review-findings.md`) and QC verdicts (`templates/qc-verdict.md`).
4. Confirm each session's actual access before relying on it.
5. Start the first batch: Coordinator issues the turn token, Builder writes, Reviewer checks, QC gates the consequential calls, Records archives.

## Operating rules

See [docs/operating-rules.md](docs/operating-rules.md) for the full rule set: written turn tokens, written findings, QC gates, recorded concept changes, human-level scope/spend/go-live decisions, and role rotation on long projects. For how the Coordinator acts on each owner's recorded delegation and asks only when blocked, see [docs/delegation.md](docs/delegation.md).

## For research use

This project keeps a clear trail: [references](docs/references.md) for the public sources behind each idea, a versioned [design-decision log](docs/design-decisions.md), an honest [proposed vs tested](docs/proposed-vs-tested.md) map, and the [evidence interface](docs/evidence-interface.md) between the runtime and the review artifacts. It claims no novelty: every component has a public precedent; the combination is what remains to be tested.
