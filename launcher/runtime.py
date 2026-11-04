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
from .bus import Bus, BusError, LOG


class SeatError(Exception):
    pass


def head_binding_clean(repo, stamped):
    """True when the stamped head is an ancestor of HEAD and every
    change since touches only queue files. Shared by the seat runtime
    (apply-time refusal) and `launcher respond` (stale-line scan), so
    both use ONE definition of staleness (live-1 patch review R1)."""
    if not stamped:
        return False
    ancestor = subprocess.run(
        ["git", "-C", repo, "merge-base", "--is-ancestor",
         stamped, "HEAD"], capture_output=True)
    if ancestor.returncode != 0:
        return False
    changed = subprocess.run(
        ["git", "-C", repo, "diff", "--name-only", stamped, "HEAD"],
        capture_output=True, text=True).stdout.split()
    return all(p.startswith(".team/queues/") for p in changed)


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Seat:
    def __init__(self, bus: Bus, name, poll_interval=5, lease_ttl=900,
                 instance_id=None, relay=None, webhook=None):
        self.bus = bus
        self.name = name
        self.poll_interval = poll_interval
        self.lease_ttl = lease_ttl
        self.relay = relay
        self.webhook = webhook
        self._relay_seq = 0
        # Session id is created lazily on first seat action: rendering a
        # prompt (or constructing a Seat) must not mint
        # .git/team-seat-<name>.instance as a side effect (live-1
        # review finding). Once minted it stays stable for this clone.
        self.instance_id = instance_id
        self._load_roster_entry(bus, name)

    def _session_id(self):
        """One stable session id per (clone, seat): persisted under
        .git/ so repeated `seat --once` runs from this clone resume the
        same session instead of tripping the single-session lease,
        while a process on another machine still gets its own id and
        stops. Falls back to a random id outside a git work tree."""
        git_dir = os.path.join(self.bus.repo, ".git")
        if not os.path.isdir(git_dir):
            return f"{self.name}-{uuid.uuid4().hex[:8]}"
        path = os.path.join(git_dir, f"team-seat-{self.name}.instance")
        if os.path.exists(path):
            with open(path) as fh:
                saved = fh.read().strip()
            if saved:
                return saved
        new_id = f"{self.name}-{uuid.uuid4().hex[:8]}"
        with open(path, "w") as fh:
            fh.write(new_id + "\n")
        return new_id

    def _load_roster_entry(self, bus, name):
        roster = bus.roster()
        if name not in roster.get("seats", {}):
            raise SeatError(f"seat {name!r} not in roster")
        self.spec = roster["seats"][name]
        self.role = self.spec.get("role", name)
        self.allowed_paths = self.spec.get("allowed_paths", [])
        adapter_spec = dict(self.spec.get("adapter", {"type": "mock"}))
        sp = adapter_spec.get("script_path")
        if sp and not os.path.isabs(sp):
            adapter_spec["script_path"] = os.path.join(bus.repo, sp)
        qp = adapter_spec.get("path")
        if adapter_spec.get("type") == "queue" and qp \
                and not os.path.isabs(qp):
            adapter_spec["path"] = os.path.join(bus.repo, qp)
        self.adapter = build_adapter(adapter_spec)

    # -- lease: one active session per seat ----------------------------

    def claim_lease(self, state):
        if not self.instance_id:
            self.instance_id = self._session_id()
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
        self.bus.pull()  # see handoffs published by other clones/machines
        state = self.bus.state()
        if state.get("turn") != self.name:
            return False

        def mutate():
            state = self.bus.state()
            if state.get("turn") != self.name:
                return False
            self._preflight_dirt_check()
            self.claim_lease(state)
            response = self._call_adapter(state)
            binding = response.pop("_queue", None)
            if binding is not None:
                # `launcher respond` stamps the turn/turn_seq/head the
                # response was reasoned against. Applying it after the
                # bus moved would replay a stale batch (live-1 major
                # finding), so refuse and leave the queue for the
                # operator instead. The head check is real: the stamped
                # head must still be an ancestor and only queue files
                # may have changed since (live-1 patch review - an
                # operator commit touching anything else is staleness,
                # even when turn/seq happen to be unchanged).
                stale = None
                if (binding.get("turn") != state.get("turn")
                        or binding.get("turn_seq") != state.get("turn_seq")):
                    stale = "turn/turn_seq moved"
                elif not self._head_binding_clean(binding.get("head")):
                    stale = "head moved by non-queue commits"
                if stale:
                    raise SeatError(
                        f"queued response is stale ({stale}): bound to "
                        f"turn={binding.get('turn')!r} "
                        f"seq={binding.get('turn_seq')} "
                        f"head={str(binding.get('head'))[:12]} but the "
                        f"bus is at turn={state.get('turn')!r} "
                        f"seq={state.get('turn_seq')} - re-render with "
                        "`launcher prompt` and re-queue with "
                        "`launcher respond` (it can --discard-stale)")
            self._apply(state, response)
            consume = getattr(self.adapter, "consume", None)
            if consume:
                consume()
            return True

        return self.bus.transact(f"TURN: {self.name} acting", mutate)

    def run(self, max_passes=None):
        passes = 0
        while True:
            try:
                acted = self.act_once()
            except SeatError as exc:
                self.bus.append_log(self.name, "error", str(exc))
                # Record the error WITHOUT sweeping the worktree (second
                # review N1): only the LOG enters this commit, the
                # message carries the seat's TURN token so the commit
                # guard accepts it (the turn still belongs to this seat
                # and .team/ is always allowed), and a recording
                # failure must neither mask the original error nor
                # leave staged residue that blocks `respond`.
                try:
                    self.bus.commit_paths(
                        f"TURN: {self.name} error recorded "
                        "(turn not taken)", [LOG])
                except BusError:
                    pass
                raise
            if acted and self.relay:
                self._signal()
            passes += 1
            if max_passes is not None and passes >= max_passes:
                return
            if not acted:
                self._wait()

    def _signal(self):
        """Wake the next seat through every configured hint channel.

        Hints are ephemeral: the bus is the record, a failed hint costs
        latency, never correctness."""
        state = self.bus.state()
        body = f"turn -> {state.get('turn')}"
        if self.relay:
            try:
                self.relay.post(self.name, "wake", body)
            except Exception:
                pass
        if self.webhook:
            try:
                self.webhook.post(self.name, "wake", body)
            except Exception:
                pass

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

    def build_prompt(self, state):
        """The exact (system, task) prompt this seat's adapter would
        receive for this state. Rendered by `launcher prompt` so an
        interactive or assistant-mediated operator reasons against the
        same input a live model would get - no side-channel context."""
        brief = self._read(self.bus.repo, ".team/brief.md")
        recent = self.bus.log(limit=20)
        system = prompts.system_prompt(self.role)
        task = prompts.task_prompt(
            self.name, self.role, brief, state, recent,
            batch=self.spec.get("batch"))
        return system, task

    def _call_adapter(self, state):
        system, task = self.build_prompt(state)
        try:
            response = self.adapter.complete(system, task)
        except AdapterError as exc:
            raise SeatError(f"adapter failed for {self.name}: {exc}") from exc
        if not isinstance(response, dict):
            raise SeatError(f"{self.name} returned a non-object response")
        if response.get("_queue") is not None:
            # A queued response was reasoned outside this process and is
            # bound to a stamped turn/seq/head; re-calling the adapter
            # would replace it with an unbound live answer, so the
            # correction round never applies to it. _apply's hard guard
            # still refuses bad paths pre-mutation.
            return response
        bad = [p for p in (response.get("writes") or {})
               if not self._path_allowed(p)]
        if not bad:
            return response
        # One bounded correction round (observed need: Groq gpt-oss
        # models repeatedly wrote outside allowed paths and wasted
        # otherwise-usable turns, live/groq-dev-1 2026-11-04). The
        # rejection goes back to the model once; a second violation
        # fails the turn honestly. Nothing has been written yet - the
        # pre-mutation refusal is preserved, and _apply still re-checks
        # every path as the hard guard.
        correction = (
            f"{task}\n\nCORRECTION REQUIRED: your previous reply "
            f"tried to write {bad}, outside your allowed paths "
            f"{self.allowed_paths}. Reply again with the same JSON "
            "contract, writing ONLY inside your allowed paths; leave "
            "every other file untouched.")
        try:
            retry = self.adapter.complete(system, correction)
        except AdapterError as exc:
            raise SeatError(
                f"adapter failed for {self.name} on the correction "
                f"round: {exc}") from exc
        if not isinstance(retry, dict):
            raise SeatError(
                f"{self.name} correction round returned a non-object "
                "response")
        still_bad = [p for p in (retry.get("writes") or {})
                     if not self._path_allowed(p)]
        if still_bad:
            raise SeatError(
                f"{self.name} still tried to write {still_bad} outside "
                f"allowed paths {self.allowed_paths} after one "
                "correction round - turn failed without mutation")
        retry["_corrected"] = bad
        return retry

    def _head_binding_clean(self, stamped):
        return head_binding_clean(self.bus.repo, stamped)

    def _preflight_dirt_check(self):
        """Refuse to START a turn when the worktree carries changes the
        turn commit could not legally contain (R4): the turn commit
        stages the whole mutation set by design, and the commit guard
        would reject outside-domain paths only AFTER the mutation ran,
        leaving an advanced uncommitted state. Better to refuse before
        touching anything. In-domain dirt (the seat's own
        allowed_paths and .team/) is the seat's business."""
        out = subprocess.run(
            ["git", "-C", self.bus.repo, "status", "--porcelain"],
            capture_output=True, text=True).stdout
        allowed = [a.rstrip("/") for a in self.allowed_paths]
        bad = []
        for line in out.splitlines():
            path = line[3:].split(" -> ")[-1]
            if path.startswith(".team/"):
                continue
            if any(path == a or path.startswith(a + "/")
                   for a in allowed):
                continue
            bad.append(path)
        if bad:
            raise SeatError(
                f"{self.name} refuses to start: worktree has changes "
                f"outside its allowed paths {allowed} and .team/: "
                f"{bad} - the turn commit would sweep them in and the "
                "commit guard would reject them after the mutation. "
                "Move scratch outside the repo (or under .team/) first.")

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
        corrected = response.pop("_corrected", None)
        body = summary
        if corrected:
            body = (f"[path-guard correction round used; first reply "
                    f" wrote outside allowed paths: {corrected}] "
                    + body)
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
