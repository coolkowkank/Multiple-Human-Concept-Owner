"""Bounded live-runner wiring (PREP - inert until explicitly wired).

Owner authority (per main's recovered owner originals, 2026-11-05):
free-tier continuous work is authorized; PAID CALLS ARE NOT. The
runner's historical envelope/halt were self-imposed project controls,
not an owner veto.

DESIGN RULE (reviewer, 2026-11-05): the live boundary is owned by the
ACCEPTED UPSTREAM chain - the corrected guarded transport (exact free
IDs, fixed endpoint, mandatory model echo, bounded reads on every
error path, no retry, max-3, explicit cost-zero accounting) and the
runner's own pre-I/O snapshot gate under store.lock (checked-then-send,
completion checks). This module deliberately does NOT duplicate those
defenses: an earlier version of this file carried a pre-I/O recheck
wrapper, an in-process counter and a window re-check, all of which
review showed to be weaker duplicates (historic-halt overreach, missed
deleted-grant revalidation, Halt-inside-post leaving an unsettled
reserve, counter resetting per step, setup-time route check not
snapshot-bound). They were removed, not fixed - the durable bound is
the signed allowance window and its ledger debits, enforced by the
runner, not anything in-process here.

What remains here is WIRING ONLY:
- the reviewed transport is INJECTED as a factory and passed ONLY into
  rc.step (no direct-call surface exists in this module);
- the factory must carry the reviewed-transport identity attribute
  (name provisional until the accepted chain defines it); and
- a setup-time route sanity check (working, price 0/0, fresh listing)
  against the run's explicit free-ID allowlist. The runner's own gates
  re-check route and price at step time; this catches config mistakes
  earlier, nothing more.

No live step runs until: the corrected upstream chain is independently
accepted, this exact integrated head is independently reviewed, and
main says go. None of those has happened.
"""
from __future__ import annotations

import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_HERE, "runner"))

import ryan_cycle as rc  # vendored, byte-exact accepted chain
import model_resources as mr  # vendored, byte-exact accepted chain

REVIEWED_TRANSPORT_ATTR = "REVIEWED_TRANSPORT_ID"  # provisional name


class LivePreconditionError(Exception):
    pass


def check_free_route(record: dict, listing: dict, route_id: str) -> None:
    """Setup-time sanity: route working, listing prices 0/0, listing
    fresh. NOT the live gate - the runner re-checks at step time."""
    route = mr.get_route(record, route_id)
    if not route or route.get("status") != "working":
        raise LivePreconditionError(f"route {route_id} not working")
    if not mr.price_zero(listing, route_id):
        raise LivePreconditionError(f"route {route_id} not priced 0/0")
    if not mr.listing_age_ok(listing):
        raise LivePreconditionError("listing not fresh")


def check_run_models(root: str, record: dict, listing: dict,
                     allowlist) -> None:
    """Every model in the committed assignments.json must be in this
    run's explicit free-ID allowlist and pass the route sanity check."""
    with open(os.path.join(root, "assignments.json")) as f:
        a = json.load(f)
    models = a.get("models") if isinstance(a, dict) else None
    if not isinstance(models, dict) or not models:
        raise LivePreconditionError("assignments.json unreadable")
    for role, model in models.items():
        if model not in allowlist:
            raise LivePreconditionError(
                f"{role} model {model} not in this run's allowlist")
        check_free_route(record, listing, model)


def bounded_live_step(root: str, listing, record, post_factory, *,
                      allowlist, transport_id, now=None, clock=None):
    """One runner step through the injected reviewed transport.

    Boundary guarantees (halt durability, allowance window debits,
    pre-I/O snapshot gate, completion checks, reserve/result
    accounting) come from the ACCEPTED RUNNER and the reviewed
    transport - not from this function. This function only: refuses a
    factory without the reviewed identity, refuses run models outside
    the allowlist, and hands the factory to rc.step. Never call this
    in a demo or fixture."""
    if not transport_id or getattr(post_factory,
                                   REVIEWED_TRANSPORT_ATTR,
                                   None) != transport_id:
        raise LivePreconditionError(
            "injected factory is not the expected reviewed transport")
    listing_doc = listing() if callable(listing) else listing
    check_run_models(root, record, listing_doc, allowlist)
    return rc.step(root, post_factory(),
                   listing if callable(listing) else (lambda: listing),
                   now if now is not None else time.time(), record,
                   clock=clock)
