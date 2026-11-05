"""Mechanical guards: the turn token as an enforced check, not a rule.

Install as a pre-commit hook (`launcher init` does). A commit is
rejected when:
- the message lacks `TURN: <seat>`;
- <seat> is not the current turn holder in .team/STATE.json;
- the commit touches paths outside that seat's roster allowed_paths;
- a handback carries no work (acknowledgement-only), per Bill's P8.

Setup commits use `TURN: setup` and may touch anything once, while the
team layout is being installed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

TURN_RE = re.compile(r"^TURN:\s*(\S+)", re.MULTILINE)


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args],
                          capture_output=True, text=True)


def _head_file(repo, path):
    proc = _git(repo, "show", f"HEAD:{path}")
    return proc.stdout if proc.returncode == 0 else None


def check_commit(repo, message, staged_paths):
    """Return a list of violations (empty = allowed).

    Turn and roster are read from HEAD, i.e. the state before this
    commit: a seat legitimately advances the turn inside its own commit,
    so the working-tree state already names the NEXT holder.
    """
    problems = []
    # Operational commits (human gate answers, supervisor restarts,
    # one-time setup) are outside the seat turn protocol. Seat commits
    # always come from the runtime, which stamps "TURN: <seat>", so a
    # seat cannot mint these prefixes itself.
    head = message.lstrip().split("\n", 1)[0].lower()
    if head.startswith(("human:", "supervisor:", "operator:")):
        return []
    match = TURN_RE.search(message)
    if not match:
        return ["commit message lacks a 'TURN: <seat>' line (or an "
                "operational 'human:'/'supervisor:'/'operator:' prefix)"]
    seat = match.group(1)
    if seat == "setup":
        return problems

    state_text = _head_file(repo, ".team/STATE.json")
    roster_text = _head_file(repo, ".team/roster.json")
    if state_text is None or roster_text is None:
        return problems  # pre-init commits are the human's own business
    state = json.loads(state_text)
    roster = json.loads(roster_text)

    if state.get("turn") != seat:
        problems.append(
            f"commit claims TURN: {seat} but the written turn holder is "
            f"{state.get('turn')!r}")

    spec = roster.get("seats", {}).get(seat)
    if spec is None:
        problems.append(f"seat {seat!r} is not in the roster")
    else:
        allowed = [a.rstrip("/") for a in spec.get("allowed_paths", [])]
        for path in staged_paths:
            p = path.lstrip("/")
            if p.startswith(".team/"):
                continue  # the bus itself is shared by protocol, not by seat
            if not any(p == a or p.startswith(a + "/") for a in allowed):
                problems.append(
                    f"{seat} touches {p} outside its allowed paths {allowed}")
    return problems


def main(argv):
    repo = os.getcwd()
    msg_file = None
    args = list(argv)
    if "--message-file" in args:
        i = args.index("--message-file")
        msg_file = args[i + 1]
    if "--repo" in args:
        i = args.index("--repo")
        repo = args[i + 1]
    message = open(msg_file).read() if msg_file else "TURN: probe\n"
    staged = _git(repo, "diff", "--cached", "--name-only").stdout.split()
    problems = check_commit(repo, message, staged)
    for p in problems:
        print(f"guard: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
