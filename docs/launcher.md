# The team launcher: operator guide

> Status: v0.1. The mechanism is implemented and covered by mechanism
> tests; live-model operation and multi-day endurance are not yet
> proven. See docs/proposed-vs-tested.md.

## What it is

`launcher/` turns the blueprint into a running team. One command starts
a supervisor that keeps every automated seat alive; seats communicate
through a shared coordination bus in the project repository, write only
under a mechanically enforced turn token, and ask humans only through a
gate queue. Stdlib-only Python 3.10+: nothing to install.

## Concepts

- **Bus** (`.team/` in the project repo, on the working branch):
  `STATE.json` (turn, turn counter, leases, status), `LOG.jsonl`
  (append-only seat communication), `roster.json` (seats and
  adapters), `brief.md` (the agreed brief), `gates/` (human questions
  and answers). Git is the durable record and the v1 work platform.
- **Turn token**: `STATE.json.turn` names the one seat allowed to write.
  A commit-msg guard (`launcher guard`) rejects commits whose `TURN:`
  line is not the HEAD turn holder or that touch paths outside the
  seat's roster allowance. Humans and the supervisor commit with
  `human:` / `supervisor:` prefixes, outside the seat protocol.
- **Lease**: a seat process claims its seat in STATE; a second process
  for the same seat stops instead of acting (the duplicate-session
  failure from the reference project). A crashed seat's lease expires
  so its restarted process can take over.
- **Supervisor**: starts one process per automated seat, restarts
  crashes with a limit, detects a stalled turn and restarts or
  escalates, and prints open human gates. Interactive seats (a human
  pasting prompts into a chat session on another platform) join the
  same bus; the supervisor cannot restart those, so a stalled
  interactive seat becomes a gate.
- **Relay** (`launcher serve`): an ephemeral 127.0.0.1 + bearer-token
  signal channel so seats wake each other in milliseconds instead of
  waiting out a poll. It carries hints only; the bus remains the
  record, and seats fall back to git polling when the relay is down.
  Loopback-only by design - exposing it is an owner security decision.
- **Adapters**: how a seat's AI is called: `mock` (scripted, no keys),
  `cli` (any installed agent CLI), `http` (OpenAI-compatible endpoint,
  key from env), `interactive` (human-pasted session). This is where AI
  from different platforms joins the same team.

## Commands

```sh
python3 -m launcher init --repo PATH --branch team-work --default-roster
python3 -m launcher seat NAME --repo PATH [--once]
python3 -m launcher launch --repo PATH [--stall-timeout N]
python3 -m launcher status --repo PATH
python3 -m launcher answer GATE_ID "decision" --repo PATH
python3 -m launcher serve --port 7431     # loopback relay
python3 -m launcher demo                  # self-checking full cycle
python3 -m unittest discover -s tests     # mechanism test suite
```

## Starting a real team

1. `init` the project repo and fill `.team/brief.md` from
   `templates/concept_to_coordinator.md`: goals, non-goals, done
   definition, accepted residual limits, stop conditions.
2. Fill `.team/roster.json` from `templates/roster.md`: one entry per
   seat with role, allowed paths, adapter, human owner. Keep QC a
   different seat from Builder.
3. Record owner delegations and gates (decision/delegation templates).
4. `launch`. The Coordinator seat takes the first turn.
5. Answer gates as they open. `status` shows the one-line progress
   chain, so nobody needs to ping the team for updates.

## Real-model rehearsal routes

Ordered by what needs no new spend:

1. **Interactive seats**: existing chat sessions (any platform) join as
   `interactive` seats; humans paste prompts and replies. Zero new
   spend, uses sessions that already exist, at human relay speed.
2. **Existing authenticated agent CLIs**: a `cli` adapter per seat using
   a CLI the owner already has signed in on their own machine, within
   its subscription and terms. No new keys; availability depends on the
   owner's machine.
3. **Local models**: an `http` adapter pointed at a local
   OpenAI-compatible server (e.g. an owner-run one). No spend; quality
   depends on the local model.
4. **Paid APIs**: an `http` adapter with a provider key. Requires owner
   approval of spend before any key is used.

The demo and test suite use only `mock` adapters: they prove the
mechanism, not model behavior. Any real-model claim will say which
route and adapter produced it.

## Known limits (honest)

- The commit-msg guard is local enforcement: a determined writer can
  bypass a client-side hook. Server-side enforcement needs branch
  protection and CI on the repository host, which is an owner account
  decision and is not set up here.
- Seats poll the bus; cross-machine teams share a git remote, so
  polling cadence vs. host rate limits is a real trade-off. The relay
  removes in-machine latency only.
- No sustained multi-day run has happened. Crash/restart/resume is
  tested in short fault-injection runs; days-long endurance is a staged
  soak test still ahead.
- HTTP/CLI adapters are implemented but not yet exercised against live
  models.
