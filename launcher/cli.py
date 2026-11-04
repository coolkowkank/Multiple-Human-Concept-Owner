"""Command line: init, seat, launch, status, demo, guard, answer."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from .adapters import MockAdapter
from .bus import Bus
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
    if args.once:
        acted = seat.act_once()
        print(f"{args.name}: {'acted' if acted else 'not our turn'}")
        return
    seat.run()


def cmd_launch(args):
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
    bus.transact(f"gate {args.gate_id} answered",
                 lambda: bus.answer_gate(args.gate_id, args.answer))


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
    # apply when turn/turn_seq have moved on.
    state = bus.state()
    head = subprocess.run(["git", "-C", bus.repo, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    response["_queue"] = {"turn": state.get("turn"),
                          "turn_seq": state.get("turn_seq"),
                          "head": head}
    os.makedirs(os.path.dirname(path) or bus.repo, exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(response) + "\n")
    rel = os.path.relpath(path, bus.repo)
    bus.commit_paths(f"operator: response queued for {args.name}", [rel])
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
    p.set_defaults(fn=cmd_prompt)

    p = sub.add_parser("respond", help="queue an externally-reasoned response")
    base(p)
    p.add_argument("name")
    p.add_argument("--file", required=True)
    p.set_defaults(fn=cmd_respond)

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
