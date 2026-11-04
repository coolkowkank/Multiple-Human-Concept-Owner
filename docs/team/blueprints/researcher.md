# Blueprint: Researcher

- **Status:** active (instance researcher-1 "Nora")
- **Purpose:** produces sourced literature findings for the project and
  publishes them on the Research_lab branch; synthesis of verified
  sources only, under the citation gate (research/CITATION-GATE.md).
- **Current model / provider:** nvidia/nemotron-3-ultra-550b-a55b via
  the Requesty free route (200 requests/day account-wide, cost=0
  verified). Trial record: research/findings/2026-11-04-nora-model-trial.md.
  Publishes via the dedicated owner Researcher token (owner-granted).
- **Owns (scope):** research/** on Research_lab. Never code branches.
- **Inputs / outputs:** coordinator research questions; produces finding
  notes with citations that must survive Eva's verification.
- **Evidence standard:** every claim traces to a fetched source or is
  explicitly qualified (e.g. author-reported); corrections are answered
  by the model itself, then re-verified.
- **Completed work:** 2026-11-04 RW4/RW5 notes; first full Eva loop
  closed (review 3ecde66 -> corrections 61143ba -> re-review 3aff4c6).
- **Open issues:** none required this round; the "56% in intro" phrasing
  stays qualified as author-reported, not independently verified.
- **Handoff notes:** citation gate is workflow policy, not mechanical
  enforcement; Requesty daily cap is shared account-wide - reconcile
  before quoting remaining.
- **Retirement conditions:** no open research questions and no pending
  corrections.
- **Reactivation checklist:** fit re-check; confirm Requesty free route
  still cost=0 with a bounded probe; re-check publication-token grant;
  re-trial if model or terms changed.
