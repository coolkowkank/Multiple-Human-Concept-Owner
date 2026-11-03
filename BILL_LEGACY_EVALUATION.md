# Bill legacy evaluation: what the human did at kickoff

*Author-side lessons from the original Bill session (design and readability, later quality control) on the Nordea × Aalto reference project, 31 Oct – 1 Nov 2026. Written 4 Nov 2026. This is not independent QC and does not resume the role.*

**Question:** what did the human actually do at the start that let the AI team work with rare routine supervision, and what is the least a human must do so the next project can start from one prompt?

**Short answer:** supervision dropped once three human-only things were in place:
- **Agreed boundaries:** which branch, which files, never `main`.
- **Real access:** repository rights and a session opened per seat.
- **Fast decisions:** concept calls made quickly in chat.

Most of the remaining human touches were not decisions. They were liveness ("check now"), relaying between sessions, and corrections to reporting format. Those are avoidable. Concept, scope, spend, credentials, merges and deletions should stay human. Unattended autonomy was **not** achieved: the human stayed the wake-up and relay layer throughout.

## Evidence labels and limits

| Label | Meaning |
|---|---|
| **[R]** | Repo-backed: the file and branch are cited |
| **[S]** | Original-session recollection (this Bill session only) |
| **[U]** | Unavailable: not observed by this session; not reconstructed |

- **What I read:** branches `Instict-prototype` and `ai-agent-communications` of `coolkowkank/Nordea-x-Aalto-Banking-`, and `main` of `coolkowkank/Multiple-Human-Concept-Owner`.
- **What I left out:** coordination transcripts and review logs are not cited (operational records), nor are assistant configurations or personal details.
- **Memory limit:** my recollection of the first hours (about 09:17–10:30 on 31 Oct) survives only in condensed form. Points from that period are marked [S] and kept general.
- **Other seats:** what the other seats' humans did in their own sessions is [U].

---

## 1. Human-only steps: what no prompt could have supplied

| # | Step | Why only a human | Label |
|:-:|---|---|:-:|
| 1.1 | **Chose the concept and its direction changes.** The project began as a README task. The human then said which branch was the final prototype, asked for the three-agent design (each agent opens only its own database, a shared context document, minimal supervision), and later decided that the context document is rebuilt *per customer session, not per question*, that all agents become LLM-driven, and that everything must be one system. | Concept ownership. The agents proposed options; only the owner could pick. | [S] |
| 1.2 | **Set the boundaries of autonomy.** One working branch; editable files limited to named ones; never push to `main`; act only on your turn. Later, explicit permission for new files (an evaluation section, a README rewrite) and an explicit "don't start yet" before a new version. | Scope and authority. The AI can draft rules but cannot grant itself permission. | [S] |
| 1.3 | **Provided repository access and identities.** Attached the repository with push rights to each AI session, and gave the builder seat its own GitHub collaborator account. | Account and access setup happens outside any chat. A prompt grants nothing (stated in `README.md`, *Quick start*, `Multiple-Human-Concept-Owner` `main`). | [S], [R] |
| 1.4 | **Opened and introduced the seats.** Started a separate session for each agent, told each one where to meet, and relayed the first introductions ("everyone is in now"). | One chat session cannot start or message another. | [S], [R] (`README.md`, *Quick start*, `Multiple-Human-Concept-Owner`) |
| 1.5 | **Credentials and spend.** AI keys (Aalto LLM over VPN, or Groq), and hosted storage secrets (Supabase). The hosted, separately-credentialed target was explicitly left needing "live infrastructure and separate approval". | Money, accounts and secrets. Keys must never be pasted into chat. | [R] `LAPTOP.md` §"What you need", "Keep the key secret" (`ai-agent-communications`); `README.md` §"The three-database architecture" (`Instict-prototype`) |
| 1.6 | **Chose storage hosting and the external-agent timing.** Three tables in one Supabase project; external personal agent deferred to a later branch. | Infrastructure and product scope. | [S] |
| 1.7 | **Handled an identity anomaly.** A commit signed with this seat's name, not made by this session, appeared on a short-lived branch. The human deleted that branch. | Only the owner can judge and clean up unexplained activity. | [S] |
| 1.8 | **Cleared closed work.** Deleted exported agent material from the project repository and kept merges into `main` as their own call. | Irreversible and repository-wide. | [S] |

## 2. Steps the human did that the AI team could have done

Given an agreed brief and delegations, all of these were within the team's reach.

| # | Step | How the team could own it | Label |
|:-:|---|---|:-:|
| 2.1 | **Writing the coordination rules** (turn line, message format, who edits what). The first rules came from the human; agents later refined them well (compact message format, hot and cold files, archiving). | Ask for boundaries only (1.2); let the coordinator seat draft the protocol for one approval. | [S] |
| 2.2 | **Pointing at the canonical repository and the relevant branches.** | Branch discovery is readable. Give the repository URL once and let the team map the branches and report back. | [S] |
| 2.3 | **Relaying messages between seats** ("tell Jeff about the new agent", "tell Instinct to pull"). Relayed owner instructions were also hard to verify, so agents waited for direct confirmation. | Have the owner write instructions once into the shared file, or broadcast them to every seat at once. | [R] `evaluation.md` §[Bill], "On the collaboration process" (`ai-agent-communications`); [S] |
| 2.4 | **Liveness prompts** ("check now", "any update?", "are you still monitoring?"). The background check already existed; the prompts often found nothing new, or work handed over well before its stated ETA. | Commit messages already carried the turn and state. The owner later switched to watching the commit history, which removed most pings. | [S] |
| 2.5 | **Correcting how agents report** (shorter, then just "whose turn it is"). | Put the reporting contract in the kickoff. | [S] |
| 2.6 | **Turning a design conversation into a plan** (the session-vs-question and change-driven rounds discussion). | The team can draft the plan and present only the decisions; the human revises once. This worked when the AI drafted and the human approved. | [S] |

## 3. Routine interventions: avoidable vs. required gates

**Avoidable (aim to remove):**
- **Wake-up and status pings** (2.4) and **relays** (2.3). Root cause: sessions cannot wake each other, so a human or a polling loop has to. [S]
- **Format and length corrections** (2.5). [S]
- **Reconciling concurrent edits.** Out-of-turn posts and stale copies caused overwrites that had to be restored. A turn token plus append-only edits worked whenever it was respected. [R] `evaluation.md` §[Bill], items 3 and "On the collaboration process" (`ai-agent-communications`); [S]
- **"Is it done?"** Done was clear only once acceptance criteria existed. Before that, each milestone needed a fresh human call. [S]

**Required gates (keep human):**
- **Concept and scope changes** (1.1). [S]
- **New permissions:** new files, new branches, new seats (1.2, 1.4). [S]
- **Credentials, accounts and spend** (1.3, 1.5). [R] `LAPTOP.md` (`ai-agent-communications`); `README.md` (`Instict-prototype`)
- **Merges to protected branches, deletions, publishing:** never done without the owner. [S]
- **Anomalies** affecting identity or access (1.7). [S]
- **Plan approval before a large build** ("don't start yet" → "start now"). One approval covered many batches, which is what kept supervision rare. [S]

## 4. Proposed minimal reusable kickoff

*A recommendation only. Implementing or changing the blueprint's templates is not authorised by this evaluation.*

### Inputs the human prepares before the prompt (human-only)

1. **Concept in a few lines:** what and why, non-goals, and how "done" is judged.
2. **Seats and people:** which seats exist, who owns each, and an independent reviewer who is not the builder.
3. **Access, done outside chat:**
   - repository URL with write rights only for writing seats;
   - one session opened per seat;
   - one commit identity per seat;
   - keys and secrets stored in the environment, never pasted into chat.
4. **Boundaries:** working-branch rule, protected branches, which files each seat may write.
5. **Gates list:** concept or scope change, spend, credentials, merges or deletions, external contact, new seats.
6. **Reporting contract:** one-line status unless asked, and where to watch progress (commit history, or a chat channel at milestones only).

### One opening prompt (draft, given to the coordinator seat)

```
Project: <one-paragraph concept, non-goals, definition of done>.
Repository: <URL>. Work only on branches you create from <base>; never write to <protected branches>.
Seats: <seat - owner - session>, QC = <seat> (never the builder). I have opened each session and granted the access listed; verify yours before relying on it.
Gates - ask me, batched, with options and a recommendation: concept or scope change, spend, credentials, merge/delete, external contact, new seats or permissions.
Everything else inside this brief is delegated: draft the protocol, criteria and plan, show me the plan once, then run batches without asking.
Coordinate through one shared file with a turn token; put whose turn it is in every commit message.
Report to me only as "Status: <whose turn>" unless I ask. Stop and report on any conflict, identity anomaly or blocked access instead of forcing.
```

This fits the existing `templates/coordinator-starter-prompt.md` and `docs/delegation.md` on `main`. The new elements are a single gates list, the reporting contract, and the turn-in-commit-message rule. [R], with the proposal [S]-based.

### Prerequisites and gaps that still need a human first

- **Opening sessions and relaying first contact:** no prompt can start other seats. [R] `README.md` *Quick start* (`Multiple-Human-Concept-Owner`)
- **Wake-up between seats:** unsolved in the reference project. Seats either poll or wait for a human. A shared wake signal (an event or notification between sessions) is needed before supervision can be truly rare. [S]
- **Per-seat identity verification:** without it, a commit's signature isn't proof of its author (1.7). [S]
- **Hosted infrastructure and secrets** for production-like testing. [R] `README.md` (`Instict-prototype`)
- **How the other seats were set up** by their humans, and any budget decisions: unavailable to this session. [U]

## Caveats

- **One project, one seat's view:** the recollection is from this Bill session only, and its earliest part survives in condensed form.
- **Rare, not absent:** routine supervision became rarer over time but never stopped. The human was still needed to wake, relay and approve.
- **Untested here:** the proposed kickoff has not been run on a new project. It belongs in "proposed (untested)" until a fresh team has tried it.
