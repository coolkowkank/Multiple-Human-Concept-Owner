# Researcher seat model trial: Nemotron-3 Ultra 550B via Requesty free route

Date: 2026-11-04. Ran by the coordinator as a bounded capability trial (3
requests, pre-declared cap 6, serial). This is an evaluation record, not a
literature finding.

## Assignment (qualified, accepted 2026-11-04)
- Researcher seat ("Nora") model: `nvidia/nemotron-3-ultra-550b-a55b` via the
  Requesty free route (OpenAI-compatible endpoint, key held outside the repo).
- Scope: synthesis of supplied, verified sources only. The model is NOT an
  autonomous literature-discovery or citation authority.
- Every citation the model produces requires semantic verification (source
  exists AND authors/title/claim support checked) before anything enters
  this branch. A fetch returning HTTP 200 alone is not verification.
- Zero cost confirmed per response (usage.cost = 0 on every trial call).
  The free route has a shared daily request budget; counts from other
  traffic on the same account are not fully visible to us, so exact
  remaining allowance is never promised.

## Why this model
The initially considered `nvidia/nemotron-3-super-120b-a12b` is listed at
$0 in the model catalogue but the provider returned Not Found for real
completion calls (reproduced twice on 2026-11-04). The 550B Ultra model in
the same family is actually served at $0. `google/gemma-4-31b-it` also
served at $0 and remains the fallback.

## Trial results (3 calls, cost 0 each)
1. Concept explanation (liveness vs progress for stall detection):
   technically correct, well structured (heartbeat proves only the
   heartbeat thread; deadlock/livelock/GC/queue cases enumerated).
2. Format compliance: produced the required finding-note shape with
   confidence tags and a Limits section, inside the word cap.
3. Scenario application (seat wrongly flagged stalled during a rate-limit
   wait): proposed distinct IDLE / WAITING / WORKING / STALLED states with
   declared-wait timer pausing - matches the RW4 design direction.

## Observed limit: citation fabrication
All three sources it cited in task 2 were checked:
- "van Renesse et al., An Introduction to the Phi Accrual Failure Detector
  (2004)" with a Cornell PDF link: FABRICATED. The real paper is
  Hayashibara, Defago, Yared, Katayama, "The Phi Accrual Failure Detector"
  (2004), DOI 10.1109/RELDIS.2004.1353004 - different authors, different
  title, dead URL. The model presented it as high confidence.
- Chandra & Toueg, "Unreliable Failure Detectors for Reliable Distributed
  Systems" (1996): real paper, but the cited DOI was wrong (actual:
  10.1145/226643.226647).
- A Consul documentation URL: unresolvable at check time (unverified).

## Consequence for the Researcher workflow
The model is fit for reasoning, synthesis and formatting against sources
the coordinator supplies and has verified. Its own generated citations are
treated as unverified leads until semantically checked; none are published
as citations directly. Status: qualified assignment, trial closed; not a
claim of overall autonomy.
