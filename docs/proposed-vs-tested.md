# Proposed vs tested

An honest map of what this blueprint is built on. It claims no novelty and no comparative performance.

## Established practice (proven elsewhere)

- One authoritative written specification, versioned changes, recorded decisions: decades of RFC and Architecture Decision Record practice.
- Single-writer control, required review before merge: standard branch protection and code review gates.
- Role-based AI teams with structured handoffs: MetaGPT and ChatDev, published with public code and benchmarks.
- Enforcement of architectural rules by linters and structural tests rather than instructions alone: published harness-engineering accounts (see references).

## Carried over from a reference project (worked there, once)

- The coordination method: a Coordinator managing all delivery roles, written turn tokens, written findings, independent QC verdicts. This ran in the reference project this blueprint was distilled from. One project is not proof of generality.
- The delegation record and the ask-only-when-blocked practice (`docs/delegation.md`): used in the reference project in a form specific to it; the generic text here has not been run elsewhere.

## Proposed here (untested)

- The blueprint itself: whether a new team can start a different project from these documents without explanation.
- The multi-owner concept level with per-owner personal robots: each component has public precedent (see references), but the combination has not been found published and has not been tested here.
- The session-to-repo handoff for autonomous high-impact seats: not set up or verified; confirm the mechanism and each session's actual access before relying on it.
- Multi-owner standing delegation (`docs/delegation.md`): each owner's own delegation, with their own limits and gates, applied by one Coordinator across owners. Untested until a fresh team has run it. It is prompt-level policy, not an enforced runtime capability.
- The capacity rule as an enforced constraint: currently a written convention, not tooling.

## Next useful test

Whether a fresh team can adopt this blueprint on a new project and run one full batch cycle - brief, turn token, build, review, QC gate, records - without outside explanation.
