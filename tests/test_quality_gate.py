import unittest
import copy
from launcher.quality_gate import (generate_mutants, harvest_expected_constants, run_gate,
                                    evaluate_done, artifact_sha256)

SRC = 'def add(a, b):\n    """Add."""\n    return a + b\n'
WEAK = 'from src.app import add\nassert add(2, 3) == 5\n'
STRONG = ('from src.app import add\nassert add(2, 3) == 5\nassert add(0, 0) == 0\n'
          'assert add(-4, 9) == 5 + 0\nassert add(10, 7) == 17\nassert add(1, 1) == 2\n')


def fake_runner(files):
    """Test double: executes in-process via exec, standing in for the sandbox runner."""
    import types
    mod = types.ModuleType('src.app')
    try:
        exec(compile(files['src/app.py'], 'app', 'exec'), mod.__dict__)
        import sys
        sys.modules['src.app'] = mod; sys.modules.setdefault('src', types.ModuleType('src'))
        exec(compile(files['tests/t.py'], 't', 'exec'), {})
        return 'pass'
    except AssertionError:
        return 'fail'
    except Exception:
        return 'error'


class T(unittest.TestCase):
    def test_harvest_and_hardcode_mutant(self):
        self.assertEqual(set(harvest_expected_constants([WEAK])), {2, 3, 5})
        ms = generate_mutants(SRC, [5])
        self.assertTrue(any('hardcoded 5' in d for _, d, _ in ms))
        self.assertTrue(all('"""' not in t or True for _, _, t in ms))

    def test_weak_test_survives_constant_five(self):
        rep = run_gate({'src/app.py': SRC}, {'tests/t.py': WEAK}, fake_runner, 'src/app.py')
        self.assertEqual(rep['baseline'], 'pass')
        self.assertTrue(any('hardcoded 5' in s['desc'] for s in rep['survivors']))
        self.assertNotEqual(rep['verdict'], 'passed')

    def test_stronger_test_passes(self):
        rep = run_gate({'src/app.py': SRC}, {'tests/t.py': STRONG}, fake_runner, 'src/app.py')
        self.assertEqual(rep['survivors'], [], rep)
        self.assertEqual(rep['verdict'], 'passed')

    def test_baseline_failing_mutates_nothing(self):
        rep = run_gate({'src/app.py': SRC}, {'tests/t.py': 'from src.app import add\nassert add(1,1) == 3\n'}, fake_runner, 'src/app.py')
        self.assertEqual(rep['verdict'], 'baseline_not_passing')
        self.assertEqual(rep['mutants'], 0)

    def test_inconclusive_not_counted_as_killed(self):
        calls = []
        def r(files):
            calls.append(1)
            return 'pass' if len(calls) == 1 else 'error'
        rep = run_gate({'src/app.py': SRC}, {'tests/t.py': WEAK}, r, 'src/app.py')
        self.assertEqual(rep['killed'], 0)
        self.assertEqual(rep['verdict'], 'insufficient_evidence')

    def test_done_requires_gate_qc_never_sufficient(self):
        qc = {'verdict': 'pass', 'model': 'm', 'builder_model': 'm'}
        d = evaluate_done(True, None, qc, 'a' * 64)
        self.assertEqual((d['quality'], d['terminal_done']), ('unproven', False))
        self.assertFalse(d['qc']['counts_toward_quality'])
        self.assertTrue(d['qc']['same_model_as_builder'])
        weak = run_gate({'src/app.py': SRC}, {'tests/t.py': WEAK}, fake_runner, 'src/app.py')
        d = evaluate_done(True, weak, qc, weak['artifact_sha256'])
        self.assertFalse(d['terminal_done'])
        strong = run_gate({'src/app.py': SRC}, {'tests/t.py': STRONG}, fake_runner, 'src/app.py')
        d = evaluate_done(True, strong, qc, strong['artifact_sha256'])
        self.assertTrue(d['terminal_done'])
        self.assertTrue(d['cycle_complete'])
        self.assertIn('same model', ' '.join(d['reasons']))

    def test_cycle_incomplete_blocks_even_with_passed_gate(self):
        strong = run_gate({'src/app.py': SRC}, {'tests/t.py': STRONG}, fake_runner, 'src/app.py')
        d = evaluate_done(False, strong, None, strong['artifact_sha256'])
        self.assertFalse(d['terminal_done'])
        self.assertEqual(d['quality'], 'proven_by_mutation_gate')

    def test_mutants_bounded_deterministic_and_valid(self):
        big = '\n'.join('def f%d(a):\n    return a + %d\n' % (i, i + 1) for i in range(80))
        a, b = generate_mutants(big), generate_mutants(big)
        self.assertEqual(a, b)
        self.assertLessEqual(len(a), 60)


def gate(test=STRONG, src=SRC):
    return run_gate({'src/app.py': src}, {'tests/t.py': test}, fake_runner, 'src/app.py')


class Bypass(unittest.TestCase):
    def test_surviving_hardcode_fails_even_with_high_score(self):
        g = gate(WEAK)
        self.assertEqual(g['verdict'], 'failed')
        self.assertGreaterEqual(g['score'], 0.8)  # score alone would have passed it

    def test_stale_pass_after_revision_change(self):
        g = gate()
        changed = artifact_sha256({'src/app.py': 'def add(a, b):\n    return 5\n', 'tests/t.py': STRONG})
        d = evaluate_done(True, g, None, changed)
        self.assertFalse(d['terminal_done'])
        self.assertEqual(d['quality'], 'unproven')
        self.assertIn('stale', ' '.join(d['reasons']))
        self.assertTrue(evaluate_done(True, g, None, g['artifact_sha256'])['terminal_done'])

    def test_no_current_revision_cannot_prove(self):
        for cur in (None, '', 'short', 5):
            self.assertFalse(evaluate_done(True, gate(), None, cur)['terminal_done'])

    def test_tampered_report_detected(self):
        g = gate(WEAK)
        for mut in (lambda r: r.update(verdict='passed'),
                    lambda r: r.update(survivors=[]),
                    lambda r: r.update(killed=r['killed'] + 3),
                    lambda r: r.update(mutants=True)):
            t = copy.deepcopy(g); mut(t)
            d = evaluate_done(True, t, None, g['artifact_sha256'])
            self.assertFalse(d['terminal_done'], t)

    def test_fake_qc_pass_never_counts(self):
        qc = {'verdict': 'PASS', 'model': 'x', 'builder_model': 'y', 'counts_toward_quality': True}
        d = evaluate_done(True, None, qc, 'b' * 64)
        self.assertFalse(d['terminal_done'])
        self.assertFalse(d['qc']['counts_toward_quality'])

    def test_operator_result_bound_and_rejection_overrides_gate(self):
        g = gate(); cur = g['artifact_sha256']
        self.assertTrue(evaluate_done(True, None, None, cur, {'artifact_sha256': cur, 'accepted': True})['terminal_done'])
        self.assertFalse(evaluate_done(True, None, None, cur, {'artifact_sha256': 'c' * 64, 'accepted': True})['terminal_done'])
        self.assertFalse(evaluate_done(True, None, None, cur, {'artifact_sha256': cur, 'accepted': 'yes'})['terminal_done'])
        d = evaluate_done(True, g, None, cur, {'artifact_sha256': cur, 'accepted': False})
        self.assertEqual((d['quality'], d['terminal_done']), ('failed', False))

    def test_failed_gate_not_rescued_by_unbound_operator_accept(self):
        g = gate(WEAK); cur = g['artifact_sha256']
        d = evaluate_done(True, g, None, cur, {'artifact_sha256': 'd' * 64, 'accepted': True})
        self.assertFalse(d['terminal_done'])

    def test_cycle_complete_and_quality_reported_separately(self):
        d = evaluate_done(True, gate(WEAK), None, gate(WEAK)['artifact_sha256'])
        self.assertTrue(d['cycle_complete'])
        self.assertEqual(d['quality'], 'failed')


if __name__ == '__main__':
    unittest.main()
