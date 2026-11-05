"""Handover self-check for a new operator (human or AI). Offline, read-only.

    python3 handover_check.py env  [--repo DIR]
    python3 handover_check.py state --root RUNNER_ROOT [--log-dir SHARED_LOG_DIR]

env:   checks the fresh environment (python, pinned packages, git identity,
       account HOME, bwrap/prlimit, vendored pins, clean tree). Prints names
       and yes/no only. Never prints a secret value. Makes no network call.
state: PRIVATE summary of an existing runner root and the shared request
       log, for a private handover only. Counts, ids, hashes and halt
       reasons the code itself wrote; never prompts, completions, key file
       contents or env values. Do not publish its output. It writes
       nothing, takes no lock and creates no directory.

Exit 0 only when no blocking problem was found. This is a setup and state
report. It does not qualify any model route, clear any halt, or approve any
call. A halt that stands in the output still stands.
"""
import hashlib, importlib.metadata as md, json, os, pwd, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PINS = {"langgraph": "1.2.19", "langgraph-checkpoint-sqlite": "3.1.3"}
FILE_PINS = {  # md5 pins the repo already asserts elsewhere; reported, not invented
    "launcher/quality_gate.py": "9de29c89f52245cacce2f82ed5138c89",
    "launcher/usage_join.py": "d00259978e57bebfba30ee5f6e8121ab",
    "runner/ryan_cycle.py": "09cdaae1b857231f15fa49cf770ebaa8",
}
SECRET_ENV = ("REQUESTY_API_KEY", "RYAN_ALLOWANCE_KEY_FILE")
MAX_LINES = 200000


def _md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def _sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def env_report(repo=None):
    rep, block, warn = {}, [], []
    rep["python"] = sys.version.split()[0]
    if sys.version_info < (3, 10):
        block.append("python >= 3.10 required")
    pk = {}
    for name, want in PINS.items():
        try:
            got = md.version(name)
        except md.PackageNotFoundError:
            got = None
        pk[name] = {"want": want, "got": got}
        if got != want:
            block.append("package %s: want %s, got %s" % (name, want, got))
    rep["packages"] = pk
    for tool in ("git", "bwrap", "prlimit"):
        rep["tool_" + tool] = bool(shutil.which(tool))
        if not shutil.which(tool):
            (block if tool == "git" else warn).append(
                "%s not found%s" % (tool, "" if tool == "git" else " (needed for model-backed runs and closeout, not for offline tests that skip the sandbox)"))
    gi = subprocess.run(["git", "config", "--get-regexp", r"^user\.(name|email)$"],
                        capture_output=True, text=True).stdout
    rep["git_identity_set"] = ("user.name" in gi and "user.email" in gi)
    if not rep["git_identity_set"]:
        block.append("git user.name/user.email not set (bus commits fail)")
    try:
        acct = pwd.getpwuid(os.getuid()).pw_dir
    except KeyError:
        acct = None
    rep["home_is_account_home"] = bool(acct) and os.path.expanduser("~") == acct
    if not rep["home_is_account_home"]:
        block.append("HOME differs from the account home: the reserve preflight and "
                     "live_entry_test refuse, because a moved ledger path looks like a deleted ledger")
    rep["LG_VERIFY_SANDBOX"] = os.environ.get("LG_VERIFY_SANDBOX") == "1"
    if not rep["LG_VERIFY_SANDBOX"]:
        warn.append("LG_VERIFY_SANDBOX is not 1 (live refuses without it; some tests expect it)")
    env = {}
    for n in SECRET_ENV:
        env[n] = "set" if os.environ.get(n) else "unset"
    rep["secret_env_names"] = env  # presence only, never values
    kf = os.environ.get("RYAN_ALLOWANCE_KEY_FILE")
    if kf:
        try:
            st = os.stat(kf)
            rep["allowance_key_file"] = {"regular": os.path.isfile(kf), "mode": oct(st.st_mode & 0o777),
                                         "owner_is_me": st.st_uid == os.getuid()}
            if st.st_mode & 0o077:
                block.append("allowance key file has group/other permission bits")
        except OSError:
            rep["allowance_key_file"] = {"readable": False}
            warn.append("RYAN_ALLOWANCE_KEY_FILE is set but not statable")
    pins = {}
    for rel, want in FILE_PINS.items():
        p = os.path.join(HERE, rel)
        got = _md5(p) if os.path.isfile(p) else None
        pins[rel] = got == want
        if got != want:
            warn.append("pin differs or file missing: %s (a later reviewed change may legitimately move it; check the guide)" % rel)
    rep["vendored_pins_match"] = pins
    top = repo or HERE
    gs = subprocess.run(["git", "-C", top, "status", "--porcelain"], capture_output=True, text=True)
    head = subprocess.run(["git", "-C", top, "rev-parse", "HEAD"], capture_output=True, text=True)
    rep["git_head"] = head.stdout.strip() or None
    rep["tree_clean"] = gs.returncode == 0 and gs.stdout.strip() == ""
    if not rep["tree_clean"]:
        warn.append("working tree not clean or not a git checkout")
    rep["blocking"], rep["warnings"] = block, warn
    rep["note"] = "setup report only; qualifies no route, clears no halt, approves no call"
    return rep


def _jsonl(path):
    """(rows, bad_line_count, truncated). Fail-closed counting, no raise."""
    rows, bad, trunc = [], 0, False
    try:
        with open(path) as f:
            for i, line in enumerate(f):
                if i >= MAX_LINES:
                    trunc = True
                    break
                if not line.strip():
                    continue
                try:
                    o = json.loads(line)
                    if isinstance(o, dict):
                        rows.append(o)
                    else:
                        bad += 1
                except ValueError:
                    bad += 1
    except OSError:
        return None, 0, False
    return rows, bad, trunc


def _in_git_tree(path):
    p = subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def state_report(root, log_dir=None):
    out = {"PRIVATE": "private handover summary - do not publish; hashes, counts and code-written reasons only",
           "root": os.path.abspath(root), "problems": []}
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        out["problems"].append("runner root is not a directory")
        return out
    top = _in_git_tree(root)
    if top:
        out["problems"].append("runner root is inside a git work tree (%s): private state must not be committable" % top)
    files = {}
    for n in ("ledger.jsonl", "queue.json", "assignments.json", "eva-assignment.json", "allowance.json"):
        p = os.path.join(root, n)
        if os.path.isfile(p):
            files[n] = {"sha256": _sha(p), "bytes": os.path.getsize(p)}
    out["files"] = files
    led, bad, trunc = _jsonl(os.path.join(root, "ledger.jsonl"))
    if led is None:
        out["problems"].append("no ledger.jsonl: cannot tell a first run from a deleted ledger")
        led = []
    if bad:
        out["problems"].append("%d unparseable ledger line(s): treat history as damaged, do not repair" % bad)
    if trunc:
        out["problems"].append("ledger longer than %d lines: summary is partial" % MAX_LINES)
    by = {}
    for e in led:
        k = "%s/%s/%s" % (e.get("phase"), e.get("role", "-"), e.get("outcome", "-"))
        by[k] = by.get(k, 0) + 1
    out["ledger"] = {"lines": len(led), "by_phase_role_outcome": by,
                     "reserves": sum(1 for e in led if e.get("phase") == "reserved")}
    # a halt stands until a later "cleared" line; the code's own rule, reported not applied
    last_halt = last_clear = None
    for i, e in enumerate(led):
        if e.get("phase") == "halt":
            last_halt = i
        elif e.get("phase") == "cleared":
            last_clear = i
    standing = last_halt is not None and (last_clear is None or last_clear < last_halt)
    out["halt"] = {"standing": standing, "halt_lines": sum(1 for e in led if e.get("phase") == "halt"),
                   "cleared_lines": sum(1 for e in led if e.get("phase") == "cleared"),
                   "last_halt_reason": (str(led[last_halt].get("reason", ""))[:160] if last_halt is not None else None)}
    unmatched = [e.get("rid") for e in led if e.get("phase") == "reserved"
                 and not any(r.get("phase") == "result" and r.get("rid") == e.get("rid") for r in led)]
    out["reserves_without_result"] = unmatched
    # the runner also refuses while a reserve without a result sits AFTER the last cleared line
    after = [e.get("rid") for i, e in enumerate(led) if e.get("phase") == "reserved"
             and e.get("rid") in unmatched and (last_clear is None or i > last_clear)]
    out["reserves_blocking_since_last_clear"] = after
    out["runner_would_refuse_next_step"] = bool(standing or after)
    out["allowance"] = {"binds": sum(1 for e in led if e.get("phase") == "allowance-bind"),
                        "stops": sum(1 for e in led if e.get("phase") == "allowance-stop")}
    q = None
    try:
        q = json.load(open(os.path.join(root, "queue.json")))
    except (OSError, ValueError):
        pass
    items = []
    if isinstance(q, dict) and isinstance(q.get("questions"), list):
        for x in q["questions"]:
            if isinstance(x, dict):
                items.append({k: x.get(k) for k in ("id", "kind", "status", "lineage", "attempts") if k in x})
    out["queue_items"] = items
    try:
        a = json.load(open(os.path.join(root, "assignments.json")))
        out["assignments"] = {"models": a.get("models"), "decided_by": a.get("decided_by")}
    except (OSError, ValueError, AttributeError):
        out["assignments"] = None
    if log_dir:
        sys.path.insert(0, HERE)
        import reserve_preflight as rp
        import fenced_http
        pf = rp.preflight(0, log_dir=log_dir, cap=fenced_http.HTTP_LIFETIME_CAP)
        out["shared_log"] = {k: pf.get(k) for k in ("status", "reserves_total", "remaining", "cap", "problems")}
        out["shared_log"]["files"] = [{k: f.get(k) for k in ("file", "lines", "reserves", "results", "halts", "unmatched_reserves", "tip_sha256")} for f in pf.get("files", [])]
    out["note"] = ("The runner ledger and the shared request log are separate, disjoint histories. "
                   "A standing halt and an unknown outcome stay as recorded until a human clears them "
                   "citing an external condition. This summary resolves nothing.")
    return out


def main(argv):
    if len(argv) < 2 or argv[1] not in ("env", "state"):
        print(__doc__)
        return 2
    args = argv[2:]
    opt = {}
    i = 0
    while i < len(args):
        if args[i] in ("--repo", "--root", "--log-dir") and i + 1 < len(args):
            opt[args[i][2:]] = args[i + 1]; i += 2
        else:
            print("unknown or incomplete argument: " + args[i], file=sys.stderr); return 2
    if argv[1] == "env":
        rep = env_report(opt.get("repo"))
        print(json.dumps(rep, indent=2, sort_keys=True))
        return 1 if rep["blocking"] else 0
    if "root" not in opt:
        print("state needs --root", file=sys.stderr); return 2
    rep = state_report(opt["root"], opt.get("log-dir"))
    print(json.dumps(rep, indent=2, sort_keys=True))
    return 1 if rep["problems"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
