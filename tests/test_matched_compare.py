import hashlib
import unittest
import uuid
from launcher.matched_compare import compare


def U4(n):
    return str(uuid.UUID(bytes=hashlib.md5(n.encode()).digest(), version=4))


def J(*toks, status='joined_provider', pre='c', rid=False):
    rows = [{'call_id': U4(f'{pre}{i}'), 'status': status, 'prompt_tokens': t, 'completion_tokens': 1,
             'response_id_sha256': (U4(f'{pre}{i}r') if rid else None)} for i, t in enumerate(toks)]
    return {'schema': 'usage-join/v1', 'rows': rows, 'total_calls': len(rows),
            'provider_joined': len(rows) if status == 'joined_provider' else 0}


def R(tid, toks, acc=True, **kw):
    kw.setdefault('pre', tid + '-')
    return {'task_id': tid, 'accepted': acc, 'join': J(*toks, **kw)}


def arm(n, t):
    # arms differ in token level; use it as the call-id namespace so ids stay unique across arms
    return [R(f't{i}', [t], pre=f't{i}-{t}-') for i in range(n)]


class T(unittest.TestCase):
    def test_measured(self):
        r = compare(arm(5, 99), arm(5, 49))
        self.assertEqual(r['verdict'], 'measured')
        self.assertEqual(r['saving_percent'], 50.0)
        self.assertEqual(r['baseline_tokens'], 500)

    def test_insufficient_no_percent(self):
        r = compare(arm(4, 99), arm(4, 49))
        self.assertEqual(r['verdict'], 'insufficient')
        self.assertIsNone(r['saving_percent'])

    def test_partial_coverage_no_headline(self):
        b = arm(10, 99); v = arm(10, 49)
        for x in v[5:]: x['join'] = {'schema': 'usage-join/v1', 'rows': [], 'total_calls': 0, 'provider_joined': 0}
        r = compare(b, v)
        self.assertEqual(r['verdict'], 'partial_coverage')
        self.assertIsNone(r['saving_percent'])
        self.assertEqual(r['restricted_saving_percent'], 50.0)
        self.assertEqual(r['coverage'], {'accepted_in_both': 10, 'comparable': 5})

    def test_call_id_must_be_uuid4(self):
        for bad in (None, '', 'c0', str(uuid.uuid1()), U4('z').upper(), U4('z').replace('-', '')):
            v = arm(5, 49)
            v[0]['join']['rows'][0]['call_id'] = bad
            self.assertEqual(compare(arm(5, 99), v)['matched_pairs'], 4, bad)

    def test_bool_totals_rejected(self):
        v = arm(5, 49)
        v[0]['join']['rows'] = v[0]['join']['rows'][:1]
        v[0]['join']['total_calls'] = True; v[0]['join']['provider_joined'] = True
        self.assertEqual(compare(arm(5, 99), v)['matched_pairs'], 4)

    def test_unaccepted_either_arm_excluded(self):
        b = arm(6, 99); v = arm(6, 49); v[0]['accepted'] = False; b[1]['accepted'] = 'yes'
        r = compare(b, v)
        self.assertEqual(r['matched_pairs'], 4)
        self.assertEqual({e['reason'] for e in r['excluded']}, {'not_accepted_in_both_arms'})

    def test_mock_missing_error_never_zero(self):
        b = arm(5, 99); v = arm(5, 49)
        v[0] = R('t0', [1], status='joined_mock', pre='m')
        v[1] = R('t1', [1], status='no_usage_record')
        v[2] = {'task_id': 't2', 'accepted': True, 'join': {'rows': []}}
        v[3] = R('t3', [])
        v[4] = {'task_id': 't4', 'accepted': True, 'join': dict(J(5), total_calls=9)}
        r = compare(b, v)
        self.assertEqual(r['matched_pairs'], 0)
        self.assertEqual(len(r['excluded']), 5)

    def test_partial_task_with_one_unknown_call_excluded(self):
        v = arm(5, 49)
        v[0]['join']['rows'].append({'call_id': U4('x'), 'status': 'no_usage_record', 'prompt_tokens': None, 'completion_tokens': None})
        self.assertEqual(compare(arm(5, 99), v)['matched_pairs'], 4)

    def test_duplicates_missing_and_garbage(self):
        b = arm(6, 99) + [R('t0', [1])]
        v = arm(5, 49) + ['junk', {'task_id': ''}]
        r = compare(b, v)
        reasons = {e['task_id']: e['reason'] for e in r['excluded']}
        self.assertEqual(reasons['t0'], 'duplicate_task_id')
        self.assertEqual(reasons['t5'], 'missing_in_one_arm')
        self.assertEqual(r['ignored_records'], 2)
        self.assertEqual(r['matched_pairs'], 4)

    def test_bad_counts_and_bools(self):
        v = arm(5, 49)
        v[0]['join']['rows'][0]['prompt_tokens'] = True
        v[1]['join']['rows'][0]['completion_tokens'] = -1
        self.assertEqual(compare(arm(5, 99), v)['matched_pairs'], 3)

    def test_bad_min_pairs_and_zero_base(self):
        self.assertEqual(compare(arm(5, 99), arm(5, 49), min_pairs=0)['verdict'], 'insufficient')
        self.assertEqual(compare(arm(5, 99), arm(5, 49), min_pairs=True)['verdict'], 'insufficient')
        z = [R(f't{i}', [0]) for i in range(5)]
        for x in z: x['join']['rows'][0]['completion_tokens'] = 0
        self.assertEqual(compare(z, z)['verdict'], 'insufficient')

    def test_negative_saving_reported(self):
        self.assertEqual(compare(arm(5, 49), arm(5, 99))['saving_percent'], -100.0)

    def test_bad_inputs_no_raise(self):
        self.assertEqual(compare(None, 'x')['matched_pairs'], 0)

    def test_survivorship_not_headline(self):
        b = arm(10, 99); v = arm(10, 49)
        for x in v[5:]: x['accepted'] = False
        r = compare(b, v)
        self.assertEqual(r['verdict'], 'survivor_only')
        self.assertIsNone(r['saving_percent'])
        self.assertEqual(r['restricted_saving_percent'], 50.0)
        self.assertEqual(r['arms'], {'baseline': {'tasks': 10, 'accepted': 10}, 'variant': {'tasks': 10, 'accepted': 5}})
        self.assertFalse(r['accepted_sets_equal'])

    def test_same_join_reused_across_tasks(self):
        j = J(99, pre='shared')
        b = [{'task_id': f't{i}', 'accepted': True, 'join': j} for i in range(5)]
        r = compare(b, arm(5, 49))
        self.assertEqual(r['matched_pairs'], 0)
        self.assertEqual({e['reason'] for e in r['excluded']}, {'reused_usage_id'})

    def test_reused_across_arms_and_response_id(self):
        b = arm(5, 99); v = arm(5, 49)
        v[0]['join'] = b[0]['join']
        b[1]['join'] = J(99, pre='q', rid=True); v[1]['join'] = J(49, pre='z', rid=True)
        v[1]['join']['rows'][0]['response_id_sha256'] = U4('q0r')
        r = compare(b, v)
        self.assertEqual(r['matched_pairs'], 3)

    def test_provider_joined_total_mismatch(self):
        v = arm(5, 49); v[0]['join']['provider_joined'] = 0
        self.assertEqual(compare(arm(5, 99), v)['matched_pairs'], 4)

    def test_count_bound(self):
        v = arm(5, 49); v[0]['join']['rows'][0]['prompt_tokens'] = 10 ** 9
        self.assertEqual(compare(arm(5, 99), v)['matched_pairs'], 4)

    def test_forged_status_known_limit(self):
        # documented limit: caller-supplied flags are unauthenticated
        self.assertEqual(compare(arm(5, 99), arm(5, 49))['verdict'], 'measured')


if __name__ == '__main__':
    unittest.main()
