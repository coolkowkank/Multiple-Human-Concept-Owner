import json, os, subprocess, sys, tempfile, unittest

TOOL = os.path.join(os.path.dirname(__file__), "..", "tools",
                    "model_resources.py")

LISTING = {"data": [
    {"id": "google/gemma-4-31b-it", "input_price": 0, "output_price": 0,
     "cached_price": 0},
    {"id": "deepinfra/google/gemma-4-31b-it", "input_price": 1.3e-07,
     "output_price": 3.8e-07},
    {"id": "openai/gpt-oss-120b", "input_price": 0, "output_price": 0},
]}

RECORD = {
    "updated": "2026-11-04", "unknowns": [],
    "routes": [
        {"id": "openai/gpt-oss-120b", "provider": "groq", "price": 0,
         "status": "working", "evidence": "e", "job_shapes": ["code-draft"]},
        {"id": "google/gemma-4-31b-it", "provider": "requesty", "price": 0,
         "status": "working", "evidence": "e",
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
        json.dump(LISTING, open(self.listing, "w"))
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

    def test_record_event_marks_capped_and_preserves_unknowns(self):
        p = self.run_tool("record-event", self.record,
                          "openai/gpt-oss-120b", "cap", "429 quota body")
        self.assertEqual(p.returncode, 0)
        rec = json.load(open(self.record))
        route = [r for r in rec["routes"]
                 if r["id"] == "openai/gpt-oss-120b"][0]
        self.assertEqual(route["status"], "capped")
        self.assertIn("429 quota body", route["evidence"])

if __name__ == "__main__":
    unittest.main()
