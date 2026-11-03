import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from turn_log_summary import handoff_counts


class TestHandoffCounts(unittest.TestCase):
    def _log(self, entries):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as fh:
            for e in entries:
                fh.write(json.dumps(e) + "\n")
        self.addCleanup(os.unlink, path)
        return path

    def test_counts_only_handoffs(self):
        path = self._log([
            {"kind": "handoff", "seat": "builder"},
            {"kind": "status", "seat": "builder"},
            {"kind": "handoff", "seat": "builder"},
            {"kind": "handoff", "seat": "qc"},
        ])
        self.assertEqual(handoff_counts(path), {"builder": 2, "qc": 1})

    def test_empty_and_blank_lines(self):
        path = self._log([])
        with open(path, "a") as fh:
            fh.write("\n\n")
        self.assertEqual(handoff_counts(path), {})


if __name__ == "__main__":
    unittest.main()
