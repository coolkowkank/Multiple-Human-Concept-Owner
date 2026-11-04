import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import ryan_cycle as rc

T0 = 1_800_000_000.0
FRESH = lambda: {"fetched_at": rc.iso(T0 - 60), "source": "mock /v1/models",
                 "data": [
    {"id": "nvidia/nemotron-3-ultra-550b-a55b", "input_price": 0,
     "output_price": 0, "model_lab": "nvidia"},
    {"id": "google/gemma-4-31b-it", "input_price": 0, "output_price": 0,
     "model_lab": "google"},
    {"id": "novita/ling", "input_price": 0, "output_price": 0,
     "model_lab": "inclusionAI"},
    {"id": "deepinfra/google/gemma-4-31B-it", "input_price": 0,
     "output_price": 0, "model_lab": "Google"},
    {"id": "nvidia/other", "input_price": 0, "output_price": 0,
     "model_lab": "nvidia"},
    {"id": "nolab/model", "input_price": 0, "output_price": 0},
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
          "why": {r: "route already recorded working" for r in rc.ROLES},
          "decided_by": "main"}


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
        self.efforts = []
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

        def post(model, system, prompt, mt, effort=None):
            self.efforts.append(effort)
            self.calls.append((model, prompt))
            return next(it)
        self.t += 20
        return rc.step(self.d, post, listing, self.t, record or RECORD)


class Pipeline(Base):
    def test_per_role_effort_and_ceilings(self):
        self.assertEqual(rc.EFFORT, {"researcher": "low", "verifier": "none",
                                     "ryan": "low"})
        self.assertEqual(rc.CEILINGS, {"researcher": 2048, "verifier": 1536,
                                       "ryan": 2048})

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
        self.assertEqual(self.efforts, ["low", "none", "low"])
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
        rec = dict(RECORD, routes=RECORD["routes"] + [
            {"id": "nvidia/other", "provider": "requesty",
             "status": "working"}])
        self.seed(assign=bad)
        self.run_step([ok(R_OK)], record=rec)
        with self.assertRaises(rc.Halt):
            self.run_step([], record=rec)

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


class ManualAssign(Base):
    SRC = "operator decision 2026-11-04 test"

    def go(self, models, why=None, record=RECORD, listing=FRESH, src=None):
        return rc.assign_manual(
            self.d, models, why or ASSIGN["why"], listing(), record,
            T0 + 20, self.SRC if src is None else src)

    def test_valid_manual_assignment_saved_with_no_call_no_ledger(self):
        out = self.go(ASSIGN["models"])
        self.assertEqual((out["action"], out["calls"]), ("assigned", 0))
        with open(os.path.join(self.d, "assignments.json")) as f:
            a = json.load(f)
        self.assertEqual(a["decided_by"], "main")
        self.assertEqual(a["source_ref"], self.SRC)
        self.assertEqual(self.store.ledger(), [])

    def test_same_gates_reject_bad_manual_choices(self):
        m = ASSIGN["models"]
        rec_cool = {"routes": [RECORD["routes"][0], dict(
            RECORD["routes"][1], status="cooldown")], "provider_blocks": {}}
        cases = [
            (dict(m, verifier=m["researcher"]), RECORD),          # same id
            (dict(m, verifier="nvidia/other"), RECORD),           # same lab
            (m, rec_cool),                                        # cooldown
            (dict(m, ryan="paid/model"), RECORD),                 # paid
            (dict(m, verifier="nolab/model"), RECORD),            # no lab
        ]
        for i, (mm, rec) in enumerate(cases):
            self.assertEqual(self.go(mm, record=rec)["action"], "rejected", i)
        stale = lambda: dict(FRESH(), fetched_at=rc.iso(T0 - 7200))
        self.assertEqual(self.go(m, listing=stale)["action"], "rejected")
        self.assertEqual(self.go(m, src="x")["action"], "rejected")
        self.assertFalse(os.path.exists(os.path.join(
            self.d, "assignments.json")))

    def test_allocate_is_disabled_and_makes_no_request(self):
        out = rc.allocate(self.d, lambda *a: 1 / 0, FRESH, RECORD, T0)
        self.assertEqual((out["action"], out["calls"]), ("disabled", 0))
        self.assertEqual(self.store.ledger(), [])

    def test_step_refuses_assignment_not_made_by_operator(self):
        bad = dict(ASSIGN, decided_by="ryan")
        self.seed(assign=bad)
        out = self.run_step([])
        self.assertEqual((out["action"], out["calls"]), ("needs-allocation", 0))
        nob = {k: v for k, v in ASSIGN.items() if k != "decided_by"}
        self.seed(assign=nob)
        self.assertEqual(self.run_step([])["calls"], 0)
        self.assertEqual(self.calls, [])

    def test_manual_assignment_does_not_clear_a_pause(self):
        self.seed(assign=None)
        self.store.append({"phase": "halt", "ts": rc.iso(T0),
                           "reason": "unknown transport outcome x"})
        self.go(ASSIGN["models"])
        with self.assertRaises(rc.Halt):
            self.run_step([ok(R_OK)])
        self.assertEqual(self.calls, [])


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


class Review3(Base):
    def test_alloc_rid_minted_inside_reserve_and_unique(self):
        e1 = {"phase": "reserved", "rid": None, "ts": rc.iso(T0),
              "qid": "alloc", "role": "allocation", "model": "m"}
        self.store.reserve(T0, e1, "alloc")
        self.store.append({"phase": "result", "rid": e1["rid"],
                           "ts": rc.iso(T0), "outcome": "ok"})
        e2 = dict(e1, rid=None, ts=rc.iso(T0 + 20))
        self.store.reserve(T0 + 20, e2, "alloc")
        self.assertNotEqual(e1["rid"], e2["rid"])

    def test_queue_deleted_midflight_fails_closed(self):
        self.seed()

        def post(*a, **k):
            self.store.save_queue({"questions": []})
            return ok(R_OK)
        with self.assertRaises(rc.Halt):
            rc.step(self.d, post, FRESH, T0 + 20, RECORD)
        self.assertEqual(self.store.ledger()[-1]["phase"], "halt")
        self.store.save_queue({"questions": [{
            "id": "q2", "status": "open", "attempts": {}, "question": "?",
            "packet": PACKET}]})
        with self.assertRaises(rc.Halt):
            self.run_step([])


class Review4(Base):
    def test_independence_uses_listed_lab_not_prefix(self):
        L = FRESH()
        i = rc.independent
        r = "nvidia/nemotron-3-ultra-550b-a55b"
        self.assertEqual(i(L, r, "novita/ling"), "")          # other lab
        self.assertIn("lab", i(L, r, "nvidia/other"))          # same lab
        self.assertIn("lab", i(L, "google/gemma-4-31b-it",
                               "deepinfra/google/gemma-4-31B-it"))  # reseller
        self.assertIn("unknown", i(L, r, "nolab/model"))       # fail closed
        self.assertIn("different model", i(L, r, r))

    def test_question_budget_stops_at_five_requests(self):
        self.seed()
        v_bad = {"verdicts": [{"id": "C1", "verdict": "NOT_SUPPORTED",
                               "evidence": "x"}]}
        acts = [self.run_step([ok(r)])["action"]
                for r in (R_OK, v_bad, R_OK, V_OK, {"usefulness": []})]
        self.assertEqual(sum(self.store.queue()["questions"][0]
                             ["attempts"].values()), 5)
        out = self.run_step([])
        self.assertLessEqual(len([e for e in self.store.ledger()
                                  if e["phase"] == "reserved"]), 5)

    def test_budget_exhaustion_goes_needs_human_without_call(self):
        self.store.save_queue({"questions": [{
            "id": "q1", "status": "open", "question": "?", "packet": PACKET,
            "attempts": {"researcher": 1, "verifier": 2, "ryan": 2}}]})
        with open(os.path.join(self.d, "assignments.json"), "w") as f:
            json.dump(ASSIGN, f)
        out = self.run_step([])
        self.assertEqual((out["action"], out["calls"]), ("needs-human", 0))


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
        self.assertTrue(any(x["title"].startswith("repeated")
                            for x in q["packet"]))
        self.assertTrue(all(x["locations"] and x["passage"]
                            for x in q["packet"]))
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


class Diag(Base):
    KEY = "sk-live-ABCDEF1234567890SECRET"

    def call(self, urlopen):
        from unittest import mock
        os.environ["REQUESTY_API_KEY"] = self.KEY
        try:
            with mock.patch("urllib.request.urlopen", urlopen):
                return rc.http_post_factory()("m", "s", "p", 10)
        finally:
            os.environ.pop("REQUESTY_API_KEY", None)

    class Resp:
        def __init__(self, body, ct="application/json", read_exc=None):
            self.body, self.read_exc = body, read_exc
            self.headers = {"content-type": ct}

        def read(self):
            if self.read_exc:
                raise self.read_exc
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def test_request_fields_and_empty_content(self):
        import json as J
        seen = {}

        def uo(req, timeout=None):
            seen["b"] = J.loads(req.data)
            return self.Resp(J.dumps({"choices": [{
                "message": {"content": "", "reasoning_content": "SECRETTHINK"},
                "finish_reason": "length"}],
                "usage": {"completion_tokens": 10, "note": "x",
                          "completion_tokens_details": {
                              "reasoning_tokens": 10}}}).encode())
        out = self.call(uo)
        b = seen["b"]
        self.assertEqual(b["max_tokens"], 10)
        self.assertEqual(b["reasoning_effort"], "low")
        self.assertNotIn("max_completion_tokens", b)
        self.assertEqual(out["kind"], "unknown")
        self.assertEqual(out["diag"]["class"], "empty-content")
        self.assertEqual(out["diag"]["finish_reason"], "length")
        self.assertEqual(out["diag"]["reasoning_present"], 1)
        self.assertEqual(out["usage"]["completion_tokens_details"],
                         {"reasoning_tokens": 10})
        self.assertNotIn("note", out["usage"])
        self.assertNotIn("SECRETTHINK", J.dumps(out))

    def test_ok_keeps_usage_and_finish_reason(self):
        import json as J
        out = self.call(lambda req, timeout=None: self.Resp(J.dumps({
            "choices": [{"message": {"content": "hi"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "cost": 0}}).encode()))
        self.assertEqual((out["kind"], out["content"], out["finish_reason"],
                          out["usage"]), ("ok", "hi", "stop",
                                          {"prompt_tokens": 3, "cost": 0}))

    def test_classification_without_inferring_cause(self):
        import socket, urllib.error
        R = self.Resp
        cases = [
            (socket.timeout("timed out"), "connect-or-send", "timeout"),
            (urllib.error.URLError(socket.timeout()), "connect-or-send",
             "timeout"),
            (urllib.error.URLError(ConnectionRefusedError("x")),
             "connect-or-send", "network"),
            (OSError("boom"), "connect-or-send", "network"),
            (R(b"", read_exc=socket.timeout()), "read-body", "timeout"),
            (R(b"<html>not json</html>", "text/html"), "parse-json",
             "malformed"),
            (R(b'{"choices": []}'), "response-shape", "malformed"),
        ]
        for c, stage, cls in cases:
            def uo(*a, **k):
                if isinstance(c, BaseException):
                    raise c
                return c
            out = self.call(uo)
            self.assertEqual(out["kind"], "unknown", stage)
            self.assertEqual((out["diag"]["stage"], out["diag"]["class"]),
                             (stage, cls))
            self.assertNotIn("error_text", out["diag"])

    def test_no_body_text_persisted_only_structure(self):
        body = (b"oops " + self.KEY.encode() + b" Bearer abc.def.ghi "
                + b"shortsecret12 " + b"A" * 300)
        out = self.call(lambda *a, **k: self.Resp(body, "text/plain"))
        blob = json.dumps(out)
        for bad in (self.KEY, "abc.def.ghi", "shortsecret12", "oops"):
            self.assertNotIn(bad, blob)
        self.assertNotIn("excerpt", out["diag"])
        self.assertEqual((out["diag"]["body_kind"], out["diag"]["body_len"],
                          out["diag"]["content_type"]),
                         ("text", len(body), "text/plain"))

    def test_http_error_diag_has_status_no_headers(self):
        import urllib.error, io
        def uo(*a, **k):
            raise urllib.error.HTTPError(
                "u", 500, "x", {"content-type": "application/json"},
                io.BytesIO(b'{"error":"' + self.KEY.encode() + b'"}'))
        out = self.call(uo)
        self.assertEqual(out["diag"]["status"], 500)
        self.assertNotIn(self.KEY, json.dumps(out))
        self.assertEqual(out["content"], "")

    def _tx(self, body, status=200):
        import json as J, urllib.error, io
        raw = J.dumps(body).encode()

        def uo(req, timeout=None):
            if status != 200:
                raise urllib.error.HTTPError("u", status, "x", {
                    "content-type": "application/json"}, io.BytesIO(raw))
            return self.Resp(raw)
        return self.call(uo)

    def test_effort_in_body_and_validated(self):
        import json as J
        seen = {}

        def uo(req, timeout=None):
            seen["b"] = J.loads(req.data)
            return self.Resp(J.dumps({"choices": [{"message": {
                "content": "x"}, "finish_reason": "stop"}]}).encode())
        from unittest import mock
        os.environ["REQUESTY_API_KEY"] = self.KEY
        try:
            with mock.patch("urllib.request.urlopen", uo):
                rc.http_post_factory()("m", "s", "p", 5, effort="none")
                self.assertEqual(seen["b"]["reasoning_effort"], "none")
                seen.clear()
                with self.assertRaises(rc.Halt):
                    rc.http_post_factory()("m", "s", "p", 5, effort="max")
                self.assertEqual(seen, {})   # nothing was sent
        finally:
            os.environ.pop("REQUESTY_API_KEY", None)

    def test_http_400_halts_no_fallback(self):
        for code in (400, 404, 422):
            self.setUp()
            self.seed()
            with self.assertRaises(rc.Halt):
                self.run_step([{"kind": "http", "code": code, "usage": None,
                                "content": ""}])
            self.assertEqual(self.store.ledger()[-1]["phase"], "halt")

    def test_finish_reason_enum_only(self):
        for fr, want in (("stop", "stop"), ("length", "length"),
                         ("shortsecret12", "unknown"), (5, None)):
            out = self._tx({"choices": [{"message": {"content": ""},
                                         "finish_reason": fr}]})
            self.assertEqual(out["diag"].get("finish_reason"), want)
            self.assertNotIn("shortsecret12", str(out))

    def test_usage_allowlist_and_validity(self):
        out = self._tx({"choices": [{"message": {"content": "hi"}}],
                        "usage": {"prompt_tokens": 3, "shortsecretkey": 1,
                                  "completion_tokens_details": {
                                      "reasoning_tokens": 4, "zz": 9}}})
        self.assertEqual(out["usage"], {"prompt_tokens": 3,
                         "completion_tokens_details": {"reasoning_tokens": 4}})
        self.assertEqual(out["usage_flag"], "extra_keys")
        self.assertNotIn("shortsecretkey", str(out))
        for bad in (-1, float("inf"), "5", True):
            o = self._tx({"choices": [{"message": {"content": "hi"}}],
                          "usage": {"completion_tokens": bad}})
            self.assertEqual(o["usage_flag"], "invalid", bad)

    def test_cost_signal_from_raw_before_sanitizing(self):
        for c, want in (("0.25", "invalid"), (True, "invalid"), (-1, "invalid"),
                        (0.25, "nonzero"), (0, "zero")):
            o = self._tx({"choices": [{"message": {"content": "hi"}}],
                          "usage": {"cost": c}})
            self.assertEqual(o["cost_signal"], want, c)
        o = self._tx({"error": "x", "usage": {"cost": 0.25}}, status=500)
        self.assertEqual((o["kind"], o["cost_signal"]), ("http", "nonzero"))

    def test_settle_halts_on_cost_for_every_kind(self):
        cases = [
            {"kind": "http", "code": 500, "usage": None, "content": "",
             "cost_signal": "nonzero"},
            {"kind": "unknown", "usage": None, "content": "",
             "cost_signal": "invalid", "diag": {"stage": "response-shape"}},
            {"kind": "ok", "usage": {"prompt_tokens": 1}, "content": "x",
             "cost_signal": "invalid"},
            {"kind": "ok", "usage": {}, "content": "x", "usage_flag": "invalid"},
            {"kind": "ok", "usage": {"cost": "0.25"}, "content": "x"},
        ]
        for res in cases:
            self.setUp()
            self.seed()
            with self.assertRaises(rc.Halt):
                self.run_step([res])
            led = self.store.ledger()
            r = [e for e in led if e["phase"] == "result"][0]
            self.assertIn(r["outcome"], ("http_500", "unknown", "ok"))
            self.assertTrue(r.get("cost_signal"))
            self.assertEqual(led[-1]["phase"], "halt")

    def _direct(self, res):
        self.setUp()
        self.seed()
        try:
            self.run_step([res])
            halted = False
        except rc.Halt:
            halted = True
        return halted, self.store.ledger()

    def test_direct_settle_boundary_revalidates(self):
        for u, sig in (({"cost": 0.25}, "zero"), ({"cost": "0.25"}, "zero"),
                       ({"cost": False}, "zero"), ({"cost": -1}, None)):
            for kind in ("http", "ok"):
                res = {"kind": kind, "usage": u, "content": "x",
                       "cost_signal": sig}
                if kind == "http":
                    res["code"] = 500
                halted, led = self._direct(res)
                self.assertTrue(halted, (u, sig, kind))
        halted, led = self._direct({"kind": "ok", "content": "x",
                                    "usage": {"completion_tokens": 3},
                                    "cost_signal": "bogus"})
        self.assertTrue(halted)

    def test_direct_settle_stores_only_sanitized(self):
        halted, led = self._direct({
            "kind": "ok", "content": "x", "cost_signal": "zero",
            "usage": {"prompt_tokens": 3, "secret-session-123": 9,
                      "prompt_tokens_details": {"secret-session-123": 1,
                                                "cached_tokens": 2}},
            "diag": {"stage": "s", "finish_reason": "secret-session-123"}})
        self.assertFalse(halted)
        r = [e for e in led if e["phase"] == "result"][0]
        self.assertEqual(r["usage"], {"prompt_tokens": 3, "prompt_tokens_details":
                                      {"cached_tokens": 2}})
        self.assertEqual(r["diag"]["finish_reason"], "unknown")
        self.assertNotIn("secret-session-123", json.dumps(led))

    def test_direct_settle_good_zero_cost_ok(self):
        halted, led = self._direct({"kind": "ok", "content": "x",
                                    "usage": {"cost": 0}, "cost_signal": "zero"})
        self.assertFalse(halted)

    def test_settle_persists_only_clean_diag_in_ledger(self):
        self.seed()
        post = lambda *a: {"kind": "unknown", "usage": None, "content": "",
                           "diag": {"stage": "read-body", "class": "timeout",
                                    "authorization": "Bearer SECRET",
                                    "excerpt": "shortsecret12" * 70,
                                    "error_type": "TimeoutError"}}
        with self.assertRaises(rc.Halt):
            self.run_step([post()])
        res = [e for e in self.store.ledger() if e["phase"] == "result"][0]
        self.assertEqual(res["outcome"], "unknown")
        self.assertEqual(res["diag"]["stage"], "read-body")
        self.assertNotIn("authorization", res["diag"])
        self.assertNotIn("excerpt", res["diag"])
        self.assertNotIn("SECRET", json.dumps(self.store.ledger()))
        self.assertNotIn("shortsecret12", json.dumps(self.store.ledger()))


if __name__ == "__main__":
    unittest.main()
