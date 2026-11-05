import unittest
from launcher.matched_compare import compare


def J(*toks, status='joined_provider'):
    return {'schema': 'usage-join/v1', 'rows': [
        {'call_id': f'c{i}', 'status': status, 'prompt_tokens': t, 'completion_tokens': 1} for i, t in enumerate(toks)]}


def R(tid, toks, acc=True, **kw):
    return {'task_id': tid, 'accepted': acc, 'join': J(*toks, **kw)}


def arm(n, t):
    return [R(f't{i}', [t]) for i in range(n)]


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

    def test_unaccepted_either_arm_excluded(self):
        b = arm(6, 99); v = arm(6, 49); v[0]['accepted'] = False; b[1]['accepted'] = 'yes'
        r = compare(b, v)
        self.assertEqual(r['matched_pairs'], 4)
        self.assertEqual({e['reason'] for e in r['excluded']}, {'not_accepted_in_both_arms'})

    def test_mock_missing_error_never_zero(self):
        b = arm(5, 99); v = arm(5, 49)
        v[0] = R('t0', [1], status='joined_mock')
        v[1] = R('t1', [1], status='no_usage_record')
        v[2] = {'task_id': 't2', 'accepted': True, 'join': {'rows': []}}
        v[3] = R('t3', [])
        r = compare(b, v)
        self.assertEqual(r['matched_pairs'], 1)
        self.assertEqual(len(r['excluded']), 4)

    def test_partial_task_with_one_unknown_call_excluded(self):
        v = arm(5, 49)
        v[0]['join']['rows'].append({'call_id': 'x', 'status': 'no_usage_record', 'prompt_tokens': None, 'completion_tokens': None})
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


if __name__ == '__main__':
    unittest.main()
