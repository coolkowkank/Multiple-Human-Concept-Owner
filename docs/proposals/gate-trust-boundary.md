# Gate trust boundary - clarification before any gate implementation GO

Status: DESIGN CLARIFICATION, no code. Date: 2026-11-04. Author:
coordinator. Companion to candidate-acceptance-gate-v1 (main-attached
design, 2026-11-04). Answers the open question: what exactly stops the
model from minting or forging an acceptance gate?

## Actors
- M: the model-driving executor process (untrusted). Writes files only
  through its tool surface (write_file / edit_file / git_commit /
  git_publish_candidate).
- O: the operator (trusted human) who reviews the diff, runs the suite,
  and mints the gate.
- Publisher: the executor's publish path. Runs inside M's process but
  takes no parameters and pushes exactly the gated candidate SHA.

## Where the boundary actually sits today (honest)
WRITE_RE + safe_path confine the model's TOOL writes to
docs|tasks/*.md and launcher|tests/*.py, with symlink checks. The gate
file must live outside that set (outside the repo, or on a path the
regex cannot match). So at the tool level, M cannot write the gate file
directly. That is a TOOL-SURFACE boundary, not an OS boundary: M and O
share one OS user, and filesystem permissions alone stop nothing here.

## The hole that decides the design: the operator runs model code
The acceptance ritual is "operator runs the model's test suite green,
then mints". The suite EXECUTES MODEL-WRITTEN CODE (tests import the
model's modules) with the operator's privileges, in the operator's
environment. Any mint tool reachable from that context is callable by
the model through its own test code - the gate file location stops
write_file, not a subprocess spawned by model-authored tests.
Filesystem-implicit issuer authority is therefore NOT a boundary for
minting; it only protects the gate file between mint and publish.

## Options (owner decision required; none authorized now)
- O1 (hard boundary): review worktree + mint under a SEPARATE OS user
  (e.g. sudo -u reviewer), gate dir mode 0700 owned by that user, suite
  run there. Model code executes as reviewer; mint also as reviewer...
  which re-opens forgery UNLESS mint additionally requires something the
  suite context lacks: a credential in the operator's OWN session
  (O3-style) or interactive confirmation. O1 alone is insufficient for
  the same reason; O1 + O3 is the hard configuration.
- O2 (TTY-gated mint): mint refuses to run without an interactive
  terminal (isatty check + operator-typed confirmation). Model test code
  can allocate a pty, so this is a speed bump, not a boundary. Rejected
  as a standalone answer.
- O3 (environment separation, procedural): the suite runs in a scrubbed
  environment (env -i with minimal PATH); mint runs only in the
  operator's real shell and reads an operator-held secret (env var or
  key file mode 0600 outside the repo) for an HMAC over the gate JSON.
  Model test code under env -i never sees the secret. Boundary strength
  = the operator following the scrub procedure; it is procedural, not
  mechanical, and must be labeled that way.
Recommended: O3 interim with explicit procedural label; O1+O3 before any
live qualification claim. HMAC key setup is owner infrastructure and is
NOT authorized - this design does not assume it exists.

## Residual risks that survive every option (must stay in non-claims)
- The operator reviews and runs model code: semantic correctness and
  malicious-logic detection are human judgment; the gate binds bytes,
  not intent.
- A compromised operator machine or toolchain defeats everything.
- Model-written code in the REVIEW worktree's test run can still
  exfiltrate anything the review context can read (network). Mitigation:
  run the suite offline where possible; documented as operator procedure.

## Verification checklist before gate implementation GO
1. Gate file path provably outside WRITE_RE (regex proof + test,
   including ../ and symlink-parent attempts).
2. Tool surface enumeration: no executor tool writes outside safe_path
   (write_file/edit_file/git_commit/git_publish_candidate only).
3. Mint preconditions tested: clean worktree, HEAD == candidate,
   base ancestor, no staged/untracked bytes.
4. Publish-by-pinned-SHA test: post-mint commit cannot ride the push.
5. Chosen boundary option (O1/O3) documented in the repo WITH its
   procedural-vs-mechanical label; HMAC remains an owner decision.
6. Independent review of the gate implementation against probes A0-E3.
