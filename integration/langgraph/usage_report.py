"""Read-only per-seat token/request report from a finished run's audit files (RW3).

Offline. No network, no credentials, no writes. Reads <seat>.audit.jsonl,
<seat>.links.jsonl and an optional <seat>.usage.jsonl from an audit directory
(the LG_AUDIT_DIR layout) and joins them with the pinned launcher.usage_join.

Rules (fail closed, never infer):
- Unknown stays unknown: a call without joined provider usage contributes
  nothing and is counted as unknown. Missing is never zero.
- Mock rows are counted but never enter token totals.
- Totals cover provider-joined calls only and are marked complete only when
  EVERY call of the seat/run is provider-joined.
- Provider-reported counts are provider-REPORTED, not verified identity or
  billing. The local call_id is the join key. No cost data exists in these
  rows, so none is reported.
- The audit rows carry no turn/cycle field, so there is no per-cycle
  breakdown; the report is per seat, with the correction-round tally from
  the link rows.
- An unreadable or malformed file refuses that whole seat (no rows used).
- compare takes the two AUDIT DIRECTORIES and recomputes both reports itself
  (a saved report file is never trusted). It refuses any figure unless: both
  runs are complete, they are different runs, and each operator outcome file
  names the same task_id, has accepted exactly true, a non-empty
  acceptance_evidence string, and a report_digest equal to the recomputed
  digest of its own run. Acceptance is OPERATOR-ATTESTED: nothing here
  verifies it. Even then it is one paired run, descriptive only.
- The same call_id or provider response id appearing in two seats refuses
  BOTH seats (no pick, no double count).
- Usage from an optional <seat>.usage.jsonl is an operator-supplied file, not
  authenticated provider identity; it is labelled in the report.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
USAGE_JOIN_MD5 = "d00259978e57bebfba30ee5f6e8121ab"   # same pin as audit_wiring
MAX_FILE = 64 * 1024 * 1024


class ReportError(Exception):
    pass


def _verify_pin():
    got = hashlib.md5(open(os.path.join(HERE, "launcher", "usage_join.py"), "rb").read()).hexdigest()
    if got != USAGE_JOIN_MD5:
        raise ReportError("launcher/usage_join.py md5 differs from the pinned version; refusing")


def _read_jsonl(path):
    """Rows of a regular, non-symlink file; any bad line refuses the file."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as e:
        raise ReportError(f"{os.path.basename(path)}: cannot open ({type(e).__name__})")
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise ReportError(f"{os.path.basename(path)}: not a regular file")
        if st.st_size > MAX_FILE:
            raise ReportError(f"{os.path.basename(path)}: larger than {MAX_FILE} bytes")
        rows = []
        for n, line in enumerate(fh.read().decode("utf-8", "replace").splitlines(), 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                raise ReportError(f"{os.path.basename(path)}:{n}: not valid JSON (no rows used)")
        return rows


def seat_report(audit_rows, link_rows=(), usage_rows=()):
    """Pure function: one seat's report from already-read rows."""
    from launcher import usage_join
    audit_rows = audit_rows if isinstance(audit_rows, list) else []
    usage_rows = usage_rows if isinstance(usage_rows, list) else []
    joined = usage_join.join(audit_rows, usage_join.usage_from_audit(audit_rows) + usage_rows)
    statuses = {}
    for r in joined["rows"]:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    prov = joined["provider_joined"]
    explicit_ids = {u["call_id"] for u in usage_rows if isinstance(u, dict) and isinstance(u.get("call_id"), str)}
    explicit_used = sum(1 for r in joined["rows"] if r["status"] == "joined_provider" and r["call_id"] in explicit_ids)
    mock = statuses.get("joined_mock", 0)
    total = joined["total_calls"]
    corr, reserved, ign_links = 0, 0, 0
    seen = set()
    known = {r["call_id"] for r in joined["rows"]}
    for l in link_rows if isinstance(link_rows, (list, tuple)) else []:
        if not (isinstance(l, dict) and isinstance(l.get("call_id"), str)) or l["call_id"] in seen or l["call_id"] not in known:
            ign_links += 1
            continue
        seen.add(l["call_id"])
        corr += l.get("correction_round") is True
        reserved += isinstance(l.get("n"), int) and not isinstance(l.get("n"), bool)
    p, c = joined["provider_prompt_tokens"], joined["provider_completion_tokens"]
    return {
        "calls": total, "provider_joined": prov, "mock": mock,
        "unknown": total - prov - mock,
        "status_counts": dict(sorted(statuses.items())),
        "complete": total > 0 and prov == total,
        "prompt_tokens": p, "completion_tokens": c,
        "total_tokens": (p + c) if p is not None and c is not None else None,
        "correction_round_calls": corr, "calls_with_reserve_number": reserved,
        "ignored_audit_rows": joined["ignored_audit_rows"], "ignored_usage_rows": joined["ignored_usage_rows"],
        "ignored_link_rows": ign_links,
        "usage_from_explicit_file_calls": explicit_used,
        "_call_ids": sorted(known),
        "_response_ids": sorted({r["response_id_sha256"] for r in joined["rows"] if r.get("response_id_sha256")}),
    }


def run_report(audit_dir):
    _verify_pin()
    if not os.path.isdir(audit_dir) or os.path.islink(audit_dir):
        raise ReportError("audit dir must be a real directory")
    seats = sorted(f[:-len(".audit.jsonl")] for f in os.listdir(audit_dir) if f.endswith(".audit.jsonl"))
    out, refused = {}, {}
    for s in seats:
        base = os.path.join(audit_dir, s)
        try:
            audit = _read_jsonl(base + ".audit.jsonl")
            links = _read_jsonl(base + ".links.jsonl") if os.path.lexists(base + ".links.jsonl") else []
            usage = _read_jsonl(base + ".usage.jsonl") if os.path.lexists(base + ".usage.jsonl") else []
            out[s] = seat_report(audit, links, usage)
        except ReportError as e:
            refused[s] = str(e)
    # same call_id or provider response id in two seats: refuse both, never pick or double count
    owners = {}
    for s_, r in out.items():
        for kind, ids in (("call_id", r["_call_ids"]), ("response_id", r["_response_ids"])):
            for i in ids:
                owners.setdefault((kind, i), set()).add(s_)
    collide = {}
    for (kind, _i), seats_ in owners.items():
        if len(seats_) > 1:
            for s_ in seats_:
                collide.setdefault(s_, set()).add(kind)
    for s_, kinds in collide.items():
        out.pop(s_)
        refused[s_] = "same " + " and ".join(sorted(kinds)) + " appears in another seat; seat refused, nothing double counted"
    for r in out.values():
        r.pop("_call_ids"); r.pop("_response_ids")
    ok = list(out.values())
    calls = sum(r["calls"] for r in ok)
    prov = sum(r["provider_joined"] for r in ok)
    have = [r for r in ok if r["total_tokens"] is not None]
    rep = {
        "schema": "usage-report/v1",
        "seats": out, "refused_seats": refused,
        "cross_seat_collision_seats": sorted(collide),
        "calls": calls, "provider_joined": prov, "unknown_or_mock": calls - prov,
        "prompt_tokens": sum(r["prompt_tokens"] for r in have) if have else None,
        "completion_tokens": sum(r["completion_tokens"] for r in have) if have else None,
        "total_tokens": sum(r["total_tokens"] for r in have) if have else None,
        "complete": bool(ok) and not refused and all(r["complete"] for r in ok),
        "usage_from_explicit_file_calls": sum(r["usage_from_explicit_file_calls"] for r in ok),
        "note": ("totals cover provider-joined calls only; unknown and mock calls are excluded, never counted as zero; "
                 "counts are provider-reported, not verified; usage from an explicit <seat>.usage.jsonl is an operator-supplied "
                 "file, not authenticated provider identity; no cost data; no per-cycle breakdown (audit rows carry no cycle field)"),
    }
    rep["digest"] = digest(rep)
    return rep


def digest(rep):
    """sha256 of the canonical report body (the digest field excluded)."""
    body = {k: v for k, v in rep.items() if k != "digest"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _outcome(o, label, report_digest):
    """Return (task_id, reasons). Operator-written, operator-attested record."""
    bad = []
    if not isinstance(o, dict):
        return None, [f"{label}: outcome is not an object"]
    if o.get("accepted") is not True:
        bad.append(f"{label}: outcome.accepted is not exactly true")
    ev = o.get("acceptance_evidence")
    if not (isinstance(ev, str) and ev.strip()):
        bad.append(f"{label}: no acceptance_evidence string")
    if o.get("report_digest") != report_digest:
        bad.append(f"{label}: outcome.report_digest does not equal this run's recomputed report digest")
    tid = o.get("task_id")
    if not (isinstance(tid, str) and tid.strip()):
        bad.append(f"{label}: no task_id string")
        tid = None
    return tid, bad


def compare(dir_a, dir_b, outcome_a, outcome_b):
    """Recomputes both runs from their audit dirs; nothing saved is trusted."""
    reasons = []
    if os.path.realpath(dir_a) == os.path.realpath(dir_b):
        return {"comparable": False, "reasons": ["A and B are the same directory: not a comparison"]}
    rep_a, rep_b = run_report(dir_a), run_report(dir_b)
    if rep_a["digest"] == rep_b["digest"]:
        reasons.append("A and B have identical reports: same run or copied data, not a comparison")
    for lab, rep in (("A", rep_a), ("B", rep_b)):
        if rep["complete"] is not True:
            reasons.append(f"{lab}: coverage incomplete (unknown, mock, refused, colliding or empty); totals would not be the whole run")
    ta, ba = _outcome(outcome_a, "A", rep_a["digest"]); tb, bb = _outcome(outcome_b, "B", rep_b["digest"])
    reasons += ba + bb
    if ta and tb and ta != tb:
        reasons.append("A and B have different task_id: not a matched comparison")
    if reasons:
        return {"comparable": False, "reasons": reasons, "digest_a": rep_a["digest"], "digest_b": rep_b["digest"]}
    a, b = rep_a["total_tokens"], rep_b["total_tokens"]
    return {"comparable": True, "task_id": ta, "digest_a": rep_a["digest"], "digest_b": rep_b["digest"],
            "total_tokens_a": a, "total_tokens_b": b, "difference_b_minus_a": b - a,
            "usage_from_explicit_file_calls": {"a": rep_a["usage_from_explicit_file_calls"], "b": rep_b["usage_from_explicit_file_calls"]},
            "note": "acceptance is OPERATOR-ATTESTED, not independently verified; one paired run, descriptive only, not a savings claim "
                    "(no repeats, no variance, provider-reported counts)"}


def _load(path, cap=1024 * 1024):
    rows = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as e:
        raise ReportError(f"{os.path.basename(path)}: cannot open ({type(e).__name__})")
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_size > cap:
            raise ReportError(f"{os.path.basename(path)}: not a regular file or larger than {cap} bytes")
        try:
            return json.loads(fh.read().decode("utf-8", "replace"))
        except ValueError:
            raise ReportError(f"{os.path.basename(path)}: not valid JSON")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if len(argv) == 2 and argv[0] == "report":
            json.dump(run_report(argv[1]), sys.stdout, indent=2, sort_keys=True); print(); return 0
        if len(argv) == 5 and argv[0] == "compare":
            res = compare(argv[1], argv[2], _load(argv[3]), _load(argv[4]))
            json.dump(res, sys.stdout, indent=2, sort_keys=True); print()
            return 0 if res["comparable"] else 2
    except (ReportError, OSError, ValueError, TypeError, KeyError) as e:
        print(f"usage_report: {type(e).__name__}: {e}", file=sys.stderr); return 1
    print("usage: usage_report.py report AUDIT_DIR\n       usage_report.py compare AUDIT_DIR_A AUDIT_DIR_B OUTCOME_A.json OUTCOME_B.json", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
