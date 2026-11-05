"""Offline Builder-call audit runner. Makes no network call itself.

One audited call through PromptAuditAdapter around a caller-supplied adapter,
then a small local record. This is NOT a Ryan ledger role and does not touch the
Ryan ledger, allowances or caps; whoever supplies the adapter owns those.

Provenance is explicit and caller-declared, never inferred from the data:
- 'fake'                : test double. Provider totals are always None.
- 'provider_unverified' : adapter claims to call a real provider. Reported usage
                          is counted but remains provider-REPORTED, not verified.
Raw prompts, model text, and raw provider ids are never written; only the
sanitized audit rows, a join summary and the exception TYPE name on failure.
"""
from __future__ import annotations

import json
import os

from .prompt_audit import PromptAuditAdapter, render_audited_prompt
from .usage_join import join, usage_from_audit

PROVENANCE = ('fake', 'provider_unverified')


def _read(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as fh:
        return [json.loads(l) for l in fh if l.strip()]


def run_builder_call(context, adapter, audit_path, record_path, provenance):
    """Run exactly one audited call. Returns the record dict (also written).

    Refuses (before any call) on unknown provenance or an existing record_path,
    so a rerun can never silently overwrite or double-spend an earlier record.
    Adapter exceptions are recorded by type and then re-raised unchanged.
    """
    if provenance not in PROVENANCE:
        raise ValueError(f'provenance must be one of {PROVENANCE}')
    if provenance == 'provider_unverified' and getattr(type(adapter), 'REPORTS_PROVIDER_USAGE', False) is not True:
        raise ValueError('provider_unverified requires an adapter class declaring REPORTS_PROVIDER_USAGE')
    if os.path.exists(record_path):
        raise FileExistsError('record already exists; refusing to rerun')
    before = len(_read(audit_path))
    system, task, _ = render_audited_prompt(**context)
    wrapped = PromptAuditAdapter(adapter, audit_path, lambda: dict(context))
    error_type = None
    exc = None
    try:
        wrapped.complete(system, task)
    except BaseException as e:  # record then re-raise; never swallow halts
        error_type, exc = type(e).__name__, e
    rows = _read(audit_path)[before:]
    rep = join(rows, usage_from_audit(rows))
    if provenance == 'fake':
        for r in rep['rows']:
            r['prompt_tokens'] = r['completion_tokens'] = None
        rep['provider_prompt_tokens'] = rep['provider_completion_tokens'] = None
        rep['provider_joined'] = 0
    record = {'schema': 'builder-audit-record/v1', 'provenance': provenance,
              'status': 'error' if error_type else 'returned',
              'error_type': error_type, 'audit_rows': len(rows),
              'join': rep,
              'note': 'usage is provider-reported, not verified; no prompts, '
                      'model text or raw ids stored'}
    tmp = record_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(record, fh, indent=2)
        fh.write('\n')
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, record_path)
    if exc is not None:
        raise exc
    return record
