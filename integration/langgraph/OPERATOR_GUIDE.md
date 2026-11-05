# Operator guide: langgraph_team.py (offline demos, closeout, live entry)

Status: work in progress. Every command below was run offline against this
branch head with scratch directories and a fake HOME. Nothing here was run
against the real router. Bus `done` means the team CYCLE finished. It is not a
quality result. Free route only: a model listed at price 0 is a listing fact,
not billing proof.

## Prerequisites

- Python >= 3.10 (tested 3.10.12), `git`, and for anything model-backed or
  closeout-related `bwrap` and `prlimit` on Linux.
- `pip install langgraph==1.2.19 langgraph-checkpoint-sqlite==3.1.3` (a venv is
  fine). The project `launcher/` is vendored in this directory; nothing else
  to install.
- Git needs a user identity (`git config --global user.name/user.email`) or the
  bus commits fail.
- `LG_VERIFY_SANDBOX=1` makes seat verify commands run through the bwrap shim.
  `live` refuses without it. Set it for every run you care about.

## Environment variables

| Variable | Meaning |
|---|---|
| `LG_VERIFY_SANDBOX=1` | Run seat verify commands in bwrap. Required by `live`. |
| `LG_OPERATOR_CONFIG=PATH` | Path (never the key) to the operator closeout config. Unset = quality unproven. |
| `LG_ALLOW_UNPROVEN=1` | Exit 0 from `run`/`live` even when quality is unproven. Still prints "quality unproven". |
| `LG_AUDIT_DIR=DIR` | Opt-in prompt/usage audit wrapper around http seats (audit_wiring.py). |
| `REQUESTY_API_KEY` | Set by `live` for the run only, from your key file. Do not export it yourself. |

`HOME` must be the account's real home. The Fenced usage ledger lives at
`~/.lg-http-usage`, and the reserve preflight refuses if `HOME` differs from the
account home (a moved ledger path looks identical to a deleted ledger).

## Commands

Arguments are positional. Missing arguments print a one-line usage message and
exit 2.

| Command | What it does | Exit |
|---|---|---|
| `init LANE DB` | New mock-seat lane. Refuses root, home, cwd and any non-empty directory. | 0 |
| `init-http LANE DB SEAT MODEL EPOCH` | New lane with ONE seat on a fenced http spec, `call_budget` fixed at 2. Prefer `live` for real use. | 0 |
| `run LANE DB [STOP_AFTER [THREAD]]` | Run the graph. `STOP_AFTER` N stops gracefully after N seat actions (resumable). Default thread `team-demo-1`. When the bus is done it runs the operator closeout. | 0 only if closeout allowed, or `LG_ALLOW_UNPROVEN=1`, or a deliberate stop that left the bus running. 3 otherwise. |
| `verify LANE DB [N [THREAD]]` | Re-verify a resumed run. | 0 / 1 |
| `status LANE` | Closeout status with no record: prints "cycle complete, quality unproven" (or "cycle not complete"). | 1 |
| `status LANE --record R --key-file K --checker-id C --path P [--path P ...]` | Re-verifies the signed operator record. `--repo` and `--branch` are fixed by the launcher and refused. | 0 only if closeout allowed; 1 otherwise; 2 for a repeated `--repo`/`--branch` |
| `live LANE DB CONFIG [THREAD] [--allow-fresh]` | Reproducible model-backed entry (below). | 0 only if closeout allowed or a deliberate `stop_after` left the bus running; 3 for quality unproven, blocked, failed or not done; 1 for a refusal |

Offline demo sequence (all three lanes must exist before `parallel_team.py`):

```
python integration/langgraph/langgraph_team.py init /tmp/demo/lane-a /tmp/demo/db-a.sqlite
python integration/langgraph/langgraph_team.py run  /tmp/demo/lane-a /tmp/demo/db-a.sqlite 2 team-demo-a
python integration/langgraph/langgraph_team.py init /tmp/demo/lane-b /tmp/demo/db-b.sqlite
python integration/langgraph/langgraph_team.py init /tmp/demo/lane-c /tmp/demo/db-c.sqlite
python integration/langgraph/parallel_team.py /tmp/demo
python integration/langgraph/controls_demo.py /tmp/lg-controls
```

`run` on a lane that reaches done without `LG_OPERATOR_CONFIG` prints
`closeout: {... "reason": "no operator config"}` and exits 3. That is the
expected outcome for the mock demos, not a failure of the cycle.

## Closeout (operator-owned)

See README "Closeout status" and "Operator-owned finalization" for the trust
model. Operator config (JSON, 0600, outside the lane): `checker_script`
(absolute path), `checker_id` (sha256 of `lg-sandboxed-checker/v1` + script
bytes), `artifact_paths`, `key_file` (0600, raw bytes, no trailing newline),
`record_dir` (0700), optional `timeout` (max 300). The checker runs inside bwrap
on a clean export of the committed files and must print exactly
`{"accepted": true|false}`. The checker must run the candidate in a CHILD
process and keep expected values and the verdict in the PARENT, and must set
the parent non-dumpable (`PR_SET_DUMPABLE=0`, return code checked, fail closed).
No checker ships in this repo for real work. The one used in
`done_gate_test.py` is a plumbing test only. Evidence is bounded to the files
and cases checked. It is not proof, and one checker covers one artifact type.

## `live`: model-backed multi-seat run (operator-run, never inside a seat)

Setup, once:

```
export LG_VERIFY_SANDBOX=1
python integration/langgraph/langgraph_team.py init /ops/lane /ops/db.sqlite
cp integration/langgraph/examples/live_config.example.json /ops/live.json
cp integration/langgraph/examples/brief_reply_rules.md /ops/brief_rules.md
chmod 600 /ops/live.json /ops/requesty.key /ops/brief_rules.md
```

Config keys (anything else is refused): `key_file`, `seats`, `brief_extra_file`,
`stop_after`, `preflight`. Seat keys: `model`, `epoch`, `budget` and optional
`max_tokens` (default 6000, max 8000). Seat names must exist in the lane roster
(`coordinator`, `builder`, `reviewer`, `qc`, `records`). `budget` is 1..8. Model
must be one of two allowlisted ids (see `HTTP_FREE_MODELS` in langgraph_team.py).
`epoch` is `[a-z0-9-]{1,32}` and names the Fenced log file. Config, key and brief
files must be regular, owned by you, mode 0600 and outside the lane. Brief rules
are capped at 16KB and appended once.

Order of checks (every refusal happens before any request or lane change):
files and modes, verify sandbox, seat specs, brief file, `preflight` keys,
reserve preflight, then a GET of the router `/models` listing (this request
carries your key and must show price exactly 0 for each seat model), then roster
writes and brief rules, then the run, then closeout.

Call budget: each seat `budget` is a ceiling on requests, and a format-correction
retry is a second request that comes out of the same budget. Fenced enforces a
lifetime cap of 8 requests across ALL logs for this account. The preflight sums
the budgets of every http seat that will run (configured seats plus any other
http seat already in the roster) and refuses if that exceeds what is left.
Check the number you are about to plan against the ledger, not against this
page. A single seat with `budget` 1 cannot use a correction round.

### Reserve preflight and the anchor

`reserve_preflight.py` only reads the Fenced logs. It reserves nothing, and
Fenced owns atomic reservation. It verifies the hash chain, line shapes and
sequence, halt lines, file names, and that the log dir is 0700 and yours (an
older 0755 dir must be `chmod 700`ed; contents untouched).

- A missing or empty ledger is `unestablished` and refused. `--allow-fresh` (CLI
  flag only, never in the config) asserts that this is a first run. It is
  ignored when `anchor_file` or a non-zero `expected_min_reserves` is set.
- `preflight.expected_min_reserves`: refuse if fewer reserves are recorded.
  A non-integer or negative value refuses. Zero is an integer but disables the
  minimum, so set it to the last verified total.
- `preflight.anchor_file`: a `reserve_preflight.snapshot()` JSON stored outside the
  log dir, in a private (0700) directory you own, mode 0600, which must already
  exist before `live` runs. It catches tail truncation and rewritten history.
  `live` refuses before any request or roster write unless the file loads as a
  `reserve-preflight/v1` snapshot object with files (null, blank, non-object,
  `{}`, wrong schema, unreadable or missing all refuse). There is no command that creates the first one. This script writes it only from
  a verified ledger, exits without writing otherwise, creates the file 0600 and
  refuses to overwrite an existing file. Run it from `integration/langgraph`
  with the real account HOME:

```
mkdir -p -m 700 /ops/private
python3 - <<'PY'
import json, os, sys, reserve_preflight as r
s = r.snapshot(r.preflight(0))
if s is None:
    sys.exit("ledger does not verify; no anchor written")
fd = os.open("/ops/private/reserve_anchor.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as fh:
    json.dump(s, fh)
print("anchor written; reserves =", s["reserves"])
PY
```

Then set `expected_min_reserves` to the printed `reserves` value. Never point
`anchor_file` at a file that was not produced by a verified preflight.
- The anchor covers only the log files named in it, each up to the line count and
  chain tip it recorded. It does not cover the whole ledger. A log that is not in
  the snapshot (a new epoch file, or a file deleted before the snapshot) is not
  checked against it, and a rewrite that keeps the anchored prefix is not seen.
  `expected_min_reserves` is the second check: it catches a drop in the total, not
  a swap. Neither is tamper-proof, since the same account can edit the ledger, the
  anchor and the config. Keep `expected_min_reserves` at the last verified total
  for this account (7 at the last real preflight; confirm against the ledger, it
  is not a universal number).
- After a run, if the ledger verifies against the old anchor, `live` replaces the
  anchor atomically with a fresh snapshot. It never raises
  `expected_min_reserves`; do that yourself.
- Cap across different model/epoch logs is not atomic across processes. Run ONE
  `live` at a time. Anchor, ledger and config are same-user storage: deleting
  the ledger and the anchor together is not detectable.

First run on an account with no ledger: `live ... --allow-fresh` with no
`preflight` block is the only supported path (the flag is an operator statement,
not proof). After that run, create the anchor with the script above and set
`expected_min_reserves` to the printed total. On an account that already spent
requests, always configure both `anchor_file` and `expected_min_reserves`.

The example config's `expected_min_reserves` is a text placeholder on purpose, so
an unedited copy refuses ("must be a non-negative int"). Replace it with your
account's last verified reserve total as an integer. No number in any example is
universal. The ledger on your account is the source of truth.

### What the example proves and does not prove

Different models per seat are a configuration, not an independence check. The
reviewer seat is instruction-guided, same-family review is not independent
review, and model quality is unqualified. Free-route runs spend a small lifetime
allowance (the ledger on this account shows how much is left), so they are not
free-unlimited.

## Rough edges (source gaps, not documented features)

- No command creates the first anchor except the script above.
- `reserve_preflight.py` run by itself applies the same anchor rule as `live`: a
  v1 snapshot with a non-empty `files` object and well-formed entries, else it
  refuses (exit 1). It still does not create anchors; use the script above.
- `init-http` hard-codes `call_budget` 2, so `live` is the only way to set budgets.
- `live` runs with `stop_after` from the config; `stop_after: 0` or absent runs to
  the end of the graph.
- Same-user storage: config, key file, anchor and ledger can all be changed by
  the same account. The anchor and minimum raise the bar. They are not tamper-proof.

## Recorded errors and prompts

When a seat's turn fails and the runtime records `TURN: <seat> error recorded (turn not taken)`, the entry stays in `.team/LOG.jsonl` for the operator, but error entries are not shown to seats in prompts (the prompt tail is the last 20 non-error entries, from one shared helper used by the seat and the audit wiring). This is what lets a queued response survive its own seat's recorded transient error; any other change to the repo since the response was queued still makes it stale and needs `respond --discard-stale`.

## Session leases and `launcher lease`

A seat's lease is written by a completed turn and refuses a different session (new clone or machine, or a restart with a new session id) as that seat for 900 seconds. It is a liveness hint: duplicate application is stopped separately by turn/turn_seq and the transaction. To inspect: `python -m launcher lease SEAT --repo REPO --branch BRANCH`. To end the wait after you have checked the old session is really gone: `... lease SEAT --release --holder HOLDER` (HOLDER must equal the holder shown; one operator commit changing only that lease entry in STATE.json, under the repo action lock). Queued responses bound to the older head are stale after a release and must be re-queued. This is cooperative, same-checkout locking, not a distributed lock: it does not make unattended multi-machine operation safe.

`lease` is manual and operator-attested only: nothing releases a lease automatically, and `--holder` is a compare-and-set check against the current value, not authority. Release only after you have independently confirmed the old session is dead. It refuses if the worktree `.team/STATE.json` differs from HEAD or the state or lease is malformed, and holder and seat names are limited to `[A-Za-z0-9._:@-]` (128 chars). Both modes run `git fetch`/rebase first (via the bus pull), so even show is not a pure local read.

## Relay hints

The relay (`launcher serve`, loopback only, bearer token) carries wake hints only; the git bus is the record and a missing hint costs latency, never correctness. A seat that loses the relay prints one line, falls back to git polling and retries the relay after 60 seconds (before, it stayed off for the life of the process). A relay restart changes its epoch and restarts sequence numbers; seats detect that and resync (before, they ignored every new hint). The server caps request bodies at 64KB, keeps the last 1000 hints and caps field lengths. Hints are not authenticated beyond the shared token and are never trusted as instructions. This does not make unattended multi-machine operation safe.

## Handoff validation

Before any write, a seat response is refused (SeatError, recorded, the turn stays with the seat) when: `handoff` is not null or the name of a roster seat; `status_line` is present but not a string; or `handoff` is null and `status_line` does not start with `DONE`. The last case used to leave `turn: null` with status `running`, a bus no seat could ever act on. DONE still closes only the cycle; closeout evidence is separate (see the closeout section).

## Handoff record (handoff/v1) and what the runtime does and does not undo

Each turn's handoff log row may carry an additive `record` (facts the runtime observed,
plus length-and-hash-only claims) or `record_error` (a fixed short code) with `record: null`.
A missing or null record is "no record" and is never evidence. A record that validates is
well formed, not proven: verify it against the real commit with `handoff_record.check_commit`.
The record is observed after verify and before the commit. It is not proof that tests passed
and not a pinned tested tree; gitignored paths are not seen; a change set over 200 paths gets
`capture_too_many_entries`. Prompts and the audit hash never include the record.

`bus.transact` has NO rollback (only `transact_paths` restores). Malformed responses are
refused BEFORE any write; a failure after the writes leaves them in the worktree, and a lost
push race replays the adapter call (at-least-once). Do not read this as whole-turn
transactional cleanup. A record failure never raises and never causes a retry by itself.

## Spending seats and the supervisor

A seat whose adapter is not a known non-spending type (mock, queue, interactive) is treated as
spending. The supervisor never terminates or restarts it on elapsed time, unknown liveness or
process exit; it opens one gate for an operator. A live declaration (`.git/lg-live-<seat>.json`)
is cooperative evidence only: it does not renew the lease and does not stop another launcher.
Residual: the classification is sticky in memory only (a supervisor restart re-reads the
roster), a clean DONE exit can raise one spurious gate, and a down seat with a new turn escalates.

Notes on the handoff record: `preexisting_dirty` is captured after the model call and before
this turn's writes (under the action lock), not at the start of the turn. If the
`handoff_record` module is not importable (the launcher needs its parent directory on
PYTHONPATH, as `python -m launcher` from integration/langgraph provides), handoffs are logged
with `record: null` and `record_error: capture_error`. The handoff log BODY already carries the
verify command text as before; only the record holds hashes.

## Write paths

A seat's `writes` keys are checked and written through one canonical relative path. Absolute
or backslash paths, control characters or NUL, `.` / `..` / empty segments, and any `.git` path segment (case-insensitive)
are refused before any write, as is any path whose existing component is a symlink (the final
file is opened with O_NOFOLLOW). A batch naming a file and a path under it is refused, as is a target under an existing non-directory or one that is an existing directory. An unexpected OS error during a write becomes a SeatError, but earlier writes of that batch are NOT rolled back. This is a
check-then-open on a same-user filesystem: it is not descriptor-relative, so a symlink swapped in
between the check and the write by another process is not covered. Not a sandbox.

## Crash residue (observed with real SIGKILL in scratch lanes)

`crash_recovery_test.py` kills a seat subprocess (mock adapter, scratch lane) at four points and records what a restart does:

- Before the adapter call: nothing changed; restart takes the turn.
- After apply, before commit: HEAD is unmoved but the working tree holds an advanced, uncommitted `.team/STATE.json`/`LOG.jsonl`. Before this fix the next seat built on that state and spent a model call whose commit the guard then rejected (a spending seat would lose a reserve). Now any seat refuses to start while `.team/STATE.json`, `LOG.jsonl` or `gates/*` are uncommitted, before any call. Nothing is discarded automatically: an operator inspects `git status`/`git diff` and commits or discards. The refusal is a typed `TornStateError`. Before a refusal the seat rechecks once after a short bounded pause (`torn_recheck_seconds`, default 2s), so a control writer's own commit window does not refuse; a dirty state that persists does. A refused seat appends nothing to the torn LOG and commits nothing (at 65be5c7 `Seat.run` appended one error row per attempt, observed 3 rows in 3 attempts), prints one BLOCKED line to stderr, and exits with status 75. The supervisor treats exit 75 as operator-blocked for every seat type including mocks: no restart, no gate, no log, no commit (a commit would sweep the torn state), one `[blocked]` console line. While any seat is blocked it also makes no bus write for other exits or stalls. Other seats keep running and are not terminated. After the operator commits or discards the residue, relaunch the supervisor. This is a refusal, not recovery: nothing is discarded, committed or reassigned automatically, the stale `lg-live` declaration is not removed (the pid binding rejects it), and a persisted transient window would also refuse.
- After commit: the commit landed. Without a remote the push is a no-op; with one, the next transaction pushes.
- During verify: in-domain files remain, a stale `.git/lg-live-<seat>.json` declaration stays until the next turn clears it, and a restart re-runs the turn (a replayed turn can replay a model call).

Not covered: a kill during the push itself (needs a remote, which the test does not create), `index.lock` residue, kills of a real adapter or http call, `bus.transact` has no rollback, and no unattended claim.

### Torn-state block: operational limits (accepted 8713d51)
- Exit status 75 is trusted as a number only. The supervisor does not verify that the process really saw torn state; any process exiting 75 latches the block.
- The block latch is in supervisor memory and never clears until the supervisor is relaunched, even if the operator already cleaned the tree.
- While the latch is set, EVERY other seat exit and every stall is console-only: no durable gate, no LOG row, no commit. Protection is reduced for the whole lane during that time. A spending seat that exits or stalls in that window gets no durable escalation, only a console line, so watch the console and do not treat silence as safety.
- The recheck pause is a plain `Seat.torn_recheck_seconds` attribute (default 2.0). It is finite but not validated and not settable from the CLI. Do not rely on it as a guarantee.
- Not an unattended-operation claim: an operator must read the console, clean the residue and relaunch.
- Ordering: the supervisor takes one snapshot of every exit status per poll and latches the block if ANY seat exited 75, before handling any other exit, so the order of seats within one poll does not matter. It cannot see the future: if another seat's exit was handled in an EARLIER poll than the seat that later exits 75, that earlier handling already wrote normally (restart log/commit, or a gate) and may have been committed before the torn state appeared.

## Same-checkout handoff window
Supervised seats share one worktree. A seat writes its handoff to the worktree inside the action lock and commits afterwards, so a next seat could see `turn == itself` before the commit landed and race it on the git index. A seat now takes the action lock briefly and re-reads state before its preflight. The lock waits at most 30s and then raises BusError, so a waiting seat can exit if a holder is stuck longer. Separate clones with a remote do not share the lock, and it is advisory (cooperative). See ENDURANCE_RESULT_2026-11-05.md for what the scripted mock runs did and did not show.

## Optional pin-consistency report (`pin_check`)

`done_gate.finalize` adds a `pin_consistency` key only if the operator-owned config has a `pin_check` object (`reviewed_commit` = full lowercase 40-hex, `reviewer_seats`, `verdict_path`) next to `artifact_paths`. Without it the result is unchanged. It is a report, not an acceptance gate: `terminal_done`, `closeout_allowed` and the label never change, verdict text is never read, and `pinned` does not mean accepted, tested or independently reviewed. A seat response must never write this config.

`pinned` needs, all from committed git objects: the reviewed commit is an ancestor of HEAD; exactly one single-parent `TURN: <seat> acting` commit for a configured seat sits directly on it; exactly one handoff row from that seat with a shape-valid record that passes `pin_check` and `check_commit` and has its own verify run; that row is in HEAD's committed LOG; `verdict_path` was added or modified in that turn and HEAD still holds the same blob; the listed artifact blobs are equal at the reviewed commit and HEAD; HEAD did not move during the check. Otherwise `not_pinned` with reasons, or `unverifiable`.

Limits: files outside `artifact_paths` can change and stay pinned; check-then-read is not TOCTOU-hardened; `record_ok` is shape only; a reviewer seat name is a claim; same-model review is not independent.

Queue-assisted lanes: the operator's "response queued" commit sits between the reviewed commit and the reviewer turn, and a null-verify reviewer response has no own verify run. In the RW2 lane the report was therefore `not_pinned` for both. The check does not accept a queue commit in between; that would be a separate reviewed change.

## Runner roles through the shared fence (source candidate, no live use)

`runner_lane.FencedRunner` + `live_runner_step` let the Ryan runner roles
(researcher, verifier, ryan) make a request ONLY through the shared
fenced adapter: reserve-before-I/O, hash chain, shared halt and
`HTTP_LIFETIME_CAP` (8) in `~/.lg-http-usage`. `ryan_cycle.http_post_factory`
is not used (a test checks the lane never references it). The vendored
runner is unchanged (md5 pin intact). Nothing here calls a real provider;
the shipped lane `post` is still the refusing one.

Flow: the runner reserves (its ledger) -> its `before_io` seam calls the
lane gate, which makes the SHARED reserve (`adapter.reserve()`, same
checks and lock as `complete()`: key, chain, halt, cap, allowlist) ->
the runner's pre-I/O boundary -> `post` executes only against that
reservation (`adapter.execute(token)`). If the gate cannot reserve, no shared
reserve exists, so it writes a runner halt and the runner's own boundary
records a factual `not_sent`. The runner reserve stays consumed (one
runner envelope slot burned with no request); preflight reduces but does
not remove that.

Two histories, both kept, neither rewritten:
- Runner ledger (`docs/team/ryan/ledger.jsonl`, envelope `ENVELOPE_TOTAL`,
  own halt/allowance state): 6 historical reserves, made through the
  independent path, so NOT in the shared 8.
- Shared fenced log: 8 of 8 reserves consumed.
A new runner request counts in BOTH (one runner reserve, one shared
reserve); either refusing stops it. They are different counters, not 8
requests in total. No cap, envelope or halt is changed by this code.

Outcomes: raw HTTP 200 with content and explicit zero cost = `ok`
(parsed-JSON validity is still the runner's own format precheck). 4xx =
`http` (the runner halts on 400/401/403/404/422/429). Redirect, 5xx,
malformed or empty 200, timeout, socket error, or any exception after
the reserve = `unknown` (consumed, halt). Nonzero or invalid cost (200,
or in a bounded 2000-byte error body read with a 5 s deadline checked between
256-byte reads, cost only, no text kept; one blocking read can still last
up to the socket timeout) halts the
shared log and the runner. Single use is durable: execute() appends a
hash-chained `exec` claim under the log flock, after re-checking chain
and shared halt, BEFORE any I/O, and refuses a rid that already has an
exec, exec-refused or result line (threads, copied/rebuilt tokens and a
second process are tested). A reserve is identified by a random rid, not
by count. States per rid (`fenced_http.reserve_states`): reserve() only =
the fence never started a request (consumed, known not sent by this
fence; only reserves written by the reserve()/execute() protocol carry
that marker; a reserve written by complete(), or a legacy line without a
marker, stays `unknown-*` until a result exists because complete() sends
without an exec line, and execute() refuses such reserves); reserve+exec-refused = stopped before start (for example a halt
written after the reserve); reserve+exec without result = started,
outcome unknown, never re-executed; plus result = settled. A crash
between gate and post is therefore reserve only. The gate binds to the last
runner ledger line, which is safe only with ONE process driving a runner
root (the runner's own advisory single-writer expectation); concurrent
processes on one root are not supported by this lane. If the runner's
boundary refuses after the shared reserve (assignment or grant changed),
the shared reserve is consumed without a request. A halt written by
another process after the reserve and before the exec claim stops the
request; after the claim it cannot (at most once).

Differences from `complete()`: the log lock is not held across the
request on this path (it is on `complete()`); `complete()` behavior is
unchanged. `post` without a reservation (seam not called, model or
parameters mismatch) makes no request and raises Halt, leaving a runner
reserve with no result for an operator to reconcile; a test fails if the
pinned runner stops calling `before_io`, which this lane depends on
(declared test seam in the vendored runner).

Limits: the adapter sends `max_completion_tokens`, the old runner post
sent `max_tokens`; provider equivalence is not verified. The adapter
keeps 4 usage keys and `finish_reason`; the old path's diag shape probes
are not carried. The allowlist is the two free models;
`google/gemma-4-31b-it` is refused. The prior Gemma outcome (unknown,
consumed, halt not cleared) is untouched. Same-user process, cooperative
checks, no TOCTOU hardening beyond the log lock.

Authority wording: a runner allowance is an operator-issued technical
token, not a user-authored or user-signed approval of a call. Its HMAC
authenticates only whoever holds the key file. This candidate creates no
allowance, fetches no key, clears no halt and makes no request. A future
call needs separate operator decisions (shared cap, envelope, halt
clearance with an external-condition note, a signed allowance, a current
route record).

## Patched vendor delta (successor window shape)

`runner/ryan_cycle.py` and `runner/make_allowance.py` are no longer byte-exact
copies of upstream. Offline source change only; no constant, cap, envelope,
question budget, allowlist, assignment, key or ledger line is changed by it.
Pins: ryan_cycle.py md5 `7aa68e610e7e9da3659b592fb98a96f2` (was
`ae08fb3c6dae3744e4a505ebc2428d8c`), make_allowance.py md5
`e81caf38b546ee4b94f1de34dea4ac42` (was `4f3d08fe51e428089c6f62517820758c`).
`runner_succession_test.py` pins both md5 values so a later accidental edit is
noticed.

Delta:
- `_shape_ok`: a window with `succeeds` may now have roles exactly
  `["verifier"]` or `["verifier","ryan"]` (models for exactly those roles,
  `max_requests` equal to the number of roles). A ryan-only successor stays
  refused. Before, a successor had to be one verifier request.
- `_succession_reason`: the verifier must be present and must not be a model any
  earlier bound window used. The novelty rule is verifier-only; a ryan step's
  model is the assignments.json ryan model, still re-checked at the I/O boundary.
- `make_allowance.build`: a successor may carry a ryan step only when the
  requested ryan model equals the assignments.json ryan model.

Unchanged and tested: the prior window must be terminal (allowance-stop); the
successor names the prior id and digest, the same lineage and claim-set
fingerprint, and a new id; the cap+1 relaxation needs a validated actual
succession; baselines must equal the lineage counts; the ryan step runs only
after the verifier step's allowance-done; a failed, unknown, stale, stopped or
expired window blocks ryan and any retry; question budget and envelope still
apply at each step. This is a technical grant mechanism issued by an operator
key holder, not a user approval.

Budget note (reviewer step probes, same-model review, offline fixtures only):
with a question budget that allows the verifier step but not a following ryan
step, the verifier step runs and the ryan step is refused with 0 calls
(needs-human). The window stays open after the verifier's allowance-done until
its TTL ends, so a later budget decision could still allow the ryan step
inside the window. Nothing here changes any constant. The source delta and its
review are offline evidence; they qualify no runner role.

