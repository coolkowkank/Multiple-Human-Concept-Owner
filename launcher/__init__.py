"""Team launcher runtime for the Multiple-Human-Concept-Owner blueprint.

Turns the blueprint's written conventions (turn token, single writer,
independent QC, recorded decisions) into enforced mechanism: a git-backed
message bus, per-seat leases, mechanical guards, supervised seat processes
with restart, and a human-gate escalation queue.

Stdlib-only on purpose: a team starts with `python3 -m launcher ...` and
nothing to install.
"""

__version__ = "0.1.0"
