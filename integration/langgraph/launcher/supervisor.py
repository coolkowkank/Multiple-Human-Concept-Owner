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
import calendar
import time

from .bus import Bus
from . import liveness


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
    # Adapter types known to spend no provider requests. Anything else
    # (http, cli, unknown, unreadable roster) is treated as SPENDING: a
    # restart replays the adapter call and can consume a request/reserve.
    NON_SPENDING_TYPES = {"mock", "queue", "interactive"}

    def _is_spending(self, seat):
        try:
            spec = self.bus.roster().get("seats", {}).get(seat)
            kind = (spec or {}).get("adapter", {}).get("type")
        except Exception:
            return True
        return kind not in self.NON_SPENDING_TYPES

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
            if self._is_spending(name):
                try:
                    st = self.bus.state()
                    holds = st.get("turn") == name
                except Exception:
                    st, holds = {}, True   # unreadable state: assume it holds the turn
                if holds:
                    # a restart would re-enter act_once and replay the call
                    del self.procs[name]
                    self._stalled_seats = {(name, st.get("turn_seq"), st.get("turn_since"))}
                    self.bus.append_log(
                        "supervisor", "exit",
                        f"seat {name} exited {proc.returncode} holding the "
                        "turn; spending seat: NOT restarted")
                    self._escalate_spending(
                        f"spending seat {name} exited ({proc.returncode}) "
                        "while holding the turn. Not restarted: a restart "
                        "replays the model call. Inspect the process, the "
                        "state and the lease (launcher lease) first.")
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

    def _check_stall(self, state, now=None):
        turn = state.get("turn")
        if not turn or state.get("status") != "running":
            return
        since = state.get("turn_since")
        if not since:
            return
        now = time.time() if now is None else now
        try:
            # the stamp is UTC (runtime._now): timegm, never local mktime
            ts = calendar.timegm(time.strptime(since, "%Y-%m-%dT%H:%M:%SZ"))
        except (ValueError, TypeError, OverflowError):
            return
        proc = self.procs.get(turn)
        decl = liveness.read_declaration(getattr(self, "repo", None) or "", turn)
        verdict, reason = liveness.liveness(
            state, decl, now, getattr(proc, "pid", None))
        if verdict == "live":
            return   # slow but inside its own declared bound: no claim, no action
        if verdict == "unknown" and now - ts < self.stall_timeout:
            return
        # identity of THIS turn: a later distinct turn of the same seat has a
        # different turn_seq/turn_since and must be acted on again
        ident = (turn, state.get("turn_seq"), since)
        if ident in self._stalled_seats:
            return
        self._stalled_seats = {ident}
        if self._is_spending(turn):
            # never terminate/restart/replay a spending seat on elapsed time
            # or uncertain liveness: escalate for an operator decision
            self.bus.append_log(
                "supervisor", "stall",
                f"turn stalled on {turn} ({reason}); spending seat: NOT "
                "terminated or restarted")
            self._escalate_spending(
                f"turn stalled on {turn} ({reason}). This seat spends "
                "provider requests, so the supervisor did NOT terminate or "
                "restart it (a restart replays the model call). Inspect the "
                "process and the lease (launcher lease) before any restart.")
        elif turn in self.procs:
            self.bus.append_log("supervisor", "stall",
                                f"turn stalled on {turn}; restarting seat")
            self.bus.commit_all(f"supervisor: stall on {turn}")
            self.procs[turn].terminate()
        else:
            self._escalate(
                f"turn stalled on interactive seat {turn}; "
                "a human must nudge or re-open that session")

    def _escalate_spending(self, text):
        self.bus.open_gate("supervisor", text,
                           options=["inspect first, then decide", "stop the team"],
                           recommendation="inspect first; do not restart blindly")
        self.bus.commit_all("supervisor: escalation (spending seat, no auto-restart)")

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
