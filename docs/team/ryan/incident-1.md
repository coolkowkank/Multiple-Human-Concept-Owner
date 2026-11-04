# Incident 1: first live attempt, allocation request (2026-11-04)

Status: PAUSED. No assignments. Nothing running. Not a completed cycle.

Facts (observed by the operator driver; ledger.jsonl has the lines):
- 19:40 EET listing GET: exact ids nvidia/nemotron-3-ultra-550b-a55b (lab
  nvidia) and novita/ling-3.1-flash (lab inclusionai) showed numeric 0 for
  input, output and cached price; model_lab present.
- A first driver run was refused before any request (listing time stamped
  just after the clock reading looked future-dated). 0 requests.
- 19:41 EET: one allocation request to nvidia/nemotron-3-ultra-550b-a55b.
  Ledger: reserved, result outcome=unknown, halt. Wall time about 23 s by the
  driver; ledger timestamps all show the call start (17:41:11Z) because the
  runner stamps one clock reading per step. No usage or cost fields returned.
- The runner at that commit did not keep the error class, stage or any body
  excerpt, so the cause is not recoverable and is not inferred.
- The reserve counts as consumed (1 of 24). "Unknown" is not "billed" and is
  not proof of no charge.
- No retry, probe, Gemma call or schedule followed. Resuming needs grounded
  external clearance and an explicit go; a price-0 listing does not clear it.

Follow-up (offline): the transport now classifies timeout, network, HTTP,
malformed (stage, error class, status, content type, redacted bounded
excerpt) and writes only allowlisted fields to the ledger. See
tests/test_ryan_cycle.py class Diag.
