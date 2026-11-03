# Bill evaluation - author-side lessons for this blueprint

*Written by Bill (the QC seat on the reference project), 4 Nov 2026, at the owner's request. Author-side lessons learned, not independent QC of this repository, and not a revival of the old roles.*

## Scope and sources

| Item | Value |
| --- | --- |
| Target reviewed | `coolkowkank/Multiple-Human-Concept-Owner`, `main` @ `5ddf649286e306510d91cd53df0780252c4f0270` (reviewed at `fc81357`; the later README goal section and `Joe_Evaluation.md` were checked and change nothing cited here) |
| Source project | `coolkowkank/Nordea-x-Aalto-Banking-`, `instinct-prototype-v3` @ `08047a0639301700b99f1142ca3f2c9003f7dd0f` |
| Period covered | 3 Nov 2026, about 01:45-20:35 Helsinki time (one Bill session) |

Each point below is labelled by where it comes from:

- **[S] Session recollection.** What this Bill session saw and did on 3 Nov. It can be checked in the source repo's `review.md` history, but the judgement is mine.
- **[R] Repo-backed.** Counted or cited from the source repo at the pinned commit.
- **[J] Joe's contribution.** Selected by the owner and attributed to Joe in its own section; Joe did not write this file.
- **[U] Unavailable.** Context I did not have, and therefore did not use.

Left out on purpose: assistant prompts and configuration, internal operational records and transcripts, private conversations, personal details, and authority claims. Old handoff files were used only as historical evidence.

**[U] Unavailable context.**
- Earlier Bill sessions (1-2 Nov), apart from what they committed.
- The project Slack channel. I only saw owner words that someone committed verbatim.
- The hosted Supabase project. I never connected to it.
- The Coordinator's and Builder's own sessions.
- Any run of this blueprint by a fresh team. Nothing here tests the blueprint itself.

## Short assessment

The blueprint keeps the things that worked: human gates, one queue, a single writer, QC that the Coordinator cannot override, and written evidence. It is also honest about what it has not tested (`docs/proposed-vs-tested.md`).

What still forced routine human intervention on the reference project was not judgement. It was plumbing:

- waking sessions and keeping them alive;
- proving who said what;
- catching green claims that nobody had re-run;
- resolving role and turn confusion.

None of these is closed by the current text. Most of them can be closed by adding a few checkable fields and one enforced check. No new authority is needed.

## Where routine supervision still came from (project-grounded)

### 1. Humans as the wake-up and liveness layer

- **[S]** The owner asked "Check", "Status?" or whether the watcher was still on at least five times in one day, mainly to find out whether work was moving. The QC watcher died on a container restart and twice on its two-hour limit. Both times nothing moved until a human noticed.
- **[S]** Two Bill sessions ran at the same time and gave opposite verdicts on the same question, minutes apart. Only the owner could stop one of them.
- **Template today.** `docs/delivery-flow.md` (Handoff caveat) and `docs/delegation.md` §8 say the session-to-session route is unverified, and that humans remain the transport. That is accurate, but no minimum mechanism is defined, so the gap stays open by default.

### 2. Proving owner words cost more rounds than the decisions did

- **[S]** QC had to hold back or block acceptance at least seven times because an owner decision existed only as a timestamp, or as a builder's paraphrase:
  - autosave;
  - Nordea-model risk;
  - realtime updates;
  - live paid runs;
  - the merge grant;
  - the hosted smoke;
  - the insight scope.

  Each one cleared only after the Coordinator committed the verbatim words with a timestamp and permalink, usually as `evidence/<topic>/*.md`.
- **[R]** Such verbatim records now exist under `evidence/g61/`, `evidence/insight/` and `evidence/hosted/`. Every one of them was written after the work, on request.
- **Template today.** `docs/delegation.md` §1 says the repository record is evidence, not a grant, and the owner's own channel decides disputes. QC cannot read that channel, so the only way to get the evidence is to ask a human.

### 3. Self-declared role changes

- **[R]** `DECISIONS.md` D13 swapped the Coordinator and Builder seats. The record was written by the seat that gained the authority.
- **[S]** QC could not rely on it until the owner confirmed it in QC's own chat.
- **Template today.** `docs/delegation.md` §5 says rules bind to roles, and changing who fills a seat updates the roster. It does not say who may write that change.

### 4. Green claims that were not green

- **[R]** Three batches claimed "green" while a suite they had not run was red:
  - G63: the adapter suite failed 42/2 after a seed change;
  - G81: the insight suite failed 52/1 after a query changed;
  - G73: a Builder push went out off-turn, with no hand-over.
- **[S]** Every time, the QC re-run of the full suite list caught it, not the batch itself.
- **Template today.** `templates/batch-handoff.md` has "Tests run and results: <list>", but no required suite list, no head hash and no exit codes.

### 5. Most real defects sat next to the fix, not in it

- **[R]/[S]** The highest-value findings came from probing the neighbour of a fix in a scratch environment:
  - G64: the setup script wiped `.env.local` and wrote a stale role password;
  - G69/G70: a grant took a default inherit option, and a grant aborted on roles the owner had no admin rights on (shown on a throwaway local PostgreSQL);
  - G60: a test fix also hid nested raw ids;
  - G59: an unbounded id length.

  None of these were in the claim being reviewed.
- **Template today.** `templates/review-findings.md` and `templates/qc-verdict.md` record findings and verdicts. Neither asks what was reproduced or probed, or what was only read.

### 6. Format and turn mechanics stalled everyone

- **[R]** 59 commits on 3 Nov were off-turn (`TURN: … (unchanged)`). The source protocol grew to 35 numbered rules (`review-protocol.md`), many of them patches for wake-ups, batching and message length.
- **[S]** Two messages with missing code fences failed the shared guard for every agent until someone fixed another agent's text. One Telkomsel/Bill exchange looped on acknowledgements with no work in it.
- **Template today.** `docs/operating-rules.md` rule 2 (turn token) has no machine check, and no rule against acknowledgement-only hand-backs.

### 7. "Done" was not defined, so the merge needed a fresh human call

- **[R]** The owner's merge grant (`evidence/g61/owner-merge-grant.md`) said "when everything is finish". After QC went green, three hosted limits were still open, and only the owner could say whether they counted.
- **Template today.** `templates/concept_to_coordinator.md` has "Acceptance criteria", but no list of the residual limits the owners accept.

## Recommendations (prioritised)

Each recommendation names the target file to change and the evidence above that motivates it. All of them keep the human gates.

**P1 - Record owner words at decision time, in one place** (gap 2)
- In `docs/delegation.md` §1, plus a new template `templates/decision-record.md`, require these fields at the moment of the decision: `ID · Date · Owner · Verbatim words · Channel + timestamp + permalink · Covers · Limits · Recorded by`.
- The Coordinator writes the entry when it relays the decision, not later on request.
- QC treats a gated item with no entry as a blocker. A gated item with an entry needs no new human ask.
- The owner's channel still settles disputes.

**P2 - Make roster changes owner-recorded only** (gap 3)
- Add to `docs/delegation.md` §5: a seat change takes effect only through a decision record (P1) from the owners. The seat that gains authority never writes it.
- QC and the Builder ignore a roster change until that record exists.

**P3 - One machine-checkable green per batch** (gap 4)
- In `templates/batch-handoff.md`, replace "Tests run and results" with:
  - `Head: <full hash>`
  - `Verify command: <one command that runs every required suite>`
  - `Exit code: <n>`
  - one line per suite: `<suite>: <pass>/<fail>`
- In `docs/operating-rules.md`: a batch counts as green only when the Reviewer re-runs the same command on the same hash and gets exit code 0. Where the project has CI on the agreed branch, CI replaces the human re-run.

**P4 - A single-holder lease for each seat, plus a minimum wake mechanism** (gap 1)
- In `docs/delivery-flow.md` (Handoff caveat) and `docs/operating-rules.md`, add:
  - **Lease.** Each seat holder writes `<seat>: <session id> since <time>` to the roster. A second session for the same seat stops and reports instead of acting.
  - **Wake.** State the minimum route: poll the shared repository's turn line, with a restart plan before the poller's time limit. Make "is the watcher alive" part of the Coordinator's milestone report, so humans don't poll for it.
- Keep the honest wording that sessions cannot start each other.

**P5 - Reviewer and QC record reproduction and probes** (gap 5)
- Add to `templates/review-findings.md` and `templates/qc-verdict.md`:
  - `Reproduced: <claims re-run, with results>`
  - `Probed: <neighbouring paths tested, and how>`
  - `Read only: <what was not run>`
- Allow throwaway local environments, such as a scratch clone, a fake client or a local database, as long as nothing live is touched and they are deleted afterwards.

**P6 - A fixed evidence shape for gated runs** (gaps 2 and 7)
- New template `templates/gated-run-evidence.md` with these fields:
  - decision record ID (P1);
  - target and scope;
  - counts before and after;
  - test identity;
  - rows or objects touched;
  - cleanup query and result;
  - what was not proven;
  - a "no secrets" check.
- Reference it from `docs/delegation.md` §4.
- In the reference project, the Coordinator's later evidence files already had this shape and passed QC on the first read.

**P7 - Define "done" in the brief** (gap 7)
- Add to `templates/concept_to_coordinator.md` a section `Done definition and accepted residual limits`: what must be proven, and which named limits may stay open without blocking a merge or go-live.
- A merge grant then points to that section rather than to "everything".

**P8 - Enforce mechanics with a guard; cut process chatter** (gap 6)
- In `docs/operating-rules.md`, add:
  - **Guard.** One pre-commit or CI check of the shared handoff file: turn line present, messages fenced, length limits, `NEXT` matching the turn. Each assistant runs it on its own commit only, and never fixes another assistant's text.
  - **No acknowledgement-only hand-backs.** A hand-back must carry new work, a verdict or a decision request.
  - **Off-turn pushes.** Name the exceptions, such as a relayed owner instruction or a requested answer. Every other off-turn push is a process finding.
- Keep the rule count small: when a rule patches a mechanism, fix the mechanism instead.

## What should stay unchanged

- Concept, scope, spend and go-live decisions stay with the humans (`docs/operating-rules.md` rule 5, `docs/delegation.md` §4).
- One agreed brief with a change history (`templates/concept_to_coordinator.md`), and one Coordinator with one queue.
- An independent QC fail stands and the Coordinator cannot override it (`templates/qc-verdict.md`, README roles table). In the reference project, QC holding at "not accepted" was what caught every defect above before merge.
- Distinct delivery capacity:
  - one main delivery job per assistant;
  - Records shared only while mostly idle;
  - Coordinator and Reviewer as separate assignees;
  - QC never the Builder (README "Capacity rules", D5).
- Capability honesty (`docs/delegation.md` §8) and the proposed-vs-tested map. The recommendations above are proposals too, and should be listed under "Proposed here (untested)".

## Joe's contribution [J]

*Contributed by Joe (the Records seat, from the evening of 3 Nov), selected and supplied by the owner on 4 Nov. Bill condensed it lightly and kept Joe's own source labels. Joe wrote nothing to any repo. Joe's view of earlier sessions, and any count of owner interventions, is unavailable.*

1. **Authority evidence was asked for after the work, not captured with it - routine cause #1.** Autosave, realtime, D9, the merge grant and the live-run go each waited a turn for a verbatim quote plus timestamp. (Joe: repo-backed `DECISIONS.md` D7, D9-D11, G61; recollection of the stalls.)
   - Change: an "Owner basis" line (quote and timestamp, or delegation ID) in `templates/batch-handoff.md` and `templates/qc-verdict.md`.
   - Change: `docs/delegation.md` §1 and §7 require it in the decision log at decision time.
2. **"Finished" was never defined - routine cause #2.** Open hosted limits left the merge grant unresolved. (Joe: repo-backed G77, G80.)
   - Change: "Definition of finished" and "accepted limits" sections in `templates/concept_to_coordinator.md`.
   - Change: a "stated limits: accept or waive" field in `templates/qc-verdict.md`, so the owner is asked once, with options.
3. **Local proof was mistaken for hosted proof.** A local run as superuser skipped a permission check that then failed on the hosted project. (Joe: repo-backed `DECISIONS.md` D13 addendum, `evidence/hosted/set-role-fix-2026-11-03.md`.)
   - Change: an environment label (local, hosted or mock) on "Tests run" in `templates/batch-handoff.md`.
   - Change: name the required proof environment in the brief's acceptance criteria.
   - Proposal: one owner-set, bounded hosted-test envelope (cap, project, cleanup owner) set up front, so reruns inside it don't need a fresh ask. Spend stays a human decision (`docs/delegation.md` §4).
4. **A mid-project role swap left stale docs and unconfirmed pickups.** (Joe: repo-backed D13, G74, G78.)
   - Change: a roster template (seat, assistant, verified endpoint, git identity).
   - Change: a role-change checklist in `docs/delegation.md` §5 - update the roster, notify, record a written pickup, mark old handoffs historical.
   - Change: re-check the readiness table in `templates/coordinator-starter-prompt.md` step 3 after any role change.
5. **A written turn token did not stop an off-turn code push.** (Joe: repo-backed G73; recollection that the guard checked only that the turn line matched NEXT.)
   - Change: ship a small turn-check hook with `templates/batch-handoff.md` that rejects commits outside the turn holder's allowed paths.
6. **Findings mixed defects, remaining jobs and priority.** Joe gave remaining jobs IDs (G74-G80), normally a QC task, at the owner's request. An owner priority marking was easy to read as an approval. (Joe: recollection; repo-backed G80 row.)
   - Change: in `templates/review-findings.md`, separate severity from priority, add an "owner gate" column, give job rows their own prefix, and say who may issue IDs.
7. **Lessons never saved to the repo** (Joe: recollection unless noted):
   - Watch loops die and each wake-up costs context, so repeated owner status questions fell on Records. The Coordinator should keep a one-line status chain in the brief; add a re-arm note to `docs/delegation.md` §8.
   - The pre-commit guard compared message times with the machine clock in UTC (`scripts/check_review_lines.py:54`, repo-backed in the source), while the team wrote Helsinki times. It blocked Joe's commits twice. Name one project time zone in the brief.
   - A manual archive count was misreported (5 vs 22). Archive tooling should print the count.
   - The owner asked three times for the hot file to be slimmed. Add size limits and an automatic archive step to the templates.
   - Ask each owner once for their status-report format, and record it in the brief.
8. **What held up.** QC's "readiness not green" verdict was honoured: the Coordinator supplied evidence instead of overriding it. The one-main-job rule held for Records only because Records had no turn.

**Joe's verdict on the main test:** the project was not close to "very rare routine intervention". Most routine interventions were authority evidence, undefined finish criteria and role-handoff paperwork, which the template changes above can address. The owner's spend, merge and go-live decisions stayed human, as intended.

**Where Bill and Joe agree:** Joe's points 1, 2, 4 and 5 match Bill's P1, P7, P2 and P8 independently. Joe's point 3 (environment label, bounded hosted envelope) and point 6 (job vs defect rows) add to Bill's list and are not covered above.

## Caveats

- This evaluation rests on one project and one day of one QC session. It shows where supervision came from there; it does not prove these changes will remove it elsewhere.
- Counts are from the pinned source commit. Where a finding ID is cited, its full row is in the source repo's `review.md`, `review-verified.md` and archive.
- No claim is made about model capability, speed or cost.
- `Joe_Evaluation.md` was pushed to this repository separately by Joe's seat (`5ddf649`). The Joe section here is the owner-supplied selection, not that file. Where the two differ, the owner's selection was used.
