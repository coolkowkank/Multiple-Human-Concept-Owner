# Brief: bounded Groq live-model test (public payload)

ONE builder turn, model openai/gpt-oss-20b via Groq free plan.

Build `src/roman.py` with `int_to_roman(n)` for integers 1..3999
(standard subtractive notation) and `tests/test_roman.py` (unittest:
1, 4, 9, 58, 1994, 3999 boundary). Verify: `python3 -m unittest
discover -s tests`. Then DONE.
