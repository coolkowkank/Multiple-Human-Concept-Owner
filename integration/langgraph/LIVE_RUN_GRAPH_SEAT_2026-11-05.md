# Model-backed graph seat: two attempts, 2026-11-05

Project record, not a grant or a qualification. Both attempts used the
fenced http seat in `langgraph_team.py` (head 738205d) on a scratch lane
outside the repo: seat `coordinator` only (the other four seats were not
run), one lane, one writer, requested model
`nvidia/nemotron-3-ultra-550b-a55b` through the fixed router endpoint.
Per-seat budget 2; the log lives in a fixed directory outside the repo.

Pre-call basis (both attempts): the router's public model listing,
fetched just before each call, showed input and output price 0 for this
id. Costs below are provider-reported usage, not independent billing proof.
The router's response model field and response id are not captured by the
adapter, so requested vs reported model cannot be compared.

## Attempt 1 - 07:26:24Z to 07:26:35Z - refused by the project's validator

- Request 1 (reserve n=1): HTTP 200, usage prompt 325, completion 667,
  total 992, cost 0.
- The reply parsed as the required JSON object, then the graph's own
  response screen refused it: `verify_command must start with ('python3',
  'python', 'pytest') and stay relative to the repo`.
- Nothing was committed. Bus state unchanged (turn coordinator, seq 0).
- Result: refusal. Not a successful seat turn.

## Attempt 2 - 07:27:33Z to 07:27:41Z - accepted turn

Before this attempt the operator committed a brief update (instruction_seq
1 -> 2) that states the runtime's reply rules for the coordinator
(verify_command null or a python3/python/pytest command with relative paths;
valid handoff names; gate not needed) and suggests a first turn: write
`.team/ACCEPTANCE.md` with two criteria, verify_command null, handoff
builder. The guard was not changed. The model's output closely follows that
suggestion, so this shows the seat can follow explicit rules, not that it
can plan the batch unaided.

- Request 2 (reserve n=2): HTTP 200, usage prompt 511, completion 200,
  total 711, cost 0.
- Accepted by the validator and committed as `TURN: coordinator acting`
  (3 files: `.team/ACCEPTANCE.md`, `.team/LOG.jsonl`, `.team/STATE.json`).
- Resulting state: turn builder, turn_seq 1, status_line "Acceptance
  criteria written; handing off to builder".
- Committed output `.team/ACCEPTANCE.md`:
  1. src/app.py provides add(a,b)
  2. python3 tests/test_app.py exits 0

## Accounting and limits

- Provider requests: 2 total, 2 of 2 reserves used on this log, no retries,
  no halt, no redirect, cost reported 0 both times.
- The usage log is local to the run machine; it was not published. The
  lifetime cap of 8 is a self-imposed project bound and the count can be
  reset by deleting that directory (not prevented). Tail truncation of the
  log is not detected.
- Prompts, raw replies and traces are not published.
- This is a Builder-style seat output on a Ryan-independent path. It is not
  a Verifier result and does not qualify the model or the team.
- Not run: builder, reviewer, qc, records seats; no model wrote application
  code.
