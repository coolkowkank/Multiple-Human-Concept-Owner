# Batch 1 (i2i-2)

- Assigned to: builder
- Scope: create src/turn_log_summary.py with handoff_counts(log_path) returning {"counts": {seat: n}, "malformed": [line_numbers]} - malformed LOG lines are skipped and reported by line number, never raised (fixes the genuine i2i-1 review finding). Plus tests/test_turn_log_summary.py. Nothing beyond it.
- Acceptance: subset suite passes; named honestly, never as full baseline.
- Owner basis: none - no gated items (synthetic rehearsal content).
- Verify command: python3 -m unittest discover -s tests -p test_turn_log_summary.py
