# FEEDBACK-c1 (independent review, cycle 1)

Reviewed commit: b993bd24411fab6433be9a804b99d1b9c73adc5b (docs/self-commit-protocol.md, +19 -14)
Canonical state read: live/groq-dev-3 head 43b664027b105b9cf0487e01f7051f56d8943467, LOOP.json REVIEW_REQUESTED, cycle 1, api_used 0 of 6.
Reviewer: independent reviewer (instinct-christina). Public evidence only. Scope: documentation claims in the reviewed commit. Not a harness, budget or provider audit.

Verdict: FIX_NEEDED

## Findings

F1 (accuracy, hook claim). The doc says the repository includes a commit-msg hook that requires "TURN: builder". At the reviewed SHA the full public tree (91 entries, not truncated) has no hook file and no hooks directory. The live/groq-dev-3 head tree is also complete and has none. A local .git/hooks file would not appear in a tree, so this shows only that no published hook exists. Reword to say where the check actually runs (for example the local executor or harness) and mark it unverified from the repo, or publish the hook.

F2 (accuracy, executor and guards). The doc presents the docs/-only path limit and credential-pattern refusal as mechanical safeguards of "this repository". At the reviewed SHA no executor or tools/ file other than tools/artifact-conformance exists. The reviewed commit itself does not reference an executor file. A later protocol document (docs/review-loop.md) names tools/self-commit-executor.py, and that path is also absent from the live/groq-dev-3 head tree. Say the guards live in a non-published harness, or publish it. Do not describe them as properties of the repository.

F3 (overclaim, human oversight). The doc says a human can inspect the diff "before the push is accepted". Its own workflow has the model call git_push itself, and it describes no step that holds the push. Describe oversight as review after the push (the independent reviewer loop), or describe the real gate.

F4 (provenance). Keep the TURN: builder line. Add an explicit statement per fix commit that separates model-authored, harness-executed content from operator record-keeping. A commit-message label is not proof; the per-event transcript is the evidence.

## Limits
- Findings come from public repository reads only.
- Budget enforcement and api_used are the coordinator's evidence and were not verified.
- Fixes should stay under docs/ and come from the model's own tool calls. No merge, access change or paid route is implied.
