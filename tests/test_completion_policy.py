import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import unittest
from dataclasses import replace
from launcher.completion_policy import Binding, Policy, Evidence, evaluate_completion


class CompletionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.binding = Binding('worktree-v1', 'brief-v1', 'runtime-v1', 'roster-v1', 'fixed-verify-v1')
        self.policy = Policy(True, True, True)  # Synthetic approved fixture, NOT project approval.
        self.roster = {'build': 'builder', 'review': 'reviewer', 'quality': 'qc'}
        self.rows = [Evidence(seat, role, self.binding, 'PASS', 0, True, True,
                              'source-commit', 'artifact-digest', seq)
                     for seat, role, seq in [('review', 'reviewer', 4), ('quality', 'qc', 5)]]

    def check(self, **changes):
        args = dict(current=self.binding, roster=self.roster, builder='build',
                    evidence=self.rows, policy=self.policy, worktree_binding_validated=True)
        args.update(changes)
        return evaluate_completion(**args)

    def test_matching_independent_fixture_eligible_not_runtime_done(self):
        self.assertTrue(self.check().eligible)

    def test_both_required(self):
        for rows in ([], self.rows[:1], self.rows[1:]):
            self.assertFalse(self.check(evidence=rows).eligible)

    def test_unresolved_semantics_refuse(self):
        self.assertFalse(self.check(policy=Policy()).eligible)
        for field in ('independent_roles_approved', 'pass_rubric_approved', 'missing_seat_policy_approved'):
            for value in (None, False, 1):
                self.assertFalse(self.check(policy=replace(self.policy, **{field: value})).eligible)

    def test_changed_complete_binding_invalidates(self):
        for field in self.binding.__dataclass_fields__:
            self.assertFalse(self.check(current=replace(self.binding, **{field: 'changed'})).eligible)

    def test_missing_binding_refuses(self):
        self.assertFalse(self.check(current=None).eligible)
        self.assertFalse(self.check(current=replace(self.binding, application='')).eligible)

    def test_worktree_validation_required_not_head_assumption(self):
        self.assertFalse(self.check(worktree_binding_validated=False).eligible)

    def test_different_application_for_each_verdict_refuses(self):
        rows = [replace(self.rows[0], binding=replace(self.binding, application='old')), self.rows[1]]
        self.assertFalse(self.check(evidence=rows).eligible)

    def test_evidence_log_only_commit_does_not_change_application_binding(self):
        rows = [replace(row, source_commit='different-evidence-commit') for row in self.rows]
        self.assertTrue(self.check(evidence=rows).eligible)

    def test_no_prose_or_self_declared_records(self):
        self.assertFalse(self.check(evidence=[{'role': 'qc', 'verdict': 'PASS'}]).eligible)
        self.assertFalse(self.check(evidence=[replace(row, provenance_validated=False) for row in self.rows]).eligible)

    def test_missing_or_ambiguous_roster_seats_refuse(self):
        for roster in ({'build': 'builder'}, dict(self.roster, review2='reviewer'), {}):
            self.assertFalse(self.check(roster=roster).eligible)

    def test_builder_cannot_supply_review_evidence(self):
        self.assertFalse(self.check(evidence=[replace(row, seat='build') for row in self.rows]).eligible)
        self.assertFalse(self.check(builder='review').eligible)

    def test_fixed_verify_policy_required(self):
        self.assertFalse(self.check(evidence=[replace(row, fixed_verify_policy_observed=False) for row in self.rows]).eligible)

    def test_verify_failure_missing_or_boolean_exit_refuses(self):
        for exit_code in (1, None, False):
            self.assertFalse(self.check(evidence=[replace(self.rows[0], observed_verify_exit=exit_code), self.rows[1]]).eligible)

    def test_explicit_pass_only(self):
        for verdict in ('FAIL', 'PASS maybe', 'UNKNOWN', None):
            self.assertFalse(self.check(evidence=[replace(self.rows[0], verdict=verdict), self.rows[1]]).eligible)

    def test_later_fail_not_hidden_by_earlier_pass(self):
        self.assertFalse(self.check(evidence=self.rows + [replace(self.rows[0], verdict='FAIL', turn_seq=6)]).eligible)

    def test_duplicate_latest_or_missing_turn_refuses(self):
        self.assertFalse(self.check(evidence=self.rows + [self.rows[0]]).eligible)
        self.assertFalse(self.check(evidence=[replace(self.rows[0], turn_seq=None), self.rows[1]]).eligible)

    def test_evidence_provenance_fields_required(self):
        for field in ('source_commit', 'evidence_digest'):
            self.assertFalse(self.check(evidence=[replace(self.rows[0], **{field: ''}), self.rows[1]]).eligible)

    def test_unhashable_or_invalid_builder_refuses(self):
        for builder in ([], {}, None, '', '   ', 1):
            self.assertFalse(self.check(builder=builder).eligible)

    def test_required_seat_wrong_role_never_hides_later_fail(self):
        bad = replace(self.rows[0], role='qc', verdict='FAIL', turn_seq=6)
        self.assertFalse(self.check(evidence=self.rows + [bad]).eligible)
        self.assertFalse(self.check(evidence=[bad] + self.rows).eligible)

    def test_commit_and_digest_require_nonempty_strings(self):
        for field in ('source_commit', 'evidence_digest'):
            for value in (True, 42, object(), [], {}, '   '):
                self.assertFalse(self.check(evidence=[replace(self.rows[0], **{field: value}), self.rows[1]]).eligible)

    def test_pure_idempotent_no_input_mutation(self):
        before = repr((self.rows, self.roster, self.binding, self.policy))
        self.assertEqual(self.check(), self.check())
        self.assertEqual(before, repr((self.rows, self.roster, self.binding, self.policy)))


if __name__ == '__main__':
    unittest.main()
