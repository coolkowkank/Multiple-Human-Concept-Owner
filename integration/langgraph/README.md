# LangGraph team orchestration (integration in progress)

**Status: work in progress, not merged readiness; branches exist so the work
is visible and reviewable. The default demos use mock (scripted) adapters.
Separate live/* branches record bounded free-route runs (see the LIVE_RUN_*
files). No paid hosting. Bus `done` is the team cycle only, not a quality
result: see "Closeout status".**

## What this is

An orchestration layer that drives the project's existing team machinery
(`launcher.runtime.Seat` over the git bus) through a LangGraph state graph
(LangGraph 1.2.19):

- LangGraph owns scheduling, conditional routing, parallel lane execution
  and durable checkpoints (`SqliteSaver`, enforced OUTSIDE the team repo
  so the bus never commits it; a checkpoint path inside the repo is
  refused).
- The project's own code keeps owning turn mechanics: lease, prompt build,
  adapter call, roster/verify validation, guard-hook commit, handoff and
  archive. The seat set is read from the project's roster
  (`launcher.cli.default_roster`), not hardcoded here.

Files:

- `langgraph_team.py` - single-lane orchestrator with execution-time
  fences (below), durable resume, graceful stop, and the operator control
  channel (assign / pause / update-instructions / resume).
- `parallel_team.py` - parent graph running several independent lanes
  concurrently, with one shared seat gate capping simultaneous seat
  actions across all lanes, plus a deterministic no-network overlap test.
- `controls_demo.py` - scripted operator-intervention run proving the
  four controls below.
- `launcher/` - vendored copy of the project's own seat runtime (bus,
  roster, adapters, CLI), copied byte-exact from
  `ryan-continuous-offline` @ e881384dbfb99748359a19a944cb6575b4961f63
  (the accepted chain: 46fa7284 baseline + e5ae0a0 queue-binding/argv
  hardening + 87e4250 transact_paths clean-index/declared restoration +
  763a01a pre_apply hook/action lock + e881384 thread-owner lock,
  per-retry release, in-lock freshness recheck). Project code,
  unchanged; included so the documented commands run as-is. Scope note: this predates the later local allowance-window and
  verified-revision-binding increments (not yet pushed anywhere); none
  of those guards are integrated or claimed here.

## Execution-time safety fences

Sync-time checks alone would be racy, so `seat_node` re-verifies
IMMEDIATELY before acting:

1. Bus status must be `running` and the written turn must name this seat
   - a resumed pending seat after an operator halt is refused.
2. The roster adapter spec must be an allowed type: `mock` (scripted,
   local) or `queue`. A queue seat applies OPERATOR-AUTHORED responses
   queued through the project's own `launcher respond` channel. The
   queue is an EFFECTS channel, not inherently bound: the guard
   REQUIRES every queued response to carry the `_queue` binding
   (turn/turn_seq/head) at the adapter boundary - a raw hand-written
   line is refused and left unconsumed. Scope notes: (a) the
   independently reviewed boundary was mock-only; admitting `queue` is
   new in this increment and has not had the same independent review;
   (b) mock/queue payloads are trusted operator-authored fixtures -
   authorship is a trust decision, NOT authenticated provenance;
   (c) response `verify_command`s run with shell=True in the seat
   runtime, so the guard screens them against a conservative allowlist
   (simple python3/pytest commands, no shell metacharacters, relative
   paths only) - a SHALLOW guard, not a sandbox; (d) no zero-network
   claim is made for response payloads, only for the transport. The CONSTRUCTED adapter is then checked by exact class
   identity against the preselected safe constructor for that spec (the
   imported class object itself, not a forgeable `__name__` string).
   Provider-calling adapters (http/cli/live) are refused at sync and at
   execution. No provider call is possible from this graph.
3. A `GuardedAdapter` wrapper re-validates status, turn, OPERATOR
   CONTROL (mode and instruction_seq) and adapter identity AT the
   adapter call - inside the seat transaction, after the lease claim.
   An operator pause/halt, instruction update or roster swap landing
   between the pre-checks and the call (including a pause issued while
   the seat waited on the seat gate) raises `SeatError` BEFORE this
   turn's commit; the in-memory lease/turn changes are never committed.
   The bus transact itself is pull/commit/push/retry - no isolation,
   no rollback of already-committed state.
   The control file fails CLOSED: anything but an explicit dict with a
   known mode and integer instruction_seq - missing file, bad JSON,
   wrong type, unknown mode, missing/bool seq - means hold, never run.
   The graph reads control, team state and roster from the COMMITTED
   state (`git show HEAD:`), never the worktree; a committed non-dict
   state or roster document is a clean refusal (SeatError), never an
   uncaught failure and never an action: an uncommitted or failed control change is
   invisible; control takes effect exactly at commit order. Operator
   commits stage exactly their own paths (`transact_paths`), precheck a
   clean index BEFORE mutating, and restore the worktree from HEAD on
   failure, so a control commit can neither sweep an in-flight seat's
   changes nor leave a dirty control value behind.

   Control semantics: the guard checks at FOUR points - before the
   adapter runs, after it returns, at the seat's accepted pre-apply
   hook INSIDE the transaction (before any write/verify/handoff), and
   the upstream runtime itself re-reads fresh state under the shared
   action lock after the slow adapter call, refusing a turn/turn_seq
   that moved while the response was produced. Operator control writers
   take the same per-repo action lock, so a control change is either
   fully before the seat's final under-lock read or fully after its
   commit. Accepted scope limits: the lock is advisory and covers this
   checkout's cooperating writers only (direct git writes and other
   clones are not isolated); a seat can hold the lock through
   verification (up to 600s) while the writer timeout is 30s, so a
   pause during verification surfaces as BusError, not an instant or
   guaranteed-timed pause; push-retry is at-least-once. Pause NEVER
   cancels in-flight work - it refuses application of responses that
   complete after it lands, and blocks the next seat action.
4. Dirty-input fence: the seat runtime builds its adapter and prompt
   from WORKTREE files (roster spec, brief, queue lines) and the bus
   commit stages everything, so an uncommitted same-class input - a
   locally edited roster naming a script adapter, a hand-edited brief
   with no instruction_seq bump, a raw queue edit - would pass a
   committed-view fence yet drive construction and be swept into the
   turn commit. The graph therefore refuses to act while any of the
   seat's exact committed inputs (`.team/STATE.json`, `roster.json`,
   `brief.md`, `CONTROL.json`, the seat's queue file for queue specs)
   diverges from HEAD - checked at construction and at every boundary
   check under the action lock. COMMITTED changes stay permitted:
   committed reads and the queue-binding staleness checks handle them,
   and mid-turn queue commits are ordinary operation. Unrelated files
   elsewhere in the repo do not block a turn. On top of that, a
   committed-context digest (brief bytes + the seat's FULL roster
   spec) is captured at construction and re-compared at every
   boundary: a committed brief edit with no instruction_seq bump or a
   committed spec change (e.g. allowed_paths emptied) mid-call refuses
   the stale response, because the seat still holds the OLD prompt and
   adapter. Queue files are exempt from the digest - the `_queue`
   binding checks own queue staleness.
5. Refusals (including `SeatError` from the project's own stale/lease/
   verify machinery) are recorded and route to the terminal node, never
   swallowed.
6. Repo and checkpoint paths must be canonical: `realpath` is applied
   and any symlink/alias spelling is refused, so the checkpoint-outside-
  -repo and resume-identity checks cannot be bypassed by a linked
   parent directory.
7. `run_graph` resumes a thread only if the stored repo and checkpoint
   path exactly match the requested ones (fail closed on identity
   mismatch).
8. `init_repo` refuses root/home/cwd, non-directories, and ANY non-empty
   directory; it never deletes data (recreating a demo is a manual
   delete).

## Operator controls (assign / pause / update / resume)

One channel: `.team/CONTROL.json` inside the git bus, mutated only
through guard-exempt `operator:` commits - the same bus every seat and
sync reads, not a competing state path.

- PAUSE: control mode `pause` holds the graph in a paused node (durable
  checkpoint, no seat acts) until RESUME restores mode `run`.
- UPDATE INSTRUCTIONS: rewriting the brief bumps `instruction_seq` and is
  an ordinary non-queue commit - every queued in-flight response bound
  to the old head is then stale by the project's own head-binding rule
  and the seat REFUSES it (recorded, queue preserved for the operator).
  Old instructions can never be applied after an update.
- RESUME / resolution: the operator discards stale lines and re-queues
  through `launcher respond --discard-stale` (the project's CLI), then
  the team completes.
- ASSIGN: new brief + turn + status through the same operator commit
  path; a closed team runs the new assignment.

`controls_demo.py` proves all four on one lane: pause held mid-run, the
in-flight queued response refused as stale after the instruction update,
cycle 1 completed after operator resolution, and a second assignment
(subtract feature) ran end to end - 10/10 checks.

Caveat: these are mechanism demos on mock/queue lanes. The controls are
NOT yet reviewed or claimed safe as a live-intervention boundary for a
real model team.

## Demonstrated (mock, no network, no keys, no spend)

- Full five-seat cycle per lane, verified against the project's own demo
  checks (turn token, handoffs, verify exit codes, guard hook, QC verdict,
  archive) in three parallel lanes - 36/36 checks.
- Graceful stop after N seat actions and resume in a NEW OS process from
  the sqlite checkpoint (step trace records both pids).
- Lanes genuinely overlapping in wall-clock time; gate high-water exactly
  at its cap; deterministic 5-branch no-network overlap test.
- Fence probes: seat refused on wrong turn, after operator halt, on a
  swapped non-mock roster, on thread/repo identity mismatch, on a
  checkpoint path inside the repo, and init refused on unsafe paths.

## Runner lane integration (offline, refusing post)

`runner_lane.py` drives the ACCEPTED Ryan runner (`runner/ryan_cycle.py`,
byte-exact accepted tip `3b09eea8ccacebc4e5d3131e4b58fa9cf58a0fe2`, chain
through tag `source-88a610a`) from inside a LangGraph node. The
provider-call injection point (`post`) is explicit and REFUSING as
shipped: it records the attempt and returns an 'unknown' transport
outcome without any network access, and the runner's own settle() then
consumes the reserve and halts - so even if a gate mistakenly passed,
no call can escape and the attempt is visibly consumed, never retried
silently.

The runner's own guard chain fires for real BEFORE that point: durable
provider halt, lifetime qualification envelope, per-question/lineage
caps, route and free-listing gates, the signed allowance window with
durable lineage+claim binding (01a495f), and the verified-revision
binding (88a610a). A live post is not provided anywhere in this
integration. Wiring one needs halt clearance, a signed allowance grant
with an owner-held key file, and a current route record - separate
owner decisions, none taken, none of which this branch makes.

`runner_lane_demo.py` proves the lane on disposable fixture roots,
11/11, including through the ACTUAL compiled LangGraph graph (not just
the step function): halt blocks the step with zero attempts; a
gate-passing attempt is recorded by the refusing post, consumed as a
reserve, and halts on the unknown outcome (ledger shows reserve +
unknown result + halt); a bad-signature allowance window blocks before
any call; a stale verified_rev routes Ryan to needs-human with zero
calls. The runner graph ships with no checkpointer: no resume claim.

## Live lane (integrated, awaiting review + go)

`live_lane.py` is the bounded live-run driver: explicit root, preflight
before any reserve, md5-pinned vendored runner/transport (accepted
ab79bf9, append-only window succession), the reviewed guarded
transport constructed only from the pinned module, settle
normalization (no dangling reserve), ONE step through the actual
compiled graph. Run config in `run-config/`. NO live
step until independent review of the exact integrated head and main's
go. See `LIVE_PREP.md`.

## Known limits (stated, not fixed)

- Graceful stop is a node-boundary stop, not crash simulation and not
  exactly-once: the git bus and sqlite checkpoint are two stores with no
  atomic commit across them. The bus (turn token, leases, head bindings)
  is what makes replay safe, not LangGraph.
- The seat gate is process-local and optional and caps seat ACTIONS; a
  seat action can make several adapter calls, so it is NOT a provider
  budget or request-concurrency control. The runner's own guard chain
  (allowance window, verified_rev, envelope, completion) runs in the
  runner lane below, but only with the REFUSING post - no provider call
  is possible from this branch.
- Resume evidence is a narrow new-process sqlite demo, not live
  readiness. Team-state durability is the git bus; LangGraph checkpoints
  cover orchestration state only.

## What this is NOT

- Not the named team (Nora, Eva, Ryan, Alex, Bill, Sam) running. Wiring a
  named member means giving a seat a live adapter (a provider route or an
  operator queue). This graph structurally refuses non-mock adapters, and
  no named member currently holds a qualified route or authorized budget.
  Parallel live model execution has not happened and is not claimed.
- Not a 24/7 service, not a resident process guarantee, not an
  architecture migration.
- No provider budgets, halts, rosters or routes are changed.

## How to run (local, no keys)

Self-contained: `launcher/` is vendored here, copied byte-exact from
this repo's `ryan-continuous-offline` branch at the accepted commit
e881384dbfb99748359a19a944cb6575b4961f63 (the reviewed chain - not
`main`). Only third-party installs needed (Python >= 3.10, tested on
3.10.12):

```
pip install langgraph==1.2.19 langgraph-checkpoint-sqlite==3.1.3
```

```
python integration/langgraph/langgraph_team.py init /tmp/demo/lane-a /tmp/demo/db-a.sqlite
python integration/langgraph/langgraph_team.py run  /tmp/demo/lane-a /tmp/demo/db-a.sqlite 2 team-demo-a   # graceful stop after 2
python integration/langgraph/langgraph_team.py init /tmp/demo/lane-b /tmp/demo/db-b.sqlite
python integration/langgraph/langgraph_team.py init /tmp/demo/lane-c /tmp/demo/db-c.sqlite
python integration/langgraph/parallel_team.py /tmp/demo   # resumes lane-a, runs all lanes, verifies
python integration/langgraph/controls_demo.py /tmp/lg-controls   # operator controls run
```

Developed and tested against the project head `46fa728`. The integration lives in
`integration/langgraph/`; later live/* branches also touch vendored
launcher files (byte-pinned) as noted in their records.

## Closeout status (operator workflow)

The runtime sets bus `done` when the team cycle ends. That is the cycle
only, not a quality result, and nothing in the runtime enforces more.
Closeout wording must come from:

```
python integration/langgraph/langgraph_team.py status LANE            # no record: "cycle complete, quality unproven", exit 1
python integration/langgraph/langgraph_team.py status LANE --record R --key-file K --checker-id C --path src/app.py ...   # exit 0 only if signed operator evidence verifies
```

The operator runs their own checker outside the lane, writes its signed
result into the record with `done_gate.operator_close`, and keeps the key
file out of every seat's reach. The record dir must be 0700, user-owned,
not a symlink. Evidence is bounded (hash-bound to the committed files), not
proof of correctness.

### Operator closeout check: project result summary (sanitized)

An operator-held checker (private, not published) signed an accepted result for the add_lib artifact (hash 834557ccea6fcd8ba065f270733bdb497600c2c806008f44def0169b262eda92, 333 cases). It was run through `done_gate` on a clean fixture repo (branch `fixture-done`, 3 files copied byte for byte from 6edfdcc, plus a committed minimal STATE.json status done). The fixture is NOT the original runtime repo or its evidence. Result: closeout allowed, exit 0. Wrong key, subset path list, wrong checker, wrong branch, forged record, tampered artifact and replay each exited 1. `runtime_blocks_done` is false: the runtime still sets bus done on its own, and the historical 7-request cycle was not gated. This check is not retroactive enforcement and not proof of correctness. The checker, key and record paths are not published.

### Operator-owned finalization (offline-tested, public test checker only)

`langgraph_team.py run` ends by calling `done_gate.finalize`. If `LG_OPERATOR_CONFIG` (a PATH, never the key) is unset or anything is wrong it prints "cycle complete, quality unproven", closeout_allowed false, and the run exits 3 (exit 0 only if closeout is allowed or `LG_ALLOW_UNPROVEN=1`, which still prints unproven). Config JSON (mode 0600, outside the lane): `checker_script` (absolute path of a python file), `checker_id` (must equal sha256 of lg-sandboxed-checker/v1 + the script bytes, computed before any run), `artifact_paths`, `key_file` (0600, raw bytes read exactly, no stripping), `record_dir` (0700), optional `timeout`.

The launcher itself runs the checker INSIDE bwrap on a clean export of the committed files: only /usr, the export (read-only), the script (read-only) and an empty /tmp are visible; no operator dir, key, config, record dir, home or network; cpu/memory/process/file-size limits; streaming stdout/stderr caps with process-group kill on overflow or timeout. A probe runs first in the same sandbox and the run is refused if the key/config/record paths are readable or the network is up, or if bwrap is missing. The checker must print exactly `{"accepted": true|false}` (duplicate or extra keys refused). The PARENT signs; the checker never has the key. A stored record only counts if its signed checker id equals the current script hash, so changed checker bytes do not inherit old trust.

Limits: bwrap under the same user is not a boundary against kernel bugs; trust ends at the config and key file; one checker per artifact type; the runtime bus DONE itself is still not blocked, so this is an operator-side gate invoked by the run entry, not runtime enforcement.
