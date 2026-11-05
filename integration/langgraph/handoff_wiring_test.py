"""Offline: handoff/v1 record wired into the seat turn (additive LOG key).
Real git lanes, no provider, no model. bus.transact has NO rollback: a
record failure must degrade to an explicit no_record and never raise,
retry or replay."""
import os as _os; _os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import json, os, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import langgraph_team as lt  # noqa: E402
import handoff_record as hr  # noqa: E402
from launcher import prompts, prompt_audit, runtime  # noqa: E402
from launcher.bus import Bus, BusError  # noqa: E402
from launcher.runtime import Seat, SeatError, prompt_log_tail  # noqa: E402
ok = True
def check(n, c):
    global ok; ok = ok and bool(c); print(("PASS  " if c else "FAIL  ") + n, flush=True)
def git(r, *a): return subprocess.run(["git", "-C", r, *a], capture_output=True, text=True).stdout.strip()
def plant_qc_pass(b, r):
    """Reviewer-skip guard (2026-11-05): DONE needs a fresh QC PASS verdict."""
    head = git(r, "rev-parse", "HEAD").strip()
    b.append_log("qc", "verdict", "verdict PASS at head " + head + ": planted")
    b.commit_all("human: plant QC verdict")
def turn(tmp, name, resp, pre=None, patch=None, push_fail_once=False, plant=False):
    r = os.path.join(tmp, name); lt.init_repo(r)
    if pre:
        for p, c in pre.items(): os.makedirs(os.path.dirname(os.path.join(r, p)), exist_ok=True); open(os.path.join(r, p), "w").write(c)
    b = Bus(r, lt.BRANCH)
    if plant: plant_qc_pass(b, r)
    s = Seat(b, "coordinator", instance_id="A"); s.adapter.consume = lambda: None
    calls = {"n": 0}
    def call(state): calls["n"] += 1; return dict(resp)
    s._call_adapter = call
    if push_fail_once:
        real = {"n": 0}
        def push():
            real["n"] += 1
            if real["n"] == 1: raise BusError("lost race")
        b.push = push; b._confirm_landed = lambda: real["n"] > 1
        b.has_remote = lambda: True; b.pull = lambda: None
    base = git(r, "rev-parse", "HEAD")
    err = None
    if patch: patch()
    try: s.act_once()
    except Exception as e: err = repr(e)
    return r, b, err, calls["n"], base
def last_handoff(b): return [e for e in b.log() if e.get("kind") == "handoff"][-1]
tmp = tempfile.mkdtemp()
try:
    W = {".team/NOTE.md": "n\n"}
    rsp = {"summary": "did x", "writes": W, "verify_command": None, "handoff": "builder", "status_line": "handing over"}
    r, b, err, n, base = turn(tmp, "a", rsp)
    row = last_handoff(b); rec = row.get("record"); head = git(r, "rev-parse", "HEAD")
    check("normal turn: row carries a handoff/v1 record and no record_error", err is None and rec and rec["schema"] == "handoff/v1" and "record_error" not in row)
    check("row_evidence record_ok", hr.row_evidence(row)[0] == "record_ok")
    check("check_commit matches the REAL commit (base, observed files, STATE turn_seq and next)", hr.check_commit(r, head, rec)["status"] == "match")
    check("record base is this attempt's parent; turn_seq equals row and STATE; next equals STATE turn", rec["facts"]["base"] == base == git(r, "rev-parse", "HEAD~1") and rec["facts"]["turn_seq"] == row["turn_seq"] == b.state()["turn_seq"] and rec["facts"]["next"] == b.state()["turn"] == "builder")
    check("declared write observed and not undeclared; bus files excluded", [e["path"] for e in rec["facts"]["observed"]["items"]] == [".team/NOTE.md"] and rec["facts"]["undeclared"]["count"] == 0)
    check("claims are length+hash only: summary text is not in the record", "did x" not in json.dumps(rec) and rec["claims"]["summary_len"] == 5)
    # DONE
    r, b, err, n, base = turn(tmp, "d", dict(rsp, handoff=None, status_line="DONE - closed"), plant=True)
    row = last_handoff(b); rec = row["record"]
    check("DONE turn: record next None, status done, STATE turn None, check_commit match", rec["facts"]["next"] is None and rec["facts"]["status"] == "done" and b.state()["turn"] is None and hr.check_commit(r, git(r, "rev-parse", "HEAD"), rec)["status"] == "match")
    # gate
    r, b, err, n, base = turn(tmp, "g", dict(rsp, gate={"question": "ok?", "options": ["y"], "recommendation": "y"}))
    rec = last_handoff(b)["record"]; paths = [e["path"] for e in rec["facts"]["observed"]["items"]]
    check("gate turn: gate file is an ordinary observed AND undeclared path (not excluded); check_commit match", rec["facts"]["gate_opened"] is True and ".team/gates/PENDING.jsonl" in paths and ".team/gates/PENDING.jsonl" in rec["facts"]["undeclared"]["items"] and hr.check_commit(r, git(r, "rev-parse", "HEAD"), rec)["status"] == "match")
    # pre-existing dirt reported
    r, b, err, n, base = turn(tmp, "p", rsp, pre={".team/pre.txt": "dirty\n"})
    rec = last_handoff(b)["record"]
    check("pre-existing in-domain dirt is reported as preexisting_dirty and the record still matches the commit", rec["facts"]["preexisting_dirty"]["items"] == [".team/pre.txt"] and hr.check_commit(r, git(r, "rev-parse", "HEAD"), rec)["status"] == "match")
    # verify run facts
    r, b, err, n, base = turn(tmp, "v", dict(rsp, writes={".team/chk.py": "pass\n"}, verify_command="python3 .team/chk.py"))
    row = last_handoff(b); v = (row.get("record") or {}).get("facts", {}).get("verify", {})
    check("verify turn: ran, exit 0, sandboxed flag, only hashes of command/tail (no command text)", err is None and v.get("ran") is True and v.get("exit_code") == 0 and v.get("sandboxed") is True and "python3" not in json.dumps(row["record"]["facts"]["verify"]) and v.get("command_len") == len("python3 .team/chk.py"))
    # no_record: capture failure, over-cap, never raises/replays
    def boom_patch():
        hr.capture_worktree = lambda repo: (_ for _ in ()).throw(RuntimeError("SECRETPATH /home/x"))
    real_cap = hr.capture_worktree
    r, b, err, n, base = turn(tmp, "f", rsp, patch=boom_patch)
    hr.capture_worktree = real_cap
    row = last_handoff(b)
    check("capture failure: turn still taken (commit, turn moved), ONE adapter call, no raise", err is None and n == 1 and b.state()["turn"] == "builder" and git(r, "rev-parse", "HEAD") != base)
    check("row has record None + fixed code, no raw error text; row_evidence is no_record (never evidence)", row["record"] is None and row["record_error"] == "capture_error" and "SECRET" not in json.dumps(row) and hr.row_evidence(row)[0] == "no_record")
    many = {f".team/m/{i}.txt": "x" for i in range(hr.MAX_ENTRIES + 1)}
    r, b, err, n, base = turn(tmp, "m", dict(rsp, writes=many))
    row = last_handoff(b)
    check("over-cap change set: explicit no_record capture_too_many_entries, turn proceeds, one call", err is None and n == 1 and row["record"] is None and row["record_error"] == "capture_too_many_entries" and b.state()["turn"] == "builder")
    # push retry provenance: record is rebuilt per attempt; final commit matches its own record
    r, b, err, n, base = turn(tmp, "r", rsp, push_fail_once=True)
    row = last_handoff(b); rec = row.get("record")
    rows = [e for e in b.log() if e.get("kind") == "handoff"]
    check("lost-push retry: the replay is documented (2 adapter calls), exactly one handoff row survives, record matches the FINAL commit", err is None and n == 2 and len(rows) == 1 and rec and hr.check_commit(r, git(r, "rev-parse", "HEAD"), rec)["status"] == "match" and rec["facts"]["base"] == base)
    # prompt / audit hash invariance: extra row keys never render
    rowa = {"ts": "t", "seat": "coordinator", "kind": "handoff", "body": "b", "turn_seq": 3}
    rowb = dict(rowa, record={"schema": "handoff/v1", "facts": {"x": "SECRETMARK"}}, record_error="capture_error")
    st = {"turn_seq": 3, "status_line": "s", "turn": "builder", "status": "running"}
    ta = prompts.task_prompt("builder", "builder", "brief", st, [rowa]); tb = prompts.task_prompt("builder", "builder", "brief", st, [rowb])
    check("task prompt is byte-identical with or without the record keys", ta == tb and "SECRETMARK" not in tb)
    ra = prompt_audit.render_audited_prompt("builder", "builder", "brief", st, [rowa]); rb = prompt_audit.render_audited_prompt("builder", "builder", "brief", st, [rowb])
    check("audited prompt render is identical with or without the record keys", ra == rb)
    r, b, err, n, base = turn(tmp, "t", rsp)
    check("the real log tail holds the record as a key, but the real prompt never renders it", "record" in last_handoff(b) and "handoff/v1" not in Seat(b, "builder", instance_id="B").build_prompt(b.state())[1])
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nHANDOFF WIRING:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
raise SystemExit(0 if ok else 1)
