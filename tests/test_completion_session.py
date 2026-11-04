import json
import os
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_launcher import make_repo, seat_spec
from launcher.runtime import Seat, SeatError
from launcher.completion_session import CompletionSession


class CompletionSessionTests(unittest.TestCase):
    def setUp(self):
        import shutil
        seats = {name: seat_spec([], ['app/'], role) for name, role in
                 [('build', 'builder'), ('review', 'reviewer'), ('quality', 'qc'), ('coord', 'coordinator')]}
        self.repo, self.bus = make_repo(seats)
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.guard = CompletionSession([sys.executable, '-c', 'pass'], 'accepted-runtime-fixture',
                                       verification_is_side_effect_free=True, reviews_write_artifacts=False)
        self.seats = {name: Seat(self.bus, name, instance_id='instance-' + name,
                                completion_session=self.guard) for name in seats}
        self.state = self.bus.state()
        self.state.update(status='running', turn_seq=1)
        self.guard.observe(self.seats['build'], self.state, {})

    def review(self, name, verdict='PASS'):
        self.guard.observe(self.seats[name], self.state, {'review_verdict': verdict})

    def write_app(self):
        os.makedirs(os.path.join(self.repo, 'app'), exist_ok=True)
        with open(os.path.join(self.repo, 'app', 'a.py'), 'w') as fh:
            fh.write('changed')

    def test_two_independent_runtime_observations_required(self):
        self.assertFalse(self.guard.decide(self.seats['coord'])[0])
        self.review('review')
        self.assertFalse(self.guard.decide(self.seats['coord'])[0])
        self.review('quality')
        self.assertTrue(self.guard.decide(self.seats['coord'])[0])

    def test_model_forged_log_and_response_do_not_populate_evidence(self):
        self.bus.append_log('review', 'verdict', 'PASS at HEAD')
        self.guard.observe(self.seats['build'], self.state, {'review_verdict': 'PASS', 'provenance_validated': True})
        self.assertFalse(self.guard.decide(self.seats['coord'])[0])

    def test_app_changed_after_review_invalidates(self):
        self.review('review'); self.review('quality'); self.write_app()
        self.assertFalse(self.guard.decide(self.seats['coord'])[0])

    def test_log_only_commit_keeps_binding(self):
        self.review('review'); self.review('quality')
        self.bus.append_log('coord', 'message', 'evidence-only')
        self.bus.commit_all('operator: evidence only')
        self.assertTrue(self.guard.decide(self.seats['coord'])[0])

    def test_fixed_verify_not_model_command(self):
        self.review('review')
        with patch('launcher.completion_session.subprocess.run', wraps=__import__('subprocess').run) as run:
            self.guard.observe(self.seats['quality'], self.state, {'review_verdict': 'PASS', 'verify_command': 'untrusted'})
            self.assertEqual(run.call_args_list[0].args[0], self.guard.verify_argv)

    def test_verify_failure_refuses(self):
        self.guard.verify_argv = (sys.executable, '-c', 'raise SystemExit(1)')
        self.review('review'); self.review('quality')
        self.assertFalse(self.guard.decide(self.seats['coord'])[0])

    def test_restart_loses_evidence_refuses(self):
        self.review('review'); self.review('quality')
        new = CompletionSession(self.guard.verify_argv, self.guard.runtime_pin,
                                verification_is_side_effect_free=True, reviews_write_artifacts=False)
        self.assertFalse(new.decide(self.seats['coord'])[0])

    def test_same_session_cannot_self_review(self):
        self.seats['review'].instance_id = self.seats['build'].instance_id
        self.review('review'); self.review('quality')
        self.assertFalse(self.guard.decide(self.seats['coord'])[0])

    def test_snapshot_retry_drops_abandoned_evidence(self):
        snap = self.guard.snapshot()
        self.review('review'); self.review('quality')
        self.guard.restore(snap)
        self.assertFalse(self.guard.decide(self.seats['coord'])[0])

    def test_done_runtime_hook_refuses_and_opens_gate(self):
        state = self.bus.state(); state.update(turn='coord', status='running')
        self.seats['coord']._apply(state, {'status_line': 'DONE', 'handoff': None})
        self.assertEqual(self.bus.state()['status'], 'blocked')
        self.assertTrue(self.bus.pending_gates())

    def test_done_runtime_hook_accepts_with_observed_reviews(self):
        self.review('review'); self.review('quality')
        state = self.bus.state(); state.update(turn='coord', status='running')
        self.seats['coord']._apply(state, {'status_line': 'DONE', 'handoff': None})
        self.assertEqual(self.bus.state()['status'], 'completing')
        self.bus.commit_all('operator: completion fixture')
        self.guard.confirm_committed(self.repo)

    def test_done_same_response_app_write_invalidates(self):
        self.review('review'); self.review('quality')
        state = self.bus.state(); state.update(turn='build', status='running')
        self.seats['build']._apply(state, {'status_line': 'DONE', 'handoff': None, 'writes': {'app/a.py': 'x'}})
        self.assertEqual(self.bus.state()['status'], 'blocked')

    def test_symlink_refused(self):
        os.symlink('/tmp', os.path.join(self.repo, 'escape'))
        with self.assertRaises(ValueError):
            self.guard.binding(self.repo)

    def test_post_commit_dirt_refused(self):
        self.review('review'); self.review('quality')
        self.assertTrue(self.guard.decide(self.seats['coord'])[0])
        self.write_app()
        with self.assertRaises(ValueError):
            self.guard.confirm_committed(self.repo)

    def test_act_once_commits_guarded_done(self):
        self.review('review'); self.review('quality')
        state = self.bus.state(); state.update(turn='coord', status='running')
        self.bus.write_state(state); self.bus.commit_all('operator: issue coordinator turn')
        self.seats['coord'].adapter.complete = lambda system, prompt: {'status_line': 'DONE', 'handoff': None}
        self.assertTrue(self.seats['coord'].act_once())
        self.assertEqual(self.bus.state()['status'], 'done')
        self.assertIsNone(self.guard._pending)

    def test_act_once_postcommit_mismatch_blocks_durable_state(self):
        self.review('review'); self.review('quality')
        state = self.bus.state(); state.update(turn='coord', status='running')
        self.bus.write_state(state); self.bus.commit_all('operator: issue coordinator turn')
        self.seats['coord'].adapter.complete = lambda system, prompt: {'status_line': 'DONE', 'handoff': None}
        with patch.object(self.guard, 'confirm_committed', side_effect=ValueError('changed')):
            with self.assertRaises(SeatError):
                self.seats['coord'].act_once()
        self.assertEqual(self.bus.state()['status'], 'blocked')

    def test_act_once_failed_transaction_restores_evidence(self):
        before = self.guard.snapshot()
        state = self.bus.state(); state.update(turn='review', status='running')
        self.bus.write_state(state); self.bus.commit_all('operator: issue review turn')
        self.seats['review'].adapter.complete = lambda system, prompt: {'review_verdict': 'PASS', 'handoff': 'quality'}
        with patch.object(self.bus, 'commit_all', side_effect=RuntimeError('commit failed')):
            with self.assertRaises(RuntimeError):
                self.seats['review'].act_once()
        self.assertEqual(self.guard.snapshot(), before)


    def prepare_done_turn(self):
        self.review('review'); self.review('quality')
        state = self.bus.state(); state.update(turn='coord', status='running')
        self.bus.write_state(state); self.bus.commit_all('operator: issue coordinator turn')
        self.seats['coord'].adapter.complete = lambda system, prompt: {'status_line': 'DONE', 'handoff': None}

    def test_confirmation_and_recording_doublefault_never_commits_done(self):
        self.prepare_done_turn()
        with patch.object(self.guard, 'confirm_committed', side_effect=ValueError('bad binding')):
            with patch.object(self.bus, 'transact_paths', side_effect=RuntimeError('unavailable')):
                with self.assertRaises(SeatError):
                    self.seats['coord'].act_once()
        import subprocess
        committed = json.loads(subprocess.run(['git', '-C', self.repo, 'show', 'HEAD:.team/STATE.json'],
                               capture_output=True, text=True, check=True).stdout)
        self.assertEqual(committed['status'], 'completing')
        self.assertNotEqual(self.bus.state()['status'], 'done')

    def test_foreign_dirt_not_swept_into_failure_record(self):
        self.prepare_done_turn()
        def fail(repo):
            self.write_app()
            raise ValueError('foreign dirt')
        with patch.object(self.guard, 'confirm_committed', side_effect=fail):
            with self.assertRaises(SeatError):
                self.seats['coord'].act_once()
        import subprocess
        tracked = subprocess.run(['git', '-C', self.repo, 'ls-tree', '-r', '--name-only', 'HEAD'],
                                 capture_output=True, text=True, check=True).stdout
        self.assertNotIn('app/a.py', tracked)
        self.assertEqual(self.bus.state()['status'], 'blocked')
        self.assertTrue(self.bus.pending_gates())

    def test_final_state_commit_failure_never_leaves_done_worktree(self):
        self.prepare_done_turn()
        original = self.bus.commit_paths
        def fail_final(message, paths):
            if 'finalize' in message:
                raise RuntimeError('final state commit failed')
            return original(message, paths)
        with patch.object(self.bus, 'commit_paths', side_effect=fail_final):
            with self.assertRaises(SeatError):
                self.seats['coord'].act_once()
        self.assertNotEqual(self.bus.state()['status'], 'done')

    def test_config_requires_side_effect_and_review_artifact_contracts(self):
        with self.assertRaises(ValueError):
            CompletionSession(self.guard.verify_argv, 'pin')
        with self.assertRaises(ValueError):
            CompletionSession(self.guard.verify_argv, 'pin', verification_is_side_effect_free=True,
                              reviews_write_artifacts=True)


    def test_first_commit_is_only_completing_then_verified_done(self):
        self.prepare_done_turn()
        observed = []
        original = self.bus.commit_all
        def capture(message):
            result = original(message)
            if result:
                observed.append(self.bus.state()['status'])
            return result
        with patch.object(self.bus, 'commit_all', side_effect=capture):
            self.seats['coord'].act_once()
        self.assertEqual(observed, ['completing'])
        self.assertEqual(self.bus.state()['status'], 'done')

    def test_verify_side_effect_refused_even_with_host_contract(self):
        self.guard.verify_argv = (sys.executable, '-c', "open('generated.txt','w').write('side effect')")
        with self.assertRaises(ValueError):
            self.review('review')
        self.assertFalse(self.guard.decide(self.seats['coord'])[0])
