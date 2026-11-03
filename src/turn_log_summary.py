"""Count handoff entries per seat in a .team/LOG.jsonl log."""
import json


def handoff_counts(log_path):
    """Return {seat: handoff-count} for kind == 'handoff' entries."""
    counts = {}
    with open(log_path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("kind") == "handoff":
                seat = entry.get("seat", "?")
                counts[seat] = counts.get(seat, 0) + 1
    return counts
