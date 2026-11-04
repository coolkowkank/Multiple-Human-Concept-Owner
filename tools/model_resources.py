#!/usr/bin/env python3
"""Team Resources (Ryan) mechanism: route health checks and cap-aware
replacement selection. Stdlib only. This tool is deterministic and
credential-free: it never calls a provider itself. A fetched models
listing is read from a file; the credentialed fetch and any actual model
call stay with the task's authorized operator flow.

Authority model (owner's 2026-11-04 resource-fit grant):
propose prints DECISION (automatic replacement choice authorized) only
when ALL of: exact candidate id verified price-0 in the supplied fresh
listing; candidate fits the job shape in the supply map; the task's
existing attempt cap is unchanged (remaining > 0, no new calls beyond
the task's own budget); no new credentials/access; route not excluded
as money. Anything else prints COORDINATOR with the unresolved gap.
"""
import json, sys, datetime

def load(path):
    with open(path) as f:
        return json.load(f)

def price_zero(listing, model_id):
    """True only if the EXACT id exists in the listing with all-zero
    prices. A prefixed variant (deepinfra/...) never matches the bare
    id; a listed price-0 id is still only a listing fact."""
    for m in listing.get("data", []):
        if m.get("id") == model_id:
            vals = [m.get("input_price"), m.get("output_price"),
                    m.get("cached_price", 0)]
            return all(v == 0 for v in vals if v is not None)
    return False

def get_route(record, route_id):
    for r in record["routes"]:
        if r["id"] == route_id:
            return r
    return None

def cmd_check_price(listing_path, model_id):
    ok = price_zero(load(listing_path), model_id)
    print(("PRICE-ZERO " if ok else "NOT-FREE-OR-ABSENT ") + model_id)
    return 0 if ok else 1

def cmd_record_event(record_path, route_id, result, evidence):
    rec = load(record_path)
    r = get_route(rec, route_id)
    if r is None:
        print("COORDINATOR unknown route id " + route_id); return 1
    today = datetime.date.today().isoformat()
    if result == "ok":
        r["status"] = "working"
    elif result == "cap":
        r["status"] = "capped"
    elif result == "error":
        r["status"] = "uncallable"
    else:
        print("COORDINATOR bad result " + result); return 1
    r["evidence"] = today + " " + evidence
    rec["updated"] = today
    with open(record_path, "w") as f:
        json.dump(rec, f, indent=2)
    print("RECORDED " + route_id + " " + r["status"])
    return 0

def cmd_propose(record_path, listing_path, job_shape, failed_route,
                remaining_attempts):
    rec = load(record_path)
    if int(remaining_attempts) <= 0:
        print("COORDINATOR task attempt cap exhausted; a replacement "
              "would expand the live call cap"); return 1
    cands = [c for c in rec["supply_map"].get(job_shape, [])
             if c != failed_route]
    if not cands:
        print("COORDINATOR no recorded backup for job shape "
              + job_shape); return 1
    listing = load(listing_path) if listing_path and listing_path != "-" else None
    fit, gaps = [], []
    for cid in cands:
        r = get_route(rec, cid)
        if r is None or r["status"] != "working":
            gaps.append(cid + ": not working per record"); continue
        if listing is not None and not price_zero(listing, cid):
            gaps.append(cid + ": not price-0 in fresh listing"); continue
        if listing is None:
            gaps.append(cid + ": no fresh listing supplied; price "
                        "unverified"); continue
        fit.append(cid)
    if len(fit) == 1:
        print("DECISION use " + fit[0] + " for " + job_shape
              + " (replaces " + failed_route + "; within existing task"
              + " attempt cap; verified price-0; no new access)")
        return 0
    if not fit:
        print("COORDINATOR no fit replacement: " + "; ".join(gaps))
        return 1
    print("COORDINATOR multiple fits, choice needed: " + ", ".join(fit))
    return 1

def main(argv):
    if len(argv) < 2:
        print(__doc__); return 2
    cmd = argv[1]
    if cmd == "check-price" and len(argv) == 4:
        return cmd_check_price(argv[2], argv[3])
    if cmd == "record-event" and len(argv) == 6:
        return cmd_record_event(argv[2], argv[3], argv[4], argv[5])
    if cmd == "propose" and len(argv) == 7:
        return cmd_propose(argv[2], argv[3], argv[4], argv[5], argv[6])
    print(__doc__); return 2

if __name__ == "__main__":
    sys.exit(main(sys.argv))
