"""Runner-backed LangGraph lane: drives the ACCEPTED Ryan runner
(tools/ryan_cycle.py, vendored byte-exact at source-88a610a under
runner/) from inside the LangGraph orchestration.

The provider-call injection point (`post`) is explicit and REFUSING as
shipped: it records the attempt and returns an 'unknown' transport
outcome WITHOUT any network access. The runner's own accounting then
consumes the reserve and halts - so even if a gate mistakenly passed,
no call can escape this lane and the attempt is visibly consumed.

The runner's accepted guard chain fires BEFORE that point: durable
provider halt, lifetime qualification envelope, per-question/lineage
caps, route/free gates, the signed allowance window with durable
lineage+claim binding (01a495f), and the verified_rev revision binding
(88a610a). A LIVE post is not provided anywhere in this integration:
wiring one needs halt clearance, a signed allowance grant with an
owner-held key file, and a current route record - separate owner
decisions, none taken.
"""
from __future__ import annotations

import os
import sys
import time

_HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_HERE, "runner"))

import ryan_cycle as rc  # vendored, byte-exact source-88a610a
from typing import Annotated, TypedDict
import operator as op
from langgraph.graph import END, START, StateGraph


def refusing_post(attempts: list):
    """The only `post` this lane ships: records the attempt, returns an
    'unknown' outcome (which the runner's settle() consumes as a spent
    reserve and halts on). NO network, no key, no provider."""
    def post(model, system, prompt, mt, effort=None):
        attempts.append({"model": model, "ts": time.time()})
        return {"kind": "unknown", "code": 0,
                "content": "no call made: integration refusing post "
                           "(a live post needs halt clearance + signed "
                           "allowance grant + current route record)",
                "usage": {}}
    return post


def runner_step(root: str, listing, record, now=None, clock=None):
    """One gated runner step. Returns {step, call_attempts, halted}."""
    attempts = []
    halted = None
    try:
        result = rc.step(root, refusing_post(attempts),
                         listing if callable(listing) else (lambda: listing),
                         now if now is not None else time.time(), record,
                         clock=clock)
    except rc.Halt as exc:
        result, halted = None, str(exc)
    return {"step": result, "call_attempts": attempts, "halted": halted}


def build_runner_graph(root, listing, record, now=None, clock=None):
    """A minimal LangGraph graph wrapping the gated runner step, for
    orchestration alongside the seat lanes."""
    class RunnerState(TypedDict):
        results: Annotated[list, op.add]

    def node(state: RunnerState) -> dict:
        return {"results": [runner_step(root, listing, record, now, clock)]}

    g = StateGraph(RunnerState)
    g.add_node("runner_step", node)
    g.add_edge(START, "runner_step")
    g.add_edge("runner_step", END)
    return g.compile()
