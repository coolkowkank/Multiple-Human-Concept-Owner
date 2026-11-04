# Blueprint: <role name>

> Reusable role definition. Update this file when the role's work
> materially changes, and ALWAYS before the role goes inactive - it is
> the handoff document a later instance starts from.

- **Status:** vacant | active | inactive (see ../registry.md)
- **Purpose:** one paragraph: what this role exists to do.
- **Current model / provider:** name, route, free-tier evidence, or
  "unassigned". A listed model is not an available model; only a real
  bounded trial qualifies.
- **Owns (scope):** files/areas this role may change. Parallel
  instances of the same role must be disjoint here, and must not share
  a branch, a dependency, or an unmanaged provider quota.
- **Inputs / outputs:** what the role consumes and what it must produce
  (artifacts, evidence format).
- **Evidence standard:** what "done" means and what proof is required
  (pins, test output, verdicts).
- **Completed work:** dated, pinned highlights.
- **Open issues:** what is broken, blocked or unverified right now.
- **Handoff notes:** what a replacement or reactivation needs to know
  first.
- **Retirement conditions:** when this role should go inactive.
- **Reactivation checklist:** fit re-check; permission re-check (no
  automatic credentials); qualification re-trial if provider, model or
  terms changed.
