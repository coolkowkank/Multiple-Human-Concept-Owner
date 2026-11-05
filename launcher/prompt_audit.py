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



_ID_OK = __import__('re').compile(r'^[A-Za-z0-9._:-]{1,128}$')
_MAX_COUNT = 10 ** 9


def reported_call_evidence(last_call):
    """Sanitized, publishable view of an adapter's reported call fields.

    Raw external ids are never stored: only sha256 of a well-formed id. Usage
    counts are kept only as plain non-negative ints below 1e9. Anything else is
    dropped and marked, never repaired. These values are provider-REPORTED, not
    verified; origin comes from the adapter class, not from provider content.
    """
    if not isinstance(last_call, dict) or last_call.get('origin') != 'provider':
        return None
    out = {'origin': 'provider'}
    rid = last_call.get('response_id')
    if isinstance(rid, str) and _ID_OK.match(rid):
        out['response_id_sha256'] = hashlib.sha256(rid.encode()).hexdigest()
    else:
        out['response_id_status'] = 'absent' if rid is None else 'rejected'
    usage = last_call.get('usage')
    counts = {}
    if isinstance(usage, dict):
        for k in ('prompt_tokens', 'completion_tokens'):
            v = usage.get(k)
            if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < _MAX_COUNT:
                counts[k] = v
    if len(counts) == 2:
        out['reported_usage'] = counts
    else:
        out['reported_usage_status'] = 'absent_or_invalid'
    return out


class AuditRecordAfterSuccess(RuntimeError):
    """Adapter returned, but its audit completion record failed. DO NOT RETRY.

    This says nothing about provider transport/billing: the wrapped adapter may
    be a queue or mock. A caller must reconcile its own evidence before acting.
    """
    retry_safe = False
    adapter_returned = True

    def __init__(self, call_id):
        self.call_id = call_id
        super().__init__('adapter returned but audit write failed; do not retry '
                         f'automatically; reconcile call_id={call_id}')


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
            try:
                self._record(dict(event='adapter_call_error', call_id=call_id,
                                  error_type=type(exc).__name__))
            except Exception as audit_exc:
                # Preserve the adapter exception as the raised failure. The
                # failed audit write is its cause, never a replacement verdict.
                raise exc from audit_exc
            raise
        try:
            row = dict(event='adapter_call_returned', call_id=call_id,
                       provider_tokens=None)
            evidence = reported_call_evidence(getattr(self.inner, 'last_call', None))
            if evidence is not None:
                row['reported'] = evidence
            self._record(row)
        except Exception as audit_exc:
            raise AuditRecordAfterSuccess(call_id) from audit_exc
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
