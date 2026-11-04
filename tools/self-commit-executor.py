#!/usr/bin/env python3
"""Thin tool-call executor for a model-driven self-commit attempt.

RECONSTRUCTION NOTICE: rebuilt 2026-11-04 after a sandbox reset destroyed
the original attempt-14 executor. Functionally equivalent design (same
tools, guards, round cap), but NOT the preserved original bytes. The
preserved evidence of attempt 14 is .team/attempts/attempt-14-transcript.json
on branch live/groq-dev-3, not this file.

The MODEL issues every tool call; this harness only executes them
mechanically with guards. No content authoring, no substantive pre-review.
Tools offered: write_file (docs/*.md only), git_commit (verbatim message
+ provenance trailer, local commit-msg hook enforced), git_push (fixed
branch only).

Durability: every event is written locally (atomic) AND checkpointed
(commit+push) to a dedicated operator records branch via a separate
worktree (RECORDS_DIR, required at startup). Any persistence failure
halts the run fail-closed BEFORE the next API call and before any
further tool execution in the same round. Honest limit: an event can
still be lost if the sandbox dies between response arrival and its
checkpoint landing; earlier events survive on the records branch.

Usage: GROQ_KEY_FILE=... RECORDS_DIR=... groq-harness.py REPO_PATH BRANCH ATTEMPT_ID TASK_FILE
"""
import json, os, re, subprocess, sys, atexit

REPO, BRANCH, ATTEMPT, TASK_FILE = sys.argv[1:5]
KEY = open(os.environ["GROQ_KEY_FILE"]).read().strip()
TASK = open(TASK_FILE).read()
MODEL = "openai/gpt-oss-120b"
MAX_ROUNDS = 6
MAX_CALLS = int(os.environ.get("MAX_CALLS", "6"))  # coordinator passes the loop's REMAINING global budget; every attempted provider request counts, including failed/error responses; the executor never retries
CALLS = {"n": 0}
MAX_BYTES = 20000
# Fixed HARNESS-controlled author identity for every model-issued commit: the
# owner-approved shared project machine account (coolkowkank-bot), per-model credit
# in the author NAME. The noreply email is account-linked, so work that lands on the
# default branch can be credited to the bot account per GitHub's email grouping.
# Three identities stay SEPARATE and honest: author (per-model name + bot noreply),
# committer (git identity configured at commit time, operator), and pusher
# (whichever credential authenticates the push) - committer metadata is
# configured independently of push authentication.
MODEL_AUTHOR = "Groq (gpt-oss-120b model) <350571665+coolkowkank-bot@users.noreply.github.com>"
CRED = re.compile(r"(gsk_[A-Za-z0-9]|ghp_[A-Za-z0-9]|github_pat_|gho_[A-Za-z0-9]|AKIA[0-9A-Z]{16}|xox[baprs]-|Bearer\s+[A-Za-z0-9._-]{20,}|-----BEGIN)")
transcript = []

OUT = os.path.join(REPO, ".team", "attempts", f"{ATTEMPT}-transcript.json")
RECORDS_DIR = os.environ.get("RECORDS_DIR")
CHECKPOINT = {"n": 0}
PERSIST = {"halt": False, "saved": 0}

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
    subprocess.run(["git", "-C", RECORDS_DIR, "-c", "user.name=instinct-telkomsel",
                    "-c", "user.email=instinct-telkomsel@users.noreply.github.com",
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
          "You commit your own work with the provided tools: write_file (docs/ only), "
          "git_commit, git_push. Be honest in commit messages: say you are Groq "
          "gpt-oss-120b committing via your own tool calls. The repo's local "
          "commit-msg hook REQUIRES your message to contain a line exactly like "
          "'TURN: builder' - include it or the commit is rejected. Never include secrets.")

TOOLS = [
 {"type":"function","function":{"name":"write_file","description":"Write a markdown file under docs/.","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}}},
 {"type":"function","function":{"name":"git_commit","description":"Stage your docs/ file and commit with your exact message (must contain a 'TURN: builder' line).","parameters":{"type":"object","properties":{"message":{"type":"string"}},"required":["message"]}}},
 {"type":"function","function":{"name":"git_push","description":"Push the current branch to GitHub.","parameters":{"type":"object","properties":{}}}},
]

def api(messages):
    if CALLS["n"] >= MAX_CALLS:
        record({"budget_stop": {"used": CALLS["n"], "budget": MAX_CALLS}})
        raise RuntimeError(f"API call budget exhausted ({CALLS['n']}/{MAX_CALLS}); refusing further provider requests")
    CALLS["n"] += 1  # counted BEFORE the request: failed/transport-blocked attempts consume budget too
    payload = {"model": MODEL, "messages": messages, "tools": TOOLS,
               "reasoning_effort": "low", "max_completion_tokens": 4096}
    p = subprocess.run(["curl", "-sS", "--max-time", "120", "-w", "\n%{http_code}",
        "https://api.groq.com/openai/v1/chat/completions",
        "-H", f"Authorization: Bearer {KEY}", "-H", "Content-Type: application/json",
        "-d", json.dumps(payload)], capture_output=True, text=True)
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
        record({"api_error": {"kind": "api", "status": status.strip(), "detail": r["error"]}})
        raise RuntimeError(f"API error: {r['error']}")
    return r

def safe_path(path):
    if not re.fullmatch(r"docs/[A-Za-z0-9._-]+\.md", path or ""):
        return "path must match docs/<name>.md"
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

def run_tool(name, args):
    try:
        if name == "write_file":
            path, content = args.get("path", ""), args.get("content", "")
            err = safe_path(path)
            if err: return {"ok": False, "error": err}
            if CRED.search(content): return {"ok": False, "error": "credential-pattern content refused"}
            if len(content.encode()) > MAX_BYTES: return {"ok": False, "error": "file too large"}
            full = os.path.join(REPO, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            open(full, "w").write(content)
            return {"ok": True, "path": path, "bytes": len(content.encode())}
        if name == "git_commit":
            msg = args.get("message", "")
            if CRED.search(msg): return {"ok": False, "error": "credential-pattern message refused"}
            trailer = "\n\nCommitted-by: Groq gpt-oss-120b via own tool calls"
            subprocess.run(["git", "-C", REPO, "add", "--", "docs/"], capture_output=True)
            p = subprocess.run(["git", "-C", REPO, "commit", "--author", MODEL_AUTHOR, "-m", msg + trailer], capture_output=True, text=True)
            if p.returncode != 0:
                return {"ok": False, "error": (p.stderr or p.stdout)[-500:]}
            head = subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
            return {"ok": True, "head": head}
        if name == "git_push":
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
            print(f"round {rnd+1}: model stopped without tool call: {(msg.get('content') or '')[:200]}")
            return
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
    print(f"round cap {MAX_ROUNDS} reached; stopping")

if __name__ == "__main__":
    main()
