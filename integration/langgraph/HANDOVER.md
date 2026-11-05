# Handover: taking over this integration without the previous operator

Audience: a new operator, human or AI, starting from a clone of this repository and nothing else. No chat history, no access to the previous operator's accounts or password store is assumed.

Scope: setup, state and limits. It does not qualify any model route, clear any halt, or approve any request. Everything here ran offline. No live run is claimed.

## 1. Recover in a fresh environment (about 1 minute, offline apart from git and pip)

```
sh integration/langgraph/handover_fresh_check.sh <repo-url-or-path> <ref>
```

It clones into a temp dir, builds a new venv with the pinned packages (`langgraph==1.2.19`, `langgraph-checkpoint-sqlite==3.1.3`), scrubs the environment, runs `handover_check.py env` and every `*_test.py`, and prints `FRESH-CHECK OK` only when all exit 0. It reads no key and makes no model or provider request. Your global git config is not touched.

Requirements it relies on: Python >= 3.10, git, a git identity (the script supplies a throwaway one), `bwrap` and `prlimit` for anything model-backed. `HOME` must be the account's real home: the reserve preflight and `live_entry_test.py` refuse a moved `HOME`, because a moved ledger path looks like a deleted ledger. Running the tests under a made-up `HOME` fails 6 checks in `live_entry_test.py`. That is the guard working, not a bug in your setup.

Last result recorded by the author: new clone of `live/operator-done` at d4a7485 plus the files in this change, new venv, scrubbed environment, all test files exit 0. This was run in one sandbox by the same agent family that wrote the code. It has not been tried on a second machine or by a second person.

## 2. Credentials (standard configuration)

- Provider key: a file you create, mode 0600, owned by you, outside the repository and outside any lane. `live` reads it and sets `REQUESTY_API_KEY` for that run only. Do not export it in your shell and do not put it in a brief, a prompt, a config in the repo or a commit.
- Runner allowance key: `RYAN_ALLOWANCE_KEY_FILE` names an absolute, owner-only (0600), regular file outside the repo. It is a local random secret used only to sign `allowance.json`, so the runner can tell an edited permit from a made one. It is not a provider key and it logs into nothing. Generate your own. Whoever can read it can sign, so treat it as a tamper and accident check, not as proof that a person approved anything.
- Nothing from the previous operator's secret storage transfers. You supply your own provider key and your own allowance key. Moving a secret between operators happens outside this repository and outside any prompt.
- `python3 integration/langgraph/handover_check.py env` reports which of these variables are set (names and set/unset only) and the key file's mode. It never prints a value.

## 3. What is not in Git, and why

Private operator state lives in directories you choose, outside the repo:

| Item | What it is | Rule |
|---|---|---|
| Runner root: `ledger.jsonl`, `queue.json`, `assignments.json`, `allowance.json`, `runs/` | The runner's history, queue, model assignments and permit | Private. Raw contents are not published. Move it only by a private handover. |
| Shared request log: `~/.lg-http-usage/*.jsonl` | The fenced adapter's reserve and result history and its lifetime cap | Private. Separate from the runner ledger. The two counts do not add up to one total and neither replaces the other. |
| Audit and output dirs (`LG_AUDIT_DIR`, `live_output/`) | Prompt and usage audit | Private. May contain prompts and completions. |
| Key files | See section 2 | Never in Git, never transferred through a prompt or a message. |

Rules that carry over to you:
- A halt or an unknown outcome in a ledger stands until a human clears it citing an external condition. Starting a fresh root, a new `HOME` or a renamed lineage to get around it is a reset of history, not a fix.
- Deleted or truncated history is not detectable without an operator anchor (see OPERATOR_GUIDE.md, "Reserve preflight and the anchor").
- Pins and md5 values in the tests are reviewed constants. If one moves, read the commit that moved it before you trust it.

## 4. Private state summary (for a private handover only)

```
python3 integration/langgraph/handover_check.py state --root <runner-root> [--log-dir <shared-log-dir>]
```

Read-only. It takes no lock, creates nothing and writes nothing. It prints counts by phase, role and outcome, whether a halt stands, reserves with no result, queue item ids and statuses, assigned model ids, and sha256 of each state file. It does not print prompts, completions, finding text, key contents or environment values. It flags an unparseable ledger line and a runner root inside a git work tree. It carries a "do not publish" label: send its output only through the same private route as the state itself.

It reports what the files say. It resolves nothing: an unknown outcome stays unknown, a standing halt stays standing.

## 5. First hour for a new operator

1. Run section 1 on the exact commit you were handed. Record the head and the result.
2. Run `handover_check.py env` in your real environment and fix every blocking line.
3. Read OPERATOR_GUIDE.md sections "Prerequisites", "Reserve preflight and the anchor", "Spending seats and the supervisor", "Runner roles through the shared fence".
4. Receive the private state by the private route. Run section 4 against it. Compare the head, hashes and counts with what the previous operator told you. Differences are a stop, not something to repair.
5. Do not run anything model-backed until the owner of the project has made the budget and permit decisions for your window in the project's decision channel, and you have supplied your own keys.

## 6. Roles and jobs

The team roster, blueprints and lifecycle rules are in `docs/team/` on the `team-launcher` branch (registry.md, lifecycle.md, blueprints). The registry is a name and role list. It does not by itself authorize models, spending or merges, and its status column is not a qualification. Model selection for each role belongs to the project's coordinator under the owner's instruction. No model route is recorded as qualified for any role.

## 7. Limits of this handover

- Tested offline in one environment. Not tested on another machine, with another person, or with another AI operator.
- `handover_check.py` is a report. It does not detect tampering with same-user files.
- Passing tests show offline behavior with fake posts. They are not evidence of live reliability, quality or autonomy.
