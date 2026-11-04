"""Count handoff entries per seat in a .team/LOG.jsonl log.

Malformed lines are skipped and reported by 1-based line number,
never raised (i2i-1 review finding, batch 1 of i2i-2)."""
import json


def handoff_counts(log_path):
    """Return {"counts": {seat: n}, "malformed": [line_numbers]}."""
    counts, malformed = {}, []
    with open(log_path) as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                malformed.append(lineno)
                continue
            if entry.get("kind") == "handoff":
                seat = entry.get("seat", "?")
                counts[seat] = counts.get(seat, 0) + 1
    return {"counts": counts, "malformed": malformed}
