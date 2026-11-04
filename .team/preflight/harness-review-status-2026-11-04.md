# Executor hardening review status - 2026-11-04

Public project summary of the two independent offline reviews of the
model-executor hardening branches. No live calls, rollout or provider
spend happened in any review; all probes were offline against local
fixtures. Pins are exact git objects; branches may move.

| Revision | Pin | Verdict |
| --- | --- | --- |
| v1 (bounded recovery + push-retry) | 321257b696389d1e72a804cb92bed894275cc6ba | accepted as offline support evidence (not autonomy, not guard implementation) |
| v2 (placeholder filter + schema recovery) | 77ed57a8cc679900472943d2d36b1693e0b4226e | REJECTED for rollout: literal filter bypassed and false-positived; classifier too broad; feedback truncated; write_file could truncate existing files |
| v3 (bounded remediation) | 4a95bf557b399fd2be0296cd308bb142e5224cdd | PARTIAL, No-GO preserved: classifier/feedback/overwrite improvements verified; content-free guard still bypassable ('...', ordinary comments, 'raise -> pass'); deletion flag global+lexical; ledger durability gaps (empty-after-crash, negative used); transport-confirmation semantics limited |

Standing truths after both reviews:
- No universal destructive-edit or semantic-correctness protection is
  claimed by any harness revision. The real boundary remains: operator
  test suite + whole-tree push gate + operator acceptance.
- Budget accounting: reservations are the durable conservative cap;
  "confirmed sends" prove only local transport completion, never
  provider receipt or billing.
- The reviewer-skip guard stays UNBUILT (batches 5 and 7 closed,
  reservations frozen). No batch runs on v2/v3.
- Next step is a structural design (staged diff + operator acceptance,
  atomic ledger, exact reservation IDs), not another filter iteration.
