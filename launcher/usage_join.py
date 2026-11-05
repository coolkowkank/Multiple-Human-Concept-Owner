"""Offline join of prompt-audit call records to provider-reported usage.

Pure functions over already-written records. No network, credentials, or
transport. Purpose: before any live comparison, show which audited calls have
a provider-reported request id and usage, and keep mock vs provider apart.

Rules (fail closed, never infer):
- A call_id counts only if it has a start row and exactly one terminal row.
- Usage comes only from an explicit usage record naming the same call_id AND a
  non-empty request_id. chars/4 estimates are never promoted to tokens.
- origin must be 'provider' or 'mock'. Mock rows never produce token totals.
- Duplicate or conflicting usage for a call_id is an error row, not a pick.
"""
from __future__ import annotations

TERMINAL = ('adapter_call_returned', 'adapter_call_error')
ORIGINS = ('provider', 'mock')


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def join(audit_rows, usage_rows):
    calls = {}
    for r in audit_rows:
        cid, ev = r.get('call_id'), r.get('event')
        if not cid:
            continue
        c = calls.setdefault(cid, {'start': 0, 'terminal': [], 'est': None})
        if ev == 'adapter_call_start':
            c['start'] += 1
            a = r.get('audit') or {}
            c['est'] = ((a.get('system') or {}).get('est_tokens_chars_div_4', 0)
                        + (a.get('task') or {}).get('est_tokens_chars_div_4', 0))
        elif ev in TERMINAL:
            c['terminal'].append(ev)
    usage = {}
    for u in usage_rows:
        usage.setdefault(u.get('call_id'), []).append(u)
    out = []
    for cid, c in sorted(calls.items()):
        row = {'call_id': cid, 'est_tokens_chars_div_4': c['est'],
               'status': None, 'origin': None, 'request_id': None,
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
                elif not u.get('request_id') or not isinstance(u.get('request_id'), str):
                    row['status'] = 'error:missing_request_id'
                elif _int(u.get('prompt_tokens')) is None or _int(u.get('completion_tokens')) is None:
                    row['status'] = 'error:bad_usage_counts'
                else:
                    row['request_id'] = u['request_id']
                    row['status'] = 'joined_' + u['origin']
                    if u['origin'] == 'provider':
                        row['prompt_tokens'] = u['prompt_tokens']
                        row['completion_tokens'] = u['completion_tokens']
        out.append(row)
    ids = [r['request_id'] for r in out if r['request_id']]
    if len(ids) != len(set(ids)):
        for r in out:
            if r['request_id'] and ids.count(r['request_id']) > 1:
                r['status'] = 'error:request_id_reused'
                r['prompt_tokens'] = r['completion_tokens'] = None
    prov = [r for r in out if r['status'] == 'joined_provider']
    return {'schema': 'usage-join/v1', 'rows': out,
            'provider_joined': len(prov), 'total_calls': len(out),
            'provider_prompt_tokens': sum(r['prompt_tokens'] for r in prov) if prov else None,
            'provider_completion_tokens': sum(r['completion_tokens'] for r in prov) if prov else None,
            'note': 'totals cover only provider-joined calls; mock and estimate rows excluded'}


def main(argv=None):
    """python -m launcher.usage_join AUDIT.jsonl USAGE.jsonl > report.json (offline)."""
    import json, sys
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        sys.exit('usage: usage_join AUDIT.jsonl USAGE.jsonl')
    rd = lambda p: [json.loads(l) for l in open(p, encoding='utf-8') if l.strip()]
    json.dump(join(rd(argv[0]), rd(argv[1])), sys.stdout, indent=2)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
