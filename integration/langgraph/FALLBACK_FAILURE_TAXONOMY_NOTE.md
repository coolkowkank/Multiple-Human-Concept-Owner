# Backup-route failure taxonomy (PROPOSAL, no authority, no code)

Status: design note read from `fenced_http.py` at 65be5c7. Nothing here is implemented, run or approved. It grants no cross-provider prompt disclosure: provider and brief scope must be recovered per actual job and per route. It is not RW6 and does not start it.

## Five separate facts per attempt (from the durable log, never exception text or log tail)
1. request_reserved: a reserve line for that n exists (written before any I/O). It means a request may have been attempted.
2. result_received: a result line exists. It is this process's local observation (status or exception class), not proof of what the provider executed.
3. usable_response: the body parsed into the required structure. Independent of the rest. An empty-content 200 is a completed, counted request with an unusable reply, not a failed execution.
4. cost_known: provider-reported cost exactly 0, a positive number, or missing. Provider-reported zero is a provider report, not independently verified cost. Nonzero or missing on a 200 already writes a global halt.
5. outcome_unknown: true for everything except a reserve plus a usable 200 reported at cost 0. That includes no result line, timeout or socket errors, 5xx, redirects (never followed), 429, bad status or size, malformed 200 and any 4xx. None of these proves the upstream did not execute.

## No safe-resend proof
Nothing in the log proves a request is safe to resend to another route. Only a refusal that happens before the reserve line (a code-path fact) would not duplicate a possibly executed call, and even that is unimplemented. After a reserve line, a route change needs an operator.

## Route-local vs global
- Missing key env: checked before any log is opened. Route-local.
- Chain broken and halted: `_read_all` walks every `*.jsonl` in the log dir, so one route's broken chain or halt refuses all routes sharing that dir. Global or integrity.
- Budget exhausted: one error text covers `mine >= call_budget` (route-local) and `total >= HTTP_LIFETIME_CAP` (global). A caller cannot split them without a structured reason in the adapter.

## Shared cap is not atomic
The lifetime total and halt flag span routes sharing HOME/.lg-http-usage, and unmatched reserves count. The flock is per log file, not per directory, and the total is read before the reserve is written, so concurrent processes on different routes can each pass the check. Fallback routes would use different log files, so this gap widens. A fresh dir or HOME does not see the old ledger (the guarded reset evasion). Not verified: whether `reserve_preflight` tolerates odd lines the same way as `_read_all`.
