# Progress tracking

Charts at the top of the main README come from `progress.json` and `render_progress.py`.

## How progress is measured

- The project is split into 10 work packages with fixed weights that add to 100%.
- This is weighted milestone progress, not independently verified completion. A package counts 100% only when its milestone is done: tests pass or an independent review passed. Commits alone do not count.
- A package that ran but has a known gap counts 50% (partial). In progress and not started count 0%.
- Credit is dated when the evidence was observed, so the curve does not claim earlier progress than the repo shows.
- Weights are a judgment call by the maintainers of this chart. They are not effort estimates.

## What the forecast is

No plan or schedule existed before 2026-11-04 14:40 EET, so there is no planned-versus-actual history and none is invented here. The dashed forecast is a baseline set on that date. Later updates keep it visible so slips show up honestly. It is a guess, not a commitment.

## Updating

Edit `progress.json` (status, `credit_at`, `forecast_end`, evidence), then run `python3 docs/progress/render_progress.py` (needs matplotlib) and commit the regenerated files. Do not mark a package done without linking the passing test run or review.

Owner: the maintainer of this repo's progress chart (currently the Telkomsel Instinct). Update on meaningful milestone changes, not per commit.
