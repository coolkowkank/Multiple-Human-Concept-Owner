# WP4 completion-guard integration contract (preparation only)

2026-11-04. RecoveryExecutor. NOT an implementation, accepted guard, live-run
permission, merge request, or proof of autonomous completion.

## Current composition and gap

Original runtime correction 26ff4bce5666afd6a3dbefbce7fe0d3d4a36e341:
independent local F1-F4 re-review closed, 8 deadlock / 167 full-suite tests;
unit scope only. Separate accepted latch candidate:
561f2e5cc4eb84b4cdcbacd81394a882495b8704. Neither establishes Reviewer
participation. The task-only reviewer-skip branch 55e7c7e proposes QC evidence
but does not require a Reviewer, so it is not an adequate implementation spec.

Source inspection: runtime._apply runs the verify command, captures its exit
and tail, appends a generic handoff, then marks any status_line beginning DONE
as done. There is no structured verdict identity, application binding, Reviewer
participation check, or role-gated completion here. Current conformance accepts
verdict-kind log records but runtime currently emits handoff records for all
seat responses. A prose PASS, log file, seat name or schema is not execution
provenance.

## Smallest integration surface, once explicitly assigned

1. NEW pure completion-policy module and fault fixtures. No provider adapter
   changes or retry changes. Prepare against the agreed accepted runtime/latch
   composition, not the older team-launcher code in this audit branch.
2. The runtime, not the model, stamps structured evidence after independently
   running the specified verification command and checking allowed writes and
   active seat/turn. Binding and execution outcome come from runtime observation.
   The Reviewer/QC must be distinct eligible seats from the Builder and each
   other; a configured role alone does not establish independent reasoning.
3. DONE check occurs after this response's writes/verify are visible and before
   setting done. Compare current application binding to both evidence records.
   Any writes during the DONE response must be included in the binding check.
4. Preserve existing budget, human-gate, lease, rollback, verification-failure
   and raw-output behavior. Missing/stale evidence routes only via an agreed
   bounded review/gate path; never fabricate PASS, repair a response, or add a
   model correction outside existing caps.
5. Test the pure predicate first, then runtime integration and the agreed
   composition, independently reviewed before any live run. No held privileged
   executor release follows from passing these tests.

## Binding proposal for review, not adopted policy

Freeze an explicit allowlist of application + test paths for the tiny target
(e.g. tinylib/ and tests/), plus exact acceptance brief, runtime-policy commit,
verification command and roster/role-policy digest. Derive an application
manifest from actual tracked entries (path, mode, content digest); order
canonically and hash the complete manifest. Deletion, executable mode changes,
renames, newly added application files and unstaged/staged changes must be
covered or refused. Do not inspect only the old pin's file list and miss a new
file. Reject symlink/path escape, ambiguous/untracked executable inputs and an
unresolved dirty application tree until a separately reviewed policy covers it.

Store repository commit provenance separately from application manifest digest.
Evidence/log-only commits under explicitly excluded paths may advance HEAD
without changing the reviewed application state. A change to brief, runtime
policy, verification command or role configuration invalidates the acceptance
binding even if application files do not change. Exclusion must not permit a
review artifact or .team file to alter test imports/behavior unnoticed. The
Reviewer and QC evidence must contain the same complete acceptance binding,
not merely the same application file hash.

Evidence records need: version, runtime-stamped seat/role and turn sequence,
application/acceptance binding, source application commit, runtime-policy pin,
verification command and observed exit, verdict, evidence artifact digest and
record provenance. Definition of independence, PASS semantic rubric and record
integrity remain integration-review questions. Text supplied by a model cannot
stamp these execution facts on its own. Runtime-observed verify exit=0 is
necessary but is not sufficient for an independent semantic PASS.

## Required fault fixtures for the future implementation

| Fixture | Expected outcome |
|---|---|
| DONE, neither verdict | Refuse completion |
| QC PASS only | Refuse: Reviewer absent |
| Reviewer PASS only | Refuse: QC absent |
| Both PASS, same complete binding and independent seats | Eligible, all other checks still apply |
| Both PASS, different application digest | Refuse: stale/mismatched application |
| Same app, changed acceptance brief/runtime/roster/command | Refuse: changed acceptance binding |
| Evidence/log-only commit, unchanged complete binding | Remains eligible; latest HEAD equality not required |
| App write in same DONE response after earlier reviews | Refuse: stale evidence |
| Added/deleted/mode-changed app file after reviews | Refuse: changed manifest |
| Self-labelled Reviewer/QC prose or forged role/turn | Refuse: no runtime provenance |
| Builder supplies both verdicts | Refuse: independence absent |
| Reviewer or QC verify exits nonzero | Refuse, retain failure evidence |
| Missing Reviewer/QC in roster | Human gate, never silently skip |
| Evidence or application binding unreadable/ambiguous | Fail closed, preserve original failure |
| Non-DONE response | Existing behavior unchanged |
| Dirty/staged changes, commit failure or restart | No stale done flag, no evidence lost or silently accepted |

These are expected cases only, not executed guard tests. The audit module's
18 focused / 214 full-suite results do not cover any completion guard above.

## Integration checkpoints

Freeze binding + review routing with the independent reviewer before shared
runtime edits. Confirm the current writer has released the relevant files or
coordinate through the project owner. Publish a small isolated candidate,
retain exact source pin and run the fixture matrix + full offline suite. Then
request independent review of both predicate and runtime call ordering. Only
after accepted composition should a new scoped live-run envelope be considered.
No provider probes, spend, old budget reuse, merge, deployment, or autonomy claim
is implied by this document.
