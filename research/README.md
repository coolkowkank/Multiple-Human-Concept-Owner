# Research_lab - Researcher role workspace

Branch: `Research_lab` (based on team-launcher @ 93b3552).
Role: scientific-literature research for prototype optimization insights.

## Ownership
- The Researcher owns everything under `research/` on this branch.
- No product code writes (launcher/, tools/, tests/, docs/ tasks stay with
  Builder/coordinator). Research findings are proposals, not changes.

## Artifact format
One Markdown file per finding in `research/findings/YYYY-MM-DD-short-title.md`:
- Claim and evidence class (peer-reviewed / preprint / hypothesis)
- Source citations (title, venue, year, link)
- Applicability to this prototype and a concrete proposed experiment
- Explicit limitation: a paper does not prove our implementation works

## Reporting route
New insights are reported to the coordinator automatically (via the project
coordinator channel). Insights become prototype work only after coordinator
assessment, testing and review - never by direct edit from this branch.
