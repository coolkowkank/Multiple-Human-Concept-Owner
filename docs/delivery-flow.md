# The delivery team

The Coordinator manages all delivery roles. Proposed seats, each labeled with its model and human owner:

- **Coordinator** (personal assistant, main delivery job) - reads the agreed brief, assigns work, runs the one queue, relays to the humans. It relays; it does not decide the concept.
- **Personal robots** (personal assistant) - one per human, part of the delivery team: each captures its owner's discussion into the brief and can clarify directly with the Coordinator, without ever overriding the brief.
- **Builder** (personal assistant, main delivery job) - the sole writer: implements one batch per written turn token, so every change is traceable and no two AIs write at once.
- **Reviewer** (personal assistant, separate main delivery assignee) - checks every routine batch and returns written findings; escalates the consequential ones to QC.
- **Records** (personal assistant, mostly-idle secondary job only) - archives hand-offs, findings, verdicts and the concept change history, so any human can reconstruct what happened.
- **Architect** (high-impact reasoning seat) - turns the agreed brief into the architecture, specs and acceptance criteria every batch is built and judged against.
- **Independent QC** (high-impact reasoning seat) - verdict on the consequential calls: milestones, high-risk cross-cutting changes, material architecture or spec changes, and unresolved critical findings. A fail stands - the Coordinator cannot override it.
- **Expandable**: add delivery robots as the project needs, each assigned a role, a model and a human owner.

## Why the high-impact seats sit where they sit

Scarce, expensive reasoning goes where it changes the outcome: the architecture that shapes every batch, and judgment on the consequential calls. Those seats are called in rather than always on, so routine throughput never waits on them. Repetitive implementation, rote checks and record-keeping stay with the personal assistants.

## Handoff caveat

Autonomous sessions in the high-impact seats need a session-to-repo handoff - how a session receives a batch and returns work. Confirm that mechanism and each session's actual access before the team relies on it. This blueprint does not set it up or verify it.
