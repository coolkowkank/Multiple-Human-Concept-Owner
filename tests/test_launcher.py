"""Mechanism tests for the team launcher.

Every test runs on real git repos in tmp dirs with mock adapters:
no keys, no spend, no network. They prove the protocol machinery
(turns, leases, guards, recovery, gates), not model quality and not
week-long endurance; see docs/proposed-vs-tested.md.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from launcher.bus import Bus, STATE, LOG  # noqa: E402
from launcher.guards import check_commit  # noqa: E402
from launcher.runtime import Seat, SeatError  # noqa: E402
from launcher.adapters import AdapterError, parse_response  # noqa: E402
from launcher.supervisor import Supervisor  # noqa: E402


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args],
                          capture_output=True, text=True)


def make_repo(seats=None, brief="# Brief\nBuild something small.\n"):
    repo = tempfile.mkdtemp(prefix="launcher-test-")
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "test")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "checkout", "-q", "-B", "team-work")
    bus = Bus(repo, "team-work")
    roster = {"seats": seats or {}}
    bus.init_layout(brief_text=brief, roster=roster)
    return repo, bus


def seat_spec(script, paths, role=None):
    return {"role": role or "builder", "allowed_paths": paths,
            "adapter": {"type": "mock", "script": script}}


class BusTests(unittest.TestCase):
    def setUp(self):
        self.repo, self.bus = make_repo()

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_log_append_and_read(self):
        def mut():
            self.bus.append_log("builder", "handoff", "did work", turn_seq=1)
        self.bus.transact("human: test entry", mut)
        entries = self.bus.log()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["seat"], "builder")
        self.assertEqual(entries[0]["turn_seq"], 1)

    def test_gate_open_and_answer(self):
        def mut():
            gid = self.bus.open_gate("coordinator", "spend $5?",
                                     options=["yes", "no"],
                                     recommendation="no")
            return gid
        gid = self.bus.transact("human: gate test", mut)
        self.assertEqual(len(self.bus.pending_gates()), 1)
        self.bus.transact("human: answer",
                          lambda: self.bus.answer_gate(gid, "no"))
        self.assertEqual(self.bus.pending_gates(), [])

    def test_state_roundtrip(self):
        state = self.bus.state()
        state["turn"] = "builder"
        self.bus.write_state(state)
        self.assertEqual(self.bus.state()["turn"], "builder")


class GuardTests(unittest.TestCase):
    def setUp(self):
        seats = {"builder": seat_spec([], ["src/"])}
        self.repo, self.bus = make_repo(seats=seats)
        state = self.bus.state()
        state["turn"] = "builder"
        state["status"] = "running"
        self.bus.write_state(state)
        self.bus.commit_all("human: turn issued")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_valid_seat_commit_allowed(self):
        problems = check_commit(self.repo, "TURN: builder acting", ["src/app.py"])
        self.assertEqual(problems, [])

    def test_off_turn_commit_rejected(self):
        problems = check_commit(self.repo, "TURN: reviewer acting", ["src/app.py"])
        self.assertTrue(any("turn holder" in p for p in problems))

    def test_missing_turn_line_rejected(self):
        problems = check_commit(self.repo, "just a commit", ["src/app.py"])
        self.assertTrue(any("TURN" in p for p in problems))

    def test_outside_paths_rejected(self):
        problems = check_commit(self.repo, "TURN: builder acting",
                                ["secret/keys.txt"])
        self.assertTrue(any("outside its allowed paths" in p for p in problems))

    def test_operational_prefix_bypasses(self):
        self.assertEqual(check_commit(self.repo, "human: gate answer",
                                      ["anything"]), [])
        self.assertEqual(check_commit(self.repo, "supervisor: restart",
                                      ["anything"]), [])

    def test_setup_turn_allowed(self):
        self.assertEqual(check_commit(self.repo, "TURN: setup", ["anything"]), [])


class SeatTests(unittest.TestCase):
    def test_path_escape_rejected(self):
        seats = {"builder": seat_spec(
            [{"summary": "evil", "writes": {"../evil.txt": "x"},
              "verify_command": None, "handoff": None}], ["src/"])}
        repo, bus = make_repo(seats=seats)
        try:
            state = bus.state()
            state["turn"] = "builder"
            bus.write_state(state)
            bus.commit_all("human: go")
            seat = Seat(bus, "builder")
            with self.assertRaises(SeatError):
                seat.act_once()
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_unknown_handoff_rejected(self):
        seats = {"builder": seat_spec(
            [{"summary": "x", "writes": {"src/a": "b"},
              "verify_command": None, "handoff": "ghost"}], ["src/"])}
        repo, bus = make_repo(seats=seats)
        try:
            state = bus.state()
            state["turn"] = "builder"
            bus.write_state(state)
            bus.commit_all("human: go")
            with self.assertRaises(SeatError):
                Seat(bus, "builder").act_once()
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_lease_blocks_second_holder(self):
        script = [{"summary": "work", "writes": {"src/a": "b"},
                   "verify_command": None, "handoff": None}]
        seats = {"builder": seat_spec(script, ["src/"])}
        repo, bus = make_repo(seats=seats)
        try:
            state = bus.state()
            state["turn"] = "builder"
            bus.write_state(state)
            bus.commit_all("human: go")
            first = Seat(bus, "builder", instance_id="one", lease_ttl=9999)
            second = Seat(bus, "builder", instance_id="two", lease_ttl=9999)
            self.assertTrue(first.act_once())
            # Same turn still names builder (handoff None, status running):
            state = bus.state()
            state["turn"] = "builder"
            bus.write_state(state)
            bus.commit_all("human: reissue")
            with self.assertRaises(SeatError):
                second.act_once()
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_adapter_crash_leaves_turn_for_retry(self):
        calls = []

        def flaky(system, prompt, i):
            calls.append(i)
            if i == 0:
                raise AdapterError("simulated crash")
            return {"summary": "recovered", "writes": {"src/a": "b"},
                    "verify_command": None, "handoff": None,
                    "status_line": "ok"}

        # roster.json must stay JSON-serializable, so the seat is created
        # with an empty script and the flaky callable is injected directly.
        seats = {"builder": {"role": "builder", "allowed_paths": ["src/"],
                             "adapter": {"type": "mock", "script": []}}}
        repo, bus = make_repo(seats=seats)
        try:
            state = bus.state()
            state["turn"] = "builder"
            bus.write_state(state)
            bus.commit_all("human: go")
            seat = Seat(bus, "builder")
            from launcher.adapters import MockAdapter
            seat.adapter = MockAdapter(flaky)
            with self.assertRaises(SeatError):
                seat.act_once()
            # The crash was inside the transaction: no commit, turn kept.
            self.assertEqual(bus.state()["turn"], "builder")
            self.assertTrue(seat.act_once())
            self.assertEqual(len(calls), 2)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_verify_exit_code_recorded(self):
        script = [{"summary": "built", "writes": {"src/x.txt": "hi"},
                   "verify_command": "test -f src/x.txt", "handoff": None}]
        seats = {"builder": seat_spec(script, ["src/"])}
        repo, bus = make_repo(seats=seats)
        try:
            state = bus.state()
            state["turn"] = "builder"
            bus.write_state(state)
            bus.commit_all("human: go")
            Seat(bus, "builder").act_once()
            entries = [e for e in bus.log() if e["kind"] == "handoff"]
            self.assertIn("exit=0", entries[-1]["body"])
        finally:
            shutil.rmtree(repo, ignore_errors=True)


class ParseTests(unittest.TestCase):
    def test_bare_json(self):
        self.assertEqual(parse_response('{"a": 1}'), {"a": 1})

    def test_fenced_json(self):
        self.assertEqual(parse_response('blah\n```json\n{"a": 2}\n```\n'),
                         {"a": 2})

    def test_garbage_raises(self):
        with self.assertRaises(AdapterError):
            parse_response("not json at all")


class SupervisorTests(unittest.TestCase):
    def test_done_cycle_and_stop(self):
        script = [{"summary": "all done", "writes": {},
                   "verify_command": None, "handoff": None,
                   "status_line": "DONE - finished"}]
        seats = {"worker": {"role": "builder", "allowed_paths": ["src/"],
                            "adapter": {"type": "mock", "script": script}}}
        repo, bus = make_repo(seats=seats)
        try:
            state = bus.state()
            state["turn"] = "worker"
            state["status"] = "running"
            bus.write_state(state)
            bus.commit_all("human: go")
            sup = Supervisor(repo, "team-work", poll=0.2, stall_timeout=30)
            self.assertEqual(sup.run(max_seconds=60), "done")
            self.assertEqual(bus.state()["status"], "done")
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_crashed_seat_restarted_then_escalated(self):
        seats = {"worker": {"role": "builder", "allowed_paths": ["src/"],
                            "adapter": {"type": "mock", "script": []}}}
        repo, bus = make_repo(seats=seats)
        try:
            state = bus.state()
            state["turn"] = "worker"
            state["status"] = "running"
            bus.write_state(state)
            bus.commit_all("human: go")
            sup = Supervisor(repo, "team-work", poll=0.2, restart_limit=2)
            self.assertEqual(sup.run(max_seconds=30), "timeout")
            gates = bus.pending_gates()
            self.assertTrue(any("worker" in g["question"] for g in gates),
                            f"expected escalation gate, got {gates}")
            self.assertGreaterEqual(sup.restarts.get("worker", 0), 2)
        finally:
            shutil.rmtree(repo, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
