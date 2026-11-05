# Provenance: first draft model-authored (nvidia/nemotron-3-ultra-550b-a55b via
# Requesty free route; one call, provider-reported usage 2306 prompt / 3224
# completion / 5530 total, cost 0, not verified). Edited by the
# product worker after independent review: the original asserted unbounded huge
# ints and raising on non-dict rows against f4576df; those now assert the
# corrected behavior (bound 10**9, rows ignored and counted).
import unittest
from launcher.usage_join import join


def A(cid, term='adapter_call_returned', est=10, audit=None):
    """Build a pair of audit rows (start + terminal) for call_id."""
    start = {'event': 'adapter_call_start', 'call_id': cid}
    if audit is not None:
        start['audit'] = audit
    else:
        start['audit'] = {
            'system': {'est_tokens_chars_div_4': est},
            'task': {'est_tokens_chars_div_4': est}
        }
    return [start, {'event': term, 'call_id': cid}]


def U(cid, origin='provider', rid='r1', p=5, c=3):
    """Build a usage row."""
    return {'call_id': cid, 'origin': origin, 'response_id_sha256': rid, 'prompt_tokens': p, 'completion_tokens': c}


class HostileTests(unittest.TestCase):
    def _status(self, rep, cid):
        for row in rep['rows']:
            if row['call_id'] == cid:
                return row['status']
        return None

    def _row(self, rep, cid):
        for row in rep['rows']:
            if row['call_id'] == cid:
                return row
        return None

    # 1. usage row fields of wrong types
    def test_request_id_non_string_types(self):
        for bad_rid in ([], 123, {}, 0, False):
            r = join(A('a'), [U('a', rid=bad_rid)])
            self.assertEqual(self._status(r, 'a'), 'error:bad_response_id')
            self.assertIsNone(r['provider_prompt_tokens'])

    def test_absent_response_id_counts_reported_usage(self):
        r = join(A('a'), [U('a', rid=None)])
        self.assertEqual(self._status(r, 'a'), 'joined_provider')
        self.assertEqual(r['provider_prompt_tokens'], 5)

    def test_call_id_none_in_usage_ignored(self):
        # usage row with call_id None should not create a row in output
        r = join(A('a'), [{'call_id': None, 'origin': 'provider', 'response_id_sha256': 'r1', 'prompt_tokens': 1, 'completion_tokens': 1}])
        self.assertEqual(len(r['rows']), 1)
        self.assertEqual(self._status(r, 'a'), 'no_usage_record')

    def test_prompt_tokens_invalid_types(self):
        for bad_p in (1.5, '5', float('inf'), True, False, -1, None):
            r = join(A('a'), [U('a', p=bad_p)])
            self.assertEqual(self._status(r, 'a'), 'error:bad_usage_counts')

    def test_completion_tokens_invalid_types(self):
        for bad_c in (1.5, '3', float('inf'), True, False, -1, None):
            r = join(A('a'), [U('a', c=bad_c)])
            self.assertEqual(self._status(r, 'a'), 'error:bad_usage_counts')

    def test_huge_int_rejected_at_wrapper_bound(self):
        # Regression: f4576df accepted 10**100 into provider totals. The bound
        # is 0 <= n < 10**9, same as the audit wrapper.
        for v in (10**9, 10**100):
            for kw in ({'p': v}, {'c': v}):
                r = join(A('a'), [U('a', **kw)])
                self.assertEqual(self._status(r, 'a'), 'error:bad_usage_counts')
                self.assertIsNone(r['provider_prompt_tokens'])
        r = join(A('a'), [U('a', p=10**9 - 1, c=1)])
        self.assertEqual(self._status(r, 'a'), 'joined_provider')

    # 2. audit rows missing 'audit' key, 'audit' null, est fields absent
    def test_audit_missing_key(self):
        r = join([{'event': 'adapter_call_start', 'call_id': 'a'}, {'event': 'adapter_call_returned', 'call_id': 'a'}], [U('a')])
        self.assertEqual(self._status(r, 'a'), 'joined_provider')
        self.assertEqual(self._row(r, 'a')['est_tokens_chars_div_4'], 0)

    def test_audit_null(self):
        r = join([{'event': 'adapter_call_start', 'call_id': 'a', 'audit': None}, {'event': 'adapter_call_returned', 'call_id': 'a'}], [U('a')])
        self.assertEqual(self._status(r, 'a'), 'joined_provider')
        self.assertEqual(self._row(r, 'a')['est_tokens_chars_div_4'], 0)

    def test_audit_missing_est_fields(self):
        r = join([{'event': 'adapter_call_start', 'call_id': 'a', 'audit': {'system': {}, 'task': {}}}, {'event': 'adapter_call_returned', 'call_id': 'a'}], [U('a')])
        self.assertEqual(self._status(r, 'a'), 'joined_provider')
        self.assertEqual(self._row(r, 'a')['est_tokens_chars_div_4'], 0)

    # 3. usage rows for call_ids with no audit row (ignored, no row created)
    def test_usage_for_unknown_call_id_ignored(self):
        r = join(A('a'), [U('b')])
        self.assertEqual(len(r['rows']), 1)
        self.assertEqual(self._status(r, 'a'), 'no_usage_record')

    # 4. request_id shared across origin provider and mock
    def test_request_id_shared_provider_and_mock(self):
        r = join(A('a') + A('b'), [U('a', rid='shared'), U('b', origin='mock', rid='shared')])
        statuses = {row['status'] for row in r['rows']}
        self.assertEqual(statuses, {'error:response_id_reused'})
        self.assertIsNone(r['provider_prompt_tokens'])
        self.assertIsNone(r['provider_completion_tokens'])

    # 5. 1000 calls mixed; totals equal the sum over joined_provider rows only
    def test_large_mixed_totals(self):
        audit = []
        usage = []
        provider_prompt_sum = 0
        provider_completion_sum = 0
        for i in range(1000):
            cid = f'c{i}'
            audit.extend(A(cid, est=0))
            if i % 3 == 0:
                # provider
                p, c = 2, 1
                usage.append(U(cid, rid=f'r{i}', p=p, c=c))
                provider_prompt_sum += p
                provider_completion_sum += c
            elif i % 3 == 1:
                # mock
                usage.append(U(cid, origin='mock', rid=f'm{i}'))
            else:
                # no usage
                pass
        r = join(audit, usage)
        self.assertEqual(r['provider_joined'], 334)  # 0,3,6,... 999 -> 334
        self.assertEqual(r['provider_prompt_tokens'], provider_prompt_sum)
        self.assertEqual(r['provider_completion_tokens'], provider_completion_sum)
        # ensure mock and no_usage rows don't affect totals
        mock_rows = [row for row in r['rows'] if row['status'] == 'joined_mock']
        self.assertEqual(len(mock_rows), 333)
        no_usage_rows = [row for row in r['rows'] if row['status'] == 'no_usage_record']
        self.assertEqual(len(no_usage_rows), 333)

    # 6. non-dict rows are ignored and counted, never raised on
    def test_non_dict_audit_row_ignored(self):
        r = join(['not a dict'] + A('a'), [])
        self.assertEqual(r['ignored_audit_rows'], 1)
        self.assertEqual(self._status(r, 'a'), 'no_usage_record')

    def test_non_dict_usage_row_ignored(self):
        r = join(A('a'), ['not a dict', U('a')])
        self.assertEqual(r['ignored_usage_rows'], 1)
        self.assertEqual(self._status(r, 'a'), 'joined_provider')


if __name__ == '__main__':
    unittest.main()

class EstimateRobustness(unittest.TestCase):
    def test_malformed_estimate_fields_do_not_raise(self):
        for bad in ('x', None, 1.5, [1], {'a': 1}, True, -3, 10**12):
            rows = [{'event': 'adapter_call_start', 'call_id': 'a',
                     'audit': {'system': {'est_tokens_chars_div_4': bad},
                               'task': {'est_tokens_chars_div_4': 1}}},
                    {'event': 'adapter_call_returned', 'call_id': 'a'}]
            r = join(rows, [])
            self.assertEqual(r['rows'][0]['status'], 'no_usage_record')
            self.assertIsNone(r['rows'][0]['est_tokens_chars_div_4'] if bad is not None else None)
        for audit in ('str', [1]):
            r = join([{'event': 'adapter_call_start', 'call_id': 'a', 'audit': audit},
                      {'event': 'adapter_call_returned', 'call_id': 'a'}], [])
            self.assertIsNone(r['rows'][0]['est_tokens_chars_div_4'])
