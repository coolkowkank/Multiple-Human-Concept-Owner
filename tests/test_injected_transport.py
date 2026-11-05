import json, unittest
from launcher.adapters import AdapterError
from launcher.injected_transport import InjectedTransportAdapter as Plain, ProviderInjectedTransportAdapter
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
                ProviderInjectedTransportAdapter(bad, trust_provider_transport=True)

    def test_ok_sets_reported_usage_and_no_id(self):
        a = ProviderInjectedTransportAdapter(tr({'kind': 'ok', 'content': OK, 'usage': {'prompt_tokens': 3, 'completion_tokens': 2}}), trust_provider_transport=True)
        self.assertEqual(a.complete('s', 'p')['summary'], 'ok')
        e = reported_call_evidence(a.last_call)
        self.assertEqual(e['reported_usage'], {'prompt_tokens': 3, 'completion_tokens': 2})
        self.assertEqual(e['response_id_status'], 'absent')

    def test_failed_call_clears_stale_evidence(self):
        good = {'kind': 'ok', 'content': OK, 'usage': {'prompt_tokens': 3, 'completion_tokens': 2}}
        seq = [good, {'kind': 'http', 'code': 429}, 'junk', {'kind': 'ok', 'content': 5}]
        it = iter(seq)
        a = ProviderInjectedTransportAdapter(lambda s, p: next(it), trust_provider_transport=True)
        a.complete('s', 'p')
        self.assertIsNotNone(a.last_call)
        for _ in range(3):
            with self.assertRaises(AdapterError):
                a.complete('s', 'p')
            self.assertIsNone(a.last_call)

    def test_missing_or_split_usage_stays_unknown_not_zero(self):
        for usage in (None, {}, {'total_tokens': 9}, {'prompt_tokens': 3}, {'prompt_tokens': 'a', 'completion_tokens': 1}):
            a = ProviderInjectedTransportAdapter(tr({'kind': 'ok', 'content': OK, 'usage': usage}), trust_provider_transport=True)
            a.complete('s', 'p')
            e = reported_call_evidence(a.last_call)
            self.assertNotIn('reported_usage', e)
            self.assertEqual(e['reported_usage_status'], 'absent_or_invalid')

    def test_through_audit_wrapper_to_join(self):
        a = ProviderInjectedTransportAdapter(tr({'kind': 'ok', 'content': OK, 'usage': {'prompt_tokens': 3, 'completion_tokens': 2}}), trust_provider_transport=True)
        rows = run_audit(a)
        rep = join(rows, usage_from_audit(rows))
        self.assertEqual(rep['provider_joined'], 1)
        self.assertEqual(rep['provider_prompt_tokens'], 3)
        self.assertIsNone(rep['rows'][0]['response_id_sha256'])

    def test_unknown_usage_through_wrapper_not_counted(self):
        a = ProviderInjectedTransportAdapter(tr({'kind': 'ok', 'content': OK, 'usage': None}), trust_provider_transport=True)
        rows = run_audit(a)
        rep = join(rows, usage_from_audit(rows))
        self.assertEqual(rep['rows'][0]['status'], 'no_usage_record')
        self.assertIsNone(rep['provider_prompt_tokens'])

    def test_one_transport_call_per_complete(self):
        t = tr({'kind': 'ok', 'content': OK, 'usage': None})
        a = ProviderInjectedTransportAdapter(t, trust_provider_transport=True)
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
            a = ProviderInjectedTransportAdapter(f, trust_provider_transport=True)
            a.last_call = {'stale': 1}
            with self.assertRaises(type(exc)) as cx:
                a.complete('s', 'p')
            self.assertIs(cx.exception, exc)
            self.assertIsNone(a.last_call)

    def test_float_and_partial_usage_unknown_not_zero(self):
        for usage in ({'prompt_tokens': 3.0, 'completion_tokens': 2, 'cost': 0},
                      {'prompt_tokens': 3, 'cost': 0, 'total_tokens': 3},
                      {'total_tokens': 5, 'prompt_tokens_details': {'cached_tokens': 1}}):
            a = ProviderInjectedTransportAdapter(tr(dict(self.OKR, usage=usage)), trust_provider_transport=True)
            a.complete('s', 'p')
            e = reported_call_evidence(a.last_call)
            self.assertNotIn('reported_usage', e)
            rows = run_audit(ProviderInjectedTransportAdapter(tr(dict(self.OKR, usage=usage)), trust_provider_transport=True))
            self.assertIsNone(join(rows, usage_from_audit(rows))['provider_prompt_tokens'])

    def test_full_ryan_ok_usage_counts_only_int_split(self):
        usage = {'prompt_tokens': 7, 'completion_tokens': 4, 'total_tokens': 11, 'cost': 0,
                 'completion_tokens_details': {'reasoning_tokens': 2}}
        rows = run_audit(ProviderInjectedTransportAdapter(tr(dict(self.OKR, usage=usage)), trust_provider_transport=True))
        rep = join(rows, usage_from_audit(rows))
        self.assertEqual((rep['provider_prompt_tokens'], rep['provider_completion_tokens']), (7, 4))

    def test_http_and_unknown_kinds_yield_no_evidence(self):
        for r in ({'kind': 'http', 'code': 402, 'usage': None, 'cost_signal': None},
                  {'kind': 'unknown', 'usage': None, 'content': '', 'cost_signal': 'invalid', 'diag': {}}):
            a = ProviderInjectedTransportAdapter(tr(r), trust_provider_transport=True)
            with self.assertRaises(AdapterError):
                a.complete('s', 'p')
            self.assertIsNone(a.last_call)


class ParseFailureAndTrust(unittest.TestCase):
    def test_parse_failure_keeps_reported_usage_in_error_row(self):
        usage = {'prompt_tokens': 5, 'completion_tokens': 2}
        a = ProviderInjectedTransportAdapter(tr({'kind': 'ok', 'content': 'not json', 'usage': usage}), trust_provider_transport=True)
        rows = run_audit_err(a)
        self.assertEqual(rows[-1]['event'], 'adapter_call_error')
        self.assertEqual(rows[-1]['reported']['reported_usage'], usage)
        rep = join(rows, usage_from_audit(rows))
        self.assertEqual(rep['provider_prompt_tokens'], 5)  # the call happened; not "no call"
        self.assertEqual(rep['rows'][0]['status'], 'joined_provider')

    def test_transport_failure_has_no_reported_evidence(self):
        a = ProviderInjectedTransportAdapter(tr({'kind': 'http', 'code': 500}), trust_provider_transport=True)
        rows = run_audit_err(a)
        self.assertNotIn('reported', rows[-1])

    def test_plain_injected_adapter_never_provider_origin(self):
        a = Plain(tr({'kind': 'ok', 'content': OK, 'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}))
        rows = run_audit(a)
        self.assertNotIn('reported', rows[-1])
        self.assertEqual(join(rows, usage_from_audit(rows))['rows'][0]['status'], 'no_usage_record')

    def test_provider_class_requires_explicit_trust(self):
        for kw in ({}, {'trust_provider_transport': False}, {'trust_provider_transport': 1}):
            with self.assertRaises(AdapterError):
                ProviderInjectedTransportAdapter(tr({'kind': 'ok'}), **kw)


def run_audit_err(adapter):
    import os, shutil, tempfile
    from launcher.prompt_audit import PromptAuditAdapter, render_audited_prompt
    from tests.test_callid_usage import ctx
    d = tempfile.mkdtemp(); path = os.path.join(d, 'a.jsonl'); c = ctx()
    w = PromptAuditAdapter(adapter, path, lambda: dict(c))
    sysp, task, _ = render_audited_prompt(**c)
    try:
        w.complete(sysp, task)
    except Exception:
        pass
    rows = [json.loads(l) for l in open(path)]
    shutil.rmtree(d, True)
    return rows
