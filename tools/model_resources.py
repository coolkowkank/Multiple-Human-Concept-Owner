#!/usr/bin/env python3
"""Team Resources (Ryan) mechanism: route health checks and cap-aware
replacement selection. Stdlib only. Deterministic and credential-free:
it never calls a provider itself. The credentialed fetch and any actual
model call stay with the task's authorized operator flow.

Listings must be an envelope: {"fetched_at": ISO UTC, "source": str,
"data": [...]}. A fresh catalog proves PRICE only - never quota health.
Health = a dated last-success; quota is unknown until an actual task
response. A same-day date is NOT proof a route works right now.

Cap classification (from the ACTUAL response, not assumption):
  cap-ambiguous       - generic 429 (rate window, concurrency, request
                        size): route cools down, provider NOT poisoned,
                        no retry hammering.
  cap-org-confirmed   - only with evidence naming the provider policy /
                        response that shows org-wide exhaustion: blocks
                        ALL routes of that provider. Never clears by
                        date guesses (no local-midnight reset); clears
                        only via a later successful call.

Authority model (owner's 2026-11-04 resource-fit grant): propose prints
DECISION only when ALL fit: exact id price-0 in a listing fetched <= 30
min ago with a named source; candidate working per record and fits the
job shape; route not cooling down; provider not org-blocked; task's
remaining attempts > 0; no new access. Anything else prints
COORDINATOR with the unresolved gap. DECISION = route selection only,
never credentialed execution.
"""
import json, sys, datetime

FRESH_LISTING_MAX_AGE_MIN = 30

def load(path):
    with open(path) as f:
        return json.load(f)

def listing_age_ok(listing):
    """Envelope freshness: fetched_at present, source named, fetched
    within FRESH_LISTING_MAX_AGE_MIN minutes (UTC ISO)."""
    try:
        if not listing.get("source"):
            return False
        ts = datetime.datetime.fromisoformat(
            listing["fetched_at"].replace("Z", "+00:00"))
        age = datetime.datetime.now(datetime.timezone.utc) - ts
        return age <= datetime.timedelta(minutes=FRESH_LISTING_MAX_AGE_MIN)
    except (KeyError, ValueError, TypeError):
        return False

def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def price_zero(listing, model_id):
    """True only if the EXACT id exists in the listing with input_price
    AND output_price present, numeric and 0 (cached_price, if present,
    also numeric 0). Missing or non-numeric pricing is UNKNOWN, never
    free. A prefixed variant never matches the bare id; a listed price-0
    id is still only a listing fact."""
    for m in listing.get("data", []):
        if m.get("id") == model_id:
            vals = [m.get("input_price"), m.get("output_price")]
            if "cached_price" in m:
                vals.append(m["cached_price"])
            return all(_num(v) and v == 0 for v in vals)
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
    rec.setdefault("provider_blocks", {})
    if result == "ok":
        r["status"] = "working"
        # a later success is the ONLY thing that clears an org block
        rec["provider_blocks"].pop(r["provider"], None)
    elif result == "cap-ambiguous":
        r["status"] = "cooldown"
    elif result == "cap-org-confirmed":
        r["status"] = "capped"
        rec["provider_blocks"][r["provider"]] = {
            "since": today, "evidence": evidence,
            "clears": "only via a later successful call (no date guesses)"}
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
    if listing is not None and not listing_age_ok(listing):
        listing = None
    blocks = rec.get("provider_blocks", {})
    fit, gaps = [], []
    for cid in cands:
        r = get_route(rec, cid)
        if r is None or r["status"] != "working":
            gaps.append(cid + ": not working per record"); continue
        if r["provider"] in blocks:
            gaps.append(cid + ": provider " + r["provider"]
                        + " org-capped since "
                        + blocks[r["provider"]]["since"]); continue
        if listing is None:
            gaps.append(cid + ": no fresh listing (envelope <= "
                        + str(FRESH_LISTING_MAX_AGE_MIN)
                        + "min with source); price unverified"); continue
        if not price_zero(listing, cid):
            gaps.append(cid + ": not price-0 in fresh listing"); continue
        fit.append(cid)
    if len(fit) == 1:
        r = get_route(rec, fit[0])
        print("DECISION use " + fit[0] + " for " + job_shape
              + " (replaces " + failed_route + "; within existing task"
              + " attempt cap; verified price-0 in fresh listing; no new"
              + " access. Last success: " + r.get("evidence", "unknown")
              + " - quota UNKNOWN until the actual call response)")
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
