"""Opt-in process-local completion guard. Restart loses evidence, fails closed.

Only the host constructs this object and supplies it to Seat. Model responses,
log records and files cannot populate its evidence store. Not cross-process
identity, sandbox security, portable evidence authentication or model quality.
"""
import hashlib
import json
import os
import subprocess
from .completion_policy import Binding, Policy, Evidence, evaluate_completion


class CompletionSession:
    def __init__(self, verify_argv, runtime_pin):
        if not verify_argv or not all(isinstance(x, str) for x in verify_argv):
            raise ValueError('fixed verification argv required')
        if not isinstance(runtime_pin, str) or not runtime_pin:
            raise ValueError('explicit runtime policy pin required')
        self.verify_argv = tuple(verify_argv)
        self.runtime_pin = runtime_pin
        self._evidence = []
        self._instances = {}
        self._pending = None

    def snapshot(self):
        return (list(self._evidence), dict(self._instances), self._pending)

    def restore(self, snapshot):
        rows, instances, pending = snapshot
        self._evidence, self._instances, self._pending = list(rows), dict(instances), pending

    @staticmethod
    def _digest(data):
        return hashlib.sha256(data).hexdigest()

    def binding(self, repo):
        # Scope: tiny-library targets; exclude coordination/evidence directories.
        # Every other file, including new/untracked files and mode, is covered.
        manifest = []
        for root, dirs, files in os.walk(repo, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not (
                root == repo and d in ('.git', '.team')) and d != '__pycache__')
            for name in sorted(dirs + files):
                path = os.path.join(root, name)
                if os.path.islink(path):
                    raise ValueError('symlink input refused')
            for name in sorted(files):
                if name.endswith('.pyc'):
                    continue
                path = os.path.join(root, name)
                with open(path, 'rb') as fh:
                    digest = self._digest(fh.read())
                manifest.append((os.path.relpath(path, repo), os.stat(path).st_mode & 0o777, digest))
        def read(path):
            with open(os.path.join(repo, path), 'rb') as fh:
                return fh.read()
        roster = json.loads(read('.team/roster.json'))
        return Binding(self._digest(json.dumps(manifest, sort_keys=True).encode()),
                       self._digest(read('.team/brief.md')), self.runtime_pin,
                       self._digest(json.dumps(roster, sort_keys=True).encode()),
                       self._digest(json.dumps(self.verify_argv).encode()))

    def observe(self, seat, state, response):
        if seat.role == 'builder':
            self._instances[seat.name] = seat.instance_id
            return
        if seat.role not in ('reviewer', 'qc'):
            return
        # A model may supply a semantic verdict, but cannot supply its observed
        # command result, binding, role, sequence, identity or evidence digest.
        before = self.binding(seat.bus.repo)
        proc = subprocess.run(self.verify_argv, cwd=seat.bus.repo,
                              capture_output=True, timeout=60)
        after = self.binding(seat.bus.repo)
        if before != after:
            raise ValueError('verification changed acceptance inputs')
        identity = seat.instance_id
        if not identity:
            raise ValueError('runtime session identity missing')
        self._instances[seat.name] = identity
        row = Evidence(seat.name, seat.role, after,
                       response.get('review_verdict', 'UNKNOWN'), proc.returncode,
                       True, True, self._head(seat.bus.repo),
                       self._digest(proc.stdout + b'\x00' + proc.stderr), state['turn_seq'] + 1)
        # Replace an observation at the same seat+turn on transact replay.
        self._evidence = [r for r in self._evidence if (r.seat, r.turn_seq) != (row.seat, row.turn_seq)] + [row]

    @staticmethod
    def _head(repo):
        return subprocess.run(['git', '-C', repo, 'rev-parse', 'HEAD'],
                              capture_output=True, text=True, check=True).stdout.strip()

    def decide(self, seat):
        roster = {name: spec.get('role') for name, spec in seat.bus.roster()['seats'].items()}
        builders = [name for name, role in roster.items() if role == 'builder']
        if len(builders) != 1:
            return False, 'builder missing or ambiguous'
        identities = [self._instances.get(name) for name, role in roster.items() if role in ('reviewer', 'qc')]
        builder_identity = self._instances.get(builders[0])
        if len(identities) != 2 or None in identities or len(set(identities)) != 2 or not builder_identity or builder_identity in identities:
            return False, 'independent runtime review sessions missing'
        current = self.binding(seat.bus.repo)
        verdict = evaluate_completion(current=current, roster=roster, builder=builders[0],
            evidence=self._evidence, policy=Policy(True, True, True), worktree_binding_validated=True)
        # True policy here implements the already assigned frozen methodology,
        # not permission from the model or the synthetic predicate fixture.
        if verdict.eligible:
            self._pending = current
        return verdict.eligible, ','.join(verdict.reasons)

    def confirm_committed(self, repo):
        if self._pending is None:
            return
        if self.binding(repo) != self._pending:
            raise ValueError('post-commit acceptance binding changed')
        # Verify tracked application content has no uncommitted delta; runtime
        # commits before calling this. Evidence directories are excluded above.
        dirty = subprocess.run(['git', '-C', repo, 'status', '--porcelain'],
                               capture_output=True, text=True, check=True).stdout
        if dirty.strip():
            raise ValueError('post-commit tree is dirty; completion unconfirmed')
        self._pending = None
