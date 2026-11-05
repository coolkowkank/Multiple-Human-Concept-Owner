"""Offline: M1 - a queued response must survive the seat's OWN recorded
transient error, and nothing else that moves the head. Real git lanes, real
`launcher respond`, mock team; no provider, no model."""
import os as _os; _os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import langgraph_team as lt  # noqa: E402
from launcher.bus import Bus, LOG  # noqa: E402
from launcher.runtime import Seat, SeatError, head_binding_clean  # noqa: E402

ok = True
def check(name, cond):
    global ok
    ok = ok and bool(cond)
    print(("PASS  " if cond else "FAIL  ") + name, flush=True)

APP = "def add(a, b):\n    return a + b\n"
TEST = "from src.app import add\nassert add(2, 3) == 5\nprint('ok')\n"
RESP = {"summary": "queued e2e", "writes": {"src/app.py": APP, "tests/test_app.py": TEST},
        "verify_command": "python3 tests/test_app.py", "handoff": "reviewer",
        "status_line": "built"}


def git(repo, *a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)


def head(repo):
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def respond(repo, seat, resp):
    f = os.path.join(tempfile.gettempdir(), f"resp-{os.getpid()}.json")
    json.dump(resp, open(f, "w"))
    env = dict(os.environ); env["PYTHONPATH"] = HERE + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run([sys.executable, "-m", "launcher", "respond", seat, "--file", f,
                        "--repo", repo, "--branch", lt.BRANCH], capture_output=True, text=True, env=env)
    os.unlink(f)
    return p.returncode, p.stdout + p.stderr


def lane(tmp, name):
    r = os.path.join(tmp, name); db = os.path.join(tmp, name + ".sqlite")
    lt.init_repo(r, queue_seats=("builder",))
    lt.run_graph(r, db, stop_after=1, thread_id=name)
    assert Bus(r, lt.BRANCH).state()["turn"] == "builder"
    return r


def stamp(repo):
    line = json.loads(open(os.path.join(repo, ".team", "queues", "builder.jsonl")).readline())
    return line["_queue"]


def trial(repo):
    """One seat loop pass: the loop records a SeatError (LOG-only commit)."""
    seat = Seat(Bus(repo, lt.BRANCH), "builder", poll_interval=1)
    try:
        seat.run(max_passes=1)
        return None
    except SeatError as exc:
        return str(exc)


def commit_log(repo, msg, entries, mutate=None):
    with open(os.path.join(repo, LOG), "a") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")
    if mutate:
        mutate()
    git(repo, "add", "-A")
    return git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-nqm", msg)


tmp = tempfile.mkdtemp()
try:
    # --- end to end: transient failure recorded, same response then applies ---
    r = lane(tmp, "a")
    rc, out = respond(r, "builder", RESP); check("respond queued a bound line", rc == 0)
    b = stamp(r); H = b["head"]
    open(os.path.join(r, "scratch.txt"), "w").write("outside allowed paths")   # transient environment problem
    err = trial(r)
    check("transient failure is recorded as a SeatError (turn not taken)", err and "refuses to start" in err)
    check("the head moved by exactly the seat's LOG-only error record", head(r) != H and [f for f in git(r, "diff", "--name-only", H, "HEAD").stdout.split() if not f.startswith(".team/queues/")] == [LOG])
    check("legacy aggregate rule alone would call it stale (M1 reproduced)", head_binding_clean(r, H) is False)
    check("with the binding, the seat's own error record is clean", head_binding_clean(r, H, b) is True)
    os.unlink(os.path.join(r, "scratch.txt"))
    seat = Seat(Bus(r, lt.BRANCH), "builder", poll_interval=1)
    acted = seat.act_once()
    st = Bus(r, lt.BRANCH).state()
    check("the SAME queued response applies without discard/re-reason", acted is True and st["turn"] == "reviewer" and os.path.exists(os.path.join(r, "src/app.py")))

    # --- the binding still catches real staleness after the error record ---
    r = lane(tmp, "b")
    respond(r, "builder", RESP); b = stamp(r); H = b["head"]
    open(os.path.join(r, "scratch.txt"), "w").write("x"); trial(r); os.unlink(os.path.join(r, "scratch.txt"))
    lt.operator_update_instructions(r, "# Brief v2\nchanged direction\n", note="v2")
    check("brief change after an error record -> stale", head_binding_clean(r, H, b) is False)
    err = Seat(Bus(r, lt.BRANCH), "builder", poll_interval=1)
    try:
        err.act_once(); applied = True
    except SeatError as e:
        applied = "stale" in str(e)
    check("seat refuses the stale response after an operator instruction change", applied is True and Bus(r, lt.BRANCH).state()["turn"] == "builder")

    # --- adversarial forged / look-alike LOG commits ---
    base = lane(tmp, "c"); respond(base, "builder", RESP); b = stamp(base); H = b["head"]
    ts = b["turn_seq"]
    def variant(name, msg, entries, mutate=None):
        d = os.path.join(tmp, "v-" + name); shutil.copytree(base, d)
        c = commit_log(d, msg, entries, mutate)
        assert c.returncode == 0, (name, c.stderr)
        return d
    good_msg = "TURN: builder error recorded (turn not taken)"
    good = {"ts": "t", "seat": "builder", "kind": "error", "body": "x"}
    check("exact own error record: clean", head_binding_clean(variant("ok", good_msg, [good]), H, b) is True)
    check("error record with the bound turn_seq: clean", head_binding_clean(variant("ts", good_msg, [dict(good, turn_seq=ts)]), H, b) is True)
    check("error record for another turn_seq: stale", head_binding_clean(variant("ts2", good_msg, [dict(good, turn_seq=ts + 5)]), H, b) is False)
    check("another seat's error entry: stale", head_binding_clean(variant("seat", good_msg, [dict(good, seat="reviewer")]), H, b) is False)
    check("non-error kind (a note) with the right message: stale", head_binding_clean(variant("kind", good_msg, [dict(good, kind="note")]), H, b) is False)
    check("look-alike commit message: stale", head_binding_clean(variant("msg", "TURN: builder error recorded", [good]), H, b) is False)
    check("other seat's commit message: stale", head_binding_clean(variant("msg2", "TURN: reviewer error recorded (turn not taken)", [good]), H, b) is False)
    check("error record plus a brief edit in the same commit: stale", head_binding_clean(variant("brief", good_msg, [good], lambda: open(os.path.join(tmp, "v-brief", ".team", "brief.md"), "a").write("\nextra\n")), H, b) is False)
    def rewrite():
        p = os.path.join(tmp, "v-rewrite", LOG); lines = open(p).read().splitlines(True)
        open(p, "w").write("".join(lines[1:]))
    check("a commit that deletes an earlier LOG line: stale", head_binding_clean(variant("rewrite", good_msg, [good], rewrite), H, b) is False)
    check("garbage appended to the LOG: stale", head_binding_clean(variant("junk", good_msg, [], lambda: open(os.path.join(tmp, "v-junk", LOG), "a").write("not json\n")), H, b) is False)
    check("empty change (no added entry): stale", head_binding_clean(variant("none", good_msg, [], lambda: open(os.path.join(tmp, "v-none", "src_marker"), "w").write("x")), H, b) is False)
    d = os.path.join(tmp, "v-merge"); shutil.copytree(base, d)
    git(d, "checkout", "-qb", "side"); commit_log(d, "TURN: builder side", [], lambda: open(os.path.join(d, "side.txt"), "w").write("s"))
    git(d, "checkout", "-q", lt.BRANCH)
    commit_log(d, good_msg, [good])
    mg = git(d, "-c", "user.name=t", "-c", "user.email=t@t", "merge", "--no-ff", "--no-verify", "-qm", "TURN: builder merge", "side")
    assert mg.returncode == 0, mg.stderr + mg.stdout
    check("a merge in the range: stale", head_binding_clean(d, H, b) is False)
    d = variant("queueonly", "TURN: builder q", [], lambda: (os.makedirs(os.path.join(tmp, "v-queueonly", ".team", "queues"), exist_ok=True), open(os.path.join(tmp, "v-queueonly", ".team", "queues", "other.jsonl"), "w").write("{}\n")))
    check("queue-file-only commit: still clean (unchanged rule)", head_binding_clean(d, H, b) is True)
    check("unknown stamped head: stale", head_binding_clean(base, "0" * 40, b) is False and head_binding_clean(base, None, b) is False)
    check("binding without a seat name: stale for an error record", head_binding_clean(variant("noseat", good_msg, [good]), H, {"turn": None, "turn_seq": ts}) is False)

    # --- respond's stale scan uses the same rule ---
    r = lane(tmp, "d"); respond(r, "builder", RESP); b = stamp(r)
    open(os.path.join(r, "scratch.txt"), "w").write("x"); trial(r); os.unlink(os.path.join(r, "scratch.txt"))
    rc, out = respond(r, "builder", dict(RESP, summary="second"))
    q = [json.loads(l) for l in open(os.path.join(r, ".team", "queues", "builder.jsonl")) if l.strip()]
    check("respond does not call the error-recorded line stale (no --discard-stale needed)", rc == 0 and len(q) == 2)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nBINDING RECOVERY (M1):", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
raise SystemExit(0 if ok else 1)
