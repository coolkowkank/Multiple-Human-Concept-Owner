"""Parallel independent team lanes under one LangGraph parent graph.

Three independent team pipelines (lane-a/b/c, separate repos, separate
checkpoint threads) execute concurrently as parallel branches. Within
each lane the project's dependency edges still serialize through the
single turn token. A shared seat gate caps concurrent seat actions
across ALL lanes (mock mode spends nothing; this is where a shared
budget control would attach in live mode - one control, not per-lane
allowances). Also runs a deterministic no-network overlap test proving
the gate's cap and genuine parallel execution.
"""

from __future__ import annotations

import json
import operator
import os
import sys
import threading
import time
from typing import Annotated, TypedDict

import langgraph_team as lt
from langgraph.graph import END, START, StateGraph

LANES = ("lane-a", "lane-b", "lane-c")
SEAT_CAP = 2  # max simultaneous seat actions across all lanes


class ParallelState(TypedDict):
    base: str
    results: Annotated[list, operator.add]


def lane_node(lane: str, state: ParallelState) -> dict:
    repo = os.path.join(state["base"], lane)
    db = os.path.join(state["base"], f"db-{lane[-1]}.sqlite")
    t0 = time.time()
    lt.run_graph(repo, db, stop_after=0, thread_id=f"team-demo-{lane[-1]}")
    t1 = time.time()
    rec = {"lane": lane, "t_start": round(t0, 3), "t_end": round(t1, 3),
           "seconds": round(t1 - t0, 2), "tid": threading.get_ident()}
    return {"results": [json.dumps(rec)]}


def build_parent():
    g = StateGraph(ParallelState)
    for lane in LANES:
        g.add_node(lane, lambda s, _l=lane: lane_node(_l, s))
        g.add_edge(START, lane)
        g.add_edge(lane, END)
    return g.compile()


def controlled_overlap_test(branches=5, cap=2, work_s=0.6):
    """Deterministic no-network proof: parallel branches really overlap,
    and a shared gate caps concurrency at exactly `cap`."""
    sem = threading.BoundedSemaphore(cap)
    mon = lt.GateMonitor()

    class S(TypedDict):
        done: Annotated[list, operator.add]

    def task(i, state):
        with sem:
            mon.enter()
            time.sleep(work_s)
            mon.exit()
        return {"done": [i]}

    g = StateGraph(S)
    for i in range(branches):
        g.add_node(f"task_{i}", lambda s, _i=i: task(_i, s))
        g.add_edge(START, f"task_{i}")
        g.add_edge(f"task_{i}", END)
    t0 = time.time()
    g.compile().invoke({"done": []})
    elapsed = time.time() - t0
    serial = branches * work_s
    print(f"controlled overlap test: {branches} no-network branches x "
          f"{work_s}s, shared cap {cap}")
    print(f"  serial would take ~{serial:.1f}s; observed {elapsed:.1f}s; "
          f"concurrency high-water {mon.high_water} (cap {cap})")
    ok = mon.high_water == cap and elapsed < serial * 0.8
    print(f"  {'PASS' if ok else 'FAIL'}  genuine overlap with cap held")
    return ok


def main(argv) -> int:
    base = os.path.abspath(argv[1])
    # One shared gate across every lane's seat actions.
    lt.SEAT_GATE = threading.BoundedSemaphore(SEAT_CAP)
    lt.GATE_MONITOR = lt.GateMonitor()

    ok = controlled_overlap_test()

    print(f"\nparallel team run: lanes {LANES}, shared seat cap {SEAT_CAP}")
    t0 = time.time()
    final = build_parent().invoke({"base": base, "results": []})
    wall = time.time() - t0
    results = sorted((json.loads(r) for r in final["results"]),
                     key=lambda r: r["t_start"])
    print("\nlane timeline (wall clock, seconds since run start):")
    for r in results:
        print(f"  {r['lane']}: {r['t_start']-t0:6.2f} -> {r['t_end']-t0:6.2f} "
              f"({r['seconds']}s, tid {r['tid']})")
    overlap = any(
        a["t_start"] < b["t_end"] and b["t_start"] < a["t_end"]
        for i, a in enumerate(results) for b in results[i + 1:])
    print(f"lanes genuinely overlapped in time: {overlap}")
    print(f"seat gate: {lt.GATE_MONITOR.acquisitions} seat actions, "
          f"high-water {lt.GATE_MONITOR.high_water} (cap {SEAT_CAP})")

    for lane in LANES:
        ok = lt.verify(os.path.join(base, lane),
                       os.path.join(base, f"db-{lane[-1]}.sqlite"),
                       f"team-demo-{lane[-1]}",
                       expect_resume=(lane == "lane-a")) and ok
    print("\nPARALLEL RUN:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
