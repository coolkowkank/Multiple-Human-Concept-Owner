#!/usr/bin/env python3
"""Standalone Groq<->reviewer loop runner (docs/review-loop.md).

Watches a public review branch for immutable FEEDBACK-cN.md files, runs the
self-commit executor with the feedback VERBATIM as the task, and advances
LOOP.json. No Instinct dependency: python3 + git + the executor.

Human control: the runner never merges, never changes access, and stops at
the global budget; terminal outcomes are for the human/reviewer to read.

Usage:
  loop_runner.py --repo MODEL_WORKTREE --records RECORDS_WORKTREE \
      --review-branch review/groq-dev-3 --budget 6 [--once] [--interval 3600]
Env: PROVIDER_KEY_FILE (+ executor's own env), GIT_AUTHOR_NAME/EMAIL or
git config for operator commits, push credentials via git's own helper.
"""
import argparse, json, os, re, subprocess, sys, time

def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True, check=check)

def load_loop(repo):
    p = os.path.join(repo, ".team", "review", "LOOP.json")
    return json.load(open(p)) if os.path.exists(p) else None

def save_loop(repo, loop, msg):
    p = os.path.join(repo, ".team", "review", "LOOP.json")
    with open(p, "w") as f:
        json.dump(loop, f, indent=2)
    git(repo, "add", "--", ".team/review/LOOP.json")
    git(repo, "commit", "-m", msg)
    git(repo, "push", "origin", "HEAD")

def remote_file(repo, branch, path):
    r = git(repo, "show", f"origin/{branch}:{path}", check=False)
    return r.stdout if r.returncode == 0 else None

def count_calls(transcript_path):
    try:
        events = json.load(open(transcript_path))
    except (OSError, json.JSONDecodeError):
        return 0
    return sum(1 for e in events if isinstance(e, dict) and ("api_response" in e or "api_error" in e))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--records", required=True)
    ap.add_argument("--review-branch", required=True)
    ap.add_argument("--budget", type=int, default=6)
    ap.add_argument("--executor", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "self-commit-executor.py"))
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=3600)
    a = ap.parse_args()

    while True:
        git(a.repo, "fetch", "origin", check=False)
        loop = load_loop(a.repo)
        if not loop or loop.get("state") in ("VERIFIED", "ESCALATE"):
            print("loop terminal or missing; nothing to do")
        else:
            n = loop.get("cycle", 1)
            fb = remote_file(a.repo, a.review_branch, f".team/review/FEEDBACK-c{n}.md")
            fb_sha = None
            if fb is not None:
                fb_sha = subprocess.run(["git", "-C", a.repo, "rev-parse", f"origin/{a.review_branch}"],
                                        capture_output=True, text=True).stdout.strip()
            used = loop.get("api_used", 0)
            remaining = a.budget - used
            if fb is None or fb_sha == loop.get("feedback_sha"):
                print(f"cycle {n}: no new feedback; state={loop.get('state')}")
            elif remaining <= 0:
                loop.update(state="ESCALATE", notes="budget exhausted with unaddressed feedback")
                save_loop(a.repo, loop, "operator: loop ESCALATE - budget exhausted, feedback unaddressed")
                print("ESCALATE: budget exhausted")
            else:
                task = os.path.join(a.repo, ".team", "review", f"task-c{n}.md")
                with open(task, "w") as f:
                    f.write(f"Review feedback (immutable source: origin/{a.review_branch} "
                            f".team/review/FEEDBACK-c{n}.md @ {fb_sha}) follows VERBATIM. "
                            "Apply it via your own tool calls.\n\n" + fb)
                env = dict(os.environ, RECORDS_DIR=a.records, MAX_CALLS=str(remaining))
                r = subprocess.run([sys.executable, a.executor, a.repo,
                                    loop.get("model_branch", "live/groq-dev-3"),
                                    f"loop-c{n}", task], env=env)
                calls = count_calls(os.path.join(a.repo, ".team", "attempts", f"loop-c{n}-transcript.json"))
                if r.returncode != 0:
                    loop.update(state="ESCALATE", api_used=used + calls,
                                notes=f"executor failed cycle {n} after {calls} calls")
                    save_loop(a.repo, loop, f"operator: loop ESCALATE - executor failure cycle {n}")
                    print(f"ESCALATE: executor exit {r.returncode}, {calls} calls")
                else:
                    head = git(a.repo, "rev-parse", "HEAD").stdout.strip()
                    loop.update(state="FIX_COMMITTED", pinned_sha=head,
                                feedback_sha=fb_sha, api_used=used + calls)
                    save_loop(a.repo, loop, f"operator: cycle {n} FIX_COMMITTED {head[:9]} ({calls} calls, {used+calls}/{a.budget} total)")
                    print(f"cycle {n}: FIX_COMMITTED {head[:9]}, budget {used+calls}/{a.budget}")
        if a.once:
            return
        time.sleep(a.interval)

if __name__ == "__main__":
    main()
