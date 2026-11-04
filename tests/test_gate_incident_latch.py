"""Incident-keyed escalation latch, exercised against the REAL Bus
(git + JSONL) lifecycle - not a DummyBus. Covers the R1/R2 review
findings on rejected 76a1554: distinct incidents stay actionable while
another supervisor gate is pending, and an unreadable pending state
neither spams gates nor loses the incident."""
import json, os, subprocess, tempfile, time, unittest

from launcher.bus import Bus, GATES_PENDING, GATES_ANSWERS
from launcher.supervisor import Supervisor


class DeadProc:
    def poll(self):
        return 1


def git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args),
                          capture_output=True, text=True, check=True)


class RealBusCase(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "t")
        self.sup = Supervisor(repo=self.repo, stall_timeout=3600,
                              restart_limit=2)
        self.bus = self.sup.bus
        self.bus.init_layout()

    def pending_questions(self):
        return [g["question"] for g in self.bus.pending_gates()]

    def commit_count(self):
        return int(git(self.repo, "rev-list", "--count", "HEAD")
                   .stdout.strip())

    def test_same_incident_deduped(self):
        self.assertTrue(self.sup._escalate("consecutive routing failures"))
        self.assertTrue(self.sup._escalate("consecutive routing failures"))
        self.assertEqual(self.pending_questions(),
                         ["consecutive routing failures"])

    def test_distinct_crash_gated_while_supervisor_gate_pending(self):
        # gate A pending; exhausted crash of seat B is a DISTINCT incident
        self.sup._escalate("consecutive routing failures")
        self.sup.procs["builder"] = DeadProc()
        self.sup.restarts["builder"] = 2
        self.sup._reap_and_restart()
        qs = self.pending_questions()
        self.assertEqual(len(qs), 2)
        self.assertIn("seat builder crashed 3 times; not restarting", qs)
        self.assertNotIn("builder", self.sup.procs)
        # answering A must not lose B's gate
        a_id = [g["id"] for g in self.bus.pending_gates()
                if g["question"] == "consecutive routing failures"][0]
        self.bus.answer_gate(a_id, "restart the seat")
        self.assertEqual(self.pending_questions(),
                         ["seat builder crashed 3 times; not restarting"])

    def test_distinct_stall_gated_while_supervisor_gate_pending(self):
        self.sup._escalate("consecutive routing failures")
        state = {"status": "running", "turn": "eva",
                 "turn_since": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                             time.gmtime(time.time() - 7200))}
        self.sup._check_stall(state)
        self.assertIn("eva", self.sup._stalled_seats)
        qs = self.pending_questions()
        self.assertEqual(len(qs), 2)
        self.assertTrue(any("interactive seat eva" in q for q in qs))

    def test_read_error_defers_without_losing_incident(self):
        real = self.bus.pending_gates
        self.bus.pending_gates = lambda: (_ for _ in ()).throw(
            OSError("disk gone"))
        try:
            before = self.commit_count()
            self.assertFalse(self.sup._escalate("incident X"))
            self.assertEqual(self.commit_count(), before)  # no new commit
            self.assertEqual(self.pending_questions_real(), [])
            # crash path: seat must NOT be dropped while deferred
            self.sup.procs["builder"] = DeadProc()
            self.sup.restarts["builder"] = 2
            self.sup._reap_and_restart()
            self.assertIn("builder", self.sup.procs)
            # stall path: seat must NOT be latched while deferred
            state = {"status": "running", "turn": "eva",
                     "turn_since": time.strftime(
                         "%Y-%m-%dT%H:%M:%SZ",
                         time.gmtime(time.time() - 7200))}
            self.sup._check_stall(state)
            self.assertNotIn("eva", self.sup._stalled_seats)
        finally:
            self.bus.pending_gates = real
        # after the read recovers, the retry lands the gate
        self.assertTrue(self.sup._escalate("incident X"))
        self.assertEqual(self.pending_questions(), ["incident X"])
        self.sup._reap_and_restart()
        self.assertNotIn("builder", self.sup.procs)
        self.sup._check_stall(state)
        self.assertIn("eva", self.sup._stalled_seats)

    def pending_questions_real(self):
        with open(os.path.join(self.repo, GATES_PENDING)) as fh:
            return [json.loads(l)["question"] for l in fh if l.strip()]

    def test_malformed_jsonl_defers_without_spam(self):
        with open(os.path.join(self.repo, GATES_ANSWERS), "a") as fh:
            fh.write("{not json\n")
        before = self.commit_count()
        for _ in range(4):
            self.assertFalse(self.sup._escalate("incident Y"))
        self.assertEqual(self.commit_count(), before)  # zero gates/commits
        self.assertEqual(self.pending_questions_real(), [])
        # repair the file; the deferred incident can still be raised
        with open(os.path.join(self.repo, GATES_ANSWERS), "w") as fh:
            fh.write("")
        self.assertTrue(self.sup._escalate("incident Y"))
        self.assertEqual(self.pending_questions(), ["incident Y"])

    def test_answer_then_repeat_incident_reopens(self):
        self.sup._escalate("incident Z")
        g_id = self.bus.pending_gates()[0]["id"]
        self.bus.answer_gate(g_id, "stop the team")
        time.sleep(0.01)  # gate ids are millisecond-stamped
        self.sup._escalate("incident Z")
        self.assertEqual(self.pending_questions(), ["incident Z"])

    def test_suppression_writes_nothing(self):
        self.sup._escalate("incident W")
        commits = self.commit_count()
        log_path = os.path.join(self.repo, ".team", "LOG.jsonl")
        log_size = os.path.getsize(log_path)
        for _ in range(5):
            self.sup._escalate("incident W")
        self.assertEqual(self.commit_count(), commits)
        self.assertEqual(os.path.getsize(log_path), log_size)


if __name__ == "__main__":
    unittest.main()
