"""Offline prompt-source accounting. No network, credentials, or prompt changes.

Counts are Unicode characters, UTF-8 bytes and a labelled ceil(chars/4)
heuristic, NEVER provider tokens. Hashes bind each exact source payload.
"""
from __future__ import annotations

import hashlib
import json
from . import prompts
from .token_est import estimate_tokens


def _stats(text):
    encoded = text.encode('utf-8')
    return {'chars': len(text), 'utf8_bytes': len(encoded),
            'sha256': hashlib.sha256(encoded).hexdigest()}


def audit_parts(parts, expected):
    """Require complete ordered coverage, including separators, before counting."""
    if ''.join(text for _, text in parts) != expected:
        raise ValueError('source parts do not reconstruct the exact prompt')
    rows = []
    offset = 0
    for source, text in parts:
        rows.append(dict(source=source, start_char=offset,
                         end_char=offset + len(text), **_stats(text)))
        offset += len(text)
    return dict(**_stats(expected), est_tokens_chars_div_4=estimate_tokens(expected),
                sources=rows)


def render_audited_prompt(seat, role, brief, state, recent_log, batch=None):
    """Render the existing prompt and count its exact source contributions.

    This mirrors the current renderer and fails closed if that renderer changes.
    It does not infer that repeated text is redundant or safe to remove.
    """
    system = prompts.system_prompt(role)
    task = prompts.task_prompt(seat, role, brief, state, recent_log, batch)
    system_parts = [('role', prompts.ROLES[role]),
                    ('response_contract', '\n\n' + prompts.RESPONSE_CONTRACT)]
    header = '\n'.join([
        f'Seat: {seat} (role: {role})',
        f"Turn: {state.get('turn_seq')}",
        f"Team status: {state.get('status_line')}", '', '# Agreed brief'])
    task_parts = [('state_and_labels', header),
                  ('brief', '\n' + (brief or '(no brief yet - your first job may be drafting one)')),
                  ('history_label', '\n\n# Recent coordination log')]
    for entry in recent_log:
        task_parts.append(('history_entry',
            f"\n- [{entry.get('ts')}] {entry.get('seat')} "
            f"({entry.get('kind')}): {entry.get('body')}"))
    if batch:
        task_parts.append(('batch', '\n\n# This batch\n' + batch))
    report = {
        'schema': 'prompt-source-audit/v1',
        'measurement': 'offline_exact_render_not_provider_observation',
        'provider_tokens': None,
        'token_note': 'characters/4 is a heuristic; source token counts are not additive',
        'system': audit_parts(system_parts, system),
        'task': audit_parts(task_parts, task),
    }
    return system, task, report



class PromptAuditAdapter:
    """Opt-in, single-writer adapter wrapper. Never enabled by this module.

    A context callback must return the exact build_prompt inputs for this call,
    including any correction suffix as a separate source. Recording failure
    before transport refuses the call. After-transport recording failure raises;
    callers must not retry automatically because transport may have completed.
    This is audit evidence, NOT an authorization/budget/transport ledger.
    """
    def __init__(self, inner, audit_path, context):
        self.inner, self.audit_path, self.context = inner, audit_path, context

    def _record(self, row):
        import os
        with open(self.audit_path, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(row, ensure_ascii=True) + '\n')
            fh.flush()
            os.fsync(fh.fileno())

    def complete(self, system, prompt):
        import uuid
        context = dict(self.context())
        suffix = context.pop('correction_suffix', '')
        base_system, base_task, report = render_audited_prompt(**context)
        if system != base_system or prompt != base_task + suffix:
            raise ValueError('audit context does not match actual adapter input')
        if suffix:
            report['task'] = audit_parts(
                [('base_task', base_task), ('correction_suffix', suffix)], prompt)
            report['base_task_sources'] = render_audited_prompt(**context)[2]['task']
        call_id = str(uuid.uuid4())
        self._record(dict(event='adapter_call_start', call_id=call_id, audit=report))
        try:
            result = self.inner.complete(system, prompt)
        except Exception as exc:
            self._record(dict(event='adapter_call_error', call_id=call_id,
                              error_type=type(exc).__name__))
            raise
        self._record(dict(event='adapter_call_returned', call_id=call_id,
                          provider_tokens=None))
        return result

    def consume(self):
        consume = getattr(self.inner, 'consume', None)
        if consume:
            return consume()


def main():
    """python -m launcher.prompt_audit < input.json > audit.json (hashes only)."""
    import sys
    data = json.load(sys.stdin)
    _, _, report = render_audited_prompt(**data)
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
