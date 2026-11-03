#!/usr/bin/env python3
"""Standalone tests for check.py - stdlib unittest, no third-party deps.

Run: python3 test_check.py   (from tools/artifact-conformance/)
"""

import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = os.path.join(HERE, "check.py")
VALID = os.path.join(HERE, "fixtures", "valid")
INVALID = os.path.join(HERE, "fixtures", "invalid")

VALID_CASES = {
    "batch-handoff.md": "batch-handoff",
    "qc-verdict.md": "qc-verdict",
    "review-findings.md": "review-findings",
    "decision-record.md": "decision-record",
    "delegation-record.md": "delegation-record",
    "gated-run-evidence.md": "gated-run-evidence",
}

# (fixture, type, expected violation substring)
INVALID_CASES = [
    ("batch-handoff-placeholder.md", "batch-handoff",
     "unfilled placeholder"),
    ("batch-handoff-short-sha.md", "batch-handoff",
     "40-hex"),
    ("qc-verdict-unresolved-limit.md", "qc-verdict",
     "accept/waive/must-fix"),
    ("decision-record-private-link.md", "decision-record",
     "public/agreed"),
    ("review-findings-gate-no-dr.md", "review-findings",
     "no DR-ID"),
    # regression: reviewer-reported false passes D1-D3
    ("batch-handoff-owner-basis-loose.md", "batch-handoff",
     "'none - no gated items'"),
    ("qc-verdict-unquoted-placeholder.md", "qc-verdict",
     "angle-bracket"),
    ("qc-verdict-qualified-pass.md", "qc-verdict",
     "exactly PASS or FAIL"),
]


def run_check(*args):
    return subprocess.run(
        [sys.executable, CHECK, *args],
        capture_output=True, text=True)


class TestValidFixtures(unittest.TestCase):
    def test_valid_fixtures_conform(self):
        for fn, atype in sorted(VALID_CASES.items()):
            with self.subTest(fixture=fn):
                extra = []
                if atype in ("batch-handoff", "qc-verdict",
                             "gated-run-evidence"):
                    extra = ["--decisions", VALID]
                r = run_check(os.path.join(VALID, fn), atype, *extra)
                self.assertEqual(r.returncode, 0,
                                 f"{fn}: {r.stdout}{r.stderr}")


class TestInvalidFixtures(unittest.TestCase):
    def test_invalid_fixtures_flagged(self):
        for fn, atype, needle in INVALID_CASES:
            with self.subTest(fixture=fn):
                r = run_check(os.path.join(INVALID, fn), atype)
                self.assertEqual(r.returncode, 1,
                                 f"{fn}: expected violations, got exit "
                                 f"{r.returncode}: {r.stdout}")
                self.assertIn(needle, r.stdout,
                              f"{fn}: missing violation {needle!r}")

    def test_cross_file_dr_resolution(self):
        # DR-999 is not among the supplied decision records
        r = run_check(os.path.join(INVALID, "gated-run-missing-dr.md"),
                      "gated-run-evidence", "--decisions", VALID)
        self.assertEqual(r.returncode, 1)
        self.assertIn("DR-999", r.stdout)
        # without --decisions the same file passes (no resolution possible)
        r2 = run_check(os.path.join(INVALID, "gated-run-missing-dr.md"),
                       "gated-run-evidence")
        self.assertEqual(r2.returncode, 0, r2.stdout)

    def test_usage_errors(self):
        self.assertEqual(run_check().returncode, 2)
        r = run_check(os.path.join(VALID, "batch-handoff.md"), "bogus")
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
