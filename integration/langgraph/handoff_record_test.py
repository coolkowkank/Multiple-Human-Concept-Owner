"""Offline tests for handoff_record.py: pure builder/validator plus real scratch git repos.
No provider, no network, no runtime/bus import. Nothing here is wired into the runtime."""
import json, os, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import handoff_record as H  # noqa: E402
ok = True
def check(n, c):
    global ok; ok = ok and bool(c); print(("PASS  " if c else "FAIL  ") + n, flush=True)
tmp = tempfile.mkdtemp()
ENV = dict(os.environ, HOME=tmp, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
def git(r, *a, inp=None):
    p = subprocess.run(["git", "-C", r, *a], capture_output=True, text=True, env=ENV, input=inp); return p.stdout.strip()
def head(r): return git(r, "rev-parse", "HEAD")
def mkrepo(name):
    r = os.path.join(tmp, name); os.makedirs(os.path.join(r, ".team")); git(r, "init", "-q")
    open(os.path.join(r, ".team", "STATE.json"), "w").write(json.dumps({"turn": "builder", "turn_seq": 1, "status": "running"}))
    open(os.path.join(r, ".team", "LOG.jsonl"), "w").write("")
    open(os.path.join(r, "keep.txt"), "w").write("keep\n"); open(os.path.join(r, "tool.sh"), "w").write("#!/bin/sh\n"); os.chmod(os.path.join(r, "tool.sh"), 0o755)
    git(r, "add", "-A"); git(r, "commit", "-qm", "base"); return r
def wf(r, rel, content):
    full = os.path.join(r, rel); os.makedirs(os.path.dirname(full), exist_ok=True); open(full, "w").write(content)
def finish(r, nxt, seq=2):
    """what the runtime does after verify: write STATE/LOG, then git add -A + commit"""
    open(os.path.join(r, ".team", "STATE.json"), "w").write(json.dumps({"turn": nxt, "turn_seq": seq, "status": "running"}))
    open(os.path.join(r, ".team", "LOG.jsonl"), "a").write('{"kind":"handoff"}\n')
    git(r, "add", "-A"); git(r, "commit", "-qm", f"TURN: handoff {seq}"); return head(r)
def obs_for(r, **kw):
    base = dict(seat="builder", turn_seq=2, base=head(r), next="reviewer", status="running", gate_opened=False, correction_rounds=0,
                declared_writes=[], observed=H.capture_worktree(r), preexisting_dirty=[],
                verify={"ran": True, "exit_code": 0, "sandboxed": True, "command": "python -m unittest", "tail": "OK\n1 test"},
                summary="did the thing", status_line="working")
    base.update(kw); return base
try:
    # ---- happy path on a real repo
    r = mkrepo("a"); b0 = head(r)
    pre = H.capture_worktree(r)
    check("clean repo: nothing observed", pre == [])
    wf(r, "src/a.py", "print(1)\n"); wf(r, "src/b.py", "x\n"); wf(r, "side_effect.log", "verify made this\n")
    os.remove(os.path.join(r, "keep.txt"))
    obs = H.capture_worktree(r)
    check("capture sees adds, deletes, untracked verify side effects; bus files excluded", {e["path"]: e["status"] for e in obs} == {"src/a.py": "A", "src/b.py": "A", "side_effect.log": "A", "keep.txt": "D"})
    rec, errs = H.build_record(obs_for(r, declared_writes=["src/a.py", "src/b.py"], observed=obs, preexisting_dirty=pre))
    check("build ok, record well formed", rec is not None and not errs and H.validate_record(rec) == [])
    f = rec["facts"]
    check("undeclared lists the verify side effect and the delete (observed but not declared)", f["undeclared"]["items"] == ["keep.txt", "side_effect.log"])
    check("verify facts: ran, exit 0, only hashes of command/tail", f["verify"]["ran"] and f["verify"]["exit_code"] == 0 and "python -m unittest" not in H.encode(rec).decode() and "1 test" not in H.encode(rec).decode())
    check("claims kept as len+sha256 only; summary text not in record", "did the thing" not in H.encode(rec).decode() and rec["claims"]["summary_len"] == 13)
    c = finish(r, "reviewer")
    res = H.check_commit(r, c, rec); check("check_commit: match (parent=base, changed files and blobs equal observation, STATE turn_seq/next)", res == {"status": "match", "problems": []})
    check("row_evidence record_ok for a matching row", H.row_evidence({"kind": "handoff", "seat": "builder", "turn_seq": 2, "record": rec})[0] == "record_ok")
    # reviewer turn
    rr, _ = H.build_record(obs_for(r, seat="reviewer", turn_seq=3, next="qc", observed=[]))
    check("pin_check passes for base == reviewed commit with its own verify", H.pin_check(c, rr) == [])
    check("pin_check refuses another commit", H.pin_check(b0, rr) != [])
    rr2, _ = H.build_record(obs_for(r, seat="reviewer", turn_seq=3, next="qc", observed=[], verify=None))
    check("pin_check refuses a reviewer record with no verify of its own", any("no verify" in x for x in H.pin_check(c, rr2)))
    check("pin_check refuses a short sha and invalid records", H.pin_check(c[:7], rr) != [] and H.pin_check(c, {"x": 1}) != [])

    # ---- check_commit mismatches
    r = mkrepo("m1"); wf(r, "a.txt", "1\n"); rec, _ = H.build_record(obs_for(r, declared_writes=["a.txt"]))
    wf(r, "a.txt", "tampered after capture\n"); c = finish(r, "reviewer")
    res = H.check_commit(r, c, rec); check("blob changed after the observation: mismatch", res["status"] == "mismatch" and any("differs from observation" in p for p in res["problems"]))
    r = mkrepo("m2"); wf(r, "a.txt", "1\n"); rec, _ = H.build_record(obs_for(r, declared_writes=["a.txt"]))
    wf(r, "extra.txt", "sneaked in between capture and commit\n"); c = finish(r, "reviewer")
    res = H.check_commit(r, c, rec); check("extra file committed that the runtime never observed: mismatch", res["status"] == "mismatch" and any("committed but not observed: extra.txt" in p for p in res["problems"]))
    r = mkrepo("m3"); wf(r, "a.txt", "1\n"); wf(r, "junk.txt", "j\n"); rec, _ = H.build_record(obs_for(r, declared_writes=["a.txt"]))
    os.remove(os.path.join(r, "junk.txt")); c = finish(r, "reviewer")
    res = H.check_commit(r, c, rec); check("observed file not in the commit: mismatch", res["status"] == "mismatch" and any("observed but not committed: junk.txt" in p for p in res["problems"]))
    r = mkrepo("m4"); wf(r, "a.txt", "1\n"); rec, _ = H.build_record(obs_for(r, declared_writes=["a.txt"])); c = finish(r, "reviewer")
    bad = json.loads(json.dumps(rec)); bad["facts"]["base"] = "0" * 40
    check("wrong base: mismatch", H.check_commit(r, c, bad)["status"] == "mismatch")
    check("STATE.json turn_seq/next not matching record: mismatch", H.check_commit(r, c, json.loads(json.dumps(dict(rec, facts=dict(rec["facts"], next="qc")))))["status"] == "mismatch")
    check("unknown commit: unverifiable, never match", H.check_commit(r, "1" * 40, rec)["status"] == "unverifiable")
    check("short or non-hex commit: unverifiable", H.check_commit(r, c[:8], rec)["status"] == "unverifiable" and H.check_commit(r, "zz" * 20, rec)["status"] == "unverifiable")
    check("invalid record: mismatch not match", H.check_commit(r, c, {"schema": "handoff/v1"})["status"] == "mismatch")
    r = mkrepo("m5"); git(r, "checkout", "-qb", "side"); wf(r, "s.txt", "s\n"); git(r, "add", "-A"); git(r, "commit", "-qm", "side"); git(r, "checkout", "-q", "-"); wf(r, "m.txt", "m\n"); git(r, "add", "-A"); git(r, "commit", "-qm", "main2")
    git(r, "merge", "-q", "--no-ff", "side", "-m", "merge"); rec, _ = H.build_record(obs_for(r, base=head(r) , observed=[]))
    check("merge commit (two parents): mismatch", H.check_commit(r, head(r), rec)["status"] == "mismatch")
    r = mkrepo("m6"); os.chmod(os.path.join(r, "tool.sh"), 0o644); wf(r, "n.txt", "n\n"); rec, _ = H.build_record(obs_for(r)); c = finish(r, "reviewer")
    check("mode change on a tracked file is observed and matches", any(e["path"] == "tool.sh" for e in rec["facts"]["observed"]["items"]) and H.check_commit(r, c, rec)["status"] == "match")
    r = mkrepo("m7"); os.symlink("keep.txt", os.path.join(r, "ln")); rec, _ = H.build_record(obs_for(r)); c = finish(r, "reviewer")
    check("symlink captured by link target, matches the commit", H.check_commit(r, c, rec)["status"] == "match" and [e["mode"] for e in rec["facts"]["observed"]["items"]] == ["120000"])
    r = mkrepo("m8"); open(os.path.join(r, ".gitignore"), "w").write("secret.out\n"); wf(r, "secret.out", "hidden\n"); obs = H.capture_worktree(r)
    check("gitignored file is not observed (stated limit)", [e["path"] for e in obs] == [".gitignore"] and any("gitignored" in x for x in H.EVIDENCE_LIMITS))
    r = mkrepo("m9"); wf(r, "bad\nname.txt", "x"); 
    try: H.capture_worktree(r); cap = False
    except H.CaptureRefused as e: cap = e.code == 'capture_unrepresentable'
    check("unrepresentable path (newline) refused by capture, not silently dropped", cap)
    r = mkrepo("m10"); sub = os.path.join(tmp, "subsrc"); os.makedirs(sub); git(sub, "init", "-q"); open(os.path.join(sub, "f"), "w").write("1"); git(sub, "add", "-A"); git(sub, "commit", "-qm", "s")
    git(r, "-c", "protocol.file.allow=always", "submodule", "add", "-q", sub, "vendor")
    try: H.capture_worktree(r); sm = False
    except H.CaptureRefused as e: sm = e.code == 'capture_unrepresentable'
    check("submodule (gitlink) refused by capture, not guessed", sm)
    rc = subprocess.run(["git", "-C", os.path.join(tmp, "nogit"), "status"], capture_output=True, env=ENV).returncode
    try: H.capture_worktree(os.path.join(tmp, "nogit")); ng = False
    except Exception: ng = True
    check("capture outside a repo refused", ng)
    r = mkrepo("ro"); wf(r, "z.txt", "z\n"); before = git(r, "status", "--porcelain"); objs = git(r, "count-objects", "-v"); idx = open(os.path.join(r, ".git", "index"), "rb").read()
    H.capture_worktree(r)
    check("capture is read-only: status, index bytes and object count unchanged (no -w, no add)", git(r, "status", "--porcelain") == before and objs == git(r, "count-objects", "-v") and idx == open(os.path.join(r, ".git", "index"), "rb").read())

    # ---- caps never truncate
    ents = [{"path": f"d/f{i:04d}.txt", "status": "A", "mode": "100644", "blob": f"{i:040x}"} for i in range(150)]
    rec, errs = H.build_record(obs_for(r, observed=ents, declared_writes=[e["path"] for e in ents]))
    o = rec["facts"]["observed"]
    check("150 observed files: digest-only form (listed false, count 150, no items, no truncation)", not errs and o["listed"] is False and o["count"] == 150 and "items" not in o and len(H.encode(rec)) <= H.MAX_RECORD_BYTES)
    check("digest-only record validates", H.validate_record(rec) == [])
    import hashlib
    check("digest equals sha256 over the FULL sorted canonical list", o["digest"] == hashlib.sha256(H._canon(sorted(ents, key=lambda e: e["path"])).encode()).hexdigest())
    # check_commit with a digest-only record against a real commit with many files
    r = mkrepo("big")
    for i in range(60): wf(r, f"many/f{i:03d}.txt", f"{i}\n")
    rec, errs = H.build_record(obs_for(r)); c = finish(r, "reviewer")
    check("60 real files: digest-only record, check_commit still verifies every file", rec["facts"]["observed"]["listed"] is False and H.check_commit(r, c, rec)["status"] == "match")
    r2 = mkrepo("big2")
    for i in range(60): wf(r2, f"many/f{i:03d}.txt", f"{i}\n")
    rec2, _ = H.build_record(obs_for(r2)); wf(r2, "many/f007.txt", "changed\n"); c2 = finish(r2, "reviewer")
    check("digest-only record: one file changed after capture is detected", H.check_commit(r2, c2, rec2)["status"] == "mismatch")
    ents = [{"path": "p/" + "x" * 480 + f"{i:04d}", "status": "A", "mode": "100644", "blob": f"{i:040x}"} for i in range(3)]
    rec, errs = H.build_record(obs_for(r, observed=ents, declared_writes=[e["path"] for e in ents], preexisting_dirty=[e["path"] for e in ents]))
    check("small list with long paths that would exceed 4KB inline falls back to digest-only, within the cap", not errs and len(H.encode(rec)) <= H.MAX_RECORD_BYTES and rec["facts"]["observed"]["listed"] is False)
    old_cap = H.MAX_RECORD_BYTES; H.MAX_RECORD_BYTES = 500
    try: rec_small, errs_small = H.build_record(obs_for(r))
    finally: H.MAX_RECORD_BYTES = old_cap
    check("a record that cannot fit even in digest form is refused (None + error), never truncated", rec_small is None and any("refusing instead of truncating" in e for e in errs_small))
    big_decl = [f"q/{i}" for i in range(2000)]
    rec, errs = H.build_record(obs_for(r, declared_writes=big_decl)); check("2000 declared writes: digest-only, still within the cap", not errs and rec["facts"]["declared_writes"]["count"] == 2000 and rec["facts"]["declared_writes"]["listed"] is False)

    # ---- build_record hostile input
    base_ok = obs_for(r)
    def bad(label, **kw):
        rec, errs = H.build_record(dict(base_ok, **kw)); check(f"build refuses: {label}", rec is None and errs)
    bad("short base", base=head(r)[:7]); bad("base not str", base=1); bad("seat with newline", seat="a\nb"); bad("turn_seq bool", turn_seq=True); bad("turn_seq negative", turn_seq=-1)
    bad("next with space", next="a b"); bad("status empty", status=""); bad("gate_opened int", gate_opened=1); bad("correction_rounds bool", correction_rounds=False)
    bad("declared path traversal", declared_writes=["../x"]); bad("declared absolute", declared_writes=["/etc/x"]); bad("declared dup", declared_writes=["a", "a"]); bad("declared .git", declared_writes=[".git/config"])
    bad("declared backslash", declared_writes=["a\\b"]); bad("declared control char", declared_writes=["a\x01b"]); bad("declared too long", declared_writes=["a" * 513])
    bad("observed bad status", observed=[{"path": "a", "status": "R", "mode": "100644", "blob": "0" * 40}]); bad("observed bad mode", observed=[{"path": "a", "status": "A", "mode": "160000", "blob": "0" * 40}])
    bad("observed blob not hex", observed=[{"path": "a", "status": "A", "mode": "100644", "blob": "xyz"}]); bad("observed D with blob", observed=[{"path": "a", "status": "D", "mode": "100644", "blob": "0" * 40}])
    bad("observed A without blob", observed=[{"path": "a", "status": "A", "mode": "100644", "blob": None}]); bad("observed extra key", observed=[{"path": "a", "status": "A", "mode": "100644", "blob": "0" * 40, "x": 1}])
    bad("observed duplicate path", observed=[{"path": "a", "status": "A", "mode": "100644", "blob": "0" * 40}] * 2)
    bad("observed includes a bus file", observed=[{"path": ".team/STATE.json", "status": "M", "mode": "100644", "blob": "0" * 40}])
    bad("preexisting not a list", preexisting_dirty="x"); bad("observation missing observed", observed=None)
    bad("verify exit_code bool", verify={"ran": True, "exit_code": True, "sandboxed": True, "command": "c", "tail": ""}); bad("verify exit_code float", verify={"ran": True, "exit_code": 0.0, "sandboxed": True, "command": "c", "tail": ""})
    bad("verify exit_code out of range", verify={"ran": True, "exit_code": 999, "sandboxed": True, "command": "c", "tail": ""}); bad("verify sandboxed missing", verify={"ran": True, "exit_code": 0, "command": "c", "tail": ""})
    bad("verify command not a string", verify={"ran": True, "exit_code": 0, "sandboxed": True, "command": 5, "tail": ""}); bad("verify ran not a bool", verify={"ran": 1})
    bad("summary not a string", summary=5)
    check("build refuses a non-dict observation", H.build_record("x")[0] is None and H.build_record(None)[0] is None)
    rec, _ = H.build_record(dict(base_ok, verify=None)); check("verify None: ran false, exit_code None (not 0)", rec["facts"]["verify"]["ran"] is False and rec["facts"]["verify"]["exit_code"] is None)
    rec, _ = H.build_record(dict(base_ok, verify={"ran": False, "exit_code": 0, "command": "x"})); check("verify ran=false: any exit_code ignored, stored as None", rec["facts"]["verify"]["exit_code"] is None)
    # claim flag heuristic
    rec, _ = H.build_record(dict(base_ok, verify=None, summary="all tests pass")); check("claim 'pass' with no verify run: flagged (heuristic)", rec["claims"]["flags"] == ["claims_pass_without_passing_verify"] and "heuristic" in rec["claims"]["flags_basis"])
    rec, _ = H.build_record(dict(base_ok, verify={"ran": True, "exit_code": 1, "sandboxed": True, "command": "c", "tail": ""}, status_line="green")); check("claim 'green' with failing verify: flagged", rec["claims"]["flags"] != [])
    rec, _ = H.build_record(dict(base_ok, summary="all tests pass")); check("claim 'pass' with exit 0: no flag; flag never changes facts", rec["claims"]["flags"] == [])
    r_a, _ = H.build_record(dict(base_ok, summary="all tests pass", verify=None)); r_b, _ = H.build_record(dict(base_ok, summary="boring", verify=None))
    check("claims never leak into facts (facts identical whatever the model wrote)", r_a["facts"] == r_b["facts"])

    # ---- validate_record tamper
    rec, _ = H.build_record(obs_for(r, declared_writes=["a.txt"], observed=[{"path": "a.txt", "status": "A", "mode": "100644", "blob": "a" * 40}]))
    def tamper(label, fn):
        t = json.loads(json.dumps(rec)); fn(t); check(f"validate rejects: {label}", H.validate_record(t) != [])
    tamper("extra top-level key", lambda t: t.update(x=1)); tamper("extra facts key", lambda t: t["facts"].update(head="0" * 40)); tamper("missing claims", lambda t: t.pop("claims"))
    tamper("evidence_limits removed", lambda t: t.update(evidence_limits=[])); tamper("evidence_limits edited", lambda t: t["evidence_limits"].__setitem__(0, "all good"))
    tamper("listed items edited, digest stale", lambda t: t["facts"]["observed"]["items"][0].__setitem__("blob", "b" * 40))
    tamper("count lies", lambda t: t["facts"]["observed"].__setitem__("count", 2)); tamper("items present while listed=false", lambda t: t["facts"]["observed"].update(listed=False))
    tamper("digest not hex", lambda t: t["facts"]["observed"].__setitem__("digest", "zz")); tamper("verify fields set while ran=false", lambda t: t["facts"]["verify"].update(ran=False))
    tamper("schema renamed", lambda t: t.update(schema="handoff/v2")); tamper("flags unknown value", lambda t: t["claims"].update(flags=["trust_me"]))
    tamper("claims extra raw text key", lambda t: t["claims"].update(summary="raw text")); tamper("turn_seq bool", lambda t: t["facts"].update(turn_seq=True))
    tamper("oversize padding", lambda t: t["claims"].update(flags_basis="x" * 5000))
    check("validate handles junk input without raising", all(H.validate_record(x) for x in (None, 1, "s", [], {}, {"schema": "handoff/v1"})))

    # ---- row_evidence
    check("row with no record: no_record, never record_ok", H.row_evidence({"kind": "handoff", "seat": "builder", "turn_seq": 2})[0] == "no_record" and H.row_evidence({"kind": "handoff", "record": None})[0] == "no_record")
    check("row with a corrupted record: invalid_record", H.row_evidence({"kind": "handoff", "seat": "builder", "record": {"schema": "handoff/v1"}})[0] == "invalid_record")
    rec, _ = H.build_record(obs_for(r))
    check("row whose seat or turn_seq differs from the record: invalid_record", H.row_evidence({"kind": "handoff", "seat": "qc", "turn_seq": 2, "record": rec})[0] == "invalid_record" and H.row_evidence({"kind": "handoff", "seat": "builder", "turn_seq": 9, "record": rec})[0] == "invalid_record")
    check("non-handoff row / junk: invalid_record, no raise", H.row_evidence({"kind": "error"})[0] == "invalid_record" and H.row_evidence(None)[0] == "invalid_record" and H.row_evidence("x")[0] == "invalid_record")
    check("record text carries no raw command, output, summary or prompt (privacy)", all(x not in H.encode(rec).decode() for x in ("python -m unittest", "did the thing", "OK\n")))

    # ---- bounded capture, no_record surface, gate files
    r = mkrepo("cap1")
    for i in range(H.MAX_ENTRIES + 1): wf(r, f"many/f{i}.txt", "x")
    calls = []; orig = H._git
    H._git = lambda *a, **k: (calls.append(a), orig(*a, **k))[1]
    st, code = H.safe_capture(r); H._git = orig
    check("over MAX_ENTRIES: refused as no_record/capture_too_many_entries before any hashing", (st, code) == ("no_record", "capture_too_many_entries") and not any(c[1] == "hash-object" for c in calls))
    r = mkrepo("cap2")
    for i in range(H.MAX_ENTRIES): wf(r, f"many/f{i}.txt", str(i))
    calls = []; H._git = lambda *a, **k: (calls.append(a), orig(*a, **k))[1]
    st, ents = H.safe_capture(r); H._git = orig
    check("exactly MAX_ENTRIES: ok with ONE hash-object subprocess, all blobs match git", st == "ok" and len(ents) == H.MAX_ENTRIES and sum(1 for c in calls if c[1] == "hash-object") == 1
          and all(e["blob"] == git(r, "hash-object", "--", e["path"]) for e in ents[:5]))
    r = mkrepo("cap3"); wf(r, "big.bin", "x"); H.MAX_FILE_BYTES, old = 0, H.MAX_FILE_BYTES
    try: st, code = H.safe_capture(r)
    finally: H.MAX_FILE_BYTES = old
    check("file over MAX_FILE_BYTES: no_record/capture_file_too_large", (st, code) == ("no_record", "capture_file_too_large"))
    r = mkrepo("cap4"); wf(r, "bad\nname", "x"); os.symlink("keep.txt", os.path.join(r, "ln"))
    st, code = H.safe_capture(r)
    check("unrepresentable path: no_record code, no partial facts", (st, code) == ("no_record", "capture_unrepresentable"))
    check("safe_capture on a non-repo never raises and gives a fixed code", H.safe_capture(os.path.join(tmp, "nogit"))[0] == "no_record" and H.safe_capture(os.path.join(tmp, "nogit"))[1] in H.ERROR_CODES)
    st, code = H.safe_build({"seat": "x/../\n secret"})
    check("safe_build bad input: fixed code only, no input text leaks", (st, code) == ("no_record", "build_invalid") and "secret" not in code)
    row = {"kind": "handoff", "seat": "builder", "turn_seq": 2, **H.no_record_fields("capture_too_many_entries")}
    ev = H.row_evidence(row)
    check("no_record row with record_error is no_record, never record_ok", ev[0] == "no_record" and "capture_too_many_entries" in ev[1][0])
    check("unknown/hostile record_error is replaced by a fixed code", H.no_record_fields("/etc/passwd rm -rf")["record_error"] == "capture_error")
    r = mkrepo("gate"); wf(r, ".team/gates/g1.json", "{}"); wf(r, "a.txt", "a")
    st, ents = H.safe_capture(r); rec, _ = H.build_record(obs_for(r, observed=ents, declared_writes=["a.txt"]))
    check("gate file under .team/ is observed and undeclared, not excluded", st == "ok" and ".team/gates/g1.json" in [e["path"] for e in rec["facts"]["observed"]["items"]] and rec["facts"]["undeclared"]["items"] == [".team/gates/g1.json"])
    r = mkrepo("sl"); os.symlink("keep.txt", os.path.join(r, "ln")); ents = H.capture_worktree(r)
    check("in-process symlink blob equals git hash-object", ents[0]["blob"] == git(r, "hash-object", "--stdin", inp="keep.txt"))
    r = mkrepo("q1"); wf(r, "a.txt", "AAA"); wf(r, '"a.txt"', "QQQ")
    check("leading-quote file with same-named sibling: refused, never a wrong blob", H.safe_capture(r) == ("no_record", "capture_unrepresentable"))
    r = mkrepo("q2"); wf(r, '"a.txt"', "QQQ")
    check("leading-quote file alone: refused as capture_unrepresentable", H.safe_capture(r) == ("no_record", "capture_unrepresentable"))
    r = mkrepo("q3"); wf(r, 'a"b.txt', "1"); wf(r, "my file.txt", "2"); wf(r, "-dash.txt", "3"); ents = H.capture_worktree(r)
    check("embedded quote, space, leading dash still captured with git's blobs", len(ents) == 3 and all(e["blob"] == git(r, "hash-object", "--", e["path"]) for e in ents))
    check("module is pure: no import from launcher/runtime/bus", not any(l.startswith(("from launcher", "import launcher", "from .", "import runtime", "import langgraph")) for l in open(os.path.join(HERE, "handoff_record.py"))))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nHANDOFF RECORD:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
raise SystemExit(0 if ok else 1)
