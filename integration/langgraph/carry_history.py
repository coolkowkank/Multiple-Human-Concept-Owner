"""carry_history: offline assessment of a FORWARD-ONLY accounting window after
the original private ledger was lost. It never reads or writes a ledger dir,
never creates logs/epochs, and approves nothing. It exists so that a later,
separately authorized new attempt cannot start from "zero reserves" as if the
old calls never happened.

Input: a carry-history/v1 manifest, an operator-supplied RECORD of what the lost
ledger is known to have held (it is not a ledger and not verified here):
  {"schema": "carry-history/v1", "source": "<where the counts come from>",
   "recorded_reserves": N, "cap_at_loss": C or null,
   "unknown": [{"rid": "...", "model": "...", "note": "..."}],   # consumed/unknown calls
   "settled": [{"rid": "...", "model": "..."}]}
Rules (all fail closed):
 - recorded_reserves counts against the NEW window's cap in full. unknown and
   settled entries are each one reserve already; their number must not exceed it.
 - Unknown calls stay unknown and consumed. They are echoed in every verdict
   (`unknown_carried`) and are never reduced by a manifest field, a flag or a
   reason string. There is no input that clears one.
 - Verdict `fits` only when carried + planned <= cap. Otherwise it reports the
   minimum cap that would fit (`min_cap_needed`). Choosing a cap is an internal
   operator control that needs its own grounded decision; this module only
   states the arithmetic.
 - `executable` is always False: acceptance here is never an execution GO, and
   the real fence still counts only the logs that exist in its own directory.
   A window built on this record would additionally need those carried reserves
   to exist as real fence logs, which this module does not and must not create.
"""
import json, re, sys

SCHEMA = "carry-history/v1"
_ID = re.compile(r"^[A-Za-z0-9._:/-]{1,80}$")


def _int(x, lo=0):
    return isinstance(x, int) and not isinstance(x, bool) and x >= lo


def assess(manifest, cap, planned):
    out = {"schema": "carry-history-verdict/v1", "status": "refuse", "executable": False,
           "problems": [], "unknown_carried": [], "carried": None, "cap": cap,
           "planned": planned, "remaining": None, "min_cap_needed": None,
           "limitations": ["a record, not a ledger: counts are unverified claims of the operator",
                           "does not create fence logs; the fence counts only logs it can read",
                           "not an execution approval"]}
    try:
        if not _int(cap) or not _int(planned):
            out["problems"].append("cap and planned must be non-negative ints"); return out
        if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
            out["problems"].append("manifest is not carry-history/v1"); return out
        extra = set(manifest) - {"schema", "source", "recorded_reserves", "cap_at_loss", "unknown", "settled"}
        if extra:
            out["problems"].append("unknown manifest keys: %s" % sorted(extra)); return out
        if not (isinstance(manifest.get("source"), str) and manifest["source"].strip()):
            out["problems"].append("source is required (where the counts come from)"); return out
        rr = manifest.get("recorded_reserves")
        if not _int(rr):
            out["problems"].append("recorded_reserves must be a non-negative int"); return out
        if manifest.get("cap_at_loss") is not None and not _int(manifest["cap_at_loss"]):
            out["problems"].append("cap_at_loss must be an int or null"); return out
        seen = set()
        for key in ("unknown", "settled"):
            lst = manifest.get(key, [])
            if not isinstance(lst, list):
                out["problems"].append("%s must be a list" % key); return out
            for e in lst:
                if not (isinstance(e, dict) and isinstance(e.get("rid"), str) and _ID.match(e["rid"])
                        and isinstance(e.get("model"), str) and e["model"]
                        and set(e) <= {"rid", "model", "note"}):
                    out["problems"].append("malformed %s entry" % key); return out
                if e["rid"] in seen:
                    out["problems"].append("duplicate rid %s" % e["rid"]); return out
                seen.add(e["rid"])
        unk = manifest.get("unknown", [])
        if len(unk) + len(manifest.get("settled", [])) > rr:
            out["problems"].append("more listed calls than recorded_reserves: record is inconsistent")
            return out
        out["unknown_carried"] = [dict(e) for e in unk]
        out["carried"] = rr
        out["remaining"] = max(0, cap - rr)
        out["min_cap_needed"] = rr + planned
        if rr + planned <= cap:
            out["status"] = "fits"
        else:
            out["status"] = "over_cap"
            out["problems"].append("carried %d + planned %d exceeds cap %d" % (rr, planned, cap))
        return out
    except Exception as exc:
        out["status"] = "refuse"; out["problems"].append("error: " + exc.__class__.__name__)
        return out


def main(argv):
    if len(argv) != 4:
        print("usage: carry_history.py MANIFEST.json CAP PLANNED  (read-only, offline)", file=sys.stderr)
        return 2
    try:
        m = json.load(open(argv[1])); v = assess(m, int(argv[2]), int(argv[3]))
    except (OSError, ValueError) as exc:
        v = {"status": "refuse", "executable": False, "problems": ["unreadable input: %s" % type(exc).__name__]}
    print(json.dumps(v, indent=1, sort_keys=True))
    return 0 if v["status"] == "fits" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
