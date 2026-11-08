#!/usr/bin/env python3
"""Offline tests for concept_scaffold.py: concept in, conformant team
repo out, driven through the honest queue boundary. No keys, no model
calls, no network; the suite runs with a fake HOME and asserts the
provider ledger is never touched."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import concept_scaffold  # noqa: E402

CONCEPT = "# Concept\nA CLI unit converter (km<->mi, kg<->lb) with tests.\n"
COORDINATOR_R1 = {
    "summary": "drafted acceptance criteria from the concept",
    "writes": {".team/ACCEPTANCE.md":
               "# Acceptance criteria\n1. converts km<->mi and kg<->lb\n"
               "2. pytest suite green\n"},
    "verify_command": None,
    "handoff": "builder",
    "status_line": "criteria drafted, builder on turn"}


def run_cli(*argv, cwd=HERE, env=None):
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run([sys.executable, *argv], cwd=cwd, env=full_env,
                          capture_output=True, text=True)


class TestScaffold(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="concept-scaffold-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, "proj")
        # Fake HOME: prove the scaffold + first turn touch no provider
        # state (the ledger path the runtime uses for http seats).
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.env = {"HOME": self.home}

    def _scaffold_via_cli(self, *extra):
        concept_file = os.path.join(self.tmp, "concept.md")
        with open(concept_file, "w") as fh:
            fh.write(CONCEPT)
        proc = run_cli(os.path.join(HERE, "concept_scaffold.py"), self.repo,
                       "--concept-file", concept_file, *extra, env=self.env)
        return proc

    def test_scaffold_happy_path(self):
        proc = self._scaffold_via_cli()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Scaffolded concept team", proc.stdout)
        self.assertIn("conform", proc.stdout.lower())

        # Concept in: the brief holds the concept verbatim.
        with open(os.path.join(self.repo, ".team", "brief.md")) as fh:
            self.assertEqual(fh.read(), CONCEPT)
        # No concept temp file left inside the repo.
        self.assertNotIn(".concept-brief.md",
                         subprocess.run(["git", "-C", self.repo, "ls-files"],
                                        capture_output=True,
                                        text=True).stdout)

        # Team out: state at the coordinator's first turn, running.
        with open(os.path.join(self.repo, ".team", "STATE.json")) as fh:
            state = json.load(fh)
        self.assertEqual(state["turn"], "coordinator")
        self.assertEqual(state["status"], "running")
        with open(os.path.join(self.repo, ".team", "CONTROL.json")) as fh:
            self.assertEqual(json.load(fh)["mode"], "run")

        # Every seat is an honest queue seat; no mock scripts, no http.
        with open(os.path.join(self.repo, ".team", "roster.json")) as fh:
            roster = json.load(fh)
        self.assertEqual(sorted(roster["seats"]),
                         sorted(concept_scaffold.DEFAULT_ROSTER))
        for name, spec in roster["seats"].items():
            self.assertEqual(spec["adapter"]["type"], "queue")
            self.assertTrue(os.path.exists(
                os.path.join(self.repo, ".team", "queues",
                             f"{name}.jsonl")))
            self.assertNotIn("script", spec.get("adapter", {}))

        # Conformance passes through the real CLI.
        proc = run_cli("-m", "launcher", "conform", "--repo", self.repo,
                       env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_concept_reaches_coordinator_prompt(self):
        self.assertEqual(self._scaffold_via_cli().returncode, 0)
        proc = run_cli("-m", "launcher", "prompt", "coordinator",
                       "--repo", self.repo, env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("unit converter", proc.stdout)

    def test_first_turn_runs_through_queue_boundary(self):
        self.assertEqual(self._scaffold_via_cli().returncode, 0)
        resp_path = os.path.join(self.tmp, "r1.json")
        with open(resp_path, "w") as fh:
            json.dump(COORDINATOR_R1, fh)
        proc = run_cli("-m", "launcher", "respond", "coordinator",
                       "--repo", self.repo, "--file", resp_path,
                       env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = run_cli("-m", "launcher", "seat", "coordinator",
                       "--repo", self.repo, "--once", env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        # The turn landed: acceptance file from the queued response is
        # committed, and the turn moved to the builder.
        with open(os.path.join(self.repo, ".team", "ACCEPTANCE.md")) as fh:
            self.assertIn("km<->mi", fh.read())
        with open(os.path.join(self.repo, ".team", "STATE.json")) as fh:
            self.assertEqual(json.load(fh)["turn"], "builder")
        proc = subprocess.run(["git", "-C", self.repo, "ls-files"],
                              capture_output=True, text=True)
        self.assertIn(".team/ACCEPTANCE.md", proc.stdout)

        # The next queue seat waits honestly: an empty queue is an
        # explicit refusal, not a faked answer.
        proc = run_cli("-m", "launcher", "seat", "builder",
                       "--repo", self.repo, "--once", env=self.env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("queue empty", (proc.stdout + proc.stderr).lower())

    def test_refusals(self):
        # Non-empty directory is refused.
        os.makedirs(self.repo)
        with open(os.path.join(self.repo, "keep.txt"), "w") as fh:
            fh.write("precious\n")
        proc = self._scaffold_via_cli()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("non-empty", proc.stderr)
        with open(os.path.join(self.repo, "keep.txt")) as fh:
            self.assertEqual(fh.read(), "precious\n")
        shutil.rmtree(self.repo)

        # Empty concept is refused.
        proc = run_cli(os.path.join(HERE, "concept_scaffold.py"), self.repo,
                       "--concept", "   ", env=self.env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("concept is empty", proc.stderr)

        # Forbidden locations are refused.
        proc = run_cli(os.path.join(HERE, "concept_scaffold.py"), "/",
                       "--concept", "x", env=self.env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("forbidden", proc.stderr)

    def test_no_provider_ledger(self):
        self.assertEqual(self._scaffold_via_cli().returncode, 0)
        self.assertFalse(os.path.exists(
            os.path.join(self.home, ".lg-http-usage")))


if __name__ == "__main__":
    unittest.main()
