# Roster

> One row per seat. Rules bind to roles, never to assistant names
> (docs/delegation.md §5). A seat change takes effect only through an
> owner-recorded decision; the seat gaining authority never writes it.

| Seat | Role | Human owner | Assistant / adapter | Commit identity | Verified endpoint | Last verified |
| --- | --- | --- | --- | --- | --- | --- |
| Coordinator | coordinator | `<owner>` | `<assistant>` | `<git identity>` | `<evidence, e.g. observed write commit>` | `<date>` |
| Builder | builder (sole writer) | `<owner>` | `<assistant>` | `<git identity>` | | |
| Reviewer | reviewer | `<owner>` | `<assistant>` | | | |
| Records | records | `<owner>` | `<assistant>` | | | |
| Architect | architect | `<owner>` | `<assistant>` | | | |
| Independent QC | qc (never the Builder) | `<owner>` | `<assistant>` | | | |

- Verified endpoint means an action was observed through it (readiness
  reply plus a real read or write), not that it was declared.
- The runtime's `.team/roster.json` is generated from this table;
  `docs/evidence-interface.md` §5 defines which fields are claims
  versus verified evidence.

## Seat-change checklist

1. Owner records the change as a decision record.
2. Update this roster and every document naming the seat.
3. Notify all seats through the bus.
4. Record a written pickup by the incoming seat.
5. Mark the old seat's open handoffs historical.
