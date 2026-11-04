# Run a project without Instinct (standalone)

Everything in this repo is Python 3 stdlib + git + HTTPS API calls. No Instinct dependency.

## Pieces
- `launcher/` - seats and launches model workers; installs the commit-msg guard hook.
- `tools/self-commit-executor.py` - drives one model through tool-call rounds; the model commits and pushes its own work. Guards: per-event transcript capture (fail-closed), global call budget, message-format hook.
- `tools/loop_runner.py` - watches a review branch for immutable `FEEDBACK-cN.md`, runs the executor with the feedback verbatim, advances `LOOP.json`. Human terminal control.

## Setup
1. Python 3, git, network access to your provider and GitHub.
2. Provider key in a 0600 file; point `PROVIDER_KEY_FILE` at it (or `GROQ_KEY_FILE`).
3. Push credential: git's own credential helper or SSH key on the shared bot account. Never stored in this repo.
4. Env (all optional, defaults shown are this project's live loop):
   - `PROVIDER_API_URL` (default Groq), `PROVIDER_MODEL` (default openai/gpt-oss-120b)
   - `MODEL_AUTHOR` - per-model name + the shared bot's account-linked noreply, e.g. `"Kimi (k2 model) <350571665+coolkowkank-bot@users.noreply.github.com>"`
   - `RECORDS_COMMITTER` - operator identity for checkpoint commits on the records branch
   - `RECORDS_DIR` - required; worktree of the operator records branch
   - `MAX_CALLS` - remaining provider-call budget (counted before issuing, failures count, no retries)

## Run one task
```
python3 -m launcher init && python3 -m launcher seat && python3 -m launcher launch
RECORDS_DIR=/path/to/records-wt MAX_CALLS=6 \
  python3 tools/self-commit-executor.py /path/to/model-wt live/BRANCH attempt-1 /path/to/task.md
```

## Run the review loop
```
python3 tools/loop_runner.py --repo MODEL_WT --records RECORDS_WT \
  --review-branch review/BRANCH --budget 6 --interval 3600
```

## Human control (unchanged)
- Merges to main are human decisions; nothing here merges.
- Budget exhaustion with unaddressed feedback = ESCALATE, not more calls.
- Reviewer verdicts land only in immutable `FEEDBACK-cN.md` files; the runner never accepts anything else as feedback.

## Honest status
Offline-proven: executor guards (12 tests), loop-runner state transitions (4 tests), env-configurable identities. Not yet proven: a full standalone run using the bot account's own push credential (needs the credential to exist and be authorized).
