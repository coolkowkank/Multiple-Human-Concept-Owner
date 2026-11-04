#!/usr/bin/env python3
"""Thin tool-call executor for a model-driven self-commit attempt.

RECONSTRUCTION NOTICE: rebuilt 2026-11-04 after a sandbox reset destroyed
the original attempt-14 executor. Functionally equivalent design (same
tools, guards, round cap), but NOT the preserved original bytes. The
preserved evidence of attempt 14 is .team/attempts/attempt-14-transcript.json
on branch live/groq-dev-3, not this file.

The MODEL issues every tool call; this harness only executes them
mechanically with guards. No content authoring, no substantive pre-review.
Tools offered: write_file (small/new files only, byte-capped),
edit_file (exact-match anchored replacement in an existing file; the
bounded interface for model-authored edits to files too large for a
reliable whole-file rewrite), git_commit (verbatim message + provenance
trailer, local commit-msg hook enforced), git_push (fixed branch only).
The harness never repairs, normalizes or completes model-supplied
content: every payload is written byte-exact, and malformed arguments,
ambiguous anchors and mismatches fail loudly back to the model (or halt
the run when the provider rejects the call).

Token discipline (owner request 2026-11-04, "optimize the communication
with groq"): the run ENDS automatically on a successful git_push - no
trailing summary round is requested (measured waste: the trailing no-op
round cost 1,078 of 3,653 total tokens in attempt bot-auth-test and 1,921
of 8,036 in loop-c1, per recorded usage on the records branch). After a
successful write_file the file content is ELIDED from the in-memory
history sent to later rounds (placeholder points at the transcript); the
full content stays in the recorded transcript, and each elision is itself
recorded. Review feedback is still passed VERBATIM; capture, budget
accounting and fail-closed behavior are unchanged.

Durability: every event is written locally (atomic) AND checkpointed
(commit+push) to a dedicated operator records branch via a separate
worktree (RECORDS_DIR, required at startup). Any persistence failure
halts the run fail-closed BEFORE the next API call and before any
further tool execution in the same round. Honest limit: an event can
still be lost if the sandbox dies between response arrival and its
checkpoint landing; earlier events survive on the records branch.

Usage: GROQ_KEY_FILE=... RECORDS_DIR=... groq-harness.py REPO_PATH BRANCH ATTEMPT_ID TASK_FILE
"""
import hashlib
import json, os, re, subprocess, sys, atexit, time, fcntl

WRITE_GATE_MODE = sys.argv[1:2] == ["--write-gate"]
if WRITE_GATE_MODE:
    # Operator approval-writer mode: no provider key, task or committer
    # identity needed - only repo content hashing.
    REPO, BRANCH, ATTEMPT, TASK_FILE = sys.argv[3], "-", "gate", os.devnull
else:
    REPO, BRANCH, ATTEMPT, TASK_FILE = sys.argv[1:5]
KEY = "" if WRITE_GATE_MODE else open(os.environ.get("PROVIDER_KEY_FILE", os.environ.get("GROQ_KEY_FILE", ""))).read().strip()
TASK = open(TASK_FILE).read()
MODEL = os.environ.get("PROVIDER_MODEL", "openai/gpt-oss-120b")
API_URL = os.environ.get("PROVIDER_API_URL", "https://api.groq.com/openai/v1/chat/completions")
MAX_ROUNDS = int(os.environ.get("MAX_ROUNDS", "6"))
MAX_NUDGES = int(os.environ.get("MAX_NUDGES", "2"))  # prose-only rounds tolerated before halt
MAX_CALLS = int(os.environ.get("MAX_CALLS", "6"))  # coordinator passes the loop's REMAINING global budget; every attempted provider request counts, including failed/error responses; the executor never retries
CALLS = {"n": 0}
# Zero-price routes only (owner rule for the Requesty gemma batch): when
# REQUIRE_ZERO_COST=1 and a response reports a NONZERO usage.cost, the run
# stops fail-closed BEFORE any further provider request - a pricing surprise
# must halt the batch, never silently spend. Missing cost field passes (the
# zero-price listing is verified separately before GO). Same semantics as the
# launcher HttpAdapter require_zero_cost guard (launcher/adapters.py).
REQUIRE_ZERO_COST = os.environ.get("REQUIRE_ZERO_COST", "").lower() in ("1", "true", "yes")
# Payload bounds (deadlock-fix batch lesson, attempts b3/b5: whole-file
# rewrite payloads from the model repeatedly failed provider-side JSON
# validation). write_file is capped small; larger existing files change
# through edit_file's anchored exact-match replacement.
MAX_BYTES = int(os.environ.get("MAX_WRITE_BYTES", "6000"))
EDIT_MAX_BYTES = int(os.environ.get("MAX_EDIT_BYTES", "6000"))
# Fixed HARNESS-controlled author identity for every model-issued commit: the
# owner-approved shared project machine account (coolkowkank-bot), per-model credit
# in the author NAME. The noreply email is account-linked, so work that lands on the
# default branch can be credited to the bot account per GitHub's email grouping.
# Three identities stay SEPARATE and honest: author (per-model name + bot noreply),
# committer (git identity configured at commit time, operator), and pusher
# (whichever credential authenticates the push) - committer metadata is
# configured independently of push authentication.
MODEL_AUTHOR = os.environ.get("MODEL_AUTHOR", "Groq (gpt-oss-120b model) <350571665+coolkowkank-bot@users.noreply.github.com>")
# Committer identity for MODEL-issued commits (owner decision 2026-11-04 for THIS
# project's runs: the shared bot account whose credential also authenticates the
# push). The tool hardcodes NO default identity - silently attributing commits to
# a specific account would be dishonest for any other user onboarding with their
# own token. Resolution order: explicit MODEL_COMMITTER ("Name <email>"), else
# derive "login <id+login@users.noreply.github.com>" from the GITHUB_TOKEN account
# (verified via the GitHub API), else fail closed. Operator record-keeping commits
# (records branch, LOOP.json) keep the operator identity regardless.
def _resolve_model_committer():
    explicit = os.environ.get("MODEL_COMMITTER")
    if explicit:
        n, e = explicit.rsplit("<", 1)
        return n.strip(), e.rstrip(">").strip(), "explicit MODEL_COMMITTER"
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        import urllib.request
        req = urllib.request.Request("https://api.github.com/user", headers={
            "Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
            "User-Agent": "mhco-standalone-committer-resolution"})
        with urllib.request.urlopen(req, timeout=15) as r:
            u = json.loads(r.read())
        login, uid = u["login"], u["id"]
        return login, f"{uid}+{login}@users.noreply.github.com", "derived from the GITHUB_TOKEN account"
    raise SystemExit("MODEL_COMMITTER ('Name <email>') is required, or set GITHUB_TOKEN to derive the "
                     "committer identity from the verified token account; refusing to attribute commits "
                     "to a hardcoded account.")
if WRITE_GATE_MODE:
    MODEL_COMMITTER_NAME = MODEL_COMMITTER_EMAIL = MODEL_COMMITTER_SOURCE = ""
else:
    MODEL_COMMITTER_NAME, MODEL_COMMITTER_EMAIL, MODEL_COMMITTER_SOURCE = _resolve_model_committer()
CRED = re.compile(r"(gsk_[A-Za-z0-9]|ghp_[A-Za-z0-9]|github_pat_|gho_[A-Za-z0-9]|AKIA[0-9A-Z]{16}|xox[baprs]-|Bearer\s+[A-Za-z0-9._-]{20,}|-----BEGIN)")
transcript = []

OUT = os.path.join(REPO, ".team", "attempts", f"{ATTEMPT}-transcript.json")
RECORDS_DIR = os.environ.get("RECORDS_DIR")
CHECKPOINT = {"n": 0}
PERSIST = {"halt": False, "saved": 0}
RECORDS_COMMITTER = os.environ.get("RECORDS_COMMITTER", "instinct-telkomsel <instinct-telkomsel@users.noreply.github.com>")

def save_transcript():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(transcript, f, indent=2)
    os.replace(tmp, OUT)
    CHECKPOINT["n"] += 1
    rel = os.path.join(".team", "attempts", f"{ATTEMPT}-transcript.json")
    dst = os.path.join(RECORDS_DIR, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w") as f:
        json.dump(transcript, f, indent=2)
    subprocess.run(["git", "-C", RECORDS_DIR, "add", "--", rel], check=True, capture_output=True)
    # Relaunch-safe: a checkpoint whose bytes are already committed (e.g. a
    # run relaunched after a halt) must not fail on "nothing to commit".
    staged = subprocess.run(["git", "-C", RECORDS_DIR, "diff", "--cached", "--quiet"],
                            capture_output=True)
    if staged.returncode != 0:
        _rn, _re_ = RECORDS_COMMITTER.rsplit("<", 1)
        subprocess.run(["git", "-C", RECORDS_DIR, "-c", f"user.name={_rn.strip()}",
                        "-c", f"user.email={_re_.rstrip('>').strip()}",
                        "commit", "--quiet", "-m",
                        f"operator: {ATTEMPT} transcript checkpoint {CHECKPOINT['n']} (auto, per-event durability)"],
                       check=True, capture_output=True)
    subprocess.run(["git", "-C", RECORDS_DIR, "push", "--quiet", "origin", "HEAD"], check=True, capture_output=True)
    PERSIST["saved"] = len(transcript)

def record(event):
    transcript.append(event)
    try:
        save_transcript()
    except Exception as e:
        try:
            transcript.append({"checkpoint_error": str(e)[:300]})
            with open(OUT, "w") as f:
                json.dump(transcript, f, indent=2)
        except Exception:
            pass
        PERSIST["halt"] = True

def _atexit():
    if PERSIST["saved"] != len(transcript) and not PERSIST["halt"]:
        try:
            save_transcript()
        except Exception:
            pass
atexit.register(_atexit)

SYSTEM = (f"You are the builder on repo Multiple-Human-Concept-Owner, branch {BRANCH}. "
          "You commit your own work with the provided tools: write_file (new or "
          "small files only), edit_file (exact-match edits to existing files), "
          "git_commit, git_push. Be honest in commit messages: say you are Groq "
          "gpt-oss-120b committing via your own tool calls. The repo's local "
          "commit-msg hook REQUIRES your message to contain a line exactly like "
          "'TURN: builder' - include it or the commit is rejected. Never include secrets. "
          "The run ENDS automatically once git_push succeeds: no summary or follow-up "
          "message is needed after it.")

TOOLS = [
 {"type":"function","function":{"name":"write_file","description":"Write a markdown file under docs/.","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}}},
 {"type":"function","function":{"name":"edit_file","description":"Replace ONE exact occurrence of old_string with new_string in an existing file (anchored small edit). Fails loudly when old_string is absent or occurs more than once - then retry with more surrounding context.","parameters":{"type":"object","properties":{"path":{"type":"string"},"old_string":{"type":"string"},"new_string":{"type":"string"}},"required":["path","old_string","new_string"]}}},
 {"type":"function","function":{"name":"git_commit","description":"Stage your docs/ file and commit with your exact message (must contain a 'TURN: builder' line).","parameters":{"type":"object","properties":{"message":{"type":"string"}},"required":["message"]}}},
 {"type":"function","function":{"name":"git_push","description":"Push the current branch to GitHub.","parameters":{"type":"object","properties":{}}}},
]

# Allowlisted rate-limit/reset/retry response headers for diagnostics
# (operator infra, 2026-11-04 pause: TPM rejections need org-window
# evidence on the NEXT real attempt - no inference probes). Nothing else
# is captured; request-side auth material is outbound-only and never
# recorded.
RATE_HEADER_ALLOWLIST = {
    "x-ratelimit-limit-requests", "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-requests", "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens",
    "retry-after"}

def _rate_headers(header_text):
    out = {}
    for line in (header_text or "").splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip().lower()
        if k in RATE_HEADER_ALLOWLIST:
            out[k] = v.strip()
    return out

# Durable cross-launch request accounting (2026-11-04 batch lesson: the
# deadlock-fix batch spent 16 provider requests against a 12 cap because
# each launch's MAX_CALLS was derived from a LAUNCH count while runs made
# 2-3 requests). When BUDGET_LEDGER is set it is the single durable
# counter: every network attempt - success, error or probe - is reserved
# BEFORE the request, under an flock, so concurrent launches cannot
# double-spend. Hard stop at MAX_CALLS across all launches using the file.
BUDGET_LEDGER = os.environ.get("BUDGET_LEDGER")
MIN_CALL_INTERVAL_S = float(os.environ.get("MIN_CALL_INTERVAL_S", "0"))

def _ledger_read(f):
    f.seek(0)
    try:
        return json.load(f)
    except Exception:
        return {"used": 0, "history": []}

def _pacing_wait_s(data, now, min_interval):
    """Seconds to wait before the next request: the configured floor AND
    any provider-supplied reset hint stored by an earlier rejection. A
    floor only reduces self-collision; it cannot guarantee quota."""
    wait = 0.0
    last = data.get("last_call_epoch")
    if last and min_interval > 0:
        wait = max(wait, min_interval - (now - last))
    hint_until = data.get("rate_reset_until_epoch")
    if hint_until:
        wait = max(wait, hint_until - now)
    return max(0.0, wait)

_RETRY_HINT_RE = re.compile(r"try again in ([0-9.]+)s", re.I)

def _retry_hint_s(error_detail):
    if not isinstance(error_detail, dict):
        return None
    m = _RETRY_HINT_RE.search(str(error_detail.get("message", "")))
    if m:
        return float(m.group(1))
    return None

def _reserve_call():
    """Reserve one provider request. Raises (hard stop) when the budget is
    exhausted. Applies pacing (sleeps) before returning."""
    if not BUDGET_LEDGER:
        if CALLS["n"] >= MAX_CALLS:
            record({"budget_stop": {"used": CALLS["n"], "budget": MAX_CALLS}})
            raise RuntimeError(f"API call budget exhausted ({CALLS['n']}/{MAX_CALLS}); refusing further provider requests")
        CALLS["n"] += 1
        return
    with open(BUDGET_LEDGER, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            data = _ledger_read(f)
            if data["used"] >= MAX_CALLS:
                record({"budget_stop": {"used": data["used"], "budget": MAX_CALLS,
                                        "ledger": BUDGET_LEDGER, "durable": True}})
                raise RuntimeError(f"durable budget exhausted ({data['used']}/{MAX_CALLS} across all launches); refusing further provider requests")
            wait = _pacing_wait_s(data, time.time(), MIN_CALL_INTERVAL_S)
            data["used"] += 1
            data["last_call_epoch"] = time.time() + wait
            data["history"].append({"attempt": ATTEMPT, "seq": data["used"],
                                    "reserved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            f.seek(0); f.truncate(); json.dump(data, f); f.flush(); os.fsync(f.fileno())
            CALLS["n"] = data["used"]
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    if wait > 0:
        record({"pacing_wait": {"seconds": round(wait, 1), "min_interval": MIN_CALL_INTERVAL_S}})
        time.sleep(wait)

def _store_reset_hint(seconds):
    if not BUDGET_LEDGER or seconds is None:
        return
    with open(BUDGET_LEDGER, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            data = _ledger_read(f)
            data["rate_reset_until_epoch"] = time.time() + seconds
            f.seek(0); f.truncate(); json.dump(data, f); f.flush(); os.fsync(f.fileno())
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

def api(messages):
    _reserve_call()
    payload = {"model": MODEL, "messages": messages, "tools": TOOLS,
               "reasoning_effort": "low",
               "max_completion_tokens": int(os.environ.get("MAX_COMPLETION_TOKENS", "4096"))}
    hdr_path = os.path.join(RECORDS_DIR, f".team-headers-{os.getpid()}.tmp")
    p = subprocess.run(["curl", "-sS", "--max-time", "120", "-w", "\n%{http_code}",
        "-D", hdr_path,
        API_URL,
        "-H", f"Authorization: Bearer {KEY}", "-H", "Content-Type: application/json",
        "-d", json.dumps(payload)], capture_output=True, text=True)
    try:
        with open(hdr_path) as hf:
            rate_headers = _rate_headers(hf.read())
    except OSError:
        rate_headers = {}
    finally:
        try:
            os.unlink(hdr_path)
        except OSError:
            pass
    if p.returncode != 0:
        record({"api_error": {"kind": "transport", "detail": p.stderr[:300]}})
        raise RuntimeError(f"curl failed: {p.stderr[:300]}")
    body, _, status = p.stdout.rpartition("\n")
    try:
        r = json.loads(body)
    except json.JSONDecodeError:
        # e.g. Cloudflare HTML error page: capture status + safe truncated body, no crash
        safe = body.replace(KEY, "[REDACTED]")[:300]
        record({"api_error": {"kind": "http", "status": status.strip(), "body_head": safe}})
        raise RuntimeError(f"non-JSON HTTP {status.strip()}")
    if "error" in r:
        if isinstance(r.get("error"), dict) and r["error"].get("code") == "rate_limit_exceeded":
            _store_reset_hint(_retry_hint_s(r["error"]))
        record({"api_error": {"kind": "api", "status": status.strip(), "detail": r["error"],
                              "rate_headers": rate_headers}})
        raise RuntimeError(f"API error: {r['error']}")
    if REQUIRE_ZERO_COST:
        cost = (r.get("usage") or {}).get("cost")
        if cost not in (None, 0, 0.0, "0", "0.0"):
            record({"cost_stop": {"cost": cost, "model": MODEL, "call": CALLS["n"]}})
            raise RuntimeError(
                f"require_zero_cost: provider reported nonzero cost {cost!r} on {MODEL}; "
                "refusing further provider requests")
    if rate_headers:
        record({"rate_headers": rate_headers, "call": CALLS["n"]})
    return r

# Paths the model may write. docs/tasks markdown for records; launcher/tests
# Python for implementation batches (widened 2026-11-04 for the
# deadlock-fix batch; each widening is a disclosed operator infra change,
# never a silent one).
WRITE_RE = re.compile(r"(docs|tasks)/[A-Za-z0-9._-]+\.md|(launcher|tests)/[A-Za-z0-9._-]+\.py")
def safe_path(path):
    if not WRITE_RE.fullmatch(path or ""):
        return "path must match docs|tasks/<name>.md or launcher|tests/<name>.py"
    full = os.path.join(REPO, path)
    d = os.path.dirname(full)
    cur = REPO
    for part in os.path.relpath(d, REPO).split(os.sep):
        cur = os.path.join(cur, part)
        if os.path.islink(cur):
            return "symlink in parent path refused"
    if os.path.islink(full):
        return "symlink target refused"
    return None


# ---- strong push gate -------------------------------------------------
# Approval binds the exact HEAD plus a hash over EVERY tracked file's
# working-tree content and every relevant untracked file (not only named
# dirs), so any pushed change - runtime paths included - is covered by the
# tested tree. Only generated noise (.git, __pycache__, *.pyc) is exempt.
def _git(repo, *a):
    return subprocess.run(["git", "-C", repo] + list(a), capture_output=True, text=True)

def _worktree_fingerprint(repo):
    h = hashlib.sha256()
    tracked = _git(repo, "ls-files", "-z").stdout.split("\x00")
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard", "-z").stdout.split("\x00")
    paths = sorted(p for p in tracked + untracked
                   if p and "__pycache__" not in p and not p.endswith(".pyc"))
    for rel in paths:
        fp = os.path.join(repo, rel)
        if not os.path.isfile(fp):
            h.update(b"MISSING\x00" + rel.encode() + b"\x00")
            continue
        h.update(rel.encode() + b"\x00")
        with open(fp, "rb") as f:
            h.update(f.read())
        h.update(b"\x00")
    return h.hexdigest()

def _write_gate(gate_path, repo):
    pin = {"head": _git(repo, "rev-parse", "HEAD").stdout.strip(),
           "worktree_sha256": _worktree_fingerprint(repo),
           "approved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "meaning": "operator ran the changed-worktree test suite green at exactly this head+content"}
    with open(gate_path, "w") as f:
        json.dump(pin, f, indent=2)
    return pin

def _push_gate_check(repo):
    """Return None when push is approved for the exact tested state, else an error string."""
    gate = os.environ.get("PUSH_GATE_FILE")
    if not gate:
        if os.environ.get("ALLOW_UNGATED_PUSH") == "1":
            return None
        return "push fail-closed: PUSH_GATE_FILE unset and ALLOW_UNGATED_PUSH!=1"
    try:
        with open(gate) as f:
            pin = json.load(f)
    except Exception:
        return f"push fail-closed: gate {gate} absent or unreadable"
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    if pin.get("head") != head:
        return (f"push STALE: approved head {pin.get('head')} != current {head}; "
                "operator must re-run tests and re-approve")
    fp = _worktree_fingerprint(repo)
    if pin.get("worktree_sha256") != fp:
        return ("push STALE: worktree content changed after approval "
                "(edit, new file, or removal); operator must re-run tests and re-approve")
    return None

def run_tool(name, args):
    try:
        if name == "write_file":
            path, content = args.get("path", ""), args.get("content", "")
            err = safe_path(path)
            if err: return {"ok": False, "error": err}
            if CRED.search(content): return {"ok": False, "error": "credential-pattern content refused"}
            if len(content.encode()) > MAX_BYTES: return {"ok": False, "error": f"content exceeds {MAX_BYTES}-byte write cap; use edit_file anchored edits for existing files or split the work"}
            full = os.path.join(REPO, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            open(full, "w").write(content)
            return {"ok": True, "path": path, "bytes": len(content.encode())}
        if name == "edit_file":
            path = args.get("path", "")
            old, new = args.get("old_string", ""), args.get("new_string", "")
            err = safe_path(path)
            if err: return {"ok": False, "error": err}
            if not old: return {"ok": False, "error": "old_string must be non-empty"}
            if CRED.search(new): return {"ok": False, "error": "credential-pattern content refused"}
            if len(old.encode()) > EDIT_MAX_BYTES or len(new.encode()) > EDIT_MAX_BYTES:
                return {"ok": False, "error": f"edit strings exceed {EDIT_MAX_BYTES}-byte cap; split into smaller anchored edits"}
            full = os.path.join(REPO, path)
            if not os.path.isfile(full):
                return {"ok": False, "error": "file does not exist; use write_file for new files"}
            text = open(full, encoding="utf-8").read()
            n = text.count(old)
            if n == 0:
                return {"ok": False, "error": "old_string not found (exact byte match required); no change made"}
            if n > 1:
                return {"ok": False, "error": f"old_string matches {n} locations; add surrounding context until it is unique; no change made"}
            open(full, "w", encoding="utf-8").write(text.replace(old, new, 1))
            return {"ok": True, "path": path, "replacements": 1, "bytes": os.path.getsize(full)}
        if name == "git_commit":
            msg = args.get("message", "")
            if CRED.search(msg): return {"ok": False, "error": "credential-pattern message refused"}
            # Mechanical guard (never repairs): staged/changed Python files
            # must compile - a corrupt file is returned to the MODEL to fix,
            # never pushed (b5 lesson: a double-escaped supervisor.py was
            # committed broken). Disable only via PRECOMMIT_COMPILE_CHECK=0.
            if os.environ.get("PRECOMMIT_COMPILE_CHECK", "1") not in ("0", "false"):
                candidates = []
                for base in ("launcher", "tests"):
                    for root, _dirs, files in os.walk(os.path.join(REPO, base)):
                        for fn in files:
                            if fn.endswith(".py"):
                                candidates.append(os.path.join(root, fn))
                for full in candidates:
                    rel = os.path.relpath(full, REPO)
                    c = subprocess.run([sys.executable, "-c",
                                        "import py_compile, sys; py_compile.compile(sys.argv[1], cfile='/tmp/pccheck.pyc', doraise=True)",
                                        full], capture_output=True, text=True)
                    if c.returncode != 0:
                        return {"ok": False, "error": f"pre-commit compile check failed for {rel}: {(c.stderr or c.stdout)[-400:]} - fix YOUR file content and retry"}
            author_name = MODEL_AUTHOR.split(" <", 1)[0]
            trailer = f"\n\nCommitted-by: {author_name} via own tool calls"
            subprocess.run(["git", "-C", REPO, "add", "--", "docs/", "tasks/", "launcher/", "tests/"], capture_output=True)
            _env = dict(os.environ, GIT_COMMITTER_NAME=MODEL_COMMITTER_NAME, GIT_COMMITTER_EMAIL=MODEL_COMMITTER_EMAIL)
            p = subprocess.run(["git", "-C", REPO, "commit", "--author", MODEL_AUTHOR, "-m", msg + trailer], capture_output=True, text=True, env=_env)
            if p.returncode != 0:
                return {"ok": False, "error": (p.stderr or p.stdout)[-500:]}
            head = subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
            return {"ok": True, "head": head}
        if name == "git_push":
            # Operator test-verification gate (2026-11-04 rule: the changed
            # worktree's tests must actually run green BEFORE publish; a
            # compile pass is not verification). When PUSH_GATE_FILE is set
            # and absent, refuse loudly; the MODEL retries after the gate
            # opens. Gate creation is always an operator act after running
            # the suite; the model cannot create it (path outside its
            # writable set).
            err = _push_gate_check(REPO)
            if err:
                if err.startswith("push STALE"):
                    return {"ok": False, "error": err + "; do other work or retry git_push in a later round"}
                return {"ok": False, "error": err + "; do other work or retry git_push in a later round"}
            p = subprocess.run(["git", "-C", REPO, "push", "origin", f"HEAD:{BRANCH}"], capture_output=True, text=True)
            out = (p.stdout + p.stderr).replace(KEY, "[REDACTED]")
            if p.returncode != 0:
                return {"ok": False, "error": out[-500:]}
            return {"ok": True, "output": out[-500:]}
        return {"ok": False, "error": f"unknown tool {name}"}
    except Exception as e:
        return {"ok": False, "error": f"executor error: {str(e)[:300]}"}

def main():
    if not RECORDS_DIR:
        raise SystemExit("RECORDS_DIR (records-branch worktree) is required; refusing to run without durable per-event capture")
    r = subprocess.run(["git", "-C", RECORDS_DIR, "rev-parse", "--git-dir"], capture_output=True)
    if r.returncode != 0:  # accepts linked worktrees (.git file) and plain clones alike
        raise SystemExit(f"RECORDS_DIR is not a git worktree: {RECORDS_DIR}")
    record({"system": SYSTEM, "user": TASK})
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": TASK}]
    nudges = 0
    for rnd in range(MAX_ROUNDS):
        if PERSIST["halt"]:
            print("HALT: transcript persistence failed; refusing further API calls (fail-closed)")
            return
        resp = api(messages)
        record({"api_response": resp})
        msg = resp["choices"][0]["message"]
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            # A prose-only round is not completion: nudge the model back to
            # tool use, bounded so a chatty model cannot burn the budget.
            nudges += 1
            record({"no_tool_call": {"round": rnd + 1, "nudge": nudges,
                                     "content": (msg.get("content") or "")[:300]}})
            if nudges > MAX_NUDGES:
                print(f"round {rnd+1}: model stopped without tool call after {MAX_NUDGES} nudges; halting")
                return
            print(f"round {rnd+1}: no tool call; nudging model to act ({nudges}/{MAX_NUDGES})")
            messages.append({"role": "user", "content":
                "You replied with text but no tool call. Take the next concrete "
                "action NOW with a tool call (edit_file/write_file/git_commit/"
                "git_push). Do not describe actions in prose."})
            continue
        nudges = 0
        for c in calls:
            if PERSIST["halt"]:
                print("HALT: persistence failed; refusing further tool execution this round (fail-closed)")
                return
            name = c["function"]["name"]
            try:
                args = json.loads(c["function"]["arguments"] or "{}")
            except json.JSONDecodeError as e:
                result = {"ok": False, "error": f"malformed tool arguments: {str(e)[:200]}"}
                record({"tool_call": name, "args_error": True, "result": result})
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(result)})
                continue
            result = run_tool(name, args)
            record({"tool_call": name, "args": args, "result": result})
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(result)})
            if name == "edit_file" and result.get("ok"):
                c["function"]["arguments"] = json.dumps(
                    {"path": args.get("path", ""),
                     "edit": f"[1 anchored replacement applied to {args.get('path','')}; full payloads in the run transcript]"})
                record({"history_elided": {"path": args.get("path", ""), "tool": "edit_file"}})
            if name == "write_file" and result.get("ok"):
                # Elide the just-written content from the history sent to later
                # rounds; the full bytes remain in the recorded transcript.
                nbytes = result.get("bytes", 0)
                c["function"]["arguments"] = json.dumps(
                    {"path": args.get("path", ""),
                     "content": f"[written to {args.get('path','')}: {nbytes} bytes; full content in the run transcript]"})
                record({"history_elided": {"path": args.get("path", ""), "bytes": nbytes}})
            if name == "git_push" and result.get("ok"):
                record({"run_complete": {"reason": "git_push succeeded", "round": rnd + 1,
                                         "api_calls": CALLS["n"]}})
                print(f"round {rnd+1}: git_push succeeded; run complete ({CALLS['n']} API calls)")
                return
    print(f"round cap {MAX_ROUNDS} reached; stopping")

if __name__ == "__main__":
    if WRITE_GATE_MODE:
        # Operator-only approval writer: binds the gate to the exact HEAD +
        # whole-tree content AFTER a green suite run.
        print(json.dumps(_write_gate(sys.argv[2], sys.argv[3]), indent=2))
    else:
        main()
