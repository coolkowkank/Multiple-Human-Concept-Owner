# Eva - Evidence verifier role (assigned, BLOCKED, not wired)

Status 2026-11-04 (current): assigned but BLOCKED and not running. The
Gemma route is on cooldown (never cleared), no verifier model is qualified,
and Eva is not wired into the launcher roster. The "trial-qualified" text below
is HISTORICAL: one small trial earlier on 2026-11-04, not current readiness.
Not an enforced gate. This document is
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

## Offline tooling (2026-11-04, not Eva, no model)

`tools/eva_check.py` is a deterministic text-match pre-check and a queue
intake for publications. It marks each claim's quoted strings FOUND /
IN_OTHER_SOURCE / NOT_FOUND and lists numbers PRESENT / ABSENT in the cited
passages. It is NOT a verdict: absent numbers can be computed or taken from
elsewhere, present numbers are not checked for units, denominators or context.
`intake` builds a HELD queue item (status held, attempts {}, kind verify) and
fails closed on partial or unsupported sources. The runner has a dedicated
verify path: only status ready-verify runs, the model comes from an
operator-made eva-assignment.json (assign_eva_manual, same price-0, route and
ledger gates), the item must name its author_model (independence), and the
result is PASS only if EVERY claim is SUPPORTED with a verbatim quote
(UNVERIFIED or NOT_SUPPORTED never passes). No Ryan step follows, and a
format failure goes to needs-human with no automatic retry. Held items never
run, and no assignment exists today. Eva remains
assigned but blocked and not wired (route cooldown, no qualified model).
`docs/team/eva-precheck-rw6-v2packet.json` is the mechanical report for the
published RW6 note against the 9-passage packet (13 claims, how many need
review is in the file); it shows which numbers the packet does not cover.
