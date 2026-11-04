"""Explicit single-process, mock-only guarded composition. No provider support.

Existing launch/seat commands are unchanged. This opt-in path shares exactly
one process-local CompletionSession, does not restart/resume lost evidence,
and stops on gates/errors/limits. It proves mechanics, not model independence.
"""
import os
import hashlib
import subprocess
import time
import uuid
from .bus import Bus
from .runtime import Seat
from .completion_session import CompletionSession


def run_guarded_offline(repo, branch, *, verify_argv, max_turns=8, max_seconds=60, prompt_audits=None):
    if type(max_turns) is not int or max_turns < 1 or max_turns > 100:
        raise ValueError('offline turn cap must be an integer from 1 to 100')
    if type(max_seconds) is not int or max_seconds < 1 or max_seconds > 300:
        raise ValueError('offline time cap must be an integer from 1 to 300')
    bus = Bus(repo, branch)
    if bus.has_remote():
        raise ValueError('offline target must have no remote')
    roster = bus.roster().get('seats', {})
    required = ('builder', 'reviewer', 'qc', 'coordinator')
    if len(roster) != 4 or sorted(spec.get('role') for spec in roster.values()) != sorted(required):
        raise ValueError('exactly one Builder, Reviewer, QC and Coordinator required')
    for spec in roster.values():
        adapter = spec.get('adapter', {})
        if adapter.get('type') != 'mock' or adapter.get('script_path'):
            raise ValueError('only in-memory mock scripts are allowed; no provider, cli or queue')
        if not isinstance(adapter.get('script'), list):
            raise ValueError('explicit mock script list required')
        for response in adapter['script']:
            if not isinstance(response, dict):
                raise ValueError('mock response must be an object')
            if response.get('verify_command') is not None:
                raise ValueError('model verify_command forbidden here; host fixed verifier only')
            if spec.get('role') in ('reviewer', 'qc') and response.get('writes'):
                raise ValueError('review artifact writes forbidden in process-local mode')
    status = subprocess.run(['git', '-C', repo, 'status', '--porcelain'],
                            capture_output=True, text=True, check=True).stdout
    if status.strip():
        raise ValueError('fresh clean target required')
    state = bus.state()
    if state.get('status') != 'forming' or state.get('turn') is not None:
        raise ValueError('fresh forming target required; restart/resume is unsupported')
    brief = os.path.join(repo, '.team', 'brief.md')
    with open(brief) as fh:
        if not fh.read().strip():
            raise ValueError('acceptance brief required')
    # Bind the actual launcher source tree, not an arbitrary model/roster pin.
    source = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    digest = hashlib.sha256()
    for name in sorted(os.listdir(os.path.join(source, 'launcher'))):
        if name.endswith('.py'):
            digest.update(name.encode() + b'\x00')
            with open(os.path.join(source, 'launcher', name), 'rb') as fh:
                digest.update(fh.read())
    pin = 'launcher-source-sha256:' + digest.hexdigest()
    guard = CompletionSession(verify_argv, pin,
                              verification_is_side_effect_free=True, reviews_write_artifacts=False)
    run_id = uuid.uuid4().hex
    seat_class = Seat
    if prompt_audits is not None:
        if not isinstance(prompt_audits, list):
            raise ValueError('prompt_audits must be a host list')
        from .prompt_audit import render_audited_prompt, audit_parts
        class AuditedMockSeat(Seat):
            def build_prompt(self, state):
                system, task = super().build_prompt(state)
                context = dict(seat=self.name, role=self.role,
                    brief=self._read(self.bus.repo, '.team/brief.md'), state=state,
                    recent_log=self.bus.log(limit=20), batch=self.spec.get('batch'))
                audited_system, audited_task, report = render_audited_prompt(**context)
                if (system, task) != (audited_system, audited_task):
                    raise ValueError('actual runtime prompt differs from audited sources')
                self._audit_base = (system, task, report)
                return system, task

            def _complete(self, system, prompt):
                original_system, original_task, report = self._audit_base
                if system != original_system or not prompt.startswith(original_task):
                    raise ValueError('unaccounted actual adapter input')
                import copy
                row = copy.deepcopy(report)
                suffix = prompt[len(original_task):]
                if suffix:
                    row['base_task_sources'] = row['task']
                    row['task'] = audit_parts([('base_task', original_task),
                                              ('correction_suffix', suffix)], prompt)
                row.update(seat=self.name, invocation=len(prompt_audits) + 1,
                           outcome='attempted_mock_adapter_call')
                prompt_audits.append(row)
                try:
                    result = super()._complete(system, prompt)
                except Exception:
                    row['outcome'] = 'mock_adapter_error'
                    raise
                row['outcome'] = 'mock_adapter_returned'
                return result
        seat_class = AuditedMockSeat
    seats = {name: seat_class(bus, name, instance_id=run_id + '-' + name,
                        completion_session=guard) for name in roster}
    first = next(name for name, spec in roster.items() if spec['role'] == 'coordinator')
    def seed():
        state = bus.state(); state.update(turn=first, status='running')
        bus.write_state(state)
        bus.append_log('supervisor', 'seed', 'mock-only single-process guarded cycle')
    bus.transact_paths('operator: seed guarded offline cycle', ['.team/STATE.json', '.team/LOG.jsonl'], seed)
    started = time.monotonic()
    for turns in range(1, max_turns + 1):
        if time.monotonic() - started >= max_seconds:
            return {'result': 'time_limit', 'turns': turns - 1}
        if bus.pending_gates():
            return {'result': 'gate', 'turns': turns - 1}
        state = bus.state()
        name = state.get('turn')
        if name not in seats:
            return {'result': 'no_turn', 'turns': turns - 1}
        if not seats[name].act_once():
            return {'result': 'turn_changed', 'turns': turns - 1}
        if bus.state().get('status') == 'done':
            return {'result': 'done', 'turns': turns, 'scope': 'mock_only_offline', 'runtime_pin': pin}
    return {'result': 'turn_limit', 'turns': max_turns}
