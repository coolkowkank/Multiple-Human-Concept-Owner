# Acceptance tests

> Status: proposed staged protocol. The launcher's mechanism suite
> (24 tests at the time of writing) exercises parts of the Stage 2
> machinery; Stages 1, 2.5, 3 and 4 have not been run as staged here, and
> no result belongs in docs/proposed-vs-tested.md until it has. These tests measure protocol machinery and supervision load. They
> do not measure model quality, and no short pass proves week-long
> autonomy - only Stage 4 speaks to that, and only for the window it ran.

## Principles

- Measure three things separately, never one binary pass: **detection**
  (did the system notice the fault), **local recovery** (was the immediate
  fault corrected), **end-to-end success** (did the work still complete).
  The gap between local recovery and final success is where supervision
  hides. (Method per MAS-FIRE, https://arxiv.org/html/2602.19843)
- Inject faults only against scratch environments - a throwaway clone, mock
  adapters, local services - never a live repo, account or transport.
  (Chaos-engineering practice for multi-agent systems,
  https://arxiv.org/html/2505.03096)
- Record every run in the shape of templates/gated-run-evidence.md, so the
  evidence is auditable by someone who did not run the test.

## Stage 1 - Cold-start adoption

A fresh team with no project context adopts the blueprint on a new, trivial
repository from the kickoff material alone, with no outside explanation.

Pass: one full batch cycle completes - brief agreed, turn token issued,
build, review, QC gate, records archived. Metric: count of human messages
beyond the kickoff and the reserved gates. Target: zero routine messages.

## Stage 2 - Mechanism conformance (git bus)

Seeded faults on a scratch repo: an off-turn commit, a false-green batch
(one required suite unrun and red), a commit outside the seat's allowed
paths, a seat change with no owner decision record, a gated item with no
`owner_basis`. Pass: every seeded fault is detected mechanically (guard or
reviewer re-run), none needs a human to notice.

**Stated limits of the mechanism.** The guard is a local commit-msg hook:
it is bypassable (`--no-verify`, a client where it was never installed, a
push from another machine). `turn_seq` fencing detects and reconciles lost
races after the fact through rebase and dedup; it does not cryptographically
prevent an unauthorized or misconfigured writer from pushing. Server-side
branch protection and CI, where the owners configure them, are the
enforcement of last resort and are outside the runtime. Reading the
launcher source is inspection, not a security proof. Stage 2 therefore also
requires an independent reviewer re-check of every batch, on the same head,
as the backstop the hook cannot provide.

## Stage 2.5 - Cross-platform live communication (required; currently unproven)

The v1 goal is heterogeneous-platform AIs collaborating with real
communication beyond GitHub and no routine human relay. In the current
runtime, seats on other platforms join the git bus through a human pasting
prompts and relaying replies (interactive seats). That is human transport:
it does not satisfy the requirement, and a Stage 2 pass on the git bus must
not be reported as satisfying it. The loopback relay wakes co-located
automated seats but has not been exercised across platforms.

Pass requires, all observed live: two seats on two different platforms,
connected by an automated transport chosen by the runtime workstream,
execute one full batch cycle - handoff sent over the transport, ack
observed, turn advanced, work landed on the agreed branch, finding returned
over the transport - with zero human relay steps. Record per-transport ack
latency and the identity binding at both endpoints (roster
`verified_endpoint` + `commit_identity`).

Status: **capability gap**. Any claim of rare routine supervision is
blocked until this stage passes live.

## Stage 3 - Failure recovery

On a scratch setup:

- Kill an automated seat mid-batch: no duplicate writer (fencing holds),
  the supervisor restarts it with backoff, and after the restart limit a
  human gate opens instead of silent death.
- Transport message lost or delayed: no reassignment on silence. The sender
  retries with the same `turn_seq`, the receiver deduplicates, and state is
  reconciled from `STATE.json` - a missing ack is not treated as proof the
  remote side never acted.
- Stalled interactive seat: becomes a human gate, by design.
- Fresh-session resume: a brand-new session reconstructs head, turn holder,
  done/remaining and open gates from the repository record alone, with no
  human relaying status.

## Stage 4 - Instrumented soak

The only stage that speaks to sustained autonomy. One low-stakes real
project, run for a pre-agreed window (suggest 7 days), with an intervention
log: every human message timestamped and classified against the reserved
gates (concept, scope, spend, access, merge/go-live, brief change) by an
independent reviewer, not self-reported by the team.

Pass threshold agreed before the run - for example: zero routine
interventions outside the reserved gates for the full window. Report
detection, local recovery and end-to-end success separately. Publish the
result as evidence for that window and that project only, never as a
general proof of unattended delivery.

## What these tests do not prove

- Short passes do not compress into endurance: Stages 1-3 say nothing about
  days or weeks; only Stage 4 accumulates that evidence, in real time.
- Passing with one model mix says nothing about another.
- Public research references inform this methodology; they are not evidence
  that this runtime works.
