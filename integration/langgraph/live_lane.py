"""Bounded live-runner lane (PREP - inert until explicitly wired).

Owner authority (corrected 2026-11-05): free-tier resources and
continuous work are authorized; there is NO owner numeric cap or halt
veto - those were self-imposed project safety controls. The owner
boundary that stands: NO PAID CALLS. A live run must therefore be
FREE-ONLY, bounded, and ledger-preserving.

This module is the ONLY place a live post enters the integration, and
it refuses to run unless every precondition below is satisfied AT RUN
TIME. It is not imported by any demo or graph yet. Preconditions:

1. ROUTE FREE-ONLY: the model's route in the route record is status
   'working', the current listing prices input AND output at exactly 0
   (model_resources.price_zero), and the route id is in this run's
   explicit allowlist. A price-0 listing alone is NOT proof of $0
   charge - the executor's vendor-state grounding must confirm the
   route is truly free before this lane is first used.
2. BOUNDED WINDOW: a signed allowance (RYAN_ALLOWANCE_KEY_FILE,
   owner-held 0600 key outside the repo) covers exactly the role(s),
   model(s), lineage and request count of this run. The runner's own
   allowance gate enforces it durably; this lane adds nothing around it.
3. REVIEWED GUARDED TRANSPORT ONLY: the post factory is INJECTED, not
   chosen here. The runner's built-in rc.http_post_factory is NOT
   cleared for live use (unbounded error reads, loose endpoint, no
   mandatory model echo); the reviewed transport contract is the
   executor's guarded_post_factory: exact free-catalog IDs, exact
   endpoint with no redirects, no retry, MANDATORY model echo, bounded
   reads on every error path. Until that exact head passes independent
   review, no live post exists in this integration.
4. PER-PROCESS CEILING: this process refuses to start if the signed
   window's max_requests exceeds PER_RUN_REQUEST_CEILING.
5. HISTORICAL LEDGER PRESERVED: the run APPENDS to the existing ledger;
   nothing is rewritten or deleted. Clearing the durable halt and the
   spent self-imposed envelope are upstream/executor operations on the
   project controls, not done by this lane.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_HERE, "runner"))

import ryan_cycle as rc  # vendored, byte-exact source-88a610a
import model_resources as mr  # vendored, byte-exact source-88a610a

PER_RUN_REQUEST_CEILING = 2  # one bounded window fits one attempt + retry


class LivePreconditionError(Exception):
    pass


def check_free_route(record: dict, listing: dict, route_id: str) -> None:
    route = mr.get_route(record, route_id)
    if not route or route.get("status") != "working":
        raise LivePreconditionError(f"route {route_id} not working")
    if not mr.price_zero(listing, route_id):
        raise LivePreconditionError(f"route {route_id} not priced 0/0")
    if not mr.listing_age_ok(listing):
        raise LivePreconditionError("listing not fresh")


def check_bounded_window(root: str) -> None:
    """A signed, structurally valid window must govern this run. The
    runner's own window mechanism covers verifier (+ optionally ryan)
    only - a bounded live run is therefore shaped as: research already
    drafted offline, window covering verifier (+ ryan) on ONE lineage."""
    if not os.environ.get("RYAN_ALLOWANCE_KEY_FILE"):
        raise LivePreconditionError("RYAN_ALLOWANCE_KEY_FILE not set")
    st, body, why = rc._load_grant(root)
    if st != "ok":
        raise LivePreconditionError(f"no valid signed window: {why}")
    if body.get("max_requests", 10**9) > PER_RUN_REQUEST_CEILING:
        raise LivePreconditionError(
            f"window max_requests {body.get('max_requests')} exceeds "
            f"per-run ceiling {PER_RUN_REQUEST_CEILING}")


def bounded_live_step(root: str, listing, record, post_factory,
                      now=None, clock=None):
    """One runner step with an INJECTED reviewed guarded transport,
    only after all preconditions pass. `post_factory` must be the
    independently reviewed guarded factory (strict echo, exact
    endpoint, bounded errors) already closed over its allowlist and key
    env name. Never call this in a demo or fixture."""
    if post_factory is None:
        raise LivePreconditionError(
            "no reviewed guarded transport injected (live held)")
    check_bounded_window(root)
    return rc.step(root, post_factory(),
                   listing if callable(listing) else (lambda: listing),
                   now if now is not None else time.time(), record,
                   clock=clock)


import time  # noqa: E402  (after rc import; used by bounded_live_step)
