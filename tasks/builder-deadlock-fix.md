# Builder task v6: fix null-handoff routing failure + stall-clock timezone bug

Tools: edit_file, write_file, git_commit, git_push ONLY (no read/list/shell).
edit_file replaces ONE exact occurrence of old_string with new_string in an
existing file. old_string MUST be copied VERBATIM from the embedded source
below - every space, quote and line break; do NOT reformat or paraphrase it.
It must match exactly once; on "not found" or "N locations" the file is
UNCHANGED - retry with a longer verbatim anchor. write_file is for NEW
files only (content <= 2000 bytes for this task).
JSON: each newline inside a string value is the two characters \ and n
(JSON escaping) - exactly once, never double-escaped. A string value ends
with one plain quote, then a comma or the closing brace. The arguments
object of write_file has EXACTLY two keys: "path" and "content". Never add
a third key. ONE tool call per round.

## Defects (from the live run record)

1. _check_stall parses turn_since (UTC "Z" stamp) with time.mktime, which
   treats it as LOCAL time: in a UTC+2 container every new turn is
   instantly "2 hours stalled" and the supervisor SIGTERMs the fresh seat
   seconds after each handoff.
2. A seat returned handoff=null; runtime wrote STATE.turn=None; all seats
   idle, _check_stall returns on falsy turn, first-turn seed only fires
   while "forming": silent permanent hang until a human re-issued the
   turn by hand.

## Required changes (launcher/supervisor.py ONLY, via edit_file anchors)

A. UTC parse: use calendar.timegm (add `import calendar` to the import
   block) so turn_since parses as UTC, not local. Unparseable stamp: skip
   the check, as now.
B. When state["status"]=="running" and state["turn"] is falsy, treat as a
   routing failure: append a LOUD log entry (kind "routing-failure")
   quoting the bus record; re-issue state["turn"]="coordinator" with a
   fresh turn_since, write state, commit (prefix "supervisor:" allowed).
   On the SECOND consecutive occurrence escalate via _escalate() instead.
   Track consecutive occurrences in a small instance counter. NEVER
   fabricate or rewrite the model's routing decision. A falsy turn with
   status "done" is a VALID terminal state: do nothing there.
C. Do not change any other file. Do not modify tests/test_launcher.py.

## Plan (one tool call per round; calls are spaced >=65s apart)

Round 1: edit_file launcher/supervisor.py, old_string (verbatim):
  "import os\nimport subprocess\nimport sys\nimport time"
  new_string:
  "import calendar\nimport os\nimport subprocess\nimport sys\nimport time"
Round 2: edit_file launcher/supervisor.py, old_string = the ENTIRE current
  _check_stall method copied VERBATIM from the embedded source below; new
  string = your fixed method (UTC parse + routing-failure branch before
  the stall logic; keep the existing stall/escalate behavior otherwise).
Round 3: write_file tests/test_deadlock_fix.py (NEW, TINY: <= 2000 bytes,
  3 short test methods, no comments needed): a 5-second-old UTC turn_since
  must NOT be stalled under a non-UTC local TZ (set os.environ["TZ"] +
  time.tzset(), restore after); running+turn=None => re-issue to
  coordinator + "routing-failure" log; second consecutive => escalation
  gate; done+turn=None => nothing. Plain unittest, temp dirs, no network.
Round 4: git_commit (message must contain a line exactly `TURN: builder`;
  describe what YOU actually changed - if a round failed, say so).
Round 5: git_push. The run ends automatically after a successful push.

## Current launcher/supervisor.py (verbatim - copy anchors from this)

```python
"""The supervisor: keeps the team alive without a human watcher.

Starts one process per automated seat, restarts crashed seats with
backoff, detects a stalled turn (the seat holding the turn has produced
no bus write within stall_timeout) and restarts or escalates, and
surfaces open human gates. This is the liveness layer the evaluations
showed humans providing by hand ("are you still watching?").

Interactive seats (a human pastes prompts into chat sessions on other
platforms) join the same bus; the supervisor cannot restart those, so a
stalled interactive seat becomes a gate for the humans instead.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

from .bus import Bus


class Supervisor:
    def __init__(self, repo, branch="team-work", stall_timeout=900,
                 restart_limit=5, poll=5, notify_command=None):
        self.bus = Bus(repo, branch)
        self.repo = repo
        self.stall_timeout = stall_timeout
        self.restart_limit = restart_limit
        self.poll = poll
        self.notify_command = notify_command
        self.procs = {}
        self.restarts = {}
        self._stalled_seats = set()
        self._notified_gates = set()

    # Seats whose responses are reasoned outside a managed process
    # (interactive human paste, assistant-mediated queue) join the same
    # bus but have no process for the supervisor to start or restart.
    EXTERNAL_TYPES = {"interactive", "queue"}

    def automated_seats(self):
        roster = self.bus.roster().get("seats", {})
        return {name: spec for name, spec in roster.items()
                if spec.get("adapter", {}).get("type")
                not in self.EXTERNAL_TYPES}

    def start_seat(self, name):
        import os
        pkg_parent = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        env = dict(os.environ)
        env["PYTHONPATH"] = pkg_parent + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.Popen(
            [sys.executable, "-m", "launcher", "seat", name,
             "--repo", self.repo, "--branch", self.bus.branch], env=env)
        self.procs[name] = proc
        return proc

    def run(self, max_seconds=None):
        start = time.time()
        self._seed_first_turn()
        for name in self.automated_seats():
            self.start_seat(name)
        while True:
            state = self.bus.state()
            if state.get("status") == "done":
                self._stop_all()
                return "done"
            if max_seconds and time.time() - start > max_seconds:
                self._stop_all()
                return "timeout"
            self._reap_and_restart()
            self._check_stall(state)
            self._report_gates()
            time.sleep(self.poll)

    def _seed_first_turn(self):
        """Issue the first turn token when the brief is in and nobody has.

        The adopter path is clone -> init -> brief -> launch: with the
        concept already in .team/brief.md and the state still "forming",
        the coordinator reads its orders from the brief - no separate
        start command, matching the demo's manual seed. Without a brief
        the team stays forming and the owner gets a gate, not a guess."""
        state = self.bus.state()
        if state.get("status") != "forming" or state.get("turn"):
            return
        brief_path = os.path.join(self.bus.repo, ".team", "brief.md")
        try:
            brief = open(brief_path).read().strip()
        except OSError:
            brief = ""
        roster = self.bus.roster().get("seats", {})
        if not brief or "coordinator" not in roster:
            return
        state["turn"] = "coordinator"
        state["status"] = "running"
        self.bus.write_state(state)
        self.bus.append_log("supervisor", "seed",
                            "brief present; first turn issued to coordinator")
        self.bus.commit_all("supervisor: brief present, first turn issued")

    # -- internals -------------------------------------------------------

    def _reap_and_restart(self):
        for name, proc in list(self.procs.items()):
            if proc.poll() is None:
                continue
            count = self.restarts.get(name, 0)
            if count >= self.restart_limit:
                self._escalate(
                    f"seat {name} crashed {count + 1} times; not restarting")
                del self.procs[name]
                continue
            self.restarts[name] = count + 1
            self.bus.append_log("supervisor", "restart",
                                f"seat {name} exited {proc.returncode}; "
                                f"restart {count + 1}")
            self.bus.commit_all(f"supervisor: restart seat {name}")
            self.start_seat(name)

    def _check_stall(self, state):
        turn = state.get("turn")
        if not turn or state.get("status") != "running":
            return
        since = state.get("turn_since")
        if not since:
            return
        try:
            ts = time.mktime(time.strptime(since, "%Y-%m-%dT%H:%M:%SZ"))
        except ValueError:
            return
        if time.time() - ts < self.stall_timeout:
            return
        if turn in self._stalled_seats:
            return
        self._stalled_seats.add(turn)
        if turn in self.procs:
            self.bus.append_log("supervisor", "stall",
                                f"turn stalled on {turn}; restarting seat")
            self.bus.commit_all(f"supervisor: stall on {turn}")
            self.procs[turn].terminate()
        else:
            self._escalate(
                f"turn stalled on interactive seat {turn}; "
                "a human must nudge or re-open that session")

    def _escalate(self, text):
        self.bus.open_gate("supervisor", text,
                           options=["restart the seat", "stop the team"],
                           recommendation="restart the seat")
        self.bus.commit_all("supervisor: escalation")

    def _report_gates(self):
        for gate in self.bus.pending_gates():
            if gate["id"] in self._notified_gates:
                continue
            self._notified_gates.add(gate["id"])
            line = (f"[gate {gate['id']}] {gate['seat']} asks: "
                    f"{gate['question']}")
            print(line, flush=True)
            if self.notify_command:
                subprocess.run(self.notify_command + [line], check=False)

    def _stop_all(self):
        for proc in self.procs.values():
            if proc.poll() is None:
                proc.terminate()
```
