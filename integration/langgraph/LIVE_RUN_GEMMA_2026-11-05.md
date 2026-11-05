# Live verifier run (gemma successor window), 2026-11-05 - SANITIZED SUMMARY

This file is a sanitized summary of the project's private authoritative
ledger. It is NOT the original ledger and not a line-by-line copy of it;
internal operator notes, audit wording, request/response bodies, key
material and grant machinery are deliberately omitted. Task-result
facts only.

## What ran

- ONE bounded verifier request, model `google/gemma-4-31b-it` (exact
  free-catalog id, price-0 in the fresh public listing), executed
  through the project's compiled LangGraph driver at reviewed
  integration head `60b2fbb` (the current docs head `f395090` carries
  a docstring-only narrowing on top; the executable code is
  identical).
- Claim set: the existing item `research-model-vs-harness-v2` (lineage
  `research-model-vs-harness`, work fingerprint unchanged - no new
  claims, no new lineage, no re-drafting).
- Window: a single-use SUCCESSOR allowance (`A2`) naming the stopped
  prior window (`A1`) by id and digest, covering the verifier role
  only (max 1 request). No Researcher call, no Ryan call, no retry,
  no further window.
- Request started 2026-11-05 08:44 EET (06:44 UTC), elapsed 114.53s.

## Outcome

- The provider returned a JSON-like body of 13801 bytes (body content
  not published). The client expected the documented
  `choices[0].message.content` response shape; the returned body did
  not match that shape and parsing raised a `KeyError`.
- No HTTP status was recorded for this exchange. No verdict content
  was produced. The response carried no usable usage/cost fields, so
  whether the provider charged anything is UNKNOWN.
- Recorded outcome: response-shape `KeyError` (client-side parse
  failure), not an HTTP error.
- The runner then halted as designed: the reserve stayed consumed, the
  successor window `A2` was terminal-stopped (consumed, not expired),
  and NO retry, no further call and no other role ran. The project
  root is frozen.

## Accounting (independently reviewed and accepted)

- Historical ledger lines before this run: 22, unchanged; 6 lines
  appended by this run (28 total), history preserved.
- Lifetime reserves: 5 -> 6 (this request is the 6th of the
  envelope of 7).
- Verifier attempts on this item: 2 -> 3 (lineage total 3 -> 4).
- Researcher (1) and Ryan (0) counts unchanged; no other role acted.

## What this does and does not show

- It DOES show: the compiled-graph live path executed end to end on a
  real provider route, including signed append-only window succession
  (A1 -> A2 on the same lineage and work fingerprint), preflight,
  reserve, pre-I/O boundary, transport, settle, terminal window stop
  and exact accounting.
- It does NOT show: a qualification of the gemma route (the route
  stays unqualified - this request was its first attempt and it
  failed), any verdict on the claim set, or the CAUSE of the
  response-shape mismatch (not determined: no HTTP status, token
  limit, safety action or missing-field cause is established, and none
  should be inferred). It is NOT proof of $0 charge (usage/cost were
  unverified in this exchange; free status rests on the vendor's
  free-catalog docs and listing, not on this result).

## Next

- Offline structural diagnostics of the captured body against the
  documented response shape, with no provider calls. Any further
  route or model decisions stay with the project's owner/operator.
