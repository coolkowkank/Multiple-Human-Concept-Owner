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

import calendar
import json
import os
import subprocess
import sys
import time

from .bus import Bus, BusError, GATES_PENDING


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
                # Only drop the seat once its incident is durably pending;
                # otherwise the next poll retries instead of losing it.
                if self._escalate(
                        f"seat {name} crashed {count + 1} times; "
                        "not restarting"):
                    del self.procs[name]
                continue
            self.restarts[name] = count + 1
            self.bus.append_log("supervisor", "restart",
                                f"seat {name} exited {proc.returncode}; "
                                f"restart {count + 1}")
            self.bus.commit_all(f"supervisor: restart seat {name}")
            self.start_seat(name)

    def _check_stall(self, state):
        # Handle routing failures before stall detection
        turn = state.get("turn")
        status = state.get("status")
        if status == "running" and turn:
            # valid turn observed; consecutive-failure counting starts over
            self._routing_failure_count = 0
        if status == "running" and not turn:
            # routing failure detected
            count = getattr(self, "_routing_failure_count", 0) + 1
            self._routing_failure_count = count
            self.bus.append_log("supervisor", "routing-failure",
                                f"routing failure detected; state: {state}")
            if count >= 2:
                self._escalate("consecutive routing failures")
                return
            # re-issue turn to coordinator, but only if a coordinator seat exists
            roster = self.bus.roster().get("seats", {})
            if "coordinator" not in roster:
                self._escalate("routing failure and no coordinator seat in roster")
                return
            state["turn"] = "coordinator"
            state["turn_since"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self.bus.write_state(state)
            self.bus.commit_all("supervisor: reissued turn to coordinator after routing failure")
            return
        if not turn or status != "running":
            return
        since = state.get("turn_since")
        if not since:
            return
        try:
            # parse as UTC using calendar.timegm
            ts = calendar.timegm(time.strptime(since, "%Y-%m-%dT%H:%M:%SZ"))
        except ValueError:
            return
        if time.time() - ts < self.stall_timeout:
            return
        if turn in self._stalled_seats:
            return
        if turn in self.procs:
            self._stalled_seats.add(turn)
            self.bus.append_log("supervisor", "stall",
                                f"turn stalled on {turn}; restarting seat")
            self.bus.commit_all(f"supervisor: stall on {turn}")
            self.procs[turn].terminate()
        else:
            # Mark stalled only once the incident is durably pending,
            # so a deferred escalation is retried, not forgotten.
            if self._escalate(
                    f"turn stalled on interactive seat {turn}; "
                    "a human must nudge or re-open that session"):
                self._stalled_seats.add(turn)

    def _gate_committed(self, gate):
        """True when THIS gate is in HEAD's PENDING file, i.e. it
        survives a crash or checkout. Exact parsed match on id (or
        seat+question) - never a substring, which false-positives on
        ids embedded in other rows. A matching WORKTREE row left by a
        failed commit is not durable."""
        proc = subprocess.run(
            ["git", "-C", self.bus.repo, "show", f"HEAD:{GATES_PENDING}"],
            capture_output=True, text=True)
        if proc.returncode != 0:
            return False
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (row.get("id") == gate.get("id")
                    or (row.get("seat") == gate.get("seat")
                        and row.get("question") == gate.get("question"))):
                return True
        return False

    def _snapshot_pending(self):
        """Worktree bytes + staged blob of the PENDING file, so a
        failed commit can be rolled back to EXACTLY the prior state,
        preserving any pre-existing staged or worktree changes."""
        if not hasattr(self.bus, "repo"):
            return None  # non-git test double: nothing to snapshot
        path = os.path.join(self.bus.repo, GATES_PENDING)
        try:
            with open(path, "rb") as fh:
                worktree = fh.read()
        except OSError:
            worktree = None
        proc = subprocess.run(
            ["git", "-C", self.bus.repo, "ls-files", "-s", "--",
             GATES_PENDING], capture_output=True, text=True)
        parts = proc.stdout.split()
        staged = parts[1] if proc.returncode == 0 and len(parts) >= 2             else None
        return worktree, staged

    def _restore_pending(self, snap):
        """Undo only this operation's delta: worktree bytes and index
        entry back to the snapshot."""
        if snap is None:
            return  # non-git test double: nothing to restore
        worktree, staged = snap
        path = os.path.join(self.bus.repo, GATES_PENDING)
        if worktree is None:
            try:
                os.remove(path)
            except OSError:
                pass
        else:
            with open(path, "wb") as fh:
                fh.write(worktree)
        if staged is None:
            subprocess.run(
                ["git", "-C", self.bus.repo, "rm", "-q", "--cached",
                 "--ignore-unmatch", "--", GATES_PENDING],
                capture_output=True)
        else:
            subprocess.run(
                ["git", "-C", self.bus.repo, "update-index",
                 "--cacheinfo", f"100644,{staged},{GATES_PENDING}"],
                capture_output=True)

    def _escalate(self, text):
        """Open a human gate for an incident, deduping only the SAME
        incident (an unanswered supervisor gate with the identical
        question). Distinct incidents always get their own gate, even
        while another supervisor gate is pending.

        Returns True only when the incident is DURABLY pending: the gate
        row is committed in HEAD (written now, recommitted now after an
        earlier commit failure, or already committed). Returns False -
        caller keeps its own state and the next poll retries - when the
        pending state cannot be read or the gate cannot be committed;
        a failed commit rolls back its own append so the uncommitted
        row is never mistaken for a durable gate. Diagnostics are
        transient prints, never bus writes: repeated failures cannot
        grow the repo."""
        try:
            pending = self.bus.pending_gates()
        except (OSError, AttributeError, json.JSONDecodeError) as exc:
            print(f"supervisor: pending gates unreadable ({exc!r}); "
                  f"deferring escalation: {text}", flush=True)
            return False
        for gate in pending:
            if (gate.get("seat") == "supervisor"
                    and gate.get("question") == text):
                if self._gate_committed(gate):
                    print(f"supervisor: incident already pending: {text}",
                          flush=True)
                    return True
                # Matching worktree row from an earlier failed commit:
                # persist it now instead of trusting it.
                try:
                    self.bus.commit_all("supervisor: escalation")
                except BusError as exc:
                    print(f"supervisor: gate commit failed ({exc}); "
                          f"deferring escalation: {text}", flush=True)
                    return False
                return self._gate_committed(gate)
        snap = self._snapshot_pending()
        gate_id = self.bus.open_gate(
            "supervisor", text,
            options=["restart the seat", "stop the team"],
            recommendation="restart the seat")
        try:
            self.bus.commit_all("supervisor: escalation")
        except BusError as exc:
            self._restore_pending(snap)
            print(f"supervisor: gate commit failed ({exc}); "
                  f"restored prior PENDING state, deferring: {text}",
                  flush=True)
            return False
        return True

    def _report_gates(self):
        try:
            gates = self.bus.pending_gates()
        except (OSError, AttributeError, json.JSONDecodeError) as exc:
            # The run loop must survive the same read failure that makes
            # _escalate defer - otherwise there is no next poll to retry.
            print(f"supervisor: pending gates unreadable ({exc!r}); "
                  "skipping gate report this poll", flush=True)
            return
        for gate in gates:
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
