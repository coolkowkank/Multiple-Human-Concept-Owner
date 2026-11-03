#!/usr/bin/env python3
"""Filled-artifact conformance checker.

Validates that a COMPLETED review artifact (batch handoff, QC verdict,
review findings, decision record, delegation record, gated-run evidence)
satisfies the structural contract of its template in templates/.

Structural checks only. This tool cannot establish semantic truth: a
present head SHA may still name the wrong commit, a filled owner_basis
may still cite a fabricated decision, tests may not have really run.
Authenticity and honesty stay with review seats and the runtime checker
(launcher/conformance.py), not with this file.

Usage: check.py <artifact-file> <type> [--decisions DIR]
Types: batch-handoff, qc-verdict, review-findings, decision-record,
       delegation-record, gated-run-evidence
Exit: 0 conformant; 1 violations (listed on stdout); 2 usage error.
"""

from __future__ import annotations

import os
import re
import sys

SHA_RE = re.compile(r"\b[0-9a-f]{40}\b")
DR_RE = re.compile(r"\bDR-\S+")
PLACEHOLDER_RE = re.compile(r"`?<[^<>\n]{2,120}>`?")
ENV_RE = re.compile(r"^(mock|local|hosted)\b", re.IGNORECASE)

VIOLATIONS = []


def fail(msg):
    VIOLATIONS.append(msg)


def table_fields(text):
    """Parse a two-column markdown table into {field: value}."""
    fields = {}
    for line in text.splitlines():
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 2:
            continue
        key, val = cells
        if key in ("Field", "---") or set(key) <= set("-: "):
            continue
        fields[key.rstrip(":")] = val
    return fields


def bullet(line):
    return line.strip().lstrip("-").strip()


def section_lines(text, header):
    """Lines under a '## header' until the next header."""
    out, on = [], False
    for line in text.splitlines():
        if re.match(r"^##\s", line):
            on = line.strip().lower().startswith("## " + header.lower())
            continue
        if on:
            out.append(line)
    return out


def nonempty(val):
    return bool(val) and val not in ("-", "none needed") or val == "none"


def check_no_placeholders(text):
    for m in PLACEHOLDER_RE.finditer(text):
        fail(f"unfilled placeholder / raw angle-bracket token: "
                     f"{m.group(0)}")


def require_fields(fields, names):
    for name in names:
        val = fields.get(name, "")
        if not val.strip():
            fail(f"missing or empty field: {name}")


def check_head(val, label):
    if not SHA_RE.search(val):
        fail(f"{label} does not contain a full 40-hex commit SHA")


def check_env(val):
    if not ENV_RE.search(val.strip()):
        fail("environment must start with mock / local / hosted and name "
             "the account type")


def check_owner_basis(val, decisions_dir):
    v = val.strip()
    if not v:
        fail("owner basis is empty; state a DR-ID or 'none - no gated "
             "items'")
        return
    if not re.fullmatch(r"none\s*-\s*no gated items\.?", v,
                        re.IGNORECASE):
        if not DR_RE.findall(v):
            fail("owner basis must cite a DR-ID or be exactly "
                 "'none - no gated items'")
            return
    else:
        return
    ids = DR_RE.findall(v)
    if not ids:
        fail("owner basis cites no decision-record ID (DR-...)")
        return
    if decisions_dir:
        known = set()
        for fn in os.listdir(decisions_dir):
            if fn.endswith(".md"):
                known.update(DR_RE.findall(
                    open(os.path.join(decisions_dir, fn)).read()))
        for i in ids:
            if i not in known:
                fail(f"owner basis cites {i}, not found in supplied "
                     "decision records")


def check_batch_handoff(text, decisions_dir):
    if not re.search(r"^TURN:\s*\S+", text, re.MULTILINE):
        fail("missing TURN: <seat> line")
    m = re.search(r"^Turn seq:\s*(\d+)", text, re.MULTILINE)
    if not m:
        fail("missing or non-integer Turn seq")
    kv = {}
    for line in text.splitlines():
        if line.startswith("- ") and ":" in line:
            k, v = line[2:].split(":", 1)
            kv[k.strip()] = v.strip()
    for k in ("Assigned to", "Batch scope", "Verify command", "Suites"):
        if not kv.get(k):
            fail(f"missing or empty line: {k}")
    check_head(kv.get("Head", ""), "Head")
    if kv.get("Exit code", "") and not kv["Exit code"].isdigit():
        fail("Exit code is not an integer")
    elif not kv.get("Exit code"):
        fail("missing Exit code")
    if kv.get("Suites") and not re.search(r"\S+:\s*\d+/\d+", kv["Suites"]):
        fail("Suites lines must be `name: pass/fail` counts")
    check_env(kv.get("Environment", ""))
    check_owner_basis(kv.get("Owner basis", ""), decisions_dir)
    if not re.search(r"^-\s*Next:\s*\S+", text, re.MULTILINE):
        fail("missing Handoff Next line")


def check_qc_verdict(text, decisions_dir):
    kv = {}
    for line in text.splitlines():
        if line.startswith("- ") and ":" in line:
            k, v = line[2:].split(":", 1)
            kv[k.strip()] = v.strip()
    check_head(kv.get("Head reviewed", ""), "Head reviewed")
    check_owner_basis(kv.get("Owner basis", ""), decisions_dir)
    if not re.search(r"^##\s*Verdict[ \t]*\n+[ \t]*(PASS|FAIL)[ \t]*$",
                     text, re.MULTILINE):
        fail("verdict line must be exactly PASS or FAIL - no "
                     "qualifiers such as 'PASS with reservations'")
    for sec in ("Reproduced", "Probed"):
        lines = [bullet(l) for l in section_lines(text, "What QC actually did")
                 if bullet(l).lower().startswith(sec.lower() + ":")]
        if not lines or not lines[0].split(":", 1)[1].strip():
            fail(f"'{sec}:' entry missing or empty")
    ro = [bullet(l) for l in section_lines(text, "What QC actually did")
          if bullet(l).lower().startswith("read only:")]
    if not ro or not ro[0].split(":", 1)[1].strip():
        fail("'Read only:' entry missing or empty (state 'none' if so)")
    lim = [bullet(l) for l in section_lines(text, "Stated limits")
           if l.strip().startswith("-")]
    for l in lim:
        if not re.search(r"\b(accept|waive|must fix)\b", l, re.IGNORECASE):
            fail(f"stated limit lacks accept/waive/must-fix resolution: {l}")


def check_review_findings(text, decisions_dir):
    rows = []
    in_table = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("|") and "Severity" in line:
            in_table = True
            continue
        if in_table and line.startswith("|") and not set(
                line.replace("|", "").strip()) <= set("-: "):
            rows.append([c.strip() for c in line.strip("|").split("|")])
        elif in_table and not line.startswith("|"):
            in_table = False
    for r in rows:
        if len(r) < 6:
            fail(f"findings row has too few cells: {r}")
            continue
        _, typ, sev, pri, gate = r[0], r[1], r[2], r[3], r[4]
        if typ not in ("defect", "remaining-work"):
            fail(f"finding type must be defect or remaining-work: {typ!r}")
        if sev not in ("critical", "major", "minor"):
            fail(f"severity must be critical/major/minor: {sev!r}")
        if not pri:
            fail("finding row missing priority")
        if gate.lower() == "yes" and not DR_RE.findall("|".join(r)):
            fail("owner-gated finding cites no DR-ID")
    if not rows:
        fail("no findings rows parsed (state an empty table explicitly "
             "if there are none)")
    for sec in ("Reproduced", "Probed", "Read only"):
        hit = [bullet(l) for l in section_lines(
            text, "What the Reviewer actually did")
            if bullet(l).lower().startswith(sec.lower() + ":")]
        if not hit or not hit[0].split(":", 1)[1].strip():
            fail(f"'{sec}:' entry missing or empty")


def check_decision_record(text, decisions_dir):
    fields = table_fields(text)
    require_fields(fields, ["ID", "Date", "Owner", "Decision",
                            "Owner words", "Channel + timestamp", "Covers",
                            "Limits", "Recorded by"])
    if not DR_RE.match(fields.get("ID", "")):
        fail("ID must be DR-<sequence number>")
    loc = fields.get("Locator", "")
    if loc and "http" in loc.lower() and not re.search(
            r"public|agreed", loc, re.IGNORECASE):
        fail("locator contains a link without a public/agreed marking "
             "(public-safe rule)")


def check_delegation_record(text, decisions_dir):
    fields = table_fields(text)
    require_fields(fields, ["Owner", "Delegated decisions",
                            "Delegated actions", "Limits",
                            "Never delegated", "Owner words",
                            "Where to verify", "Recorded at"])


def check_gated_run_evidence(text, decisions_dir):
    fields = table_fields(text)
    require_fields(fields, ["Decision record", "Target and scope",
                            "Environment", "Counts before / after",
                            "Test identity", "Cleanup", "Not proven",
                            "No-secrets check"])
    dr = fields.get("Decision record", "")
    if dr and not DR_RE.findall(dr):
        fail("Decision record field cites no DR-ID")
    if decisions_dir and DR_RE.findall(dr):
        known = set()
        for fn in os.listdir(decisions_dir):
            if fn.endswith(".md"):
                known.update(DR_RE.findall(
                    open(os.path.join(decisions_dir, fn)).read()))
        for i in DR_RE.findall(dr):
            if i not in known:
                fail(f"gated run cites {i}, not found in supplied "
                     "decision records")
    env = fields.get("Environment", "")
    if env:
        check_env(env)
    ti = fields.get("Test identity", "")
    if ti and not SHA_RE.search(ti):
        fail("Test identity must name the full head SHA alongside the "
             "verify command")


CHECKERS = {
    "batch-handoff": check_batch_handoff,
    "qc-verdict": check_qc_verdict,
    "review-findings": check_review_findings,
    "decision-record": check_decision_record,
    "delegation-record": check_delegation_record,
    "gated-run-evidence": check_gated_run_evidence,
}


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    path, atype = argv[1], argv[2]
    decisions_dir = None
    if "--decisions" in argv:
        decisions_dir = argv[argv.index("--decisions") + 1]
    if atype not in CHECKERS:
        print(f"unknown type {atype!r}; choose from {sorted(CHECKERS)}")
        return 2
    text = open(path).read()
    check_no_placeholders(text)
    CHECKERS[atype](text, decisions_dir)
    if VIOLATIONS:
        print(f"NONCONFORMANT ({len(VIOLATIONS)} violation(s)):")
        for v in VIOLATIONS:
            print(f"  - {v}")
        return 1
    print("CONFORMANT")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
