import unittest
from launcher.usage_join import join


def A(cid, term='adapter_call_returned', est=10):
    return [{'event': 'adapter_call_start', 'call_id': cid,
             'audit': {'system': {'est_tokens_chars_div_4': est}, 'task': {'est_tokens_chars_div_4': est}}},
            {'event': term, 'call_id': cid}]


def U(cid, origin='provider', rid='r1', p=5, c=3):
    return {'call_id': cid, 'origin': origin, 'request_id': rid, 'prompt_tokens': p, 'completion_tokens': c}


class T(unittest.TestCase):
    def st(self, rep, i=0):
        return rep['rows'][i]['status']

    def test_provider_joined(self):
        r = join(A('a'), [U('a')])
        self.assertEqual(self.st(r), 'joined_provider')
        self.assertEqual(r['provider_prompt_tokens'], 5)
        self.assertEqual(r['rows'][0]['est_tokens_chars_div_4'], 20)

    def test_mock_no_totals(self):
        r = join(A('a'), [U('a', origin='mock')])
        self.assertEqual(self.st(r), 'joined_mock')
        self.assertIsNone(r['provider_prompt_tokens'])
        self.assertIsNone(r['rows'][0]['prompt_tokens'])

    def test_no_usage_never_uses_estimate(self):
        r = join(A('a'), [])
        self.assertEqual(self.st(r), 'no_usage_record')
        self.assertIsNone(r['provider_prompt_tokens'])

    def test_empty_id_rejected_absent_id_allowed(self):
        self.assertEqual(self.st(join(A('a'), [U('a', rid='')])), 'error:bad_response_id')
        r = join(A('a'), [U('a', rid=None)])
        self.assertEqual(self.st(r), 'joined_provider')
        self.assertEqual(r['provider_prompt_tokens'], 5)

    def test_bad_counts_and_bool(self):
        self.assertEqual(self.st(join(A('a'), [U('a', p=True)])), 'error:bad_usage_counts')
        self.assertEqual(self.st(join(A('a'), [U('a', c=-1)])), 'error:bad_usage_counts')
        self.assertEqual(self.st(join(A('a'), [U('a', p=None)])), 'error:bad_usage_counts')

    def test_bad_origin(self):
        self.assertEqual(self.st(join(A('a'), [U('a', origin='guess')])), 'error:bad_origin')

    def test_duplicate_usage(self):
        self.assertEqual(self.st(join(A('a'), [U('a'), U('a', rid='r2')])), 'error:duplicate_usage')

    def test_incomplete_audit(self):
        self.assertEqual(self.st(join(A('a')[:1], [U('a')])), 'error:incomplete_or_duplicate_audit')
        self.assertEqual(self.st(join(A('a') + A('a'), [U('a')])), 'error:incomplete_or_duplicate_audit')

    def test_error_terminal_still_joinable(self):
        self.assertEqual(self.st(join(A('a', 'adapter_call_error'), [U('a')])), 'joined_provider')

    def test_reused_request_id_blocks_totals(self):
        r = join(A('a') + A('b'), [U('a'), U('b')])
        self.assertEqual({x['status'] for x in r['rows']}, {'error:request_id_reused'})
        self.assertIsNone(r['provider_prompt_tokens'])

    def test_totals_only_provider(self):
        r = join(A('a') + A('b') + A('c'), [U('a'), U('b', origin='mock', rid='m'), U('c', rid='r3', p=7, c=1)])
        self.assertEqual(r['provider_joined'], 2)
        self.assertEqual(r['provider_prompt_tokens'], 12)
        self.assertEqual(r['provider_completion_tokens'], 4)

if __name__ == '__main__':
    unittest.main()
