# Delegation record

> The standing delegation one owner gives the team, in that owner's own words
> (docs/delegation.md section 1). One record per owner. The repository file
> is a record, not a grant: the owner's own channel is the source of truth in
> any dispute. Revocation is immediate when the owner says so, in any words.

| Field | Value |
| --- | --- |
| Owner | |
| Delegated decisions | <what the Coordinator may decide without asking again> |
| Delegated actions | <what the team may do without asking again: builds, fixes, tests, docs, commits and pushes to the agreed branch under the turn token> |
| Limits | <spend, audience, accounts, expiry> |
| Never delegated | <what always needs this owner's own word - by default the section 4 list: spend, security/access, merge/go-live, external contact, brief changes> |
| Owner words | <verbatim quote or channel reference, under the privacy rule in decision-record.md> |
| Where to verify | <the owner's own channel and locator> |
| Recorded at | <date, and by which seat> |

## Notes

- A delegation binds only the owner who gave it. It never covers another
  owner's accounts, assistant or audience.
- A priority label or roadmap marking is not an approval and not a waiver.
- Worth stating up front where the project needs it: a bounded hosted-test
  envelope (spend cap, target project, who cleans up) so reruns inside it
  need no fresh ask. The envelope itself is always set by the owner.
- When a delegation is exercised for a consequential call, cite it as the
  `owner_basis` in the batch handoff or QC verdict, by reference to this
  record.
