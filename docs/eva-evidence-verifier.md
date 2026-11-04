# Eva - Evidence verifier role (planned, trial-qualified)

Status 2026-11-04: role defined and model trial-qualified; NOT yet wired
into the launcher roster and NOT an enforced gate. This document is
workflow policy. "Eva checked it" is only claimable once the loop below is
actually run and logged for a given publication.

## Purpose
Independent verification of the Researcher's (Nora's) citations and of
whether her output faithfully reflects the cited sources, before anything
is published to Research_lab. Separate from Bill's code review and from
Nora herself: Nora never verifies her own citations, and Nora's output is
never treated as source truth.

## Model (trial-qualified, bounded)
google/gemma-4-31b-it via the Requesty free route (existing project
credential; usage.cost = 0 on every trial call). Different model family
from Nora (Nemotron-3 Ultra 550B) so verification is not the same weights
grading their own phrasing. Trial (2026-11-04, 2 calls, cap 5, serial):
7/7 correct verdicts - supported claim accepted with passage reference;
fabricated numeric detail ("every 2 seconds" vs passage "every second")
rejected; overreaching extension ("removes the need for timeouts")
rejected; metadata mismatch (passage attributed to the wrong paper)
flagged; claim citing an unfetched source returned UNVERIFIED. One small
trial: evidence of fit, not a guarantee. Fallback if the free route
drops the model: re-trial before any substitution.

## Verification workflow (per publication candidate)
1. Coordinator collects the actual evidence: fetched source text or
   paper passages for every citation in the draft. Malformed, missing or
   paywalled evidence means the claim is UNVERIFIED - never a pass.
2. Eva receives ONLY: the draft's claims, the citation metadata, and the
   fetched passages with fixed passage IDs. No outside knowledge allowed;
   no access to Nora's reasoning as evidence.
3. Eva returns per claim: SUPPORTED (passage literally backs the claim,
   numbers and qualifiers included) / NOT SUPPORTED / UNVERIFIED /
   METADATA MISMATCH, with the passage ID used.
4. Anything not SUPPORTED goes back to Nora for correction or is cut.
   Publication is blocked until every cited claim is SUPPORTED. The
   coordinator (Telkomsel) keeps final accountability for the check; Eva
   is an instrument, not an approver.
5. The verdicts and the fetched evidence references are recorded with the
   publication (which passages backed which claims).

## Limits
- Eva verifies against supplied passages only; a wrong or cherry-picked
  passage selection by the coordinator is outside her view.
- Passage-level support can still be gamed by quote truncation; the
  coordinator spot-checks the surrounding source context.
- No code changes were made for this role; roster wiring, if wanted, is
  Builder work with its own tests and review.
