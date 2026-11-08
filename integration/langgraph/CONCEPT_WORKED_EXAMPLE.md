# Worked example: concept in, team out - a full queue-driven cycle

A real, replayable walkthrough: one project concept goes in, a conformant
five-seat team repo comes out, and the team runs a complete cycle
(coordinator -> builder -> reviewer -> qc -> records -> done) driven
entirely through the operator queue boundary.

Offline after the one pip install: no keys, no model calls, no provider
IO. Every seat response below is operator-authored and queued through
`python3 -m launcher respond` - the reviewed reasoning boundary. The
harness owns the turn, lease, verify and record; the reasoning is yours.
Nothing here fakes a model.

Transcripts below are real output from this exact sequence (paths
shortened: `$W` = the scratch directory, `python` = the venv python).
The whole walkthrough is also a runnable proof - `concept_cycle.py`
drives every step below through the real CLIs and asserts each
transcript's claim (run it: `python3 concept_cycle.py /tmp/lg-concept-cycle`);
the clean-room proof (`cleanroom_test.py`) runs it on a pristine export
of HEAD.

## 1. Setup

```sh
cd integration/langgraph
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

## 2. Put the concept in

```sh
cat > $W/concept.md <<'EOF'
# Concept
A CLI unit converter (km<->mi, kg<->lb) with tests.
EOF

python concept_scaffold.py $W/unit-converter --concept-file $W/concept.md
```

```
note: status=running turn=coordinator seq=0
note: gates: 0 total, 0 open
note: brief has no definition-of-finished section
conformance: PASS

Scaffolded concept team at $W/unit-converter
The repo sits at the coordinator's first turn. Drive it:
  python3 -m launcher prompt coordinator --repo $W/unit-converter
  python3 -m launcher respond coordinator --repo $W/unit-converter --file R.json
  python3 -m launcher seat coordinator --repo $W/unit-converter --once
or run the graph (waits at each seat for a queued response):
  python3 langgraph_team.py run $W/unit-converter /path/to/checkpoints.sqlite3
```

The scaffold refuses to print that summary unless `launcher conform`
passes. The concept is now `.team/brief.md`, verbatim, on branch
`team-work`; all five seats (coordinator, builder, reviewer, qc, records)
are queue seats; the coordinator holds the first turn.

## 3. The rhythm: run, wait, respond, resume

Run the graph. It acts until a seat has nothing queued, then stops
gracefully with an explicit WAITING surface - not an error, not a
refusal:

```sh
python langgraph_team.py run $W/unit-converter $W/cp.sqlite 0 walkthrough-1
```

```
  step: [pid 106034 tid ...] seat=coordinator WAITING (response queue empty)
run[walkthrough-1]: WAITING for an operator response for seat 'coordinator' (.team/queues/coordinator.jsonl is empty). This is the expected state of a queue seat, not an error.
  1. read the prompt:   python3 -m launcher prompt coordinator --repo $W/unit-converter
  2. queue the answer:  python3 -m launcher respond coordinator --repo $W/unit-converter --file response.json
  3. resume the run:    python3 langgraph_team.py run $W/unit-converter $W/cp.sqlite 0 walkthrough-1
run[walkthrough-1]: stopped gracefully while waiting (checkpoint durable in $W/cp.sqlite)
```

Exit code is 0: a deliberate resumable stop, like `--stop-after`. The
checkpoint is durable mid-graph, so re-running the same command resumes
exactly where it stopped.

Read the seat's prompt (`launcher prompt coordinator --repo ...`), reason
about it however you like - yourself, a colleague, a chat assistant, later
an approved model route - then write the response as one JSON object and
queue it:

```sh
python -m launcher respond coordinator --repo $W/unit-converter --file $W/resp-coordinator.json
```

```
queued response for coordinator (bound to turn='coordinator' seq=0 head=3adff09295fb); run `python3 -m launcher seat coordinator --repo $W/unit-converter --branch team-work --once` to take the turn
```

The response is bound to the exact turn/sequence/head it was reasoned
against; if the bus moved since, the runtime refuses it as stale instead
of applying it to the wrong state.

Resume with the same command. The coordinator acts, commits, hands off -
and the graph waits at the next seat:

```
run[walkthrough-1]: resuming from checkpoint 1f1dbad5-f9f9-67d5-8002-92ddcfe6f74c
  step: [pid 106064 tid ...] seat=coordinator acted=True head=a20f99f seq=1
  step: [pid 106064 tid ...] seat=builder WAITING (response queue empty)
run[walkthrough-1]: WAITING for an operator response for seat 'builder' ...
```

Repeat per seat. The five responses used in this walkthrough:

```json
coordinator:
{"summary": "drafted acceptance criteria from the concept",
 "writes": {".team/ACCEPTANCE.md": "# Acceptance criteria\n1. converts km<->mi and kg<->lb\n2. test suite green\n"},
 "verify_command": null, "handoff": "builder",
 "status_line": "criteria drafted, builder on turn"}

builder:
{"summary": "implemented the converter with tests",
 "writes": {"src/convert.py": "def km_to_mi(km):\n    return km * 0.621371\n\ndef mi_to_km(mi):\n    return mi / 0.621371\n\ndef kg_to_lb(kg):\n    return kg * 2.20462\n\ndef lb_to_kg(lb):\n    return lb / 2.20462\n",
            "tests/test_convert.py": "import sys, os\nsys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))\nfrom convert import km_to_mi, mi_to_km, kg_to_lb, lb_to_kg\nassert abs(km_to_mi(1) - 0.621371) < 1e-9\nassert abs(mi_to_km(1) - 1.60934) < 1e-3\nassert abs(kg_to_lb(1) - 2.20462) < 1e-9\nassert abs(lb_to_kg(1) - 0.453593) < 1e-6\nprint('ok')\n"},
 "verify_command": "python3 tests/test_convert.py", "handoff": "reviewer",
 "status_line": "batch built and verified"}

reviewer:
{"summary": "re-ran builder verify: green; no findings",
 "writes": {"review/findings-1.md": "# Findings batch 1\nNone.\n"},
 "verify_command": "python3 tests/test_convert.py", "handoff": "qc",
 "status_line": "review green"}

qc:
{"summary": "verdict PASS on the cycle evidence",
 "writes": {"review/qc-verdict-1.md": "# QC verdict 1\nPASS.\n"},
 "verify_command": "python3 tests/test_convert.py", "handoff": "records",
 "status_line": "QC PASS"}

records:
{"summary": "archived batch 1; closing the cycle",
 "writes": {"records/archive-1.md": "# Archive 1\nBatch 1 closed: converter + tests, QC PASS.\n"},
 "verify_command": null, "handoff": null,
 "status_line": "DONE - cycle 1 QC pass"}
```

Each seat can only write inside its own roster-scoped paths (the
coordinator writes under `.team/`, the builder under `src/` and `tests/`,
and so on); anything else is refused pre-mutation. A seat's
`verify_command` runs for real and its exit code is recorded - the
builder's test suite actually ran green in this walkthrough. The cycle
closes when a seat answers with `handoff: null` and a `status_line`
starting with `DONE`.

## 4. Final run and honest closeout

After the records response is queued, the resume runs to the end:

```
run[walkthrough-1]: resuming from checkpoint 1f1dbad6-14b5-6238-8012-be9567ced72e
  step: [pid 106376 tid ...] seat=records acted=True head=54a32d7 seq=1
run[walkthrough-1]: finished. status=done outcome=reached END (done)
run[walkthrough-1]: this status is the team CYCLE only. Quality is unproven unless `langgraph_team.py status` allows closeout.
closeout: {"closeout_allowed": false, "cycle_complete": true, "label": "cycle complete, quality unproven", "reason": "no operator config", "terminal_done": false}
```

```sh
python langgraph_team.py status $W/unit-converter
```

```json
{"closeout_allowed": false, "cycle_complete": true, "terminal_done": false,
 "label": "cycle complete, quality unproven", "reason": "no operator record"}
```

## What this proves - and what it does not

Proven: the concept reaches the brief and the coordinator's prompt
verbatim; the full five-seat cycle runs on a scaffolded repo through the
queue boundary with lease, path guards, verify, stale-binding refusals,
handoffs, durable checkpoints and graceful waiting stops; the cycle
closes `done` and every artifact above is committed in the project repo.

Runnable proof: `concept_cycle.py` replays this entire walkthrough and
asserts every claim above (22 checks).

Not proven: quality. `done` is the team cycle only - closeout stays
`quality unproven` until the operator's own acceptance evidence exists
(see OPERATOR_GUIDE.md and done_gate). And no model was involved: queue
seats move only on responses someone reasoned elsewhere. Wiring a real
model seat is the live/* lane's job and needs the provider route,
budget and approval - none of which this example touches.
