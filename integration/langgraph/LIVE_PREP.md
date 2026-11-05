# Bounded live-run preparation (inert - nothing here runs a provider)

Owner authority (corrected 2026-11-05 by recovered originals): free-tier
resources, continuous work and failover are authorized; there is NO owner
numeric cap or halt veto - the lifetime envelope, verifier cap and the
durable halt were self-imposed project safety controls. The owner
boundary that stands: NO PAID CALLS. A live run must be free-only,
bounded and ledger-preserving. Do not ask the owner to "lift" the
self-imposed envelope; reconfiguring those controls is an executor
operation on the project, not an owner approval question.

## What a bounded live run looks like

1. Scope: ONE lineage, research already drafted offline. The runner's
   signed-window mechanism covers verifier (+ optionally ryan) only, so
   the windowed run is: verifier qualification/review on a drafted item,
   optionally followed by one Ryan review - at most 2 requests
   (ALLOWANCE_MAX_REQUESTS hard ceiling in the runner itself).
2. Route: free-only. `live_lane.check_free_route` requires route status
   working + listing input/output price exactly 0 + fresh listing, and
   the route must be in the run's explicit allowlist. A price-0 listing
   alone is NOT proof of $0 charge: the executor's vendor-state
   grounding confirmed the free catalog (fresh listing 03:58, 13 exact
   free IDs, policy: model prefix / explicit managed id selection).
   Selected qualification mapping (main, 2026-11-05 ~03:59): researcher
   nvidia/nemotron-3-ultra-550b-a55b; verifier mistral/leanstral-1-5
   (route viability unproven - the bounded run itself is the test);
   Ryan third request ONLY on a valid verifier PASS with a grounded
   model constraint. Bound: 3 requests max, serial, no retries, no 4th;
   executor's runtime config keeps lifetime envelope 7 = 4 historical +
   3 new, verifier max_tokens 4096, claim-set identity respected.
3. Window: signed allowance body (lineage + work_fp bound, pinned model
   per role, max_requests == number of window roles, <= 2) verified
   against RYAN_ALLOWANCE_KEY_FILE (owner-held, 0600, outside the repo).
   The runner enforces it durably: deny by default, every reserve
   debited, a reserve counts clean only with an explicit
   allowance-done line, history never edited. Shape note: windows cover
   verifier (+ optionally ryan) only - the researcher request runs
   under the ordinary gates, not a window.
4. Transport: INJECTED reviewed guarded post only. The runner's
   built-in rc.http_post_factory is NOT cleared (unbounded error
   reads, loose endpoint shape, optional model echo). The pending
   contract (executor's guarded_post_factory, first candidate rejected
   in review): exact free-catalog ID allowlist, exact endpoint with no
   redirects, no retry, mandatory model echo, bounded reads on every
   error path including HTTPError and timeout. The key is read from
   the named env var at call time, injected by the operator for the
   run's duration only - never stored or committed. NO live step until
   the integrated exact head passes independent review and main says
   go. Missing usage/cost in a response is not proof of $0 - the free
   determination rests on vendor docs + the fresh price-0 listing, not
   on observed usage fields.

   Accounting integration, ENFORCED in live_lane.bounded_live_step (not
   delegated to helper names):
   - Transport identity: the injected factory must carry
     REVIEWED_TRANSPORT_ID equal to this run's expected value, else
     refusal. The vendored rc.http_post_factory does NOT carry it and
     is refused.
   - The factory is invoked ONLY inside rc.step: no direct-call
     surface exists in the module, so a bare post cannot bypass the
     reserve ledger.
   - Pre-I/O recheck: the vendored runner (88a610a) reserves and then
     posts with NO fresh halt/grant recheck in between. live_lane adds
     it: a wrapper re-reads the ledger and grant from disk immediately
     before any socket opens (after the runner's reservation) and
     raises Halt on any halt line, invalid or expired grant; the
     runner's settle() records that as a consumed unknown outcome,
     never a silent retry. Completion-side checks remain the runner's.
   - Per-process counter caps actual post invocations at the signed
     window's max_requests (hard ceiling PER_RUN_REQUEST_CEILING=2);
     the runner's reserve ledger is the durable count.
   - Run allowlist: every model in the committed assignments.json must
     be in the run's exact free-ID allowlist AND pass check_free_route
     (working route, price 0/0, fresh listing).
5. Ledger: append-only. The run adds reserve/result/window lines to the
   existing ledger; nothing is rewritten. Clearing the durable halt and
   reconfiguring the self-imposed envelope are executor operations on
   the project controls, coordinated upstream - not done by this lane.
6. Remaining gate before first live step: the corrected upstream
   (action_lock + pre_apply, e881384 under review) must be accepted and
   integrated so control/operator coherence holds during the run.

## Inert behavior (tested)

Importing this module performs no I/O. bounded_live_step refuses
(BEFORE any network) without: RYAN_ALLOWANCE_KEY_FILE, a valid signed
window within the per-run ceiling, and the key env var. The refusing
runner lane (runner_lane.py) remains the only wired lane.
