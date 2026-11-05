# Live run 3: Builder, Reviewer and QC seats (model-backed), 2026-11-05

Code: branch live/langgraph-http-seat, accepted head 1e013ac0b967135d60ee236f4b08c4a0aa808010 (the fenced adapter plus the verify sandbox). Record only; no code change.

## What ran
- One graph pass, three seat turns, in the existing scratch lane (turn builder, instruction_seq 2 on entry). The coordinator seat was not called again. Records stayed scripted and did not run.
- Seats builder, reviewer and qc each used the fenced HTTP adapter on nvidia/nemotron-3-ultra-550b-a55b (requested model; the reported model is not captured). Epochs b1 (budget 2), r1 (budget 2), q1 (budget 1).
- One request per seat, no retries, no halt. Reported usage (provider-reported, cost 0 each, not billing proof):
  - builder: prompt 792, completion 226, total 1018
  - reviewer: prompt 871, completion 458, total 1329
  - qc: prompt 944, completion 281, total 1225
- Lifetime reserves used after this run: 5 of 8 (2 coordinator + 3 here). A new epoch is a separate log name, not new budget.
- Price listing re-fetched just before the run: input and output price 0.

## Execution fence in force
- LG_VERIFY_SANDBOX=1 was set in the launch environment, and the run printed "ready = True" (flag set and shim executable). Model-backed seats refuse to run otherwise.
- Verify ran each model-written test through the bwrap shim: no network, no home, no host files, read-only repo mount, 20s CPU, 60s wall.
- The key was read from a transient file after the process started, set in-process only, and the file was deleted. It was not exported.
- Limits: same unprivileged user, bwrap isolation, not a hardened boundary.

## Result
- The Builder turn wrote src/app.py (add(a, b)) and tests/test_app.py. The runtime's verify step ran `python3 tests/test_app.py` in the sandbox: exit 0, output "ok". The reviewer and QC turns re-ran it, also exit 0, and wrote a review and a verdict (both acceptance criteria PASS).
- Each turn was validated and committed by the project runtime. The code is in live_output/add_lib/ (two small files, copied unchanged from the lane).
- Honest labels: instruction-guided (the brief spelled out the reply rules and the test shape), same model on all three seats so review and QC are not independent, and the task is tiny. This shows the model-backed team handing work builder to reviewer to qc under the runtime's guards, not an unaided or independently qualified team. Records and coordinator close-out did not run, so the team is not DONE.
- Raw prompts, model replies, review text and the usage logs are not published.
