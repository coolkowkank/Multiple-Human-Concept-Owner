"""Build a signed allowance window for ONE queue item (bookkeeping only).

    python3 tools/make_allowance.py ROOT QID ID TTL_MIN VERIFIER_MODEL [RYAN_MODEL]

Reads the CURRENT queue and ledger for the item's lineage, claim-set
fingerprint and pinned baseline, validates the body with the runner's own
_shape_ok(), signs it with the key named by RYAN_ALLOWANCE_KEY_FILE (the
runner's key location rules apply) and writes ROOT/allowance.json. It
makes no network call and prints no key. It refuses when the item is not
at the Verifier step, the TTL exceeds the runner maximum, or an
allowance-bind for the lineage already exists (a bound window is never
replaced).
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ryan_cycle as rc  # noqa: E402


def build(root, qid, aid, ttl_min, verifier, ryan=None, now=None):
    now = time.time() if now is None else now
    store = rc.Store(root)
    queue = store.queue()
    q = next((x for x in queue["questions"] if x["id"] == qid), None)
    if q is None:
        raise SystemExit("no such queue item")
    if rc.next_action(q) != "verifier":
        raise SystemExit("item is not at the Verifier step")
    L, fp = rc.lineage_of(q), rc.work_fp(q)
    led = store.ledger()
    binds = [e for e in led if e.get("phase") == "allowance-bind"
             and (e.get("lineage") == L or e.get("work_fp") == fp)]
    succeeds = None
    if binds:   # a bound window is never replaced; only SUCCEEDED
        last = binds[-1]
        if not any(e.get("phase") == "allowance-stop"
                   and e.get("allowance") == last.get("allowance")
                   for e in led):
            raise SystemExit("a window is already bound and not terminal")
        if any(e.get("phase") == "allowance-bind"
               and e.get("allowance") == aid for e in led):
            raise SystemExit("successor needs a new window id")
        succeeds = {"id": last["allowance"], "digest": last["digest"]}
    if not (isinstance(ttl_min, int) and 0 < ttl_min * 60
            <= rc.ALLOWANCE_MAX_TTL_S):
        raise SystemExit("ttl out of range")
    used = rc.lineage_counts(store, queue, q)
    base = {r: used.get(r, 0) for r in rc.ROLE_CAP}
    roles = ["verifier"] + (["ryan"] if ryan else [])
    models = {"verifier": verifier}
    if ryan:
        models["ryan"] = ryan
    body = {"version": 2, "id": aid, "lineage": L, "work_fp": fp,
            "roles": roles, "models": models, "baseline": base,
            "max_counts": {r: base[r] + 1 for r in roles},
            "max_requests": len(roles),
            "issued_at": rc.iso(now),
            "expires_at": rc.iso(now + ttl_min * 60)}
    if succeeds:
        if ryan:   # one verifier step then one ryan step; ryan's model
            # must be the operator assignment's ryan model
            a = rc.load_assignments(root)
            if not a or a.get("models", {}).get("ryan") != ryan:
                raise SystemExit("ryan model is not the assignments.json "
                                 "ryan model")
        body["succeeds"] = succeeds
        bound = {e.get("allowance") for e in led
                 if e.get("phase") == "allowance-bind"}
        prior = {e.get("model") for e in led if e.get("phase") == "reserved"
                 and e.get("allowance") in bound}
        if verifier in prior:
            raise SystemExit("successor must pin a different model")
    if succeeds:   # the runtime's own validator, before anything is signed
        why = rc._succession_reason(led, "ok", body, binds[-1], L, fp)
        if why:
            raise SystemExit("not a valid successor: " + why)
    bad = rc._shape_ok(body, succession_ok=bool(succeeds))
    if bad:
        raise SystemExit("body invalid: " + bad)
    key, why = rc._allowance_key()
    if key is None:
        raise SystemExit("key unusable: " + why)
    return {"body": body, "sig": rc.allowance_sign(key, body)}


def main(argv):
    if len(argv) not in (6, 7):
        print(__doc__)
        return 2
    doc = build(argv[1], argv[2], argv[3], int(argv[4]), argv[5],
                argv[6] if len(argv) == 7 else None)
    with open(os.path.join(argv[1], "allowance.json"), "w") as f:
        json.dump(doc, f, indent=1)
    print("wrote allowance %s digest %s" % (
        doc["body"]["id"], rc.grant_digest(doc["body"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
