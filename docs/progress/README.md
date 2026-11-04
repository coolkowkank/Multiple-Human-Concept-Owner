# Progress tracking

Charts at the top of the main README come from `progress.json` and `render_progress.py`.

## How progress is measured

- The project is split into 10 work packages with fixed weights that add to 100%.
- This is weighted milestone progress, not independently verified completion. A package counts 100% only when its milestone is done: tests pass or an independent review passed. Commits alone do not count.
- A package that ran but has a known gap counts 50% (partial). In progress and not started count 0%.
- Credit is dated when the evidence was observed, so the curve does not claim earlier progress than the repo shows.
- Weights are a judgment call by the maintainers of this chart. They are not effort estimates.

## Research package criteria

The Researcher role's deliverable is sourced literature insight, so WP8a does not require product adoption.
- WP8a done: a published note whose citations resolve, whose key numbers match the sources, and which labels evidence class, limits and a proposed experiment. Partial while only some claims have been checked against sources.
- WP8b done: a finding tested in an experiment on this prototype with results recorded. Adopting it is a separate decision.

## What the forecast is

No plan or schedule existed before 2026-11-04 14:40 EET, so there is no planned-versus-actual history and none is invented here. The dashed forecast is a baseline set on that date. Later updates keep it visible so slips show up honestly. It is a guess, not a commitment.

## Baseline and as-of time

`baseline` in progress.json is frozen at 2026-11-04 14:40 EET and must never be edited. `as_of` is the time of the latest update. The current forecast (`forecast_end`) can move; the red diamonds on the Gantt chart and the pink S-curve line keep the original dates visible.

## Owners (PIC)

The large icon is the accountable current owner by role assignment, not by who authored commits. Small icons are contributors. The shared bot account is not a unique model identity, and the Researcher has no GitHub account, so it uses a role icon.

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
