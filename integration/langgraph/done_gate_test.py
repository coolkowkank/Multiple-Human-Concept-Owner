"""Offline: operator-side DONE hook. The test plays the operator with an
EPHEMERAL key and FAKE test-signed results (no private checker, no provider).
Proves: only signed, hash-bound, checker-pinned external evidence on a
cycle-complete bus gives terminal_done; everything else stays unproven/failed."""
import json, os, secrets, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import langgraph_team as lt
from launcher.bus import Bus
from launcher.quality_gate import sign_operator, artifact_sha256, HASH_SCHEME
import done_gate

ok = True
def check(n, c):
    global ok; ok = ok and bool(c); print(("PASS  " if c else "FAIL  ") + n, flush=True)

tmp = tempfile.mkdtemp()
KEY = secrets.token_bytes(32); CHK = "c" * 64
def git(repo, *a): return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
def mk(status):
    repo = tempfile.mkdtemp(dir=tmp); lt.init_repo(repo)
    os.makedirs(repo + "/src"); open(repo + "/src/app.py", "w").write("def add(a, b):\n    return a + b\n")
    git(repo, "add", "-A"); git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "operator: art")
    if status == "done":
        b = Bus(repo, lt.BRANCH); st = b.state(); st["status"] = "done"; st["turn"] = None; b.write_state(st)
        git(repo, "add", "-A"); git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "operator: done")
    return repo
PATHS = ["src/app.py"]
def res(repo, **kw):
    _, sha = done_gate.current_artifact(repo, PATHS)
    p = {"hash_scheme": HASH_SCHEME, "artifact_sha256": sha, "accepted": True,
         "state": "accepted", "checker_id": CHK}; p.update(kw)
    return sign_operator(KEY, p)
def close(repo, signed, key=KEY, chk=CHK, name="rec.json"):
    return done_gate.operator_close(repo, lt.BRANCH, PATHS, signed, operator_key=key,
                                    expected_operator_checker_id=chk,
                                    record_path=os.path.join(tmp, name + secrets.token_hex(3)))

r = close(mk("done"), None)
check("no evidence -> not terminal, operator_terminal_check_passed false", not r["terminal_done"] and not r["operator_terminal_check_passed"] and r["cycle_complete"])
repo = mk("done"); r = close(repo, res(repo))
check("signed accept on cycle-complete bus -> terminal_done, operator_terminal_check_passed true",
      r["terminal_done"] and r["operator_terminal_check_passed"] and r["quality"] == "operator_check_passed")
check("record has hash, paths, head, no key", r["artifact_sha256"] and r["artifact_paths"] == PATHS
      and r["head"] and KEY.hex() not in json.dumps(r))
repo = mk("running"); r = close(repo, res(repo))
check("cycle not complete (bus running) -> not terminal even with valid evidence", not r["terminal_done"] and not r["operator_terminal_check_passed"])
repo = mk("done"); s = res(repo); r = close(repo, s, key=secrets.token_bytes(32))
check("wrong key -> unproven", not r["terminal_done"] and r["quality"] == "unproven")
repo = mk("done"); s = res(repo); s["payload"]["accepted"] = True; s["payload"]["artifact_sha256"] = "0" * 64
check("tampered payload after signing -> unproven", not close(repo, s)["terminal_done"])
repo = mk("done"); s = res(repo)
open(repo + "/src/app.py", "w").write("def add(a, b):\n    return 5\n")
git(repo, "add", "-A"); git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "operator: changed")
check("stale: artifact changed after evidence was signed -> unproven", not close(repo, s)["terminal_done"])
repo = mk("done"); open(repo + "/src/app.py", "w").write("def add(a, b):\n    return 5\n")
r = close(repo, res_ := sign_operator(KEY, {"hash_scheme": HASH_SCHEME, "artifact_sha256": done_gate.current_artifact(repo, PATHS)[1], "accepted": True, "state": "accepted", "checker_id": CHK}))
check("uncommitted worktree edit is ignored: committed hash is evaluated", r["terminal_done"] and "return a + b" in done_gate.committed_files(repo, PATHS)["src/app.py"])
repo = mk("done"); r = close(repo, res(repo, accepted=False, state="rejected"))
check("signed reject -> failed, not terminal", r["quality"] == "failed" and not r["terminal_done"])
repo = mk("done"); r = close(repo, res(repo, accepted=False, state="error"))
check("signed error state -> unproven, not terminal", r["quality"] == "unproven" and not r["terminal_done"])
repo = mk("done"); r = close(repo, res(repo, checker_id="d" * 64))
check("wrong checker id -> unproven", not r["terminal_done"])
repo = mk("done"); r = close(repo, res(repo), chk=None)
check("unspecified expected checker -> unproven", not r["terminal_done"])
repo = mk("done"); r = close(repo, res(repo, hash_scheme="per-file"))
check("per-file hash scheme -> unproven", not r["terminal_done"])
repo = mk("done"); plain = {"payload": res(repo)["payload"], "sig": "x", "kind": "operator-check-result/v1"}
check("forged signature -> unproven", not close(repo, plain)["terminal_done"])
repo = mk("done"); r = done_gate.operator_close(repo, lt.BRANCH, ["src/missing.py"], res(repo), operator_key=KEY,
        expected_operator_checker_id=CHK, record_path=os.path.join(tmp, "m.json"))
check("missing artifact path -> not terminal, error recorded", not r["terminal_done"] and r["artifact_error"] and not r["operator_terminal_check_passed"])
for bad in (["/etc/passwd"], ["../x"], []):
    try:
        done_gate.committed_files(repo, bad); refused = False
    except ValueError: refused = True
    check("unsafe or empty path list refused: %r" % (bad,), refused)
repo = mk("done"); p = os.path.join(tmp, "once.json"); done_gate.operator_close(repo, lt.BRANCH, PATHS, res(repo), operator_key=KEY, expected_operator_checker_id=CHK, record_path=p)
try:
    done_gate.operator_close(repo, lt.BRANCH, PATHS, res(repo), operator_key=KEY, expected_operator_checker_id=CHK, record_path=p); again = False
except FileExistsError: again = True
check("existing record is never overwritten", again)
try:
    done_gate.operator_close(repo, lt.BRANCH, PATHS, res(repo), operator_key=KEY, expected_operator_checker_id=CHK, record_path=repo + "/rec.json"); inside = False
except ValueError: inside = True
check("record path inside the lane repo refused", inside)
# --- cycle_complete comes from HEAD, not the worktree
repo = mk("running"); b = Bus(repo, lt.BRANCH); st = b.state(); st["status"] = "done"; b.write_state(st)   # uncommitted
r = close(repo, res(repo))
check("uncommitted worktree status=done is NOT cycle_complete", not r["cycle_complete"] and not r["terminal_done"])
repo = mk("done"); git(repo, "checkout", "-q", "-b", "other")
r = close(repo, res(repo))
check("HEAD on a different branch than expected -> not cycle_complete", not r["cycle_complete"] and r["cycle_complete_note"])
r = close(mk("done"), None)
check("records say the runtime does not block DONE", r["runtime_blocks_done"] is False)
# --- race: a symlink or file planted at the record path is never followed or replaced
repo = mk("done"); target = os.path.join(tmp, "victim.txt"); open(target, "w").write("keep")
lnk = os.path.join(tmp, "planted.json"); os.symlink(target, lnk)
try:
    done_gate.operator_close(repo, lt.BRANCH, PATHS, res(repo), operator_key=KEY, expected_operator_checker_id=CHK, record_path=lnk); sl = False
except FileExistsError: sl = True
check("planted symlink at record path refused, victim untouched", sl and open(target).read() == "keep")
# --- completion_status (re-verifies signed evidence at read time)
rd = os.path.join(tmp, "recs"); os.mkdir(rd, 0o700)
def cs_for(repo, signed, **kw):
    p = os.path.join(rd, "r" + secrets.token_hex(3) + ".json")
    done_gate.operator_close(repo, lt.BRANCH, PATHS, signed, operator_key=KEY, expected_operator_checker_id=CHK, record_path=p)
    return p
def cs(repo, p, key=KEY, chk=CHK, paths=PATHS):
    return done_gate.completion_status(repo, lt.BRANCH, p, paths, operator_key=key, expected_operator_checker_id=chk)
repo = mk("done"); p = cs_for(repo, res(repo)); c = cs(repo, p)
check("status: genuine signed evidence -> closeout allowed", c["cycle_complete"] and c["terminal_done"] and c["closeout_allowed"])
check("status: no record -> cycle complete, closeout NOT allowed",
      not cs(repo, os.path.join(rd, "none.json"))["closeout_allowed"] and "unproven" in cs(repo, os.path.join(rd, "none.json"))["label"])
check("status: missing/short/wrong key -> not allowed", not cs(repo, p, key=None)["closeout_allowed"] and not cs(repo, p, key=b"short")["closeout_allowed"] and not cs(repo, p, key=secrets.token_bytes(32))["closeout_allowed"])
check("status: wrong expected checker -> not allowed", not cs(repo, p, chk="e" * 64)["closeout_allowed"])
# forged record: plaintext flags true, no valid signed evidence
f = json.load(open(p)); f["signed_operator_result"] = {"kind": "operator-check-result/v1", "payload": f["signed_operator_result"]["payload"], "sig": "0" * 64}
fp = os.path.join(rd, "forged.json"); json.dump(f, open(fp, "w"))
check("forged record (flags true, bad signature) -> not allowed", not cs(repo, fp)["closeout_allowed"])
f2 = json.load(open(p)); f2["signed_operator_result"] = None
fp2 = os.path.join(rd, "forged2.json"); json.dump(f2, open(fp2, "w"))
check("record with flags true but no evidence -> not allowed", f2["terminal_done"] is True and not cs(repo, fp2)["closeout_allowed"])
# subset: record names fewer files than the operator config
check("caller path list differs from record (subset/superset) -> not allowed", not cs(repo, p, paths=["src/app.py", "src/extra.py"])["closeout_allowed"])
f3 = json.load(open(p)); f3["artifact_paths"] = []
fp3 = os.path.join(rd, "subset.json"); json.dump(f3, open(fp3, "w"))
check("record edited to a smaller file set -> not allowed", not cs(repo, fp3)["closeout_allowed"])
# replay of valid evidence on a changed artifact
repo9 = mk("done"); s9 = res(repo9); p9 = cs_for(repo9, s9)
open(repo9 + "/src/app.py", "w").write("def add(a, b):\n    return 5\n"); git(repo9, "add", "-A"); git(repo9, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "operator: changed")
check("replayed evidence after the artifact/HEAD moved -> not allowed", not cs(repo9, p9)["closeout_allowed"])
# evidence from another lane replayed into this record
repoB = mk("done"); open(repoB + "/src/app.py", "w").write("def add(a, b):\n    return a + b  # other\n")
git(repoB, "add", "-A"); git(repoB, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "operator: other"); sB = res(repoB)
pB = cs_for(repo, sB)
check("signed evidence for a DIFFERENT artifact (other bytes) placed in this lane's record -> not allowed (identical bytes would be accepted by design: the evidence binds the artifact hash)", not cs(repo, pB)["closeout_allowed"])
# unsigned (unproven) record
repo2 = mk("done"); p2 = cs_for(repo2, None)
check("record of an unproven result -> not allowed", not cs(repo2, p2)["closeout_allowed"])
# record dir permissions / symlink
os.chmod(rd, 0o755); check("record dir not 0700 -> not allowed", not cs(repo, p)["closeout_allowed"]); os.chmod(rd, 0o700)
lk = os.path.join(rd, "link.json"); os.symlink(p, lk)
check("record that is a symlink -> not allowed", not cs(repo, lk)["closeout_allowed"])
# public entry point (CLI): exit 0 only when allowed, key from a file
kf = os.path.join(tmp, "k.bin"); open(kf, "wb").write(KEY)
def cli(rec, repo_=repo, kfile=kf):
    r = subprocess.run([sys.executable, os.path.join(HERE, "done_gate.py"), "--repo", repo_, "--branch", lt.BRANCH, "--record", rec,
                        "--key-file", kfile, "--checker-id", CHK, "--path", "src/app.py"], capture_output=True, text=True)
    return r.returncode, r.stdout
rc, out = cli(p)
check("CLI entry point: genuine -> exit 0 and closeout_allowed true", rc == 0 and json.loads(out)["closeout_allowed"] is True and KEY.hex() not in out)
check("CLI entry point: forged record -> exit 1", cli(fp)[0] == 1)
kf2 = os.path.join(tmp, "k2.bin"); open(kf2, "wb").write(secrets.token_bytes(32))
check("CLI entry point: wrong key file -> exit 1", cli(p, kfile=kf2)[0] == 1)
# end to end with the real mock team cycle (no provider): produced artifact, then a PUBLIC test operator check
e2 = tempfile.mkdtemp(dir=tmp); lt.init_repo(e2); lt.run_graph(e2, os.path.join(tmp, "e2.sqlite"), 0, "e2e")
st = Bus(e2, lt.BRANCH).state()
art = [x for x in ("src/app.py",) if os.path.exists(os.path.join(e2, x))]
check("mock team cycle reached done with a produced src/app.py (cycle_complete only)", st.get("status") == "done" and art == ["src/app.py"])
if art:
    files = done_gate.committed_files(e2, art)
    ns = {}; exec(compile(files["src/app.py"], "app", "exec"), ns)   # test operator: trusted mock code only
    accepted = all(ns["add"](a, b) == a + b for a, b in [(0, 0), (-5, 2), (10**9, 7), (3, -3)])
    sig = sign_operator(KEY, {"hash_scheme": HASH_SCHEME, "artifact_sha256": artifact_sha256(files), "accepted": accepted,
                              "state": "accepted" if accepted else "rejected", "checker_id": CHK})
    pe = os.path.join(rd, "e2e.json")
    done_gate.operator_close(e2, lt.BRANCH, art, sig, operator_key=KEY, expected_operator_checker_id=CHK, record_path=pe)
    c = done_gate.completion_status(e2, lt.BRANCH, pe, art, operator_key=KEY, expected_operator_checker_id=CHK)
    check("end to end (public test operator, mock-produced artifact): closeout allowed", c["closeout_allowed"] and c["terminal_done"])
    c0 = done_gate.completion_status(e2, lt.BRANCH, os.path.join(rd, "absent.json"), art, operator_key=KEY, expected_operator_checker_id=CHK)
    check("end to end without an operator record: cycle complete but closeout NOT allowed", c0["cycle_complete"] and not c0["closeout_allowed"])
    def lt_status(*extra):
        r = subprocess.run([sys.executable, os.path.join(HERE, "langgraph_team.py"), "status", e2, *extra], capture_output=True, text=True)
        return r.returncode, r.stdout
    rc0, o0 = lt_status()
    check("langgraph_team status, no record: cycle complete, quality unproven, exit 1", rc0 == 1 and json.loads(o0)["cycle_complete"] and not json.loads(o0)["closeout_allowed"] and "quality unproven" in json.loads(o0)["label"])
    kfe = os.path.join(tmp, "ke.bin"); open(kfe, "wb").write(KEY)
    rc1, o1 = lt_status("--record", pe, "--key-file", kfe, "--checker-id", CHK, "--path", "src/app.py")
    check("langgraph_team status with signed record: exit 0 and allowed", rc1 == 0 and json.loads(o1)["closeout_allowed"])
    rc2, _ = lt_status("--record", pe, "--key-file", kf2, "--checker-id", CHK, "--path", "src/app.py")
    check("langgraph_team status with wrong key: exit 1", rc2 == 1)

# ---- automatic operator-owned finalization (offline, PUBLIC test checker) ----
cdir = tempfile.mkdtemp(dir=tmp); os.chmod(cdir, 0o700)
chk = os.path.join(cdir, "chk.py")
open(chk, "w").write("""import sys, os, json
# public test checker: refuses if the parent's env leaked into the child
leaked = any(k.startswith("LG_") or "KEY" in k.upper() for k in os.environ)
ns = {}; exec(open(os.path.join(sys.argv[-1], "src/app.py")).read(), ns)
ok = (not leaked) and all(ns["add"](a, b) == a + b for a, b in [(0, 0), (-5, 2), (3, -3)])
print(json.dumps({"accepted": ok}))
""")
bad_chk = os.path.join(cdir, "bad.py"); open(bad_chk, "w").write("import sys; sys.exit(3)\n")
fkey = os.path.join(cdir, "key.bin"); open(fkey, "wb").write(KEY); os.chmod(fkey, 0o600)
def mkcfg(name, script=chk, **kw):
    rd2 = os.path.join(cdir, name + "-rec"); os.makedirs(rd2, exist_ok=True); os.chmod(rd2, 0o700)
    c = {"checker_cmd": [sys.executable, script], "checker_id": CHK, "artifact_paths": ["src/app.py"],
         "key_file": fkey, "record_dir": rd2, "timeout": 30}; c.update(kw)
    cp = os.path.join(cdir, name + ".json"); open(cp, "w").write(json.dumps(c)); os.chmod(cp, 0o600)
    return cp, rd2
def newlane():
    d = tempfile.mkdtemp(dir=tmp); lt.init_repo(d); lt.run_graph(d, os.path.join(tmp, os.path.basename(d) + ".sqlite"), 0, "f"); return d
os.environ["LG_OPERATOR_CONFIG"] = "leak-probe"; os.environ["SOME_API_KEY"] = "leak-probe"
fl = newlane()
check("finalize: no config -> quality unproven", (lambda s: s["cycle_complete"] and not s["closeout_allowed"] and "unproven" in s["label"])(done_gate.finalize(fl, lt.BRANCH, None)))
cp, rd2 = mkcfg("ok")
s = done_gate.finalize(fl, lt.BRANCH, cp)
check("finalize: genuine public test checker (child env scrubbed) -> closeout allowed", s["closeout_allowed"] and s["terminal_done"] and KEY.hex() not in json.dumps(s))
check("finalize: record written once, rerun still allowed without a second checker run", len(os.listdir(rd2)) == 1 and done_gate.finalize(fl, lt.BRANCH, cp)["closeout_allowed"])
cp2, _ = mkcfg("loose"); os.chmod(cp2, 0o644)
check("finalize: config with mode 0644 -> unproven", not done_gate.finalize(newlane(), lt.BRANCH, cp2)["closeout_allowed"])
l3 = newlane(); cp3, rd3 = mkcfg("crash", script=bad_chk)
s3 = done_gate.finalize(l3, lt.BRANCH, cp3)
check("finalize: checker crash -> unproven and no record", not s3["closeout_allowed"] and os.listdir(rd3) == [])
l4 = newlane(); kin = os.path.join(l4, "k.bin"); open(kin, "wb").write(KEY); os.chmod(kin, 0o600)
cp4, _ = mkcfg("keyinlane", key_file=kin)
check("finalize: key file inside the lane -> unproven", not done_gate.finalize(l4, lt.BRANCH, cp4)["closeout_allowed"])
cp6, rd6 = mkcfg("reject"); l6 = newlane()
open(os.path.join(l6, "src/app.py"), "w").write("def add(a, b):\n    return a - b\n")
git(l6, "add", "-A"); git(l6, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "operator: bad artifact")
s6 = done_gate.finalize(l6, lt.BRANCH, cp6)
check("finalize: checker rejects the artifact -> not allowed", not s6["closeout_allowed"])
# run phase end to end through the real launcher entry
l7 = tempfile.mkdtemp(dir=tmp); subprocess.run([sys.executable, os.path.join(HERE, "langgraph_team.py"), "init", l7, os.path.join(tmp, "l7.sqlite")], check=True, capture_output=True)
cp7, _ = mkcfg("run")
env7 = dict(os.environ); env7["LG_OPERATOR_CONFIG"] = cp7
r7 = subprocess.run([sys.executable, os.path.join(HERE, "langgraph_team.py"), "run", l7, os.path.join(tmp, "l7.sqlite"), "0", "r7"], capture_output=True, text=True, env=env7)
check("run phase with operator config ends with closeout allowed (offline mock cycle, public test checker)", r7.returncode == 0 and '"closeout_allowed": true' in r7.stdout and KEY.hex() not in r7.stdout + r7.stderr)
l8 = tempfile.mkdtemp(dir=tmp); subprocess.run([sys.executable, os.path.join(HERE, "langgraph_team.py"), "init", l8, os.path.join(tmp, "l8.sqlite")], check=True, capture_output=True)
env8 = {k: v for k, v in os.environ.items() if k != "LG_OPERATOR_CONFIG"}
r8 = subprocess.run([sys.executable, os.path.join(HERE, "langgraph_team.py"), "run", l8, os.path.join(tmp, "l8.sqlite"), "0", "r8"], capture_output=True, text=True, env=env8)
check("run phase without operator config: cycle done, closeout unproven", r8.returncode == 0 and '"closeout_allowed": false' in r8.stdout and "quality unproven" in r8.stdout)
os.environ.pop("LG_OPERATOR_CONFIG"); os.environ.pop("SOME_API_KEY")
shutil.rmtree(tmp, ignore_errors=True)
print("\nOPERATOR DONE HOOK:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE"); raise SystemExit(0 if ok else 1)
