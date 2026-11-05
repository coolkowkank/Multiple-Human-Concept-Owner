"""Offline matched token comparison between two arms (WP9). No network.

Input per arm: list of {'task_id': str, 'accepted': bool, 'join': <usage-join/v1 report>}.
`accepted` is the independent acceptance outcome for that task, recorded outside this
module. Rules (fail closed, never infer):
- A task is comparable only if it appears exactly once in each arm, is accepted (the
  literal True) in BOTH arms, and every call in its join report is 'joined_provider'
  with counts. Anything else is excluded with a reason and never counted as zero.
- Mock, estimate, missing or errored usage excludes the task. Totals come only from
  provider-reported counts.
- Savings are reported only over matched pairs. Below `min_pairs` the verdict is
  'insufficient' and no percentage is given. No significance claim is made: this is
  descriptive arithmetic over the matched pairs, not proof of an effect.
"""
from __future__ import annotations

SCHEMA = 'matched-compare/v1'


def _tokens(join):
    """Return (total_tokens, None) or (None, reason)."""
    if not isinstance(join, dict) or join.get('schema') != 'usage-join/v1' or not isinstance(join.get('rows'), list):
        return None, 'bad_join_report'
    rows = join['rows']
    if not rows:
        return None, 'no_calls'
    tot = 0
    for r in rows:
        if not isinstance(r, dict) or r.get('status') != 'joined_provider':
            return None, 'usage_not_provider_joined'
        p, c = r.get('prompt_tokens'), r.get('completion_tokens')
        if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (p, c)):
            return None, 'usage_not_provider_joined'
        tot += p + c
    return tot, None


def _arm(records):
    seen, dup, bad = {}, set(), 0
    for r in records if isinstance(records, list) else []:
        tid = r.get('task_id') if isinstance(r, dict) else None
        if not isinstance(tid, str) or not tid:
            bad += 1
            continue
        if tid in seen:
            dup.add(tid)
        seen[tid] = r
    return seen, dup, bad


def compare(baseline, variant, min_pairs=5):
    a, dup_a, bad_a = _arm(baseline)
    b, dup_b, bad_b = _arm(variant)
    pairs, excluded = [], []
    for tid in sorted(set(a) | set(b)):
        if tid in dup_a or tid in dup_b:
            excluded.append({'task_id': tid, 'reason': 'duplicate_task_id'})
        elif tid not in a or tid not in b:
            excluded.append({'task_id': tid, 'reason': 'missing_in_one_arm'})
        elif a[tid].get('accepted') is not True or b[tid].get('accepted') is not True:
            excluded.append({'task_id': tid, 'reason': 'not_accepted_in_both_arms'})
        else:
            ta, ra = _tokens(a[tid].get('join'))
            tb, rb = _tokens(b[tid].get('join'))
            if ra or rb:
                excluded.append({'task_id': tid, 'reason': ra or rb})
            else:
                pairs.append({'task_id': tid, 'baseline_tokens': ta, 'variant_tokens': tb,
                              'delta': ta - tb})
    n = len(pairs)
    base = sum(p['baseline_tokens'] for p in pairs)
    var = sum(p['variant_tokens'] for p in pairs)
    ok = isinstance(min_pairs, int) and not isinstance(min_pairs, bool) and min_pairs >= 1 and n >= min_pairs and base > 0
    return {'schema': SCHEMA, 'verdict': 'measured' if ok else 'insufficient',
            'matched_pairs': n, 'min_pairs': min_pairs, 'pairs': pairs, 'excluded': excluded,
            'ignored_records': bad_a + bad_b,
            'baseline_tokens': base if ok else None, 'variant_tokens': var if ok else None,
            'saving_percent': round(100.0 * (base - var) / base, 2) if ok else None,
            'note': 'descriptive, matched accepted tasks only; provider-reported counts only; not a significance test'}
