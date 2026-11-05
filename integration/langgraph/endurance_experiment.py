"""Bounded endurance experiment: a REAL supervisor (`launcher launch`) runs REAL
seat processes over a scratch lane with SCRIPTED MOCK adapters: N full team
cycles (coordinator -> builder -> reviewer -> qc -> records), real verify
runs, real git commits. No provider, no key, no ledger, no project lease.

Success is defined BEFORE the run against the workflow (see CRITERIA). Run
modes: `clean` (nothing injected) and `kill` (ONE actual SIGKILL of the
builder seat process while it is inside its batch-2 verify).

This measures a short scripted run. It says nothing about model quality, long
duration, provider failures, or unattended safety."""
import os as _os; _os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import argparse, json, os, signal, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import langgraph_team as lt  # noqa: E402
from launcher.bus import Bus  # noqa: E402

CRITERIA = [
 "C1 supervisor returns 'done' within the time cap",
 "C2 STATE status done; handoff rows are exactly the expected seat order (5N+1 turns), turn_seq +1 per turn",
 "C3 functional output: per-batch module, test, review, qc verdict and archive files exist, and the final cumulative test passes when re-run",
 "C4 worktree clean, no error rows, no gates, no stale lg-live declaration, one lease holder per seat",
 "C5 clean mode: zero restart rows. kill mode: exactly one restart row for builder, the batch-2 builder handoff appears once, and C1-C4 still hold",
]
SEATS = ["coordinator", "builder", "reviewer", "qc", "records"]

def scripts(n, slow_batch):
    out = {s: [] for s in SEATS}
    for k in range(1, n + 1):
        out["coordinator"].append({"summary": f"dispatch batch {k}", "writes": {f".team/ACCEPTANCE-{k}.md": f"batch {k}: mod_{k}.value() == {k*k}\n"},
            "verify_command": None, "handoff": "builder", "status_line": f"batch {k} dispatched"})
        mods = "".join(f"import mod_{i}\nassert mod_{i}.value() == {i*i}, {i}\n" for i in range(1, k + 1))
        sl = "import time; time.sleep(5)\n" if k == slow_batch else ""
        test = ("import sys, os\nsys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))\n" + sl + mods + "print('ok', %d)\n" % k)
        out["builder"].append({"summary": f"built batch {k}", "writes": {f"src/mod_{k}.py": f"def value():\n    return {k*k}\n", "tests/test_app.py": test},
            "verify_command": "python3 tests/test_app.py", "handoff": "reviewer", "status_line": f"batch {k} built"})
        out["reviewer"].append({"summary": f"reviewed batch {k}", "writes": {f"review/findings-{k}.md": f"batch {k}: none; verify re-run green\n"},
            "verify_command": "python3 tests/test_app.py", "handoff": "qc", "status_line": f"batch {k} reviewed"})
        out["qc"].append({"summary": f"qc batch {k}", "writes": {f"review/qc-verdict-{k}.md": f"batch {k}: PASS\n"},
            "verify_command": "python3 tests/test_app.py", "handoff": "records", "status_line": f"batch {k} qc pass"})
        out["records"].append({"summary": f"archived batch {k}", "writes": {f"records/archive-{k}.md": f"batch {k} archived\n"},
            "verify_command": None, "handoff": "coordinator", "status_line": f"batch {k} archived"})
    out["coordinator"].append({"summary": "all batches accepted", "writes": {}, "verify_command": None, "handoff": None,
        "status_line": f"DONE - {n} batches archived and verified"})
    return out

def children(ppid):
    r = []
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                st = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
                if int(st[1]) == ppid: r.append(int(pid))
            except (OSError, IndexError, ValueError): pass
    return r

def cmdline(pid):
    try: return open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode()
    except OSError: return ""

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("mode", choices=["clean", "kill"])
    ap.add_argument("--batches", type=int, default=3); ap.add_argument("--cap", type=int, default=240)
    a = ap.parse_args(); n = a.batches
    tmp = tempfile.mkdtemp(prefix="endure-"); r = os.path.join(tmp, "lane")
    lt.init_repo(r)
    bus = Bus(r, lt.BRANCH); roster = bus.roster()
    os.makedirs(os.path.join(r, ".team", "queues"), exist_ok=True)
    sc = scripts(n, 2 if a.mode == "kill" else 0)
    for s in SEATS:
        q = os.path.join(r, ".team", "queues", f"{s}.mock.jsonl")
        open(q, "w").write("".join(json.dumps(x) + "\n" for x in sc[s]))
    bus.commit_all("operator: scripted queues")
    env = dict(os.environ); env["PYTHONPATH"] = HERE + os.pathsep + env.get("PYTHONPATH", "")
    out_path = os.path.join(tmp, "supervisor.out")
    t0 = time.time(); killed = None
    sup = subprocess.Popen([sys.executable, "-m", "launcher", "launch", "--repo", r, "--branch", lt.BRANCH, "--poll", "1", "--max-seconds", str(a.cap)],
                           stdout=open(out_path, "w"), stderr=subprocess.STDOUT, env=env, start_new_session=True)
    try:
        while sup.poll() is None and time.time() - t0 < a.cap + 30:
            if a.mode == "kill" and killed is None:
                try: txt = open(os.path.join(r, "tests", "test_app.py")).read()
                except OSError: txt = ""
                if "sleep(5)" in txt:
                    for c in children(sup.pid):
                        if f"seat builder" in cmdline(c) and r in cmdline(c) and children(c):
                            os.kill(c, signal.SIGKILL); killed = {"pid": c, "at_s": round(time.time() - t0, 1)}; break
            time.sleep(0.2)
        if sup.poll() is None: os.killpg(sup.pid, signal.SIGKILL)
        sup.wait()
    finally:
        if sup.poll() is None: os.killpg(sup.pid, signal.SIGKILL)
        time.sleep(0.5)
        for p in os.listdir("/proc"):   # only descendants of our scratch lane's supervisor group
            pass
    wall = round(time.time() - t0, 1)
    so = open(out_path).read()
    g = lambda *x: subprocess.run(["git", "-C", r, *x], capture_output=True, text=True).stdout
    st = bus.state(); log = bus.log()
    hs = [e for e in log if e.get("kind") == "handoff"]
    expect = (SEATS) * n + ["coordinator"]
    seats = [e.get("seat") for e in hs]
    seqs = [e.get("turn_seq") for e in hs]
    restarts = [e for e in log if e.get("kind") == "restart"]
    errs = [e for e in log if e.get("kind") == "error"]
    files_ok = all(os.path.exists(os.path.join(r, f)) for k in range(1, n + 1) for f in
                   (f"src/mod_{k}.py", f"review/findings-{k}.md", f"review/qc-verdict-{k}.md", f"records/archive-{k}.md", f".team/ACCEPTANCE-{k}.md"))
    clean_tree = g("status", "--porcelain") == ""   # BEFORE re-running the test (it writes __pycache__)
    t = subprocess.run([sys.executable, "-B", "tests/test_app.py"], cwd=r, capture_output=True, text=True)
    final_ok = t.returncode == 0 and f"ok {n}" in t.stdout
    leases = st.get("leases") or {}
    res = {"mode": a.mode, "batches": n, "wall_s": wall, "killed": killed,
           "C1_supervisor_done": "supervisor: done" in so, "C2_status": st.get("status"),
           "C2_order_ok": seats == expect[:len(seats)] and len(seats) == len(expect) , "turns": len(seats),
           "C2_seq_plus1": all(b - a_ == 1 for a_, b in zip(seqs, seqs[1:])) if all(isinstance(x, int) for x in seqs) else None,
           "C3_files_ok": files_ok, "C3_final_test_ok": final_ok,
           "C4_clean_tree": clean_tree, "C4_error_rows": len(errs), "C4_gates": len(bus.pending_gates()),
           "C4_stale_decl": [f for f in os.listdir(os.path.join(r, ".git")) if f.startswith("lg-live-")],
           "C4_leases": {k: v.get("holder") for k, v in leases.items()},
           "restart_rows": [(e.get("seat"), e.get("body")) for e in restarts],
           "builder_handoffs_batch2": sum(1 for e in hs if e.get("seat") == "builder") - 0,
           "commits": int(g("rev-list", "--count", "HEAD").strip()),
           "log_bytes": os.path.getsize(os.path.join(r, ".team/LOG.jsonl")),
           "supervisor_out_tail": so.strip().splitlines()[-3:], "lane": r}
    ok = (res["C1_supervisor_done"] and res["C2_status"] == "done" and res["C2_order_ok"] and res["C2_seq_plus1"] is True
          and files_ok and final_ok and res["C4_clean_tree"] and not errs and not res["C4_gates"] and not res["C4_stale_decl"])
    if a.mode == "clean": ok = ok and not restarts
    else: ok = ok and killed is not None and len(restarts) == 1 and restarts[0].get("seat") == "supervisor" and "builder" in (restarts[0].get("body") or "") and res["builder_handoffs_batch2"] == n
    res["SUCCESS"] = bool(ok)
    print(json.dumps(res, indent=1)); sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
