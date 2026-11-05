# RW6 scoping note: rate-limit-aware provider routing (draft, requirements only)

Date: 2026-11-05. Status: S1 scoping draft. Not a finding, not a design, no code, no adoption decision.

**How it was made.** One operator-mediated request to a free-route model (nvidia/nemotron-3-ultra-550b-a55b through the project's fenced adapter), given only the public excerpts listed under Sources. The raw draft stays private. A reviewer checked each line against those excerpts, and this note keeps only what survived that check, with corrections. It is not Researcher-seat work, not a team run and not a role qualification. Cost zero was provider-reported and is not a billing guarantee. The provider's token counts were not relied on.

## What the sources say a router would have to respect
- Goal as stated: spread free-tier requests across providers without losing request accounting or provenance [S1].
- Accounting: a reserve line is written before any I/O, counted against the per-route `call_budget` and the lifetime cap (8) [S5][S2].
- After a reserve line, nothing proves a request is safe to resend to another route. A route change then needs an operator decision [S2].
- Some failures are route-local (missing key env) and some are global (a broken chain or halt in the shared log dir refuses every route sharing it). The budget-exhausted error text covers both a route-local and a global case, so a caller cannot tell them apart [S2].
- Provider and brief scope must be recovered per job and per route. No cross-provider prompt disclosure is granted by the project's notes. This is a scope limit, not a missing mechanism [S2].
- Route status can matter: the runner's route gate admits only "working" or "untested" routes, but only where the route record the runner loads carries that status. A standalone note changes nothing [S4].

## Failure and uncertainty classes recorded in the project
- Outcome unknown for everything except a reserve plus a usable 200 at provider-reported cost 0: no result line, timeout or socket error, 5xx, redirects, 429, bad status or size, a malformed 200, any 4xx [S2].
- A 200 with a body that did not match the expected shape, no HTTP status recorded, no usage or cost fields, so any charge is unknown [S3].
- An HTTP 400 with no verdict and unknown cause [S4].
- A model listed price-0 in the router listing while the vendor page, as quoted in S4, says it is deprecated [S4].

## Rate-limit evidence: have and lack
- Have: nothing about provider rate limits. The excerpts hold no provider limit, quota, window, header or observed 429 [S1: "Sources: none gathered"]. Accounting and listing facts (price 0, cost 0, halt on nonzero cost) are cost controls, not rate-limit evidence.
- Lack: provider rate-limit policies and signals for each free-tier route, and any real run that observed a 429 or a rate-limit header. Needed before any design.

## Open risks that block a fallback design (not "skip" items)
- The lifetime total is read before the reserve is written and the lock is per log file, not per directory. Concurrent processes on different routes can each pass the cap check. A fallback route would use a different log file, so the gap widens. Making the shared cap atomic is a precondition to any fallback design, and it is not implemented [S2].
- Whether `reserve_preflight` tolerates odd log lines the same way as the adapter's own reader is not verified [S2].

## Proposals (all [PROPOSAL], not decisions)
1. Skip automatic fallback after a reserve line. Reason: no safe-resend proof [S2].
2. Keep an operator decision for any route change after a reserve line [S2].
3. Add a structured reason to the budget-exhausted error so route-local and global causes are separable [S2].
4. Treat rate-limit data collection as the next step before design: gather provider documentation excerpts and, if a run ever sees a 429, record it as a structured outcome class.

## Limits
Based only on the excerpts below. No external provider documentation and no live rate-limit testing. The model's draft added no new facts beyond the excerpts; its value is the organized checklist.

## Sources (public, pinned)
- [S1] research/PLAN.md, RW6 section, branch Research_lab at b0e4ebf0a736be6ad7f57e4eba254c0c392bbee0.
- [S2] integration/langgraph/FALLBACK_FAILURE_TAXONOMY_NOTE.md at ac45e5c80d45a08dcef552f1f2bef74d0aa39d3a (a proposal note).
- [S3] integration/langgraph/LIVE_RUN_GEMMA_2026-11-05.md at ac45e5c (a recorded run).
- [S4] integration/langgraph/ROUTE_NOTE_leanstral_2026-11-05.md at ac45e5c (a recorded failure).
- [S5] integration/langgraph/fenced_http.py, `FencedHttpAdapter.complete`, at ac45e5c.
