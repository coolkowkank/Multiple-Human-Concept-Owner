import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import eva_check as ev

PUB = """# T

## Bottom line
ignored 99%

## Evidence

**M1. arXiv 1** (Table 1).
- Claude 36/63 (57.14%), "records 19/63 and 38/63".
- No numbers here but "a made up quote".

**M2. arXiv 2** (x).
- Gap fell from 6 pp to 2.67 pp, "Claude records 36/63".

## Not used
- ignored 12
"""
PACK = [
    {"id": "P1", "title": "M1 rank", "passage": "Claude records 36/63; PI \"records 19/63 and 38/63, respectively\""},
    {"id": "P2", "title": "M2 gap", "passage": "gap about 6 pp -> 2.67 pp"},
]


class T(unittest.TestCase):
    def test_parse_only_evidence_bullets_with_tags(self):
        c = ev.parse_publication(PUB)
        self.assertEqual([x["id"] for x in c], ["M1.1", "M1.2", "M2.1"])

    def test_found_absent_and_other_source(self):
        rows = {r["id"]: r for r in ev.report(PUB, PACK)["rows"]}
        a = rows["M1.1"]
        self.assertEqual(a["quotes"][0]["status"], "FOUND")
        self.assertIn("57.14%", a["numbers_absent"])
        self.assertEqual(rows["M1.2"]["quotes"][0]["status"], "NOT_FOUND")
        self.assertEqual(rows["M2.1"]["quotes"][0]["status"], "IN_OTHER_SOURCE")
        self.assertTrue(rows["M2.1"]["review"])

    def test_exact_numeric_token(self):
        self.assertFalse(ev.num_in("13%", "flips 13.7% of tasks"))
        self.assertFalse(ev.num_in("13", "flips 13.7 tasks"))
        self.assertFalse(ev.num_in("13%", "flips 113% of tasks"))
        self.assertFalse(ev.num_in("13", "flips 13% of tasks"))
        self.assertTrue(ev.num_in("13%", "median 13% for reruns"))
        self.assertTrue(ev.num_in("2.67", "from 6 to 2.67 pp"))
        self.assertFalse(ev.num_in("2.67", "from 12.67 pp"))

    def test_intake_fails_closed_on_partial_source(self):
        with self.assertRaises(ValueError):
            ev.intake(PUB, [], "x")
        with self.assertRaises(ValueError):
            ev.intake(PUB, PACK[:1], "x")       # M2 has no passage
        with self.assertRaises(ValueError):
            ev.intake(PUB, [dict(PACK[0], passage="a [truncated: 5 of 9]"),
                            PACK[1]], "x")
        with self.assertRaises(ValueError):
            ev.intake("# no evidence", PACK, "x")

    def test_intake_rejects_nonstring_rows(self):
        for bad in ([dict(PACK[0], passage={"a": 1}), PACK[1]],
                    [dict(PACK[0], passage=None), PACK[1]],
                    [dict(PACK[0], id=None), PACK[1]],
                    [PACK[0], dict(PACK[1], id="P1")],
                    [PACK[0], "P2"], "notalist"):
            with self.assertRaises(ValueError):
                ev.intake(PUB, bad, "x")
        with self.assertRaises(ValueError):
            ev.intake(PUB, PACK, "x", author_model=5)

    def test_report_says_review_false_is_not_a_pass(self):
        self.assertIn("NOT a publication pass",
                      ev.report(PUB, PACK)["review_false_means"])

    def test_label_is_not_a_verdict(self):
        r = ev.report(PUB, PACK)
        self.assertIn("not-a-verdict", r["kind"])
        self.assertNotIn("verdict", " ".join(k for row in r["rows"] for k in row))

    def test_intake_is_held_and_unwired(self):
        it = ev.intake(PUB, PACK, "eva-x")
        self.assertEqual((it["status"], it["attempts"], it["kind"]),
                         ("held", {}, "verify"))
        self.assertEqual(it["findings"][0]["sources"], ["P1"])
        self.assertEqual(it["lineage"], "eva-x")

    def test_runner_would_not_pick_held_item(self):
        import ryan_cycle as rc
        it = ev.intake(PUB, PACK, "eva-x")
        self.assertIsNone(rc.next_action(it))
        self.assertEqual(rc.pick({"questions": [it]}), None)


if __name__ == "__main__":
    unittest.main()
