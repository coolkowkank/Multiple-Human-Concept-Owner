# Batch: token estimate helper (new files only)

Create exactly two NEW files. Do not modify, delete or rewrite any
existing file. Keep the module under 60 lines, stdlib only.

1. `launcher/token_est.py`:
   - `estimate_tokens(text: str) -> int`: ceil(len(text) / 4), the
     launcher's documented chars/4 heuristic. Empty string -> 0.
   - `measure_prompt(system: str, task: str) -> dict`: returns
     {"system_chars": int, "task_chars": int, "total_chars": int,
      "est_tokens": int} where est_tokens = estimate_tokens of the
     combined text.
   - Module docstring naming the estimate an estimate, never a
     rate-fit claim.

2. `tests/test_token_est.py` (unittest, mirror existing test style):
   - 400 chars -> 100 tokens; empty string -> 0; non-multiple-of-4
     rounds up; measure_prompt returns all four keys with consistent
     totals.

verify_command: python3 -m unittest discover -s tests -v
status_line: token estimate helper added
handoff: null
