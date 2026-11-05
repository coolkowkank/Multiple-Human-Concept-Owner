import json, os, shutil, tempfile, unittest
from unittest import mock
from launcher.adapters import HttpAdapter, MockAdapter
from launcher.prompt_audit import PromptAuditAdapter, reported_call_evidence
from launcher.usage_join import join, usage_from_audit
from launcher import prompts


class Resp:
    def __init__(self, body): self.body = json.dumps(body).encode()
    def read(self): return self.body
    def __enter__(self): return self
    def __exit__(self, *a): return False


def body(**kw):
    b = {"choices": [{"message": {"content": '{"summary": "ok", "handoff": null}'}}]}
    b.update(kw); return b


class Stub:
    REPORTS_PROVIDER_USAGE = True
    def __init__(self, last): self.last_call = last
    def complete(self, s, p): return {"summary": "x", "handoff": None}


def ctx():
    role = sorted(prompts.ROLES)[0]
    return dict(seat='s', role=role, brief='b', state={'turn_seq': 1, 'status_line': 'x'}, recent_log=[])


def run_audit(inner):
    d = tempfile.mkdtemp()
    path = os.path.join(d, 'a.jsonl')
    c = ctx()
    a = PromptAuditAdapter(inner, path, lambda: dict(c))
    sysp, task, _ = __import__('launcher.prompt_audit', fromlist=['x']).render_audited_prompt(**c)
    a.complete(sysp, task)
    rows = [json.loads(l) for l in open(path)]
    shutil.rmtree(d, True)
    return rows


class T(unittest.TestCase):
    def test_http_adapter_exposes_reported_fields(self):
        os.environ['CK'] = 'k'
        a = HttpAdapter('http://x.invalid', 'm', 'CK')
        with mock.patch('urllib.request.urlopen', return_value=Resp(body(id='cmpl-1', usage={'prompt_tokens': 4, 'completion_tokens': 2}))):
            a.complete('s', 'p')
        self.assertEqual(a.last_call['response_id'], 'cmpl-1')

    def test_last_call_cleared_on_failure(self):
        os.environ['CK'] = 'k'
        a = HttpAdapter('http://x.invalid', 'm', 'CK')
        a.last_call = {'stale': 1}
        with mock.patch('urllib.request.urlopen', return_value=Resp({"choices": []})):
            with self.assertRaises(Exception):
                a.complete('s', 'p')
        # the call happened (JSON body returned): evidence is THIS response's, never the stale one
        self.assertNotIn('stale', a.last_call)
        self.assertIsNone(a.last_call['usage'])
        a.last_call = {'stale': 1}
        with mock.patch('urllib.request.urlopen', side_effect=OSError('x')):
            with self.assertRaises(Exception):
                a.complete('s', 'p')
        self.assertIsNone(a.last_call)

    def test_audit_row_has_hash_not_raw_id(self):
        rows = run_audit(Stub({'origin': 'provider', 'response_id': 'cmpl-secret-1', 'usage': {'prompt_tokens': 4, 'completion_tokens': 2}}))
        ret = rows[-1]
        self.assertIsNone(ret['provider_tokens'])
        self.assertNotIn('cmpl-secret-1', json.dumps(rows))
        self.assertEqual(ret['reported']['reported_usage'], {'prompt_tokens': 4, 'completion_tokens': 2})

    def test_hostile_ids_and_usage(self):
        for rid in ('a b', 'x' * 129, '<script>', '../../etc', 5, ['a'], ''):
            e = reported_call_evidence({'origin': 'provider', 'response_id': rid, 'usage': {'prompt_tokens': 1, 'completion_tokens': 1}})
            self.assertNotIn('response_id_sha256', e)
            self.assertEqual(e['response_id_status'], 'rejected')
        self.assertEqual(reported_call_evidence({'origin': 'provider', 'usage': {}})['response_id_status'], 'absent')
        for u in ({'prompt_tokens': True, 'completion_tokens': 1}, {'prompt_tokens': 1.5, 'completion_tokens': 1},
                  {'prompt_tokens': 10**9, 'completion_tokens': 1}, {'prompt_tokens': -1, 'completion_tokens': 1}, 'x', None):
            self.assertIn('reported_usage_status', reported_call_evidence({'origin': 'provider', 'response_id': 'ok', 'usage': u}))

    def test_origin_comes_from_adapter_not_content(self):
        self.assertIsNone(reported_call_evidence({'origin': 'mock', 'response_id': 'a'}))
        self.assertIsNone(reported_call_evidence({'response_id': 'a'}))
        self.assertIsNone(reported_call_evidence('provider'))
        rows = run_audit(MockAdapter([{"summary": "x", "handoff": None}]))
        self.assertNotIn('reported', rows[-1])

    def test_end_to_end_join_and_reuse(self):
        last = {'origin': 'provider', 'response_id': 'cmpl-1', 'usage': {'prompt_tokens': 4, 'completion_tokens': 2}}
        rows = run_audit(Stub(last))
        rep = join(rows, usage_from_audit(rows))
        self.assertEqual(rep['provider_joined'], 1)
        self.assertEqual(rep['provider_prompt_tokens'], 4)
        rows2 = run_audit(Stub(last))  # same provider id on a different call_id
        rep2 = join(rows + rows2, usage_from_audit(rows + rows2))
        self.assertIsNone(rep2['provider_prompt_tokens'])
        self.assertEqual({r['status'] for r in rep2['rows']}, {'error:response_id_reused'})

    def test_missing_usage_yields_no_record(self):
        rows = run_audit(Stub({'origin': 'provider', 'response_id': 'cmpl-1', 'usage': None}))
        self.assertEqual(usage_from_audit(rows), [])
        self.assertEqual(join(rows, [])['rows'][0]['status'], 'no_usage_record')

if __name__ == '__main__':
    unittest.main()


class NoId(unittest.TestCase):
    def test_absent_provider_id_still_counts_reported_usage(self):
        rows = run_audit(Stub({'origin': 'provider', 'response_id': None, 'usage': {'prompt_tokens': 4, 'completion_tokens': 2}}))
        rep = join(rows, usage_from_audit(rows))
        self.assertEqual(rep['provider_joined'], 1)
        self.assertIsNone(rep['rows'][0]['response_id_sha256'])
        rows2 = run_audit(Stub({'origin': 'provider', 'response_id': None, 'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}))
        rep2 = join(rows + rows2, usage_from_audit(rows + rows2))
        self.assertEqual(rep2['provider_prompt_tokens'], 5)


class Boundary(unittest.TestCase):
    def test_instance_cannot_claim_provider_origin(self):
        class Liar:
            def __init__(self): self.last_call = {'origin': 'provider', 'response_id': 'a', 'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}
            def complete(self, s, p): return {"summary": "x", "handoff": None}
        self.assertNotIn('reported', run_audit(Liar())[-1])
        l = Liar(); l.REPORTS_PROVIDER_USAGE = True  # instance attr is not the class capability
        self.assertNotIn('reported', run_audit(l)[-1])

    def test_non_dict_and_unhashable_rows_do_not_raise(self):
        good = run_audit(Stub({'origin': 'provider', 'response_id': None, 'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}))
        junk = [None, 5, 'x', [], {'call_id': ['u']}, {'call_id': {'a': 1}}, {'event': 'adapter_call_start'}]
        rep = join(good + junk, usage_from_audit(good + junk) + junk)
        self.assertEqual(rep['provider_joined'], 1)
        self.assertEqual(rep['ignored_audit_rows'], 7)
        self.assertEqual(join('nope', None)['total_calls'], 0)

    def test_count_bound_matches_wrapper(self):
        from launcher.usage_join import join as j
        a = [{'event': 'adapter_call_start', 'call_id': 'a', 'audit': {}}, {'event': 'adapter_call_returned', 'call_id': 'a'}]
        for v in (10 ** 9, 10 ** 12):
            r = j(a, [{'call_id': 'a', 'origin': 'provider', 'prompt_tokens': v, 'completion_tokens': 1}])
            self.assertEqual(r['rows'][0]['status'], 'error:bad_usage_counts')

    def test_both_sources_same_call_id_is_duplicate(self):
        rows = run_audit(Stub({'origin': 'provider', 'response_id': None, 'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}))
        cid = rows[0]['call_id']
        extra = [{'call_id': cid, 'origin': 'provider', 'prompt_tokens': 9, 'completion_tokens': 9}]
        rep = join(rows, usage_from_audit(rows) + extra)
        self.assertEqual(rep['rows'][0]['status'], 'error:duplicate_usage')
        self.assertIsNone(rep['provider_prompt_tokens'])


class StaleBeforeRequest(unittest.TestCase):
    def test_missing_key_after_prior_call_carries_no_old_evidence(self):
        os.environ['CK2'] = 'k'
        a = HttpAdapter('http://x.invalid', 'm', 'CK2')
        with mock.patch('urllib.request.urlopen', return_value=Resp(body(id='cmpl-1', usage={'prompt_tokens': 4, 'completion_tokens': 2}))):
            a.complete('s', 'p')
        self.assertIsNotNone(a.last_call)
        del os.environ['CK2']
        with mock.patch('urllib.request.urlopen') as uo:
            with self.assertRaises(Exception):
                a.complete('s', 'p')
            uo.assert_not_called()  # no provider attempt
        self.assertIsNone(a.last_call)
        # through the audit wrapper: the error row has no reported evidence, nothing joins
        d = tempfile.mkdtemp()
        from launcher.prompt_audit import PromptAuditAdapter, render_audited_prompt
        c = ctx(); path = os.path.join(d, 'a.jsonl')
        w = PromptAuditAdapter(a, path, lambda: dict(c))
        sysp, task, _ = render_audited_prompt(**c)
        with self.assertRaises(Exception):
            w.complete(sysp, task)
        rows = [json.loads(l) for l in open(path)]
        shutil.rmtree(d, True)
        self.assertEqual(rows[-1]['event'], 'adapter_call_error')
        self.assertNotIn('reported', rows[-1])
        rep = join(rows, usage_from_audit(rows))
        self.assertIsNone(rep['provider_prompt_tokens'])
