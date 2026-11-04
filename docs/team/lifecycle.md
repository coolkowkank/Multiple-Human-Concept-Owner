# Role lifecycle

How members join, pause, and return. The registry (registry.md) records
state; this file records the rules.

## Activation
1. Coordinator identifies real work that justifies the role (no
   headcount for its own sake) and proposes it.
2. Authority check: if the role needs anything beyond existing
   permissions and free-tier caps - spend, new credentials, access
   changes, merges - the owner's explicit decision is required first.
   Within existing permissions and caps, the coordinator assigns
   directly under the owner's standing dynamic-team approval
   (2026-11-04).
3. Qualification: a bounded, free-only trial with a declared cap,
   recorded in the repo (model, provider, calls, verdict). A listed
   model is not an available model; availability is proven by a real
   free-tier call.
4. Registry row moves to `active` with evidence; blueprint is current
   before the first real task.

## Retirement (going inactive)
1. The blueprint is updated FIRST: completed work, open issues, and
   what a replacement needs to pick up.
2. Open handoffs are marked historical.
3. The registry row loses its `*`. The instance ID is never reused.

## Reactivation ("resurrect")
1. Start from the blueprint: it is the handoff document.
2. Re-check fit for the actual work and re-check permissions. Access
   and credentials are never restored automatically; whatever authority
   the role needs is obtained fresh under the rules at that time.
3. If the provider, model or free-tier terms changed since the
   blueprint was written, the qualification trial is re-run before
   real work.

## Parallel instances
Same role, multiple instances: only for independent work items with
disjoint owned files, no shared branch, no dependency between the
items, and no shared provider-quota collision (or an explicit
coordinator serialization plan when the quota is shared, e.g. the
org-level Groq free tier). Each instance gets its own row, its own
instance number, and where it spends provider budget, its own durable
ledger with a declared cap.
