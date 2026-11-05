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
from .adapters import AdapterError, QueueAdapter, build_adapter
from .bus import Bus, BusError, LOG


class SeatError(Exception):
    pass


VERIFY_EXECUTABLES = ("python3", "python", "pytest", "test", "true", "false")
_VERIFY_BAD_CHARS = set(";&|`$<>\n\r(){}*?~\\\"'!#")


def verify_argv(cmd):
    """Strict argv for a seat's verify_command, or SeatError. No shell:
    no pipes, redirects, expansions or chaining. Executable from a short
    list; python only as `python <relative .py>` or `-m unittest|pytest`
    (never -c); no absolute paths, `..`, or `~`. This narrows the shape of
    the command. It is NOT a sandbox: verify still runs code the seat
    wrote, with the operator's privileges (secrets are withheld from the
    environment, see _verify_env)."""
    import shlex
    if not isinstance(cmd, str) or not cmd.strip():
        raise SeatError("verify_command must be a non-empty string")
    if any(c in _VERIFY_BAD_CHARS for c in cmd):
        raise SeatError("verify_command refused: shell syntax is not "
                        "allowed (no pipes, redirects, expansion, quoting)")
    try:
        argv = shlex.split(cmd)
    except ValueError as exc:
        raise SeatError(f"verify_command refused: {exc}")
    if not argv or argv[0] not in VERIFY_EXECUTABLES:
        raise SeatError("verify_command refused: executable must be one "
                        f"of {list(VERIFY_EXECUTABLES)}")
    for a in argv[1:]:
        if a.startswith("/") or a.startswith("~") or \
                ".." in a.replace("\\", "/").split("/"):
            raise SeatError("verify_command refused: absolute, home or "
                            "parent-relative path argument")
    if argv[0] in ("python3", "python"):
        ok = (len(argv) >= 2 and argv[1].endswith(".py")
              and not argv[1].startswith("-")) or \
             (len(argv) >= 3 and argv[1] == "-m"
              and argv[2] in ("unittest", "pytest"))
        if not ok:
            raise SeatError("verify_command refused: python only as "
                            "`python <relative.py>` or `-m unittest|pytest`")
    return argv


def verify_sandbox_ready():
    """True only when the flag is set AND the shim is executable."""
    shim = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "sandbox", "python3")
    return bool(os.environ.get("LG_VERIFY_SANDBOX")) and \
        os.path.isfile(shim) and os.access(shim, os.X_OK)


def correction_suffix(kind, exc_text=None, bad=None, allowed=None):
    """The EXACT text appended to the task for a correction round. Single
    source for the runtime and for the audit wrapper (which compares
    equality against what the runtime recorded, no pattern matching)."""
    if kind == "format":
        return (f"\n\nCORRECTION REQUIRED: your previous reply "
                f"was not a single JSON object per the response "
                f"contract ({exc_text}). Reply with EXACTLY ONE JSON object "
                "matching the contract and nothing else - no prose, "
                "no fences, no tool calls.")
    if kind == "path":
        return (f"\n\nCORRECTION REQUIRED: your previous reply "
                f"tried to write {bad}, outside your allowed paths "
                f"{allowed}. Reply again with the same JSON "
                "contract, writing ONLY inside your allowed paths; leave "
                "every other file untouched.")
    raise ValueError("unknown correction kind")


def sandboxed_verify_argv(argv):
    """When LG_VERIFY_SANDBOX is set (the live-run operator sets it),
    verify may ONLY run python3/python through sandbox/python3 (bwrap: no
    network, no home, no secrets, read-only repo copy, CPU/memory limits).
    Anything else (pytest, test, true, false) is refused, and the shim
    must exist, so a missing sandbox fails closed instead of running bare."""
    if not os.environ.get("LG_VERIFY_SANDBOX"):
        return argv
    shim = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "sandbox", "python3")
    if argv[0] not in ("python3", "python"):
        raise SeatError("verify refused under sandbox: only python3 allowed")
    if not (os.path.isfile(shim) and os.access(shim, os.X_OK)):
        raise SeatError("verify refused: sandbox shim missing")
    return [shim] + argv[1:]


def _verify_env():
    """Minimal environment: no API keys or tokens reach verify code."""
    keep = ("PATH", "LANG", "LC_ALL", "TMPDIR")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


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
        self._turn_calls = 0  # new turn: reset the global call budget
        self.bus.pull()  # see handoffs published by other clones/machines
        state = self.bus.state()
        if state.get("turn") != self.name:
            return False

        locks = []

        def mutate():
            # A lost push race re-invokes mutate (retry). Release any
            # lock kept from the previous attempt so the slow adapter
            # call below never runs while holding the action lock. A
            # retry REPLAYS the adapter call and its effects: the
            # contract is at-least-once, never exactly-once.
            while locks:
                locks.pop().__exit__(None, None, None)
            state = self.bus.state()
            if state.get("turn") != self.name:
                return False
            self._preflight_dirt_check()
            self.claim_lease(state)
            response = self._call_adapter(state)
            # Take the repo action lock AFTER the (slow) model call and
            # hold it through apply + commit (released by act_once), so
            # control writers wait only for this short window. Then
            # RE-READ state INSIDE the lock: a compliant control writer
            # may have moved turn/seq/head while we waited. All
            # freshness and binding checks below use this fresh state.
            if not locks:
                lk = self.bus.action_lock()
                lk.__enter__()
                locks.append(lk)
            fresh = self.bus.state()
            if (fresh.get("turn") != self.name
                    or fresh.get("turn_seq") != state.get("turn_seq")):
                raise SeatError(
                    f"{self.name}: turn moved while the response was "
                    f"produced (turn={fresh.get('turn')!r} "
                    f"seq={fresh.get('turn_seq')} vs "
                    f"seq={state.get('turn_seq')}); refusing to apply a "
                    "stale response")
            # keep OUR lease claim (made on the pre-call state); every
            # other field comes from the fresh, lock-protected read
            fresh.setdefault("leases", {})[self.name] = \
                state["leases"][self.name]
            state = fresh
            binding = response.pop("_queue", None)
            if isinstance(self.adapter, QueueAdapter) and not isinstance(
                    binding, dict):
                # A queued line reasoned outside this process MUST carry
                # the stamp `launcher respond` writes. An unbound line
                # (hand-edited or raw) is never applied.
                raise SeatError(
                    f"queued response for {self.name} has no _queue "
                    "binding; refusing an unbound line - re-queue with "
                    "`launcher respond`")
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
            hook = getattr(self, "pre_apply", None)
            if hook is not None:
                # Contract: called inside the transaction, after the
                # binding checks and BEFORE any write/verify/handoff.
                # hook(seat, state, response) must return None to
                # proceed; raising SeatError aborts with no residue.
                # The queue line is not consumed on abort.
                hook(self, state, response)
            self._apply(state, response)
            consume = getattr(self.adapter, "consume", None)
            if consume:
                consume()
            return True

        try:
            return self.bus.transact(f"TURN: {self.name} acting", mutate)
        finally:
            while locks:
                locks.pop().__exit__(None, None, None)

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

    # AdapterError message prefixes that mean "the model's reply did
    # not follow the response contract" - the only failures a
    # format-correction round can heal. Provider/HTTP/key errors are
    # never re-asked here (429 backoff lives in the adapter).
    _FORMAT_ERROR_PREFIXES = ("model output is not JSON",)

    # Global per-turn complete() budget (see comment below). Shared
    # across Bus.transact retry attempts because it lives on the seat
    # instance, reset only when a NEW turn starts in act_once.
    TURN_COMPLETE_BUDGET = 3

    # Adapter-call budget: at most 3 complete() calls PER TURN, GLOBAL
    # across Bus.transact retry attempts - the initial call, ONE
    # format-correction round (contract-format failures only), and ONE
    # path-guard correction round (forbidden write paths); the two
    # corrections can compose. Before this cap was global (pre-490f21e
    # review, 2026-11-04), a lost push race re-invoked mutate() and
    # could regenerate up to 3 calls per transact attempt x 3 attempts
    # = 9 complete calls/turn. Now a transact retry that would exceed
    # the per-turn budget fails closed instead of re-calling the model
    # without bound; the turn ends honestly and the operator re-runs.
    # HTTP requests are a separate layer: each complete() may make up
    # to max_retries+1 (default 4) HTTP requests on persistent 429, so
    # the theoretical per-turn HTTP ceiling is 12 requests, retry-
    # dependent - NOT live-verified (peer is checking HTTP counts
    # separately). Do not quote "3 HTTP calls"; 3 is the complete()
    # budget, not a request count.
    # Raw model output is LOCAL-ONLY evidence (review 2026-11-04): it
    # may carry private input, secrets, or copied context, so it must
    # never be auto-staged into public turn commits. It lives in
    # .git/local-evidence/raw/ - git-private, outside the worktree, so
    # no `git add -A` or path guard can ever stage it (an earlier
    # .git/info/exclude approach, c84214b, only ignored UNTRACKED
    # files: a tracked .team/raw file would still have been swept).
    # Safety before every write: the destination must resolve inside
    # the evidence dir (no symlink escape) and an existing file with
    # different content is never overwritten (a -vN suffix preserves
    # both). On an unsafe destination the write is REFUSED and the
    # refusal is recorded in the note instead of the path. Publishing
    # any raw payload requires an explicit reviewed/redacted opt-in.
    # Consequence for reporting: a failed turn is "zero mutation" only
    # in git-state/app-code terms - it can still leave these local
    # side-effect files.
    _EVIDENCE_DIR = os.path.join(".git", "local-evidence", "raw")

    def _preserve_raw(self, state, exc, attempt):
        raw = getattr(exc, "raw", None)
        if raw is None:
            return None
        base = os.path.join(self.bus.repo, self._EVIDENCE_DIR)
        try:
            # N4 (peer review of e08769a): check the existing path
            # components BEFORE creating anything, so a refusal has no
            # side effects outside .git (an earlier version created
            # the dir first and could leave an empty dir outside).
            gitdir = os.path.realpath(os.path.join(self.bus.repo,
                                                   ".git"))
            probe = base
            while not os.path.lexists(probe):
                probe = os.path.dirname(probe)
            # nearest existing component must resolve inside .git and
            # no existing component on the way down may be a symlink
            if not os.path.realpath(probe).startswith(gitdir + os.sep)                     and os.path.realpath(probe) != gitdir:
                raise OSError("evidence path is not git-private "
                              "(symlink escape?)")
            cur = os.path.join(self.bus.repo, ".git")
            for part in self._EVIDENCE_DIR.split(os.sep)[1:]:
                cur = os.path.join(cur, part)
                if os.path.islink(cur):
                    raise OSError(f"evidence path component is a "
                                  f"symlink: {cur}")
            os.makedirs(base, exist_ok=True)
            if not os.path.realpath(base).startswith(gitdir + os.sep):
                raise OSError("evidence dir is not git-private "
                              "(symlink escape?)")
            name = (f"{self.name}-seq{state['turn_seq']}"
                    f"-attempt-{attempt}.txt")
            path = os.path.join(base, name)
            version = 2
            while os.path.islink(path) or (
                    os.path.exists(path)
                    and open(path).read() != raw):
                path = os.path.join(
                    base, name.replace(".txt", f"-v{version}.txt"))
                version += 1
            if not os.path.exists(path):
                with open(path, "w") as fh:
                    fh.write(raw)
            return os.path.join(self._EVIDENCE_DIR,
                                os.path.basename(path))
        except OSError as exc2:
            return f"<raw preservation REFUSED: unsafe destination: {exc2}>"

    def _complete(self, system, prompt):
        """One adapter complete() against the GLOBAL per-turn budget.

        Fail-closed on a lost commit race: a transact retry re-invokes
        the mutation, but the budget refuses regeneration past 3 calls
        instead of letting retries multiply model calls uncontrolled.
        """
        self._turn_calls = getattr(self, "_turn_calls", 0) + 1
        if self._turn_calls > self.TURN_COMPLETE_BUDGET:
            raise SeatError(
                f"{self.name} exhausted the per-turn adapter-call "
                f"budget ({self.TURN_COMPLETE_BUDGET}, global across "
                "commit-race retries) - refusing uncontrolled "
                "regeneration; the turn ends here, re-run it")
        return self.adapter.complete(system, prompt)

    def _call_adapter(self, state):
        system, task = self.build_prompt(state)
        self.correction_meta = None
        corrections = []
        try:
            response = self._complete(system, task)
        except AdapterError as exc:
            if not str(exc).startswith(self._FORMAT_ERROR_PREFIXES):
                raise SeatError(
                    f"adapter failed for {self.name}: {exc}") from exc
            first_raw = self._preserve_raw(state, exc, 1)
            # One bounded format-correction round (observed live:
            # gpt-oss-120b appended prose after a valid object,
            # live/groq-dev-2 2026-11-04). The model re-answers and the
            # reply is revalidated STRICTLY - no prose salvage, which
            # review rejected because text outside the object can carry
            # intent. A second format failure ends the turn honestly.
            self.correction_meta = {"kind": "format", "exc_text": str(exc)}
            correction = task + correction_suffix("format", str(exc))
            try:
                response = self._complete(system, correction)
            except AdapterError as exc2:
                second_raw = self._preserve_raw(state, exc2, 2)
                saved = [p for p in (first_raw, second_raw) if p]
                raise SeatError(
                    f"adapter failed for {self.name} on the "
                    f"format-correction round: {exc2}"
                    + (f" (raw model output preserved: {saved})"
                       if saved else "")) from exc2
            corrections.append(
                "format-correction round used; first reply was not "
                f"contract JSON ({exc})"
                + (f" (raw preserved: {first_raw})"
                   if first_raw else ""))
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
            if corrections:
                response["_corrections"] = corrections
            return response
        # One bounded correction round (observed need: Groq gpt-oss
        # models repeatedly wrote outside allowed paths and wasted
        # otherwise-usable turns, live/groq-dev-1 2026-11-04). The
        # rejection goes back to the model once; a second violation
        # fails the turn honestly. Nothing has been written yet - the
        # pre-mutation refusal is preserved, and _apply still re-checks
        # every path as the hard guard.
        self.correction_meta = {"kind": "path", "bad": bad,
                                "allowed": self.allowed_paths}
        correction = task + correction_suffix("path", bad=bad,
                                               allowed=self.allowed_paths)
        try:
            retry = self._complete(system, correction)
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
        corrections.append(
            "path-guard correction round used; first reply wrote "
            f"outside allowed paths: {bad}")
        retry["_corrections"] = corrections
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
        pre_handoff = response.get("handoff")
        if pre_handoff is not None and pre_handoff not in \
                self.bus.roster().get("seats", {}):
            # validate BEFORE any write: a refusal must leave no residue
            raise SeatError(
                f"{self.name} handed off to unknown seat {pre_handoff!r}")
        verify_cmd = response.get("verify_command")
        exit_code = None
        raw_legacy = self.spec.get("legacy_shell_verify", False)
        if not (type(raw_legacy) is bool or raw_legacy is None):
            # only the literal JSON booleans are accepted; "false", 1,
            # "yes" etc. must never be read as shell permission
            raise SeatError(
                f"{self.name}: legacy_shell_verify must be a literal "
                f"boolean, got {raw_legacy!r}")
        legacy = raw_legacy is True
        if legacy and os.environ.get("LG_VERIFY_SANDBOX"):
            raise SeatError(f"{self.name}: legacy_shell_verify refused "
                            "while LG_VERIFY_SANDBOX is set")
        argv = None
        if verify_cmd and not legacy:
            argv = verify_argv(verify_cmd)   # refuse BEFORE any write
        if verify_cmd:
            # Apply writes first so the verify command sees the batch.
            for path, content in writes.items():
                self._write(self.bus.repo, path, content)
            if legacy:   # explicit per-seat opt-in to the old shell path
                proc = subprocess.run(
                    verify_cmd, shell=True, cwd=self.bus.repo,
                    capture_output=True, text=True, timeout=600)
            else:
                argv = sandboxed_verify_argv(argv)
                proc = subprocess.run(
                    argv, shell=False, cwd=self.bus.repo, env=_verify_env(),
                    capture_output=True, text=True,
                    timeout=60 if os.environ.get("LG_VERIFY_SANDBOX") else 600)
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
        for note in response.pop("_corrections", []):
            body = f"[{note}] " + body
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
