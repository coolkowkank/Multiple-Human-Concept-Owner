# Batch: standalone token estimation module

Write a small standalone Python utility module and its unit tests.
Nothing else exists for you to change; this batch is the whole task.

Files to create:

1. `launcher/token_est.py` (stdlib only, under 60 lines):
   - `estimate_tokens(text: str) -> int`: ceil(len(text) / 4). Empty
     string -> 0.
   - `measure_prompt(system: str, task: str) -> dict` with keys
     system_chars, task_chars, total_chars, est_tokens (est_tokens
     from estimate_tokens of the combined text).
   - Module docstring stating the chars/4 figure is an estimate.

2. `tests/test_token_est.py` (unittest):
   - 400 chars -> 100 tokens; "" -> 0; 401 chars rounds up to 101;
     measure_prompt returns consistent totals.

verify_command: python3 -m unittest discover -s tests -v
status_line: token estimation module added
handoff: null
