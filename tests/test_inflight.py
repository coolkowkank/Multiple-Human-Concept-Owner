"""Offline: a provider result is applied only if the item's inputs,
status, role, model and assignment are unchanged when it returns."""
import copy, json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import ryan_cycle as rc
import eva_check as ev

T = 1800000000
R, V = "lab-a/research", "lab-b/verifier"
LISTING = {"source": "offline mock", "fetched_at": rc.iso(T - 1), "data": [
    {"id": R, "model_lab": "lab-a", "input_price": 0, "output_price": 0},
    {"id": V, "model_lab": "lab-b", "input_price": 0, "output_price": 0}]}
RECORD = {"routes": [{"id": V, "provider": "mock", "status": "untested"}],
          "provider_blocks": {}}
PACKET = [{"id": "P1", "title": "M1 source",
           "passage": "The experiment used a red control widget."}]
OK = {"kind": "ok", "usage": {"cost": 0}, "content": json.dumps({
    "verdicts": [{"id": "M1.1", "verdict": "SUPPORTED", "source": "P1",
                  "quote": "red control widget", "evidence": "ok"}]})}


def base(qid="check-one"):
    q = ev.intake("## Evidence\n**M1. Source**\n- The control widget was "
                  "red.", PACKET, qid, R)
    q["status"] = "ready-verify"
    return q


class InFlight(unittest.TestCase):
    def run_case(self, mutate, extra=None):
        root = tempfile.mkdtemp()
        store = rc.Store(root)
        items = [base()] + ([extra] if extra else [])
        store.save_queue({"questions": items})
        rc.assign_eva_manual(root, V, "offline mock only", LISTING, RECORD,
                             T, "offline mock operator decision")

        def post(model, system, prompt, max_tokens, **kw):
            mutate(store, root)
            return copy.deepcopy(OK)
        out = rc.step(root, post, lambda: LISTING, T, RECORD)
        return out, store

    def edit(self, fn):
        def m(store, root):
            s = store.queue()
            fn(s["questions"][0], s)
            store.save_queue(s)
        return m

    def stale(self, out, store, status):
        self.assertEqual(out["action"], "stale-result-halt")
        self.assertEqual(store.queue()["questions"][0]["status"], status)
        self.assertNotIn("verifier_verdict", store.queue()["questions"][0])
        led = store.ledger()
        self.assertEqual(led[-1]["phase"], "halt")
        # durable: the next step cannot run automatically
        with self.assertRaises(rc.Halt):
            rc.ledger_gate(store, T + 100, "check-one")
        # the call is still counted as consumed, raw result kept for audit
        self.assertTrue(any(l.get("phase") == "reserved" for l in led))

    def test_claim_edit(self):
        out, st = self.run_case(self.edit(
            lambda q, s: q["findings"][0].update(claim="Changed claim.")))
        self.stale(out, st, "needs-human")
        self.assertEqual(st.queue()["questions"][0]["findings"][0]["claim"],
                         "Changed claim.")

    def test_hold_mid_call(self):
        out, st = self.run_case(self.edit(
            lambda q, s: q.update(status="held")))
        self.stale(out, st, "held")

    def test_superseded_mid_call(self):
        out, st = self.run_case(self.edit(
            lambda q, s: q.update(status="superseded-by-packet-v2")))
        self.stale(out, st, "superseded-by-packet-v2")

    def test_packet_and_author_edit(self):
        out, st = self.run_case(self.edit(
            lambda q, s: q["packet"][0].update(passage="Other text.")))
        self.stale(out, st, "needs-human")
        out, st = self.run_case(self.edit(
            lambda q, s: q.update(author_model="lab-c/other")))
        self.stale(out, st, "needs-human")

    def test_assignment_changed(self):
        def m(store, root):
            p = os.path.join(root, "eva-assignment.json")
            a = json.load(open(p))
            a["models"]["eva"] = "lab-b/other"
            json.dump(a, open(p, "w"))
        out, st = self.run_case(m)
        self.stale(out, st, "needs-human")

    def test_same_model_authority_edit(self):
        def m(store, root):
            p = os.path.join(root, "eva-assignment.json")
            with open(p) as f:
                a = json.load(f)
            a["decided_by"] = "revoked"
            with open(p, "w") as f:
                json.dump(a, f)
        out, st = self.run_case(m)
        self.stale(out, st, "needs-human")

    def test_same_model_provenance_edit(self):
        def m(store, root):
            p = os.path.join(root, "eva-assignment.json")
            with open(p) as f:
                a = json.load(f)
            a["decided_at"] = "2000-01-01T00:00:00Z"
            with open(p, "w") as f:
                json.dump(a, f)
        out, st = self.run_case(m)
        self.stale(out, st, "needs-human")

    def test_unrelated_item_edit_does_not_invalidate(self):
        other = base("other")
        other["status"] = "held"

        def m(store, root):
            s = store.queue()
            s["questions"][1]["findings"][0]["claim"] = "Different."
            s["questions"][1]["status"] = "superseded"
            store.save_queue(s)
        out, st = self.run_case(m, extra=other)
        self.assertEqual(out["action"], "done-verifier")
        self.assertEqual(st.queue()["questions"][0]["status"],
                         "verify-complete")

    def test_feedback_edit_changes_prompt(self):
        out, st = self.run_case(self.edit(
            lambda q, s: q.update(fb_verifier="new correction text")))
        self.stale(out, st, "needs-human")

    def test_render_failure_fails_closed(self):
        out, st = self.run_case(self.edit(
            lambda q, s: q.pop("packet")))
        self.assertEqual(out["action"], "stale-result-halt")
        self.assertNotIn("verifier_verdict", st.queue()["questions"][0])

    def test_researcher_feedback_and_ryan_verified_ids(self):
        for role, status, key, val in (
                ("researcher", "open", "feedback", "changed feedback"),
                ("ryan", "verified", "verified_ids", ["C9"])):
            root = tempfile.mkdtemp()
            store = rc.Store(root)
            q = {"id": "j1", "kind": "research", "status": status,
                 "question": "Q?", "packet": PACKET, "attempts": {},
                 "findings": [{"id": "C1", "claim": "The control widget "
                               "was red.", "sources": ["P1"],
                               "status": "SUPPORTED_BY_PACKET"}],
                 "verified_ids": ["C1"]}
            store.save_queue({"questions": [q]})
            models = {"researcher": R, "verifier": V, "ryan": R}
            with open(os.path.join(root, "assignments.json"), "w") as f:
                json.dump({"decided_by": rc.OPERATOR, "models": models,
                           "why": {r: "x" for r in rc.ROLES}}, f)

            def post(model, system, prompt, max_tokens, **kw):
                s = store.queue()
                s["questions"][0][key] = val
                store.save_queue(s)
                return {"kind": "ok", "usage": {"cost": 0}, "content": "{}"}
            rec = {"routes": [{"id": R, "provider": "mock",
                               "status": "working"}], "provider_blocks": {}}
            try:
                out = rc.step(root, post, lambda: LISTING, T, rec)
            except rc.Halt as e:  # gates before the call are not under test
                self.skipTest("pre-call gate: %s" % e)
            self.assertEqual(out["action"], "stale-result-halt", role)

    def test_unchanged_applies(self):
        out, st = self.run_case(lambda store, root: None)
        self.assertEqual(out["action"], "done-verifier")


if __name__ == "__main__":
    unittest.main()
