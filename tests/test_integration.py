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


class RaceAndResumeTests(unittest.TestCase):
    """Stage 3 machinery: lost commit races and fresh-session resume."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="launcher-race-")
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

    def _seed_remote(self):
        a = self._clone("a")
        bus = Bus(a, "team-work")
        bus.init_layout(brief_text="# Brief\nRace test.\n",
                        roster={"seats": {
                            "alpha": spec([], ["work/"], "builder"),
                            "beta": spec([], ["work/"], "reviewer")}})
        git(a, "checkout", "--quiet", "-B", "team-work")
        bus.commit_all("human: layout")
        git(a, "push", "--quiet", "-u", "origin", "team-work")
        return a

    def test_lost_race_retries_and_both_writes_survive(self):
        a = self._seed_remote()
        b = self._clone("b")
        git(b, "checkout", "--quiet", "-B", "team-work", "origin/team-work")
        bus_a, bus_b = Bus(a, "team-work"), Bus(b, "team-work")

        # B commits and pushes first; A's transact must rebase and retry,
        # and both writes must survive exactly once.
        bus_b.transact("human: b first",
                       lambda: bus_b.append_log("beta", "status", "b was here"))
        bus_a.transact("human: a second",
                       lambda: bus_a.append_log("alpha", "status", "a was here"))
        bus_b.pull()
        kinds = [(e["seat"], e["body"]) for e in bus_b.log()
                 if e["kind"] == "status"]
        self.assertEqual(sorted(kinds),
                         [("alpha", "a was here"), ("beta", "b was here")])
        log_b = git(b, "log", "--format=%s").stdout
        self.assertEqual(log_b.count("a second"), 1)

    def test_lost_race_replays_same_queued_response_exactly_once(self):
        from launcher.bus import BusError
        a = self._seed_remote()
        # alpha gets a script_path queue (multi-process turn responses)
        import json as _json
        roster_path = os.path.join(a, ".team", "roster.json")
        roster = _json.load(open(roster_path))
        roster["seats"]["alpha"]["adapter"] = {
            "type": "mock", "script_path": "work/.alpha.jsonl"}
        _json.dump(roster, open(roster_path, "w"), indent=2)
        os.makedirs(os.path.join(a, "work"), exist_ok=True)
        with open(os.path.join(a, "work", ".alpha.jsonl"), "w") as fh:
            fh.write(_json.dumps(
                {"writes": {"work/x.txt": "hello"},
                 "summary": "alpha turn one", "handoff": "beta"}) + "\n")
            fh.write(_json.dumps(
                {"summary": "alpha later turn", "handoff": "beta"}) + "\n")
        bus0 = Bus(a, "team-work")
        state = bus0.state()
        state["turn"] = "alpha"
        bus0.write_state(state)
        bus0.commit_all("human: alpha queued, turn issued")
        bus0.push()

        bus_a = Bus(a, "team-work")
        pushes = []
        orig_push = bus_a.push
        def flaky_push():
            pushes.append(1)
            if len(pushes) == 1:
                raise BusError("simulated lost race")
            return orig_push()
        bus_a.push = flaky_push

        seat = Seat(bus_a, "alpha")
        self.assertTrue(seat.act_once())
        self.assertEqual(len(pushes), 2)  # one lost race, one success
        handoffs = [e for e in bus_a.log()
                    if e["kind"] == "handoff" and e["seat"] == "alpha"]
        self.assertEqual(len(handoffs), 1)  # applied exactly once
        self.assertEqual(handoffs[0]["body"].split(" | ")[0],
                         "alpha turn one")
        self.assertEqual(open(os.path.join(a, "work", "x.txt")).read(),
                         "hello")
        remaining = open(os.path.join(a, "work", ".alpha.jsonl")).read()
        self.assertNotIn("turn one", remaining)   # consumed once
        self.assertIn("later turn", remaining)     # next response intact

    def test_fresh_session_resumes_from_record_alone(self):
        a = self._seed_remote()
        bus_a = Bus(a, "team-work")
        bus_a.transact("human: seed", lambda: (
            bus_a.append_log("alpha", "handoff", "batch 3 done", turn_seq=7),
            bus_a.open_gate("alpha", "proceed to hosted?", ["yes", "no"])))
        state = bus_a.state()
        state["turn"] = "beta"
        state["turn_seq"] = 7
        state["status"] = "running"
        bus_a.write_state(state)
        bus_a.commit_all("human: turn to beta")
        bus_a.push()

        b = self._clone("b")
        git(b, "checkout", "--quiet", "-B", "team-work", "origin/team-work")
        bus_b = Bus(b, "team-work")
        bus_b.pull()
        state = bus_b.state()
        self.assertEqual((state["turn"], state["turn_seq"]), ("beta", 7))
        self.assertEqual(len(bus_b.pending_gates()), 1)
        self.assertEqual(bus_b.log()[-1]["turn_seq"], 7)

    def test_stale_lease_takeover_after_crash(self):
        repo, bus = make_repo_for(self.root)
        state = bus.state()
        state["turn"] = "builder"
        state["status"] = "running"
        bus.write_state(state)
        bus.commit_all("human: go")
        script = [{"summary": "s", "writes": {"work/a": "b"},
                   "verify_command": None, "handoff": None}]
        bus.transact("human: roster", lambda: None)
        roster = bus.roster()
        roster["seats"]["builder"]["adapter"] = {"type": "mock", "script": script}
        with open(os.path.join(repo, ".team", "roster.json"), "w") as fh:
            json.dump(roster, fh)
        bus.commit_all("human: script")

        # First instance crashes mid-turn: lease held, no work committed.
        crashed = Seat(bus, "builder", instance_id="dead", lease_ttl=0)
        crashed.claim_lease(state)
        bus.write_state(state)
        bus.commit_all("human: lease taken")
        # Replacement process: stale lease (ttl 0) must not block takeover.
        replacement = Seat(bus, "builder", instance_id="new", lease_ttl=0)
        self.assertTrue(replacement.act_once())
        self.assertEqual(bus.state()["leases"]["builder"]["holder"], "new")


def make_repo_for(root):
    repo = os.path.join(root, "lease-repo")
    os.makedirs(repo)
    git(repo, "init", "--quiet")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "checkout", "--quiet", "-B", "team-work")
    bus = Bus(repo, "team-work")
    bus.init_layout(brief_text="# Brief\nLease test.\n",
                    roster={"seats": {"builder": spec([], ["work/"], "builder")}})
    return repo, bus


class CrossCloneQueueBindingTests(unittest.TestCase):
    """Stale queued responses are refused across real clones and real
    processes - the cross-machine case from the live-1 major finding,
    proven through the actual CLI + seat path, not a unit mock."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="launcher-xbind-")
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

    def _repo(self, path):
        from launcher.bus import Bus
        bus = Bus(path, "team-work")
        bus.init_layout(brief_text="# Brief\n", roster={
            "seats": {
                "builder": {"role": "builder", "allowed_paths": ["src/"],
                            "adapter": {"type": "queue",
                                        "path": ".team/queues/b.jsonl"}},
                "reviewer": {"role": "reviewer", "allowed_paths": ["review/"],
                             "adapter": {"type": "mock", "script": []}},
            }})
        git(path, "checkout", "--quiet", "-B", "team-work")
        bus.commit_all("operator: init layout")
        return bus

    def _respond(self, repo, summary):
        cli = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "launcher", "cli.py")
        scratch = tempfile.mkdtemp(prefix="launcher-scratch-")
        self.addCleanup(shutil.rmtree, scratch, True)
        payload = os.path.join(scratch, "resp.json")
        with open(payload, "w") as fh:
            json.dump({"summary": summary, "writes": {}, "handoff":
                       "reviewer", "status_line": "s"}, fh)
        proc = subprocess.run(
            [sys.executable, "-m", "launcher", "respond", "builder",
             "--repo", repo, "--branch", "team-work", "--file", payload],
            capture_output=True, text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        assert proc.returncode == 0, proc.stderr
        return proc.stdout

    def test_stale_response_refused_across_clones(self):
        a = self._clone("a")
        bus_a = self._repo(a)
        bus_a.push()
        state = bus_a.state()
        state["turn"] = "builder"
        state["status"] = "running"
        bus_a.write_state(state)
        bus_a.commit_all("operator: turn to builder")
        bus_a.push()
        # operator reasons against turn=builder seq=0 and queues
        out = self._respond(a, "reasoned at seq 0")
        self.assertIn("seq=0", out)
        # the bus moves meanwhile: two turns pass in another clone
        b = self._clone("b")
        bus_b = self._repo_pull(b)
        state = bus_b.state()
        state["turn_seq"] += 2
        bus_b.write_state(state)
        bus_b.commit_all("operator: two turns passed elsewhere")
        bus_b.push()
        # clone a pulls the movement, then the seat refuses the stale line
        from launcher.runtime import Seat, SeatError
        with self.assertRaises(SeatError) as ctx:
            Seat(bus_a, "builder").act_once()
        self.assertIn("stale", str(ctx.exception))
        with open(os.path.join(a, ".team/queues/b.jsonl")) as fh:
            self.assertNotEqual(fh.read().strip(), "")
        # nothing was applied: seq and turn are exactly as clone b left them
        self.assertEqual(bus_a.state()["turn_seq"], state["turn_seq"])
        self.assertEqual(bus_a.state()["turn"], "builder")

    def _repo_pull(self, path):
        from launcher.bus import Bus
        git(path, "checkout", "--quiet", "-B", "team-work",
            "origin/team-work")
        bus = Bus(path, "team-work")
        bus.pull()
        return bus


class FreshCloneAdopterTests(unittest.TestCase):
    """The owner's acceptance path, mechanically: an adopter clones this
    blueprint repo, points its commands at their OWN fresh target repo,
    initializes the team there, and the installed layout is complete.
    Offline; scripted/queue seats only - a live adopter-AI cycle is the
    separate bounded proposal in docs/proposals/."""

    def test_clone_init_status_path(self):
        import shutil, subprocess, tempfile
        blueprint_src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        clone = os.path.join(d, "blueprint-clone")
        target = os.path.join(d, "adopter-target")
        subprocess.run(["git", "clone", "--quiet", blueprint_src, clone],
                       check=True, capture_output=True)
        subprocess.run(["git", "init", "--quiet", target], check=True,
                       capture_output=True)
        subprocess.run(["git", "-C", target, "-c", "user.name=t",
                        "-c", "user.email=t@t", "commit", "--quiet",
                        "--allow-empty", "-m", "init"], check=True,
                       capture_output=True)
        brief = os.path.join(d, "brief.md")
        with open(brief, "w") as fh:
            fh.write("# Concept\n\nBuild a fizzbuzz CLI.\n")
        env = dict(os.environ, PYTHONPATH=clone)
        def launcher(*args):
            return subprocess.run(
                [sys.executable, "-m", "launcher"] + list(args),
                cwd=clone, env=env, capture_output=True, text=True)
        r = launcher("init", "--repo", target, "--branch", "team-work",
                     "--default-roster", "--brief", brief)
        self.assertEqual(r.returncode, 0, r.stderr)
        # installed in the TARGET repo, not the clone
        for rel in (".team/STATE.json", ".team/roster.json",
                    ".team/brief.md", ".team/LOG.jsonl"):
            self.assertTrue(os.path.exists(os.path.join(target, rel)), rel)
        self.assertTrue(os.access(
            os.path.join(target, ".git", "hooks", "commit-msg"), os.X_OK))
        self.assertIn("fizzbuzz", open(os.path.join(target, ".team", "brief.md")).read())
        roster = json.load(open(os.path.join(target, ".team", "roster.json")))
        self.assertIn("coordinator", roster["seats"])
        # no .team leaked into the blueprint clone
        self.assertFalse(os.path.exists(os.path.join(clone, ".team")))
        r = launcher("status", "--repo", target, "--branch", "team-work")
        self.assertEqual(r.returncode, 0, r.stderr)
        # the unattended entry point guards budgets (mock roster here is
        # not flagged; http seats without call_budget would be)
        from launcher.cli import unbounded_http_seats
        self.assertEqual(unbounded_http_seats(target, "team-work"), [])
