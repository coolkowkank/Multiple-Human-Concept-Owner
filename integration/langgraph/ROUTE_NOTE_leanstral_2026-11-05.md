# Route note: mistral/leanstral-1-5 - failed-first-call (2026-11-05)

Sanitized publication of the project's route-record note. Task-result
facts only; no raw audit lines. The executor's route-record change
(patch f970bcf) lives on a SEPARATE route-notes branch; the
authoritative root stays frozen at 75ee635. This branch carries no
docs/team/model-availability.json, so the note publishes as this
standalone file. The reviewed executable head d97ccc07 is unchanged.

## Status

`failed-first-call` - the route must not be reused without a new
operator decision. ENFORCEMENT SCOPE: this file is documentation only.
The runtime gate engages where the route record the runner actually
loads carries this status (the executor's route-record change): the
runner's route gate admits only "working"/"untested", so a loaded
"failed-first-call" record refuses the route. This standalone note by
itself changes no loaded record and blocks nothing.

## Evidence

FACT 1 (run): 2026-11-05 04:35 EET one bounded Verifier request through
the integrated compiled-graph driver returned HTTP 400 (structural
diagnostics only: http-status, application/json, 1.09 s elapsed,
88-byte error body, body not retained; sent shape: temperature 0,
max_tokens 4096, reasoning_effort none, system+user messages). No
verdict, no usage/cost signal returned. Failure, NOT a qualification;
cause UNKNOWN.

FACT 2 (separate, not shown to cause the failure): Mistral's own model
page for leanstral-1-5 says "deprecated and being phased out",
deprecation date 9/29/2026 (https://docs.mistral.ai/models/leanstral-1-5).
The Requesty public listing still shows the exact id price-0 (listing
updated 2026-11-02). Listing/docs facts: max output 32768, json_object
supported.

Earlier listing fact (unchanged): exact id, input/output/cached price
all numeric 0 in the public /v1/models listing; model lab mistral
(distinct from nvidia and inclusionai). Prefixed look-alikes are PAID
(fireworks/muse-glimmer-30b, nebius/nvidia/..., sail/gemma-...).
