# Joe Legacy Evaluation: what the humans did at the start, and the minimum for a one-prompt kickoff

*Author-side lessons learned from the records / context-memory and protocol seat of the reference project. This is not an independent QC review, not a resumed role, and not authorization to change any template or process in this repository. Everything proposed below is for the concept owners to accept or reject. Prepared 4 Nov 2026.*

## How to read this

- **[R]** repo-backed evidence, with file and branch.
- **[S]** original-session recollection: what this seat itself saw or did.
- **[U]** unavailable: not observed by this seat, so not reconstructed.

Scope: this seat's own window, from the first morning of the agent-team phase (31 Oct 2026) to early the next morning, plus short read-only check-ins afterwards. Seats are named by role. No transcripts, prompts, configuration, private exchanges, personal details or authority claims are reproduced. "Owner" means the human concept owner.

## Short answer

What let the AI team work with low routine supervision was four things, done early:

1. **A checkable destination.** A goal in plain words, then numbered acceptance criteria that a separate QC seat tested against. "Done" was a QC pass at a named commit, not a feeling. [S]
2. **Structure before leaving.** Separate seats with one rule each (the builder writes code; QC reviews and never edits code; the records seat edits only the shared memory), and one shared coordination file with a turn marker and append-only messages. [S]
3. **The few gates no prompt can pass**, handled once: repository push access, hosted accounts and privileged setup, spend and provider, scope calls. [S]
4. **Staying reachable for short answers**, then stepping away for hours. [S]

Unattended autonomy was **not** achieved. Long build and review stretches ran without owner input, but the owner still made scope decisions, handled access, and woke the team with prods and status questions: a few dozen short messages over roughly 17 hours. [S]

## 1. Human-only decisions and access

| Item | What happened | Label |
|---|---|---|
| Concept and direction | Direction moved in stages: a README redesign, then a three-agent prototype, then a single-system rebuild. Each step was an owner decision; agents proposed but could not settle it. | [S]; staging visible in `README.md` ("Final prototype" section), branch `ai-agent-communications` [R] |
| Scope and "done" | The owner described the expected behaviour once in plain words. The QC seat turned it into numbered criteria and baseline findings. Later scope calls were small and quick, e.g. whether the shared document is rebuilt per question or per session: answered within minutes, then corrected once. | [S] |
| Out-of-scope calls | Real external-agent integration was deferred to a later branch by owner decision. | [S] |
| Repository access | A read-only clone worked with no grant. The first push failed (HTTP 403) until the repository was attached to the session with push rights. A builder seat used a temporary credential, reported removed at close; who issued it is **[U]**. Early on, each AI change reached the base branch as a human-merged pull request (five in about 70 minutes, 28 Oct); later phases used direct pushes to a working branch under written rules. | [S]; early merge pattern in commit history, branch `ai-agent-communications` [R] |
| Secrets and accounts | API keys and the hosted-database URL/secret are environment variables, never committed. The owner ran the privileged database SQL; the builder held only a read-only token and shipped the migration for the owner to run. | variable names in `.env.example`, branch `Instict-prototype` [R]; rest [S] |
| Spend and provider | The requirement that every agent be model-driven came from the owner. Provider, plan and cost limits: **[U]**. The owner's token-cost concern surfaced late (about 18 hours in) and led to a fresh session. | [S]; limits [U] |
| Seats and names | Which seats exist, adding seats mid-project, names and signatures were owner decisions. | [S]; four seats listed in `README.md` ("About this README"), branch `ai-agent-communications` [R] |
| Merge, deletion, close | The owner decided pushes to the protected branch (overriding a written "never main" rule once), removal of exported agent-configuration files from the public repository, and dismissing the team. | [S] |
| Data and privacy sign-off | The data was fictional, so no sign-off was exercised. | [U] |

Before this seat started (who created the repository, how the first seats were opened, what the other seats were told, the original concept discussion): **[U]**.

## 2. What the humans did that the team could have done

- **Resolving imprecise names.** The first request named a branch and a file slightly wrongly. This seat listed the remote branches and found the right ones. A repository URL plus a goal is enough. [S]
- **Authoring the coordination rules.** The first coordination file, turn rules and message format were drafted by agents; the owner only asked for refinements after friction. A kickoff can generate them. [S]
- **Cosmetic choices.** Naming and signatures could be delegated. [S]
- **Relaying between seats.** Several owner instructions reached other seats second-hand through one agent, which nobody could verify. One shared file with a clearly marked owner-question section removes the relay. [S]
- **Status requests and wake-up prods** ("check again", "where are we"). A one-line chain in the memory section answers these; the owner later asked for exactly that. [S]
- **Merging every AI change by pull request.** Replaced by a working branch, written rules and a QC gate. [R] history of `ai-agent-communications`; [S]
- **Closing evidence.** Exports and evaluations were requested one by one; they could be a standing close-out step. [S]

## 3. Avoidable interventions versus gates that should stay human

| Intervention | Verdict | Why, and what would remove it |
|---|---|---|
| Wake-up prods; "are you still watching?" | Avoidable | Agents polled the repository; background checks expire (30 minutes to 2 hours), so the team went quiet. A standing wake-up route, or an expiry notice in the file, would remove it. [S] |
| Status questions | Avoidable | A one-line progress chain at the top of the memory section. [S] |
| Second-hand relays of owner decisions | Avoidable | Put owner decisions in the shared file with a time, quoted. [S] |
| Fixing misnamed targets | Avoidable | Let the first seat resolve them against the real repository. [S] |
| Restarting a long session | Human, but avoidable in cause | Only a human can open a session. Cause was growing context; a short hot file plus a handoff folder shortened it. [S] |
| Answering a design question the brief left open | Required, but cheap if prepared | The QC seat recorded a default assumption and carried on; the owner's answer arrived hours later and needed one correction. Keep this pattern. [S] |
| Access, credentials, privileged SQL, secrets | **Keep human** | No prompt can create or verify them. [S] |
| Spend, provider, paid model use | **Keep human** | [S] |
| Scope or goal changes; approving a new phase | **Keep human** | [S] |
| Merging to the protected branch; go-live | **Keep human** | One overriding of a written rule happened only on explicit owner request. [S] |
| Deleting data or files; where agent configuration lives | **Keep human** | Exported agent configuration did not belong in a public repository. [S] |
| Closing and dismissing the team | **Keep human** | [S] |

Other avoidable costs, from team habits rather than owner action: stale-copy overwrites of the shared file (twice, early), made-up message times (ahead of the real clock), and one wipe of the file's sections. These were fixed by pull-before-edit, append-only, non-force pushes and, later, a pre-commit check. A kickoff should install those on day one. [S]

## 4. Minimal reusable kickoff

**Inputs the human supplies (about one page):**

1. Goal, non-goals, and "done means a QC pass on every criterion at one named commit".
2. Repository URL, base branch, new working branch, paths agents may edit, and forbidden actions (protected branch, force-push, secrets in the repo).
3. Seats, one line each: Builder (sole writer), QC (separate session, never edits code), Records (edits only the memory section).
4. Owner-only gates and the default while waiting: merge or go-live, access and credentials, spend, deleting data or files, goal or scope changes.
5. Spend and time envelope: provider, free or capped, hours away, how progress is reported.
6. Where questions go (an owner-question section in the shared file) and what happens if unanswered (a recorded default).
7. Close rule: QC pass plus builder confirmation, then the turn marker is set to none, then the owner reviews.

**The one opening prompt** (a proposal; it complements `templates/coordinator-starter-prompt.md`, which is a longer step-by-step setup flow):

```text
You are the Coordinator of a small AI delivery team. I am the owner. I decide scope, spend, access, merges, deletions and go-live. You organise and relay.

Project: <goal in one paragraph>. Non-goals: <list>. Done means: the QC seat has checked every acceptance criterion at one named commit.
Repo: <URL>. Base branch: <base>. Working branch: <new branch>. Agents may edit only <paths>. Never push to <protected branch>, never force-push, never put a secret in the repo.
Spend and time: <provider, free or cap>; I will be away <hours>; report as a one-line progress chain unless I ask for detail.
Owner-only gates (ask once, batched, with options and a recommendation): merge or go-live, access or credentials, spend, deleting data or files, changing the goal or scope. For anything else choose a documented default, keep working, and list it as an open owner question.

First check your real access and report it plainly: can you read the repo, can you push to the working branch? If not, name the exact step I must take. Do not claim anything works until you have seen it work.

Then, without waiting for me:
1. Create the shared coordination file on the working branch: line 1 is the turn marker; short protocol (pull before editing, append only, no force-push, one turn at a time); a memory section of at most 15 lines; a findings table; a messages section. Keep a short hot file and separate archive files.
2. Draft numbered acceptance criteria from my description in that file, for me to skim once.
3. Write one short prompt per other seat for me to paste into a new session: repo, branch, role limits, how to hand over, and "reply READY once you have verified your own access".
Then run the build, review, QC loop.
```

**Prerequisites that still need a human first:**

- Accounts: the repository host, any hosted database, the model provider, with billing set up where needed.
- The repository and base branch exist; the protected branch is actually protected.
- Each session is attached to the repository with the push rights its seat needs; temporary credentials are revoked at close.
- Secrets reach sessions out of band, never through chat or the repository.
- One session opened per seat; a session cannot start another. QC is a different seat from the Builder.
- A decision on where agent configuration lives (a private location, not the public project repository).
- Data classification: fictional or real, and who signs off if real.

**Gaps a prompt cannot close:**

- A prompt creates no access and no authority; it can only check for them and name what is missing.
- Wake-up between sessions was done by polling the repository, with time-limited background checks. A reliable standing route is missing.
- Long sessions cost more as context grows; fresh-session handoff worked but needs a human to open the session.
- Nothing here demonstrates a fully unattended run.

## 5. Limits of this evaluation

- Only this seat's view. The builder's and QC's experience, and any later session of this role, are **[U]**.
- No spend figures, no account details, and nothing about the period before this seat started.
- Recommendations are untested: they were not run as a fresh kickoff on another project.
