# Requesty route compatibility notes (read-only docs, 2026-11-04)

No API probe was made. Sources: docs.requesty.ai/features/reasoning,
/features/structured-outputs, /api-reference/endpoint/chat-completions-create,
and the live /v1/models listing fetched 19:54 EET.

- Reasoning effort: "none" and "min" are documented as synonyms that either
  disable or minimise reasoning "for reasoning models". For models Requesty has
  no supported-effort list for, "none" and "min" are SENT AS "low". Whether
  novita/ling-3.1-flash has such a list is unknown, so "none" may have been
  forwarded as "low". The listing shows supports_reasoning true for it.
- Structured output: docs say json_object works on "all models" while
  json_schema depends on the listing flag. The listing says
  supports_output_json_object false and supports_output_json_schema false for
  both novita/ling-3.1-flash and nvidia/nemotron-3-ultra-550b-a55b. The docs
  and the listing disagree on json_object; this is unresolved without a call,
  so response_format is not used.
- Observed (this project): a 1536-token Verifier reply with effort low was empty
  at finish_reason length (reasoning present); the retry with effort none
  returned 4763 bytes of working-out text at the 1536 ceiling, not JSON. The
  reasoning_tokens split was not returned for the retry. Cause not established.
- Prompt-side change made offline (format only, no verdict hints): the
  Verifier prompt now states that the entire reply is the JSON object, first
  character "{", no analysis or fence, one verdict per id, evidence under 25
  words. Not tested live. Replies are never repaired or scraped into verdicts.
- Other free-listed, reasoning-flagged candidates from labs other than nvidia
  (all UNTESTED, none in the route record): novita/ling-3.1-flash (tried),
  google/gemma-4-31b-it (cooldown, 8192 output), mistral/leanstral-1-5 (name
  suggests a specialised model; fit unknown), nvidia/muse-glimmer-30b (lab
  listed as meta, 20480 output). Task fit is judgment, not measured.
