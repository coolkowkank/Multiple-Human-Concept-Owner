# Model availability record (Team Resources - Ryan)

Health = evidence. "Working" = recent successful price-0 call on the
exact id. "Capped" = actual 429/quota error body. Unknowns stay
unknown. Verified facts below are dated; anything stale is an unknown,
not a fact.

## Verified routes (existing authorized free resources)

| Route (exact id) | Provider | Price | Evidence | Caps / notes |
| --- | --- | --- | --- | --- |
| openai/gpt-oss-120b | Groq free tier | $0 | working 2026-11-04 (WP5/F1/F2/F3 draft calls, 3 completions) | org-level token budget; parallel Groq seats coordinator-serialized; observed weakness: malformed diff syntax, semantics usable after operator review |
| google/gemma-4-31b-it | Requesty | $0 (input/output/cached all 0 in /v1/models, re-verified 2026-11-04) | working 2026-11-04 (status-draft, cost 0) | 200 req/day org-wide across ALL price-0 routes; same-day floor >=26; daily reset boundary UNKNOWN; PREFIXED variants (deepinfra/, sail/, ...) are PAID - pin the exact id |
| Nemotron-3 Ultra 550B (Nora's route) | Requesty price-0 | $0 | working 2026-11-04 (researcher-1 outputs RW5, corrections 61143ba) | shares the Requesty 200/day org pool |
| nvidia/nemotron-3.5-lightning-30b-a3b | Requesty price-0 | $0 | callable 2026-11-04, NOT qualified: empty/truncated answers on multi-KB inputs, 4-11x reasoning overhead | same pool |
| nvidia/nemotron-3-super-120b-a12b | Requesty | listed $0 | UNCALLABLE 2026-11-04 (404 twice) - listing != callable | - |

## Excluded without owner approval (money)

| Route | Why excluded |
| --- | --- |
| Cerebras free trial (any model) | $5 credits - credits are money; no approval exists |
| Any Requesty provider-prefixed variant with nonzero price | paid |
| Any paid tier / auto-recharge / new credential | owner decision |

## Replacement supply map (job shape -> current candidates)

- Code draft (small files, instruction + diff): openai/gpt-oss-120b
  (Groq). No second qualified code-draft route today - GAP.
- Fixed-template status draft: google/gemma-4-31b-it (Requesty).
- Research/long findings: Nemotron-3 Ultra 550B (Requesty). No
  qualified backup - GAP.
- Evidence verification: google/gemma-4-31b-it (Requesty, verifier-1's
  working route).

On a cap/failure, Ryan proposes from this map with evidence; the
coordinator approves or holds the task. No automatic substitution.
