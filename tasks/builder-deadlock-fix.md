# Builder task: fix null-handoff routing failure + stall-clock timezone bug

You are the Builder. You have exactly THREE tools: write_file, git_commit,
git_push. NOTHING else exists (no file reading, no listing, no shell) - do
not call any other tool name. The full current content of the file you must
fix is embedded below. write_file writes a WHOLE file (complete content,
not a diff). Commit with git_commit, then finish with git_push.

## Background (from the live experiment record, 2026-11-04)

A live 5-seat run on google/gemma-4-31b-it exposed two defects:

1. STALL-CLOCK TIMEZONE BUG: the supervisor logged "turn stalled;
   restarting seat" about 4 seconds after EVERY handoff and SIGTERMed the
   fresh seat. Cause: supervisor._check_stall parses turn_since (a UTC
   "Z" stamp) with time.mktime, which interprets it as LOCAL time; in a
   UTC+2 container every new turn is instantly "2 hours stalled".
2. NULL-HANDOFF ROUTING FAILURE: a builder seat returned handoff=null;
   the runtime wrote STATE.turn=None; every seat then idled forever -
   seats act only when the turn names them, _check_stall returns on a
   falsy turn, and the first-turn seed fires only while status=="forming".
   The bus hung silently with no escalation until a human operator
   re-issued the turn to the coordinator by hand.

## What to implement (ALL changes inside launcher/supervisor.py only)

A. Parse turn_since as UTC, not local time (e.g. calendar.timegm(
   time.strptime(...)) or a timezone-aware datetime). Keep behavior on
   unparseable stamps: skip the check, as now.
B. New routing-failure handling: when state["status"] == "running" and
   state["turn"] is falsy, treat it as a routing failure:
   - append a LOUD log entry (kind "routing-failure") quoting what the
     bus recorded (e.g. the last handoff log entry) - NEVER fabricate or
     rewrite the model's routing decision; its output stays untouched;
   - re-issue the turn: set state["turn"] = "coordinator" with a fresh
     turn_since, write state, commit (prefix "supervisor:" is allowed);
   - if this happens twice in a row (the coordinator again yields a null
     turn without DONE), escalate via the existing _escalate() gate
     instead of re-issuing a third time.
   - A null turn together with status "done" is a VALID terminal state:
     never fire routing-failure handling there.
C. Do not change any other file's logic. Do not modify tests/test_launcher.py.

## Tests to add: NEW file tests/test_deadlock_fix.py

Write focused unittest tests for A and B: a stubbed bus/state where
turn_since is 5 seconds old in UTC must NOT be judged stalled while the
local timezone is non-UTC (set os.environ["TZ"] and time.tzset() in the
test, restore after); a running state with turn=None triggers one
re-issue to coordinator and logs "routing-failure"; a second consecutive
occurrence escalates; status "done" + turn=None does nothing. Follow the
existing suite's style (plain unittest, temp dirs, no network).

## CRITICAL tool-call format rules (read twice)

- Tool arguments must be STRICTLY VALID JSON: every newline inside a
  string MUST be escaped as \n, every quote as \", never emit a raw
  line break inside a JSON string value. A previous attempt failed
  because the file content contained unescaped newlines.
- Write ONE file per round, and only ONE tool call per round. Plan:
  round 1 write_file launcher/supervisor.py; round 2 write_file
  tests/test_deadlock_fix.py; round 3 git_commit; round 4 git_push.
- Keep code lines short and the test file compact (aim under 150 lines):
  a few focused tests beat a long file.

## Bounds

- Only write launcher/supervisor.py and tests/test_deadlock_fix.py.
- Then ONE git_commit, then git_push. No other tools, no extra commits.

## Current launcher/supervisor.py (verbatim - base your rewrite on this)

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
