# WP4 re-proof run (scripted seats, offline, unattended)

Script: `wp4_reproof.py`. One batch through the real `launcher launch`
supervisor on the accepted pin a1c36ce (the Reviewer-skip guard's code),
in a disposable lane, with scripted mock queue adapters. No provider, no
model, no key, no manual input. This proves the acceptance FLOW -
builder change, Reviewer review, QC verdict, guarded close with no
manual recovery - on the exact pinned code. It does not prove any
model's ability, and it is not an autonomy or WP10 claim.

Run 2026-11-05 (~21s wall): SUCCESS, all pre-registered checks:
- R1 unattended close: supervisor done, status done, no turn holder.
- R2 seat order coordinator,builder,reviewer,qc,records,coordinator,
  turn_seq +1 per turn.
- R3 QC verdict row "verdict PASS at head dc98bd07..."; src/ and tests/
  are byte-identical between the verdict head and the final HEAD, so
  Reviewer and QC ruled on the same application pin.
- R4 guarded close, not a bypass: zero review-required, error and
  restart rows; zero pending gates.
- R5 evidence files present (app, test, findings, QC verdict, archive,
  acceptance criteria); the final verify test passes when re-run.

Limits: scripted seats follow their queue; the WP4 record's "fresh
proof must include Reviewer and QC on the same application pin,
unattended" is met for the flow and guard mechanics only. Model-backed
seats are a separate, provider-blocked step. The lane is disposable;
re-running the script reproduces the evidence.
