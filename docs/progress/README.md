# Progress tracking

Charts at the top of the main README come from `progress.json` and `render_progress.py`.

## How progress is measured

- The project is split into 10 work packages with fixed weights that add to 100%.
- This is weighted milestone progress, not independently verified completion. A package counts 100% only when its milestone is done: tests pass or an independent review passed. Commits alone do not count.
- A package that ran but has a known gap counts 50% (partial). In progress and not started count 0%.
- Credit is dated when the evidence was observed, so the curve does not claim earlier progress than the repo shows.
- Weights are a judgment call by the maintainers of this chart. They are not effort estimates.

## WP5 and WP7 criteria

WP7 criterion: the rule frozen at 14:40 on 2026-11-04 applies unchanged. A package is verified only with passing tests or an independent review that passed. A delivered changes-required review is not a pass, so WP7 earns no credit until a review accepts the corrected fix. (An earlier update on 15:05 counted WP7 under a looser reading. That was reversed in the following update, because criteria are not changed after the outcome is seen.)

## Research package criteria

The Researcher role's deliverable is sourced literature insight, so WP8a does not require product adoption.
- WP8a done: a published note whose citations resolve, whose key numbers match the sources, and which labels evidence class, limits and a proposed experiment. Partial while only some claims have been checked against sources.
- WP8b done: a finding tested in an experiment on this prototype with results recorded. Adopting it is a separate decision.

## What the forecast is

No plan or schedule existed before 2026-11-04 14:40 EET, so there is no planned-versus-actual history and none is invented here. The dashed forecast is a baseline set on that date. Later updates keep it visible so slips show up honestly. It is a guess, not a commitment.

## Baseline and as-of time

`baseline` in progress.json is frozen at 2026-11-04 14:40 EET and must never be edited. `as_of` is the time of the latest update. The current forecast (`forecast_end`) can move; the red diamonds on the Gantt chart and the pink S-curve line keep the original dates visible.

## Owners (PIC)

Team chart levels: owner on top, Coordinator one level below, all other roles one level below the Coordinator. The Builder and reviewer feedback loop is drawn as workflow arrows, separate from the levels.

Eva - Evidence verifier is a planned role for checking Nora's sources (existence, metadata, and whether the cited passage supports the claim, with uncertainty) before publication. Model: Gemma 4 31B on the Requesty free route, trial-tested on 2 calls at zero reported cost with 7 of 7 fixture verdicts correct (executor report; role doc at team-launcher 06479b3). It is a manual review workflow only. Runtime roster wiring and a mechanical gate are not implemented, so it is not automated or fully operational. It has no GitHub account or token, and the document and trial alone earn no milestone credit. The Coordinator keeps responsibility for accepting reviewed work.

Provider pool (kept short on the chart): Groq serves the Builder (Alex, gpt-oss-120b via the shared bot account). Requesty serves Nora (Nemotron-3 Ultra 550B) and Eva (Gemma 4 31B). The small provider badges on the chart are stylized letter marks, not official logos. Telkomsel and Bill show "not project-configured" because no project provider is assigned to those seats. Cerebras is on hold, with the key and tool calls checked and the credit ledger unverified. Requesty's free route is in use for the Nora and Eva trials only. Requesty also ran one bounded Builder run that needed manual recovery and skipped the Reviewer, so it is not autonomy. Providers are not team seats.

Project aliases: Telkomsel (Coordinator), Alex (Builder), Nora (Researcher), Bill (Independent reviewer, Christina's existing project name). They are display names only; account, model and status facts are unchanged.

The large icon is the accountable current owner by role assignment, not by who authored commits. Small icons are contributors. The shared bot account is not a unique model identity, and the Researcher uses a role icon instead of an avatar. Since 15:10 it publishes through the owner's research token, which the owner has also allowed Eva to use (grant at 15:38) with the Researcher role as commit author and the owner as committer. That is a publishing route, not a new GitHub account, and earns no product credit. Model for Nora: Nemotron-3 Ultra 550B on the Requesty free route, for verified-source synthesis with citations reviewed. A 3-request trial returned zero reported cost with good reasoning and format, but some citations were wrong or unverified, so it is not trusted for finding references on its own. This earns no research-quality pass and no extra milestone credit.

## Publishing the images

GitHub caches branch-path image URLs (query strings are ignored), so the main README links the charts pinned to a commit. After regenerating: commit and push the charts, then set the two image URLs in the main README to `https://github.com/coolkowkank/Multiple-Human-Concept-Owner/raw/<that commit sha>/docs/progress/<chart>.png`, and push again.

## R&D states (not part of the score)

Research work packages are tracked separately from delivered product progress. States: S0 scoped, S1 sources read, S2 finding published, S3 experiment designed, S4 experiment run, S5 reviewed with an adopt or reject decision. As reported at 14:52 EET: RW1 handoffs S2, RW2 independent review gates S2, RW3 token efficiency S1, RW4 stall and liveness S0, RW5 prior art S0 to S1, RW6 rate-limit-aware routing S0. No experiment has run. A state is not a completion percentage, and a finding is not an adopted feature.

## Commit identity

Coordination work (this progress page, planning, team display) is committed by instinct-telkomsel. Research and implementation work is committed under coolkowkank-bot, with the actual role and model named in the commit. Past history is unchanged.

## Project Team chart

`team_chart.py` draws docs/progress/team.png (called by render_progress.py). Its facts come from docs/developers.md and the team roster chart on the team-launcher branch. Edit the labels there when the team changes, and pin all three images to the commit as described above.

## Updating

Edit `progress.json` (status, `credit_at`, `forecast_end`, evidence), then run `python3 docs/progress/render_progress.py` (needs matplotlib) and commit the regenerated files. Do not mark a package done without linking the passing test run or review.

Owner: the maintainer of this repo's progress chart (currently the Telkomsel Instinct). Update on meaningful milestone changes, not per commit.
