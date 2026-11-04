#!/usr/bin/env python3
"""Token-only GitHub push setup for standalone use (docs/standalone.md).

No GitHub password ever touches this repo. A user who wants model self-commits
with their own account (or a shared bot) creates a personal access token on
GitHub, stores it in a local 0600 file, and runs this once. It verifies the
token's account and push permission on the target repo, then configures a
repo-local git credential helper that reads the token file at push time.

Minimum classic-PAT scope: public_repo (public repos) or repo (private).
Fine-grained PATs only work for repos OWNED by the token's account - they
cannot write repos where the account is an outside/repo collaborator
(source: docs.github.com/managing-your-personal-access-tokens).

Usage: setup_push_auth.py --repo PATH --owner OWNER --name REPO [--token-file PATH]
Env:   PUSH_TOKEN_FILE (default <repo>/.git/mhco-push-token-path NOT used;
       default ~/.mhco/push-token), GITHUB_API_URL (tests only).
The token value is never printed, logged, committed, or passed via argv.
"""
import argparse, json, os, stat, subprocess, sys, urllib.request, urllib.error

API = os.environ.get("GITHUB_API_URL", "https://api.github.com")
NEEDED = {"public_repo", "repo"}
BROAD = {"workflow", "delete_repo", "admin:org", "admin:public_key", "admin:repo_hook",
         "admin:org_hook", "admin:enterprise", "delete:packages", "user", "gist"}

def http_json(path, token):
    req = urllib.request.Request(API + path, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "User-Agent": "mhco-push-auth-setup"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {}), dict(r.headers)
    except urllib.error.HTTPError as e:
        try: body = json.loads(e.read().decode() or "{}")
        except Exception: body = {}
        return e.code, body, dict(e.headers)
    except urllib.error.URLError as e:
        fail(f"cannot reach {API}: {e.reason}")

def fail(msg):
    print(f"setup-push-auth: ERROR: {msg}", file=sys.stderr)
    sys.exit(1)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="local clone/worktree to configure")
    ap.add_argument("--owner", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--token-file", default=os.environ.get("PUSH_TOKEN_FILE",
                    os.path.expanduser("~/.mhco/push-token")))
    a = ap.parse_args()

    if not os.path.isfile(a.token_file):
        fail(f"token file not found: {a.token_file} - create it (mode 0600) containing ONLY your GitHub token")
    mode = stat.S_IMODE(os.stat(a.token_file).st_mode)
    if mode & 0o077:
        fail(f"token file {a.token_file} is readable by group/other (mode {mode:o}); run: chmod 600 {a.token_file}")
    token = open(a.token_file).read().strip()
    if not token:
        fail("token file is empty")

    st, body, hdrs = http_json("/user", token)
    if st == 401:
        fail("token rejected (401 Bad credentials): create a classic personal access token at https://github.com/settings/tokens (minimum scope: public_repo for public repos)")
    if st != 200:
        fail(f"identity check failed: HTTP {st}")
    login = body.get("login") or fail("identity response had no login")
    scopes = {s.strip() for s in (hdrs.get("X-OAuth-Scopes") or hdrs.get("x-oauth-scopes") or "").split(",") if s.strip()}

    st, repo, _ = http_json(f"/repos/{a.owner}/{a.name}", token)
    if st == 404:
        fail(f"repository {a.owner}/{a.name} not found OR account '{login}' has no access (GitHub returns 404 for both)")
    if st != 200:
        fail(f"repository check failed: HTTP {st}")
    if not (repo.get("permissions") or {}).get("push"):
        fail(f"token verified as '{login}' but the account has NO push permission on {a.owner}/{a.name} (collaborator access required)")

    if scopes and not (scopes & NEEDED):
        print(f"setup-push-auth: WARNING: token scopes {sorted(scopes)} include neither repo nor public_repo; pushes will likely be rejected", file=sys.stderr)
    broad = scopes & BROAD
    if broad:
        print(f"setup-push-auth: WARNING: token carries broad scope(s) {sorted(broad)} beyond push needs; consider a minimal token", file=sys.stderr)

    helper = '!f() { echo username=x-access-token; echo "password=$(cat ' + a.token_file + ')"; }; f'
    subprocess.run(["git", "-C", a.repo, "config", "credential.helper", helper], check=True)
    print(f"setup-push-auth: OK - token account '{login}', push access to {a.owner}/{a.name} verified")
    print(f"setup-push-auth: repo-local credential helper set in {a.repo} (reads {a.token_file} at push time; token never stored in git config)")
    print("setup-push-auth: author/committer identities stay separate - set per-model author names via MODEL_AUTHOR (see docs/standalone.md)")

if __name__ == "__main__":
    main()
