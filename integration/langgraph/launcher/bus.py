"""Git-backed coordination bus.

The shared state every seat reads and writes lives in the project
repository (v1 transport: the git repository itself):

    .team/STATE.json   turn holder, turn counter, leases, status
    .team/LOG.jsonl    append-only message log (the communication place)
    .team/roster.json  seats, roles, adapters, allowed write paths
    .team/brief.md     the agreed brief (concept_to_coordinator)
    .team/gates/PENDING.jsonl / ANSWERS.jsonl   human gate queue

Every bus mutation is one git commit. Pull-before-edit, rebase on
conflict, never force-push: the same rules the evaluations showed
breaking when they were conventions instead of mechanism.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import subprocess
import threading
import time

BUS_DIR = ".team"
STATE = os.path.join(BUS_DIR, "STATE.json")
LOG = os.path.join(BUS_DIR, "LOG.jsonl")
ROSTER = os.path.join(BUS_DIR, "roster.json")
BRIEF = os.path.join(BUS_DIR, "brief.md")
GATES_PENDING = os.path.join(BUS_DIR, "gates", "PENDING.jsonl")
GATES_ANSWERS = os.path.join(BUS_DIR, "gates", "ANSWERS.jsonl")

DEFAULT_STATE = {
    "turn": None,
    "turn_seq": 0,
    "turn_since": None,
    "status": "forming",
    "status_line": "team forming",
    "leases": {},
}


class BusError(Exception):
    pass


def _git(repo, *args, check=True):
    proc = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True,
    )
    if check and proc.returncode != 0:
        raise BusError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


class Bus:
    def __init__(self, repo, branch="team-work", retries=3):
        self.repo = os.path.abspath(repo)
        self.branch = branch
        self.retries = retries

    # -- setup ---------------------------------------------------------

    def init_layout(self, brief_text="", roster=None):
        """Create the .team layout on the working branch. Idempotent."""
        for path, content in [
            (STATE, json.dumps(DEFAULT_STATE, indent=2) + "\n"),
            (LOG, ""),
            (ROSTER, json.dumps(roster or {"seats": {}}, indent=2) + "\n"),
            (BRIEF, brief_text),
            (GATES_PENDING, ""),
            (GATES_ANSWERS, ""),
        ]:
            full = os.path.join(self.repo, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            if not os.path.exists(full):
                with open(full, "w") as fh:
                    fh.write(content)
        self.commit_paths("operator: init coordination layout",
                          [STATE, LOG, ROSTER, BRIEF,
                           GATES_PENDING, GATES_ANSWERS])

    # -- git transport ---------------------------------------------------

    def has_remote(self):
        return _git(self.repo, "remote").stdout.strip() != ""

    def pull(self):
        if not self.has_remote():
            return
        _git(self.repo, "fetch", "origin", self.branch, check=False)
        proc = _git(self.repo, "rebase", f"origin/{self.branch}", check=False)
        if proc.returncode != 0:
            _git(self.repo, "rebase", "--abort", check=False)
            raise BusError(f"pull conflict on {self.branch}: {proc.stderr.strip()}")

    def push(self):
        if not self.has_remote():
            return
        _git(self.repo, "push", "origin", self.branch)

    def commit_all(self, message):
        _git(self.repo, "add", "-A")
        if _git(self.repo, "diff", "--cached", "--quiet", check=False).returncode == 0:
            return False  # nothing to commit
        _git(self.repo, "commit", "-m", message)
        return True

    def assert_index_clean(self, context):
        """Refuse when the index already has staged changes (live-1
        patch review P3): a partial-path commit would otherwise sweep
        them in. Call BEFORE mutating files, so a refusal leaves no
        uncommitted residue behind (R3)."""
        pre_staged = _git(
            self.repo, "diff", "--cached", "--name-only").stdout.split()
        if pre_staged:
            raise BusError(
                f"refusing to {context}: the index already has staged "
                f"changes ({', '.join(pre_staged)}) - unstage or "
                "commit them first so the next commit contains exactly "
                "its own paths")

    def commit_paths(self, message, paths):
        """Commit ONLY the named paths. Unlike commit_all (git add -A),
        an unrelated dirty file elsewhere in the worktree is never
        swept into the commit (live-1 review finding). Pre-STAGED
        changes are refused rather than swept (P3). A failed commit
        (e.g. the commit guard rejects the message) unstages its own
        paths again so no staged residue blocks later commands (R2)."""
        self.assert_index_clean(f"commit only {paths}")
        _git(self.repo, "add", "--", *paths)
        if _git(self.repo, "diff", "--cached", "--quiet",
                check=False).returncode == 0:
            return False
        try:
            _git(self.repo, "commit", "-m", message)
        except BusError:
            _git(self.repo, "reset", "-q", "--", *paths, check=False)
            raise
        return True

    def transact_paths(self, message, paths, mutate):
        """transact() with explicit staging: commit exactly `paths`."""
        # Clean-index precheck BEFORE any mutation: a refusal leaves
        # nothing dirty. Failure restoration touches ONLY `paths`.
        self.assert_index_clean(f"transact {list(paths)}")
        for attempt in range(self.retries):
            self.pull()
            snap = self._snapshot_paths(paths)
            try:
                result = mutate()
                committed = self.commit_paths(message, paths)
            except BaseException:
                self._restore_paths(paths, snap)
                raise
            if not committed:
                return result
            try:
                self.push()
                return result
            except BusError:
                if self._confirm_landed():
                    return result
                _git(self.repo, "reset", "--hard", "HEAD~1", check=False)
                if attempt == self.retries - 1:
                    raise BusError(f"lost {self.retries} commit races on {self.branch}")
        return result

    @contextlib.contextmanager
    def action_lock(self, timeout=30.0):
        """Per-REPO exclusive advisory lock (flock on a file inside
        .git, so it is never committed and independent repos never
        contend). Control writers (pause/update/reassign) and a seat's
        validate->apply->commit window take the same lock, so a control
        change is either fully before the seat's final control read or
        fully after its commit. Re-entrant within one Bus object.
        Times out with BusError rather than blocking forever."""
        if not hasattr(self, "_tlock"):
            self._tlock = threading.RLock()
            self._lock_depth = 0
        # Thread-level: re-entrant ONLY for the owning thread; any other
        # thread using this same Bus object must contend (with timeout).
        if not self._tlock.acquire(timeout=timeout):
            raise BusError("action lock busy: timed out (thread)")
        try:
            if self._lock_depth > 0:      # we own it: same-thread reentry
                self._lock_depth += 1
                try:
                    yield
                finally:
                    self._lock_depth -= 1
                return
            gitdir = _git(self.repo, "rev-parse",
                          "--absolute-git-dir").stdout.strip()
            fh = open(os.path.join(gitdir, "team-action.lock"), "a+")
            deadline = time.time() + timeout
            try:
                while True:
                    try:
                        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError:
                        if time.time() >= deadline:
                            raise BusError("action lock busy: timed out")
                        time.sleep(0.05)
                self._lock_depth = 1
                try:
                    yield
                finally:
                    self._lock_depth = 0
            finally:
                fh.close()   # releases the flock
        finally:
            self._tlock.release()

    def _snapshot_paths(self, paths):
        snap = {}
        for rel in paths:
            full = os.path.join(self.repo, rel)
            if os.path.isfile(full):
                with open(full, "rb") as fh:
                    snap[rel] = fh.read()
            else:
                snap[rel] = None
        return snap

    def _restore_paths(self, paths, snap):
        """Restore only the declared paths to their pre-mutate bytes
        (or absence); unstage them. Other files are never touched."""
        _git(self.repo, "reset", "-q", "--", *paths, check=False)
        for rel, data in snap.items():
            full = os.path.join(self.repo, rel)
            if data is None:
                if os.path.isfile(full):
                    os.remove(full)
            else:
                with open(full, "wb") as fh:
                    fh.write(data)

    def transact(self, message, mutate):
        """Pull, mutate working tree, commit, push; retry on races.

        `mutate()` edits files under the repo. Returns mutate()'s value.
        Raises BusError after `retries` lost races.
        """
        for attempt in range(self.retries):
            self.pull()
            result = mutate()
            if not self.commit_all(message):
                return result
            try:
                self.push()
                return result
            except BusError:
                # A failed push does NOT prove the commit never landed
                # (missing ack != no execution). Check before retrying,
                # or a retry would duplicate the batch's external
                # effects (model calls, verify runs).
                if self._confirm_landed():
                    return result
                _git(self.repo, "reset", "--hard", "HEAD~1", check=False)
                if attempt == self.retries - 1:
                    raise BusError(f"lost {self.retries} commit races on {self.branch}")
        return result

    def _confirm_landed(self):
        """True when the remote already contains our local HEAD commit."""
        if not self.has_remote():
            return True  # local-only bus: the commit itself is the record
        head = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        _git(self.repo, "fetch", "origin", self.branch, check=False)
        proc = _git(self.repo, "merge-base", "--is-ancestor",
                    head, f"origin/{self.branch}", check=False)
        return proc.returncode == 0

    # -- state -----------------------------------------------------------

    def _read_json(self, path, default):
        full = os.path.join(self.repo, path)
        if not os.path.exists(full):
            return default
        with open(full) as fh:
            text = fh.read().strip()
        return json.loads(text) if text else default

    def state(self):
        state = dict(DEFAULT_STATE)
        state.update(self._read_json(STATE, {}))
        return state

    def write_state(self, state):
        with open(os.path.join(self.repo, STATE), "w") as fh:
            fh.write(json.dumps(state, indent=2) + "\n")

    def roster(self):
        return self._read_json(ROSTER, {"seats": {}})

    def append_log(self, seat, kind, body, turn_seq=None):
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "seat": seat,
            "kind": kind,
            "body": body,
        }
        if turn_seq is not None:
            entry["turn_seq"] = turn_seq
        with open(os.path.join(self.repo, LOG), "a") as fh:
            fh.write(json.dumps(entry) + "\n")

    def log(self, limit=None, kinds=None):
        full = os.path.join(self.repo, LOG)
        if not os.path.exists(full):
            return []
        entries = []
        with open(full) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        if kinds:
            entries = [e for e in entries if e.get("kind") in kinds]
        return entries[-limit:] if limit else entries

    # -- gates -----------------------------------------------------------

    def open_gate(self, seat, question, options=None, recommendation=None):
        gate = {
            "id": f"gate-{int(time.time() * 1000)}",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "seat": seat,
            "question": question,
            "options": options or [],
            "recommendation": recommendation,
        }
        with open(os.path.join(self.repo, GATES_PENDING), "a") as fh:
            fh.write(json.dumps(gate) + "\n")
        return gate["id"]

    def pending_gates(self):
        answered = {a.get("id") for a in self._read_jsonl(GATES_ANSWERS)}
        return [g for g in self._read_jsonl(GATES_PENDING) if g.get("id") not in answered]

    def answer_gate(self, gate_id, answer, author="human"):
        with open(os.path.join(self.repo, GATES_ANSWERS), "a") as fh:
            fh.write(json.dumps({
                "id": gate_id,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "author": author,
                "answer": answer,
            }) + "\n")

    def _read_jsonl(self, path):
        full = os.path.join(self.repo, path)
        if not os.path.exists(full):
            return []
        rows = []
        with open(full) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows
