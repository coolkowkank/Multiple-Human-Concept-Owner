import datetime, json, os, subprocess, sys, tempfile, unittest

TOOL = os.path.join(os.path.dirname(__file__), "..", "tools",
                    "model_resources.py")

DATA = [
    {"id": "google/gemma-4-31b-it", "input_price": 0, "output_price": 0,
     "cached_price": 0},
    {"id": "deepinfra/google/gemma-4-31b-it", "input_price": 1.3e-07,
     "output_price": 3.8e-07},
    {"id": "openai/gpt-oss-120b", "input_price": 0, "output_price": 0},
]

def fresh_listing():
    return {"fetched_at": datetime.datetime.now(
                datetime.timezone.utc).isoformat(),
            "source": "requesty /v1/models (test fixture)", "data": DATA}

def stale_listing():
    old = datetime.datetime.now(datetime.timezone.utc) \
        - datetime.timedelta(hours=3)
    return {"fetched_at": old.isoformat(),
            "source": "requesty /v1/models (test fixture)", "data": DATA}

RECORD = {
    "updated": "2026-11-04", "unknowns": [],
    "routes": [
        {"id": "openai/gpt-oss-120b", "provider": "groq", "price": 0,
         "status": "working", "evidence": "2026-11-04 ok x4",
         "job_shapes": ["code-draft"]},
        {"id": "google/gemma-4-31b-it", "provider": "requesty", "price": 0,
         "status": "working", "evidence": "2026-11-04 ok x1",
         "job_shapes": ["status-draft", "code-draft"]},
        {"id": "nvidia/broken", "provider": "requesty", "price": 0,
         "status": "uncallable", "evidence": "404", "job_shapes": []},
    ],
    "supply_map": {"code-draft": ["openai/gpt-oss-120b",
                                  "google/gemma-4-31b-it"],
                   "status-draft": ["google/gemma-4-31b-it"],
                   "research": ["nvidia/broken"]},
    "excluded_money": [],
}

class ModelResourcesCase(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.listing = os.path.join(self.d, "listing.json")
        self.record = os.path.join(self.d, "record.json")
        json.dump(fresh_listing(), open(self.listing, "w"))
        json.dump(RECORD, open(self.record, "w"))

    def run_tool(self, *args):
        return subprocess.run([sys.executable, TOOL] + list(args),
                              capture_output=True, text=True)

    def test_check_price_exact_free_id(self):
        p = self.run_tool("check-price", self.listing,
                          "google/gemma-4-31b-it")
        self.assertEqual(p.returncode, 0)
        self.assertIn("PRICE-ZERO", p.stdout)

    def test_check_price_rejects_paid_prefixed_variant(self):
        p = self.run_tool("check-price", self.listing,
                          "deepinfra/google/gemma-4-31b-it")
        self.assertEqual(p.returncode, 1)
        self.assertIn("NOT-FREE-OR-ABSENT", p.stdout)

    def test_check_price_absent_id(self):
        p = self.run_tool("check-price", self.listing, "no/such-model")
        self.assertEqual(p.returncode, 1)

    def test_propose_automatic_choice_when_all_scope_fits(self):
        p = self.run_tool("propose", self.record, self.listing,
                          "code-draft", "openai/gpt-oss-120b", "2")
        self.assertEqual(p.returncode, 0)
        self.assertIn("DECISION use google/gemma-4-31b-it", p.stdout)

    def test_decision_states_quota_unknown_until_call(self):
        p = self.run_tool("propose", self.record, self.listing,
                          "code-draft", "openai/gpt-oss-120b", "2")
        self.assertEqual(p.returncode, 0)
        self.assertIn("quota UNKNOWN until the actual call", p.stdout)

    def test_propose_returns_coordinator_when_cap_exhausted(self):
        p = self.run_tool("propose", self.record, self.listing,
                          "code-draft", "openai/gpt-oss-120b", "0")
        self.assertEqual(p.returncode, 1)
        self.assertIn("cap exhausted", p.stdout)

    def test_propose_returns_coordinator_when_no_backup(self):
        p = self.run_tool("propose", self.record, self.listing,
                          "research", "nvidia/broken", "2")
        self.assertEqual(p.returncode, 1)
        self.assertIn("no recorded backup", p.stdout)

    def test_propose_returns_coordinator_without_fresh_listing(self):
        p = self.run_tool("propose", self.record, "-", "code-draft",
                          "openai/gpt-oss-120b", "2")
        self.assertEqual(p.returncode, 1)
        self.assertIn("price unverified", p.stdout)

    def test_stale_listing_rejected(self):
        json.dump(stale_listing(), open(self.listing, "w"))
        p = self.run_tool("propose", self.record, self.listing,
                          "code-draft", "openai/gpt-oss-120b", "2")
        self.assertEqual(p.returncode, 1)
        self.assertIn("price unverified", p.stdout)

    def test_missing_listing_source_rejected(self):
        bad = fresh_listing(); del bad["source"]
        json.dump(bad, open(self.listing, "w"))
        p = self.run_tool("propose", self.record, self.listing,
                          "code-draft", "openai/gpt-oss-120b", "2")
        self.assertEqual(p.returncode, 1)

    def test_record_event_cap_ambiguous_cools_route_only(self):
        p = self.run_tool("record-event", self.record,
                          "google/gemma-4-31b-it", "cap-ambiguous",
                          "429 concurrency body")
        self.assertEqual(p.returncode, 0)
        rec = json.load(open(self.record))
        route = [r for r in rec["routes"]
                 if r["id"] == "google/gemma-4-31b-it"][0]
        self.assertEqual(route["status"], "cooldown")
        self.assertIn("429 concurrency body", route["evidence"])
        # route cooldown does NOT poison the provider
        self.assertNotIn("requesty", rec.get("provider_blocks", {}))

    def test_record_event_org_confirmed_blocks_provider(self):
        p = self.run_tool("record-event", self.record,
                          "google/gemma-4-31b-it", "cap-org-confirmed",
                          "provider policy doc: org daily quota 200 hit")
        self.assertEqual(p.returncode, 0)
        rec = json.load(open(self.record))
        self.assertIn("requesty", rec["provider_blocks"])
        self.assertIn("no date guesses",
                      rec["provider_blocks"]["requesty"]["clears"])

    def test_propose_skips_provider_blocked_candidate(self):
        rec = json.load(open(self.record))
        rec["provider_blocks"] = {"requesty": {
            "since": "2026-11-04", "evidence": "org quota confirmed",
            "clears": "only via a later successful call"}}
        json.dump(rec, open(self.record, "w"))
        p = self.run_tool("propose", self.record, self.listing,
                          "code-draft", "openai/gpt-oss-120b", "2")
        self.assertEqual(p.returncode, 1)
        self.assertIn("org-capped", p.stdout)

    def test_ok_event_clears_provider_block(self):
        self.run_tool("record-event", self.record,
                      "google/gemma-4-31b-it", "cap-org-confirmed", "ev")
        p = self.run_tool("record-event", self.record,
                          "google/gemma-4-31b-it", "ok", "later success")
        self.assertEqual(p.returncode, 0)
        rec = json.load(open(self.record))
        self.assertNotIn("requesty", rec["provider_blocks"])
        route = [r for r in rec["routes"]
                 if r["id"] == "google/gemma-4-31b-it"][0]
        self.assertEqual(route["status"], "working")

    def test_record_event_bad_result_rejected(self):
        p = self.run_tool("record-event", self.record,
                          "openai/gpt-oss-120b", "cap", "old class")
        self.assertEqual(p.returncode, 1)
        self.assertIn("bad result", p.stdout)

if __name__ == "__main__":
    unittest.main()
