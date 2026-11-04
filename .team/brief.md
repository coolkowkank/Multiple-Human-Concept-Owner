# Batch: prompt-size measurement for `launcher prompt`

## Goal
Give operators a cheap way to see how big a rendered prompt is BEFORE
sending it to a provider with token limits.

## Required behavior
`python3 -m launcher prompt NAME --repo R --branch B --measure`
must print one extra line at the very end, in exactly this shape:
`measure: system=<N>c task=<N>c total=<N>c est_tokens=<N> (estimate: total_chars/4)`
where the counts are the character lengths of the rendered system and
task prompts. The token figure MUST stay labeled as an estimate - it
is total characters divided by 4, never a rate-fit guarantee.
Without `--measure`, output must be byte-identical to today.

## Implementation constraints
- Put the measurement helper in launcher/prompts.py (small, pure,
  Python standard library only).
- Wire the `--measure` flag in launcher/cli.py `cmd_prompt` (argparse,
  `action="store_true"`).
- Add tests in tests/test_prompt_budget.py proving: the line format,
  the counts match the rendered prompts, and no line without the flag.
- Do not change any other behavior. Standard library only.
- You may write ONLY these files: launcher/prompts.py,
  launcher/cli.py, tests/test_prompt_budget.py

## Current cmd_prompt source (launcher/cli.py), verbatim:
```python
def cmd_prompt(args):
    """Print the exact (system, task) prompt a seat would receive this
    turn, so an external operator (interactive paste session, or an
    assistant-mediated agent) reasons against the real input."""
    bus = Bus(args.repo, args.branch)
    bus.pull()
    state = bus.state()
    seat = Seat(bus, args.name)
    if state.get("turn") != args.name:
        print(f"note: turn is {state.get('turn')!r}, not {args.name!r}; "
              "rendering the prompt as if it were", file=sys.stderr)
    system, task = seat.build_prompt(state)
    print("=== SYSTEM ===")
    print(system)
    print("=== TASK ===")
    print(task)
```

## Verify command to supply
python3 -m unittest discover -s tests
