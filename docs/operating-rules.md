# Operating rules

Rules to carry over into any project that adopts this blueprint.

1. One main delivery job per assistant. A second job is allowed only while mostly idle; if it becomes busy, make a reallocation decision. Preserve own-human availability and independent review.
2. No AI writes without the written turn token; one batch per turn.
3. The Reviewer returns written findings on every batch; QC's written verdict goes to the Coordinator, which handles routine fixes but cannot override a fail; merge or go-live needs a QC pass.
4. Direct clarification between a personal robot and the Coordinator never changes the agreed brief; real concept changes are recorded in `concept_to_coordinator.md`.
5. Scope, spend and go-live decisions stay at the human level and need agreement there, unless an owner's written delegation covers a specific case within its stated limits (rule 8).
6. Agreeing the concept first covers committed builds. Exploration, research and prototypes a human asks for during the concept phase are fine.
7. If the project runs long, rotate roles between phases so no human's AI keeps the same power the whole time.
8. Standing delegation: each owner's written delegation names what the Coordinator may decide and do without asking again, its limits, and how it is revoked. The repo record is evidence, not a grant; the owner's own channel decides disputes. See `docs/delegation.md`.
9. Ask only when blocked: routine work inside a delegation does not wait for answers. Blockers are asked once, batched, with options and a recommendation.
