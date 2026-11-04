# Response Contract

This document defines the exact format that AI assistants must use when responding to the launcher in this repository.

## Required JSON Structure
The reply must be a **single JSON object** with the following keys:

- `summary`: A one‑line description of what the assistant did.
- `writes`: An object mapping relative file paths (within the assistant's allowed paths) to the full new file content strings.
- `verify_command`: A shell command (string) that can be executed to verify the writes, or `null` if none.
- `handoff`: Either `null` or an object `{ "to": "seat-name", "note": "optional note" }` indicating the next seat.
- `status_line`: A short human‑readable progress line.

The entire response **must be exactly one JSON object**, either:

```json
{ ... }
```

or the raw object with no surrounding text. No additional prose, multiple fences, or extra objects are allowed.

## Write Constraints
- Paths in `writes` must be relative and confined to the assistant's `allowed_paths`.
- Only the files listed in the scope may be created or modified.

## Verification
The `verify_command` should be a command that, when run, confirms the writes (e.g., `cat <path>`). It may be `null` if verification is not applicable.

## Handoff
If further processing is needed, set `handoff` to the next seat name and an optional note; otherwise, use `null`.

## Status Line
Provide a concise status line for human reviewers, e.g., `Created docs/response-contract.md`.
