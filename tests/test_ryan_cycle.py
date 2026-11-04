import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import ryan_cycle as rc

T0 = 1_800_000_000.0
FRESH = lambda: {"fetched_at": rc.iso(T0 - 60), "source": "mock /v1/models",
                 "data": [
    {"id": "nvidia/nemotron-3-ultra-550b-a55b", "input_price": 0,
     "output_price": 0},
    {"id": "google/gemma-4-31b-it", "input_price": 0, "output_price": 0},
    {"id": "paid/model", "input_price": 1, "output_price": 1}]}
PACKET = [{"id": "P1", "title": "t", "passage": "alpha passage text here"},
          {"id": "P2", "title": "t", "passage": "beta passage text here"}]
RECORD = {"provider_blocks": {}, "routes": [
    {"id": "nvidia/nemotron-3-ultra-550b-a55b", "provider": "requesty",
     "status": "working"},
    {"id": "google/gemma-4-31b-it", "provider": "requesty",
     "status": "working"}]}
ASSIGN = {"models": {"researcher": "nvidia/nemotron-3-ultra-550b-a55b",
                     "verifier": "google/gemma-4-31b-it",
                     "ryan": "nvidia/nemotron-3-ultra-550b-a55b"},
          "why": {r: "route already recorded working" for r in rc.ROLES}}


def ok(obj, usage=None):
    return {"kind": "ok", "content": json.dumps(obj),
            "usage": usage or {"total_tokens": 10}}


R_OK = {"findings": [{"id": "C1", "claim": "a", "sources": ["P1"],
                      "status": "SUPPORTED_BY_PACKET"}], "summary": "s"}
V_OK = {"verdicts": [{"id": "C1", "verdict": "SUPPORTED", "source": "P1",
                      "quote": "alpha passage text", "evidence": "e"}],
        "overall": "PASS"}
Y_OK = {"usefulness": [{"id": "C1", "useful": "HIGH", "why": "w",
                        "proposed_action": "p"}], "note": "n"}


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.calls = []
        self.t = T0
        self.store = rc.Store(self.d)

    def seed(self, assign=ASSIGN, qid="q1"):
        self.store.save_queue({"questions": [{
            "id": qid, "status": "open", "attempts": {}, "question": "?",
            "packet": PACKET}]})
        if assign:
            with open(os.path.join(self.d, "assignments.json"), "w") as f:
                json.dump(assign, f)

    def run_step(self, replies, listing=FRESH, record=None):
        it = iter(replies)

        def post(model, system, prompt, mt):
            self.calls.append((model, prompt))
            return next(it)
        self.t += 20
        return rc.step(self.d, post, listing, self.t, record or RECORD)


class Pipeline(Base):
    def test_clean_cycle_three_calls_in_order(self):
        self.seed()
        self.assertEqual(self.run_step([ok(R_OK)])["action"], "done-researcher")
        self.assertEqual(self.run_step([ok(V_OK)])["action"], "done-verifier")
        self.assertEqual(self.run_step([ok(Y_OK)])["action"], "done-ryan")
        q = self.store.queue()["questions"][0]
        self.assertEqual(q["status"], "ready-for-chain")
        self.assertEqual([c[0] for c in self.calls], [
            ASSIGN["models"]["researcher"], ASSIGN["models"]["verifier"],
            ASSIGN["models"]["ryan"]])
        self.assertEqual(self.run_step([])["action"], "idle")
        self.assertEqual(len([e for e in self.store.ledger()
                              if e["phase"] == "reserved"]), 3)

    def test_idle_makes_no_listing_fetch_and_no_call(self):
        self.store.save_queue({"questions": []})
        fetched = []
        out = rc.step(self.d, lambda *a: 1 / 0,
                      lambda: fetched.append(1), T0, RECORD)
        self.assertEqual((out["action"], out["calls"], fetched),
                         ("idle", 0, []))

    def test_fabricated_source_blocks_verifier_spend(self):
        self.seed()
        bad = {"findings": [{"id": "C1", "claim": "a", "sources": ["P9"],
                             "status": "SUPPORTED_BY_PACKET"}]}
        out = self.run_step([ok(bad)])
        self.assertEqual(out["action"], "precheck-failed")
        self.assertEqual(len(self.calls), 1)
        out = self.run_step([ok(bad)])
        self.assertEqual(self.store.queue()["questions"][0]["status"],
                         "needs-human")

    def test_verifier_fail_returns_to_researcher_before_ryan(self):
        self.seed()
        self.run_step([ok(R_OK)])
        v = {"verdicts": [{"id": "C1", "verdict": "NOT_SUPPORTED",
                           "evidence": "x"}], "overall": "PASS"}  # lie
        self.run_step([ok(v)])
        q = self.store.queue()["questions"][0]
        self.assertEqual(q["status"], "open")           # not verified
        self.assertEqual(q["verifier_verdict"]["overall"], "FAIL")
        self.assertIn("C1", q["feedback"])
        self.run_step([ok(R_OK)])
        self.run_step([ok(V_OK)])
        self.assertEqual(self.store.queue()["questions"][0]["status"],
                         "verified")
        # researcher 2 + verifier 2 + (ryan not yet) <= 6 per question
        self.assertEqual(self.store.queue()["questions"][0]["attempts"],
                         {"researcher": 2, "verifier": 2})

    def test_second_failure_goes_to_human_not_ryan(self):
        self.seed()
        bad = {"verdicts": [{"id": "C1", "verdict": "NOT_SUPPORTED",
                             "evidence": "x"}]}
        for r in (R_OK, bad, R_OK, bad):
            self.run_step([ok(r)])
        q = self.store.queue()["questions"][0]
        self.assertEqual(q["status"], "needs-human")
        self.assertEqual(self.run_step([])["action"], "idle")

    def test_ryan_only_sees_verified_claims(self):
        self.seed()
        r = {"findings": [
            {"id": "C1", "claim": "good", "sources": ["P1"],
             "status": "SUPPORTED_BY_PACKET"},
            {"id": "C2", "claim": "unknownbit", "sources": [],
             "status": "UNVERIFIED"}]}
        v = {"verdicts": [{"id": "C1", "verdict": "SUPPORTED",
                           "source": "P1", "quote": "alpha passage text",
                           "evidence": "e"},
                          {"id": "C2", "verdict": "UNVERIFIED",
                           "evidence": "e"}]}
        self.run_step([ok(r)])
        self.run_step([ok(v)])
        self.run_step([ok(Y_OK)])
        self.assertNotIn("unknownbit", self.calls[-1][1])
        self.assertIn("good", self.calls[-1][1])


class Safety(Base):
    def test_no_assignments_means_needs_allocation_zero_calls(self):
        self.seed(assign=None)
        out = self.run_step([])
        self.assertEqual((out["action"], out["calls"]),
                         ("needs-allocation", 0))
        self.assertEqual(self.calls, [])

    def test_same_family_verifier_halts(self):
        bad = json.loads(json.dumps(ASSIGN))
        bad["models"]["verifier"] = "nvidia/other"
        self.seed(assign=bad)
        self.run_step([ok(R_OK)])
        with self.assertRaises(rc.Halt):
            self.run_step([])

    def test_stale_or_paid_listing_refuses_before_any_call(self):
        self.seed()
        stale = lambda: dict(FRESH(), fetched_at=rc.iso(T0 - 7200))
        with self.assertRaises(rc.Halt):
            self.run_step([], listing=stale)
        paid = json.loads(json.dumps(ASSIGN))
        paid["models"]["researcher"] = "paid/model"
        self.seed(assign=paid)
        rec = dict(RECORD, routes=RECORD["routes"] + [
            {"id": "paid/model", "provider": "x", "status": "working"}])
        with self.assertRaises(rc.Halt):
            self.run_step([], record=rec)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.store.ledger(), [])

    def test_429_pauses_and_no_call_until_cleared(self):
        self.seed()
        with self.assertRaises(rc.Halt):
            self.run_step([{"kind": "http", "code": 429, "usage": None,
                            "content": "x"}])
        self.t += 7200
        with self.assertRaises(rc.Halt):
            self.run_step([ok(R_OK)])           # time alone does not clear
        self.assertEqual(len(self.calls), 1)
        with self.assertRaises(ValueError):
            rc.clear(self.d, "ok", self.t)
        rc.clear(self.d, "console shows the org window reset", self.t)
        fresh_now = lambda: dict(FRESH(), fetched_at=rc.iso(self.t))
        self.assertEqual(self.run_step([ok(R_OK)], listing=fresh_now)["action"],
                         "done-researcher")

    def test_unknown_outcome_halts_and_counts_consumed(self):
        self.seed()
        with self.assertRaises(rc.Halt):
            self.run_step([{"kind": "unknown", "usage": None,
                            "content": ""}])
        led = self.store.ledger()
        self.assertEqual([e["phase"] for e in led],
                         ["reserved", "result", "halt"])
        self.assertEqual(led[1]["outcome"], "unknown")

    def test_dangling_reserve_halts(self):
        self.seed()
        self.store.append({"phase": "reserved", "rid": "r", "ts":
                           rc.iso(T0), "qid": "q1", "role": "researcher",
                           "model": "m"})
        with self.assertRaises(rc.Halt):
            self.run_step([])

    def test_nonzero_cost_halts(self):
        self.seed()
        with self.assertRaises(rc.Halt):
            self.run_step([ok(R_OK, usage={"cost": 0.01})])

    def test_auth_error_halts(self):
        self.seed()
        with self.assertRaises(rc.Halt):
            self.run_step([{"kind": "http", "code": 401, "usage": None,
                            "content": ""}])

    def test_daily_cap_and_cycle_cap(self):
        self.seed()
        for i in range(rc.DAILY_CAP):
            self.store.append({"phase": "reserved", "rid": "x%d" % i,
                               "ts": rc.iso(T0 - 100), "qid": "q%d" % (i % 4),
                               "role": "researcher", "model": "m"})
            self.store.append({"phase": "result", "rid": "x%d" % i,
                               "ts": rc.iso(T0 - 100), "outcome": "ok"})
        out = self.run_step([])
        self.assertEqual((out["action"], out["calls"]), ("wait", 0))
        self.assertIn("daily cap", out["reason"])

    def test_four_cycles_per_day(self):
        self.seed(qid="q9")
        for i in range(4):
            self.store.append({"phase": "reserved", "rid": "y%d" % i,
                               "ts": rc.iso(T0 - 100), "qid": "o%d" % i,
                               "role": "researcher", "model": "m"})
            self.store.append({"phase": "result", "rid": "y%d" % i,
                               "ts": rc.iso(T0 - 100), "outcome": "ok"})
        out = self.run_step([])
        self.assertEqual(out["action"], "wait")
        self.assertIn("cycles", out["reason"])

    def test_spacing(self):
        self.seed()
        self.run_step([ok(R_OK)])
        out = rc.step(self.d, lambda *a: 1 / 0, FRESH, self.t + 2, RECORD)
        self.assertEqual(out["action"], "wait")

    def test_oversize_input_refused(self):
        self.store.save_queue({"questions": [{
            "id": "q1", "status": "open", "attempts": {}, "question": "?",
            "packet": [{"id": "P1", "title": "t",
                        "passage": "x" * 20000}]}]})
        with open(os.path.join(self.d, "assignments.json"), "w") as f:
            json.dump(ASSIGN, f)
        out = self.run_step([])
        self.assertEqual(out["action"], "needs-human")
        self.assertEqual(self.calls, [])


class Allocation(Base):
    ALLOC = ASSIGN

    def test_valid_choice_saved_and_counts_in_cap(self):
        rec = RECORD
        out = rc.allocate(self.d, lambda *a: ok(self.ALLOC), FRESH, rec,
                          T0 + 20)
        self.assertEqual(out["action"], "assigned")
        with open(os.path.join(self.d, "assignments.json")) as f:
            self.assertEqual(json.load(f)["decided_by"], "ryan")
        self.assertEqual(len([e for e in self.store.ledger()
                              if e["phase"] == "reserved"]), 1)

    def test_invalid_choices_rejected_not_saved(self):
        rec = {"routes": [RECORD["routes"][0], {
            "id": "google/gemma-4-31b-it", "provider": "requesty",
            "status": "cooldown"}], "provider_blocks": {}}
        cases = []
        same = json.loads(json.dumps(ASSIGN))
        same["models"]["verifier"] = "nvidia/nemotron-3-ultra-550b-a55b"
        cases.append((same, RECORD))
        cases.append((ASSIGN, rec))                     # verifier cooldown
        paid = json.loads(json.dumps(ASSIGN))
        paid["models"]["ryan"] = "paid/model"
        cases.append((paid, RECORD))
        nojust = json.loads(json.dumps(ASSIGN)); nojust["why"]["ryan"] = ""
        cases.append((nojust, RECORD))
        for i, (a, r) in enumerate(cases):
            out = rc.allocate(self.d, lambda *x, a=a: ok(a), FRESH, r,
                              T0 + 20 + 30 * i)
            self.assertEqual(out["action"], "rejected", i)
        self.assertFalse(os.path.exists(os.path.join(
            self.d, "assignments.json")))


class Review2(Base):
    def test_missing_or_partial_prices_are_unknown_not_free(self):
        for item in ({"id": "m", "output_price": 0},
                     {"id": "m"},
                     {"id": "m", "input_price": None, "output_price": 0},
                     {"id": "m", "input_price": "0", "output_price": 0},
                     {"id": "m", "input_price": 0, "output_price": 0,
                      "cached_price": None}):
            self.assertFalse(rc.mr.price_zero({"data": [item]}, "m"), item)
        self.assertTrue(rc.mr.price_zero({"data": [
            {"id": "m", "input_price": 0, "output_price": 0}]}, "m"))

    def test_unrecorded_route_is_unknown_for_assignment(self):
        rec = {"provider_blocks": {}, "routes": [
            {"id": "nvidia/nemotron-3-ultra-550b", "provider": "requesty",
             "status": "working"}] + RECORD["routes"][1:]}
        bad = rc.validate_assignments(ASSIGN, rec, FRESH(), T0)
        self.assertIn("no route record", bad)

    def test_bootstrap_uses_same_availability_gate(self):
        for rec in ({"routes": [], "provider_blocks": {}},
                    {"routes": [dict(RECORD["routes"][0], status="capped")],
                     "provider_blocks": {}},
                    {"routes": RECORD["routes"],
                     "provider_blocks": {"requesty": {}}}):
            out = rc.allocate(self.d, lambda *a: 1 / 0, FRESH, rec, T0 + 20)
            self.assertEqual((out["action"], out["calls"]),
                             ("needs-human", 0))
        self.assertEqual(self.store.ledger(), [])

    def test_step_refuses_blocked_route_record(self):
        self.seed()
        rec = {"routes": [dict(RECORD["routes"][0], status="cooldown")],
               "provider_blocks": {}}
        out = self.run_step([], record=rec)
        self.assertEqual((out["action"], out["calls"]), ("needs-human", 0))

    def test_concurrent_steps_never_exceed_cap(self):
        import threading
        self.seed()
        for i in range(rc.DAILY_CAP - 1):
            self.store.append({"phase": "reserved", "rid": "x%d" % i,
                               "ts": rc.iso(T0 - 100), "qid": "q%d" % (i % 3),
                               "role": "researcher", "model": "m"})
            self.store.append({"phase": "result", "rid": "x%d" % i,
                               "ts": rc.iso(T0 - 100), "outcome": "ok"})
        outs, errs = [], []

        def go():
            try:
                outs.append(rc.step(self.d, lambda *a: ok(R_OK), FRESH,
                                    T0 + 20, RECORD)["action"])
            except rc.Halt as e:
                errs.append(str(e))
        ts = [threading.Thread(target=go) for _ in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        n = len([e for e in self.store.ledger() if e["phase"] == "reserved"])
        self.assertLessEqual(n, rc.DAILY_CAP)

    def test_reserve_is_atomic_gate_plus_append(self):
        for i in range(rc.DAILY_CAP - 1):
            self.store.append({"phase": "reserved", "rid": "x%d" % i,
                               "ts": rc.iso(T0 - 100), "qid": "q%d" % (i % 3),
                               "role": "researcher", "model": "m"})
            self.store.append({"phase": "result", "rid": "x%d" % i,
                               "ts": rc.iso(T0 - 100), "outcome": "ok"})
        a = rc.Store(self.d).reserve(T0, {"phase": "reserved", "rid": "a",
            "ts": rc.iso(T0), "qid": "q0", "role": "r", "model": "m"}, "q0")
        self.assertEqual(a[0], "ok")
        self.store.append({"phase": "result", "rid": "a", "ts": rc.iso(T0),
                           "outcome": "ok"})
        b = rc.Store(self.d).reserve(T0 + 20, {"phase": "reserved",
            "rid": "b", "ts": rc.iso(T0 + 20), "qid": "q1", "role": "r",
            "model": "m"}, "q1")
        self.assertEqual(b[0], "wait")

    def test_fabricated_or_wrong_source_quote_is_not_verified(self):
        for v in ({"source": "P1", "quote": "this never appears anywhere"},
                  {"source": "P2", "quote": "beta passage text"},
                  {"source": "P1", "quote": ""}):
            self.setUp()
            self.seed()
            self.run_step([ok(R_OK)])
            row = dict({"id": "C1", "verdict": "SUPPORTED",
                        "evidence": "e"}, **v)
            out = self.run_step([ok({"verdicts": [row]})])
            self.assertEqual(out["action"], "precheck-failed", v)
            self.assertEqual(self.store.queue()["questions"][0]["status"],
                             "drafted")

    def test_verifier_and_ryan_retry_carry_feedback(self):
        self.seed()
        self.run_step([ok(R_OK)])
        self.run_step([ok({"verdicts": "bad"})])
        self.run_step([ok(V_OK)])
        self.assertIn("rejected", self.calls[2][1])
        self.run_step([ok({"usefulness": [{"id": "ZZ", "useful": "HIGH"}]})])
        self.run_step([ok(Y_OK)])
        self.assertIn("rejected", self.calls[-1][1])

    def test_same_second_halt_after_clear_pauses(self):
        s = self.store
        s.append({"phase": "halt", "ts": rc.iso(T0), "reason": "x"})
        s.append({"phase": "cleared", "ts": rc.iso(T0), "note": "console ok x"})
        self.assertEqual(rc.ledger_gate(s, T0 + 20)[0], "ok")
        s.append({"phase": "halt", "ts": rc.iso(T0), "reason": "y"})
        with self.assertRaises(rc.Halt):
            rc.ledger_gate(s, T0 + 20)

    def test_allocation_takes_one_of_four_slots(self):
        self.seed(qid="qNEW")
        for i, qid in enumerate(["alloc", "o1", "o2", "o3"]):
            self.store.append({"phase": "reserved", "rid": "r%d" % i,
                               "ts": rc.iso(T0 - 100), "qid": qid,
                               "role": "researcher", "model": "m"})
            self.store.append({"phase": "result", "rid": "r%d" % i,
                               "ts": rc.iso(T0 - 100), "outcome": "ok"})
        self.assertEqual(self.run_step([])["action"], "wait")


class JobDesc(unittest.TestCase):
    def mk(self, extra=""):
        repo = tempfile.mkdtemp()
        os.makedirs(os.path.join(repo, "docs/team/blueprints"))
        rep = ("Every claim carries its source pin and unknowns are "
               "reported as unknowns before anything is published here. ")
        for n in ("a", "b"):
            with open(os.path.join(repo, "docs/team/blueprints/%s.md" % n),
                      "w") as f:
                f.write("# %s\n%s\n%s\n" % (n, rep, extra))
        with open(os.path.join(repo, "docs/team/registry.md"), "w") as f:
            f.write("r\n")
        return repo

    def test_change_driven_and_zero_calls(self):
        repo, root = self.mk(), tempfile.mkdtemp()
        out = rc.jobdesc_scan(repo, root, T0)
        self.assertEqual((out["action"], out["calls"]), ("enqueued", 0))
        q = rc.Store(root).queue()["questions"][0]
        self.assertEqual(q["kind"], "jobdesc-efficiency")
        self.assertTrue(q["packet"][0]["title"].startswith("repeated"))
        self.assertEqual(rc.jobdesc_scan(repo, root, T0 + 5)["action"],
                         "unchanged")
        self.assertEqual(len(rc.Store(root).queue()["questions"]), 1)
        with open(os.path.join(repo, "docs/team/registry.md"), "w") as f:
            f.write("new\n")
        self.assertNotEqual(rc.jobdesc_scan(repo, root, T0 + 9)["action"],
                            "unchanged")

    def test_measurement_is_labelled_heuristic(self):
        repo, root = self.mk(), tempfile.mkdtemp()
        rc.jobdesc_scan(repo, root, T0)
        with open(os.path.join(root, "jobdesc-state.json")) as f:
            st = json.load(f)
        self.assertIn("chars_div4_heuristic_not_tokens", st)
        self.assertNotIn("tokens", st)


if __name__ == "__main__":
    unittest.main()
