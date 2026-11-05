import json, unittest
from launcher.adapters import AdapterError
from launcher.injected_transport import InjectedTransportAdapter
from launcher.prompt_audit import reported_call_evidence
from launcher.usage_join import join, usage_from_audit
from tests.test_callid_usage import run_audit

OK = '{"summary": "ok", "handoff": null}'


def tr(result):
    calls = []
    def f(s, p):
        calls.append((s, p)); return result
    f.calls = calls
    return f


class T(unittest.TestCase):
    def test_refuses_without_callable(self):
        for bad in (None, 'x', 5):
            with self.assertRaises(AdapterError):
                InjectedTransportAdapter(bad)

    def test_ok_sets_reported_usage_and_no_id(self):
        a = InjectedTransportAdapter(tr({'kind': 'ok', 'content': OK, 'usage': {'prompt_tokens': 3, 'completion_tokens': 2}}))
        self.assertEqual(a.complete('s', 'p')['summary'], 'ok')
        e = reported_call_evidence(a.last_call)
        self.assertEqual(e['reported_usage'], {'prompt_tokens': 3, 'completion_tokens': 2})
        self.assertEqual(e['response_id_status'], 'absent')

    def test_failed_call_clears_stale_evidence(self):
        good = {'kind': 'ok', 'content': OK, 'usage': {'prompt_tokens': 3, 'completion_tokens': 2}}
        seq = [good, {'kind': 'http', 'code': 429}, 'junk', {'kind': 'ok', 'content': 5}, {'kind': 'ok', 'content': 'not json'}]
        it = iter(seq)
        a = InjectedTransportAdapter(lambda s, p: next(it))
        a.complete('s', 'p')
        self.assertIsNotNone(a.last_call)
        for _ in range(4):
            with self.assertRaises(AdapterError):
                a.complete('s', 'p')
            self.assertIsNone(a.last_call)

    def test_missing_or_split_usage_stays_unknown_not_zero(self):
        for usage in (None, {}, {'total_tokens': 9}, {'prompt_tokens': 3}, {'prompt_tokens': 'a', 'completion_tokens': 1}):
            a = InjectedTransportAdapter(tr({'kind': 'ok', 'content': OK, 'usage': usage}))
            a.complete('s', 'p')
            e = reported_call_evidence(a.last_call)
            self.assertNotIn('reported_usage', e)
            self.assertEqual(e['reported_usage_status'], 'absent_or_invalid')

    def test_through_audit_wrapper_to_join(self):
        a = InjectedTransportAdapter(tr({'kind': 'ok', 'content': OK, 'usage': {'prompt_tokens': 3, 'completion_tokens': 2}}))
        rows = run_audit(a)
        rep = join(rows, usage_from_audit(rows))
        self.assertEqual(rep['provider_joined'], 1)
        self.assertEqual(rep['provider_prompt_tokens'], 3)
        self.assertIsNone(rep['rows'][0]['response_id_sha256'])

    def test_unknown_usage_through_wrapper_not_counted(self):
        a = InjectedTransportAdapter(tr({'kind': 'ok', 'content': OK, 'usage': None}))
        rows = run_audit(a)
        rep = join(rows, usage_from_audit(rows))
        self.assertEqual(rep['rows'][0]['status'], 'no_usage_record')
        self.assertIsNone(rep['provider_prompt_tokens'])

    def test_one_transport_call_per_complete(self):
        t = tr({'kind': 'ok', 'content': OK, 'usage': None})
        a = InjectedTransportAdapter(t)
        a.complete('s', 'p'); a.complete('s', 'p')
        self.assertEqual(len(t.calls), 2)  # no hidden retry

if __name__ == '__main__':
    unittest.main()


class RyanShaped(unittest.TestCase):
    OKR = {'kind': 'ok', 'content': OK, 'finish_reason': 'stop', 'usage_flag': None, 'cost_signal': 'zero'}

    def test_exceptions_propagate_unaltered_and_clear_evidence(self):
        class Halt(BaseException):
            pass
        for exc in (Halt('stop'), RuntimeError('boom'), KeyboardInterrupt()):
            def f(s, p, exc=exc): raise exc
            a = InjectedTransportAdapter(f)
            a.last_call = {'stale': 1}
            with self.assertRaises(type(exc)) as cx:
                a.complete('s', 'p')
            self.assertIs(cx.exception, exc)
            self.assertIsNone(a.last_call)

    def test_float_and_partial_usage_unknown_not_zero(self):
        for usage in ({'prompt_tokens': 3.0, 'completion_tokens': 2, 'cost': 0},
                      {'prompt_tokens': 3, 'cost': 0, 'total_tokens': 3},
                      {'total_tokens': 5, 'prompt_tokens_details': {'cached_tokens': 1}}):
            a = InjectedTransportAdapter(tr(dict(self.OKR, usage=usage)))
            a.complete('s', 'p')
            e = reported_call_evidence(a.last_call)
            self.assertNotIn('reported_usage', e)
            rows = run_audit(InjectedTransportAdapter(tr(dict(self.OKR, usage=usage))))
            self.assertIsNone(join(rows, usage_from_audit(rows))['provider_prompt_tokens'])

    def test_full_ryan_ok_usage_counts_only_int_split(self):
        usage = {'prompt_tokens': 7, 'completion_tokens': 4, 'total_tokens': 11, 'cost': 0,
                 'completion_tokens_details': {'reasoning_tokens': 2}}
        rows = run_audit(InjectedTransportAdapter(tr(dict(self.OKR, usage=usage))))
        rep = join(rows, usage_from_audit(rows))
        self.assertEqual((rep['provider_prompt_tokens'], rep['provider_completion_tokens']), (7, 4))

    def test_http_and_unknown_kinds_yield_no_evidence(self):
        for r in ({'kind': 'http', 'code': 402, 'usage': None, 'cost_signal': None},
                  {'kind': 'unknown', 'usage': None, 'content': '', 'cost_signal': 'invalid', 'diag': {}}):
            a = InjectedTransportAdapter(tr(r))
            with self.assertRaises(AdapterError):
                a.complete('s', 'p')
            self.assertIsNone(a.last_call)
