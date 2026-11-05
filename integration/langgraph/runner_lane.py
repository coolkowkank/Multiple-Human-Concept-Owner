"""Runner-backed LangGraph lane: drives the ACCEPTED Ryan runner
(tools/ryan_cycle.py, vendored from source-88a610a with ONE documented
successor-shape patch, see OPERATOR_GUIDE 'Patched vendor delta', under
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

import ryan_cycle as rc  # vendored source-88a610a + documented patch
import fenced_http as fh
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


class FencedRunner:
    """The runner roles' ONLY live request path: the shared fenced
    adapter (reserve-before-I/O, hash chain, shared halt, lifetime cap
    HTTP_LIFETIME_CAP in ~/.lg-http-usage). It never touches
    ryan_cycle.http_post_factory. Nothing in this repo builds one against
    a real provider.

    Two steps, matching the runner's own order:
    1. gate() runs as the runner's before_io seam, right after the
       runner reserve. It reads the reserve line the runner just wrote
       (model, role), checks the allowlist and makes the SHARED reserve
       (adapter.reserve()). If anything refuses, no shared reserve exists
       and no request can follow: gate() writes a runner halt (never
       clears one), so the runner's own pre-I/O boundary records a
       factual `not_sent` result. The runner reserve stays consumed.
    2. post() executes ONLY against that reservation (single use). It
       can be refused only by the durable exec claim (a halt written after the
       reserve, key gone, reservation already claimed): then no request is
       made, post raises Halt and the runner keeps a reserve with no
       result for an operator to reconcile. It cannot make a second request.
       Without a reservation (the seam did not run, wrong model or
       parameters) it makes NO request and raises Halt; the runner ledger
       then keeps a reserve with no result, which needs an operator to
       reconcile (fail closed, not a not_sent claim).
    gate() binds to the LAST runner ledger line: single process per runner
    root only (documented limit).
    An exception after the exec claim is an unknown outcome. A crash
    between gate() and post() leaves a shared reserve with no exec line:
    consumed, the fence never started a request. If the runner's boundary refuses after the
    shared reserve (assignment/grant changed), the shared reserve is
    consumed without a request."""

    def __init__(self, root, attempts, base_url, api_key_env, epoch,
                 opener=None, timeout=120, allowed_models=None):
        self.root, self.attempts = root, attempts
        self.args = (base_url, api_key_env, epoch, opener, timeout)
        self.allowed = fh_allowed() if allowed_models is None \
            else allowed_models
        self.token = self.adapter = self.params = None

    def _halt(self, why):
        st = rc.Store(self.root)
        with st.lock():
            st.append({"phase": "halt", "ts": rc.iso(time.time()),
                       "reason": "shared fence refused before I/O: " + why})

    def gate(self):
        self.token = self.adapter = None
        led = rc.Store(self.root).ledger()
        last = led[-1] if led else {}
        model, role = last.get("model"), last.get("role")
        if last.get("phase") != "reserved" or role not in rc.ROLES:
            self._halt("no fresh runner reserve to bind")
            return
        if model not in self.allowed:
            self.attempts.append({"model": model, "known_not_sent": True,
                                  "cause": "model-not-allowlisted"})
            self._halt("model not allowlisted")
            return
        base_url, key_env, epoch, opener, timeout = self.args
        mt, eff = rc.CEILINGS[role], rc.EFFORT[role]
        ad = fh.FencedHttpAdapter(base_url, model, key_env, epoch,
                                  fh.HTTP_LIFETIME_CAP, mt, timeout, eff,
                                  opener=opener)
        try:
            tok = ad.reserve()
        except fh.FenceRefused as exc:
            self.attempts.append({"model": model, "known_not_sent": True,
                                  "cause": str(exc)[:60]})
            self._halt(str(exc)[:60])
            return
        except Exception as exc:   # state of the shared log unknown
            self.attempts.append({"model": model, "known_not_sent": False,
                                  "cause": "reserve-error:"
                                  + type(exc).__name__})
            self._halt("reserve error " + type(exc).__name__
                       + " (shared log state unverified)")
            return
        self.token, self.adapter, self.params = tok, ad, (model, mt, eff)

    def post(self, model, system, prompt, mt, effort="low"):
        tok, ad, params = self.token, self.adapter, self.params
        self.token = None                        # single use
        if tok is None or params != (model, mt, effort):
            raise rc.Halt("fence reservation missing or mismatched: "
                          "no request made")
        try:
            r = ad.execute(tok, system, prompt)
        except fh.FenceRefused:
            raise rc.Halt("fence reservation unusable: no request made")
        except Exception as exc:                 # after reserve: unknown
            self.attempts.append({"model": model, "known_not_sent": False,
                                  "cause": "execute-error:"
                                  + type(exc).__name__})
            return {"kind": "unknown", "code": 0, "content": "",
                    "usage": None,
                    "diag": {"stage": "shared-fence", "class": "error"}}
        self.attempts.append({"model": model, "known_not_sent": False,
                              "kind": r["kind"], "code": r["code"],
                              "shared_n": r["n"]})
        return {k: r[k] for k in ("kind", "code", "content", "usage",
                                  "cost_signal", "finish_reason")}


def fh_allowed():
    import langgraph_team as lt
    return lt.HTTP_FREE_MODELS


def shared_eligible():
    """(ok, reason, used). Reads the shared log dir only."""
    used, halted, chain = fh._read_all(fh.HTTP_LOG_DIR)
    if not chain:
        return False, "shared log chain broken", used
    if halted:
        return False, "shared log halted", used
    if used >= fh.HTTP_LIFETIME_CAP:
        return False, "shared lifetime cap reached", used
    return True, "", used


def live_runner_step(root, listing, record, fenced, now=None, clock=None,
                     before_io=None):
    """Like runner_step but the request path is a FencedRunner. Pre-flight
    (zero runner reserve, zero request): shared fence must be eligible.
    Depends on the pinned runner calling its `before_io` seam after the
    runner reserve (a test fails if it stops). Needs halt clearance, a
    current signed allowance and a route record per runner rules; this
    function creates none of them. Returns runner_step's dict plus
    `shared` {before_used, after_used}."""
    ok, why, used0 = shared_eligible()
    if not ok:
        return {"step": None, "call_attempts": [], "halted": None,
                "refused": "preflight: " + why,
                "shared": {"before_used": used0, "after_used": used0}}
    halted, result = None, None

    def hook():
        if before_io is not None:
            before_io()
        fenced.gate()
    try:
        result = rc.step(root, fenced.post, listing if callable(listing)
                         else (lambda: listing),
                         now if now is not None else time.time(), record,
                         clock=clock, before_io=hook)
    except rc.Halt as exc:
        halted = str(exc)
    return {"step": result, "call_attempts": list(fenced.attempts),
            "halted": halted, "refused": None,
            "shared": {"before_used": used0,
                       "after_used": shared_eligible()[2]}}


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
