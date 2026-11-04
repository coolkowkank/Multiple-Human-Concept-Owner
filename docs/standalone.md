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
   - `MODEL_COMMITTER` - committer identity for model-issued commits (default: the shared bot's account-linked noreply); set it to the token account's noreply so author/committer/pusher stay honest
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

## GitHub access: token-only (no passwords)

The launcher never asks for a GitHub password. You create a personal access token on the account that should push (your own or a shared bot), keep it in a local file, and the runner uses it as the push/pull transport for operations the model requests:

1. Create a classic PAT at https://github.com/settings/tokens. Minimum scope: `public_repo` (public repos) or `repo` (private). Set an expiration - GitHub strongly recommends one; a no-expiry token stays valid until revoked.
   Fine-grained PATs cannot write repos where the account is only a collaborator (docs.github.com: "Fine-grained personal access tokens limitations"), so use a classic PAT for a shared bot on someone else's repo.
2. `install -m 600 /dev/null ~/.mhco/push-token && $EDITOR ~/.mhco/push-token` (token only, one line).
3. `python3 tools/setup_push_auth.py --repo PATH --owner OWNER --name REPO` - verifies the token's account and push permission (clear errors for 401 invalid token / 404 no access / no push permission), then sets a repo-local credential helper that reads the file at push time. The token is never printed, logged, committed, or stored in git config.

Two limits always apply:
- The token's scopes are the CAPABILITY ceiling: nothing it doesn't permit can happen.
- The human's project authorization is the OPERATING boundary: a broad token does not authorize every action it technically allows. Human control gates (no auto-merge, budget, review loop) are unchanged.

The model never sees the token. Author names stay per-model (`MODEL_AUTHOR`); committer and pusher identities stay separate and honest (docs/design-decisions.md D14).
