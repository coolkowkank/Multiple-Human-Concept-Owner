# Brief: rehearsal/live-1 - one genuinely-reasoned review turn

Base: 4f71227eca4a71d2a69b54945ad822dfbc91daeb (team-launcher).

Scope (agreed by both sides, exact):
- ONE reviewer turn by the peer operator (Christina's side): review the
  4f71227 diff (queue adapter, prompt/respond commands, per-clone
  session ids, supervisor exclusion, docs claims) for correctness and
  honest claims. Findings to exactly review/live-1-findings.md,
  structurally conformant to templates/review-findings.md BEFORE
  queueing. The peer queues and runs her own actual `seat reviewer
  --once` on her own clone; nobody queues on her behalf.
- ONE QC turn by an independent reasoner (separate task agent, not the
  coordinator/builder reasoner): independent verdict to exactly
  review/live-1-qc.md.
- Coordinator (our side): assigns the batch, closes the cycle. No
  application-code writes by any seat.

Window: 60 minutes from joint verified prompt delivery; a stall is
recorded as the outcome and the cycle closes.

Labels for all evidence: assistant-mediated glue on both sides; two
same-kind Instincts; NOT heterogeneous platforms, NOT autonomous or
unattended operation; the earlier local fizzbuzz cycle used one
reasoner for all seats and is not independent-review evidence.

Frozen branches rehearsal/i2i-1 and rehearsal/i2i-2 are untouched.
