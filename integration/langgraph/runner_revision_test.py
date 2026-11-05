"""Offline N3: verified -> Ryan revision binding and edit-between-calls
refusal, exercised on the pinned runner.ryan_cycle.step with a FAKE post
(a local function, no network, no key, no provider). Disposable temp roots.
Test-only, fake post, offline; asserts what the vendored step does today. Not a live qualification and not a quality review.
Limits: verified_rev is an UNKEYED digest (accident guard, not tamper
proof); this test records that limit as a check, it does not defend it."""
import copy, json, os, shutil, sys, tempfile
HERE = os.path.dirname(os.path.realpath(__file__)); sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "runner"))
import ryan_cycle as rc  # noqa: E402

T0 = 1_800_000_000.0
PACKET = [{"id": "P1", "title": "t", "passage": "alpha passage text here"},
          {"id": "P2", "title": "t", "passage": "beta passage text here"}]
FINDINGS = [{"id": "C1", "claim": "claim one", "sources": ["P1"], "status": "SUPPORTED_BY_PACKET"},
            {"id": "C2", "claim": "claim two SECRETMARK", "sources": [], "status": "UNVERIFIED"}]
R, V, Y = "nvidia/nemotron-3-ultra-550b-a55b", "google/gemma-4-31b-it", "nvidia/nemotron-3-ultra-550b-a55b"
LISTING = {"fetched_at": rc.iso(T0 - 60), "source": "fixture", "data": [
    {"id": R, "input_price": 0, "output_price": 0, "model_lab": "nvidia"},
    {"id": V, "input_price": 0, "output_price": 0, "model_lab": "google"}]}
RECORD = {"provider_blocks": {}, "routes": [{"id": R, "provider": "requesty", "status": "working"},
                                              {"id": V, "provider": "requesty", "status": "working"}]}
ASSIGN = {"models": {"researcher": R, "verifier": V, "ryan": Y}, "why": {r: "fixture" for r in rc.ROLES}, "decided_by": "main"}
VERDICT = {"verdicts": [{"id": "C1", "verdict": "SUPPORTED", "source": "P1", "quote": "alpha passage text", "evidence": "e"},
                        {"id": "C2", "verdict": "UNVERIFIED", "source": "P1", "quote": "", "evidence": "e"}]}
RYAN_OK = {"usefulness": [{"id": "C1", "useful": "LOW", "why": "w", "proposed_action": "a"}], "note": "n"}
ok = True
def check(n, c):
    global ok; ok = ok and bool(c); print(("PASS  " if c else "FAIL  ") + n, flush=True)

class Fake:
    """Local fake post; records every call; optional hook runs mid-call."""
    def __init__(self, content, hook=None): self.calls, self.content, self.hook = [], content, hook
    def __call__(self, model, system, prompt, max_tokens, effort=None):
        self.calls.append({"model": model, "prompt": prompt})
        if self.hook: self.hook()
        return {"kind": "ok", "code": 200, "content": json.dumps(self.content), "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

tmps = []
def new_root(status="drafted", extra=None):
    d = tempfile.mkdtemp(); tmps.append(d)
    q = {"id": "q1", "status": status, "lineage": "L", "question": "?", "packet": copy.deepcopy(PACKET),
         "findings": copy.deepcopy(FINDINGS), "author_model": R, "attempts": {"researcher": 1}}
    q.update(extra or {})
    rc.Store(d).save_queue({"questions": [q]})
    json.dump(ASSIGN, open(os.path.join(d, "assignments.json"), "w"))
    return d
_clk = {}
def run(d, post, before_io=None):
    t = _clk[d] = _clk.get(d, T0) + 100   # past the runner's 10 s spacing between calls
    return rc.step(d, post, lambda: LISTING, t, RECORD, clock=lambda: t, before_io=before_io)
def q_of(d): return rc.Store(d).queue()["questions"][0]
def edit(d, fn):
    st = rc.Store(d); qu = st.queue(); fn(qu["questions"][0]); st.save_queue(qu)
def verified_root():
    d = new_root(); fv = Fake(VERDICT); r = run(d, fv)
    assert r["status"] == "verified" and q_of(d).get("verified_rev"), r
    return d

# A: clean path, Ryan sees only verified findings
d = verified_root(); q = q_of(d)
check("A verifier PASS stores verified_ids=[C1] and a revision bound to the current item", q["verified_ids"] == ["C1"] and rc.verified_rev_ok(q))
fy = Fake(RYAN_OK); r = run(d, fy)
check("A unchanged item: Ryan runs exactly once and reaches ready-for-chain", len(fy.calls) == 1 and r["status"] == "ready-for-chain")
check("A Ryan prompt carries the verified finding and not the unverified one", "claim one" in fy.calls[0]["prompt"] and "SECRETMARK" not in fy.calls[0]["prompt"])

# B: edits after the verifier PASS and before Ryan: refused, zero calls, item to needs-human
def refused(name, fn):
    d = verified_root(); edit(d, fn); fy = Fake(RYAN_OK); n0 = len(rc.Store(d).ledger())
    r = run(d, fy); q = q_of(d)
    check("B %s: refused, 0 calls, needs-human, no ledger line" % name,
          fy.calls == [] and r["action"] == "needs-human" and q["status"] == "needs-human" and len(rc.Store(d).ledger()) == n0
          and "re-verify" in q.get("reason", "") and "ryan_review" not in q)
refused("finding text edited", lambda q: q["findings"][0].update(claim="edited claim"))
refused("packet passage edited", lambda q: q["packet"][0].update(passage="changed passage text"))
refused("unverified id added to verified_ids", lambda q: q["verified_ids"].append("C2"))
refused("author_model changed", lambda q: q.update(author_model=V))
refused("lineage changed", lambda q: q.update(lineage="other"))
refused("question edited", lambda q: q.update(question="a different question"))
refused("verified_rev removed", lambda q: q.pop("verified_rev"))
refused("status forced to verified without a PASS revision", lambda q: (q.update(status="verified"), q.pop("verified_rev", None)))
# transplant: a revision from another item cannot be reused
d1 = verified_root(); rev1 = q_of(d1)["verified_rev"]
d2 = verified_root(); edit(d2, lambda q: (q.update(id="q1", lineage="L2"), q.update(verified_rev=rev1)))
f2 = Fake(RYAN_OK); run(d2, f2)
check("B different lineage plus a pasted revision is refused (a lineage edit, not an independent second item)", f2.calls == [] and q_of(d2)["status"] == "needs-human")

# C: edit during the Ryan call: result not applied, durable halt, call stays consumed
d = verified_root()
fy = Fake(RYAN_OK, hook=lambda: edit(d, lambda q: q["findings"][0].update(claim="mid-call edit")))
try: run(d, fy); halted = False
except rc.Halt: halted = True
q = q_of(d); led = rc.Store(d).ledger()
check("C edit during Ryan call: stale result not applied, no ready-for-chain", len(fy.calls) == 1 and "ryan_review" not in q and q["status"] != "ready-for-chain")
check("C a halt line stands and the reserve stays consumed", led[-1]["phase"] == "halt" and "stale result" in led[-1]["reason"] and sum(1 for e in led if e["phase"] == "reserved" and e["role"] == "ryan") == 1)
nxt = run(d, Fake(RYAN_OK)); check("C runner halted: no further call (runner-wide halt; not an item-level rerun claim)", nxt["action"] in ("wait", "needs-human") or nxt.get("calls", 0) == 0)

# D: edit during the verifier call: no verified marker is written
d = new_root(); fv = Fake(VERDICT, hook=lambda: edit(d, lambda q: q["findings"][0].update(claim="mid-call edit")))
r = run(d, fv); q = q_of(d)
check("D edit during verifier call: not verified, no verified_rev, no verified_ids", r["action"] == "stale-result-halt" and q["status"] != "verified" and "verified_rev" not in q and not q.get("verified_ids"))

# E: documented limit - the digest is unkeyed
d = verified_root(); edit(d, lambda q: (q["findings"][0].update(claim="forged"), q.update(verified_rev=rc.verified_rev(q))))
fy = Fake(RYAN_OK); run(d, fy)
check("E LIMIT: an editor who recomputes the unkeyed digest passes the check (accident guard only, not authentication)", len(fy.calls) == 1)
for t in tmps: shutil.rmtree(t, ignore_errors=True)
print("ALL PASS" if ok else "SOME FAIL"); sys.exit(0 if ok else 1)
