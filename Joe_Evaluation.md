# Joe_Evaluation.md - Records-seat lessons learned (author side)

*Author-side experience transfer from the Records seat of the reference project. This is not independent QC and not a resumed implementation. Bill's evaluation is a separate file.*

## 1. Scope, sources and limits

**Seat.** Records (Joe): context memory, archive of hand-offs, the short "state" section of the hot review file. I held no turn, wrote no application code, and decided no scope, spend, go-live or merge question.

**Window.** My first-hand view starts in the early hours of 3 Nov 2026 and runs to 4 Nov 2026 (one long session). Everything before that, and any count of human interventions, is **unavailable**.

**Labels used throughout**

| Label | Meaning |
| --- | --- |
| **[repo]** | Checked against a file in one of the two listed repositories at the time of writing |
| **[recall]** | My own recollection of the session; not independently checkable from the repos |
| **[unavailable]** | I have no first-hand evidence; I do not reconstruct it |

**Read.** Target: `README.md`, `docs/*`, `templates/*` (main at the time of writing). Source (`instinct-prototype-v3`, [link](https://github.com/coolkowkank/Nordea-x-Aalto-Banking-/tree/instinct-prototype-v3)): `DECISIONS.md`, the findings table in `review.md`, `review-findings-detail.md`, `review-verified.md`, `TEAM.md`, `scripts/check_review_lines.py`, and the file list under `evidence/hosted/`.

**Deliberately not used.** Assistant prompts and configuration, the message archive and other operational records or transcripts, private conversations, personal details, and any claim of someone's authority. The source repository contains such material; none of it is cited here. Older handoff files are historical only.

## 2. Short assessment

Against the target's stated goal in `README.md` ("autonomous AI-human teamwork with very rare routine human supervision"), the reference project did **not** reach that level. [recall + repo] Humans stayed in the loop for routine items, not only for the reserved decisions.

What kept humans involved was mostly **not** the decisions the blueprint reserves for them (concept, scope, spend, go-live). It was clerical and structural friction that a template can remove:

1. Proof of who had authorised something was supplied after the work, on request.
2. "Finished" was never defined, so the final call could not be made by rule.
3. Local proof was easy to mistake for hosted proof.
4. A mid-project role change left stale documents and unconfirmed hand-overs.
5. The write turn was a convention, not a mechanism.
6. The records seat was woken by human requests for status and compaction.

The reserved human decisions held, and independent QC remained separate from the Builder. No part of this file claims unattended delivery was demonstrated. [repo: `docs/proposed-vs-tested.md` makes the same point]

## 3. What still forced routine human intervention

Each row: the cause, its label and evidence, and where the target template is silent.

| # | Cause | Label and evidence | Target gap |
| --- | --- | --- | --- |
| A | **Authority proof requested after the work.** Decisions taken under a standing delegation were recorded as the Coordinator's own, and the exact owner words and timestamps were supplied only when the review loop asked. Several scope items were accepted only once those quotes were committed. | [repo] source `DECISIONS.md` D7, D9, D10, D11 ("scope basis" quoted in a later Coordinator commit) | `docs/delegation.md` §1, §7 and `templates/` have no field that records the owner basis at decision time |
| B | **No definition of "finished".** A merge grant said "when everything is finished"; open, stated limits (hosted provisioning, TLS, pooler user form) left it unclear whether the condition was met. A priority marking by the owner on the merge row was explicitly *not* an approval or waiver. | [repo] source `review.md` findings G77, G80; `DECISIONS.md` D13 addendum (fix acceptance, hosted rerun and merge on HOLD) | `templates/concept_to_coordinator.md` has "Acceptance criteria" but no accepted-limits or stop-condition section |
| C | **Local proof mistaken for hosted proof.** A hosted initialisation failed on a role-permission step that local runs, executed as a superuser, bypass. | [repo] `DECISIONS.md` D13 addendum; `evidence/hosted/set-role-fix-2026-11-03.md` ("Local proofs ran as a real superuser, which bypasses the check") | `templates/batch-handoff.md` "Tests run and results" has no environment label |
| D | **Role change and unconfirmed pickups.** The Coordinator and Builder assignments changed mid-project. Team documents still named the previous assignee; the notice reached only a former operator, so the live endpoints stayed unconfirmed. | [repo] `DECISIONS.md` D13; `review.md` findings G74, G78 | `docs/delegation.md` §5 ("Roles, not identities") says rules bind to roles but gives no roster template or change checklist |
| E | **Turn discipline was a convention.** A code fix was pushed while the written turn named a different role; a stricter storage limit than the one the Coordinator had decided was pushed first. Both were disclosed afterwards and left unratified or ratified later. | [repo] `review.md` finding G73; `DECISIONS.md` D12 (length timeline, "process deviation, disclosed"); the project guard `scripts/check_review_lines.py` checks that the turn line matches the newest next-actor line and message format, not which files a commit touches | `templates/batch-handoff.md` states "No AI writes without holding the written turn token" but ships no check |
| F | **Hot file growth.** The shared review file kept growing and was compacted by hand. The archive counter reached 191 earlier messages by the time of writing. | [repo] `review.md` counter; [recall] I was asked several times to compact it, and once reported an archive count that was wrong because I wrote it by hand | `templates/review-findings.md` and `batch-handoff.md` set no size or archive rule |
| G | **Findings table mixed defect rows with remaining-work rows**, and Records was asked to assign IDs, a QC task. Severity and owner priority were easy to conflate. | [repo] `review.md` findings G74-G80 (marked "Joe-assigned; Bill to confirm"), G80 row | `templates/review-findings.md` has Severity but no priority, owner-gate or ID-issuer field |
| H | **Tooling friction.** The guard compares message times with the machine clock (`datetime.now()` at line 54) while the team stamped local time, which blocked commits until the time zone was set per command. Background watch loops expired after roughly an hour and had to be restarted. | [repo] `scripts/check_review_lines.py:54`; [recall] blocked commits and loop expiry | `docs/delegation.md` §8 says sessions cannot message each other, but not that watchers expire |

**Not exercised.** The reference project had no separate Reviewer seat that I can evidence; its team file states only that new code needs "a reviewer who did not write it" and names QC. So the target's Coordinator / Reviewer / QC separation is **[unavailable]** as a tested pattern from my side. [repo: source `TEAM.md`]

## 4. Prioritised recommendations

Priority reflects how often the cause forced a human step, not effort. Each change names a target file; none alters a reserved human decision.

### P1 - Capture authority at decision time (cause A)

- **Add `templates/delegation-record.md`.** `docs/delegation.md` §1 refers to a `DELEGATION.md` in the project repository, but `templates/` has no template for it. Columns as in §1 (owner, delegated decisions, delegated actions, limits, revocation) plus "owner's own words" and "where to verify".
- **Add an "Owner basis" line** to `templates/batch-handoff.md` and `templates/qc-verdict.md`: delegation ID, or the owner's quoted words with source, for any scope, spend or go-live item.
- **Add an "Evidence" column** to the "Decisions log" in `templates/concept_to_coordinator.md`.
- Keep `docs/delegation.md` §1's rule that the repository record is evidence, not a grant.

### P2 - Define "finished" and accepted limits up front (cause B)

- In `templates/concept_to_coordinator.md`, add **Definition of finished**, **Accepted limits** (named, owner-agreed) and **Stop conditions** (what the team may not resolve itself). This matches the exceptions listed in the target `README.md` goal section.
- In `templates/qc-verdict.md`, add **Stated limits** with an **Accept / waive** field, so the owner is asked once, with options and a recommendation (`docs/delegation.md` §3).
- State in `docs/delegation.md` §4 that a priority label is not an approval.

### P3 - Label the environment and bound hosted testing (cause C)

- `templates/batch-handoff.md`: each test line carries an environment (mock, local, hosted) and the account type used.
- `templates/concept_to_coordinator.md`: acceptance criteria name the environment where proof is required.
- `docs/delegation.md` §4 already lets a written delegation cover spend "with its limits". Provide a delegation-record example with an owner-set spend envelope (cap, project, who cleans up) so reruns inside it need no new ask. The humans still set the envelope. This is a template example, not a rule change.

### P4 - Roster with verified endpoints and a role-change checklist (cause D)

- Add `templates/roster.md`: seat, responsibility, assistant, human owner, verified endpoint, required commit identity, date last verified.
- Extend `docs/delegation.md` §5 with a checklist: update the roster, update documents that name seats, notify, record a written pickup, mark old hand-offs historical.
- `templates/coordinator-starter-prompt.md` step 3 already tracks readiness and access; add a re-check after any seat change.

### P5 - Make the turn a mechanism (cause E)

- Ship a small, path-scoped hook with `templates/batch-handoff.md`: a commit is rejected when the committer is not the turn holder, or touches paths outside that role's allowed set.
- Add a rule that a decision needed mid-batch is raised as a question before the commit, not disclosed after.
- Keep `docs/operating-rules.md` rule 2 as written; this only enforces it.

### P6 - Findings fields and ID discipline (cause G)

- `templates/review-findings.md`: add Priority (separate from Severity), an owner-gate column and an ID issuer. Keep remaining-work rows under a different prefix from defect rows.

### P7 - Records hygiene and status without Records (causes F, H)

- Put size limits and an archive rule in the templates (for example a message limit per hand-over and "archive all but the newest two once past a set count"), and provide a script that prints the archive count and header time instead of relying on the author.
- Ask each owner once for their status format and record it in the brief; the Coordinator keeps one status line there, so routine status questions do not fall to Records.
- Add to `docs/delegation.md` §8: watchers expire, so a re-arm rule or a scheduled check is needed; "watching" is not a standing capability.
- The guard should read one project time zone from the brief.

## 5. What should remain unchanged

- **Reserved human decisions** (`docs/delegation.md` §4): scope, spend, security, go-live and merge, and changes to the brief, with the recorded change history in `templates/concept_to_coordinator.md`.
- **One Coordinator and one queue**; peers do not reassign each other (`docs/delivery-flow.md`).
- **Independent QC separate from the Builder, and a QC fail stands** (`README.md`, `templates/qc-verdict.md`). In the reference project a QC "not ready" position was answered with evidence rather than overridden. [recall]
- **One main delivery responsibility per assistant; Records only while mostly idle.** Records worked here only because it had no turn and no write authority over code. [recall]
- **Coordinator and Reviewer as separate assignees** (`README.md`). I cannot evidence this from the reference project (see section 3). It should stay as designed, and be tested.
- **Written turn token and single writer**, and **capability honesty** (`docs/delegation.md` §8, `docs/proposed-vs-tested.md`): reporting verified, planned and unknown separately was the most useful single habit.

## 6. Caveats

- One project, one seat, about one day of first-hand view. This is a lessons-learned input, not a measurement of intervention rates **[unavailable]**.
- No claim is made that these changes would produce unattended delivery. They remove specific, evidenced friction; the effect is untested.
- Citations to the source repository point to its `instinct-prototype-v3` branch, which may change. Hashes and finding IDs are cited by name so a reader can locate them.
- I did not read or cite the source repository's assistant prompts, operational archive or transcripts.
