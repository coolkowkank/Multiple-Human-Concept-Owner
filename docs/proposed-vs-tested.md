# Proposed vs Tested Capabilities

## Live Verified

- **Capability**: token-only GitHub push transport for standalone runs (tools/setup_push_auth.py + repo-local credential helper reading a 0600 token file; no GitHub password involved).
- **Status**: LIVE-VERIFIED 2026-11-04 - a token account was verified via the GitHub API and its push permission on this repository confirmed by the setup tool; this commit's own push is the transport proof.
- **Notes**: Keep the two limits: token scopes are the capability ceiling; human project authorization is the operating boundary. Author, committer and pusher identities stay separate (D14).
