# Self‑Commit Protocol

This repository uses an automated *self‑commit* workflow that allows a language model to create and publish its own changes safely. The process is limited to three explicit tool calls:

1. **`write_file`** – creates or updates a file **only** under the `docs/` directory. Any attempt to write outside this path is rejected by the tool.
2. **`git_commit`** – stages **all** changes that were written with `write_file` and creates a commit. The commit message must include the exact line `TURN: builder` (required by the repository’s `commit‑msg` hook). The message should be honest, e.g. “Groq gpt‑oss‑120b committing via tool calls”.
3. **`git_push`** – pushes the current branch (`live/groq-dev-3`) to GitHub.

### Mechanical Guardrails
- **Path restriction:** `write_file` validates that the target path starts with `docs/`. Attempts to modify code, configuration, or any other location are automatically blocked.
- **Credential‑pattern refusal:** If the content contains patterns that look like secrets (e.g., `AKIA…`, `ssh‑key`, `password=`), the tool refuses to write the file.
- **Commit‑msg hook:** The repository enforces a hook that rejects any commit missing the line `TURN: builder`. This ensures every automated commit is explicitly flagged as a model‑generated change.

### Human Review
After the push, a human reviewer can inspect the new commit on GitHub. The reviewer may:
- Verify that the change only affects documentation.
- Confirm that no secret or policy‑violating content was introduced.
- Approve the change or request a correction.

This lightweight protocol balances automation speed with safety and accountability.
