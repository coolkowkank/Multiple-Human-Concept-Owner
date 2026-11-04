"""Pure WP4 completion predicate, NOT wired to runtime or an authority source.

Inputs are observations supplied by a future reviewed runtime integration.
This function cannot authenticate records, compute the worktree manifest or
establish independent reasoning. Missing provenance/semantic decisions refuse
completion. No I/O, stamps, mutation, clock, provider or retry behavior here.
"""
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class Binding:
    application: str
    brief: str
    runtime_policy: str
    roster_policy: str
    verify_policy: str

    def complete(self):
        return all(isinstance(v, str) and bool(v.strip()) for v in (
            self.application, self.brief, self.runtime_policy,
            self.roster_policy, self.verify_policy))


@dataclass(frozen=True)
class Policy:
    # None means unresolved, NOT an implicit default.
    independent_roles_approved: Optional[bool] = None
    pass_rubric_approved: Optional[bool] = None
    missing_seat_policy_approved: Optional[bool] = None


@dataclass(frozen=True)
class Evidence:
    seat: str
    role: str
    binding: Binding
    verdict: str
    observed_verify_exit: Optional[int]
    # Integration must set these from observed execution, never model fields.
    provenance_validated: bool = False
    fixed_verify_policy_observed: bool = False
    source_commit: str = ''
    evidence_digest: str = ''
    turn_seq: Optional[int] = None


@dataclass(frozen=True)
class Decision:
    eligible: bool
    reasons: Tuple[str, ...]


def evaluate_completion(*, current, roster, builder, evidence, policy,
                        worktree_binding_validated=False):
    """Eligibility only. Never marks done or treats prose/HEAD equality as proof.

    roster is the explicitly frozen seat->role mapping. current must bind the
    post-write WORKTREE plus acceptance policy, not pre-turn HEAD. Provenance
    flags are assertions of a trusted caller and need separate integration
    review; passing user/model JSON here is NOT secure provenance validation.
    Evidence/log commit SHA is retained for audit but not the eligibility pin.
    """
    reasons = []
    if not isinstance(policy, Policy) or any(v is not True for v in (
            policy.independent_roles_approved, policy.pass_rubric_approved,
            policy.missing_seat_policy_approved)):
        reasons.append('semantic_policy_unresolved_or_unapproved')
    if not isinstance(current, Binding) or not current.complete():
        reasons.append('acceptance_binding_missing')
    if worktree_binding_validated is not True:
        reasons.append('post_write_worktree_binding_unvalidated')
    if not isinstance(roster, dict) or roster.get(builder) != 'builder':
        reasons.append('builder_identity_missing')
        roster = {} if not isinstance(roster, dict) else roster
    seats = {}
    for role in ('reviewer', 'qc'):
        matches = [seat for seat, assigned in roster.items() if assigned == role]
        if len(matches) != 1:
            reasons.append(role + '_seat_missing_or_ambiguous')
        else:
            seats[role] = matches[0]
    if builder in seats.values() or len(set(seats.values())) != len(seats):
        reasons.append('distinct_seats_required')
    if reasons:
        return Decision(False, tuple(reasons))
    if not isinstance(evidence, (list, tuple)) or any(
            not isinstance(row, Evidence) for row in evidence):
        return Decision(False, ('evidence_schema_invalid',))
    for role, seat in seats.items():
        # Latest supplied runtime-validated turn for this seat controls. An
        # earlier PASS must not hide a later FAIL or conflicting verdict.
        rows = [row for row in evidence if row.seat == seat and row.role == role]
        if not rows:
            reasons.append(role + '_evidence_missing')
            continue
        if any(type(row.turn_seq) is not int or row.turn_seq < 0 for row in rows):
            reasons.append(role + '_turn_provenance_invalid')
            continue
        latest = max(row.turn_seq for row in rows)
        latest_rows = [row for row in rows if row.turn_seq == latest]
        if len(latest_rows) != 1:
            reasons.append(role + '_latest_evidence_ambiguous')
            continue
        row = latest_rows[0]
        if row.provenance_validated is not True or not row.source_commit or not row.evidence_digest:
            reasons.append(role + '_runtime_provenance_missing')
        if row.binding != current:
            reasons.append(role + '_binding_stale')
        if row.fixed_verify_policy_observed is not True:
            reasons.append(role + '_fixed_verify_policy_unobserved')
        if type(row.observed_verify_exit) is not int or row.observed_verify_exit != 0:
            reasons.append(role + '_verify_not_passed')
        if row.verdict != 'PASS':
            reasons.append(role + '_verdict_not_passed')
    return Decision(not reasons, tuple(reasons))
