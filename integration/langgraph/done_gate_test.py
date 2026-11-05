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
check("no evidence -> not terminal, gate_enforced false", not r["terminal_done"] and not r["gate_enforced"] and r["cycle_complete"])
repo = mk("done"); r = close(repo, res(repo))
check("signed accept on cycle-complete bus -> terminal_done, gate_enforced true",
      r["terminal_done"] and r["gate_enforced"] and r["quality"] == "operator_check_passed")
check("record has hash, paths, head, no key", r["artifact_sha256"] and r["artifact_paths"] == PATHS
      and r["head"] and KEY.hex() not in json.dumps(r))
repo = mk("running"); r = close(repo, res(repo))
check("cycle not complete (bus running) -> not terminal even with valid evidence", not r["terminal_done"] and not r["gate_enforced"])
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
check("missing artifact path -> not terminal, error recorded", not r["terminal_done"] and r["artifact_error"] and not r["gate_enforced"])
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
shutil.rmtree(tmp, ignore_errors=True)
print("\nOPERATOR DONE HOOK:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE"); raise SystemExit(0 if ok else 1)
