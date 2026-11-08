#!/usr/bin/env python3
"""Offline test: `langgraph_team.py run` on a queue-seated repo stops
gracefully with an explicit WAITING surface (not a refusal) when a
seat's queue is empty, and resumes through the same checkpoint once the
operator queues a response. No keys, no model calls, fake HOME."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CONCEPT = "# Concept\nA CLI unit converter (km<->mi, kg<->lb) with tests.\n"
COORDINATOR_R1 = {
    "summary": "drafted acceptance criteria from the concept",
    "writes": {".team/ACCEPTANCE.md":
               "# Acceptance criteria\n1. converts km<->mi and kg<->lb\n"
               "2. pytest suite green\n"},
    "verify_command": None,
    "handoff": "builder",
    "status_line": "criteria drafted, builder on turn"}


def run_cli(*argv, env):
    return subprocess.run([sys.executable, *argv], cwd=HERE, env=env,
                          capture_output=True, text=True)


class TestWaitingSurface(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="waiting-surface-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, "proj")
        self.db = os.path.join(self.tmp, "cp.sqlite")
        home = os.path.join(self.tmp, "home")
        os.makedirs(home)
        self.env = dict(os.environ, HOME=home)
        concept_file = os.path.join(self.tmp, "concept.md")
        with open(concept_file, "w") as fh:
            fh.write(CONCEPT)
        proc = run_cli(os.path.join(HERE, "concept_scaffold.py"), self.repo,
                       "--concept-file", concept_file, env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def _run_graph(self):
        return run_cli("langgraph_team.py", "run", self.repo, self.db,
                       "0", "waiting-t1", env=self.env)

    def test_waiting_then_resume_through_queue(self):
        # 1. Empty queue: explicit WAITING, graceful stop, exit 0.
        proc = self._run_graph()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("WAITING for an operator response for seat "
                      "'coordinator'", proc.stdout)
        self.assertIn("not an error", proc.stdout)
        self.assertIn("launcher respond coordinator", proc.stdout)
        self.assertIn("resume the run", proc.stdout)
        self.assertIn("stopped gracefully while waiting", proc.stdout)
        self.assertNotIn("REFUSED", proc.stdout)

        # 2. Queue the coordinator response, resume the SAME thread.
        resp = os.path.join(self.tmp, "r1.json")
        with open(resp, "w") as fh:
            json.dump(COORDINATOR_R1, fh)
        proc = run_cli("-m", "launcher", "respond", "coordinator",
                       "--repo", self.repo, "--file", resp, env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = self._run_graph()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        # The coordinator acted on resume (not stuck on the checkpoint).
        with open(os.path.join(self.repo, ".team", "ACCEPTANCE.md")) as fh:
            self.assertIn("km<->mi", fh.read())
        with open(os.path.join(self.repo, ".team", "STATE.json")) as fh:
            self.assertEqual(json.load(fh)["turn"], "builder")
        # The run waited again, one seat later, with the same surface.
        self.assertIn("WAITING for an operator response for seat "
                      "'builder'", proc.stdout)

        # 3. No provider ledger anywhere (queue seats never call out).
        self.assertFalse(os.path.exists(
            os.path.join(self.env["HOME"], ".lg-http-usage")))


if __name__ == "__main__":
    unittest.main()
