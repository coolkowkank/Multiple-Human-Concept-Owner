# Batch: brief linter (new files only)

Create exactly two NEW files. This batch is the whole task; every
other project file stays untouched.

1. `launcher/brief_lint.py` (stdlib only, under 70 lines):
   - `mentioned_paths(text: str) -> list[str]`: return the sorted
     unique repo-relative paths mentioned in the text. A path token
     looks like `launcher/foo.py`, `tests/test_x.py` or
     `docs/name.md`: one of the prefixes launcher/, tests/, docs/,
     followed by word characters, dots, slashes or dashes.
   - `forbidden_mentions(brief_text: str, allowed_paths: list[str]) -> list[str]`:
     the mentioned paths NOT equal to or under any allowed path.
   - Module docstring: explains why - a brief that names files outside
     a seat's allowed paths primes the model to write them.

2. `tests/test_brief_lint.py` (unittest):
   - mentioned_paths finds launcher/a.py and tests/test_b.py in a
     sentence, dedupes repeats, and returns [] for prose without paths.
   - forbidden_mentions returns launcher/cli.py when allowed_paths is
     ["launcher/token_est.py"], and [] when every mention is allowed.

verify_command: python3 -m unittest discover -s tests -v
status_line: brief linter added
handoff: null
