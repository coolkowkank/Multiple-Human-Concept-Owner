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

    def install_rejecting_hook(self):
        hook = os.path.join(self.repo, ".git", "hooks", "pre-commit")
        with open(hook, "w") as fh:
            fh.write("#!/bin/sh\nexit 1\n")
        os.chmod(hook, 0o755)

    def remove_rejecting_hook(self):
        os.remove(os.path.join(self.repo, ".git", "hooks",
                               "pre-commit"))

    def pending_rows(self):
        with open(os.path.join(self.repo, GATES_PENDING)) as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def head_pending_contains(self, gate_id):
        p = subprocess.run(
            ["git", "-C", self.repo, "show", f"HEAD:{GATES_PENDING}"],
            capture_output=True, text=True)
        return p.returncode == 0 and gate_id in p.stdout


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


class ReviewReproCase(RealBusCase):
    """The two confirmed v2 REQUEST-CHANGES repros, as integrated
    regressions."""

    def test_failed_commit_rolls_back_and_preserves_crash(self):
        self.install_rejecting_hook()
        try:
            before = self.commit_count()
            self.assertFalse(self.sup._escalate("incident C"))
            # rollback: no worktree row, no commit, nothing durable
            self.assertEqual(self.pending_rows(), [])
            self.assertEqual(self.commit_count(), before)
            # caller keeps the crashed seat - the incident is not lost
            self.sup.procs["builder"] = DeadProc()
            self.sup.restarts["builder"] = 2
            self.sup._reap_and_restart()
            self.assertIn("builder", self.sup.procs)
        finally:
            os.remove(os.path.join(self.repo, ".git", "hooks",
                                   "pre-commit"))
        # after the blocker clears, the retry durably lands the gate
        self.assertTrue(self.sup._escalate("incident C"))
        rows = self.pending_rows()
        self.assertEqual(len(rows), 1)
        self.assertTrue(self.head_pending_contains(rows[0]["id"]))
        self.sup._reap_and_restart()
        self.assertNotIn("builder", self.sup.procs)

    def test_uncommitted_matching_row_recommitted_on_retry(self):
        # residue of an earlier failed commit: worktree row, empty HEAD
        row = {"id": "gate-residue", "ts": "2026-11-04T00:00:00Z",
               "seat": "supervisor", "question": "incident M",
               "options": [], "recommendation": None}
        with open(os.path.join(self.repo, GATES_PENDING), "a") as fh:
            fh.write(json.dumps(row) + "\n")
        self.assertFalse(self.head_pending_contains("gate-residue"))
        # retry must recommit the matching row, not trust it
        self.assertTrue(self.sup._escalate("incident M"))
        self.assertTrue(self.head_pending_contains("gate-residue"))
        self.assertEqual(len(self.pending_rows()), 1)  # deduped, no 2nd

    def test_report_gates_read_error_survives(self):
        with open(os.path.join(self.repo, GATES_ANSWERS), "a") as fh:
            fh.write("{broken\n")
        self.sup._report_gates()  # must not raise
        self.assertEqual(self.pending_rows(), [])

    def test_run_loop_survives_malformed_answers_no_spam(self):
        with open(os.path.join(self.repo, GATES_ANSWERS), "a") as fh:
            fh.write("{broken\n")
        sup = Supervisor(repo=self.repo, stall_timeout=3600, poll=0.05)
        before = self.commit_count()
        # the whole run loop must ride out the read failure: no raise,
        # no gates, no commits - so a later poll CAN retry
        self.assertEqual(sup.run(max_seconds=0.3), "timeout")
        self.assertEqual(self.commit_count(), before)
        self.assertEqual(self.pending_rows(), [])
        # and recovery works in the same repo
        with open(os.path.join(self.repo, GATES_ANSWERS), "w") as fh:
            fh.write("")
        self.assertTrue(sup._escalate("incident after recovery"))


class V3ReviewReproCase(RealBusCase):
    """The two narrow v3 REQUEST-CHANGES repros."""

    def staged_paths(self):
        p = subprocess.run(
            ["git", "-C", self.repo, "diff", "--cached", "--name-only"],
            capture_output=True, text=True, check=True)
        return [l for l in p.stdout.splitlines() if l]

    def test_rollback_restores_index_and_preserves_preexisting(self):
        # pre-existing staged change to ANOTHER file + a pre-existing
        # STAGED PENDING row must both survive the rollback
        with open(os.path.join(self.repo, "note.txt"), "w") as fh:
            fh.write("keep me staged\n")
        git(self.repo, "add", "note.txt")
        r0 = {"id": "gate-staged-before", "ts": "2026-11-04T00:00:00Z",
              "seat": "supervisor", "question": "older incident",
              "options": [], "recommendation": None}
        with open(os.path.join(self.repo, GATES_PENDING), "a") as fh:
            fh.write(json.dumps(r0) + "\n")
        git(self.repo, "add", GATES_PENDING)
        self.install_rejecting_hook()
        try:
            self.assertFalse(self.sup._escalate("incident D"))
        finally:
            os.remove(os.path.join(self.repo, ".git", "hooks",
                                   "pre-commit"))
        # no staged PENDING delta left behind by the failed operation
        staged = self.staged_paths()
        self.assertIn("note.txt", staged)            # pre-existing kept
        self.assertIn(GATES_PENDING, staged)         # only r0, staged BEFORE
        p = subprocess.run(
            ["git", "-C", self.repo, "show", f":{GATES_PENDING}"],
            capture_output=True, text=True, check=True)
        self.assertIn("gate-staged-before", p.stdout)
        self.assertNotIn("incident D", p.stdout)     # own delta unstaged
        # worktree also restored to the snapshot (r0 present, D absent)
        with open(os.path.join(self.repo, GATES_PENDING)) as fh:
            wt = fh.read()
        self.assertIn("gate-staged-before", wt)
        self.assertNotIn("incident D", wt)
        # assert_index_clean contract: only the PRE-EXISTING staged
        # changes remain; after committing them, answers are unblocked
        git(self.repo, "commit", "-q", "-m", "pre-existing staged work")
        self.bus.assert_index_clean("after rollback + normal commit")

    def test_committed_check_exact_match_no_substring_false_positive(self):
        # HEAD has a row whose QUESTION TEXT contains the string
        # 'gate-residue'; the uncommitted supervisor row's id IS
        # 'gate-residue'. Substring matching would falsely read it as
        # committed.
        row = {"id": "gate-111", "ts": "2026-11-04T00:00:00Z",
               "seat": "builder",
               "question": "crash reported near gate-residue seat",
               "options": [], "recommendation": None}
        with open(os.path.join(self.repo, GATES_PENDING), "a") as fh:
            fh.write(json.dumps(row) + "\n")
        git(self.repo, "add", GATES_PENDING)
        git(self.repo, "commit", "-q", "-m", "commit builder row")
        residue = {"id": "gate-residue", "ts": "2026-11-04T00:00:01Z",
                   "seat": "supervisor", "question": "incident M",
                   "options": [], "recommendation": None}
        with open(os.path.join(self.repo, GATES_PENDING), "a") as fh:
            fh.write(json.dumps(residue) + "\n")
        before = self.commit_count()
        self.assertTrue(self.sup._escalate("incident M"))
        # it must have RECOMMITTED (not false-positive True), and the
        # exact id is now in HEAD
        self.assertEqual(self.commit_count(), before + 1)
        self.assertTrue(self.head_pending_contains("gate-residue"))
        self.assertTrue(self.head_pending_contains("gate-111"))


if __name__ == "__main__":
    unittest.main()
