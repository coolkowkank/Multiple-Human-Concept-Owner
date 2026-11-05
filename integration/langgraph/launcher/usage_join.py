"""Offline join of prompt-audit call records to provider-reported usage.

Pure functions over already-written records. No network, credentials, or
transport. Purpose: before any live comparison, show which audited calls have
a provider-reported request id and usage, and keep mock vs provider apart.

Rules (fail closed, never infer):
- A call_id counts only if it has a start row and exactly one terminal row.
- Usage comes only from an explicit usage record naming the same local call_id.
  The provider id (response_id_sha256 field) is OPTIONAL opaque evidence; when present it
  must be a non-empty string and must not repeat across calls. chars/4 estimates are never promoted to tokens.
- origin must be 'provider' or 'mock'. Mock rows never produce token totals.
- Non-dict rows or rows without a str call_id are ignored and counted, never
  raised on. Usage counts must be plain ints in [0, 1e9).
- CLI input sources: usage derived from the audit file's 'reported' evidence is
  ADDED to the explicit USAGE file; a call_id present in both is a duplicate and
  yields error:duplicate_usage (neither is preferred).
- Duplicate or conflicting usage for a call_id is an error row, not a pick.
"""
from __future__ import annotations

TERMINAL = ('adapter_call_returned', 'adapter_call_error')
ORIGINS = ('provider', 'mock')


MAX_COUNT = 10 ** 9  # same bound as prompt_audit.reported_call_evidence


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < MAX_COUNT else None


def _rows(rows):
    """Keep only dict rows with a str call_id; count the rest, never raise."""
    keep, ignored = [], 0
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and isinstance(r.get('call_id'), str):
            keep.append(r)
        else:
            ignored += 1
    return keep, ignored


def usage_from_audit(audit_rows):
    """Derive usage rows from sanitized 'reported' evidence on returned rows.

    response_id_sha256 is the sha256 of the provider-reported RESPONSE id when it is
    well-formed, else None; it is not a vendor-proven request id. The local
    call_id is the join key. Rows without valid usage yield nothing.
    """
    out = []
    audit_rows, _ = _rows(audit_rows)
    for r in audit_rows:
        rep = r.get('reported') if r.get('event') in TERMINAL else None
        if not isinstance(rep, dict) or rep.get('origin') != 'provider':
            continue
        u, rid = rep.get('reported_usage'), rep.get('response_id_sha256')
        if isinstance(u, dict):
            out.append({'call_id': r.get('call_id'), 'origin': 'provider',
                        'response_id_sha256': rid or None, 'prompt_tokens': u.get('prompt_tokens'),
                        'completion_tokens': u.get('completion_tokens')})
    return out


def join(audit_rows, usage_rows):
    audit_rows, ign_a = _rows(audit_rows)
    usage_rows, ign_u = _rows(usage_rows)
    calls = {}
    for r in audit_rows:
        cid, ev = r.get('call_id'), r.get('event')
        if not cid:
            continue
        c = calls.setdefault(cid, {'start': 0, 'terminal': [], 'est': None})
        if ev == 'adapter_call_start':
            c['start'] += 1
            a = r.get('audit') or {}
            sysv = _int(((a.get('system') if isinstance(a.get('system'), dict) else {}) or {}).get('est_tokens_chars_div_4', 0)) if isinstance(a, dict) else None
            taskv = _int(((a.get('task') if isinstance(a.get('task'), dict) else {}) or {}).get('est_tokens_chars_div_4', 0)) if isinstance(a, dict) else None
            # heuristic only; malformed parts make the estimate None, never raise
            c['est'] = sysv + taskv if sysv is not None and taskv is not None else None
        elif ev in TERMINAL:
            c['terminal'].append(ev)
    usage = {}
    for u in usage_rows:
        usage.setdefault(u.get('call_id'), []).append(u)
    out = []
    for cid, c in sorted(calls.items()):
        row = {'call_id': cid, 'est_tokens_chars_div_4': c['est'],
               'status': None, 'origin': None, 'response_id_sha256': None,
               'prompt_tokens': None, 'completion_tokens': None}
        if c['start'] != 1 or len(c['terminal']) != 1:
            row['status'] = 'error:incomplete_or_duplicate_audit'
        else:
            us = usage.get(cid, [])
            if not us:
                row['status'] = 'no_usage_record'
            elif len(us) > 1:
                row['status'] = 'error:duplicate_usage'
            else:
                u = us[0]
                row['origin'] = u.get('origin')
                if u.get('origin') not in ORIGINS:
                    row['status'] = 'error:bad_origin'
                elif u.get('response_id_sha256') is not None and not (
                        isinstance(u.get('response_id_sha256'), str) and u['response_id_sha256']):
                    row['status'] = 'error:bad_response_id'
                elif _int(u.get('prompt_tokens')) is None or _int(u.get('completion_tokens')) is None:
                    row['status'] = 'error:bad_usage_counts'
                else:
                    row['response_id_sha256'] = u.get('response_id_sha256')
                    row['status'] = 'joined_' + u['origin']
                    if u['origin'] == 'provider':
                        row['prompt_tokens'] = u['prompt_tokens']
                        row['completion_tokens'] = u['completion_tokens']
        out.append(row)
    ids = [r['response_id_sha256'] for r in out if r['response_id_sha256']]
    if len(ids) != len(set(ids)):
        for r in out:
            if r['response_id_sha256'] and ids.count(r['response_id_sha256']) > 1:
                r['status'] = 'error:response_id_reused'
                r['prompt_tokens'] = r['completion_tokens'] = None
    prov = [r for r in out if r['status'] == 'joined_provider']
    return {'schema': 'usage-join/v1', 'rows': out,
            'provider_joined': len(prov), 'total_calls': len(out),
            'provider_prompt_tokens': sum(r['prompt_tokens'] for r in prov) if prov else None,
            'provider_completion_tokens': sum(r['completion_tokens'] for r in prov) if prov else None,
            'ignored_audit_rows': ign_a, 'ignored_usage_rows': ign_u,
            'note': 'totals cover only provider-joined calls; mock and estimate rows excluded'}


def main(argv=None):
    """python -m launcher.usage_join AUDIT.jsonl USAGE.jsonl > report.json (offline)."""
    import json, sys
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        sys.exit('usage: usage_join AUDIT.jsonl USAGE.jsonl')
    def rd(p):
        rows = []
        with open(p, encoding='utf-8') as fh:
            for n, l in enumerate(fh, 1):
                if l.strip():
                    try:
                        rows.append(json.loads(l))
                    except ValueError:
                        sys.exit(f'{p}:{n}: not valid JSON (no rows used)')
        return rows
    audit = rd(argv[0])
    json.dump(join(audit, rd(argv[1]) + usage_from_audit(audit)), sys.stdout, indent=2)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
