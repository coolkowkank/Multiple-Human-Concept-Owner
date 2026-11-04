# live/groq-dev-1 attempt log (operator record, secrets redacted)

Bounded test: one Groq builder turn (openai/gpt-oss-20b, free plan),
brief = add a --measure token-estimate flag to `launcher prompt`.

- attempts 1-2: empty content. Probe (labeled direct API call):
  finish_reason=length, 2041 reasoning tokens consumed the provider's
  2048 default completion cap, 0 content. Root cause: missing
  completion-token cap -> team-launcher a29f7c5 (HttpAdapter
  max_tokens config).
- attempt 3 (cap 8192): content truncated mid-JSON at ~5.2k chars;
  ~6.7k reasoning + content exceeded the cap.
- attempts 4-6 (caps 32768/16384/16384): generation completed and the
  seat applied the batch, but the operator's ~120s command window
  killed the seat before its commit/push step (no seat commit; remote
  head verified unchanged). Review of the applied batch: REJECTED -
  wholesale rewrite (426 deletions gutting cli.py/prompts.py), far
  outside the batch scope, not a useful minimal change.

Operator decision: narrow the brief to NEW files only (full-content
writes cannot drift existing code): launcher/token_est.py +
tests/test_token_est.py. --measure CLI wiring deferred to a reviewed
follow-up.
- attempt 7: generation complete but seat path guard rejected the
  batch (model wrote launcher/prompts.py, outside allowed paths).
  Guard worked as designed; brief amended with explicit allowed keys.
- attempt 8: provider HTTP 400 - gpt-oss-20b emitted a tool call
  (container.exec) though no tools are offered; model does not hold
  the JSON-only seat contract on this brief.
Operator decision: stay on the Groq free route but switch seat model
to llama-3.3-70b-versatile (same key/plan; non-reasoning, strong
JSON-contract adherence, no reasoning-token burn).
- attempt 9 (gpt-oss-120b): path guard rejected prompts.py write.
  prompts.py then allowed (both gpt-oss models independently targeted
  it; small file, full-content write is reviewable).
- attempt 10 (gpt-oss-120b): path guard rejected cli.py write. Brief
  still named cli.py/--measure as out-of-batch, which primed the
  models to write it; brief purged to a pure standalone-module task.
- attempt 11 (gpt-oss-120b): output truncated mid-JSON (reasoning
  burn at 16384 cap).
- RESOLUTION (controlled contribution path, 08:18 UTC+2): labeled
  direct API call to Groq openai/gpt-oss-120b, reasoning_effort=low,
  max_completion_tokens 7000 (8000 TPM free-tier cap observed live).
  finish=stop, 535 completion tokens (12 reasoning). Output reviewed
  on-spec, full suite 82/82 green, committed by operator as a14eb5f
  with provenance in the message and published to GitHub branch
  live/groq-dev-1. Not a runtime seat commit.
