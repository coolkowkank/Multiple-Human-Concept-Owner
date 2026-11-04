import json
import os
import shutil
import subprocess
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_launcher import make_repo, seat_spec
from launcher.guarded_offline import run_guarded_offline


class GuardedOfflineTests(unittest.TestCase):
    def setUp(self):
        self.verify = [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v']
        scripts = {
            'coordinator': [dict(summary='assign', handoff='builder'), dict(status_line='DONE', handoff=None)],
            'builder': [dict(summary='implement', handoff='reviewer', writes={
                'tinylib/__init__.py': 'def add(a,b):\n    return a+b\n',
                'tests/test_add.py': 'import unittest\nfrom tinylib import add\nclass Test(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n'})],
            'reviewer': [dict(summary='review', review_verdict='PASS', handoff='qc')],
            'qc': [dict(summary='QC', review_verdict='PASS', handoff='coordinator')],
        }
        seats = {role: seat_spec(script, ['tinylib/', 'tests/'] if role == 'builder' else ['.team/'], role)
                 for role, script in scripts.items()}
        self.repo, self.bus = make_repo(seats, 'add(a,b) returns a+b; add(2,3)==5; unittest passes')
        self.addCleanup(shutil.rmtree, self.repo, True)

    def run_cycle(self, **kwargs):
        return run_guarded_offline(self.repo, self.bus.branch, verify_argv=self.verify, **kwargs)

    def change_roster(self, fn):
        roster = self.bus.roster(); fn(roster)
        with open(os.path.join(self.repo, '.team/roster.json'), 'w') as fh:
            json.dump(roster, fh)
        self.bus.commit_all('operator: configure fixture')

    def test_complete_five_turn_cycle_no_manual_recovery(self):
        result = self.run_cycle()
        self.assertEqual((result['result'], result['turns']), ('done', 5))
        self.assertEqual(self.bus.state()['status'], 'done')
        order = [row['seat'] for row in self.bus.log(kinds=['handoff'])]
        self.assertEqual(order, ['coordinator', 'builder', 'reviewer', 'qc', 'coordinator'])
        self.assertFalse(self.bus.pending_gates())

    def test_skip_reviewer_refuses_done(self):
        self.change_roster(lambda r: r['seats']['builder']['adapter']['script'][0].update(handoff='qc'))
        self.assertEqual(self.run_cycle()['result'], 'gate')
        self.assertEqual(self.bus.state()['status'], 'blocked')

    def test_qc_fail_refuses_done(self):
        self.change_roster(lambda r: r['seats']['qc']['adapter']['script'][0].update(review_verdict='FAIL'))
        self.assertEqual(self.run_cycle()['result'], 'gate')

    def test_provider_and_cli_and_queue_refused_before_building_seat(self):
        from unittest.mock import patch
        for kind in ('http', 'cli', 'queue'):
            with self.subTest(kind=kind):
                self.change_roster(lambda r: r['seats']['builder']['adapter'].update(type=kind))
                with patch('launcher.guarded_offline.Seat') as seat:
                    with self.assertRaises(ValueError): self.run_cycle()
                    seat.assert_not_called()

    def test_missing_seat_refused(self):
        self.change_roster(lambda r: r['seats'].pop('reviewer'))
        with self.assertRaises(ValueError): self.run_cycle()

    def test_review_writes_refused(self):
        self.change_roster(lambda r: r['seats']['reviewer']['adapter']['script'][0].update(writes={'review/x': 'x'}))
        with self.assertRaises(ValueError): self.run_cycle()

    def test_model_command_refused(self):
        self.change_roster(lambda r: r['seats']['builder']['adapter']['script'][0].update(verify_command='anything'))
        with self.assertRaises(ValueError): self.run_cycle()

    def test_turn_limit_and_restart_refusal(self):
        self.assertEqual(self.run_cycle(max_turns=1)['result'], 'turn_limit')
        with self.assertRaises(ValueError): self.run_cycle()

    def test_existing_launch_subprocess_behavior_untouched(self):
        from launcher.supervisor import Supervisor
        from unittest.mock import patch
        with patch('launcher.supervisor.subprocess.Popen') as proc:
            Supervisor(self.repo).start_seat('builder')
            self.assertIn('seat', proc.call_args.args[0])

    def test_cli_explicit_mock_only_path(self):
        source = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        proc = subprocess.run([sys.executable, '-m', 'launcher', 'guarded-offline', '--repo', self.repo,
            '--branch', self.bus.branch, '--verify-argv-json', json.dumps(self.verify)],
            cwd=source, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['result'], 'done')


    def test_preexisting_lease_still_enforced(self):
        import time
        state = self.bus.state()
        state['leases']['coordinator'] = {'holder': 'other-session', 'claimed_at': time.time()}
        self.bus.write_state(state); self.bus.commit_all('operator: lease fixture')
        from launcher.runtime import SeatError
        with self.assertRaises(SeatError): self.run_cycle()

    def test_nonpositive_caps_refused(self):
        for values in ({'max_turns': 0}, {'max_seconds': 0}, {'max_turns': True}):
            with self.assertRaises(ValueError): self.run_cycle(**values)


    def test_actual_cycle_prompt_sources_counted_without_content(self):
        rows = []
        result = self.run_cycle(prompt_audits=rows)
        self.assertEqual(result['result'], 'done')
        self.assertEqual([r['seat'] for r in rows], ['coordinator', 'builder', 'reviewer', 'qc', 'coordinator'])
        self.assertTrue(all(r['provider_tokens'] is None for r in rows))
        self.assertTrue(all(r['outcome'] == 'mock_adapter_returned' for r in rows))
        for row in rows:
            for field in ('system', 'task'):
                self.assertEqual(sum(s['chars'] for s in row[field]['sources']), row[field]['chars'])
        text = json.dumps(rows)
        self.assertNotIn('add(2,3)==5', text)
        self.assertNotIn('def add', text)
        self.assertGreater(rows[-1]['task']['chars'], rows[0]['task']['chars'])

    def test_observer_is_optional_and_wrong_type_refused(self):
        with self.assertRaises(ValueError): self.run_cycle(prompt_audits={})
        self.assertEqual(self.run_cycle()['result'], 'done')
