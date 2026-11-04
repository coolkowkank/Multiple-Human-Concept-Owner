# Evidence: first live-model seat turn (Groq free plan)

Date: 2026-11-04. Model: `openai/gpt-oss-20b` via Groq
(`https://api.groq.com/openai/v1`, OpenAI-compatible), user-confirmed
Free plan. Bounded test: ONE builder seat, TWO turns total, public
roman-numeral brief. Runtime: team-launcher 13781e6 (includes the
User-Agent fix this test exposed).

## What this proves and what it does not

PROVES: a live model's response can occupy a seat through the real
seat path (lease, path checks, runtime-executed verify, durable git
record); the harness records a live model's failure honestly; the bus
LOG feeds that failure back so the model repairs its own work on the
next turn.

DOES NOT PROVE: autonomous or unattended operation (an operator ran
each `seat --once`), heterogeneous platforms (one model, one seat),
cycle termination by the model (it never emitted DONE - see below),
or any multi-seat live team.

## Exact reproduction

```sh
python3 -m launcher init --repo REPO --branch team-work
# roster.json: one "builder" seat, adapter:
#   {"type": "http", "base_url": "https://api.groq.com/openai/v1",
#    "model": "openai/gpt-oss-20b", "api_key_env": "GROQ_API_KEY"}
# brief.md: build src/roman.py int_to_roman(1..3999) + unittest suite
python3 -m launcher prompt builder --repo REPO --branch team-work   # measure
GROQ_API_KEY=... python3 -m launcher seat builder --repo REPO --branch team-work --once
```

## Turn record (verbatim artifacts in this directory)

- `prompt-turn1.txt` (1,396 chars, live-measured): brief + empty LOG.
- Turn 1 (`TURN: builder acting`): model wrote `roman.py` +
  `test_roman.py`; runtime ran its verify command
  `python3 -m unittest discover -s tests` -> **exit=1, recorded**.
  Genuine model failure: the test imported `from roman import ...`
  while the module lives in `src/`.
- `prompt-turn2.txt` (rendered from the pre-turn-2 commit; 1,723 chars
  live-measured): the same brief plus the LOG entry carrying turn 1's
  failure tail.
- Turn 2 (`TURN: builder acting`): the model read its own recorded
  failure, rewrote the import (`from src.roman import ...`), verify
  -> **exit=0, 4 tests, OK**. Independent spot check after the run:
  `int_to_roman(2026) == "MMXXVI"`.
- `LOG.jsonl`, `STATE.json`, `roster.json`, `brief.md`,
  `commit-list.txt`: the durable bus record, copied unedited.

## Termination limit (honest)

The model never set `status_line` starting with DONE and handed off to
null, leaving `STATE.json` at turn=null / status="running". The
current conformance checker flags exactly this ("cycle not marked
done") - the same closing-validation gap first recorded in
rehearsal/i2i-2, now observed with a live model. Recorded, not
retro-fixed. Closing a live-model cycle currently needs a coordinator
seat or an operator close.

## Provider edge finding (fixed)

Groq's edge returned **403** for chat completions sent with the bare
`Python-urllib/3.10` User-Agent while GET /models succeeded. The http
adapter now sends an explicit User-Agent (13781e6, fixture-asserted).
Diagnosis consumed one minimal authorized completion (~83 tokens of
free quota).

## Rate limits observed

Post-call response headers on the account: 8000 TPM / 1000 RPD for
`openai/gpt-oss-20b` (account-specific, consistent with the published
docs table; headers describe the moment, not a plan guarantee).

## Labels

Assistant-operated bounded live test; public project payload only; no
private data left this repository. Not a rehearsal cycle, not peer
work, not an endurance or autonomy claim.
