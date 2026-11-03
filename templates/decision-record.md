# Decision record

> One record per owner decision, written at decision time - not after the work,
> on request. The Coordinator writes the entry when it relays the decision.
> QC treats a gated item with no entry as a blocker; a gated item with an entry
> needs no new human ask.
>
> Privacy: this repository may be public. Quote the owner's exact words only
> when they were already public or the owner agreed to publication. Otherwise
> record the reference (channel, timestamp, locator) and a plain summary, and
> keep the exact words on the owner's own channel. This record is evidence,
> not a grant: the owner's own channel settles any dispute
> (docs/delegation.md section 1).

| Field | Value |
| --- | --- |
| ID | DR-<number> |
| Date | <YYYY-MM-DD HH:MM, one named timezone> |
| Owner | <which owner decided> |
| Decision | <what was decided, one or two lines> |
| Owner words | <verbatim quote, or "on owner's channel: <reference>"> |
| Channel + timestamp + locator | <platform, message time, permalink or message reference> |
| Covers | <the scope this decision covers> |
| Limits | <spend, audience, accounts, expiry> |
| Recorded by | <seat that wrote the record> |

## Rules

- Anything listed in docs/delegation.md section 4 - spending, security and
  access changes, merge or go-live, contacting third parties, changing the
  agreed brief - needs a decision record before the team acts, unless a
  standing delegation record already covers the case within its stated
  limits.
- A seat change takes effect only through an owner decision record. The seat
  that gains authority never writes that record, and other seats ignore the
  change until the record exists.
- One owner's yes never covers a shared commitment; who must agree is what
  the brief and the delegation records say.
- Batch handoffs and QC verdicts reference these records as `owner_basis`
  (docs/evidence-interface.md section 3).
