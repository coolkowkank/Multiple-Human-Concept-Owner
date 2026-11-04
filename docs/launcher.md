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
- **Webhook wake** (`TEAM_WAKE_WEBHOOK` env): outbound-only wake posts
  to any HTTPS endpoint the team configures (a chat-platform incoming
  webhook, an automation listener on another platform). No server of
  ours is exposed; delivery is best-effort and the bus stays the
  record. The URL is a secret and is never committed.
- **Adapters**: how a seat's response is produced: `mock` (scripted,
  no keys), `queue` (a response reasoned OUTSIDE the process - a human
  pasting into a chat session or an assistant-mediated agent - queued
  via `launcher respond` and applied through the real seat path),
  `cli` (any installed agent CLI), `http` (OpenAI-compatible endpoint,
  key from env), `interactive` (roster marker for a human-pasted
  session the supervisor does not manage). This is where AI from
  different platforms joins the same team.

## Staging, session ids and queue binding

- Operator routes stage exactly their own files: `launcher respond`
  and gate answers commit only their queue/gate file, and `init`
  commits exactly the layout files. A dirty worktree is never swept
  in; a pre-staged index is refused rather than included. Seat turns
  (`launcher seat`) still commit the whole mutation set by design -
  the bus refuses to pull into a dirty tree, so unrelated work must
  not live in a seat's clone anyway.
- Session ids are lazy: rendering a prompt or constructing a seat has
  no write side effects. The per-clone id is minted on the seat's
  first action and stored at `.git/team-seat-<name>.instance`, stable
  for that clone afterwards.
- Queue binding: `respond` stamps each queued response with the
  `turn`, `turn_seq` and head it was reasoned against. The runtime
  refuses a stale apply: turn/seq changed, or the stamped head is no
  longer an ancestor, or any non-queue file changed since. The queue
  is preserved for the operator; `respond` will not append behind a
  stale line - pass `--discard-stale` to drop stale lines and
  re-queue. The marker is removed before the response is applied, so
  it never persists into STATE.

## Operator hygiene (enforced, not advisory)

- Keep response scratch files OUTSIDE the seat's repo (or under
  `.team/`). A seat refuses to start its turn while the worktree
  carries changes outside its allowed paths and `.team/` - the turn
  commit stages the whole mutation set, and the commit guard would
  otherwise reject the swept paths after the mutation ran.
- `respond` and gate answers are atomic: a failed commit rolls the
  appended line back, so a retry cannot duplicate it.

## Commands

```sh
python3 -m launcher init --repo PATH --branch team-work --default-roster
python3 -m launcher seat NAME --repo PATH [--once]
python3 -m launcher launch --repo PATH [--stall-timeout N]
python3 -m launcher status --repo PATH
python3 -m launcher answer GATE_ID "decision" --repo PATH
python3 -m launcher serve --port 7431     # loopback relay
python3 -m launcher conform --repo PATH   # check .team against the evidence interface
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

## Assistant-mediated and interactive seats

A seat whose reasoning happens outside this process - a human pasting
into a chat session on any platform, or another agent reasoning at
turn time - joins through the `queue` adapter:

```sh
python3 -m launcher prompt NAME --repo PATH     # the exact prompt the
                                                # seat's model would get
# ... the operator reasons against that prompt, writes one JSON object ...
python3 -m launcher respond NAME --repo PATH --file response.json
python3 -m launcher seat NAME --repo PATH --once
```

`prompt` renders from live bus state only (brief, STATE, recent LOG) -
the operator gets no side-channel context a live model would not have.
`respond` validates and commits the response before the turn runs, so
a lost push race cannot lose reasoned work. `seat --once` then takes
the real path: lease, path checks, executed verify command, durable
record. A seat keeps one stable session id per clone (`.git/`), so a
returning operator session resumes and a second machine still stops.

This route carries GENUINE reasoning when the operator genuinely
reasons, but it is human/agent transport, not an autonomous model
call: evidence must name the reasoner and say "assistant-mediated" or
"interactive", never "live model".

## Real-model rehearsal routes

Ordered by what needs no new spend:

1. **Interactive / assistant-mediated seats** (above): existing chat
   sessions or agents reason at turn time. Zero new spend, at relay
   speed; transport is manual, reasoning is real if the operator's is.
2. **Existing authenticated agent CLIs**: a `cli` adapter per seat using
   a CLI the owner already has signed in on their own machine, within
   its subscription and terms. No new keys; availability depends on the
   owner's machine.
3. **Local models**: an `http` adapter pointed at a local
   OpenAI-compatible server (e.g. an owner-run one). No spend; quality
   depends on the local model.
4. **Free-tier model APIs** (verified against official docs 2026-11-04;
   re-verify before relying on them): Groq (`http` adapter,
   base `https://api.groq.com/openai/v1`, key env `GROQ_API_KEY` from
   console.groq.com; free plan exists, e.g. openai/gpt-oss-20b listed
   at 30 RPM / 1K RPD) and Gemini (`http` adapter, base
   `https://generativelanguage.googleapis.com/v1beta/openai`, key env
   `GEMINI_API_KEY` from Google AI Studio; free tier exists, per-model
   limits, free-tier content may be used to improve Google's products).
   Free tier still needs the owner's key and an explicit go decision.
5. **Paid APIs**: an `http` adapter with a provider key. Requires owner
   approval of spend before any key is used.

The demo and test suite use only `mock` adapters and local fixtures:
they prove the mechanism, not model behavior. Any real-model claim
will say which route and adapter produced it.

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
