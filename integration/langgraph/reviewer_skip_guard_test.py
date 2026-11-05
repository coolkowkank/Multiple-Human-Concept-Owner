"""Reviewer-skip acceptance guard: a DONE claim is accepted only with a
fresh QC PASS verdict in the bus. Offline, scripted mock seats, real git
repos. Mutation note: on the pre-guard runtime every refused case below
used to close DONE unconditionally."""
import json, os, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from launcher.bus import Bus
from launcher.runtime import Seat

ok = True
def check(n, c):
    global ok; ok = ok and bool(c); print(("PASS  " if c else "FAIL  ") + n, flush=True)

APP = "def add(a, b):\n    return a + b\n"
TEST = ("import sys, os\nsys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))\n"
        "from app import add\nassert add(2, 3) == 5\nprint('ok')\n")
REPOS = []

def mk_repo(roster_edit=None, scripts=None):
    repo = tempfile.mkdtemp(); REPOS.append(repo)
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.email", "t@example.com"], check=True)
    proc = subprocess.run([sys.executable, "-m", "launcher", "init",
                           "--default-roster", "--repo", repo],
                          capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": HERE})
    assert proc.returncode == 0, proc.stderr
    bus = Bus(repo, "team-work")
    roster = bus.roster()
    for name, spec in roster["seats"].items():
        spec["adapter"] = {"type": "mock", "script": (scripts or {}).get(name, [])}
    if roster_edit:
        roster_edit(roster)
    with open(os.path.join(repo, ".team", "roster.json"), "w") as fh:
        json.dump(roster, fh, indent=2)
    state = bus.state(); state["turn"] = "builder"; state["status"] = "running"
    bus.write_state(state)
    bus.commit_all("human: start")
    seats = {name: Seat(bus, name) for name in roster["seats"]}
    return repo, bus, seats

def give_turn(bus, name):
    st = bus.state(); st["turn"] = name; bus.write_state(st)
    bus.commit_all("human: test routing")

BUILD = {"summary": "built add()", "writes": {"src/app.py": APP, "tests/test_app.py": TEST},
         "verify_command": None, "handoff": "qc", "status_line": "built"}
QC_PASS = {"summary": "pass", "writes": {"review/qc-verdict-1.md": "PASS\n"},
           "verify_command": None, "handoff": "builder", "status_line": "QC PASS"}
DONE_CLAIM = {"summary": "closing", "writes": {}, "verify_command": None,
              "handoff": None, "status_line": "DONE - ready"}
MORE_WORK = {"summary": "more work", "writes": {"src/more.py": "X = 1\n"},
             "verify_command": None, "handoff": "builder", "status_line": "iterated"}

# Case A: DONE with no verdict -> refused/routed; then QC PASS at head -> accepted
repo, bus, seats = mk_repo(scripts={"builder": [BUILD, DONE_CLAIM, DONE_CLAIM],
                                    "qc": [QC_PASS]})
seats["builder"].act_once()
give_turn(bus, "builder")
seats["builder"].act_once()   # DONE claim, no verdict anywhere
st = bus.state()
check("1. DONE without verdict not accepted", st["status"] != "done")
check("2. turn routed to qc", st["turn"] == "qc")
rr = [e for e in bus.log() if e.get("kind") == "review-required"]
check("3. review-required logged naming the claimant", rr and "builder" in rr[-1]["body"])
check("4. no lying DONE status_line", not str(st.get("status_line", "")).startswith("DONE -"))
seats["qc"].act_once()        # verdict PASS at head, hands back
st = bus.state()
check("5. qc turn handed back to builder", st["turn"] == "builder")
v = [e for e in bus.log() if e.get("kind") == "verdict"]
check("6. verdict row recorded with PASS and a head",
      v and v[-1]["body"].startswith("verdict PASS at head "))
seats["builder"].act_once()   # DONE claim with the fresh verdict
st = bus.state()
check("7. DONE accepted with fresh QC PASS verdict", st["status"] == "done")
check("8. turn closed after accepted DONE", st["turn"] is None)

# Case B: verdict then application work -> stale -> refused
repo2, bus2, seats2 = mk_repo(scripts={"builder": [BUILD, MORE_WORK, DONE_CLAIM],
                                       "qc": [QC_PASS]})
seats2["builder"].act_once()
seats2["qc"].act_once()       # verdict PASS at head (BUILD handed to qc)
give_turn(bus2, "builder")
seats2["builder"].act_once()  # MORE_WORK: application commit after the verdict
st = bus2.state()
check("9. builder self-handoff keeps turn", st["turn"] == "builder")
seats2["builder"].act_once()  # DONE claim on the now-stale verdict
st = bus2.state()
check("10. stale-verdict DONE not accepted", st["status"] != "done")
check("11. stale DONE routed back to qc", st["turn"] == "qc")

# Case C: no QC seat in the roster -> human gate, parked turn, not done
def drop_qc(roster):
    del roster["seats"]["qc"]
repo3, bus3, seats3 = mk_repo(roster_edit=drop_qc,
                              scripts={"builder": [dict(BUILD, handoff="reviewer"), DONE_CLAIM]})
seats3["builder"].act_once()
give_turn(bus3, "builder")
seats3["builder"].act_once()  # DONE claim, nobody can review
st = bus3.state()
check("12. no-QC DONE not accepted", st["status"] != "done")
check("13. human gate opened", any("no QC seat" in g.get("question", "")
                                   for g in bus3.pending_gates()))
check("14. turn parked (no holder, not silently routed)", st["turn"] is None)

# Case D: verdict row from a non-QC seat does not satisfy
repo4, bus4, seats4 = mk_repo(scripts={"builder": [BUILD, DONE_CLAIM]})
seats4["builder"].act_once()
head = subprocess.run(["git", "-C", repo4, "rev-parse", "HEAD"],
                      capture_output=True, text=True).stdout.strip()
bus4.append_log("builder", "verdict", "verdict PASS at head " + head + ": faked")
bus4.commit_all("human: plant a fake verdict row")
give_turn(bus4, "builder")
seats4["builder"].act_once()
st = bus4.state()
check("15. non-QC verdict does not satisfy", st["status"] != "done" and st["turn"] == "qc")

# Case E: FAIL verdict does not satisfy
repo5, bus5, seats5 = mk_repo(scripts={
    "builder": [BUILD, DONE_CLAIM],
    "qc": [dict(QC_PASS, status_line="QC FAIL", summary="fail")]})
seats5["builder"].act_once()
seats5["qc"].act_once()
give_turn(bus5, "builder")
seats5["builder"].act_once()
st = bus5.state()
check("16. FAIL verdict does not satisfy", st["status"] != "done" and st["turn"] == "qc")

# Case F: regression - ordinary non-DONE handoff unaffected
repo6, bus6, seats6 = mk_repo(scripts={"builder": [BUILD]})
seats6["builder"].act_once()
st = bus6.state()
check("17. plain handoff still works", st["turn"] == "qc" and st["status"] == "running")

for _r in REPOS:
    shutil.rmtree(_r, ignore_errors=True)
print("REVIEWER-SKIP GUARD:", "ALL CHECKS PASSED" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
