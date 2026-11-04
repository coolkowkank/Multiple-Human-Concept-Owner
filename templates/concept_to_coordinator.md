# Concept to Coordinator - the agreed brief

> The one agreed brief between the concept owners and the delivery team.
> The Coordinator reads its orders from here, not from side conversations.
> Clarifications never override this brief. Every concept change is recorded in the change history below.

## Concept

`<What we are building and why, in the owners' words.>`

## Goals

- `<goal statement>`

## Non-goals

- `<what this project explicitly does not do>`

## Scope and constraints

- `<scope, budget/spend limits, deadlines, technical constraints>`

## Acceptance criteria

- <how the owners judge that the concept is delivered - name the environment
  where proof is required (mock / local / hosted), so evidence from a weaker
  environment cannot close the criterion>

## Definition of finished

<What must be proven, at one named commit, for "done" to be called by rule
instead of a fresh human call. A merge or go-live grant points to this
section, never to an open-ended "when everything is finished".>

## Accepted limits

<The named residual limits the owners accept may stay open without blocking
merge or go-live. Anything not listed here blocks until the owners accept,
waive or require a fix (see Stated limits in templates/qc-verdict.md).>

## Stop conditions

<What the team may not resolve itself and must always escalate to the
owners, regardless of the standing delegations.>

## Definition of finished

<The objective checks that make a cycle complete: which commands must
exit 0, which artifacts must exist and pass their conformance checker,
and the closing condition (a DONE status_line that sets status=done and
turn=null). The conformance tooling rejects a running cycle that claims
completion, so state the checks here instead of implying them.>

## Status

<One line, kept current by the Coordinator: whose turn, what is done, what
is next. Routine status questions are answered here, not by waking seats.>

## Decisions log

| Date | Decision | Evidence | Agreed by |
| --- | --- | --- | --- |
| | | `<decision-record ID or channel reference>` | |

## Change history

| Date | Change | Reason | Agreed by |
| --- | --- | --- | --- |
| | | | |
