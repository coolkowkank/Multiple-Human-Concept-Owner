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
correctness. A mutant list is bounded and deterministic.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json

MAX_MUTANTS = 60
MIN_CONCLUSIVE = 5
MIN_SCORE = 0.8
MAX_INCONCLUSIVE_FRACTION = 0.2
MAX_HARVESTED = 6


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
    """Literal values tests compare against (int/str only, bounded, ordered)."""
    seen, out = set(), []
    for src in test_sources:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and not isinstance(n.value, bool) \
                    and isinstance(n.value, (int, str)) and n.value not in ('',):
                key = (type(n.value).__name__, n.value)
                if key not in seen:
                    seen.add(key); out.append(n.value)
    return out[:MAX_HARVESTED]


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
    if k + sv < MIN_CONCLUSIVE or (n and inc / n > MAX_INCONCLUSIVE_FRACTION):
        return 'insufficient_evidence'
    return 'passed' if k / (k + sv) >= MIN_SCORE else 'failed'


def run_gate(source_files, test_files, run_tests, target):
    """Mutate `target` (a key of source_files), run all tests per mutant.

    source_files/test_files: {path: text}. run_tests(files) -> 'pass'|'fail'|'error'
    where files is the merged dict. The baseline must pass; otherwise the gate
    is 'baseline_not_passing' and nothing is mutated.
    """
    files = dict(source_files); files.update(test_files)
    base = run_tests(files)
    rep = {'schema': 'quality-gate/v1', 'target': target, 'baseline': base,
           'artifact_sha256': artifact_sha256(files),
           'killed': 0, 'survived': 0, 'inconclusive': 0, 'survivors': [],
           'thresholds': {'min_score': MIN_SCORE, 'min_conclusive': MIN_CONCLUSIVE,
                          'max_inconclusive_fraction': MAX_INCONCLUSIVE_FRACTION,
                          'status': 'proposed, not validated'}}
    if base != 'pass':
        rep.update(verdict='baseline_not_passing', score=None, mutants=0)
        return rep
    hard = harvest_expected_constants(test_files.values())
    mutants = generate_mutants(source_files[target], hard)
    rep['mutants'] = len(mutants)
    for mid, desc, text in mutants:
        f = dict(files); f[target] = text
        r = run_tests(f)
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


def evaluate_done(cycle_complete, gate_report, qc=None, current_artifact_sha256=None,
                  operator_result=None):
    """Terminal DONE with an explicit quality label, bound to one artifact revision.

    terminal_done requires cycle completion AND a quality proof bound to
    current_artifact_sha256: either a mutation-gate report that recomputes to
    'passed', or an operator-held check result that accepted that exact
    revision. Stale (different revision), inconsistent or unbound evidence is
    'unproven'; an operator rejection of the current revision is 'failed' and
    overrides a gate pass. A QC verdict, same-model or not, never counts.
    Reports are unauthenticated data: the caller must obtain them from its own
    operator-side run, not from a seat's output.
    """
    reasons = []
    if cycle_complete is not True:
        reasons.append('cycle not complete')
    cur = current_artifact_sha256
    if not (isinstance(cur, str) and len(cur) == 64):
        reasons.append('no current artifact revision to bind quality evidence to')
        cur = None
    quality = 'unproven'
    # operator-held check
    op = operator_result if isinstance(operator_result, dict) else None
    op_state = None
    if op is not None:
        if cur is None or op.get('artifact_sha256') != cur:
            reasons.append('operator result is for a different or unknown artifact revision')
        elif op.get('accepted') is True:
            op_state = 'accepted'
        elif op.get('accepted') is False:
            op_state = 'rejected'
    gate_state = None
    if gate_report is not None:
        if not isinstance(gate_report, dict):
            reasons.append('gate report malformed')
        elif cur is None or gate_report.get('artifact_sha256') != cur:
            reasons.append('gate report is stale: artifact revision changed or unknown')
        else:
            v = _verdict(gate_report)
            if v != gate_report.get('verdict'):
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
        quality = 'proven_by_operator_check'
    elif gate_state == 'passed':
        quality = 'proven_by_mutation_gate'
    if quality == 'unproven' and gate_report is None and op is None:
        reasons.append('no quality gate or operator check; QC verdict alone cannot prove quality')
    qc_note = None
    if isinstance(qc, dict):
        same = qc.get('model') is not None and qc.get('model') == qc.get('builder_model')
        qc_note = {'verdict': qc.get('verdict'), 'same_model_as_builder': bool(same),
                   'counts_toward_quality': False}
        if same:
            reasons.append('QC used the same model as the builder: smoke only')
    return {'cycle_complete': cycle_complete is True, 'quality': quality,
            'terminal_done': cycle_complete is True and quality.startswith('proven_by_'),
            'artifact_sha256': cur, 'qc': qc_note, 'reasons': reasons}
