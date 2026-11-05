import json, os, shutil, tempfile, unittest
from launcher import prompts
from launcher.adapters import AdapterError
from launcher.builder_audit import run_builder_call
from launcher.injected_transport import InjectedTransportAdapter as Plain, ProviderInjectedTransportAdapter

OK = '{"summary": "ok", "handoff": null}'
USAGE = {'prompt_tokens': 6, 'completion_tokens': 3}


def ctx():
    return dict(seat='Builder', role=sorted(prompts.ROLES)[0], brief='b', state={'turn_seq': 1, 'status_line': 'x'}, recent_log=[])


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.d, True)
        self.a, self.r = os.path.join(self.d, 'a.jsonl'), os.path.join(self.d, 'r.json')

    def adapter(self, usage=USAGE):
        return ProviderInjectedTransportAdapter(lambda s, p: {'kind': 'ok', 'content': OK, 'usage': usage}, trust_provider_transport=True)

    def test_unknown_provenance_refused_before_call(self):
        called = []
        ad = ProviderInjectedTransportAdapter(lambda s, p: called.append(1) or {'kind': 'ok', 'content': OK}, trust_provider_transport=True)
        for pv in (None, 'live', 'provider', ''):
            with self.assertRaises(ValueError):
                run_builder_call(ctx(), ad, self.a, self.r, pv)
        self.assertEqual(called, [])
        self.assertFalse(os.path.exists(self.r))

    def test_fake_never_claims_provider_totals(self):
        rec = run_builder_call(ctx(), self.adapter(), self.a, self.r, 'fake')
        self.assertEqual(rec['provenance'], 'fake')
        self.assertIsNone(rec['join']['provider_prompt_tokens'])
        self.assertEqual(rec['join']['provider_joined'], 0)
        self.assertEqual(json.load(open(self.r))['provenance'], 'fake')

    def test_unverified_provider_counts_reported_usage(self):
        rec = run_builder_call(ctx(), self.adapter(), self.a, self.r, 'provider_unverified')
        self.assertEqual(rec['join']['provider_prompt_tokens'], 6)
        self.assertIn('not verified', rec['note'])

    def test_unknown_usage_not_counted(self):
        rec = run_builder_call(ctx(), self.adapter(usage=None), self.a, self.r, 'provider_unverified')
        self.assertIsNone(rec['join']['provider_prompt_tokens'])

    def test_rerun_refused_and_no_second_call(self):
        n = []
        ad = ProviderInjectedTransportAdapter(lambda s, p: n.append(1) or {'kind': 'ok', 'content': OK, 'usage': USAGE}, trust_provider_transport=True)
        run_builder_call(ctx(), ad, self.a, self.r, 'fake')
        with self.assertRaises(FileExistsError):
            run_builder_call(ctx(), ad, self.a, self.r, 'fake')
        self.assertEqual(len(n), 1)

    def test_failure_recorded_by_type_and_reraised(self):
        ad = ProviderInjectedTransportAdapter(lambda s, p: {'kind': 'http', 'code': 402}, trust_provider_transport=True)
        with self.assertRaises(AdapterError):
            run_builder_call(ctx(), ad, self.a, self.r, 'provider_unverified')
        rec = json.load(open(self.r))
        self.assertEqual((rec['status'], rec['error_type']), ('error', 'AdapterError'))
        self.assertIsNone(rec['join']['provider_prompt_tokens'])

    def test_no_prompt_or_text_or_ids_in_files(self):
        run_builder_call(ctx(), self.adapter(), self.a, self.r, 'provider_unverified')
        blob = open(self.a).read() + open(self.r).read()
        for needle in ('"b"', 'Builder', OK, 'summary'):
            self.assertNotIn(needle, blob)

    def test_only_this_calls_audit_rows_joined(self):
        run_builder_call(ctx(), self.adapter(), self.a, self.r, 'fake')
        r2 = os.path.join(self.d, 'r2.json')
        rec = run_builder_call(ctx(), self.adapter(), self.a, r2, 'provider_unverified')
        self.assertEqual(rec['join']['total_calls'], 1)

if __name__ == '__main__':
    unittest.main()


class Binding(unittest.TestCase):
    def test_provider_unverified_requires_provider_class(self):
        d = tempfile.mkdtemp(); 
        plain = Plain(lambda s, p: {'kind': 'ok', 'content': OK, 'usage': USAGE})
        with self.assertRaises(ValueError):
            run_builder_call(ctx(), plain, os.path.join(d, 'a'), os.path.join(d, 'r'), 'provider_unverified')
        shutil.rmtree(d, True)
