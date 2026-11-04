# Chart style memory

This repo uses two diagram kinds with two distinct visual grammars. Do not mix them.
Owner decision 2026-11-04: the current-team chart exists to show, at a glance, WHO is on
the team, their ROLE, and the reporting/review links between them. Method explanation is
a separate artifact with its own style.

## 1. Method diagrams (README / explanation)

- Canonical sources: diagrams/formation-chart.py, diagrams/delivery-flow.py
- Grammar: warm cream page (#f4efec) with an inset white rounded card; palette ink
  #2b2523, grays #6a615c / #a39a93 / #8f857d, brown #6b5f59, teal accent #3f7a73;
  serif display title (Noto Serif), sans body (Noto Sans); robot()/human() line glyphs;
  section panels #faf6f3 with #e6d9d2 borders.
- Purpose: explain the METHOD (concept-led team formation, delivery flow). Adapter
  details, seat capacity and project history belong here, not in the team chart.

## 2. Current-team chart (who is in charge of what)

- Canonical source: diagrams/team-roster.py -> docs/team-roster.png
- Grammar: white background; one circular GitHub avatar per human seat (fetched from
  github.com/<login>.png, cached in diagrams/.avatars/, not committed); under each node
  a bold role name, an italic @handle, and one or two gray scope lines; thin curved gray
  arrows carry the hand-off labels; a small legend box sits top-left.
- The Builder seat is a model drawn as an icon node (purple "AI" circle); models never
  appear in a contributors graph.
- Owner decision 2026-11-04: label the Builder node @coolkowkank-bot - the shared
  machine account the Builder has access to and acts through - and keep the model name
  (Groq gpt-oss-120b) as a scope line. Never write "no GitHub account". The bot account
  is the Builder's GitHub identity, not a separate team seat; a short footer explains
  what the account does (authenticates model pushes, committer identity).
- Layout: owner on top; Coordinator, Builder and independent reviewer in one row with the
  Builder in the middle, so each hand-off is a short straight arrow pair that never crosses
  a label.
- Content rules: current occupants only - no unused seats, no adapter details, no
  historical contributors. README roles with no active occupant are NOT drawn as seats;
  a small "On demand" note states they exist and are activated per task (owner steer
  2026-11-04, Slack 1793790584.019179 + 1793790702.379659: README framework with
  task-scaled activation, no empty-seat clutter).
- Link rule (owner decision 2026-11-04, Slack 1793788269.210599): the review/verdict loop
  is directly between the Builder (@coolkowkank-bot) and the independent reviewer
  (@instinct-christina): review requests go Builder -> reviewer, verdicts go reviewer ->
  Builder. The Coordinator (@instinct-telkomsel) is NOT in that loop; it assigns scoped
  tasks to the Builder and checks the completed review loop. Never draw review arrows
  to or from the Coordinator, and never read independent review as a subordinate
  reporting line.
- Coordination link (owner steer 2026-11-04, Slack 1793790702.379659): the Coordinator
  manages BOTH delivery roles, so one shallow arc runs from the Coordinator side to the
  reviewer above the Builder, labeled "coordinates both roles (never carries review)".
  It is a coordination link, never a review arrow; the review loop stays untouched.
- Arrow check: after rendering, read each arrowhead on the actual image and confirm it
  matches its label.
- Available model pool (owner request 2026-11-04, Slack 1793788648.701489; refined
  1793790702.379659): qualified but inactive PROVIDERS sit in a separate dashed
  "Available model pool" band below the team row - never as active seats, and never
  labeled as a role ("Builder route" is wrong: providers are model sources, roles are
  seats). Each pool node states only verified facts (models, what was probe-verified,
  the date, and its current grounded status - e.g. zero-price verified / on hold with
  the reason) plus its assignment state. One dashed connector from the Coordinator to
  the band, labeled "Coordinator assigns scoped work": the Coordinator activates a pool
  model for a seat by assigning scoped work within verified free budgets and existing
  task authority - there is no separate owner approval gate per routine task. Never
  mark a pool model active until real assigned execution has run, and never infer seat
  suitability (e.g. Architect/QC) from provider or price labels alone.

## Update rules

- Change facts (occupants, proven capabilities, date) without changing the grammar.
- Keep the title date in sync with the facts shown.
- After every change: render and VISUALLY inspect the PNG for overflow, overlap and
  readability at chat size before committing.
- docs/developers.md embeds docs/team-roster.png; the README-method diagrams stay as
  they are unless the method itself changes.
