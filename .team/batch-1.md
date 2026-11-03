# Batch 1 (rehearsal i2i-1)

- Assigned to: builder
- Scope: add src/turn_log_summary.py (count handoff entries per seat in a .team/LOG.jsonl) and tests/test_turn_log_summary.py. Nothing beyond it.
- Acceptance: new test module passes; honest subset-suite naming, never reported as full baseline.
- Owner basis: none - no gated items (synthetic rehearsal content, mock work).
- Verify command: python3 -m unittest discover -s tests -p test_turn_log_summary.py
