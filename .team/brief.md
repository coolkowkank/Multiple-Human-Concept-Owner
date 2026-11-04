# Brief: live/groq-dev-3 - one Groq-authored doc turn

Scope (exact): the seat `builder` (Groq openai/gpt-oss-120b, free plan)
writes EXACTLY ONE file: `docs/response-contract.md` - a concise
reference for AI assistants working this repo. No other file may be
written. One turn, one shot; the launcher records the outcome either
way.

Content the doc must cover (the seat response contract, as implemented
in launcher/adapters.py parse_response and launcher/runtime.py):
- The reply is EXACTLY ONE JSON object with keys: summary, writes
  (path -> content map), verify_command (string or null), handoff
  (null or {to, note}), status_line.
- The whole reply is that object: bare JSON, or inside exactly one
  ```json fence with only whitespace around it. Any prose outside the
  object, multiple fences, or multiple objects is rejected.
- Writes may only touch the seat's allowed_paths.
- Recovery: one format-correction round (re-ask with strict
  revalidation) and one path-guard correction round; a global budget
  of 3 adapter calls per turn, then the turn fails honestly.
- Tone: concise, factual, for AI assistants; no marketing.

Labels: this is a bounded live test of the launcher-managed commit
path (user direction 2026-11-04: Groq commits its own output, then
review). It is NOT proof of autonomous operation.
