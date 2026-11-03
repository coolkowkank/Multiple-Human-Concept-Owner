# Decision record

> One record per owner decision, written at decision time - not after the work,
> on request. The Coordinator writes the entry when it relays the decision.
> QC treats a gated item with no entry as a blocker; a gated item with an entry
> needs no new human ask.
>
> Privacy: this repository may be public. Quote the owner's exact words only
> when they were already public or the owner agreed to publication; otherwise
> keep the exact words on the owner's own channel and say so here. The same
> rule applies to locators: record the platform and timestamp by default, and
> include a permalink or message reference only when the channel is already
> public or the owner agreed - a link into a private channel is itself a
> disclosure. This record is evidence, not a grant: the owner's own channel
> settles any dispute (docs/delegation.md section 1).

| Field | Value |
| --- | --- |
| ID | DR-<sequence number> |
| Date | <YYYY-MM-DD HH:MM, one named timezone> |
| Owner | <which owner decided> |
| Decision | <what was decided, one or two lines> |
| Owner words | <verbatim quote, or "on owner's channel: <channel reference>"> |
| Channel + timestamp | <platform and message time> |
| Locator | <permalink or message reference - only if the channel is public or the owner agreed; otherwise "on owner's channel"> |
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
