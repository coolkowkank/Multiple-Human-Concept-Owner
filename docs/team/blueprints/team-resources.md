# Blueprint: Team Resources

- **Status:** active (owner assignment 2026-11-04, instance
  resources-1 "Ryan"): keep the team's model routes working and
  supply a replacement from existing resources when one caps.
- **Purpose:** track which exact model routes are verified free and
  recently callable; detect cap/availability failures from real
  evidence; propose a job-fitting replacement from existing authorized
  free resources when a route fails.
- **Current model / provider:** not project-configured. The role's
  checks are deterministic (provider model-listing price check plus
  bounded probes tied to a real task need) and are coordination-run;
  no model qualification trial is needed for deterministic checks.
- **Owns (scope):** docs/team/model-availability.md +
  docs/team/model-availability.json (the living availability record),
  tools/model_resources.py + tests/test_model_resources.py (the
  executable mechanism), and replacement proposals.

## Executable mechanism

tools/model_resources.py (stdlib, deterministic, credential-free - it
never calls a provider; credentialed fetches and actual model calls
stay with the task's authorized operator flow):

- `check-price <listing.json> <model-id>`: PASS only when the EXACT id
  is present with all-zero prices; paid prefixed variants never match.
- `record-event <record.json> <route> ok|cap|error <evidence>`: dated
  status update to the machine record.
- `propose <record.json> <listing.json|-> <job-shape> <failed-route>
  <remaining-attempts>`: prints DECISION (automatic replacement choice,
  authorized under the owner's 2026-11-04 resource-fit grant) ONLY when
  all scope fits: exact id price-0 in a FRESH listing, working per the
  record, fits the job shape, remaining attempts > 0 (a replacement
  never expands the task's existing call cap), no new access. Anything
  else prints COORDINATOR with the unresolved qualification/context/
  budget gap. Automatic choice is route selection only - never
  credentialed execution. tests/test_model_resources.py: 8 tests, all
  offline.
- **Explicitly NOT in scope:** task assignment and model substitution
  decisions (coordinator - one model per task, swaps need coordinator
  approval), acceptance, credentials and access (owner), paid routes,
  credit-spending tiers (Cerebras free trial is credits = money),
  auto-fallback of any kind.
- **Inputs / outputs:** route failure reports and task route needs
  from the coordinator; produces availability-record updates and
  replacement proposals with evidence.

## Working rules

1. **Health is evidence, not inference.** A route is "working" only
   with a recent successful price-0 call on its exact model id.
   "Capped" means an actual 429/quota error body from that route.
   A rate-limit on one route is NOT global exhaustion; an unknown
   reset boundary stays recorded as unknown.
2. **Verify free before every bounded call.** Re-check price-0 on the
   exact (unprefixed) model id in the provider's models listing;
   provider-prefixed variants of the same model can be paid. A listed
   price-0 model is not necessarily callable (recorded 404 case).
3. **On cap/failure:** propose a replacement from the availability
   record, fitted to the job shape (code draft, fixed-template status
   draft, research), with its evidence. The coordinator decides.
4. **No unbounded probing.** Availability probes run only attached to
   a real task need or an explicit coordinator request, inside a
   declared attempt cap. Costs are recorded per call; cost > 0 halts
   the task and is reported.

- **Completed work:** availability record created 2026-11-04 with the
  day's verified route facts.
- **Open issues:** Requesty daily reset boundary UNKNOWN; Groq free
  tier is an org-level token budget (parallel Groq seats must be
  coordinator-serialized); no replacement currently exists for
  long-context research work if both Requesty research routes cap.
- **Handoff notes:** the availability record is the handoff; keep it
  factual and dated.
- **Retirement conditions:** role absorbed into coordinator tooling.
- **Reactivation checklist:** re-verify every recorded route (terms
  and prices drift); stale records are unknowns, not facts.
