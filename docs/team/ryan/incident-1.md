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
malformed (stage, error class, status, content type, body length and a coarse
body kind; no response text) and writes only allowlisted fields to the ledger. See
tests/test_ryan_cycle.py class Diag.

## Follow-up 2026-11-04 20:09 EET

Operator-controlled single diagnostic (reviewed transport: max_tokens 2048,
reasoning_effort low). Result: ok, cost 0, 1 request, 1207/1423/2630 tokens.
This does not identify the cause of the first unknown outcome and is not an
external provider recovery signal. Requests consumed in total: 2 of the first
qualification envelope of 6 (4 remain); no other call is authorised.

## Follow-up 2026-11-04 20:11 EET (Verifier diagnostic)

Operator-controlled single Verifier attempt, novita/ling-3.1-flash,
max_tokens 1536, reasoning_effort low, prompt 1754 tokens. Result: HTTP 200,
EMPTY content, finish_reason length, completion_tokens 1536 (the whole ceiling),
reasoning present, cost 0, 12.9 s. Recorded as an unknown/response-shape
(empty-content) outcome and the run halted by design. No verdicts exist. The
route is NOT qualified for this job at these settings; the reason beyond
'ceiling reached with empty content' is not established. Requests consumed in
total: 3 of the first qualification envelope of 6 (3 remain). No retry,
review or schedule ran.

## Follow-up 2026-11-04 20:23 EET (Verifier retry, one attempt)

Operator-controlled single retry on queue item research-model-vs-harness-v2
(same 6-finding draft, packet v2 with Appendix F text), novita/ling-3.1-flash,
max_tokens 1536, reasoning_effort none. Result: HTTP 200, cost 0, prompt 1915
/ completion 1536 (the whole ceiling) / total 3451, 13.6 s, content 4763 bytes.
The content is free-form working-out text and NOT the required JSON, so the
mechanical format pre-check failed (no verdict JSON exists). The raw text is
not published here (it reads as unstructured reasoning). It is unverified model
output, not a verifier verdict. Run halted again. Requests consumed: 4 of the
lifetime envelope of 6 (2 remain); the Verifier role cap of 2 is reached.
