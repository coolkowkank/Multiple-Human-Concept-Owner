# Self‑Commit Protocol

This repository is set up so that an LLM can safely commit its own changes. The process is fully mechanical and enforced by a few simple guards.

## Allowed tool calls
1. **write_file** – creates or overwrites files **only** under the `docs/` directory.
2. **git_commit** – stages everything that was written under `docs/` and creates a commit.
3. **git_push** – pushes the current branch (`live/groq-dev-3`) to GitHub.

## Mechanical safeguards
- **Path restriction** – `write_file` will reject any path that is not inside `docs/`. This prevents the model from altering code, configuration, or secret files.
- **Credential‑pattern refusal** – the model is prohibited from writing strings that look like credentials (e.g., `ghp_`, `aws_`, `token=`). The tool will reject such content.
- **Commit‑message hook** – the repository includes a `commit‑msg` hook that requires the line `TURN: builder` in every commit message. If the line is missing, the commit is rejected.

## Human oversight
Even though the model can perform the three tool calls automatically, a human reviewer can inspect the generated documentation and the resulting commit diff before the push is accepted. This final check ensures that the model did not inadvertently introduce unwanted changes.

## Typical workflow
```text
1. Model calls write_file(...) to add or update a doc file.
2. Model calls git_commit(message="...\nTURN: builder") to record the change.
3. Model calls git_push() to publish the commit.
```

The combination of path limits, credential checks, and the mandatory `TURN: builder` line provides a clear, auditable way for the model to contribute without over‑stepping its bounds.
