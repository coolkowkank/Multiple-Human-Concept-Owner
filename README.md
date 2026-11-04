# Operator records branch: live/groq-dev-3-records

Per-event auto-checkpoints of attempt transcripts from the self-commit
executor harness (operator record-keeping). Each harness event (system/user
prompt, API response with request id + usage, tool result, or error) is
committed+pushed here immediately, so a sandbox crash or reset cannot
silently erase call accounting.

This branch is OPERATOR record-keeping. It is NOT part of any Groq
self-commit fulfillment: the model's own tool-call commits live only on
live/groq-dev-3. Failed runs, blocked calls and probes are recorded here
when they occur; nothing here implies a successful model commit.
