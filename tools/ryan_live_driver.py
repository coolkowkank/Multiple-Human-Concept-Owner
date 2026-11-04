"""Operator driver used for the first live Ryan attempt (2026-11-04).
Reads the key from the vault-delivered file for this one run; never prints
it. Commands: listing-check | alloc | step. Delete the key file after use.
"""
import sys, os, json, time, urllib.request
sys.path.insert(0, "/tmp/teamdocs-wt/tools")
import ryan_cycle as rc
KEY = open("/home/sandbox/.vault/requesty-api-key-b02ae0/password").read().strip()
os.environ["REQUESTY_API_KEY"] = KEY
ROOT = "/tmp/teamdocs-wt/docs/team/ryan"
RECORD = json.load(open("/tmp/teamdocs-wt/docs/team/model-availability.json"))

now = time.time()

def listing():
    req = urllib.request.Request(rc.BASE_URL + "/models", headers={
        "authorization": "Bearer " + KEY, "user-agent": "team-launcher-ryan-cycle/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            d = json.loads(r.read())
    except Exception as e:  # class only: messages can echo request details
        raise rc.Halt("listing GET failed: " + type(e).__name__)
    env = {"fetched_at": rc.iso(now), "source": "requesty /v1/models GET",
           "data": d["data"]}
    return env

post = rc.http_post_factory()
cmd = sys.argv[1]
try:
    if cmd == "listing-check":
        L = listing()
        for mid in ("nvidia/nemotron-3-ultra-550b-a55b", "novita/ling-3.1-flash", "google/gemma-4-31b-it"):
            e = next((m for m in L["data"] if m["id"] == mid), None)
            print(mid, e and (e.get("input_price"), e.get("output_price"), e.get("cached_price"), e.get("model_lab")))
        print("price_zero:", {m: rc.mr.price_zero(L, m) for m in ("nvidia/nemotron-3-ultra-550b-a55b", "novita/ling-3.1-flash")})
    elif cmd == "alloc":
        print(json.dumps(rc.allocate(ROOT, post, listing, RECORD, now), indent=1))
    elif cmd == "step":
        print(json.dumps(rc.step(ROOT, post, listing, now, RECORD), indent=1))
except rc.Halt as e:
    print("HALT/PAUSED:", e)
st = rc.Store(ROOT)
led = st.ledger()
print("ledger:", [(e["phase"], e.get("role"), e.get("outcome"), e.get("model"), e.get("usage")) for e in led[-4:]])
print("reserves total:", sum(1 for e in led if e["phase"] == "reserved"))
