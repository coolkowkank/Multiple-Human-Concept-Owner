# Builder task: Reviewer-skip acceptance guard (v1)

Branch: live/reviewer-skip-guard (base d96e09d, team-launcher tip).
You own: launcher/runtime.py + new tests in tests/. Stdlib only.

## Observed defect (evidence, verified 2026-11-04)
In launcher/runtime.py, the seat-turn handler accepts completion
unconditionally:

    if response.get("status_line", "").startswith("DONE"):
        state["status"] = "done"
        state["turn"] = None

No independent verdict is required. Any seat can declare DONE and the team
is marked done - the failure mode we hit in production: a run reached
"accepted" with the independent reviewer never asked.

Related facts (verified):
- launcher/conformance.py VALID_KINDS already includes "verdict".
- launcher/demo.py's mock QC writes review/qc-verdict-1.md and a verdict
  summary "verdict PASS on evidence at head"; the demo check only looks for
  the file.
- launcher/prompts.py QC role: "Your verdict gates milestones".
- Every seat response is logged via self.bus.append_log(self.name,
  "handoff", body, turn_seq=seq) - verdicts are not recorded as a
  verdict-kind log entry today.

## Required behavior
1. A DONE claim is accepted only when the bus holds a QC verdict for the
   CURRENT pinned head: a verdict-kind log entry (or verdict artifact
   recorded in the log) from the roster's QC seat whose body references the
   current repo HEAD sha, with a PASS outcome.
2. DONE without that verdict: do NOT set status done. Route the turn to the
   QC seat (turn = QC seat) and append a "review-required" log entry naming
   the would-be DONE seat and head.
3. If the roster has no QC seat: open a human gate ("no QC seat to review
   DONE claim") instead of accepting or routing.
4. A verdict naming a STALE head (not the current HEAD) does not satisfy 1.
5. Everything else about DONE handling (status_line, turn clearing after a
   valid verdict) stays as it is.

## Tests to add (tests/, follow existing style)
- DONE with no verdict anywhere -> not done, turn routed to QC,
  review-required logged.
- DONE with a QC PASS verdict at current HEAD -> done accepted.
- DONE with a QC PASS verdict at a stale/other sha -> not accepted.
- DONE with no QC seat in roster -> human gate opened, not done.
- Non-DONE responses are unaffected (regression).
Run the full suite; all tests must pass. Commit with your honest model
attribution and a 'TURN: builder' line. Commit message: say exactly what
changed. Push when ready (a push gate applies; if push is refused as gated,
retry in a later round - the operator opens it after the suite passes).
