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

# Case G (review D1): DONE turn carrying application writes -> refused even
# with a fresh verdict
repo7, bus7, seats7 = mk_repo(scripts={
    "builder": [BUILD, dict(DONE_CLAIM, writes={"src/evil.py": "E = 1\n"})],
    "qc": [QC_PASS]})
seats7["builder"].act_once()
seats7["qc"].act_once()
give_turn(bus7, "builder")
seats7["builder"].act_once()
st = bus7.state()
check("18. DONE with own application writes refused despite fresh verdict",
      st["status"] != "done" and st["turn"] == "qc")

# Case H (review D2): negated/qualified PASS text records NONE
for i, line in enumerate(("QC cannot PASS this build", "PASS pending")):
    repoN, busN, seatsN = mk_repo(scripts={
        "builder": [BUILD, DONE_CLAIM],
        "qc": [dict(QC_PASS, status_line=line, summary="x")]})
    seatsN["builder"].act_once()
    seatsN["qc"].act_once()
    give_turn(busN, "builder")
    seatsN["builder"].act_once()
    st = busN.state()
    check(f"{19+i}. {line!r} does not satisfy", st["status"] != "done" and st["turn"] == "qc")

# Case I (review D3): rename of application work into an evidence path stales
repo8, bus8, seats8 = mk_repo(scripts={"builder": [BUILD, DONE_CLAIM],
                                       "qc": [QC_PASS]})
seats8["builder"].act_once()
seats8["qc"].act_once()
subprocess.run(["git", "-C", repo8, "mv", "src/app.py", "review/app.py"], check=True)
subprocess.run(["git", "-C", repo8, "commit", "-q", "-m", "human: rename app into review/"], check=True)
give_turn(bus8, "builder")
seats8["builder"].act_once()
st = bus8.state()
check("21. rename hiding application work stales the verdict", st["status"] != "done" and st["turn"] == "qc")

# Case J (review D4): bare roster path "review" must not prefix-match reviewer_x.py
def bare_review(roster):
    roster["seats"]["qc"]["allowed_paths"] = ["review"]
    roster["seats"]["reviewer"]["allowed_paths"] = ["review"]
repo9, bus9, seats9 = mk_repo(roster_edit=bare_review,
                              scripts={"builder": [BUILD, DONE_CLAIM], "qc": [QC_PASS]})
seats9["builder"].act_once()
seats9["qc"].act_once()
open(os.path.join(repo9, "reviewer_x.py"), "w").write("E = 1\n")
subprocess.run(["git", "-C", repo9, "add", "reviewer_x.py"], check=True)
subprocess.run(["git", "-C", repo9, "commit", "-q", "-m", "human: add reviewer_x.py"], check=True)
give_turn(bus9, "builder")
seats9["builder"].act_once()
st = bus9.state()
check("22. bare 'review' prefix does not cover reviewer_x.py", st["status"] != "done" and st["turn"] == "qc")

# Case K (policy): a QC seat MAY close DONE on its own earlier fresh verdict
repoA, busA, seatsA = mk_repo(scripts={"builder": [BUILD],
                                      "qc": [dict(QC_PASS, handoff="builder"),
                                             dict(DONE_CLAIM, status_line="DONE")]})
seatsA["builder"].act_once()
seatsA["qc"].act_once()       # verdict recorded, hands to builder
give_turn(busA, "qc")
seatsA["qc"].act_once()       # QC claims DONE on its own verdict
st = busA.state()
check("23. QC self-close (bare DONE) with own fresh PASS verdict accepted", st["status"] == "done" and st["turn"] is None)

# Case L (product P2): PASS then a newer FAIL cancels - DONE refused
repoB, busB, seatsB = mk_repo(scripts={
    "builder": [BUILD, DONE_CLAIM],
    "qc": [QC_PASS, dict(QC_PASS, status_line="QC FAIL", summary="regression found")]})
seatsB["builder"].act_once()
seatsB["qc"].act_once()       # PASS at head, hands to builder
give_turn(busB, "qc")
seatsB["qc"].act_once()       # newer FAIL verdict (evidence-only commit)
give_turn(busB, "builder")
seatsB["builder"].act_once()  # DONE claim
st = busB.state()
check("24. newer QC FAIL cancels older fresh PASS", st["status"] != "done" and st["turn"] == "qc")

# Case M (product P8): filename with a space is not a false stale
repoC, busC, seatsC = mk_repo(scripts={"builder": [BUILD, DONE_CLAIM],
                                       "qc": [QC_PASS]})
seatsC["builder"].act_once()
seatsC["qc"].act_once()
sp = os.path.join(repoC, "review", "my file.md")
open(sp, "w").write("note\n")
subprocess.run(["git", "-C", repoC, "add", "review/my file.md"], check=True)
subprocess.run(["git", "-C", repoC, "commit", "-q", "-m", "human: evidence file with a space"], check=True)
give_turn(busC, "builder")
seatsC["builder"].act_once()
st = busC.state()
check("25. space in an evidence filename stays fresh (no false block)", st["status"] == "done")

# Case N (review round 3): the PASS grammar is a whole-line whitelist.
# Every qualified/conditional/hedged line records NONE, never PASS.
QUALIFIED = ("PASS (2 tests fail)", "PASS with failures", "PASS unless the API changes",
             "PASS if the owner agrees", "PASS - needs rework", "PASS? unsure",
             "PASS w/ open P1 issues", "PASS, no wait, broken", "PASS once fixed",
             "PASS (skipped all checks)", "PASS-ish", "PASS rejected by owner")
for i, line in enumerate(QUALIFIED):
    repoN, busN, seatsN = mk_repo(scripts={
        "builder": [BUILD, DONE_CLAIM],
        "qc": [dict(QC_PASS, status_line=line, summary="x")]})
    seatsN["builder"].act_once()
    seatsN["qc"].act_once()
    give_turn(busN, "builder")
    seatsN["builder"].act_once()
    st = busN.state()
    check(f"{26+i}. qualified {line!r} records no PASS", st["status"] != "done" and st["turn"] == "qc")

# Case O: the strict good forms still pass - bare "PASS" (no QC prefix)
repoO, busO, seatsO = mk_repo(scripts={"builder": [BUILD, DONE_CLAIM],
                                       "qc": [dict(QC_PASS, status_line="PASS")]})
seatsO["builder"].act_once()
seatsO["qc"].act_once()
give_turn(busO, "builder")
seatsO["builder"].act_once()
st = busO.state()
check("38. bare 'PASS' verdict still satisfies", st["status"] == "done" and st["turn"] is None)

# Case P/Q (product probe round 3): a QC DONE carrying its own verdict
# text must not close on an earlier PASS - the row is recorded and the
# newest-verdict-wins rule vetoes the close.
for i, line in enumerate(("DONE FAIL", "DONE - found a blocking bug, work is bad")):
    repoX, busX, seatsX = mk_repo(scripts={
        "builder": [BUILD],
        "qc": [dict(QC_PASS, handoff="builder"), dict(DONE_CLAIM, status_line=line)]})
    seatsX["builder"].act_once()
    seatsX["qc"].act_once()       # fresh PASS, hands to builder
    give_turn(busX, "qc")
    seatsX["qc"].act_once()       # QC claims DONE with its own verdict text
    st = busX.state()
    v = [e for e in busX.log() if e.get("kind") == "verdict"]
    check(f"{39+i}. QC {line!r} refused and veto row recorded",
          st["status"] != "done" and st["turn"] == "qc"
          and v[-1]["body"].startswith("verdict NONE at head "))

def set_script(repo, bus, name, script):
    r = bus.roster()
    r["seats"][name]["adapter"] = {"type": "mock", "script": script}
    with open(os.path.join(repo, ".team", "roster.json"), "w") as fh:
        json.dump(r, fh, indent=2)
    return Seat(bus, name)

# Case R (review round 4): an "at head <sha>" claim is binding.
repoR, busR, seatsR = mk_repo(scripts={"builder": [BUILD, DONE_CLAIM], "qc": []})
seatsR["builder"].act_once()
headR = subprocess.run(["git", "-C", repoR, "rev-parse", "HEAD"],
                       capture_output=True, text=True).stdout.strip()
# good: full sha claim matches the real head
seatsR["qc"] = set_script(repoR, busR, "qc",
                          [dict(QC_PASS, status_line="PASS at head " + headR)])
seatsR["qc"].act_once()
give_turn(busR, "builder")
seatsR["builder"].act_once()
st = busR.state()
check("41. 'PASS at head <real sha>' satisfies", st["status"] == "done" and st["turn"] is None)

# good: abbreviated sha (7 chars) prefix-matches
repoS, busS, seatsS = mk_repo(scripts={"builder": [BUILD, DONE_CLAIM], "qc": []})
seatsS["builder"].act_once()
headS = subprocess.run(["git", "-C", repoS, "rev-parse", "HEAD"],
                       capture_output=True, text=True).stdout.strip()
seatsS["qc"] = set_script(repoS, busS, "qc",
                          [dict(QC_PASS, status_line="PASS at head " + headS[:7])])
seatsS["qc"].act_once()
give_turn(busS, "builder")
seatsS["builder"].act_once()
st = busS.state()
check("42. 'PASS at head <7-char prefix>' satisfies", st["status"] == "done" and st["turn"] is None)

# bad: wrong sha records NONE, DONE refused
repoT, busT, seatsT = mk_repo(scripts={"builder": [BUILD, DONE_CLAIM], "qc": []})
seatsT["builder"].act_once()
seatsT["qc"] = set_script(repoT, busT, "qc",
                          [dict(QC_PASS, status_line="PASS at head 0000000")])
seatsT["qc"].act_once()
give_turn(busT, "builder")
seatsT["builder"].act_once()
st = busT.state()
v = [e for e in busT.log() if e.get("kind") == "verdict"]
check("43. 'PASS at head <wrong sha>' records NONE and refuses",
      st["status"] != "done" and st["turn"] == "qc"
      and v[-1]["body"].startswith("verdict NONE at head "))

# bad: "QC DONE" is not a closing form at all (is_done_status needs a
# leading DONE); the turn is refused as a null handoff without DONE.
repoU, busU, seatsU = mk_repo(scripts={
    "builder": [BUILD],
    "qc": [dict(QC_PASS, handoff="builder"), dict(DONE_CLAIM, status_line="QC DONE")]})
seatsU["builder"].act_once()
seatsU["qc"].act_once()
give_turn(busU, "qc")
raised = None
try:
    seatsU["qc"].act_once()
except Exception as e:
    raised = e
st = busU.state()
check("44. 'QC DONE' does not close the cycle (refused as null handoff without DONE)",
      st["status"] != "done" and raised is not None and "null handoff" in str(raised))

for _r in REPOS:
    shutil.rmtree(_r, ignore_errors=True)
print("REVIEWER-SKIP GUARD:", "ALL CHECKS PASSED" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
