# RW1 offline handoff validator spec (design only, Researcher agent, 2026-11-04)
Status: proposal for Builder; no code changed, no provider calls. Pending Eva review.

## Read evidence (repo reads, branch live/builder-deadlock-fix @ 2024e2d3; runtime.py last changed 344942a4, adapters.py fe14bcf6)
- runtime.py ~L503-531 (act: after the model response): `handoff = response.get("handoff")`; only check is that a non-null handoff names a seat in the roster. Then `state["turn"] = handoff`.
- Only `status_line` starting with "DONE" sets status done and turn None. Any other response with `handoff: null` sets `turn = None` while status stays "running".
- prompts.py L13/L29: prompt tells the model null is for DONE only; nothing enforces it.
- Recorded case: builder seq 2 `handoff: null`, 11:13:18 UTC (docs/proposals/groq-deadlock-fix.md). H (hypothesis): that state has no seat to act and no gate; read is code-path only, not re-executed.

## Proposed validation rules (check before write_state)
V1 handoff null is valid only if status_line starts with DONE, or a gate was opened in this response. Otherwise reject (fail closed, ask one regeneration within the existing per-turn call budget, else end turn honestly).
V2 handoff non-null must be a roster seat (exists today) and not empty string.
V3 handoff == own seat name: reject unless roster allows self-turns.
V4 DONE with non-null handoff: reject (ambiguous).
V5 summary missing or "(no summary)": warn, do not reject.

## Offline replay fixtures (no model calls)
F1 {handoff:null,status_line:"working"} -> reject (V1). Reproduces recorded null-handoff.
F2 {handoff:null,status_line:"DONE: ..."} -> accept.
F3 {handoff:null,gate:{question:"..."}} -> accept.
F4 {handoff:"nobody"} -> reject (V2, existing).
F5 {handoff:"Eva"} valid seat -> accept.
F6 {handoff:"",status_line:"x"} -> reject (V2).
Success criterion: F1 and F6 never leave state turn=None with status running. Measure by running fixtures through a pure function; Builder owns implementation and review.

## Limits
N=1 recorded case; rules are design proposals, not shown to fix deadlocks in practice. The existing deadlock-fix proposal may already cover V1; compare before adopting.
