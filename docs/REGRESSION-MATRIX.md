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

## Call budget (per act_once, documented in runtime.py)

At most 3 adapter calls: 1 initial + at most ONE format-correction + at
most ONE path-guard correction. The two corrections can compose.
Raw model output is preserved unmodified under .team/raw/ before and
after corrections (attempt-<n>.txt), with file paths - never content -
in SeatError/success notes. No silent dropping of model output;
ambiguous multi-object or contradictory trailing content fails closed.

Raw files are LOCAL-ONLY (review 2026-11-04): raw output may carry
private input, secrets, or copied context, so .team/raw/ is excluded
via .git/info/exclude and is never staged into public turn commits
(fixtures pin this, including a secret-shaped marker and a follow-up
turn). Publishing any raw payload requires an explicit
reviewed/redacted opt-in. Consequence: "zero mutation" on a failed
turn is git-state/app-code scoped - local untracked raw side-effect
files can remain.

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
