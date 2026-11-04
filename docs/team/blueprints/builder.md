# Blueprint: Builder

- **Status:** active (instance builder-1 "Alex")
- **Instances:** builder-1 "Alex" (Groq gpt-oss-120b). builder-2 (model
  none, operator execution; carries the WP4/WP9 work, formerly
  recovery-1, see recovery-executor.md). builder-2 asks reviewer-1 Bill
  for review of each pinned change and receives his verdicts. It shares no
  provider quota with builder-1 because it holds no model.
- **Purpose:** implements scoped code tasks on live/* branches through
  the self-commit executor: receives a coordinator task file with
  verified anchors, edits, commits and pushes its own work with honest
  model authorship.
- **Current model / provider:** Groq openai/gpt-oss-120b, free tier
  (org-level 8K TPM). Commits ride under @coolkowkank-bot with the model
  named in author/message.
- **Owns (scope):** the pinned branch + files named in its task file
  (e.g. launcher/, tests/). Never main, never other seats' files.
- **Inputs / outputs:** task file in tasks/; produces commits on its
  live/* branch; push only through the whole-tree push gate after an
  operator-verified green suite.
- **Evidence standard:** exact base/head pins, changed-tree test output,
  real-sent vs reserved provider-call counts from the durable ledger.
  Compile-clean is not test-green; no overall PASS claims.
- **Completed work:** 2026-11-04 null-handoff deadlock fix 45cec13
  (pushed, suite green at pin); token_est.py a14eb5f (first module,
  reviewed path).
- **Open issues:** routing counter/consecutive fix v2 undelivered
  (batch 6, 8/8 spent on prose rounds); reviewer-skip guard unbuilt
  (batch 5: records-push transient halt + unknown-tool crash; batch 7
  in flight with hardened executor); prose-only rounds burn budget.
- **Handoff notes:** read tasks/CURRENT.md for the single live
  assignment; ledgers are pre-request, fail-closed; MAX_TOOL_RECOVERIES=2
  then abort; 65s pacing on the org TPM.
- **Retirement conditions:** no open task files and no running batch.
- **Reactivation checklist:** fit re-check against the task; confirm
  executor pin matches a suite-green hardened commit; fresh ledger with
  declared cap; no credential inheritance - keys are materialized per
  run and deleted.
