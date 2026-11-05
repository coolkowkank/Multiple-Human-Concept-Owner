import copy
import functools
import unittest
from launcher.quality_gate import (generate_mutants, harvest_expected_constants, run_gate,
                                    evaluate_done, artifact_sha256, sign, verify, checker_id)

KEY = b'k' * 32
SRC = 'def add(a, b):\n    """Add."""\n    return a + b\n'
CK = 'def check(c):\n    if not c:\n        raise AssertionError\n'
WEAK = 'from src.app import add\n' + CK + 'check(add(2, 3) == 5)\n'
STRONG = ('from src.app import add\n' + CK + 'check(add(2, 3) == 5)\ncheck(add(0, 0) == 0)\n'
          'check(add(-4, 9) == 5 + 0)\ncheck(add(10, 7) == 17)\ncheck(add(1, 1) == 2)\n')
OPCK = 'c' * 64


def fake_runner(files, optimize=-1):
    """Test double, in-process: stands in for the sandboxed runner (never use on model code)."""
    import sys, types
    mod = types.ModuleType('src.app')
    try:
        exec(compile(files['src/app.py'], 'app', 'exec'), mod.__dict__)
        sys.modules['src.app'] = mod; sys.modules.setdefault('src', types.ModuleType('src'))
        exec(compile(files['tests/t.py'], 't', 'exec', optimize=optimize), {})
        return 'pass'
    except AssertionError:
        return 'fail'
    except Exception:
        return 'error'


fake_runner_O = functools.partial(fake_runner, optimize=2)


def gate(test=STRONG, src=SRC, o=True, **kw):
    return run_gate({'src/app.py': src}, {'tests/t.py': test}, fake_runner, 'src/app.py',
                    run_tests_optimized=fake_runner_O if o else None, runner_id='bwrap-shim-v1', **kw)


def done(g, cur=None, *, cycle=True, qc=None, op=None, key=KEY, **kw):
    kw.setdefault('expected_target', 'src/app.py')
    kw.setdefault('expected_operator_checker_id', OPCK)
    return evaluate_done(cycle, sign(KEY, g) if g is not None else None, qc,
                         cur or (g or {}).get('artifact_sha256'), op, operator_key=key, **kw)


def op(cur, accepted=True, state=None, checker=OPCK):
    return sign(KEY, {'artifact_sha256': cur, 'accepted': accepted, 'checker_id': checker,
                      'state': state or ('accepted' if accepted else 'rejected')})


class Mut(unittest.TestCase):
    def test_harvest_floats_and_truncation(self):
        v, t = harvest_expected_constants([WEAK])
        self.assertEqual((set(v), t), ({2, 3, 5}, False))
        v, t = harvest_expected_constants(['x = 0.5 + 1.5\ny = True\n'])
        self.assertEqual((set(v), t), ({0.5, 1.5}, False))  # bool excluded
        big = '\n'.join('check(f(%d) == %d)' % (i, i + 100) for i in range(40))
        v, t = harvest_expected_constants([big])
        self.assertTrue(t)
        self.assertEqual(len(v), 12)

    def test_truncated_harvest_is_insufficient_evidence(self):
        big = 'from src.app import add\n' + CK + '\n'.join('check(add(%d, 0) == %d)' % (i, i) for i in range(40))
        self.assertEqual(gate(big)['verdict'], 'insufficient_evidence')

    def test_float_hardcode_veto(self):
        src = 'def half(x):\n    return x / 2\n'
        t = 'from src.app import half\n' + CK + 'check(half(3.0) == 1.5)\n'
        g = run_gate({'src/app.py': src}, {'tests/t.py': t}, fake_runner, 'src/app.py', fake_runner_O)
        self.assertEqual(g['verdict'], 'failed')
        self.assertTrue(any('hardcoded 1.5' in s['desc'] for s in g['survivors']))

    def test_weak_fails_strong_passes(self):
        self.assertEqual(gate(WEAK)['verdict'], 'failed')
        self.assertGreaterEqual(gate(WEAK)['score'], 0.8)  # veto, not score, fails it
        g = gate()
        self.assertEqual((g['survivors'], g['verdict']), ([], 'passed'))

    def test_legit_literal_return_not_a_false_fail(self):
        src = 'def answer():\n    return 42\n'
        t = ('from src.app import answer\n' + CK + 'check(answer() == 42)\ncheck(answer() + 1 == 43)\n'
             'check(type(answer()) is int)\ncheck(answer() > 41)\ncheck(answer() < 43)\n')
        g = run_gate({'src/app.py': src}, {'tests/t.py': t}, fake_runner, 'src/app.py', fake_runner_O)
        self.assertEqual(g['survivors'], [])  # mutant identical to original is skipped, not a survivor

    def test_bare_assert_tests_fail_the_O_policy(self):
        bare = 'from src.app import add\nassert add(2, 3) == 5\nassert add(0, 0) == 0\nassert add(10, 7) == 17\nassert add(1, 1) == 2\nassert add(-4, 9) == 5\n'
        g = gate(bare)
        self.assertEqual(g['verdict'], 'failed')
        self.assertTrue(all('-O' in s['desc'] for s in g['survivors']))
        self.assertEqual(gate(bare, o=False)['verdict'], 'passed')  # why the policy exists

    def test_assert_only_tests_do_not_survive_under_O(self):
        # killed by plain run but pass under -O would be a survivor; bare-assert tests pass baseline under -O too,
        # so every mutant they kill normally "survives under -O": the gate fails them.
        g = gate()
        t = STRONG
        # simulate a runner whose -O run cannot fail: all kills become O-survivors
        g2 = run_gate({'src/app.py': SRC}, {'tests/t.py': t}, fake_runner, 'src/app.py',
                      run_tests_optimized=lambda f: 'pass')
        self.assertEqual(g2['verdict'], 'failed')
        self.assertTrue(all('-O' in s['desc'] for s in g2['survivors']))

    def test_baseline_failing_and_O_failing(self):
        g = gate('from src.app import add\n' + CK + 'check(add(1,1) == 3)\n')
        self.assertEqual((g['verdict'], g['mutants']), ('baseline_not_passing', 0))
        g = run_gate({'src/app.py': SRC}, {'tests/t.py': STRONG}, fake_runner, 'src/app.py', lambda f: 'fail')
        self.assertEqual(g['baseline'], 'fail_under_O')

    def test_unknown_and_malformed_target(self):
        with self.assertRaises(ValueError):
            run_gate({'src/app.py': SRC}, {'tests/t.py': STRONG}, fake_runner, 'src/other.py')
        g = run_gate({'src/app.py': 'def (:'}, {'tests/t.py': 'pass\n'}, lambda f: 'pass', 'src/app.py')
        self.assertEqual(g['verdict'], 'malformed_target')

    def test_inconclusive_not_killed(self):
        calls = []
        def r(files):
            calls.append(1); return 'pass' if len(calls) == 1 else 'error'
        g = run_gate({'src/app.py': SRC}, {'tests/t.py': WEAK}, r, 'src/app.py')
        self.assertEqual((g['killed'], g['verdict']), (0, 'insufficient_evidence'))

    def test_mutants_bounded_deterministic(self):
        big = '\n'.join('def f%d(a):\n    return a + %d\n' % (i, i + 1) for i in range(80))
        a = generate_mutants(big)
        self.assertEqual(a, generate_mutants(big))
        self.assertLessEqual(len(a), 60)


class Policy(unittest.TestCase):
    def test_labels_and_terminal(self):
        g = gate(); d = done(g)
        self.assertEqual((d['quality'], d['terminal_done']), ('gate_passed', True))
        self.assertIn('not proof', d['note'])
        d = done(gate(WEAK))
        self.assertEqual((d['quality'], d['terminal_done'], d['cycle_complete']), ('failed', False, True))
        self.assertFalse(done(g, cycle=False)['terminal_done'])

    def test_unsigned_or_wrong_key_dict_cannot_pass(self):
        g = gate()
        for signed in (g, {'payload': g, 'sig': 'x'}, sign(b'z' * 32, g), {'payload': g}, None, 5):
            d = evaluate_done(True, signed, None, g['artifact_sha256'], None, operator_key=KEY,
                              expected_target='src/app.py')
            self.assertFalse(d['terminal_done'], signed)
        for key in (None, b'short', 'str'):
            self.assertFalse(evaluate_done(True, sign(KEY, g), None, g['artifact_sha256'], None, operator_key=key,
                                           expected_target='src/app.py')['terminal_done'])
        self.assertIsNone(verify(KEY, 'junk'))

    def test_tampered_after_signing_detected(self):
        g = gate(WEAK)
        s = sign(KEY, g); s['payload']['verdict'] = 'passed'
        self.assertFalse(evaluate_done(True, s, None, g['artifact_sha256'], None, operator_key=KEY,
                                       expected_target='src/app.py')['terminal_done'])

    def test_signed_but_inconsistent_report_rejected(self):
        g = gate(WEAK); g['verdict'] = 'passed'  # operator-signed lie: counts disagree
        self.assertFalse(done(g)['terminal_done'])
        g = gate(); g['killed'] += 2
        self.assertFalse(done(g)['terminal_done'])

    def test_stale_revision_and_missing_current(self):
        g = gate()
        other = artifact_sha256({'src/app.py': 'def add(a, b):\n    return 5\n', 'tests/t.py': STRONG})
        self.assertFalse(done(g, other)['terminal_done'])
        for cur in (None, '', 'short', 5):
            d = evaluate_done(True, sign(KEY, g), None, cur, None, operator_key=KEY, expected_target='src/app.py')
            self.assertFalse(d['terminal_done'])

    def test_target_checker_runner_and_O_binding(self):
        g = gate()
        self.assertFalse(done(g, expected_target='src/other.py')['terminal_done'])
        self.assertFalse(done(g, expected_target=None)['terminal_done'])
        self.assertFalse(done(g, expected_runner_id='other-runner')['terminal_done'])
        self.assertTrue(done(g, expected_runner_id='bwrap-shim-v1')['terminal_done'])
        g2 = copy.deepcopy(g); g2['checker_id'] = 'f' * 64
        self.assertFalse(done(g2)['terminal_done'])
        noo = gate(o=False)
        self.assertFalse(done(noo)['terminal_done'])
        self.assertTrue(done(noo, require_o_policy=False)['terminal_done'])

    def test_fake_qc_never_counts(self):
        qc = {'verdict': 'PASS', 'model': 'x', 'builder_model': 'x', 'counts_toward_quality': True}
        d = evaluate_done(True, None, qc, 'b' * 64, None, operator_key=KEY)
        self.assertFalse(d['terminal_done'])
        self.assertFalse(d['qc']['counts_toward_quality'])
        self.assertTrue(d['qc']['same_model_as_builder'])

    def test_operator_result_rules(self):
        cur = gate()['artifact_sha256']
        def ev(o, g=None, **kw):
            return evaluate_done(True, sign(KEY, g) if g else None, None, cur, o, operator_key=KEY,
                                 expected_target='src/app.py', expected_operator_checker_id=OPCK, **kw)
        self.assertEqual(ev(op(cur))['quality'], 'operator_check_passed')
        self.assertTrue(ev(op(cur))['terminal_done'])
        for bad in (op('d' * 64), op(cur, checker='e' * 64), op(cur, accepted='yes'),
                    op(cur, accepted=True, state='error'), {'payload': {'accepted': True}, 'sig': 'x'},
                    {'artifact_sha256': cur, 'accepted': True}):
            self.assertFalse(ev(bad)['terminal_done'], bad)
        d = ev(op(cur, accepted=False), gate())
        self.assertEqual((d['quality'], d['terminal_done']), ('failed', False))
        g = gate(WEAK)
        d = evaluate_done(True, sign(KEY, g), None, g['artifact_sha256'], op('d' * 64), operator_key=KEY,
                          expected_target='src/app.py', expected_operator_checker_id=OPCK)
        self.assertFalse(d['terminal_done'])

    def test_operator_checker_unspecified_not_trusted(self):
        cur = 'a' * 64
        d = evaluate_done(True, None, None, cur, op(cur), operator_key=KEY)
        self.assertFalse(d['terminal_done'])


if __name__ == '__main__':
    unittest.main()
