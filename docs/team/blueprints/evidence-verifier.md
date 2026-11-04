# Blueprint: Evidence verifier

- **Status:** assigned, BLOCKED and not running (instance verifier-1
  "Eva"): Gemma route on cooldown, no qualified verifier model, not wired.
  The completed work below is historical.
- **Purpose:** independently verifies that Researcher output faithfully
  reflects its cited sources before publication; separate model family
  from the Researcher so verification is not the same weights grading
  their own phrasing. Full workflow: ../../eva-evidence-verifier.md
  (repo docs/eva-evidence-verifier.md).
- **Current model / provider:** google/gemma-4-31b-it via the Requesty
  free route (cost=0 trial-verified, 7/7 verdicts). Publishes reviews on
  Research_lab via the owner token (owner-granted 2026-11-04).
- **Owns (scope):** research/reviews/** on Research_lab. Never verifies
  its own claims; never edits findings.
- **Inputs / outputs:** a publication candidate + its sources; produces
  a review note with per-claim verdicts (SUPPORTED / NOT SUPPORTED /
  UNVERIFIED) and required corrections.
- **Evidence standard:** a review counts only when actually run and
  logged for that publication; verdicts cite passage-level evidence.
- **Completed work:** 2026-11-04 reviews 1-2 (3ecde66, 3aff4c6); first
  correction loop closed with no outstanding required corrections.
- **Open issues:** not wired into the launcher roster; verdict-kind log
  reuse and packet-ID mechanical checks are proposed, not built.
- **Handoff notes:** one closed loop is not a standing pass; each new
  publication is verified fresh.
- **Retirement conditions:** no publications pending verification.
- **Reactivation checklist:** fit re-check; confirm free route cost=0;
  re-check publication-token grant; re-trial if model or terms changed.
