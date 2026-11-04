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
        self.assertEqual(check_commit(self.repo, "operator: glue commit",
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


class RelayTests(unittest.TestCase):
    def _server(self):
        import threading
        from http.server import ThreadingHTTPServer
        from launcher.relay import RelayState, make_handler
        state = RelayState("tok")
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, server.server_address[1]

    def test_post_and_longpoll(self):
        from launcher.relay import RelayClient
        server, port = self._server()
        try:
            c = RelayClient(f"http://127.0.0.1:{port}", "tok")
            seq = c.post("builder", "wake", "turn -> reviewer")
            self.assertEqual(seq, 1)
            msgs = c.since(0, wait=1)
            self.assertEqual(msgs[0]["body"], "turn -> reviewer")
            self.assertEqual(c.since(1, wait=0), [])
        finally:
            server.shutdown()

    def test_bad_token_rejected(self):
        from launcher.relay import RelayClient
        server, port = self._server()
        try:
            c = RelayClient(f"http://127.0.0.1:{port}", "wrong")
            with self.assertRaises(Exception):
                c.post("x", "wake", "y")
        finally:
            server.shutdown()

    def test_seat_falls_back_when_relay_down(self):
        from launcher.relay import RelayClient
        script = [{"summary": "s", "writes": {"src/a": "b"},
                   "verify_command": None, "handoff": None}]
        seats = {"builder": seat_spec(script, ["src/"])}
        repo, bus = make_repo(seats=seats)
        try:
            dead = RelayClient("http://127.0.0.1:1", "tok", timeout=1)
            seat = Seat(bus, "builder", poll_interval=0, relay=dead)
            seat._wait()  # must not raise; drops the dead relay
            self.assertIsNone(seat.relay)
        finally:
            shutil.rmtree(repo, ignore_errors=True)


class WebhookTests(unittest.TestCase):
    def test_wake_reaches_configured_endpoint(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        got = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("content-length", 0))
                got.append(self.rfile.read(n).decode())
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            from launcher.relay import WebhookSink
            url = f"http://127.0.0.1:{server.server_address[1]}/hook"
            self.assertEqual(WebhookSink(url).post("builder", "wake", "turn -> qc"), 200)
            self.assertIn("turn -> qc", got[0])
        finally:
            server.shutdown()

    def test_seat_signals_webhook_without_breaking_on_failure(self):
        from launcher.relay import WebhookSink
        script = [{"summary": "s", "writes": {"src/a": "b"},
                   "verify_command": None, "handoff": None}]
        seats = {"builder": seat_spec(script, ["src/"])}
        repo, bus = make_repo(seats=seats)
        try:
            state = bus.state()
            state["turn"] = "builder"
            bus.write_state(state)
            bus.commit_all("human: go")
            # Dead endpoint: the seat still completes its turn.
            seat = Seat(bus, "builder",
                        webhook=WebhookSink("http://127.0.0.1:1", timeout=1))
            self.assertTrue(seat.act_once())
        finally:
            shutil.rmtree(repo, ignore_errors=True)


class ConformanceTests(unittest.TestCase):
    def test_demo_repo_conforms(self):
        from launcher.demo import run_demo
        from launcher.conformance import check_repo
        d = tempfile.mkdtemp(prefix="launcher-conform-")
        try:
            run_demo(d)
            problems, notes = check_repo(d)
            self.assertEqual(problems, [], f"demo repo nonconformant: {problems}")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_broken_records_detected(self):
        from launcher.conformance import check_repo
        repo, bus = make_repo(seats={"builder": seat_spec([], ["src/"])})
        try:
            with open(os.path.join(repo, ".team", "LOG.jsonl"), "a") as fh:
                fh.write('{"ts":"t","seat":"ghost","kind":"weird","body":"b","turn_seq":5}\n')
                fh.write('{"ts":"t","seat":"builder","kind":"handoff","body":"did x | verify: `pytest`","turn_seq":3}\n')
                fh.write('{"ts":"t","seat":"builder","kind":"handoff","body":"again | verify: `pytest` exit=0","turn_seq":2}\n')
                fh.write('not json\n')
            problems, _ = check_repo(repo)
            text = "\n".join(problems)
            self.assertIn("unknown kind", text)
            self.assertIn("not a roster seat", text)
            self.assertIn("not strictly increasing", text)
            self.assertIn("records no exit code", text)
            self.assertIn("invalid JSON", text)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_orphan_gate_answer_detected(self):
        from launcher.conformance import check_repo
        repo, bus = make_repo(seats={"builder": seat_spec([], ["src/"])})
        try:
            bus.answer_gate("gate-nope", "yes")
            problems, _ = check_repo(repo)
            self.assertTrue(any("unknown gate" in p for p in problems))
        finally:
            shutil.rmtree(repo, ignore_errors=True)


class ConformanceSeqTests(unittest.TestCase):
    def _repo_with_log(self, lines):
        repo, bus = make_repo(seats={"builder": seat_spec([], ["src/"])})
        with open(os.path.join(repo, ".team", "LOG.jsonl"), "a") as fh:
            for l in lines:
                fh.write(l + "\n")
        self.addCleanup(shutil.rmtree, repo, True)
        return repo

    def test_status_annotations_may_reference_any_seq(self):
        from launcher.conformance import check_repo
        repo = self._repo_with_log([
            '{"ts":"t","seat":"builder","kind":"handoff","body":"x","turn_seq":1}',
            '{"ts":"t","seat":"builder","kind":"status","body":"note about turn 1","turn_seq":1}',
            '{"ts":"t","seat":"builder","kind":"status","body":"late correction","turn_seq":0}',
        ])
        from launcher.conformance import check_repo
        problems, _ = check_repo(repo)
        self.assertEqual(problems, [], f"annotations flagged: {problems}")

    def test_duplicate_or_decreasing_handoff_seq_flagged(self):
        from launcher.conformance import check_repo
        repo = self._repo_with_log([
            '{"ts":"t","seat":"builder","kind":"handoff","body":"x","turn_seq":1}',
            '{"ts":"t","seat":"builder","kind":"handoff","body":"retry","turn_seq":1}',
        ])
        problems, _ = check_repo(repo)
        self.assertTrue(any("not strictly increasing" in p for p in problems))


class MockQueueTests(unittest.TestCase):
    def _queue(self, responses):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as fh:
            for r in responses:
                fh.write(json.dumps(r) + "\n")
        self.addCleanup(os.unlink, path)
        return path

    def test_peek_then_consume_persists_across_processes(self):
        from launcher.adapters import MockAdapter
        path = self._queue([{"summary": "turn one"}, {"summary": "turn two"}])
        a = MockAdapter([], script_path=path)
        r1 = a.complete("s", "p")
        # peek alone must not consume: a failed turn loses nothing
        self.assertEqual(MockAdapter([], script_path=path)
                         .complete("s", "p")["summary"], "turn one")
        a.consume()
        # next process reads the next response
        self.assertEqual(MockAdapter([], script_path=path)
                         .complete("s", "p")["summary"], "turn two")
        self.assertEqual(r1["summary"], "turn one")

    def test_empty_queue_raises(self):
        from launcher.adapters import MockAdapter, AdapterError
        path = self._queue([])
        with self.assertRaises(AdapterError):
            MockAdapter([], script_path=path).complete("s", "p")

    def test_consume_rejects_changed_queue(self):
        from launcher.adapters import MockAdapter, AdapterError
        path = self._queue([{"summary": "turn one"}])
        a = MockAdapter([], script_path=path)
        a.complete("s", "p")
        with open(path, "w") as fh:
            fh.write('{"summary": "swapped"}\n')
        with self.assertRaises(AdapterError):
            a.consume()


class FalseGreenTests(unittest.TestCase):
    def test_claimed_green_cannot_override_recorded_exit_code(self):
        # Builder's prose claims green; the runtime records the true
        # nonzero exit code, so the false claim is visible in the record.
        script = [{"summary": "all suites green",
                   "writes": {"src/a": "b"},
                   "verify_command": "exit 1",
                   "handoff": "reviewer"}]
        seats = {"builder": seat_spec(script, ["src/"]),
                 "reviewer": seat_spec([], ["review/"], role="reviewer")}
        repo, bus = make_repo(seats=seats)
        try:
            state = bus.state()
            state["turn"] = "builder"
            state["status"] = "running"
            bus.write_state(state)
            bus.commit_all("human: go")
            Seat(bus, "builder").act_once()
            entry = [e for e in bus.log() if e["kind"] == "handoff"][-1]
            self.assertIn("exit=1", entry["body"])
            self.assertIn("all suites green", entry["body"])
        finally:
            shutil.rmtree(repo, ignore_errors=True)
