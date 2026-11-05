"""Command line: init, seat, launch, status, demo, guard, answer."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from .adapters import MockAdapter
from .bus import Bus, BusError, BusPushUnknown, EXIT_PUSH_UNKNOWN
from .runtime import Seat
from .supervisor import Supervisor

def _hook_text():
    pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return ("#!/bin/sh\nPYTHONPATH=\"%s\" exec python3 -m launcher guard "
            "--message-file \"$1\"\n" % pkg_parent)



def _prep_repo(path):
    repo = os.path.abspath(path)
    os.makedirs(repo, exist_ok=True)
    if subprocess.run(["git", "-C", repo, "rev-parse", "--git-dir"],
                      capture_output=True).returncode != 0:
        subprocess.run(["git", "-C", repo, "init"], check=True,
                       capture_output=True)
    return repo


def cmd_init(args):
    repo = _prep_repo(args.repo)
    bus = Bus(repo, args.branch)
    current = subprocess.run(
        ["git", "-C", repo, "branch", "--show-current"],
        capture_output=True, text=True).stdout.strip()
    if current != args.branch:
        subprocess.run(["git", "-C", repo, "checkout", "-B", args.branch],
                       check=True, capture_output=True)
    roster = {"seats": default_roster()} if args.default_roster else None
    brief = open(args.brief).read() if args.brief else ""
    bus.init_layout(brief_text=brief, roster=roster)
    hook = os.path.join(repo, ".git", "hooks", "commit-msg")
    with open(hook, "w") as fh:
        fh.write(_hook_text())
    os.chmod(hook, 0o755)
    print(f"initialized .team bus on branch {args.branch} in {repo}")


def cmd_seat(args):
    bus = Bus(args.repo, args.branch)
    relay = None
    relay_url = args.relay_url or os.environ.get("TEAM_RELAY_URL")
    token = os.environ.get("TEAM_RELAY_TOKEN")
    if relay_url and token:
        from .relay import RelayClient
        relay = RelayClient(relay_url, token)
    webhook = None
    hook_url = os.environ.get("TEAM_WAKE_WEBHOOK")
    if hook_url:
        from .relay import WebhookSink
        webhook = WebhookSink(hook_url)
    seat = Seat(bus, args.name, poll_interval=args.poll, relay=relay,
                webhook=webhook)
    from .runtime import TornStateError, EXIT_TORN_STATE
    try:
        if args.once:
            acted = seat.act_once()
            print(f"{args.name}: {'acted' if acted else 'not our turn'}")
            return
        seat.run()
    except TornStateError as exc:
        print(f"{args.name}: BLOCKED ({exc.code}): {exc}", file=sys.stderr,
              flush=True)
        raise SystemExit(EXIT_TORN_STATE)
    except BusPushUnknown as exc:
        print(f"{args.name}: STOPPED (push_outcome_unknown): the turn commit "
              "is kept locally and may have landed. Not restarted, not "
              "retried. Check the remote before relaunching.",
              file=sys.stderr, flush=True)
        raise SystemExit(EXIT_PUSH_UNKNOWN)


def unbounded_http_seats(repo, branch):
    """Seat names whose http adapter has no provider call budget.

    An unattended (supervised) http seat without a budget can make
    unbounded provider requests; launch fails closed on these unless the
    operator explicitly passes --allow-unbounded."""
    roster = Bus(repo, branch).roster().get("seats", {})
    return sorted(name for name, spec in roster.items()
                  if spec.get("adapter", {}).get("type") == "http"
                  and spec["adapter"].get("call_budget") is None)


def cmd_launch(args):
    unbounded = unbounded_http_seats(args.repo, args.branch)
    if unbounded and not args.allow_unbounded:
        raise SystemExit(
            "refusing unattended launch: http seat(s) "
            f"{', '.join(unbounded)} have no call_budget in .team/roster.json; "
            "set a per-seat request budget (+usage_log) or pass "
            "--allow-unbounded to accept unbounded provider requests")
    sup = Supervisor(
        args.repo, args.branch, stall_timeout=args.stall_timeout,
        poll=args.poll)
    result = sup.run(max_seconds=args.max_seconds)
    print(f"supervisor: {result}")


def cmd_status(args):
    bus = Bus(args.repo, args.branch)
    bus.pull()
    state = bus.state()
    print(f"status: {state['status']} | turn: {state['turn']} | "
          f"seq: {state['turn_seq']}")
    print(f"line:   {state['status_line']}")
    for entry in bus.log(limit=args.lines):
        print(f"  [{entry['ts']}] {entry['seat']} ({entry['kind']}): "
              f"{entry['body']}")
    for gate in bus.pending_gates():
        print(f"  OPEN GATE {gate['id']} from {gate['seat']}: "
              f"{gate['question']}")


def cmd_answer(args):
    bus = Bus(args.repo, args.branch)
    # Message needs the operational prefix or the installed commit
    # guard rejects it (R2). Roll back the append if the commit fails,
    # so a retry cannot duplicate the answer line (R3 pattern).
    answers = os.path.join(bus.repo, ".team/gates/ANSWERS.jsonl")
    snapshot = open(answers).read() if os.path.exists(answers) else None
    try:
        bus.transact_paths(f"operator: gate {args.gate_id} answered",
                           [".team/gates/ANSWERS.jsonl"],
                           lambda: bus.answer_gate(args.gate_id,
                                                   args.answer))
    except BusPushUnknown:
        # The answer commit is KEPT locally and may have landed: do NOT
        # restore the snapshot (that would leave the worktree different from
        # HEAD and a later commit could undo the answer).
        print(f"answer for gate {args.gate_id} is committed locally; the push "
              "outcome is unknown. Do not repeat it. Check the remote.",
              file=sys.stderr)
        raise
    except Exception:
        if snapshot is not None:
            with open(answers, "w") as fh:
                fh.write(snapshot)
        raise


def cmd_lease(args):
    """Show a seat's session lease, or (operator-attested) release it.

    A lease is written only by a COMPLETED turn and is a liveness hint, not
    the correctness mechanism (turn/turn_seq + the transaction already stop a
    duplicate apply). A successor session (new clone/machine, or a restart
    with a new session id) is refused until the lease is older than the TTL
    (900s). This command is the bounded operator recovery for that wait:
    --release requires --holder HOLDER, which must equal the CURRENT holder
    (compare-and-set: you cannot release a lease you did not inspect), runs
    under the repo action lock, changes only STATE.json's leases entry, and
    never touches turn, turn_seq, status, log or queues. Because STATE.json
    changes, queued responses bound to an older head are stale and must be
    re-queued: the head binding is not weakened."""
    import re as _re
    import time as _t
    from .bus import STATE
    ident = _re.compile(r"^[A-Za-z0-9._:@-]{1,128}$")

    def refuse(msg):
        print("refused: " + msg, file=sys.stderr)
        sys.exit(1)

    def state_clean():
        # worktree STATE.json must equal HEAD: the release commit may
        # carry the leases deletion ONLY, never someone's unrelated edit
        return subprocess.run(
            ["git", "-C", bus.repo, "diff", "--quiet", "HEAD", "--", STATE],
            capture_output=True).returncode == 0

    def read_lease(state):
        leases = state.get("leases", {}) if isinstance(state, dict) else None
        if not isinstance(leases, dict):
            refuse("STATE.json leases is malformed")
        lease = leases.get(args.name)
        if lease is None:
            return None
        if (not isinstance(lease, dict)
                or not isinstance(lease.get("holder"), str)
                or not ident.match(lease["holder"])
                or isinstance(lease.get("claimed_at"), bool)
                or not isinstance(lease.get("claimed_at"), (int, float))
                or lease["claimed_at"] != lease["claimed_at"]
                or lease["claimed_at"] in (float("inf"), float("-inf"))):
            refuse(f"lease for {args.name} is malformed; fix STATE.json by hand")
        return lease

    if not ident.match(args.name):
        refuse("seat name has characters outside [A-Za-z0-9._:@-]")
    if args.holder is not None and not ident.match(args.holder):
        refuse("--holder has characters outside [A-Za-z0-9._:@-]")
    bus = Bus(args.repo, args.branch)
    cur_branch = subprocess.run(
        ["git", "-C", bus.repo, "symbolic-ref", "--short", "-q", "HEAD"],
        capture_output=True, text=True).stdout.strip()
    if cur_branch != args.branch:
        refuse(f"checked-out branch is {cur_branch or 'detached HEAD'!r}, "
               f"not the bus branch {args.branch!r} (--branch)")
    bus.pull()   # git fetch/rebase: show mode is not a pure local read
    if args.name not in bus.roster().get("seats", {}):
        refuse(f"seat {args.name!r} not in roster")
    if args.release and not state_clean():
        refuse("worktree .team/STATE.json differs from HEAD; commit or "
               "restore it first (the release must change only the lease)")
    lease = read_lease(bus.state())
    if lease is None:
        print(f"lease {args.name}: none")
        if args.release:
            sys.exit(1)
        return
    age = _t.time() - lease["claimed_at"]
    print(f"lease {args.name}: holder={lease['holder']} "
          f"age={int(age)}s (a different session is refused for 900s)")
    if not args.release:
        return
    if args.holder != lease["holder"]:
        refuse("--release needs --holder equal to the holder shown above "
               "(compare-and-set)")
    seen = lease["holder"]

    def mutate():
        if not state_clean():
            raise BusError("STATE.json changed in the worktree; refusing")
        state = bus.state()
        cur = read_lease(state)
        if cur is None or cur["holder"] != seen:
            raise BusError(f"lease for {args.name} changed; re-inspect")
        del state["leases"][args.name]
        bus.write_state(state)

    try:
        with bus.action_lock():
            bus.transact_paths(
                f"operator: lease released for {args.name} (holder {seen})",
                [STATE], mutate)
    except BusPushUnknown:
        print(f"lease release for {args.name} is committed locally; the push "
              "outcome is unknown. Do not repeat it. Check the remote.",
              file=sys.stderr)
        sys.exit(EXIT_PUSH_UNKNOWN)
    except BusError as exc:
        refuse(f"release not committed: {str(exc)[:300]}")
    print(f"released lease {args.name} (was {seen}); re-queue any queued "
          "response for this bus state")


def cmd_prompt(args):
    """Print the exact (system, task) prompt a seat would receive this
    turn, so an external operator (interactive paste session, or an
    assistant-mediated agent) reasons against the real input."""
    bus = Bus(args.repo, args.branch)
    bus.pull()
    state = bus.state()
    seat = Seat(bus, args.name)
    if state.get("turn") != args.name:
        print(f"note: turn is {state.get('turn')!r}, not {args.name!r}; "
              "rendering the prompt as if it were", file=sys.stderr)
    system, task = seat.build_prompt(state)
    print("=== SYSTEM ===")
    print(system)
    print("=== TASK ===")
    print(task)
    if getattr(args, "measure", False):
        from launcher.token_est import measure_prompt
        m = measure_prompt(system, task)
        print(f"measure: system={m['system_chars']}c "
              f"task={m['task_chars']}c total={m['total_chars']}c "
              f"est_tokens={m['est_tokens']} "
              "(estimate: total_chars/4)")


def cmd_respond(args):
    """Queue an externally-reasoned response for a `queue` seat, then
    commit it (durable before the turn runs). The turn itself is taken
    by `launcher seat NAME --once`, which applies the response through
    the real seat path: lease, path checks, verify command, record."""
    bus = Bus(args.repo, args.branch)
    spec = bus.roster().get("seats", {}).get(args.name)
    if not spec:
        print(f"seat {args.name!r} not in roster", file=sys.stderr)
        sys.exit(1)
    adapter = spec.get("adapter", {})
    if adapter.get("type") != "queue":
        print(f"seat {args.name!r} adapter is {adapter.get('type')!r}, "
              "not 'queue'; respond only feeds queue seats",
              file=sys.stderr)
        sys.exit(1)
    path = adapter["path"]
    if not os.path.isabs(path):
        path = os.path.join(bus.repo, path)
    try:
        with open(args.file) as fh:
            response = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"response file is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(response, dict):
        print("response must be one JSON object", file=sys.stderr)
        sys.exit(1)
    # Bind the response to the bus state it was reasoned against
    # (live-1 major finding: an unbound queued response could be
    # applied silently after the bus moved). The runtime refuses the
    # apply when turn/turn_seq/head have moved on.
    # A pre-staged index would fail the commit AFTER the queue line is
    # appended, leaving uncommitted residue and duplicate lines on
    # retry (R3) - check before touching the file.
    bus.assert_index_clean(f"queue a response for {args.name}")
    state = bus.state()
    head = subprocess.run(["git", "-C", bus.repo, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    # Stale lines already in the queue would be refused by the runtime
    # forever (the seat always reads the first line), so appending
    # behind one strands the fresh response. Refuse unless the operator
    # explicitly discards the stale lines (live-1 patch review). The
    # staleness test is the SAME one the seat applies: turn/seq AND
    # head binding (R1) - a head-stale line must be discardable too.
    from launcher.runtime import head_binding_clean
    stale = []
    if os.path.exists(path):
        with open(path) as fh:
            existing = [json.loads(line) for line in fh if line.strip()]
        for line in existing:
            bound = line.get("_queue")
            if (bound is None
                    or bound.get("turn") != state.get("turn")
                    or bound.get("turn_seq") != state.get("turn_seq")
                    or not head_binding_clean(
                        bus.repo, bound.get("head"), bound)):
                stale.append(line)
    if stale:
        if not args.discard_stale:
            print(f"queue for {args.name} holds {len(stale)} stale "
                  "line(s) the runtime would refuse; re-queue with "
                  "--discard-stale to drop them, or clear the queue "
                  "file yourself", file=sys.stderr)
            sys.exit(1)
        with open(path) as fh:
            kept = [json.loads(line) for line in fh if line.strip()]
        kept = [line for line in kept if line not in stale]
        with open(path, "w") as fh:
            for line in kept:
                fh.write(json.dumps(line) + "\n")
        print(f"discarded {len(stale)} stale queued line(s) for "
              f"{args.name}")
    response["_queue"] = {"turn": state.get("turn"),
                          "turn_seq": state.get("turn_seq"),
                          "head": head}
    os.makedirs(os.path.dirname(path) or bus.repo, exist_ok=True)
    # Snapshot so a failed commit (e.g. guard rejection) rolls the
    # append back: no uncommitted line, no duplicate on retry (R3).
    snapshot = open(path).read() if os.path.exists(path) else None
    with open(path, "a") as fh:
        fh.write(json.dumps(response) + "\n")
    rel = os.path.relpath(path, bus.repo)
    try:
        bus.commit_paths(f"operator: response queued for {args.name}",
                         [rel])
    except Exception:
        if snapshot is None:
            os.unlink(path)
        else:
            with open(path, "w") as fh:
                fh.write(snapshot)
        raise
    current = subprocess.run(
        ["git", "-C", bus.repo, "branch", "--show-current"],
        capture_output=True, text=True).stdout.strip()
    hint_branch = current or bus.branch
    extra = ""
    if current and current != bus.branch:
        extra = (f" [note: checkout is on {current!r}, respond used "
                 f"--branch {bus.branch!r}]")
    print(f"queued response for {args.name} (bound to "
          f"turn={state.get('turn')!r} seq={state.get('turn_seq')} "
          f"head={head[:12]}); run `python3 -m launcher seat {args.name} "
          f"--repo {bus.repo} --branch {hint_branch} --once` to take "
          f"the turn{extra}")


def _cmd_serve(args):
    import secrets
    from .relay import serve
    token = os.environ.get("TEAM_RELAY_TOKEN") or secrets.token_hex(16)
    print(f"relay on 127.0.0.1:{args.port} "
          f"(token in TEAM_RELAY_TOKEN env, never committed)", flush=True)
    os.environ["TEAM_RELAY_TOKEN"] = token
    serve(args.port, token)


def default_roster():
    """The blueprint's delivery seats as a ready roster (mock adapters;
    swap in cli/http adapters for live models)."""
    return {
        "coordinator": {"role": "coordinator",
                        "allowed_paths": [".team/"],
                        "adapter": {"type": "mock", "script": []}},
        "builder": {"role": "builder",
                    "allowed_paths": ["src/", "tests/"],
                    "adapter": {"type": "mock", "script": []}},
        "reviewer": {"role": "reviewer",
                     "allowed_paths": ["review/"],
                     "adapter": {"type": "mock", "script": []}},
        "qc": {"role": "qc",
               "allowed_paths": ["review/"],
               "adapter": {"type": "mock", "script": []}},
        "records": {"role": "records",
                    "allowed_paths": ["records/"],
                    "adapter": {"type": "mock", "script": []}},
    }


def cmd_demo(args):
    """Full team cycle in a fresh repo with scripted mock adapters.

    Proves the mechanism end to end - turn token, handoffs, guard,
    recovery - with no keys and no spend. It is not evidence of model
    quality or of a real week-long run; see docs/proposed-vs-tested.md.
    """
    from .demo import run_demo
    run_demo(args.dir)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="launcher")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def base(p):
        p.add_argument("--repo", default=".")
        p.add_argument("--branch", default="team-work")

    p = sub.add_parser("init", help="create the .team bus in a repo")
    base(p)
    p.add_argument("--brief")
    p.add_argument("--default-roster", action="store_true")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("seat", help="run one seat process")
    base(p)
    p.add_argument("name")
    p.add_argument("--once", action="store_true")
    p.add_argument("--poll", type=int, default=5)
    p.add_argument("--relay-url")
    p.set_defaults(fn=cmd_seat)

    p = sub.add_parser("launch", help="supervise all automated seats")
    base(p)
    p.add_argument("--stall-timeout", type=int, default=900)
    p.add_argument("--allow-unbounded", action="store_true",
                   help="permit http seats without a call_budget (unbounded provider requests)")
    p.add_argument("--poll", type=int, default=5)
    p.add_argument("--max-seconds", type=int)
    p.set_defaults(fn=cmd_launch)

    p = sub.add_parser("status", help="print turn, log tail, open gates")
    base(p)
    p.add_argument("--lines", type=int, default=10)
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("serve", help="loopback relay server (127.0.0.1)")
    p.add_argument("--port", type=int, required=True)
    p.set_defaults(fn=lambda a: _cmd_serve(a))

    p = sub.add_parser("answer", help="answer a human gate")
    base(p)
    p.add_argument("gate_id")
    p.add_argument("answer")
    p.set_defaults(fn=cmd_answer)

    p = sub.add_parser("prompt", help="render the seat's exact prompt this turn")
    base(p)
    p.add_argument("name")
    p.add_argument("--measure", action="store_true",
                   help="also print char counts and a chars/4 token "
                        "estimate for the rendered prompt")
    p.set_defaults(fn=cmd_prompt)

    p = sub.add_parser("respond", help="queue an externally-reasoned response")
    base(p)
    p.add_argument("name")
    p.add_argument("--file", required=True)
    p.add_argument("--discard-stale", action="store_true",
                   help="drop stale queued lines (bound to an old "
                        "turn/seq) before appending; without it a "
                        "stale queue is an error, not a silent append")
    p.set_defaults(fn=cmd_respond)

    p = sub.add_parser("lease", help="show or (operator-attested) release a seat session lease")
    base(p)
    p.add_argument("name")
    p.add_argument("--release", action="store_true")
    p.add_argument("--holder", help="the holder shown by `lease NAME`; required with --release")
    p.set_defaults(fn=cmd_lease)

    p = sub.add_parser("conform", help="check .team against the evidence interface")
    p.add_argument("--repo", default=".")
    p.set_defaults(fn=lambda a: sys.exit(
        __import__("launcher.conformance", fromlist=["main"]).main(
            ["--repo", a.repo])))

    p = sub.add_parser("demo", help="self-checking full cycle, mock seats")
    p.add_argument("--dir", default="/tmp/team-launcher-demo")
    p.set_defaults(fn=cmd_demo)

    p = sub.add_parser("guard", help="pre-commit turn/path checks")
    p.add_argument("--message-file")
    p.add_argument("--repo", default=".")
    p.set_defaults(fn=lambda a: sys.exit(
        __import__("launcher.guards", fromlist=["main"]).main(
            (["--message-file", a.message_file] if a.message_file else [])
            + ["--repo", a.repo])))

    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
