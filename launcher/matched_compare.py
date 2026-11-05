"""Offline matched token comparison between two arms (WP9). No network.

Input per arm: list of {'task_id': str, 'accepted': bool, 'join': <usage-join/v1 report>}.
`accepted` is the independent acceptance outcome for that task, recorded outside this
module. Rules (fail closed, never infer):
- A task is comparable only if it appears exactly once in each arm, is accepted (the
  literal True) in BOTH arms, and every call in its join report is 'joined_provider'
  with counts. Anything else is excluded with a reason and never counted as zero.
- Mock, estimate, missing or errored usage excludes the task. Totals come only from
  provider-reported counts.
- Call ids and provider response-id hashes (when present) must be unique across ALL
  tasks and both arms. A task whose id also appears in any other task, or twice in
  itself, is excluded as 'reused_usage_id', so one usage record cannot be counted again.
- Counts must be ints in [0, 1e9), the same bound as usage_join.
- If the accepted task sets differ between arms, the result is 'survivor_only': the
  saving is computed over tasks accepted in both arms and is given as
  survivor_saving_percent, never as saving_percent. It says nothing about equal quality.
- Savings are reported only over matched pairs. Below `min_pairs` the verdict is
  'insufficient' and no percentage is given.
- LIMITS: `accepted` and the join report are caller-supplied and unauthenticated. A
  forged 'joined_provider' status or invented ids pass; this module checks internal
  consistency only. It is not proof of provider usage, not a significance test, and not
  a WP9 completion. No significance claim is made: this is
  descriptive arithmetic over the matched pairs, not proof of an effect.
"""
from __future__ import annotations

SCHEMA = 'matched-compare/v1'
MAX_COUNT = 10 ** 9  # same bound as usage_join


def _tokens(join):
    """Return (total_tokens, None) or (None, reason)."""
    if not isinstance(join, dict) or join.get('schema') != 'usage-join/v1' or not isinstance(join.get('rows'), list):
        return None, 'bad_join_report'
    rows = join['rows']
    if not rows:
        return None, 'no_calls'
    if join.get('total_calls') != len(rows) or join.get('provider_joined') != len(rows):
        return None, 'join_totals_inconsistent'
    tot = 0
    for r in rows:
        if not isinstance(r, dict) or r.get('status') != 'joined_provider':
            return None, 'usage_not_provider_joined'
        p, c = r.get('prompt_tokens'), r.get('completion_tokens')
        if not all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v < MAX_COUNT for v in (p, c)):
            return None, 'usage_not_provider_joined'
        tot += p + c
    return tot, None


def _ids(rec):
    """Usage identifiers of one record: call_id and (if present) response id hash."""
    out = []
    j = rec.get('join') if isinstance(rec, dict) else None
    for r in (j.get('rows') if isinstance(j, dict) and isinstance(j.get('rows'), list) else []):
        if isinstance(r, dict):
            for k in ('call_id', 'response_id_sha256'):
                if r.get(k) is not None:
                    out.append((k, str(r[k])))
    return out


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
    from collections import Counter
    cnt = Counter()
    per = {}
    for arm_name, d in (('a', a), ('b', b)):
        for tid, rec in d.items():
            ids = _ids(rec)
            per[(arm_name, tid)] = ids
            cnt.update(ids)
    def reused(tid):
        return any(cnt[i] > 1 for k in ('a', 'b') for i in per.get((k, tid), []))
    pairs, excluded = [], []
    for tid in sorted(set(a) | set(b)):
        if tid in dup_a or tid in dup_b:
            excluded.append({'task_id': tid, 'reason': 'duplicate_task_id'})
        elif reused(tid):
            excluded.append({'task_id': tid, 'reason': 'reused_usage_id'})
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
    acc_a = {t for t, r in a.items() if r.get('accepted') is True and t not in dup_a}
    acc_b = {t for t, r in b.items() if r.get('accepted') is True and t not in dup_b}
    survivor = acc_a != acc_b
    arms = {'baseline': {'tasks': len(a), 'accepted': len(acc_a)},
            'variant': {'tasks': len(b), 'accepted': len(acc_b)}}
    n = len(pairs)
    base = sum(p['baseline_tokens'] for p in pairs)
    var = sum(p['variant_tokens'] for p in pairs)
    ok = isinstance(min_pairs, int) and not isinstance(min_pairs, bool) and min_pairs >= 1 and n >= min_pairs and base > 0
    pct = round(100.0 * (base - var) / base, 2) if ok else None
    verdict = 'insufficient' if not ok else ('survivor_only' if survivor else 'measured')
    return {'schema': SCHEMA, 'verdict': verdict, 'arms': arms,
            'accepted_sets_equal': not survivor,
            'matched_pairs': n, 'min_pairs': min_pairs, 'pairs': pairs, 'excluded': excluded,
            'ignored_records': bad_a + bad_b,
            'baseline_tokens': base if ok else None, 'variant_tokens': var if ok else None,
            'saving_percent': pct if verdict == 'measured' else None,
            'survivor_saving_percent': pct if verdict == 'survivor_only' else None,
            'note': 'descriptive, matched accepted tasks only; caller-supplied unauthenticated inputs; not provider proof, not a significance test, not WP9 completion; survivor_only says nothing about equal quality'}
