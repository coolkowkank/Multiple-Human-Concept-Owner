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
import sys
import time
import uuid

from . import prompts
from .adapters import AdapterError, QueueAdapter, build_adapter
from .bus import Bus, BusError, LOG, STATE, GATES_PENDING, GATES_ANSWERS


class SeatError(Exception):
    pass


# A typed refusal (never matched on message text): the working tree holds
# uncommitted coordination state, so a turn must not start. Seat.run does
# not append to the torn LOG for it, the CLI exits with EXIT_TORN_STATE,
# and the supervisor treats that exit as operator-blocked.
class TornStateError(SeatError):
    code = "torn_control_state"


EXIT_TORN_STATE = 75


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


import re as _re
from . import liveness as _liveness
try:   # pure module next to the launcher package (PYTHONPATH = its parent)
    import handoff_record as _hr
except ImportError:   # absent: handoffs are logged without a record
    _hr = None
_DONE_RE = _re.compile(r"DONE(?![A-Za-z0-9_])")


def is_done_status(status_line):
    """True for a status_line that starts with the word DONE (exactly
    "DONE", or DONE followed by a non-word character such as space, ':'
    or '-'). DONEZO, DONE2 and "DONEBUT..." are not DONE. The prompt
    contract is "put DONE at the start of status_line"."""
    return isinstance(status_line, str) and bool(_DONE_RE.match(status_line))


def validate_response_shape(name, response):
    """Refuse a malformed response BEFORE any write (RW1: incomplete or
    wrongly typed handoff fields used to crash after files were written,
    leaving residue with the turn still held). Pure: no I/O."""
    summary = response.get("summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 4000:
        raise SeatError(f"{name}: summary must be a non-empty string "
                        "(at most 4000 chars); an incomplete handoff is refused")
    writes = response.get("writes")
    if writes is not None:
        if not isinstance(writes, dict):
            raise SeatError(f"{name}: writes must be an object of path to content")
        for path, content in writes.items():
            if not isinstance(path, str) or not isinstance(content, str):
                raise SeatError(f"{name}: writes entries must be string path "
                                "to string content")
    gate = response.get("gate")
    if gate:
        if not isinstance(gate, dict):
            raise SeatError(f"{name}: gate must be an object or null")
        if not isinstance(gate.get("question"), str) or not gate["question"].strip():
            raise SeatError(f"{name}: gate needs a non-empty string question")
        opts = gate.get("options")
        if opts is not None and not (isinstance(opts, list)
                                     and all(isinstance(o, str) for o in opts)):
            raise SeatError(f"{name}: gate options must be a list of strings")
        rec = gate.get("recommendation")
        if rec is not None and not isinstance(rec, str):
            raise SeatError(f"{name}: gate recommendation must be a string")


def _hr_fields(code):
    if _hr is not None:
        return _hr.no_record_fields(code)
    return {"record": None, "record_error": "capture_error"}


def prompt_log_tail(bus, limit=20):
    """THE log tail every prompt renders (Seat.build_prompt and the audit
    wiring's context both call this, so they cannot drift). Runtime-written
    kind=="error" entries are status, not decision input: they are kept out
    so recording one can never change what a queued response was reasoned
    against (M1). The window is the last `limit` NON-error entries."""
    return [e for e in bus.log() if e.get("kind") != "error"][-limit:]


_ERROR_ENTRY_KEYS = {"ts", "seat", "kind", "body"}


def _error_record_commit_ok(repo, commit, parent, binding):
    """True only for the seat's OWN runtime-written error record (M1).

    Authority is the CONTENT, never the commit metadata: the commit touches
    only LOG; the new LOG blob equals the parent's LOG blob byte-for-byte
    PLUS appended lines (no deletion, no edit, no mid-file insert); every
    appended line is exactly one runtime-shaped entry: JSON object whose keys
    are ts/seat/kind/body (+ optional turn_seq), seat == bound seat, kind ==
    "error", body a short single string, turn_seq absent or the bound one.
    The subject must also be the exact runtime string.

    Why this is a no-new-input append: build_prompt() renders the LOG tail
    WITHOUT kind=="error" entries (see Seat.build_prompt), so an error record
    cannot change what any seat or operator reasons against, and it records
    that the turn was NOT taken. Any other change is staleness."""
    seat = binding.get("turn")
    if not isinstance(seat, str) or not seat:
        return False

    def git(*a):
        return subprocess.run(["git", "-C", repo, *a], capture_output=True)

    subj = git("log", "-1", "--format=%s", commit).stdout.decode(
        "utf-8", "replace").strip()
    if subj != f"TURN: {seat} error recorded (turn not taken)":
        return False
    files = git("diff-tree", "--no-commit-id", "--name-only", "-r", "-z",
                "--no-renames", commit).stdout.decode(
        "utf-8", "replace").split("\0")
    if [f for f in files if f] != [LOG]:
        return False
    old = git("show", f"{parent}:{LOG}")
    old = old.stdout if old.returncode == 0 else b""
    new = git("show", f"{commit}:{LOG}")
    if new.returncode != 0:
        return False
    new = new.stdout
    if not new.startswith(old) or len(new) == len(old):
        return False
    if old and not old.endswith(b"\n"):
        return False
    added = new[len(old):]
    if not added.endswith(b"\n") or len(added) > 8192:
        return False
    for raw in added.split(b"\n")[:-1]:
        try:
            entry = json.loads(raw.decode("utf-8"))
        except ValueError:
            return False
        if (not isinstance(entry, dict)
                or not (set(entry) - {"turn_seq"}) == _ERROR_ENTRY_KEYS
                or entry["seat"] != seat or entry["kind"] != "error"
                or not isinstance(entry["body"], str)
                or len(entry["body"]) > 2000
                or not isinstance(entry["ts"], str)
                or entry.get("turn_seq") not in (None, binding.get("turn_seq"))):
            return False
    return True


def head_binding_clean(repo, stamped, binding=None):
    """True when the stamped head is an ancestor of HEAD and every
    change since touches only queue files. Shared by the seat runtime
    (apply-time refusal) and `launcher respond` (stale-line scan), so
    both use ONE definition of staleness (live-1 patch review R1).

    M1: when `binding` (the queued line's _queue stamp) is passed, commits
    are judged one by one and the seat's own exact error-record commit (see
    _error_record_commit_ok) also counts as clean, so a transient failure
    that was recorded does not force the operator to discard and re-reason a
    response that is still valid. Merges, any other LOG change, and any
    non-queue file change remain stale. Without `binding` the original
    aggregate rule applies unchanged."""
    if not stamped:
        return False
    ancestor = subprocess.run(
        ["git", "-C", repo, "merge-base", "--is-ancestor",
         stamped, "HEAD"], capture_output=True)
    if ancestor.returncode != 0:
        return False
    if binding is None:
        changed = subprocess.run(
            ["git", "-C", repo, "diff", "--name-only", stamped, "HEAD"],
            capture_output=True, text=True).stdout.split()
        return all(p.startswith(".team/queues/") for p in changed)
    rl = subprocess.run(
        ["git", "-C", repo, "rev-list", "--parents", "--reverse",
         f"{stamped}..HEAD"], capture_output=True, text=True)
    if rl.returncode != 0:
        return False
    for row in rl.stdout.splitlines():
        parts = row.split()
        if len(parts) != 2:       # a merge (or a root) is never clean
            return False
        commit = parts[0]
        files = subprocess.run(
            ["git", "-C", repo, "diff-tree", "--no-commit-id", "--name-only",
             "-r", commit], capture_output=True, text=True).stdout.split()
        if files and all(p.startswith(".team/queues/") for p in files):
            continue
        if not _error_record_commit_ok(repo, commit, parts[1], binding):
            return False
    return True


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

    def _declare(self, phase, seconds):
        """Cooperative liveness declaration for one bounded blocking step.
        Best-effort; a failure leaves the supervisor at 'unknown'."""
        ident = getattr(self, "_live_ident", None)
        if ident:
            _liveness.write_declaration(
                self.bus.repo, self.name, ident, self.instance_id,
                phase, seconds, time.time())

    def _undeclare(self):
        _liveness.clear_declaration(self.bus.repo, self.name)

    LIVE_GRACE = 60

    def _adapter_step_seconds(self):
        ad = self.spec.get("adapter", {}) or {}
        t = ad.get("timeout")
        if not isinstance(t, (int, float)) or isinstance(t, bool) or t <= 0:
            t = 1800 if ad.get("type") == "cli" else 600
        tries = getattr(self.adapter, "max_retries", 0)
        tries = (tries if isinstance(tries, int) and not isinstance(tries, bool) and tries >= 0 else 0) + 1
        return t * tries + self.LIVE_GRACE

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
                elif not self._head_binding_clean(binding.get("head"), binding):
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
            except TornStateError:
                # never write over torn control state: no LOG append, no commit
                raise
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

    RELAY_RETRY_SECONDS = 60

    def _wait(self):
        """Long-poll the relay for a wake hint; fall back to sleep.

        The relay is a latency hint only (the git bus is the record), so
        every failure path here costs latency, never correctness. A failed
        relay is retried after RELAY_RETRY_SECONDS instead of being
        disabled for the life of the process, the failure is printed once
        per outage, and a server restart (new epoch, or a latest seq below
        ours) resyncs the cursor instead of leaving the seat deaf."""
        if self.relay is None and getattr(self, "_relay_cfg", None) \
                and time.time() >= getattr(self, "_relay_retry_at", 0):
            self.relay = self._relay_cfg
        if self.relay:
            try:
                poll = getattr(self.relay, "poll", None)
                if poll is None:
                    msgs = self.relay.since(self._relay_seq,
                                            wait=self.poll_interval)
                    info = {}
                else:
                    info = poll(self._relay_seq, wait=self.poll_interval)
                    msgs = info.get("messages", [])
                epoch, latest = info.get("epoch"), info.get("latest")
                restarted = (
                    (epoch is not None
                     and getattr(self, "_relay_epoch", None) not in (None, epoch))
                    or (isinstance(latest, int) and latest < self._relay_seq))
                if epoch is not None:
                    self._relay_epoch = epoch
                if restarted:
                    self._relay_seq = latest if isinstance(latest, int) else 0
                    print(f"relay: server restarted; resynced at seq "
                          f"{self._relay_seq}", file=sys.stderr, flush=True)
                    return
                for m in msgs:
                    self._relay_seq = max(self._relay_seq, m["seq"])
                self._relay_down = False
                return
            except Exception as exc:
                if not getattr(self, "_relay_down", False):
                    print(f"relay: unavailable ({type(exc).__name__}); "
                          f"git polling, retry in "
                          f"{self.RELAY_RETRY_SECONDS}s", file=sys.stderr,
                          flush=True)
                self._relay_down = True
                self._relay_cfg = self.relay
                self._relay_retry_at = time.time() + self.RELAY_RETRY_SECONDS
                self.relay = None
        time.sleep(self.poll_interval)

    # -- internals -------------------------------------------------------

    def build_prompt(self, state):
        """The exact (system, task) prompt this seat's adapter would
        receive for this state. Rendered by `launcher prompt` so an
        interactive or assistant-mediated operator reasons against the
        same input a live model would get - no side-channel context."""
        brief = self._read(self.bus.repo, ".team/brief.md")
        recent = prompt_log_tail(self.bus)
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
        self._declare("adapter", self._adapter_step_seconds())
        try:
            return self.adapter.complete(system, prompt)
        finally:
            self._undeclare()

    def _call_adapter(self, state):
        self._live_ident = {"turn": state.get("turn"),
                            "turn_seq": state.get("turn_seq"),
                            "turn_since": state.get("turn_since")}
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

    def _head_binding_clean(self, stamped, binding=None):
        return head_binding_clean(self.bus.repo, stamped, binding)

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
        # Uncommitted BUS state is the signature of a process killed
        # between apply and commit: the working tree then carries an
        # advanced turn/seq that no commit holds. Starting another turn
        # on it spends a model call whose commit the guard rejects and
        # builds on state nobody committed. Refuse; never auto-discard.
        ctrl = {STATE, LOG, GATES_PENDING, GATES_ANSWERS}

        def torn_paths(porcelain):
            return sorted({l[3:].split(" -> ")[-1] for l in porcelain.splitlines()
                           if l[3:].split(" -> ")[-1] in ctrl})
        torn = torn_paths(out)
        if torn:
            # a control writer's own commit window can look torn for a
            # moment: look once more after a short bounded pause
            time.sleep(getattr(self, "torn_recheck_seconds", 2.0))
            out = subprocess.run(
                ["git", "-C", self.bus.repo, "status", "--porcelain"],
                capture_output=True, text=True).stdout
            torn = torn_paths(out)
        if torn:
            raise TornStateError(
                f"{self.name} refuses to start: uncommitted coordination "
                f"state {torn} - a previous process was probably killed "
                "between apply and commit (a transient control-writer "
                "window is possible but persisted over a recheck). No model "
                "call was made. An operator must inspect `git status`/"
                "`git diff` and either commit or discard it (see "
                "OPERATOR_GUIDE: crash residue); nothing is discarded or "
                "written automatically.")
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
        validate_response_shape(self.name, response)
        writes = response.get("writes") or {}
        _ws = sorted(p for p in writes if isinstance(p, str))
        for _a in _ws:
            if any(_b.startswith(_a + "/") for _b in _ws):
                raise SeatError(f"{self.name}: writes name both a file and a "
                                "directory under it; refused before any write")
        for path in writes:
            if not self._path_allowed(path):
                raise SeatError(
                    f"{self.name} tried to write {path} outside allowed paths "
                    f"{self.allowed_paths}")
        pre_handoff = response.get("handoff")
        # validate BEFORE any write: a refusal must leave no residue
        if pre_handoff is not None and (
                not isinstance(pre_handoff, str)
                or pre_handoff not in self.bus.roster().get("seats", {})):
            raise SeatError(
                f"{self.name} handed off to unknown seat {pre_handoff!r}")
        pre_status = response.get("status_line")
        if pre_status is not None and not isinstance(pre_status, str):
            raise SeatError(f"{self.name}: status_line must be a string")
        if pre_handoff is not None and is_done_status(pre_status):
            # Ambiguous: DONE closes the cycle (no turn holder) while a
            # named seat says "continue". Never guess which was meant.
            raise SeatError(
                f"{self.name}: DONE status_line with handoff {pre_handoff!r} "
                "is ambiguous (DONE closes the cycle and drops the next "
                "seat); use handoff null to close, or a non-DONE "
                "status_line to continue")
        if pre_handoff is None and not is_done_status(pre_status):
            # RW1 null-handoff incident: a null handoff without a DONE
            # status line used to leave turn=None with status "running" -
            # no seat can ever act and nobody is told. Refuse; the turn
            # stays with this seat.
            raise SeatError(
                f"{self.name}: null handoff without a DONE status_line would "
                "leave the bus with no turn holder; name the next seat, or "
                "set handoff to null AND start status_line with DONE")
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
        # handoff/v1: capture what was ALREADY dirty before this turn's
        # writes (action lock held, per attempt). Failure degrades to no
        # record; it never raises (bus.transact has no rollback).
        pre_state, pre_val = _hr.safe_capture(self.bus.repo) if _hr else ("no_record", "capture_error")
        ver = {"ran": False}
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
                vt = 60 if os.environ.get("LG_VERIFY_SANDBOX") else 600
                self._declare("verify", vt + self.LIVE_GRACE)
                try:
                    proc = subprocess.run(
                        argv, shell=False, cwd=self.bus.repo, env=_verify_env(),
                        capture_output=True, text=True, timeout=vt)
                finally:
                    self._undeclare()
            exit_code = proc.returncode
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-5:]
            ver = {"ran": True, "exit_code": exit_code, "command": verify_cmd,
                   "tail": "\n".join(tail),
                   "sandboxed": (not legacy) and bool(os.environ.get("LG_VERIFY_SANDBOX"))}
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

        # decide next/status BEFORE the row so the record carries the same
        # values STATE gets (DONE closes: next None; DONE+handoff is refused)
        done = is_done_status(response.get("status_line"))
        nxt = None if done else handoff
        final_status = ("done" if done else
                        "running" if state["status"] == "forming" else state["status"])
        record_kw = self._handoff_record_kw(
            state, seq, nxt, final_status, bool(gate), response, writes,
            pre_state, pre_val, ver)
        summary = response.get("summary", "(no summary)")
        body = summary
        for note in response.pop("_corrections", []):
            body = f"[{note}] " + body
        if verify_cmd:
            body += (f" | verify: `{verify_cmd}` exit={exit_code}"
                     + (f" | tail: {' / '.join(tail)}" if tail else ""))
        self.bus.append_log(self.name, "handoff", body, turn_seq=seq, **record_kw)

        state["turn_seq"] = seq
        state["turn"] = handoff
        state["turn_since"] = _now()
        if response.get("status_line"):
            state["status_line"] = response["status_line"]
        if is_done_status(response.get("status_line")):
            state["status"] = "done"
            state["turn"] = None
        elif state["status"] == "forming":
            state["status"] = "running"
        self.bus.write_state(state)

    def _handoff_record_kw(self, state, seq, nxt, status, gate_opened,
                           response, writes, pre_state, pre_val, ver):
        """Keyword args for append_log: a handoff/v1 record, or an explicit
        no_record with a FIXED error code. Never raises, never retries."""
        try:
            if _hr is None or pre_state != "ok":
                return _hr_fields(pre_val if pre_state != "ok" else "capture_error")
            obs_state, obs_val = _hr.safe_capture(self.bus.repo)
            if obs_state != "ok":
                return _hr_fields(obs_val)
            st, val = _hr.safe_build({
                "seat": self.name, "turn_seq": seq,
                "base": head_hash(self.bus.repo), "next": nxt,
                "status": status, "gate_opened": gate_opened,
                "correction_rounds": len(response.get("_corrections") or []),
                "declared_writes": list(writes),
                "observed": obs_val,
                "preexisting_dirty": [e["path"] for e in pre_val],
                "verify": ver,
                "summary": response.get("summary"),
                "status_line": response.get("status_line")})
            if st != "ok":
                return _hr_fields(val)
            return {"record": val}
        except Exception:
            return _hr_fields("capture_error")

    @staticmethod
    def canonical_rel(path):
        """The ONE relative path form both the allow check and the write
        use, or None. Refuses (never repairs): non-str, empty, absolute
        (/ or \\ lead), any backslash, control chars or NUL, '.'/'..'/
        empty segments, and ANY .git path segment (case-insensitive)."""
        if not isinstance(path, str) or not path or len(path) > 1024:
            return None
        if path[0] in "/\\" or "\\" in path:
            return None
        if any(ord(c) < 32 or ord(c) == 127 for c in path):
            return None
        parts = path.split("/")
        if any(x in ("", ".", "..") or x.casefold() == ".git" for x in parts):
            return None   # any .git segment: repo metadata is not seat content
        return path

    @staticmethod
    def _symlink_free(repo, rel):
        """No existing component under the repo (including the final file)
        may be a symlink: a write through one could leave the repo. A
        missing component is fine (it will be created as a real dir)."""
        cur = repo
        parts = rel.split("/")
        for i, part in enumerate(parts):
            cur = os.path.join(cur, part)
            try:
                if os.path.islink(cur):
                    return False
                last = i == len(parts) - 1
                if os.path.lexists(cur):
                    # an existing ancestor must be a directory (a file there
                    # would fail mid-batch); the target itself must not be one
                    if last and os.path.isdir(cur):
                        return False
                    if not last and not os.path.isdir(cur):
                        return False
            except OSError:
                return False
        real = os.path.realpath(os.path.dirname(os.path.join(repo, rel)))
        root = os.path.realpath(repo)
        return real == root or real.startswith(root + os.sep)

    def _path_allowed(self, path):
        rel = self.canonical_rel(path)
        if rel is None or not self._symlink_free(self.bus.repo, rel):
            return False
        for allowed in self.allowed_paths:
            allowed = allowed.rstrip("/")
            if rel == allowed or rel.startswith(allowed + "/"):
                return True
        return False

    @staticmethod
    def _write(repo, path, content):
        rel = Seat.canonical_rel(path)
        if rel is None or not Seat._symlink_free(repo, rel):
            raise SeatError("refusing to write an unsafe path")
        full = os.path.join(repo, rel)
        try:
            os.makedirs(os.path.dirname(full) or repo, exist_ok=True)
            fd = os.open(full, os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                         | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, "w") as fh:
                fh.write(content)
        except OSError as exc:
            # arbitrary I/O failure: earlier writes of this batch are NOT
            # rolled back (bus.transact has no rollback)
            raise SeatError(f"write failed ({type(exc).__name__}); earlier "
                            "writes of this batch are not rolled back")

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
