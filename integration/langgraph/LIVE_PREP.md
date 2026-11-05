# Bounded live-run preparation (integrated, reviewed-transport wired - still NO live go)

Owner authority (attribution: main's relay of recovered owner originals,
2026-11-05; this lane holds no independent owner evidence): free-tier
resources, continuous work and failover are authorized; there is NO owner
numeric cap or halt veto - the lifetime envelope, verifier cap and the
durable halt were self-imposed project safety controls. The owner
boundary that stands: NO PAID CALLS. A live run must be free-only,
bounded and ledger-preserving. Do not ask the owner to "lift" the
self-imposed envelope; reconfiguring those controls is an executor
operation on the project, not an owner approval question.

## Integrated accepted chain (2026-11-05)

Upstream tip `3b09eea8ccacebc4e5d3131e4b58fa9cf58a0fe2` (independently
reviewed, accepted by main: bounded transport/boundary, 385 independent
+ adversarial + production stale-listing-0-send tests) is vendored
BYTE-EXACT into `runner/` and md5-pinned in `live_lane.VENDORED_MD5`:

- `ryan_cycle.py` (ecc7bbb21c62b9aceccf95ba41deec5b) - envelope 7
  (4 historic + at most 3 new; historic ledger never reset), verifier
  max_tokens 4096, pre-I/O boundary under store.lock (halt/stop, own
  reserve line, operator assignment, rendered-input snapshot, grant,
  price-0, listing freshness at the actual clock; refusal = result
  outcome not_sent + halt, reserve stays consumed).
- `model_resources.py` (148d1e609f466332ebb1d6ce85ccf40d) - unchanged
  from the previously accepted chain.
- `requesty_transport.py` (701321b3a753b82365575b0b40f2acfd) - the
  reviewed guarded transport: exact free-ID allowlist (subset of
  FREE_IDS with an evidenced listing ceiling), fixed endpoint
  (https://router.requesty.ai/v1/chat/completions, constant-verified,
  no redirects), ONE request no retry, mandatory exact model echo,
  bounded reads on every error path, max-3 attempts per factory counted
  BEFORE I/O, and cost-zero accounting: an absent or invalid cost
  signal is cost-unverified and surfaces as unknown, never ok.
- `make_allowance.py` (8587d6e2d5ffd5b86446baa68a7a89ab) - offline
  bookkeeping builder for ONE signed window; refuses when the item is
  not at the Verifier step, the TTL exceeds the runner max, or a window
  is already bound to the lineage/work-fingerprint (a bound window is
  never replaced).

Run config: `run-config/assignments.json` carries the exact
assignment content of the local assignment head
`49f189dd59843f66dc3719871e0750b5fa0ba5c0` (the web editor normalized
the final newline; the JSON content is identical) - main's delta,
2026-11-05: researcher nvidia/nemotron-3-ultra-550b-a55b
(unchanged), verifier mistral/leanstral-1-5 (exact free id, price-0 in
the fresh public listing; viability unproven - the bounded run is the
test), ryan novita/ling-3.1-flash (unchanged, NOT authorized for this
run).

## The bounded run shape (what main authorized preparing)

ONE verifier-only window (max_requests 1, TTL <= 60 min) on the
existing claim-set lineage research-model-vs-harness-v2: the drafted
Ultra item C1-C6/P1-P9 continues (verifier already used 2 of its
ordinary attempts, baseline pinned in the window). NO Researcher
re-call, NO new lineage, NO Ryan role. The existing bound window
mechanism prevents a second window; nothing here redesigns that. No
retry and no halt-clearing until main's go after the run.

Execution ownership (main, 2026-11-05): the EXECUTOR runs ONE driver
pass of this exact integrated code against its own authoritative
root/ledger (tip 49f189dd, unchanged), after independent review of
this exact integrated head and main's go. This lane never makes a
provider call and never executes a cloned ledger. The executor holds
the vault Requesty key (env REQUESTY_API_KEY) and the allowance
bookkeeping key (RYAN_ALLOWANCE_KEY_FILE); no secret passes through
this repo or chat. After the run the executor returns the non-secret
ledger/queue/result/grant-digest delta through main for forward-only
publication and freezes the root.

## What the driver adds (live_lane.py - wiring and run-shape only)

1. Explicit authoritative root path (no cwd default; must be a
   directory with queue.json).
2. Preflight BEFORE any reserve: key env present; assignments parse
   with decided_by == the runner's OPERATOR constant; every assigned
   model in the run allowlist (subset of FREE_IDS with an evidenced
   listing ceiling); listing fresh at the actual clock; and, for the
   ACTUAL next_action role's model only (the runner's own pick +
   next_action selection), a recorded non-blocked route with a
   non-blocked provider and exact price-0. An "untested" route is
   passed through AS untested - the bounded run IS its qualification -
   never relabeled "working"; any other non-working status, a blocked
   provider, or an unrecorded id refuses. Inactive assigned roles do
   not gate the step. Preflight failure raises with the ledger
   untouched (tested byte-identical).
3. Reviewed-transport identity: the post callable is constructed ONLY
   from the vendored, md5-pinned requesty_transport module. Callers
   cannot inject a factory into the live path; a tampered vendored
   file refuses at load (tested).
4. Settle normalization: any exception escaping rc.step after the
   reserve (the transport raises only for local pre-I/O refusals, e.g.
   a key that vanishes between preflight and post) leaves no dangling
   reserve - the driver settles ONLY this invocation's own newly
   created reserves (pre-step reserve snapshot; historical or
   concurrent reserves are never touched) as outcome unknown via the
   runner's own settle(), which appends the halt (tested: exactly one
   unknown result + halt; the halt is durable and a later step
   reserves and sends nothing; a pre-existing historical orphan is
   left untouched and blocks the run via the runner's own gate).
   Paused-path accounting is evidence-driven, never a blanket number:
   the reason is the allowlisted exception CLASS ONLY (exception text
   can carry secrets/raw prompt - tested with a secret-bearing
   RuntimeError), and calls/io_attempted come from the ledger:
   runner-settled result lines say exactly (not_sent = no I/O;
   unknown/http_* = one attempt), a driver-settled dangling reserve is
   io "unknown" counted conservatively as 1, no new reserve is 0.
5. The step runs through the ACTUAL compiled LangGraph
   (build_live_runner_graph, one node, no checkpointer - no resume
   claim), satisfying the requirement that the bounded run is driven
   through the real graph, not a direct rc.step call. `opener` and
   `before_io` parameters are test seams only (they mirror the
   runner's own seams); production uses the defaults.

The durable bound on spend is the signed allowance window and its
ledger debits, enforced by the runner - not anything in-process here.

## Accepted limits (documented, not redesigned)

- Builder bookkeeping is offline/quiescent; its allowance.json write is
  NOT crash-atomic (single-writer use; no crash-atomicity claim).
- Socket timeout only - no strict total deadline.
- Listing age is checked, not refetched; the checked-then-send residual
  remains (state can change between the boundary check and the send).
- A price-0 listing is NOT proof of $0 charge: free status rests on the
  vendor docs + the fresh listing. Missing usage/cost in a response is
  not proof of $0 either - the transport treats an absent/invalid cost
  signal as unverified, never ok.

## Offline test evidence (round 9, this head - no network, dummy key)

12/12 driver probes pass (round 9b, reviewer-corrected): md5 pins load/tamper-refused; key-missing and
config-fail (allowlist, authority, stale listing) raise pre-ledger with
the ledger byte-identical; post-reserve transport raise settles exactly
one unknown + halt; the compiled graph completes a verifier window
(done-verifier, reserve tagged to the window, allowance-done, second
invoke needs-human with no new reserve); the builder refuses a second
window on the bound lineage; network-down settles unknown + halt with
no dangling reserve. Prior suites re-run on this head: round-4 12/12;
committed-control fail-closed 3/3 (round-3's worktree-write probe is
stale by design - the graph reads the COMMITTED control only).
