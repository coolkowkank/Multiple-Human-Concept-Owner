# Operator guide: langgraph_team.py (offline demos, closeout, live entry)

Status: work in progress. Every command below was run offline against this
branch head with scratch directories and a fake HOME. Nothing here was run
against the real router. Bus `done` means the team CYCLE finished. It is not a
quality result. Free route only: a model listed at price 0 is a listing fact,
not billing proof.

## Prerequisites

- Python >= 3.10 (tested 3.10.12), `git`, and for anything model-backed or
  closeout-related `bwrap` and `prlimit` on Linux.
- `pip install langgraph==1.2.19 langgraph-checkpoint-sqlite==3.1.3` (a venv is
  fine). The project `launcher/` is vendored in this directory; nothing else
  to install.
- Git needs a user identity (`git config --global user.name/user.email`) or the
  bus commits fail.
- `LG_VERIFY_SANDBOX=1` makes seat verify commands run through the bwrap shim.
  `live` refuses without it. Set it for every run you care about.

## Environment variables

| Variable | Meaning |
|---|---|
| `LG_VERIFY_SANDBOX=1` | Run seat verify commands in bwrap. Required by `live`. |
| `LG_OPERATOR_CONFIG=PATH` | Path (never the key) to the operator closeout config. Unset = quality unproven. |
| `LG_ALLOW_UNPROVEN=1` | Exit 0 from `run`/`live` even when quality is unproven. Still prints "quality unproven". |
| `LG_AUDIT_DIR=DIR` | Opt-in prompt/usage audit wrapper around http seats (audit_wiring.py). |
| `REQUESTY_API_KEY` | Set by `live` for the run only, from your key file. Do not export it yourself. |

`HOME` must be the account's real home. The Fenced usage ledger lives at
`~/.lg-http-usage`, and the reserve preflight refuses if `HOME` differs from the
account home (a moved ledger path looks identical to a deleted ledger).

## Commands

Arguments are positional. Missing arguments print a one-line usage message and
exit 2.

| Command | What it does | Exit |
|---|---|---|
| `init LANE DB` | New mock-seat lane. Refuses root, home, cwd and any non-empty directory. | 0 |
| `init-http LANE DB SEAT MODEL EPOCH` | New lane with ONE seat on a fenced http spec, `call_budget` fixed at 2. Prefer `live` for real use. | 0 |
| `run LANE DB [STOP_AFTER [THREAD]]` | Run the graph. `STOP_AFTER` N stops gracefully after N seat actions (resumable). Default thread `team-demo-1`. When the bus is done it runs the operator closeout. | 0 only if closeout allowed, or `LG_ALLOW_UNPROVEN=1`, or a deliberate stop that left the bus running. 3 otherwise. |
| `verify LANE DB [N [THREAD]]` | Re-verify a resumed run. | 0 / 1 |
| `status LANE` | Closeout status with no record: prints "cycle complete, quality unproven" (or "cycle not complete"). | 1 |
| `status LANE --record R --key-file K --checker-id C --path P [--path P ...]` | Re-verifies the signed operator record. `--repo` and `--branch` are fixed by the launcher and refused. | 0 only if closeout allowed; 1 otherwise; 2 for a repeated `--repo`/`--branch` |
| `live LANE DB CONFIG [THREAD] [--allow-fresh]` | Reproducible model-backed entry (below). | 0 only if closeout allowed or a deliberate `stop_after` left the bus running; 3 for quality unproven, blocked, failed or not done; 1 for a refusal |

Offline demo sequence (all three lanes must exist before `parallel_team.py`):

```
python integration/langgraph/langgraph_team.py init /tmp/demo/lane-a /tmp/demo/db-a.sqlite
python integration/langgraph/langgraph_team.py run  /tmp/demo/lane-a /tmp/demo/db-a.sqlite 2 team-demo-a
python integration/langgraph/langgraph_team.py init /tmp/demo/lane-b /tmp/demo/db-b.sqlite
python integration/langgraph/langgraph_team.py init /tmp/demo/lane-c /tmp/demo/db-c.sqlite
python integration/langgraph/parallel_team.py /tmp/demo
python integration/langgraph/controls_demo.py /tmp/lg-controls
```

`run` on a lane that reaches done without `LG_OPERATOR_CONFIG` prints
`closeout: {... "reason": "no operator config"}` and exits 3. That is the
expected outcome for the mock demos, not a failure of the cycle.

## Closeout (operator-owned)

See README "Closeout status" and "Operator-owned finalization" for the trust
model. Operator config (JSON, 0600, outside the lane): `checker_script`
(absolute path), `checker_id` (sha256 of `lg-sandboxed-checker/v1` + script
bytes), `artifact_paths`, `key_file` (0600, raw bytes, no trailing newline),
`record_dir` (0700), optional `timeout` (max 300). The checker runs inside bwrap
on a clean export of the committed files and must print exactly
`{"accepted": true|false}`. The checker must run the candidate in a CHILD
process and keep expected values and the verdict in the PARENT, and must set
the parent non-dumpable (`PR_SET_DUMPABLE=0`, return code checked, fail closed).
No checker ships in this repo for real work. The one used in
`done_gate_test.py` is a plumbing test only. Evidence is bounded to the files
and cases checked. It is not proof, and one checker covers one artifact type.

## `live`: model-backed multi-seat run (operator-run, never inside a seat)

Setup, once:

```
export LG_VERIFY_SANDBOX=1
python integration/langgraph/langgraph_team.py init /ops/lane /ops/db.sqlite
cp integration/langgraph/examples/live_config.example.json /ops/live.json
cp integration/langgraph/examples/brief_reply_rules.md /ops/brief_rules.md
chmod 600 /ops/live.json /ops/requesty.key /ops/brief_rules.md
```

Config keys (anything else is refused): `key_file`, `seats`, `brief_extra_file`,
`stop_after`, `preflight`. Seat keys: `model`, `epoch`, `budget` and optional
`max_tokens` (default 6000, max 8000). Seat names must exist in the lane roster
(`coordinator`, `builder`, `reviewer`, `qc`, `records`). `budget` is 1..8. Model
must be one of two allowlisted ids (see `HTTP_FREE_MODELS` in langgraph_team.py).
`epoch` is `[a-z0-9-]{1,32}` and names the Fenced log file. Config, key and brief
files must be regular, owned by you, mode 0600 and outside the lane. Brief rules
are capped at 16KB and appended once.

Order of checks (every refusal happens before any request or lane change):
files and modes, verify sandbox, seat specs, brief file, `preflight` keys,
reserve preflight, then a GET of the router `/models` listing (this request
carries your key and must show price exactly 0 for each seat model), then roster
writes and brief rules, then the run, then closeout.

Call budget: each seat `budget` is a ceiling on requests, and a format-correction
retry is a second request that comes out of the same budget. Fenced enforces a
lifetime cap of 8 requests across ALL logs for this account. The preflight sums
the budgets of every http seat that will run (configured seats plus any other
http seat already in the roster) and refuses if that exceeds what is left.
Check the number you are about to plan against the ledger, not against this
page. A single seat with `budget` 1 cannot use a correction round.

### Reserve preflight and the anchor

`reserve_preflight.py` only reads the Fenced logs. It reserves nothing, and
Fenced owns atomic reservation. It verifies the hash chain, line shapes and
sequence, halt lines, file names, and that the log dir is 0700 and yours (an
older 0755 dir must be `chmod 700`ed; contents untouched).

- A missing or empty ledger is `unestablished` and refused. `--allow-fresh` (CLI
  flag only, never in the config) asserts that this is a first run. It is
  ignored when `anchor_file` or a non-zero `expected_min_reserves` is set.
- `preflight.expected_min_reserves`: refuse if fewer reserves are recorded.
  A non-integer or negative value refuses. Zero is an integer but disables the
  minimum, so set it to the last verified total.
- `preflight.anchor_file`: a `reserve_preflight.snapshot()` JSON stored outside the
  log dir, in a private (0700) directory you own, mode 0600, which must already
  exist before `live` runs. It catches tail truncation and rewritten history.
  `live` refuses before any request or roster write unless the file loads as a
  `reserve-preflight/v1` snapshot object with files (null, blank, non-object,
  `{}`, wrong schema, unreadable or missing all refuse). There is no command that creates the first one. This script writes it only from
  a verified ledger, exits without writing otherwise, creates the file 0600 and
  refuses to overwrite an existing file. Run it from `integration/langgraph`
  with the real account HOME:

```
mkdir -p -m 700 /ops/private
python3 - <<'PY'
import json, os, sys, reserve_preflight as r
s = r.snapshot(r.preflight(0))
if s is None:
    sys.exit("ledger does not verify; no anchor written")
fd = os.open("/ops/private/reserve_anchor.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as fh:
    json.dump(s, fh)
print("anchor written; reserves =", s["reserves"])
PY
```

Then set `expected_min_reserves` to the printed `reserves` value. Never point
`anchor_file` at a file that was not produced by a verified preflight.
- The anchor covers only the log files named in it, each up to the line count and
  chain tip it recorded. It does not cover the whole ledger. A log that is not in
  the snapshot (a new epoch file, or a file deleted before the snapshot) is not
  checked against it, and a rewrite that keeps the anchored prefix is not seen.
  `expected_min_reserves` is the second check: it catches a drop in the total, not
  a swap. Neither is tamper-proof, since the same account can edit the ledger, the
  anchor and the config. Keep `expected_min_reserves` at the last verified total
  for this account (7 at the last real preflight; confirm against the ledger, it
  is not a universal number).
- After a run, if the ledger verifies against the old anchor, `live` replaces the
  anchor atomically with a fresh snapshot. It never raises
  `expected_min_reserves`; do that yourself.
- Cap across different model/epoch logs is not atomic across processes. Run ONE
  `live` at a time. Anchor, ledger and config are same-user storage: deleting
  the ledger and the anchor together is not detectable.

First run on an account with no ledger: `live ... --allow-fresh` with no
`preflight` block is the only supported path (the flag is an operator statement,
not proof). After that run, create the anchor with the script above and set
`expected_min_reserves` to the printed total. On an account that already spent
requests, always configure both `anchor_file` and `expected_min_reserves`.

The example config's `expected_min_reserves` is a text placeholder on purpose, so
an unedited copy refuses ("must be a non-negative int"). Replace it with your
account's last verified reserve total as an integer. No number in any example is
universal. The ledger on your account is the source of truth.

### What the example proves and does not prove

Different models per seat are a configuration, not an independence check. The
reviewer seat is instruction-guided, same-family review is not independent
review, and model quality is unqualified. Free-route runs spend a small lifetime
allowance (the ledger on this account shows how much is left), so they are not
free-unlimited.

## Rough edges (source gaps, not documented features)

- No command creates the first anchor except the script above.
- `reserve_preflight.py` run by itself applies the same anchor rule as `live`: a
  v1 snapshot with a non-empty `files` object and well-formed entries, else it
  refuses (exit 1). It still does not create anchors; use the script above.
- `init-http` hard-codes `call_budget` 2, so `live` is the only way to set budgets.
- `live` runs with `stop_after` from the config; `stop_after: 0` or absent runs to
  the end of the graph.
- Same-user storage: config, key file, anchor and ledger can all be changed by
  the same account. The anchor and minimum raise the bar. They are not tamper-proof.
