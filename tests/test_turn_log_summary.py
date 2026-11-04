import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from turn_log_summary import handoff_counts


class TestHandoffCounts(unittest.TestCase):
    def _log(self, raw_lines):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(raw_lines) + "\n")
        self.addCleanup(os.unlink, path)
        return path

    def test_counts_only_handoffs(self):
        path = self._log([
            json.dumps({"kind": "handoff", "seat": "builder"}),
            json.dumps({"kind": "status", "seat": "builder"}),
            json.dumps({"kind": "handoff", "seat": "builder"}),
            json.dumps({"kind": "handoff", "seat": "qc"}),
        ])
        r = handoff_counts(path)
        self.assertEqual(r["counts"], {"builder": 2, "qc": 1})
        self.assertEqual(r["malformed"], [])

    def test_malformed_lines_skipped_and_reported(self):
        path = self._log([
            json.dumps({"kind": "handoff", "seat": "builder"}),
            "not json at all",
            "{truncated",
            json.dumps({"kind": "handoff", "seat": "qc"}),
        ])
        r = handoff_counts(path)
        self.assertEqual(r["counts"], {"builder": 1, "qc": 1})
        self.assertEqual(r["malformed"], [2, 3])

    def test_empty_log(self):
        self.assertEqual(handoff_counts(self._log([])),
                         {"counts": {}, "malformed": []})


if __name__ == "__main__":
    unittest.main()
