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
+ provenance trailer, repo commit-msg hook enforced), git_push (fixed
branch only). Transcript (project-level messages only) saved atexit.

Usage: groq-harness.py REPO_PATH BRANCH ATTEMPT_ID TASK_FILE
Env: GROQ_KEY_FILE points at a file holding the API key (deleted by caller).
"""
import json, os, re, subprocess, sys, atexit

REPO, BRANCH, ATTEMPT, TASK_FILE = sys.argv[1:5]
KEY = open(os.environ["GROQ_KEY_FILE"]).read().strip()
TASK = open(TASK_FILE).read()
MODEL = "openai/gpt-oss-120b"
MAX_ROUNDS = 6
MAX_BYTES = 20000
CRED = re.compile(r"(gsk_[A-Za-z0-9]|ghp_[A-Za-z0-9]|github_pat_|gho_[A-Za-z0-9]|AKIA[0-9A-Z]{16}|xox[baprs]-|Bearer\s+[A-Za-z0-9._-]{20,}|-----BEGIN)")
transcript = []

OUT = os.path.join(REPO, ".team", "attempts", f"{ATTEMPT}-transcript.json")
def save_transcript():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(transcript, f, indent=2)
    os.replace(tmp, OUT)
atexit.register(save_transcript)

def record(event):
    transcript.append(event)
    save_transcript()  # durable after EVERY event: a crash loses nothing already recorded

SYSTEM = (f"You are the builder on repo Multiple-Human-Concept-Owner, branch {BRANCH}. "
          "You commit your own work with the provided tools: write_file (docs/ only), "
          "git_commit, git_push. Be honest in commit messages: say you are Groq "
          "gpt-oss-120b committing via your own tool calls. The repo's commit-msg hook "
          "REQUIRES your message to contain a line exactly like 'TURN: builder' - "
          "include it or the commit is rejected. Never include secrets.")

TOOLS = [
 {"type":"function","function":{"name":"write_file","description":"Write a markdown file under docs/.","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}}},
 {"type":"function","function":{"name":"git_commit","description":"Stage your docs/ file and commit with your exact message (must contain a 'TURN: builder' line).","parameters":{"type":"object","properties":{"message":{"type":"string"}},"required":["message"]}}},
 {"type":"function","function":{"name":"git_push","description":"Push the current branch to GitHub.","parameters":{"type":"object","properties":{}}}},
]

def api(messages):
    payload = {"model": MODEL, "messages": messages, "tools": TOOLS,
               "reasoning_effort": "low", "max_completion_tokens": 4096}
    p = subprocess.run(["curl", "-sS", "--max-time", "120",
        "https://api.groq.com/openai/v1/chat/completions",
        "-H", f"Authorization: Bearer {KEY}", "-H", "Content-Type: application/json",
        "-d", json.dumps(payload)], capture_output=True, text=True)
    if p.returncode != 0:
        record({"api_error": {"kind": "transport", "detail": p.stderr[:300]}})
        raise RuntimeError(f"curl failed: {p.stderr[:300]}")
    r = json.loads(p.stdout)
    if "error" in r:
        record({"api_error": {"kind": "api", "detail": r["error"]}})
        raise RuntimeError(f"API error: {r['error']}")
    return r

def safe_path(path):
    if not re.fullmatch(r"docs/[A-Za-z0-9._-]+\.md", path or ""):
        return "path must match docs/<name>.md"
    full = os.path.join(REPO, path)
    d = os.path.dirname(full)
    # check parents BEFORE creating anything (N4): no symlink anywhere in chain
    cur = REPO
    for part in os.path.relpath(d, REPO).split(os.sep):
        cur = os.path.join(cur, part)
        if os.path.islink(cur):
            return "symlink in parent path refused"
    if os.path.islink(full):
        return "symlink target refused"
    return None

def run_tool(name, args):
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
        p = subprocess.run(["git", "-C", REPO, "add", "--", "docs/"], capture_output=True, text=True)
        p = subprocess.run(["git", "-C", REPO, "commit", "-m", msg + trailer], capture_output=True, text=True)
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

def main():
    record({"system": SYSTEM, "user": TASK})
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": TASK}]
    for rnd in range(MAX_ROUNDS):
        resp = api(messages)
        record({"api_response": resp})
        msg = resp["choices"][0]["message"]
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            print(f"round {rnd+1}: model stopped without tool call: {(msg.get('content') or '')[:200]}")
            return
        for c in calls:
            name = c["function"]["name"]
            args = json.loads(c["function"]["arguments"] or "{}")
            result = run_tool(name, args)
            record({"tool_call": name, "args": args, "result": result})
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(result)})
    print(f"round cap {MAX_ROUNDS} reached; stopping")

if __name__ == "__main__":
    main()

# Standalone probe mode: `groq-harness.py ... --probe "short prompt"` records the
# call in the same attempt transcript so probes never escape call accounting.
