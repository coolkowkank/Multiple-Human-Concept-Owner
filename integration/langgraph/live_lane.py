"""Bounded live-runner driver (compiled-LangGraph shape; PREP until go).

PATCHED-VENDOR NOTE (2026-11-05): ryan_cycle.py and make_allowance.py are
no longer byte-exact copies of upstream eef61c6. The only delta is the
successor-window shape (a successor is [verifier] or [verifier, ryan],
never ryan-only; novelty rule stays verifier-only) - see OPERATOR_GUIDE
"Patched vendor delta". The md5 pins below are the patched files. The
md5 values in the paragraph that follows describe the earlier run.

Provenance note: a project record, not a grant. Free-only operation is
a project working rule from the operator's relay of owner instructions
(not authenticated by this repo). The runner's historical envelope/halt
are self-imposed bookkeeping controls. Paid calls are out of scope.

Integrated accepted chain (2026-11-05): upstream tip
eef61c620308dc9e086a5bc6fe08152607824e1f (append-only window
succession: validated actual prior bind, same lineage + claim-set
fingerprint, strictly verifier-only max_requests 1, shared
runtime/builder validator; recorded repository history, not an approval),
vendored into runner/ (md5 values of that earlier state; the current pins
are in VENDORED_MD5 below):
  - ryan_cycle.py       md5 ae08fb3c6dae3744e4a505ebc2428d8c
  - model_resources.py  md5 148d1e609f466332ebb1d6ce85ccf40d
  - requesty_transport.py md5 974fbbfdcffd7b648d4552a063495fea
  - make_allowance.py   md5 4f3d08fe51e428089c6f62517820758c
Run config: run-config/assignments.json is the SANITIZED public form
of the operator assignment (operator-selected 2026-11-05, project record): verifier
google/gemma-4-31b-it (owner-directed switch after the leanstral
route's failed first call), researcher Ultra unchanged, ryan unchanged
and NOT authorized for this run - ONE verifier-only successor window,
max_requests 1, naming the stopped prior window by id+digest. The
private original's source_ref carried internal delegation traces; the
published source_ref is reduced to user-project facts, and this file
does NOT claim byte-identity with the private original.

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
     with decided_by == the runner's OPERATOR constant, every assigned
     model in this run's allowlist (a subset of the transport's
     FREE_IDS with an evidenced listing ceiling), listing fresh at the
     actual clock, and - for the ACTUAL next_action role's model only -
     a recorded non-blocked route (an "untested" route is passed
     through AS untested: this run is its qualification, never
     relabeled "working"), non-blocked provider, price-0. Inactive
     assigned roles do not gate the step. A preflight failure raises
     BEFORE the ledger is touched (no reserve, no result, no halt).
  3. REVIEWED-TRANSPORT IDENTITY: the post callable is constructed
     ONLY from the vendored, md5-pinned requesty_transport module
     (guarded_post_factory). Callers cannot inject a factory into the
     live path. The md5 pins are verified at load; a tampered vendored
     file refuses.
  4. SETTLE NORMALIZATION: the transport raises (Halt) only for local
     pre-I/O refusals, but the runner reserves BEFORE it calls post, so
     ANY exception escaping rc.step could leave a reserve without a
     result. After an unexpected exception the driver settles ONLY this
     invocation's own newly-created reserves (pre-step reserve snapshot;
     historical reserves are never touched) as outcome unknown via the
     runner's own settle() (which appends the halt),
     then reports paused with EVIDENCE-DRIVEN accounting: the reason is
     the allowlisted exception class only (exception text can carry
     secrets/raw prompt), and calls/io_attempted come from the ledger -
     runner-settled result lines say exactly (not_sent = no I/O,
     unknown/http_* = one attempt), a driver-settled dangling reserve
     is io "unknown" counted conservatively as 1, no new reserve is 0.
     End-to-end tested: key-missing/config-fail leave the ledger
     byte-identical; a thrown post after the reserve settles exactly
     one unknown result + halt with calls 1.
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

# md5 pins of the vendored files (a tamper check, not an approval).
# Verified before ANY runner/transport use.
VENDORED_MD5 = {
    "ryan_cycle.py": "09cdaae1b857231f15fa49cf770ebaa8",
    "model_resources.py": "148d1e609f466332ebb1d6ce85ccf40d",
    "requesty_transport.py": "974fbbfdcffd7b648d4552a063495fea",
    "make_allowance.py": "e81caf38b546ee4b94f1de34dea4ac42",
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


def check_free_route(rc, mr, record: dict, listing: dict, model: str):
    """Setup-time route sanity for the ONE model the next step will call.
    Mirrors the runner's own route_gate: the route must be RECORDED
    under the exact id with a non-blocked status and a non-blocked
    provider. "untested" is a recorded human status the runner itself
    admits (rc.OK_STATUS): it is passed through AS "untested" - this
    run is that route's qualification - never relabeled "working".
    Returns the recorded status string. NOT the live gate - the
    runner's own pre-I/O boundary re-checks under the store lock."""
    rec = mr.get_route(record, model) if isinstance(record, dict) else None
    if rec is None:
        raise LivePreconditionError(
            "%s has no route record (unknown, not working)" % model)
    status = rec.get("status")
    if status not in rc.OK_STATUS:
        raise LivePreconditionError("%s recorded %s" % (model, status))
    if rec.get("provider") in (record.get("provider_blocks") or {}):
        raise LivePreconditionError("provider of %s is blocked" % model)
    if not mr.price_zero(listing, model):
        raise LivePreconditionError("%s not priced 0/0" % model)
    return status


def preflight(root, record, listing_doc, allowlist, *, key_env, clock):
    """Everything checkable BEFORE a reserve exists. Raises
    LivePreconditionError; the ledger is never touched on failure.
    Route checks apply to the ACTUAL next_action role's model only:
    assigned models for inactive roles are allowlist-checked (a paid or
    unceilinged id may not sit in assignments) but their route status
    does not gate this step. Returns (rc, mr, rt, run_info)."""
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
    if not rc.listing_fresh(listing_doc, clock()):
        raise LivePreconditionError("listing not fresh at the actual clock")
    # the actual next step: same selection the runner uses (pick +
    # next_action), so the route check targets the model that will
    # really be called - not inactive assigned roles.
    queue = rc.Store(root).queue()
    q = rc.pick(queue)
    if q is None:
        raise LivePreconditionError("no actionable queue item")
    role = rc.next_action(q)
    if q.get("kind") == "verify":
        cur = rc.load_eva_assignment(root)
        if not isinstance(cur, dict) or cur.get("decided_by") != rc.OPERATOR:
            raise LivePreconditionError("Eva assignment missing or not "
                                        "operator-made")
        model = (cur.get("models") or {}).get("eva")
    else:
        model = models.get(role)
    if not model:
        raise LivePreconditionError("no assigned model for role %s" % role)
    status = check_free_route(rc, mr, record, listing_doc, model)
    run_info = {"qid": q["id"], "role": role, "model": model,
                "route_status": status,
                "qualification": status == "untested"}
    return rc, mr, rt, run_info


def _settle_orphaned_reserves(rc, root, exc, now, pre_rids):
    """After an unexpected exception from rc.step: settle ONLY reserves
    created by THIS invocation (absent from the pre-step snapshot) that
    have no result line. Historical reserves are never touched -
    mutating unrelated history is worse than leaving it for a human.
    SCOPE: the snapshot diff cannot distinguish this invocation's
    reserve from a CONCURRENTLY created one, so this guarantee holds
    only under the accepted sole-writer, externally-quiescent
    precondition (design A: one writer from preflight through
    settlement, no concurrent run). NOT a general-concurrency claim.
    Settlement is outcome unknown via the runner's own settle() (which
    appends the halt and raises Halt - caught here). Returns the
    settled rids."""
    store = rc.Store(root)
    settled = []
    with store.lock():
        led = store.ledger()
        results = {e.get("rid") for e in led if e.get("phase") == "result"}
        orphans = [e for e in led
                   if e.get("phase") == "reserved"
                   and e.get("rid") not in pre_rids
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

    Returns the rc.step outcome dict enriched with the route status,
    or a paused dict after an unexpected exception. Raises
    LivePreconditionError on preflight failure (ledger untouched).
    `opener` and `before_io` are test seams only (offline fake
    transport I/O; post-reserve mutation hook, same contract as the
    runner's own before_io) - production uses the defaults.

    Paused-path accounting is EVIDENCE-DRIVEN, never a blanket number:
    the reason is the allowlisted exception CLASS ONLY (exception text
    can carry secrets or raw prompt); the post-step ledger decides
    calls/io - a runner-settled result line says exactly what happened
    (not_sent = no I/O; unknown/http_* = one attempt), a reserve the
    runner left dangling (settled here as unknown) means I/O state is
    unknowable and is reported as io_attempted "unknown" with calls 1
    conservatively, and no new reserve means nothing was attempted."""
    clock = clock or time.time
    now = now if now is not None else clock()
    listing_doc = listing() if callable(listing) else listing
    rc, mr, rt, run_info = preflight(root, record, listing_doc, allowlist,
                                     key_env=key_env, clock=clock)
    post = rt.guarded_post_factory(allowlist, env=key_env, opener=opener)
    list_models = listing if callable(listing) else (lambda: listing)
    pre_rids = {e.get("rid") for e in rc.Store(root).ledger()
                if e.get("phase") == "reserved"}
    try:
        out = dict(rc.step(root, post, list_models, now, record,
                           clock=clock, before_io=before_io))
        out["route_status"] = run_info["route_status"]
        if run_info["qualification"]:
            out["qualification"] = "untested-route-first-call"
        return out
    except Exception as e:
        settled = _settle_orphaned_reserves(rc, root, e, now, pre_rids)
        led = rc.Store(root).ledger()
        new_res = [e for e in led if e.get("phase") == "reserved"
                   and e.get("rid") not in pre_rids]
        results = {e.get("rid"): e for e in led
                   if e.get("phase") == "result"}
        outcome, io_attempted, calls = None, False, 0
        for r in new_res:
            res = results.get(r.get("rid"))
            if res is not None and r.get("rid") not in settled:
                # the runner itself settled this reserve: exact evidence
                outcome = res.get("outcome")
                if outcome != "not_sent":
                    io_attempted, calls = True, 1
        if settled:
            # reserve consumed, exception left I/O state unknowable
            io_attempted, calls = "unknown", 1
        return {"action": "paused", "reason": type(e).__name__,
                "calls": calls, "io_attempted": io_attempted,
                "reserve_consumed": [r.get("rid") for r in new_res],
                "ledger_outcome": outcome,
                "settled_unknown": settled,
                "route_status": run_info["route_status"]}


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
