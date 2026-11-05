"""Offline test-quality gate: mutation check plus a terminal-DONE evaluator.

Separates two facts the old cycle conflated:
  cycle_complete : the team finished its turns and the verify command passed.
  quality        : the tests can actually tell a correct implementation from
                   plausible wrong ones. 'proven' needs this gate; a QC seat,
                   same-model or not, is never sufficient by itself.

This module runs nothing by itself. Mutants are executed through an INJECTED
`run_tests(files) -> 'pass' | 'fail' | 'error'` callable; model-written code
must only run through a sandboxed runner (see the verify sandbox). There is no
default runner on purpose.

Thresholds below are PROPOSED defaults, not validated against real projects.
A passing gate is evidence that these mutants were caught, not proof of
correctness; labels are gate_passed / operator_check_passed, never "proven".
Reports and operator results are only believed when signed (HMAC) with an
operator-held key the seats never see; a plain dict cannot carry a pass. A mutant list is bounded and deterministic.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import hmac
import json

MAX_MUTANTS = 60
MIN_CONCLUSIVE = 5
MIN_SCORE = 0.8
MAX_INCONCLUSIVE_FRACTION = 0.2
MAX_HARVESTED = 12
GATE_VERSION = 'quality-gate-v2'


def _docstring_nodes(tree):
    ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            b = getattr(n, 'body', [])
            if b and isinstance(b[0], ast.Expr) and isinstance(getattr(b[0], 'value', None), ast.Constant) \
                    and isinstance(b[0].value.value, str):
                ids.add(id(b[0].value))
    return ids


def harvest_expected_constants(test_sources):
    """Literal int/float/str values tests mention (bool excluded), in first-seen
    order. Returns (values, truncated); truncated=True if more than the cap."""
    seen, out = set(), []
    for src in test_sources:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and not isinstance(n.value, bool) \
                    and isinstance(n.value, (int, float, str)) and n.value != '':
                key = (type(n.value).__name__, n.value)
                if key not in seen:
                    seen.add(key); out.append(n.value)
    return out[:MAX_HARVESTED], len(out) > MAX_HARVESTED


_CMP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt,
        ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
_BIN = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Add, ast.Div: ast.Mult,
        ast.FloorDiv: ast.Mult, ast.Mod: ast.Mult}


def generate_mutants(source, hardcode_values=()):
    """Deterministic (id, description, mutated_source) list, capped."""
    tree = ast.parse(source)
    skip = _docstring_nodes(tree)
    sites = []  # (kind, node-index, detail)
    nodes = list(ast.walk(tree))
    for i, n in enumerate(nodes):
        if isinstance(n, ast.Constant) and id(n) not in skip and isinstance(n.value, int) \
                and not isinstance(n.value, bool):
            sites.append(('const', i, 'int constant %r -> %r' % (n.value, n.value + 1)))
        elif isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            sites.append(('binop', i, 'operator %s -> %s' % (type(n.op).__name__, _BIN[type(n.op)].__name__)))
        elif isinstance(n, ast.Compare) and len(n.ops) == 1 and type(n.ops[0]) in _CMP:
            sites.append(('cmp', i, 'comparison %s -> %s' % (type(n.ops[0]).__name__, _CMP[type(n.ops[0])].__name__)))
        elif isinstance(n, ast.Return) and n.value is not None:
            sites.append(('ret_none', i, 'return value -> None'))
            for v in hardcode_values:
                sites.append(('ret_const', i, 'return value -> hardcoded %r' % (v,), v))
    out = []
    for k, site in enumerate(sites):
        t = copy.deepcopy(tree)
        ns = list(ast.walk(t))
        n = ns[site[1]]
        kind = site[0]
        if kind == 'const':
            n.value = n.value + 1
        elif kind == 'binop':
            n.op = _BIN[type(n.op)]()
        elif kind == 'cmp':
            n.ops = [_CMP[type(n.ops[0])]()]
        elif kind == 'ret_none':
            n.value = ast.Constant(value=None)
        elif kind == 'ret_const':
            n.value = ast.Constant(value=site[3])
        ast.fix_missing_locations(t)
        try:
            text = ast.unparse(t)
            compile(text, '<mutant>', 'exec')
        except Exception:
            continue
        if text == ast.unparse(tree):
            continue
        out.append(('m%03d' % k, '%s (line %s)' % (site[2], getattr(n, 'lineno', '?')), text))
        if len(out) >= MAX_MUTANTS:
            break
    return out


def checker_id():
    """Identity of this gate's configuration (version + thresholds)."""
    return hashlib.sha256(json.dumps([GATE_VERSION, MAX_MUTANTS, MIN_CONCLUSIVE, MIN_SCORE,
                                      MAX_INCONCLUSIVE_FRACTION, MAX_HARVESTED]).encode()).hexdigest()


def _canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':')).encode()


KIND_GATE = 'quality-gate-report/v2'
KIND_OPERATOR = 'operator-check-result/v1'
HASH_SCHEME = 'artifact_sha256/v1'   # hash over the FULL files dict; a per-file hash is not accepted
_KINDS = (KIND_GATE, KIND_OPERATOR)


def sign(key, payload, kind):
    """Operator-side: authenticate a report/result under an explicit domain `kind`.
    The kind is inside the MAC, so a gate signature cannot be replayed as an
    operator result or vice versa. key is bytes held by the operator only (never
    in a seat's env, messages, sandbox or the repo); use an ephemeral key in tests.
    Signatures carry no expiry: they bind to an artifact revision, not to time."""
    if kind not in _KINDS:
        raise ValueError('unknown signature kind')
    return {'kind': kind, 'payload': payload,
            'sig': hmac.new(key, _canon({'kind': kind, 'payload': payload}), hashlib.sha256).hexdigest()}


def sign_gate(key, report):
    return sign(key, report, KIND_GATE)


def sign_operator(key, result):
    return sign(key, result, KIND_OPERATOR)


def verify(key, signed, kind):
    """Return the payload if the signature is valid for `kind`, else None. Never raises."""
    try:
        if kind not in _KINDS or not isinstance(key, (bytes, bytearray)) or len(key) < 16 \
                or not isinstance(signed, dict) or signed.get('kind') != kind:
            return None
        p, sig = signed.get('payload'), signed.get('sig')
        if not isinstance(p, dict) or not isinstance(sig, str):
            return None
        want = hmac.new(bytes(key), _canon({'kind': kind, 'payload': p}), hashlib.sha256).hexdigest()
        return p if hmac.compare_digest(want, sig) else None
    except Exception:
        return None


def artifact_sha256(files):
    """Hash of the exact artifact revision (sorted path + content)."""
    h = hashlib.sha256()
    for k in sorted(files):
        h.update(json.dumps([k, files[k]]).encode())
    return h.hexdigest()


def _verdict(rep):
    """Verdict recomputed from counts only. Any surviving hardcoded-constant
    mutant fails outright: a function that returns a value the test expects is
    exactly the failure the gate exists to catch, whatever the score."""
    if rep.get('baseline') != 'pass':
        return 'baseline_not_passing'
    k, sv, inc, n = (rep.get('killed'), rep.get('survived'), rep.get('inconclusive'), rep.get('mutants'))
    if not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in (k, sv, inc, n)):
        return 'malformed'
    if k + sv + inc != n or sv != len(rep.get('survivors') or []):
        return 'malformed'
    if any('hardcoded' in str(x.get('desc')) for x in rep.get('survivors') if isinstance(x, dict)):
        return 'failed'
    if rep.get('harvest_truncated') is True:
        return 'insufficient_evidence'
    if k + sv < MIN_CONCLUSIVE or (n and inc / n > MAX_INCONCLUSIVE_FRACTION):
        return 'insufficient_evidence'
    return 'passed' if k / (k + sv) >= MIN_SCORE else 'failed'


def run_gate(source_files, test_files, run_tests, target, run_tests_optimized=None, runner_id=None):
    """Mutate `target` (a key of source_files), run all tests per mutant.

    source_files/test_files: {path: text}. run_tests(files) -> 'pass'|'fail'|'error'
    where files is the merged dict. The baseline must pass; otherwise the gate
    is 'baseline_not_passing' and nothing is mutated.
    """
    if target not in source_files:
        raise ValueError('target is not one of the source files')
    files = dict(source_files); files.update(test_files)
    base = run_tests(files)
    rep = {'schema': 'quality-gate/v1', 'target': target, 'baseline': base,
           'artifact_sha256': artifact_sha256(files), 'hash_scheme': HASH_SCHEME, 'checker_id': checker_id(),
           'runner_id': runner_id,
           'o_policy': 'checked' if run_tests_optimized is not None else 'not_checked',
           'killed': 0, 'survived': 0, 'inconclusive': 0, 'survivors': [],
           'thresholds': {'min_score': MIN_SCORE, 'min_conclusive': MIN_CONCLUSIVE,
                          'max_inconclusive_fraction': MAX_INCONCLUSIVE_FRACTION,
                          'status': 'proposed, not validated'}}
    if base != 'pass':
        rep.update(verdict='baseline_not_passing', score=None, mutants=0)
        return rep
    if run_tests_optimized is not None and run_tests_optimized(files) != 'pass':
        rep.update(verdict='baseline_not_passing', score=None, mutants=0, baseline='fail_under_O')
        return rep
    hard, trunc = harvest_expected_constants(test_files.values())
    rep['harvest_truncated'] = trunc
    try:
        mutants = generate_mutants(source_files[target], hard)
    except SyntaxError:
        rep.update(verdict='malformed_target', score=None, mutants=0)
        return rep
    rep['mutants'] = len(mutants)
    for mid, desc, text in mutants:
        f = dict(files); f[target] = text
        r = run_tests(f)
        if r == 'fail' and run_tests_optimized is not None:
            ro = run_tests_optimized(f)
            if ro == 'pass':   # killed only by asserts that python -O strips
                rep['survived'] += 1
                rep['survivors'].append({'id': mid, 'desc': desc + ' [survives under -O]'})
                continue
            if ro != 'fail':
                rep['inconclusive'] += 1
                continue
        if r == 'fail':
            rep['killed'] += 1
        elif r == 'pass':
            rep['survived'] += 1
            rep['survivors'].append({'id': mid, 'desc': desc})
        else:
            rep['inconclusive'] += 1
    conclusive = rep['killed'] + rep['survived']
    rep['score'] = (rep['killed'] / conclusive) if conclusive else None
    rep['verdict'] = _verdict(rep)
    return rep


def evaluate_done(cycle_complete, signed_gate, qc=None, current_artifact_sha256=None,
                  signed_operator_result=None, *, operator_key=None, expected_target=None,
                  expected_runner_id=None, expected_operator_checker_id=None,
                  require_o_policy=True):
    """Terminal DONE with explicit, bounded evidence labels.

    Evidence labels are gate_passed / operator_check_passed (bounded evidence,
    not proof). terminal_done needs cycle completion AND one such label, where
    the evidence is HMAC-signed by operator_key, bound to current_artifact_sha256,
    this gate's checker_id, expected_target (and expected_runner_id /
    expected_operator_checker_id when given), and for gates an -O-checked run
    (require_o_policy). Plain dicts, stale, mismatched or inconsistent evidence is
    'unproven'; a valid operator rejection overrides a gate pass. QC verdicts,
    same-model or not, never count.
    """
    reasons = []
    if cycle_complete is not True:
        reasons.append('cycle not complete')
    cur = current_artifact_sha256
    if not (isinstance(cur, str) and len(cur) == 64):
        reasons.append('no current artifact revision to bind quality evidence to')
        cur = None
    quality = 'unproven'
    op_state = gate_state = None
    if signed_operator_result is not None:
        p = verify(operator_key, signed_operator_result, KIND_OPERATOR)
        if p is None:
            reasons.append('operator result not authenticated (bad or missing signature/key)')
        elif p.get('hash_scheme') != HASH_SCHEME:
            reasons.append('operator result does not bind the full-artifact hash scheme')
        elif cur is None or p.get('artifact_sha256') != cur:
            reasons.append('operator result is for a different or unknown artifact revision')
        elif expected_operator_checker_id is None or p.get('checker_id') != expected_operator_checker_id:
            reasons.append('operator result is from an unexpected or unspecified checker')
        elif p.get('accepted') is True and p.get('state') == 'accepted':
            op_state = 'accepted'
        elif p.get('accepted') is False and p.get('state') == 'rejected':
            op_state = 'rejected'
        else:
            reasons.append('operator result is not a clean accept or reject')
    if signed_gate is not None:
        g = verify(operator_key, signed_gate, KIND_GATE)
        if g is None:
            reasons.append('gate report not authenticated (bad or missing signature/key)')
        elif g.get('hash_scheme') != HASH_SCHEME:
            reasons.append('gate report does not bind the full-artifact hash scheme')
        elif cur is None or g.get('artifact_sha256') != cur:
            reasons.append('gate report is stale: artifact revision changed or unknown')
        elif g.get('checker_id') != checker_id():
            reasons.append('gate report is from a different gate configuration')
        elif expected_target is None or g.get('target') != expected_target:
            reasons.append('gate report target does not match the expected source target')
        elif expected_runner_id is not None and g.get('runner_id') != expected_runner_id:
            reasons.append('gate report was run by an unexpected runner')
        elif require_o_policy and g.get('o_policy') != 'checked':
            reasons.append('gate did not check behavior under python -O')
        else:
            v = _verdict(g)
            if v != g.get('verdict'):
                reasons.append('gate report inconsistent: verdict does not match its counts')
            elif v == 'passed':
                gate_state = 'passed'
            elif v == 'failed':
                gate_state = 'failed'
                reasons.append('mutation gate failed: surviving mutants')
            else:
                reasons.append('gate verdict %r is not a pass' % (v,))
    if op_state == 'rejected':
        quality = 'failed'; reasons.append('operator check rejected this revision')
    elif gate_state == 'failed':
        quality = 'failed'
    elif op_state == 'accepted':
        quality = 'operator_check_passed'
    elif gate_state == 'passed':
        quality = 'gate_passed'
    if quality == 'unproven' and signed_gate is None and signed_operator_result is None:
        reasons.append('no quality gate or operator check; QC verdict alone cannot establish quality')
    qc_note = None
    if isinstance(qc, dict):
        same = qc.get('model') is not None and qc.get('model') == qc.get('builder_model')
        qc_note = {'verdict': qc.get('verdict'), 'same_model_as_builder': bool(same),
                   'counts_toward_quality': False}
        if same:
            reasons.append('QC used the same model as the builder: smoke only')
    return {'cycle_complete': cycle_complete is True, 'quality': quality,
            'terminal_done': cycle_complete is True and quality in ('gate_passed', 'operator_check_passed'),
            'artifact_sha256': cur, 'qc': qc_note, 'reasons': reasons,
            'note': 'bounded evidence, not proof of correctness'}
