"""Integration evidence: real processes, real clones, live relay and
webhook together. Models are still mocks - these tests prove the
transport and supervision machinery, not model behavior."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from launcher.bus import Bus  # noqa: E402
from launcher.runtime import Seat  # noqa: E402
from launcher.supervisor import Supervisor  # noqa: E402


def git(repo, *args):
    proc = subprocess.run(["git", "-C", repo, *args],
                          capture_output=True, text=True)
    assert proc.returncode == 0, f"git {args}: {proc.stderr}"
    return proc


def spec(script, paths, role):
    return {"role": role, "allowed_paths": paths,
            "adapter": {"type": "mock", "script": script}}


class CrossCloneBusTests(unittest.TestCase):
    """Two separate clones synchronize through a shared remote: the
    git bus as real cross-checkout transport."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="launcher-xclone-")
        self.origin = os.path.join(self.root, "origin.git")
        git(self.root, "init", "--bare", "--quiet", self.origin)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _clone(self, name):
        path = os.path.join(self.root, name)
        git(self.root, "clone", "--quiet", self.origin, path)
        git(path, "config", "user.name", name)
        git(path, "config", "user.email", f"{name}@example.com")
        return path

    def test_handoff_crosses_clones_without_duplication(self):
        a = self._clone("a")
        bus_a = Bus(a, "team-work")
        roster = {"seats": {
            "alpha": spec([{"summary": "alpha work",
                            "writes": {"work/alpha.txt": "done by alpha"},
                            "verify_command": None, "handoff": "beta"}],
                          ["work/"], "builder"),
            "beta": spec([{"summary": "beta confirms",
                           "writes": {"work/beta.txt": "done by beta"},
                           "verify_command": None, "handoff": None,
                           "status_line": "DONE - both seats delivered"}],
                         ["work/"], "reviewer"),
        }}
        bus_a.init_layout(brief_text="# Brief\nTwo seats, two clones.\n",
                          roster=roster)
        git(a, "checkout", "--quiet", "-B", "team-work")
        bus_a.commit_all("human: layout") or None
        bus_a.push()
        git(a, "push", "--quiet", "-u", "origin", "team-work")

        b = self._clone("b")
        git(b, "checkout", "--quiet", "-B", "team-work",
            "origin/team-work")
        bus_b = Bus(b, "team-work")

        # Seed the first turn from clone A and publish it.
        state = bus_a.state()
        state["turn"] = "alpha"
        state["status"] = "running"
        bus_a.write_state(state)
        bus_a.commit_all("human: first turn")
        bus_a.push()

        # Alpha acts in clone A; beta must see it in clone B.
        self.assertTrue(Seat(bus_a, "alpha").act_once())
        self.assertTrue(Seat(bus_b, "beta").act_once())

        state_b = bus_b.state()
        self.assertEqual(state_b["status"], "done")
        handoffs = [e for e in bus_b.log() if e["kind"] == "handoff"]
        self.assertEqual([e["seat"] for e in handoffs], ["alpha", "beta"])
        # alpha's file arrived in B exactly once, through the remote.
        bus_b.pull()
        with open(os.path.join(b, "work", "alpha.txt")) as fh:
            self.assertEqual(fh.read(), "done by alpha")
        log_b = git(b, "log", "--format=%s").stdout
        self.assertEqual(log_b.count("TURN: alpha acting"), 1)


class FullTransportTests(unittest.TestCase):
    """Supervisor + relay server + webhook receiver + seat subprocesses
    in one run: the wake channels actually carry signals."""

    def test_supervised_cycle_with_live_wake_channels(self):
        root = tempfile.mkdtemp(prefix="launcher-transport-")
        received = {"webhook": []}
        try:
            from launcher.relay import RelayState, make_handler
            relay_server = ThreadingHTTPServer(
                ("127.0.0.1", 0), make_handler(RelayState("tok")))
            threading.Thread(target=relay_server.serve_forever,
                             daemon=True).start()
            relay_port = relay_server.server_address[1]

            class Hook(BaseHTTPRequestHandler):
                def do_POST(self):
                    n = int(self.headers.get("content-length", 0))
                    received["webhook"].append(self.rfile.read(n).decode())
                    self.send_response(200)
                    self.end_headers()

                def log_message(self, *a):
                    pass

            hook_server = ThreadingHTTPServer(("127.0.0.1", 0), Hook)
            threading.Thread(target=hook_server.serve_forever,
                             daemon=True).start()
            hook_port = hook_server.server_address[1]

            repo = os.path.join(root, "repo")
            os.makedirs(repo)
            git(repo, "init", "--quiet")
            git(repo, "config", "user.name", "t")
            git(repo, "config", "user.email", "t@example.com")
            git(repo, "checkout", "--quiet", "-B", "team-work")
            bus = Bus(repo, "team-work")
            bus.init_layout(brief_text="# Brief\nOne worker seat.\n",
                            roster={"seats": {
                                "worker": spec(
                                    [{"summary": "work done",
                                      "writes": {"work/x.txt": "x"},
                                      "verify_command": None,
                                      "handoff": None,
                                      "status_line": "DONE - shipped"}],
                                    ["work/"], "builder")}})
            state = bus.state()
            state["turn"] = "worker"
            state["status"] = "running"
            bus.write_state(state)
            bus.commit_all("human: go")

            os.environ["TEAM_RELAY_URL"] = f"http://127.0.0.1:{relay_port}"
            os.environ["TEAM_RELAY_TOKEN"] = "tok"
            os.environ["TEAM_WAKE_WEBHOOK"] = \
                f"http://127.0.0.1:{hook_port}/hook"
            try:
                sup = Supervisor(repo, "team-work", poll=0.2,
                                 stall_timeout=30)
                self.assertEqual(sup.run(max_seconds=60), "done")
            finally:
                for var in ("TEAM_RELAY_URL", "TEAM_RELAY_TOKEN",
                            "TEAM_WAKE_WEBHOOK"):
                    os.environ.pop(var, None)
                relay_server.shutdown()
                hook_server.shutdown()

            self.assertTrue(received["webhook"],
                            "webhook endpoint received no wake")
            self.assertIn("worker", received["webhook"][0])
            self.assertEqual(bus.state()["status"], "done")
            self.assertTrue(os.path.exists(
                os.path.join(repo, "work", "x.txt")))
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
