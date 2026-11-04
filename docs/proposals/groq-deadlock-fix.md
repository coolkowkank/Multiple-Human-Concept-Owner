# Proposal: Builder batch - fix null-handoff deadlock + stall-clock bug

Status: PROPOSED (2026-11-04). Awaiting owner GO. Grounded in the bounded
Requesty experiment's terminal record (branch `live/requesty-tinylib-experiment`,
head e51fae6).

## Evidence (from the live run, all timestamps UTC 2026-11-04)

1. **Null-handoff deadlock.** The builder seat returned `handoff: null`
   (11:13:18); the runtime wrote `STATE.turn = None`; every seat then idled
   forever: seats act only when the turn names them
   (`runtime.py act_once`), the supervisor's `_check_stall` returns on a
   falsy turn, and the first-turn seed fires only while status is
   "forming". The bus hung silently from 11:13:18 to 11:19:29 with no
   escalation; an operator commit re-issued the turn to the coordinator.
2. **Stall-clock timezone bug.** The supervisor logged
   "turn stalled; restarting seat" ~4-5s after EVERY handoff (builder
   11:12:59, coordinator 11:19:30, qc 11:19:55).
   `supervisor._check_stall` uses `time.mktime(time.strptime(turn_since,
   "...Z"))`, which parses a UTC stamp as LOCAL time; in a UTC+2 container
   every new turn is instantly "2 hours stalled". The watchdog SIGTERMs
   the fresh seat on its first check; restart recovers it, but a kill
   landing mid-request would burn budget and could corrupt a turn.
3. **Reviewer seat skipped (severe).** The coordinator routed
   build -> QC -> builder-confirm -> DONE without ever engaging the
   Reviewer seat (0 reviewer requests). The runtime does not require the
   review loop, so a "DONE" can carry no independent review at all.
   This deserves an acceptance guard (a DONE without a reviewer verdict
   cannot be accepted), but that is unbounded architecture work and is
   NOT bundled into this batch - tracked as a separate follow-up.

## Scope (Builder implements, own commits, branch live/groq-dev-5)

Base: the `team-launcher` tip containing this proposal.

- `launcher/supervisor.py`: parse `turn_since` as UTC (e.g.
  `calendar.timegm` or timezone-aware `datetime`); add a regression test
  pinning a non-UTC local timezone.
- `launcher/supervisor.py`: when `status == "running"` and
  `turn is None`, treat as a routing failure: re-issue the turn to the
  coordinator; escalate to a human gate after 2 consecutive occurrences.
  A null handoff WITH a DONE status line is a valid terminal state
  (`runtime.py` already sets turn=None on DONE) - the routing-failure
  path must fire only on a null turn that is NOT a declared DONE, never
  reject null handoffs indiscriminately.
- `launcher/runtime.py` / `launcher/adapters.py`: when a seat response
  lacks a usable `handoff`, record a validation note in the log entry
  (do not silently write `turn: null` without a marker). NEVER
  fabricate, rewrite or silently correct the model's routing decision -
  that would hide protocol failures. Enforce valid bus state and make
  the failure loud: validation marker + routing-failure escalation as
  above. The model's actual output stays in the record untouched.
- `launcher/cli.py` `default_roster()` / docs: exclude `__pycache__`
  from what seats can commit (the run committed .pyc files).
- Tests for each behavior; full suite must pass.

## Bounds

- Builder: Groq `gpt-oss-120b` via @coolkowkank-bot, free plan; key
  re-verified 2026-11-04 (models endpoint 200, model listed). Account
  tier/billing is console-only; free plan with no payment method is the
  standing record - console confirmation optional before GO.
- Budget: max 12 Groq model calls for the whole batch, including fixes
  requested in review. Calls counted from the bot-side run records.
- Review: @instinct-christina reviews the pinned commit directly
  (Builder <-> reviewer loop); the Coordinator assigns the task and
  checks the completed loop.
- No merge to main; no history rewrite; no provider or account changes.
