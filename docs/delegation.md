# Delegation: act without asking, ask only when blocked

> Status: proposed, not yet tested with a fresh multi-owner team. See docs/proposed-vs-tested.md.

Once the brief and the roster are agreed, the Coordinator runs delivery
without asking again inside the standing delegations below. It asks a
human only when something is genuinely blocked or outside what was
delegated - and then it asks the one unresolved decision, with options
and a recommendation, after doing the research itself.

## 1. The delegation record

Each owner records a standing delegation in their own words, on their
own channel, captured in DELEGATION.md in the project repository:

  Owner | Delegated decisions | Delegated actions | Limits (spend,
  audience, accounts) | Revocation

- A delegation binds only the owner who gave it. It never covers another
  owner's accounts, assistant or audience.
- The repository file is a record, not a grant. If a delegation is
  disputed, the owner's own channel is the source of truth, not the
  repo.
- Revocation is immediate when the owner says so, in any words.

## 2. Act without asking (inside the delegations)

The Coordinator and the delivery roles proceed without per-step
approval on:

- routine batches: builds, fixes, tests, docs, commits and pushes to
  the agreed branch, under the turn token;
- assignments, priorities and conflict resolution inside the agreed
  brief;
- research, proposals and options for anything not yet decided;
- progress reports at milestones, blockers and results - not status
  polling.

## 3. Ask only when blocked

A blocker is a decision the Coordinator cannot take inside the
delegations:

- an unresolved question of fact after the Coordinator has checked the
  available sources itself;
- a genuine choice the delegations leave open - asked with options and
  a recommendation, in one batched message, not an interview;
- anything outside the delegations (section 4).

## 4. Always ask (never delegated by default)

Each of these needs the affected owners' own word, every time, unless
a written delegation explicitly covers it, with its limits:

- spending money or credits, including per-action and total limits;
- security, access and credential changes;
- going live or merging to the main branch;
- contacting third parties or representing an owner externally;
- changing the agreed brief or scope.

One owner's yes never covers a shared commitment. Who must agree is
what the brief and the delegations say: no invented quorum, and no
assumed all-owner approval for routine work already delegated.

## 5. Roles, not identities

Rules bind to roles (Coordinator, Builder, Reviewer, QC), never to a
hard-coded assistant name or account. Role assignments live in one
table in the roster; changing who fills a seat updates the roster, not
the rules. The writer and the independent QC are never the same
assistant.

## 6. One unambiguous handover

A handover is one written message that both ends the current turn and
names the next actor. A partial question to another role does not move
the turn. While a handover is disputed, the last unambiguous turn
stands and nobody else writes.

## 7. Evidence and resumption

Decisions and verdicts cite verifiable evidence: a commit hash, a file
and line, a test count actually run. Verified work stays closed and is
not reopened. A new session resumes from the recorded state. Re-run
the suites a change touches, plus the full baseline when the change
or a QC gate warrants it; never claim a full green from one suite's
result.

## 8. Capability honesty

The Coordinator reports what it has actually done and seen work: what
is verified, what is planned, what is unknown. "Act without asking" is
a working agreement, not a new capability: sessions still cannot start
or message each other unless a real session-to-session route exists
and has been seen working. Until then, the humans remain the transport
- but only as transport, not as decision-makers for delegated work.
