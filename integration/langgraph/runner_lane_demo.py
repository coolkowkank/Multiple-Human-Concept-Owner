"""Offline integration demo: the accepted Ryan guard chain runs INSIDE
the LangGraph orchestration, and the only call path is the refusing
post. Every scenario asserts ZERO network calls; fixtures are disposable
temp roots. Run: python runner_lane_demo.py"""
import json, os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import runner_lane as rl
import ryan_cycle as rc

T0 = 1_800_000_000.0
PACKET = [{"id": "P1", "title": "t", "passage": "alpha passage text here"},
          {"id": "P2", "title": "t", "passage": "beta passage text here"}]
FRESH = {"fetched_at": rc.iso(T0 - 60), "source": "fixture", "data": [
    {"id": "nvidia/nemotron-3-ultra-550b-a55b", "input_price": 0,
     "output_price": 0, "model_lab": "nvidia"},
    {"id": "google/gemma-4-31b-it", "input_price": 0,
     "output_price": 0, "model_lab": "google"}]}
RECORD = {"provider_blocks": {}, "routes": [
    {"id": "nvidia/nemotron-3-ultra-550b-a55b", "provider": "requesty",
     "status": "working"},
    {"id": "google/gemma-4-31b-it", "provider": "requesty",
     "status": "working"}]}
ASSIGN = {"models": {"researcher": "nvidia/nemotron-3-ultra-550b-a55b",
                     "verifier": "google/gemma-4-31b-it",
                     "ryan": "nvidia/nemotron-3-ultra-550b-a55b"},
          "why": {r: "fixture" for r in rc.ROLES}, "decided_by": "main"}
R_OK = {"findings": [{"id": "C1", "claim": "a", "sources": ["P1"],
                      "status": "SUPPORTED_BY_PACKET"}], "summary": "s"}
fails = []
_roots = []

def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name, flush=True)
    if not cond:
        fails.append(name)

def root_with(q, assign=ASSIGN):
    d = tempfile.mkdtemp()
    _roots.append(d)
    rc.Store(d).save_queue({"questions": [q]})
    if assign:
        with open(os.path.join(d, "assignments.json"), "w") as f:
            json.dump(assign, f)
    return d

# S1: durable provider halt blocks the step before anything else
d = root_with({"id": "q1", "status": "open", "attempts": {},
               "question": "?", "packet": PACKET})
rc.Store(d).append({"phase": "halt", "ts": rc.iso(T0 - 100),
                    "reason": "provider halt stands"})
r = rl.runner_step(d, FRESH, RECORD, now=T0, clock=lambda: T0)
check("S1 halt blocks step (Halt raised)", r["halted"] is not None)
check("S1 zero call attempts under halt", r["call_attempts"] == [])

# S2: gates pass -> refusing post records the attempt, reserve is
# consumed, runner halts on the unknown outcome. NO network.
d = root_with({"id": "q1", "status": "open", "attempts": {},
               "question": "?", "packet": PACKET})
r = rl.runner_step(d, FRESH, RECORD, now=T0, clock=lambda: T0)
led = rc.Store(d).ledger()
check("S2 gate-passing attempt was RECORDED by refusing post",
      len(r["call_attempts"]) == 1)
check("S2 unknown outcome halts (reserve consumed, no silent retry)",
      r["halted"] is not None and "unknown transport" in r["halted"])
check("S2 ledger shows reserve + unknown result + halt",
      [e["phase"] for e in led] == ["reserved", "result", "halt"]
      and led[1]["outcome"] == "unknown")

# S3: allowance-bound item, WRONG signature -> window denies, zero calls
kd = tempfile.mkdtemp()
kf = os.path.join(kd, "keyfile")
open(kf, "wb").write(b"demo-key-not-a-secret")
os.chmod(kf, 0o600)
os.environ["RYAN_ALLOWANCE_KEY_FILE"] = kf
d = root_with({"id": "q1", "status": "drafted", "lineage": "L",
               "findings": R_OK["findings"], "attempts":
               {"researcher": 1, "verifier": 2},
               "question": "?", "packet": PACKET})
store = rc.Store(d)
for i, role in enumerate(("researcher", "verifier", "verifier")):
    store.append({"phase": "reserved", "rid": "o%d" % i,
                  "ts": rc.iso(T0 - 9000 + i), "qid": "q1", "role": role,
                  "model": "m", "lineage": "L"})
    store.append({"phase": "result", "rid": "o%d" % i,
                  "ts": rc.iso(T0 - 9000 + i), "qid": "q1", "role": role,
                  "model": "m", "outcome": "ok"})
q = store.queue()["questions"][0]
body = {"version": 2, "id": "A1", "lineage": "L", "work_fp": rc.work_fp(q),
        "roles": ["verifier", "ryan"],
        "models": {"verifier": ASSIGN["models"]["verifier"],
                   "ryan": ASSIGN["models"]["ryan"]},
        "baseline": {"researcher": 1, "verifier": 2, "ryan": 0},
        "max_counts": {"verifier": 3, "ryan": 1}, "max_requests": 2,
        "issued_at": rc.iso(T0 - 60), "expires_at": rc.iso(T0 + 3600)}
with open(os.path.join(d, "allowance.json"), "w") as f:
    json.dump({"body": body, "sig": "deliberately-wrong"}, f)
r = rl.runner_step(d, FRESH, RECORD, now=T0, clock=lambda: T0)
check("S3 bad-signature window blocks before any call",
      r["call_attempts"] == [] and r["halted"] is None)
check("S3 item not acted (no result line added)",
      len([e for e in rc.Store(d).ledger() if e["rid"].startswith("r")])
      == 0)

# S4: verified item with STALE verified_rev -> Ryan needs-human, 0 calls
d = root_with({"id": "q1", "status": "verified", "lineage": "L",
               "findings": R_OK["findings"], "packet": PACKET,
               "verified_ids": ["C1"], "author_model": "m",
               "verified_rev": "stale-revision",
               "attempts": {"researcher": 1, "verifier": 1},
               "question": "?"})
r = rl.runner_step(d, FRESH, RECORD, now=T0, clock=lambda: T0)
check("S4 stale verified_rev -> needs-human",
      r["step"] is not None and r["step"].get("action") == "needs-human")
check("S4 zero call attempts on stale revision", r["call_attempts"] == [])

# G1/G2: the ACTUAL compiled LangGraph graph (not just runner_step)
# on isolated roots - the reviewer-accepted boundary.
d = root_with({"id": "q1", "status": "open", "attempts": {},
               "question": "?", "packet": PACKET})
rc.Store(d).append({"phase": "halt", "ts": rc.iso(T0 - 100),
                    "reason": "provider halt stands"})
app = rl.build_runner_graph(d, FRESH, RECORD, now=T0, clock=lambda: T0)
r = app.invoke({"results": []})["results"][0]
check("G1 graph: halt blocks step, zero attempts",
      r["halted"] is not None and r["call_attempts"] == [])

d = root_with({"id": "q1", "status": "open", "attempts": {},
               "question": "?", "packet": PACKET})
app = rl.build_runner_graph(d, FRESH, RECORD, now=T0, clock=lambda: T0)
r = app.invoke({"results": []})["results"][0]
led = rc.Store(d).ledger()
check("G2 graph: gate-pass -> 1 refusing attempt -> reserve,result,halt",
      len(r["call_attempts"]) == 1
      and [e["phase"] for e in led] == ["reserved", "result", "halt"]
      and led[1]["outcome"] == "unknown"
      and "unknown transport" in (r["halted"] or ""))
# No checkpointer on the runner graph: no resume claim, by design.

for d in _roots + [kd]:
    shutil.rmtree(d, ignore_errors=True)
print("\nRUNNER LANE INTEGRATION:", "ALL CHECKS PASSED" if not fails
      else "FAILURES ABOVE")
sys.exit(1 if fails else 0)
