"""Bounded live-runner driver (compiled-LangGraph shape; PREP until go).

Owner authority (per main's recovered owner originals, 2026-11-05):
free-tier continuous work is authorized; PAID CALLS ARE NOT. The
runner's historical envelope/halt were self-imposed project controls,
not an owner veto.

Integrated accepted chain (2026-11-05): upstream tip
3b09eea8ccacebc4e5d3131e4b58fa9cf58a0fe2, independently reviewed and
accepted by main, vendored BYTE-EXACT into runner/:
  - ryan_cycle.py       md5 ecc7bbb21c62b9aceccf95ba41deec5b
  - model_resources.py  md5 148d1e609f466332ebb1d6ce85ccf40d
  - requesty_transport.py md5 701321b3a753b82365575b0b40f2acfd
  - make_allowance.py   md5 8587d6e2d5ffd5b86446baa68a7a89ab
Run config: run-config/assignments.json carries the exact assignment
content of the local assignment head 49f189dd (main's delta: verifier
mistral/leanstral-1-5, researcher Ultra unchanged, ryan unchanged and
NOT authorized for this run - ONE verifier-only window; the
builder/runner binding prevents a second window, by design). The web
editor normalized the final newline; the JSON content is identical.

DESIGN RULE (reviewer, 2026-11-05): the live boundary is owned by the
ACCEPTED UPSTREAM chain - the guarded transport (exact free IDs, fixed
endpoint, mandatory model echo, bounded reads on every error path, no
retry, max-3 per factory, explicit cost-zero accounting: a missing or
invalid cost signal is cost-unverified, never an ok) and the runner's
own pre-I/O snapshot gate under store.lock (halt/stop state, own
reserve line, operator assignment, rendered-input snapshot, grant,
price-0, listing freshness; checked-then-send residual is documented).
This module deliberately does NOT duplicate those defenses.

What this driver owns (wiring + run-shape only):
  1. EXPLICIT authoritative root path - no cwd default, must be a
     directory with a readable queue.json.
  2. PREFLIGHT before any reserve: key env present, assignments parse
     with decided_by == the runner's OPERATOR constant, every run model
     in this run's allowlist (a subset of the transport's FREE_IDS with
     an evidenced listing ceiling), listing fresh at the actual clock,
     routes working and price-0. A preflight failure raises BEFORE the
     ledger is touched (no reserve, no result, no halt line).
  3. REVIEWED-TRANSPORT IDENTITY: the post callable is constructed
     ONLY from the vendored, md5-pinned requesty_transport module
     (guarded_post_factory). Callers cannot inject a factory into the
     live path. The md5 pins are verified at load; a tampered vendored
     file refuses.
  4. SETTLE NORMALIZATION: the transport raises (Halt) only for local
     pre-I/O refusals, but the runner reserves BEFORE it calls post, so
     ANY exception escaping rc.step could leave a reserve without a
     result. After an unexpected exception the driver settles every
     orphaned reserve as outcome unknown via the runner's own settle()
     (which appends the halt), then reports paused. End-to-end tested:
     key-missing/config-fail leave the ledger byte-identical; a thrown
     post after the reserve settles exactly one unknown result + halt.
  5. ONE bounded step through the ACTUAL compiled LangGraph
     (build_live_runner_graph). No checkpointer: no resume claim.

Execution ownership (main, 2026-11-05): the EXECUTOR runs this driver
against its own authoritative root/ledger after independent review of
this exact integrated head and main's go. This lane never makes a
provider call and never executes a cloned ledger. The executor holds
the vault key (env REQUESTY_API_KEY) and the allowance bookkeeping key
(RYAN_ALLOWANCE_KEY_FILE); no secret passes through this repo or chat.

Known accepted limits (document, don't redesign): builder bookkeeping
is offline/quiescent and its allowance.json write is NOT crash-atomic;
socket timeout only, no strict total deadline; listing age is checked,
not refetched; checked-then-send residual remains.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.realpath(__file__))
_RUNNER = os.path.join(_HERE, "runner")
sys.path.insert(0, _RUNNER)

from typing import Annotated, TypedDict
import operator as op
from langgraph.graph import END, START, StateGraph

# md5 pins of the accepted, independently reviewed vendored files
# (upstream tip 3b09eea). Verified before ANY runner/transport use.
VENDORED_MD5 = {
    "ryan_cycle.py": "ecc7bbb21c62b9aceccf95ba41deec5b",
    "model_resources.py": "148d1e609f466332ebb1d6ce85ccf40d",
    "requesty_transport.py": "701321b3a753b82365575b0b40f2acfd",
    "make_allowance.py": "8587d6e2d5ffd5b86446baa68a7a89ab",
}


class LivePreconditionError(Exception):
    pass


def _verify_vendored():
    for name, want in VENDORED_MD5.items():
        p = os.path.join(_RUNNER, name)
        try:
            with open(p, "rb") as f:
                got = hashlib.md5(f.read()).hexdigest()
        except OSError:
            raise LivePreconditionError("vendored file missing: " + name)
        if got != want:
            raise LivePreconditionError(
                "vendored %s md5 %s != accepted pin %s" % (name, got, want))


def _load_runner():
    """Import the vendored runner modules ONLY after the md5 pins pass.
    Returns (ryan_cycle, model_resources, requesty_transport)."""
    _verify_vendored()
    import ryan_cycle as rc
    import model_resources as mr
    import requesty_transport as rt
    for mod, name in ((rc, "ryan_cycle.py"), (mr, "model_resources.py"),
                      (rt, "requesty_transport.py")):
        if os.path.dirname(os.path.realpath(mod.__file__)) != _RUNNER:
            raise LivePreconditionError(
                "%s did not load from the vendored runner dir" % name)
    return rc, mr, rt


def check_free_route(mr, record: dict, listing: dict, route_id: str,
                     clock) -> None:
    """Setup-time sanity: route working, listing prices 0/0, listing
    fresh at the actual clock. NOT the live gate - the runner's own
    pre-I/O boundary re-checks all of this under the store lock."""
    route = mr.get_route(record, route_id)
    if not route or route.get("status") != "working":
        raise LivePreconditionError("route %s not working" % route_id)
    if not mr.price_zero(listing, route_id):
        raise LivePreconditionError("route %s not priced 0/0" % route_id)


def preflight(root, record, listing_doc, allowlist, *, key_env, clock):
    """Everything checkable BEFORE a reserve exists. Raises
    LivePreconditionError; the ledger is never touched on failure."""
    rc, mr, rt = _load_runner()
    if not root or not isinstance(root, str):
        raise LivePreconditionError("explicit authoritative root required")
    if not os.path.isdir(root):
        raise LivePreconditionError("root is not a directory: " + root)
    if not os.path.isfile(os.path.join(root, "queue.json")):
        raise LivePreconditionError("root has no queue.json: " + root)
    if not os.environ.get(key_env):
        raise LivePreconditionError("missing key env " + key_env)
    allowlist = frozenset(allowlist)
    if (not allowlist or not allowlist <= rt.FREE_IDS
            or not allowlist <= set(rt.LISTING_MAX_OUT)):
        raise LivePreconditionError(
            "allowlist must be a non-empty subset of the free ids with "
            "an evidenced listing ceiling")
    try:
        with open(os.path.join(root, "assignments.json")) as f:
            a = json.load(f)
    except (OSError, ValueError) as e:
        raise LivePreconditionError("assignments.json unreadable: %s"
                                    % type(e).__name__)
    models = a.get("models") if isinstance(a, dict) else None
    if not isinstance(models, dict) or not models:
        raise LivePreconditionError("assignments.json has no models map")
    if a.get("decided_by") != rc.OPERATOR:
        raise LivePreconditionError("assignment authority is not the "
                                    "operator constant")
    for role, model in models.items():
        if model not in allowlist:
            raise LivePreconditionError(
                "%s model %s not in this run's allowlist" % (role, model))
        check_free_route(mr, record, listing_doc, model, clock)
    if not rc.listing_fresh(listing_doc, clock()):
        raise LivePreconditionError("listing not fresh at the actual clock")
    return rc, mr, rt


def _settle_orphaned_reserves(rc, root, exc, now):
    """After an unexpected exception from rc.step: every reserve with no
    result line is settled as outcome unknown via the runner's own
    settle() (which appends the halt and raises Halt - caught here).
    Returns the settled rids. Ledger accounting stays exact: a reserve
    never dangles."""
    store = rc.Store(root)
    settled = []
    with store.lock():
        led = store.ledger()
        results = {e.get("rid") for e in led if e.get("phase") == "result"}
        orphans = [e for e in led
                   if e.get("phase") == "reserved"
                   and e.get("rid") not in results]
        for o in orphans:
            res = {"kind": "unknown", "usage": None, "content": "",
                   "diag": rc.clean_diag({
                       "stage": "driver-post-exception",
                       "class": "unexpected",
                       "error_type": type(exc).__name__})}
            try:
                rc.settle(store, o["rid"], o["qid"], o["role"],
                          o["model"], res, now)
            except rc.Halt:
                pass    # settle() appends the halt line itself
            settled.append(o["rid"])
    return settled


def run_bounded_step(root, listing, record, *, allowlist,
                     key_env="REQUESTY_API_KEY", now=None, clock=None,
                     opener=None, before_io=None):
    """ONE bounded runner step through the reviewed transport.

    Returns the rc.step outcome dict, or a paused dict after settling
    an unexpected exception. Raises LivePreconditionError on preflight
    failure (ledger untouched). `opener` and `before_io` are test seams
    only (offline fake transport I/O; post-reserve mutation hook, same
    contract as the runner's own before_io) - production uses the
    defaults."""
    clock = clock or time.time
    now = now if now is not None else clock()
    listing_doc = listing() if callable(listing) else listing
    rc, mr, rt = preflight(root, record, listing_doc, allowlist,
                           key_env=key_env, clock=clock)
    post = rt.guarded_post_factory(allowlist, env=key_env, opener=opener)
    list_models = listing if callable(listing) else (lambda: listing)
    try:
        return rc.step(root, post, list_models, now, record, clock=clock,
                       before_io=before_io)
    except Exception as e:
        settled = _settle_orphaned_reserves(rc, root, e, now)
        return {"action": "paused", "reason": "%s: %s"
                % (type(e).__name__, str(e)[:200]),
                "settled_unknown": settled, "calls": 0}


def build_live_runner_graph(root, listing, record, *, allowlist,
                            key_env="REQUESTY_API_KEY", now=None,
                            clock=None, opener=None, before_io=None):
    """The required run shape: ONE bounded live runner step driven
    through the ACTUAL compiled LangGraph, not a direct rc.step call.
    No checkpointer: no resume claim. All boundary guarantees come from
    the accepted runner + reviewed transport; this graph adds nothing
    but orchestration. Inert until independent review of this exact
    integrated head and main's go."""
    class LiveRunnerState(TypedDict):
        results: Annotated[list, op.add]

    def node(state: LiveRunnerState) -> dict:
        out = run_bounded_step(root, listing, record,
                               allowlist=allowlist, key_env=key_env,
                               now=now, clock=clock, opener=opener,
                               before_io=before_io)
        return {"results": [out]}

    g = StateGraph(LiveRunnerState)
    g.add_node("bounded_live_step", node)
    g.add_edge(START, "bounded_live_step")
    g.add_edge("bounded_live_step", END)
    return g.compile()
