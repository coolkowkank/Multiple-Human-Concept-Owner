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
- Content rules: current occupants only - no unused seats, no adapter details, no
  historical contributors. The independent reviewer is drawn as a PEER exchange with the
  Coordinator (review requests one way, verdicts the other), never as a subordinate
  reporting line.

## Update rules

- Change facts (occupants, proven capabilities, date) without changing the grammar.
- Keep the title date in sync with the facts shown.
- After every change: render and VISUALLY inspect the PNG for overflow, overlap and
  readability at chat size before committing.
- docs/developers.md embeds docs/team-roster.png; the README-method diagrams stay as
  they are unless the method itself changes.
