# Scripted-seat demonstration of the WP4 acceptance flow (offline, unattended)

Script: `wp4_flow_demonstration.py`. One batch through the real
`launcher launch` supervisor on the accepted pin a1c36ce (the
Reviewer-skip guard's code), in a disposable lane, with scripted mock
queue adapters. No provider, no model, no key, no manual input.

This is NOT a WP4 re-proof and earns no WP4 credit. Independent review
(judgment, same model family): every seat output is predetermined queued
text, so nothing was reviewed or judged; the Reviewer's verdict does not
name the pin it ruled on (only the QC verdict head is compared); and no
negative path ran (no FAIL, rework, refused DONE or stale verdict). What
it does show: the pipeline carries a queued PASS to a guarded close with
no manual recovery on the exact pinned code. WP4's real qualification -
Reviewer and QC judgment on the same application pin, unattended - stays
blocked on a model-backed route, which needs its own grounding and
authority.

Run 2026-11-05 (~21s wall): SUCCESS, all pre-registered flow checks
(flow checks, not acceptance criteria):
- R1 unattended close: supervisor done, status done, no turn holder.
- R2 seat order coordinator,builder,reviewer,qc,records,coordinator,
  turn_seq +1 per turn.
- R3 QC verdict row "verdict PASS at head <40-hex>"; src/ and tests/
  are byte-identical between the QC verdict head and the final HEAD.
  The Reviewer's pin is not checked - no Reviewer verdict names a head.
- R4 guarded close, not a bypass: zero review-required, error and
  restart rows; zero pending gates.
- R5 evidence files present (app, test, findings, QC verdict, archive,
  acceptance criteria); the final verify test passes when re-run.

Limits: scripted seats follow their queue. The flow and guard
mechanics are demonstrated; independent review explicitly rejected
treating this as WP4 credit or as evidence of review judgment, model
ability or autonomy. The lane is disposable; re-running the script
reproduces the same flow.
