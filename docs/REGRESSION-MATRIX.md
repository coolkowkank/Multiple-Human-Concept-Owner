# Regression matrix (team-launcher)

Fixture-tested only — NOT live-verified, NOT peer-reviewed.
Pinned to the commit this file ships in. Live evidence below comes from
12 authorized single-seat attempts on live/groq-dev-1/-2 (2026-11-04).

## Observed failure classes (Groq gpt-oss-120b, live attempts)

| Class | Live count | Fixture coverage | Fix |
|---|---|---|---|
| reasoning exhaustion (cap) | 3 | -- | max_tokens cap (a29f7c5) |
| context window kill | 3 | -- | brief/task discipline (N1, 3017bbd) |
| path-contract violation | 3 | path guard + correction (0b7bb2e) | one path-guard correction round |
| malformed JSON (trailing prose) | 1 | format-correction round (7d40565) | strict revalidation, one correction |
| truncated JSON | 1 | format-correction round (same path) | same |
| unexpected tool call | 1 | -- | prompt: no tool calling |

## Call budget (ENFORCED global per-turn, review-corrected 2026-11-04)

At most 3 adapter complete() calls PER TURN, global across Bus.transact
race retries: 1 initial + at most ONE format-correction + at most ONE
path-guard correction (the two compose). Before this correction, the 3
were per transact attempt and a lost push race could re-invoke the
model (source ceiling 9 complete/turn). Now a retry that would exceed
3 fails closed (fixtures: race recount + excess-regeneration refusal).
HTTP is a separate layer: up to max_retries+1 (4) requests per
complete -> theoretical 12 HTTP/turn, retry-dependent, NOT
live-verified. Never quote "3 HTTP calls".
Raw model output is preserved unmodified on FORMAT failures (before
and after the correction round), with file paths - never content - in
SeatError/success notes. Path-guard rejections of VALID JSON are
recorded via the correction note naming the offending paths, not as
raw files. No silent dropping of model output; ambiguous multi-object
or contradictory trailing content fails closed.

Raw files are LOCAL-ONLY (review 2026-11-04): raw output may carry
private input, secrets, or copied context, so they live git-private
under .git/local-evidence/raw/ - outside the worktree, never staged
by git add -A. Guards: symlink-escape checked BEFORE any mkdir (a
refusal leaves zero side effects outside .git), no overwrite of
differing content (-vN suffix). Fixtures pin: secret marker in raw
reaches no commit, legacy tracked raw untouched, symlink refusal,
follow-up commit never sweeps. TOCTOU between path check and write is
not exercised. Publishing any raw payload requires an explicit
reviewed/redacted opt-in. Consequence: "zero mutation" on a failed
turn is git-state/app-code scoped - local evidence files can remain.

## Remaining gap

A live launcher-managed commit (model act_once -> real provider -> repo
commit via the launcher) is UNPROVEN after 12 attempts. All fixes are
fixture-tested only.

Minimal next repro (requires main's bounded live authorization):
1. team run --once --seat builder --brief "write hello world to src/hw.txt"
   on live/groq-dev-3 (fresh branch), seat gpt-oss-120b, reasoning_effort=low.
2. Expected success: exactly one commit by seat identity, LOG entry,
   turn_seq 1, status_line set, <= 3 adapter calls recorded.
3. On failure: .team/raw/*.txt + ATTEMPTS.md record the class; no retry
   without fresh authorization.
