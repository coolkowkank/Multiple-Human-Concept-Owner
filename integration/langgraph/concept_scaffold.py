#!/usr/bin/env python3
"""Concept-in / team-out scaffolding: one command from a project concept
to a conformant team repo ready for its first turn.

    python3 concept_scaffold.py NEW_DIR --concept-file CONCEPT.md
    python3 concept_scaffold.py NEW_DIR --concept "one-line concept"

What it does, in order (fully offline - no keys, no model calls):
  1. creates NEW_DIR (refuses root, home, cwd and any non-empty
     directory) and `git init`s it on the team branch;
  2. runs the real `launcher init` with the default five-seat roster and
     the concept as .team/brief.md;
  3. points every seat at the QUEUE adapter (.team/queues/<seat>.jsonl):
     seats act only on responses the operator (or an approved model
     route) queues through `python3 -m launcher respond` - the reviewed
     reasoning boundary. An empty queue is an explicit "seat waits"
     error, never a faked answer. No mock scripts are written: mock
     adapters prove harness mechanics with the bundled add(a,b) demo
     (`python3 -m launcher demo`), not with your concept;
  4. issues the first turn to the coordinator (status running, run
     control on) - the same human-step the demo performs by hand;
  5. runs `launcher conform` on the result and refuses to print a
     success summary unless the evidence interface passes.

It does NOT run the team. With queue seats the team moves only when
someone answers a prompt, so the scaffolded repo sits at the
coordinator's first turn until the operator drives it:

    python3 -m launcher status --repo NEW_DIR
    python3 -m launcher prompt coordinator --repo NEW_DIR
    python3 -m launcher respond coordinator --repo NEW_DIR --file R.json
    python3 -m launcher seat coordinator --repo NEW_DIR --once
    python3 langgraph_team.py run NEW_DIR /path/to/checkpoints.sqlite3

`launcher demo` remains the self-running proof of the mechanics (mock
seats, bundled brief); this scaffold is the same harness holding YOUR
concept, driven through the honest queue boundary instead.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROSTER = ["coordinator", "builder", "reviewer", "qc", "records"]
FORBIDDEN = {"/", os.path.expanduser("~"), os.path.abspath(os.getcwd())}


def _die(msg):
    print(f"concept_scaffold: {msg}", file=sys.stderr)
    sys.exit(1)


def _git(repo, *args, check=True):
    return subprocess.run(["git", "-C", repo, *args], check=check,
                          capture_output=True, text=True)


def _run(cmd, label):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        _die(f"{label} failed (exit {proc.returncode})")
    return proc


def scaffold(repo, concept, branch="team"):
    """Build the scaffold; return the coordinator name. See module doc."""
    if repo in FORBIDDEN:
        _die(f"refused: {repo} is a forbidden location")
    if os.path.exists(repo):
        if not os.path.isdir(repo):
            _die(f"refused: {repo} exists and is not a directory")
        if os.listdir(repo):
            _die(f"refused: {repo} is non-empty; delete it by hand if it "
                 f"is really disposable")
    else:
        os.makedirs(repo)

    concept = concept.strip() + "\n"
    brief_path = os.path.join(repo, ".concept-brief.md")
    with open(brief_path, "w") as fh:
        fh.write(concept)

    _git(repo, "init", "-b", branch)
    # A local identity so init commits land without inheriting the
    # operator's global git config; change it freely, it is per-repo.
    _git(repo, "config", "user.name", "concept-team")
    _git(repo, "config", "user.email", "concept-team@localhost")

    _run([sys.executable, "-m", "launcher", "init",
          "--repo", repo, "--branch", branch,
          "--default-roster", "--brief", brief_path], "launcher init")
    os.remove(brief_path)

    # Queue seats: reasoning enters only through `launcher respond`.
    roster_path = os.path.join(repo, ".team", "roster.json")
    with open(roster_path) as fh:
        roster = json.load(fh)
    queue_dir = os.path.join(repo, ".team", "queues")
    os.makedirs(queue_dir, exist_ok=True)
    for name, spec in roster["seats"].items():
        spec["adapter"] = {"type": "queue",
                           "path": f".team/queues/{name}.jsonl"}
        open(os.path.join(queue_dir, f"{name}.jsonl"), "w").close()
    with open(roster_path, "w") as fh:
        json.dump(roster, fh, indent=2)
        fh.write("\n")

    # First turn to the coordinator, status running, run control on -
    # the human step the demo performs by hand.
    state_path = os.path.join(repo, ".team", "STATE.json")
    with open(state_path) as fh:
        state = json.load(fh)
    state["turn"] = "coordinator"
    state["status"] = "running"
    with open(state_path, "w") as fh:
        json.dump(state, fh, indent=2)
        fh.write("\n")
    with open(os.path.join(repo, ".team", "CONTROL.json"), "w") as fh:
        json.dump({"mode": "run", "instruction_seq": 1,
                   "note": "concept agreed, first turn issued"}, fh,
                  indent=2)
        fh.write("\n")

    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "human: concept agreed, first turn issued")

    proc = _run([sys.executable, "-m", "launcher", "conform",
                 "--repo", repo], "launcher conform")
    sys.stdout.write(proc.stdout)
    return roster


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Scaffold a conformant concept team repo (offline).")
    ap.add_argument("repo", help="new empty directory to create")
    ap.add_argument("--branch", default="team")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--concept", help="the project concept, inline")
    group.add_argument("--concept-file",
                       help="file holding the project concept")
    args = ap.parse_args(argv)

    if args.concept_file:
        try:
            with open(args.concept_file) as fh:
                concept = fh.read()
        except OSError as exc:
            _die(f"cannot read concept file: {exc}")
    else:
        concept = args.concept
    if not concept.strip():
        _die("concept is empty")

    repo = os.path.abspath(args.repo)
    scaffold(repo, concept, args.branch)
    print(f"\nScaffolded concept team at {repo}")
    print("The repo sits at the coordinator's first turn. Drive it:")
    print(f"  python3 -m launcher prompt coordinator --repo {repo}")
    print(f"  python3 -m launcher respond coordinator --repo {repo} "
          f"--file R.json")
    print(f"  python3 -m launcher seat coordinator --repo {repo} --once")
    print("or run the graph (waits at each seat for a queued response):")
    print(f"  python3 {os.path.join(HERE, 'langgraph_team.py')} run "
          f"{repo} /path/to/checkpoints.sqlite3")


if __name__ == "__main__":
    main()
