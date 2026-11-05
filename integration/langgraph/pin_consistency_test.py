"""Tests for the opt-in pin_consistency REPORT in done_gate (not an acceptance gate).
Stdlib only; real scratch git repos; records built with handoff_record from the real
worktree capture, the way a seat turn does. Run: python3 pin_consistency_test.py"""
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import done_gate as dg          # noqa: E402
import handoff_record as hr     # noqa: E402

ok = True
def check(name, cond):
    global ok; ok = ok and bool(cond); print(("PASS  " if cond else "FAIL  ") + name, flush=True)

def git(r, *a):
    p = subprocess.run(["git", "-C", r, *a], capture_output=True, text=True)
    return p.stdout.strip()

def head(r): return git(r, "rev-parse", "HEAD")

def mk_repo(tmp, name):
    r = os.path.join(tmp, name); os.makedirs(os.path.join(r, ".team")); os.makedirs(os.path.join(r, "src"))
    subprocess.run(["git", "init", "-q", "-b", "team-work", r], check=True)
    git(r, "config", "user.name", "t"); git(r, "config", "user.email", "t@x")
    json.dump({"turn": "builder", "turn_seq": 0, "status": "running"}, open(os.path.join(r, ".team/STATE.json"), "w"))
    open(os.path.join(r, ".team/LOG.jsonl"), "w").write("")
    open(os.path.join(r, "src/art.py"), "w").write("VALUE = 1\n")
    git(r, "add", "-A"); git(r, "commit", "-qm", "operator: init")
    return r

def turn(r, seat, seq, nxt, writes, *, record=True, verify=True, extra_after_capture=None, base=None, subject=None):
    """One seat turn the way the runtime does it: write, capture the worktree, build the record from the
    capture, append the LOG row, write STATE, commit with the TURN subject."""
    b = head(r) if base is None else base
    for p, c in writes.items():
        os.makedirs(os.path.dirname(os.path.join(r, p)) or r, exist_ok=True); open(os.path.join(r, p), "w").write(c)
    status, entries = hr.safe_capture(r)
    assert status == "ok", entries
    obs = {"seat": seat, "turn_seq": seq, "base": b, "next": nxt, "status": "running", "gate_opened": False, "correction_rounds": 0,
           "declared_writes": sorted(writes), "observed": entries, "preexisting_dirty": [],
           "verify": {"ran": True, "exit_code": 0, "sandboxed": False, "command": "python3 x.py", "tail": "ok"} if verify else None,
           "summary": "s", "status_line": "line"}
    row = {"ts": "2026-01-01T00:00:00Z", "seat": seat, "kind": "handoff", "body": "b", "turn_seq": seq}
    if record:
        st, rec = hr.safe_build(obs); assert st == "ok", rec
        row["record"] = rec
    else:
        row.update(hr.no_record_fields("capture_error"))
    if extra_after_capture:
        for p, c in extra_after_capture.items(): open(os.path.join(r, p), "w").write(c)
    with open(os.path.join(r, ".team/LOG.jsonl"), "a") as fh: fh.write(json.dumps(row, sort_keys=True) + "\n")
    json.dump({"turn": nxt, "turn_seq": seq, "status": "running"}, open(os.path.join(r, ".team/STATE.json"), "w"))
    git(r, "add", "-A"); git(r, "commit", "-qm", subject or ("TURN: %s acting" % seat))
    return head(r)

def scenario(tmp, name, **kw):
    """builder -> reviewer -> coordinator; returns (repo, reviewed_commit, reviewer_commit)."""
    r = mk_repo(tmp, name)
    reviewed = turn(r, "builder", 1, "reviewer", {"src/art.py": "VALUE = 2\n"})
    rev = turn(r, "reviewer", 2, "coordinator", kw.get("reviewer_writes", {"review/verdict-1.md": "my own verdict\n"}), **kw.get("reviewer_kw", {}))
    turn(r, "coordinator", 3, None, {".team/NOTE.md": "n\n"})
    return r, reviewed, rev

CFG = lambda reviewed, **o: dict({"reviewed_commit": reviewed, "reviewer_seats": ["reviewer"], "verdict_path": "review/verdict-1.md"}, **o)
ART = ["src/art.py"]
def run(r, cfg, art=ART): return dg.pin_consistency(r, "team-work", cfg, art)
def reasons(res): return " | ".join(res.get("reasons", []))

def naive(r, cfg, art=ART):
    """A naive implementation: reads the WORKTREE log, accepts any reviewer handoff row that has a record."""
    rows = [json.loads(l) for l in open(os.path.join(r, ".team/LOG.jsonl")) if l.strip()]
    return any(x.get("seat") in cfg["reviewer_seats"] and x.get("record") for x in rows)

tmp = tempfile.mkdtemp()
# ---- happy path
r, rv, rc = scenario(tmp, "happy")
res = run(r, CFG(rv))
check("happy: pinned, with the reviewer commit, seat and verdict blob recorded", res["status"] == "pinned" and res["reviewer_commit"] == rc and res["reviewer_seat"] == "reviewer" and res.get("verdict_blob"))
check("happy: the report says it is not acceptance", res["not_acceptance"] is True and "not an acceptance gate" in res["note"] and "verdict text was not read" in res["note"])
check("happy: reasons empty and schema named", res["reasons"] == [] and res["schema"] == "pin-consistency/v1")

# ---- negatives (each: real says not_pinned/unverifiable; naive implementation would say pinned)
r, rv, _ = scenario(tmp, "norec", reviewer_kw={"record": False})
res = run(r, CFG(rv)); check("no_record: not_pinned, reason names no_record", res["status"] == "not_pinned" and "no_record" in reasons(res))
r, rv, _ = scenario(tmp, "seat")
res = run(r, dict(CFG(rv), reviewer_seats=["qc"])); check("wrong seat: not_pinned (no configured reviewer turn on the reviewed commit)", res["status"] == "not_pinned" and "no configured reviewer turn" in reasons(res))
r, rv, _ = scenario(tmp, "early")
early = git(r, "rev-list", "--max-parents=0", "HEAD").splitlines()[0]
res = run(r, CFG(early)); check("reviewed commit is an older commit (reviewer record base != it): not_pinned", res["status"] == "not_pinned")
# commit lands between the reviewed commit and the reviewer turn
r = mk_repo(tmp, "between")
rv = turn(r, "builder", 1, "reviewer", {"src/art.py": "VALUE = 2\n"})
turn(r, "builder", 2, "reviewer", {"src/other.py": "x = 1\n"})
turn(r, "reviewer", 3, "coordinator", {"review/verdict-1.md": "v\n"})
res = run(r, CFG(rv)); check("a commit landed between the reviewed commit and the review: not_pinned", res["status"] == "not_pinned")
# forged record base: the reviewer record claims another base than its commit's parent
r = mk_repo(tmp, "forgedbase")
rv = turn(r, "builder", 1, "reviewer", {"src/art.py": "VALUE = 2\n"})
turn(r, "reviewer", 2, "coordinator", {"review/verdict-1.md": "v\n"}, base=git(r, "rev-list", "--max-parents=0", "HEAD").splitlines()[0])
res = run(r, CFG(rv)); check("record base differs from the reviewer commit's parent: not_pinned (pin_check/check_commit)", res["status"] == "not_pinned" and ("pin_check" in reasons(res) or "check_commit" in reasons(res)))
# artifact changed after the review
r, rv, _ = scenario(tmp, "artchange")
turn(r, "coordinator", 4, None, {"src/art.py": "VALUE = 3\n"})
res = run(r, CFG(rv)); check("artifact blob changed after the reviewed commit: not_pinned", res["status"] == "not_pinned" and "artifact changed" in reasons(res))
check("   a naive reader of reviewer rows would say pinned here", naive(r, CFG(rv)) is True)
# verdict path not observed
r, rv, _ = scenario(tmp, "noverdict")
res = run(r, CFG(rv, verdict_path="review/other.md")); check("verdict_path not added or modified in the reviewer turn: not_pinned", res["status"] == "not_pinned" and "verdict_path" in reasons(res))
check("   a naive reader of reviewer rows would say pinned here", naive(r, CFG(rv)) is True)
# reviewer turn that did not run its own verify
r, rv, _ = scenario(tmp, "noverify", reviewer_kw={"verify": False})
res = run(r, CFG(rv)); check("reviewer record without its own verify run: not_pinned", res["status"] == "not_pinned" and "verify" in reasons(res))
# short hex, uppercase, unknown, non-ancestor
r, rv, _ = scenario(tmp, "hex")
check("short hex: unverifiable", run(r, CFG(rv[:12]))["status"] == "unverifiable")
check("uppercase hex: unverifiable", run(r, CFG(rv.upper()))["status"] == "unverifiable")
check("unknown commit: unverifiable", run(r, CFG("0" * 40))["status"] == "unverifiable")
git(r, "checkout", "-q", "-b", "side", early if False else rv); open(os.path.join(r, "side.txt"), "w").write("s"); git(r, "add", "-A"); git(r, "commit", "-qm", "side commit"); side = head(r); git(r, "checkout", "-q", "team-work")
res = run(r, CFG(side)); check("commit not an ancestor of HEAD: not_pinned", res["status"] == "not_pinned" and "ancestor" in reasons(res))
# bad cfg shapes
for nm, bad in (("extra key", dict(CFG(rv), approve=True)), ("no seats", dict(CFG(rv), reviewer_seats=[])), ("abs verdict", dict(CFG(rv), verdict_path="/etc/x")), ("verdict under .team", dict(CFG(rv), verdict_path=".team/v.md")), ("not a dict", "x")):
    check("bad pin_check (%s): unverifiable" % nm, run(r, bad)["status"] == "unverifiable")
check("empty artifact_paths: unverifiable", run(r, CFG(rv), [])["status"] == "unverifiable")
# verdict file replaced or deleted after the review
r, rv, _ = scenario(tmp, "vreplace")
turn(r, "coordinator", 4, None, {"review/verdict-1.md": "someone else's text\n"})
res = run(r, CFG(rv)); check("verdict file replaced after the review: not_pinned", res["status"] == "not_pinned" and "differs" in reasons(res))
r, rv, _ = scenario(tmp, "vdelete")
git(r, "rm", "-q", "review/verdict-1.md"); git(r, "commit", "-qm", "remove verdict")
res = run(r, CFG(rv)); check("verdict file deleted after the review: not_pinned", res["status"] == "not_pinned" and "missing at HEAD" in reasons(res))
# handoff_record cannot be imported: report unverifiable, never raise
r, rv, _ = scenario(tmp, "noimport")
sys.modules["handoff_record"] = None
try:
    res = run(r, CFG(rv))
finally:
    sys.modules["handoff_record"] = hr
check("handoff_record import failure: unverifiable, no raise", res["status"] == "unverifiable")
# worktree LOG tampering: committed LOG wins, both directions
r, rv, _ = scenario(tmp, "tamper")
open(os.path.join(r, ".team/LOG.jsonl"), "w").write("")
check("worktree LOG emptied: still pinned (committed LOG at HEAD is read)", run(r, CFG(rv))["status"] == "pinned")
r, rv, _ = scenario(tmp, "forge", reviewer_kw={"record": False})
rows = [json.loads(l) for l in open(os.path.join(r, ".team/LOG.jsonl")) if l.strip()]
good_r, good_rv, _ = scenario(tmp, "donor")
donor = [json.loads(l) for l in open(os.path.join(good_r, ".team/LOG.jsonl")) if l.strip() and json.loads(l).get("seat") == "reviewer"][0]
with open(os.path.join(r, ".team/LOG.jsonl"), "a") as fh: fh.write(json.dumps(donor) + "\n")
check("a forged reviewer record appended to the WORKTREE log only: still not_pinned", run(r, CFG(rv))["status"] == "not_pinned")
check("   a naive worktree-log reader would say pinned here", naive(r, CFG(rv)) is True)
# check_commit mismatch: a file in the reviewer commit that the observation did not see
r, rv, _ = scenario(tmp, "mismatch", reviewer_kw={"extra_after_capture": {"review/sneak.md": "x\n"}})
res = run(r, CFG(rv)); check("reviewer commit holds a path the record did not observe: not_pinned via check_commit", res["status"] == "not_pinned" and "check_commit" in reasons(res))
check("   a naive reader of reviewer rows would say pinned here", naive(r, CFG(rv)) is True)
# HEAD must be on the expected branch
r, rv, _ = scenario(tmp, "branch")
check("wrong branch: unverifiable", dg.pin_consistency(r, "other-branch", CFG(rv), ART)["status"] == "unverifiable")

# ---- finalize: default unchanged, pin never alters the quality verdict
cfgdir = tempfile.mkdtemp(); os.chmod(cfgdir, 0o700)
def write_cfg(d):
    p = os.path.join(cfgdir, "c.json"); open(p, "w").write(json.dumps(d)); os.chmod(p, 0o600); return p
r, rv, _ = scenario(tmp, "fin")
base_cfg = {"checker_script": "/nonexistent", "checker_id": "x", "artifact_paths": ART, "key_file": "/nonexistent", "record_dir": "/nonexistent"}
core = dg._finalize_core(r, "team-work", write_cfg(base_cfg))
check("finalize without pin_check returns exactly the core result (default unchanged)", dg.finalize(r, "team-work", write_cfg(base_cfg)) == core)
check("finalize with no config returns the core result", dg.finalize(r, "team-work", None) == dg._finalize_core(r, "team-work", None))
withpin = dg.finalize(r, "team-work", write_cfg(dict(base_cfg, pin_check=CFG(rv))))
check("finalize with pin_check adds ONLY the pin_consistency key", set(withpin) - set(core) == {"pin_consistency"} and {k: v for k, v in withpin.items() if k != "pin_consistency"} == core)
check("pin_consistency never changes terminal_done, closeout_allowed or the label", withpin["terminal_done"] is False and withpin["closeout_allowed"] is False and withpin["label"] == core["label"] and withpin["pin_consistency"]["status"] == "pinned")
bad = dg.finalize(r, "team-work", write_cfg(dict(base_cfg, pin_check={"reviewed_commit": "x"})))
check("a bad pin_check yields an unverifiable report and still the core quality fields", bad["pin_consistency"]["status"] == "unverifiable" and bad["closeout_allowed"] is False)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
