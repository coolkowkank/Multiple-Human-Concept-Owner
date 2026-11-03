"""The seat loop: one process per seat.

Loop: pull -> if the written turn names this seat, claim its lease,
build the prompt, call the seat's adapter, validate the response against
the roster (allowed paths, known handoff target), run the batch's verify
command and record the honest exit code, commit with a TURN line, hand
off. Otherwise poll again.

This loop is the wake-up layer the four evaluations found missing:
seats poll the shared repository themselves, so no human prods
"check now" between steps.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid

from . import prompts
from .adapters import AdapterError, build_adapter
from .bus import Bus


class SeatError(Exception):
    pass


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Seat:
    def __init__(self, bus: Bus, name, poll_interval=5, lease_ttl=900,
                 instance_id=None, relay=None):
        self.bus = bus
        self.name = name
        self.poll_interval = poll_interval
        self.lease_ttl = lease_ttl
        self.relay = relay
        self._relay_seq = 0
        self.instance_id = instance_id or f"{name}-{uuid.uuid4().hex[:8]}"
        roster = bus.roster()
        if name not in roster.get("seats", {}):
            raise SeatError(f"seat {name!r} not in roster")
        self.spec = roster["seats"][name]
        self.role = self.spec.get("role", name)
        self.allowed_paths = self.spec.get("allowed_paths", [])
        self.adapter = build_adapter(self.spec.get("adapter", {"type": "mock"}))

    # -- lease: one active session per seat ----------------------------

    def claim_lease(self, state):
        lease = state["leases"].get(self.name)
        if lease and lease["holder"] != self.instance_id:
            age = time.time() - lease.get("claimed_at", 0)
            if age < self.lease_ttl:
                raise SeatError(
                    f"seat {self.name} already held by {lease['holder']}; "
                    "a second session stops instead of acting")
        state["leases"][self.name] = {
            "holder": self.instance_id, "claimed_at": time.time(),
        }

    # -- one pass --------------------------------------------------------

    def act_once(self):
        """Take the turn if it is ours. Returns True if we acted."""
        state = self.bus.state()
        if state.get("turn") != self.name:
            return False

        def mutate():
            state = self.bus.state()
            if state.get("turn") != self.name:
                return False
            self.claim_lease(state)
            brief = self._read(self.bus.repo, ".team/brief.md")
            recent = self.bus.log(limit=20)
            response = self._call_adapter(state, brief, recent)
            self._apply(state, response)
            return True

        return self.bus.transact(f"TURN: {self.name} acting", mutate)

    def run(self, max_passes=None):
        passes = 0
        while True:
            try:
                acted = self.act_once()
            except SeatError as exc:
                self.bus.append_log(self.name, "error", str(exc))
                self.bus.commit_all(f"seat {self.name}: error recorded")
                raise
            if acted and self.relay:
                self._signal()
            passes += 1
            if max_passes is not None and passes >= max_passes:
                return
            if not acted:
                self._wait()

    def _signal(self):
        """Wake the next seat through the relay (ephemeral hint only)."""
        try:
            state = self.bus.state()
            self.relay.post(self.name, "wake",
                            f"turn -> {state.get('turn')}")
        except Exception:
            pass  # relay down costs latency, never correctness

    def _wait(self):
        """Long-poll the relay for a wake signal; fall back to sleep."""
        if self.relay:
            try:
                msgs = self.relay.since(self._relay_seq,
                                        wait=self.poll_interval)
                for m in msgs:
                    self._relay_seq = max(self._relay_seq, m["seq"])
                return
            except Exception:
                self.relay = None  # permanent fallback to git polling
        time.sleep(self.poll_interval)

    # -- internals -------------------------------------------------------

    def _call_adapter(self, state, brief, recent):
        system = prompts.system_prompt(self.role)
        task = prompts.task_prompt(
            self.name, self.role, brief, state, recent,
            batch=self.spec.get("batch"))
        try:
            response = self.adapter.complete(system, task)
        except AdapterError as exc:
            raise SeatError(f"adapter failed for {self.name}: {exc}") from exc
        if not isinstance(response, dict):
            raise SeatError(f"{self.name} returned a non-object response")
        return response

    def _apply(self, state, response):
        writes = response.get("writes") or {}
        for path in writes:
            if not self._path_allowed(path):
                raise SeatError(
                    f"{self.name} tried to write {path} outside allowed paths "
                    f"{self.allowed_paths}")
        verify_cmd = response.get("verify_command")
        exit_code = None
        if verify_cmd:
            # Apply writes first so the verify command sees the batch.
            for path, content in writes.items():
                self._write(self.bus.repo, path, content)
            proc = subprocess.run(
                verify_cmd, shell=True, cwd=self.bus.repo,
                capture_output=True, text=True, timeout=600)
            exit_code = proc.returncode
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-5:]
        else:
            for path, content in writes.items():
                self._write(self.bus.repo, path, content)
            tail = []

        seq = state["turn_seq"] + 1
        handoff = response.get("handoff")
        seats = self.bus.roster().get("seats", {})
        if handoff is not None and handoff not in seats:
            raise SeatError(f"{self.name} handed off to unknown seat {handoff!r}")

        gate = response.get("gate")
        if gate:
            self.bus.open_gate(
                self.name, gate["question"],
                options=gate.get("options"),
                recommendation=gate.get("recommendation"))

        summary = response.get("summary", "(no summary)")
        body = summary
        if verify_cmd:
            body += (f" | verify: `{verify_cmd}` exit={exit_code}"
                     + (f" | tail: {' / '.join(tail)}" if tail else ""))
        self.bus.append_log(self.name, "handoff", body, turn_seq=seq)

        state["turn_seq"] = seq
        state["turn"] = handoff
        state["turn_since"] = _now()
        if response.get("status_line"):
            state["status_line"] = response["status_line"]
        if response.get("status_line", "").startswith("DONE"):
            state["status"] = "done"
            state["turn"] = None
        elif state["status"] == "forming":
            state["status"] = "running"
        self.bus.write_state(state)

    def _path_allowed(self, path):
        path = path.replace("\\", "/").lstrip("/")
        if ".." in path.split("/"):
            return False
        for allowed in self.allowed_paths:
            allowed = allowed.rstrip("/")
            if path == allowed or path.startswith(allowed + "/"):
                return True
        return False

    @staticmethod
    def _write(repo, path, content):
        full = os.path.join(repo, path)
        os.makedirs(os.path.dirname(full) or repo, exist_ok=True)
        with open(full, "w") as fh:
            fh.write(content)

    @staticmethod
    def _read(repo, path):
        full = os.path.join(repo, path)
        if not os.path.exists(full):
            return ""
        with open(full) as fh:
            return fh.read()


def head_hash(repo):
    proc = subprocess.run(
        ["git", "-C", repo, "rev-parse", "HEAD"],
        capture_output=True, text=True)
    return proc.stdout.strip()
