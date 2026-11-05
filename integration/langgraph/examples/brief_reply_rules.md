
Reply rules for model-backed seats (generic example, append to a brief):
- Reply with exactly one JSON object and nothing else (no code fence, no prose around it).
- Write only inside the paths your seat is allowed to write. Builder: the task source and tests. Reviewer: review/. QC: review/ (verdict file). Records: records/. Coordinator close-out: .team/.
- Set verify_command to the test command only if your seat is the Builder; otherwise null.
- Do not claim a result you did not produce. The runtime runs verify commands itself and records the exit code.
- A closeout or DONE status means the team cycle finished. It is not a quality result.
