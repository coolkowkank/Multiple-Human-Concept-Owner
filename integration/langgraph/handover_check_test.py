"""Offline: handover_check env/state. Synthetic roots only; no network, no
provider, no real ledger, no key. Planted fake secret values must never
appear in any output, and state must be strictly read-only."""
import contextlib, io, json, os, shutil, stat, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import handover_check as hc  # noqa: E402
ok = True
def check(n, c):
    global ok; ok = ok and bool(c); print(("PASS  " if c else "FAIL  ") + n, flush=True)
FAKE_KEY, FAKE_API = "FAKE-ALLOWANCE-KEY-VALUE-123", "FAKE-API-KEY-VALUE-456"
def snapshot(root):
    out = {}
    for dp, dn, fn in os.walk(root):
        for f in fn + dn:
            p = os.path.join(dp, f); st = os.stat(p); out[p] = (st.st_mtime_ns, st.st_size, st.st_mode)
    return out
def jl(path, rows, raw=None):
    with open(path, "w") as f:
        for r in rows: f.write(json.dumps(r) + "\n")
        if raw: f.write(raw)
tmp = tempfile.mkdtemp()
try:
    root = os.path.join(tmp, "root"); os.makedirs(root)
    logd = os.path.join(tmp, "logs"); os.makedirs(logd); os.chmod(logd, 0o700)
    led = [{"phase": "reserved", "rid": "r1", "qid": "q1", "role": "researcher", "model": "m1"},
           {"phase": "result", "rid": "r1", "qid": "q1", "role": "researcher", "model": "m1", "outcome": "ok"},
           {"phase": "reserved", "rid": "r2", "qid": "q1", "role": "verifier", "model": "m2"},
           {"phase": "result", "rid": "r2", "qid": "q1", "role": "verifier", "model": "m2", "outcome": "unknown"},
           {"phase": "halt", "reason": "unknown transport outcome r2"},
           {"phase": "reserved", "rid": "r3", "qid": "q1", "role": "verifier", "model": "m2"}]
    jl(os.path.join(root, "ledger.jsonl"), led)
    json.dump({"questions": [{"id": "q1", "status": "drafted", "lineage": "L", "attempts": {"researcher": 1, "verifier": 2},
                              "findings": [{"claim": "PRIVATE-CLAIM-TEXT"}]}]}, open(os.path.join(root, "queue.json"), "w"))
    json.dump({"models": {"researcher": "m1", "verifier": "m2"}, "decided_by": "main"}, open(os.path.join(root, "assignments.json"), "w"))
    os.environ["REQUESTY_API_KEY"] = FAKE_API
    kf = os.path.join(tmp, "key"); open(kf, "w").write(FAKE_KEY); os.chmod(kf, 0o600)
    os.environ["RYAN_ALLOWANCE_KEY_FILE"] = kf
    before = snapshot(root)
    r = hc.state_report(root, logd)
    s = json.dumps(r)
    check("state: read-only (no file or dir created, changed or locked-in)", snapshot(root) == before and not os.path.exists(os.path.join(root, ".lock")))
    check("state: counts and standing halt reported", r["ledger"]["reserves"] == 3 and r["halt"]["standing"] is True and r["halt"]["cleared_lines"] == 0)
    check("state: reserve without result listed (r3), unknown outcome kept as recorded", r["reserves_without_result"] == ["r3"] and r["ledger"]["by_phase_role_outcome"]["result/verifier/unknown"] == 1)
    check("state: runner would refuse next step (standing halt and r3 without result)", r["runner_would_refuse_next_step"] is True and r["reserves_blocking_since_last_clear"] == ["r3"])
    check("state: queue item fields only, no finding text", r["queue_items"][0]["id"] == "q1" and "PRIVATE-CLAIM-TEXT" not in s)
    check("state: no key value or env value anywhere", FAKE_KEY not in s and FAKE_API not in s)
    check("state: file hashes present, no contents", len(r["files"]["ledger.jsonl"]["sha256"]) == 64)
    check("state: carries the private-do-not-publish label", "do not publish" in r["PRIVATE"])
    check("state: empty shared log dir is unestablished, not zero", r["shared_log"]["status"] == "unestablished")
    # cleared halt
    jl(os.path.join(root, "ledger.jsonl"), led + [{"phase": "cleared", "source_note": "x"}])
    cl = hc.state_report(root)
    check("state: a later cleared line ends the standing halt and the old reserve block", cl["halt"]["standing"] is False and cl["reserves_blocking_since_last_clear"] == [] and cl["runner_would_refuse_next_step"] is False)
    # damaged history is flagged, never repaired
    jl(os.path.join(root, "ledger.jsonl"), led, raw="{not json\n[1]\n")
    h0 = hc._sha(os.path.join(root, "ledger.jsonl")); rr = hc.state_report(root)
    check("state: unparseable lines flagged and file untouched", any("unparseable" in p for p in rr["problems"]) and hc._sha(os.path.join(root, "ledger.jsonl")) == h0)
    e2 = os.path.join(tmp, "e2"); os.makedirs(e2)
    check("state: missing ledger flagged as cannot-tell", any("no ledger.jsonl" in p for p in hc.state_report(e2)["problems"]))
    check("state: nonexistent root refused without creating it", hc.state_report(os.path.join(tmp, "nope"))["problems"] and not os.path.exists(os.path.join(tmp, "nope")))
    # root inside a git tree is flagged
    g = os.path.join(tmp, "g"); os.makedirs(os.path.join(g, "priv")); subprocess.run(["git", "-C", g, "init", "-q"])
    check("state: root inside a git work tree is flagged", any("git work tree" in p for p in hc.state_report(os.path.join(g, "priv"))["problems"]))
    # env report
    buf = hc.env_report()
    eb = json.dumps(buf)
    check("env: secret env presence by name only, values never printed", buf["secret_env_names"] == {"REQUESTY_API_KEY": "set", "RYAN_ALLOWANCE_KEY_FILE": "set"} and FAKE_KEY not in eb and FAKE_API not in eb)
    check("env: key file mode reported, not content", buf["allowance_key_file"]["mode"] == "0o600")
    os.chmod(kf, 0o644)
    check("env: key file with group/other bits is blocking", any("permission bits" in b for b in hc.env_report()["blocking"]))
    saved = os.environ["HOME"]; os.environ["HOME"] = tmp
    check("env: HOME differing from the account home is blocking", any("HOME differs" in b for b in hc.env_report()["blocking"]))
    os.environ["HOME"] = saved
    check("env: report states it qualifies nothing", "qualifies no route" in buf["note"])
    # CLI
    p = subprocess.run([sys.executable, os.path.join(HERE, "handover_check.py"), "state"], capture_output=True, text=True)
    check("cli: state without --root exits 2", p.returncode == 2)
    p = subprocess.run([sys.executable, os.path.join(HERE, "handover_check.py"), "state", "--root", root], capture_output=True, text=True)
    check("cli: state output carries no planted secret", FAKE_KEY not in p.stdout + p.stderr and FAKE_API not in p.stdout + p.stderr)
    # fresh-check verdict fails closed
    vd = os.path.join(tmp, "vd"); os.makedirs(vd)
    for n in ("a_test.py", "b_test.py"): open(os.path.join(vd, n), "w").close()
    rf = os.path.join(tmp, "res.txt")
    check("verdict: missing results file fails", not hc.fresh_verdict(vd, rf)[0])
    open(rf, "w").close()
    check("verdict: empty results file fails", not hc.fresh_verdict(vd, rf)[0])
    open(rf, "w").write("a_test.py 0\n")
    check("verdict: partial results fail", not hc.fresh_verdict(vd, rf)[0])
    open(rf, "w").write("a_test.py 0\nb_test.py 1\n")
    check("verdict: a nonzero status fails", not hc.fresh_verdict(vd, rf)[0])
    open(rf, "w").write("a_test.py 0\nb_test.py 0\nb_test.py 0\n")
    check("verdict: duplicate result fails", not hc.fresh_verdict(vd, rf)[0])
    open(rf, "w").write("a_test.py 0\nb_test.py 0\nc_test.py 0\n")
    check("verdict: unexpected extra file fails", not hc.fresh_verdict(vd, rf)[0])
    open(rf, "w").write("a_test.py 0\nb_test.py\n")
    check("verdict: malformed line fails", not hc.fresh_verdict(vd, rf)[0])
    open(rf, "w").write("a_test.py 0\nb_test.py 0\n")
    check("verdict: all discovered files exit 0 passes", hc.fresh_verdict(vd, rf) == (True, "2"))
    ed = os.path.join(tmp, "ed"); os.makedirs(ed)
    check("verdict: no test files fails", not hc.fresh_verdict(ed, rf)[0])
    p = subprocess.run([sys.executable, "-B", os.path.join(HERE, "handover_check.py"), "verdict", "--dir", vd, "--results", rf + ".none"], capture_output=True, text=True)
    check("cli: verdict with missing results exits 1", p.returncode == 1 and p.stdout.startswith("FAIL"))
finally:
    for k in ("REQUESTY_API_KEY", "RYAN_ALLOWANCE_KEY_FILE"): os.environ.pop(k, None)
    shutil.rmtree(tmp, ignore_errors=True)
print("ALL PASS" if ok else "SOME FAIL"); sys.exit(0 if ok else 1)
