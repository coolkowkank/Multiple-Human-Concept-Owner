"""Conformance checker: does a project repo's .team record match the
evidence interface (docs/evidence-interface.md v0.1)?

Runtime-side mechanical checks - the same class of check the acceptance
protocol's Stage 2 seeds faults against. This checker inspects the
record; it is inspection, not a security proof, and it does not replace
the reviewer re-run backstop.

    python3 -m launcher conform --repo PATH
"""

from __future__ import annotations

import json
import os

VALID_KINDS = {"message", "handoff", "finding", "verdict", "gate",
               "answer", "status", "error", "restart", "stall"}
STATE_KEYS = {"turn", "turn_seq", "turn_since", "status", "status_line",
              "leases"}
SEAT_KEYS = {"role", "allowed_paths", "adapter"}


def check_repo(repo):
    """Return (problems, notes): strings describing violations / facts."""
    problems, notes = [], []

    def req(path):
        full = os.path.join(repo, path)
        if not os.path.exists(full):
            problems.append(f"missing {path}")
            return None
        return full

    # STATE schema
    state_path = req(".team/STATE.json")
    if state_path:
        try:
            state = json.load(open(state_path))
            missing = STATE_KEYS - set(state)
            if missing:
                problems.append(f"STATE.json missing keys {sorted(missing)}")
            if not isinstance(state.get("turn_seq"), int):
                problems.append("STATE.json turn_seq is not an integer")
            notes.append(f"status={state.get('status')} "
                         f"turn={state.get('turn')} "
                         f"seq={state.get('turn_seq')}")
        except json.JSONDecodeError as exc:
            problems.append(f"STATE.json is not valid JSON: {exc}")

    # Roster schema
    roster_path = req(".team/roster.json")
    seats = {}
    if roster_path:
        try:
            roster = json.load(open(roster_path))
            seats = roster.get("seats", {})
            if not seats:
                problems.append("roster.json has no seats")
            for name, spec in seats.items():
                missing = SEAT_KEYS - set(spec)
                if missing:
                    problems.append(
                        f"roster seat {name} missing {sorted(missing)}")
                elif not isinstance(spec["allowed_paths"], list):
                    problems.append(f"roster seat {name}: allowed_paths "
                                    "is not a list")
        except json.JSONDecodeError as exc:
            problems.append(f"roster.json is not valid JSON: {exc}")

    # LOG: parse, kinds, fencing order, evidence fields
    log_path = req(".team/LOG.jsonl")
    if log_path:
        last_seq = 0
        for lineno, line in enumerate(open(log_path), 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                problems.append(f"LOG.jsonl line {lineno}: invalid JSON")
                continue
            for key in ("ts", "seat", "kind", "body"):
                if key not in entry:
                    problems.append(
                        f"LOG.jsonl line {lineno}: missing {key!r}")
            kind = entry.get("kind")
            if kind and kind not in VALID_KINDS:
                problems.append(
                    f"LOG.jsonl line {lineno}: unknown kind {kind!r}")
            seat = entry.get("seat")
            if seat and seats and seat not in seats and seat != "supervisor":
                problems.append(
                    f"LOG.jsonl line {lineno}: {seat!r} is not a roster seat")
            seq = entry.get("turn_seq")
            # Interface v0.1 section 2: turn_seq is optional per entry and
            # retries may reuse a seq. Strictly-increasing is the
            # exactly-once tripwire for TURN-ADVANCING entries (handoffs);
            # other kinds are annotations and may reference any seq.
            if kind == "handoff" and seq is not None:
                if not isinstance(seq, int) or seq <= last_seq:
                    problems.append(
                        f"LOG.jsonl line {lineno}: handoff turn_seq {seq} "
                        f"not strictly increasing after {last_seq}")
                else:
                    last_seq = seq
            if kind == "handoff":
                body = entry.get("body", "")
                if "verify:" in body and "exit=" not in body:
                    problems.append(
                        f"LOG.jsonl line {lineno}: handoff names a verify "
                        "command but records no exit code")

    # Gates schema + orphan answers
    pending = _read_jsonl(repo, ".team/gates/PENDING.jsonl", problems)
    answers = _read_jsonl(repo, ".team/gates/ANSWERS.jsonl", problems)
    ids = {g.get("id") for g in pending}
    for g in pending:
        for key in ("id", "ts", "seat", "question"):
            if key not in g:
                problems.append(f"gate missing {key!r}: {g}")
    for a in answers:
        if a.get("id") not in ids:
            problems.append(f"answer references unknown gate {a.get('id')}")
    notes.append(f"gates: {len(pending)} total, "
                 f"{len(pending) - len({a.get('id') for a in answers})} open")

    # Brief present with a done definition
    brief_path = req(".team/brief.md")
    if brief_path:
        brief = open(brief_path).read().lower()
        if "finished" not in brief and "done" not in brief:
            notes.append("brief has no definition-of-finished section")

    return problems, notes


def _read_jsonl(repo, path, problems):
    full = os.path.join(repo, path)
    if not os.path.exists(full):
        return []
    rows = []
    for lineno, line in enumerate(open(full), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            problems.append(f"{path} line {lineno}: invalid JSON")
    return rows


def main(argv):
    repo = "."
    if "--repo" in argv:
        repo = argv[argv.index("--repo") + 1]
    problems, notes = check_repo(repo)
    for n in notes:
        print(f"note: {n}")
    for p in problems:
        print(f"NONCONFORMANT: {p}")
    print("conformance:", "FAIL" if problems else "PASS")
    return 1 if problems else 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
