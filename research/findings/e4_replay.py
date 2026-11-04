"""E4 harness. Pure stdlib, no launcher import, no network.
Part 1: synthetic fixtures (harness check only, not evidence).
Part 2: replay of the one recorded multi-seat history (recorded-requesty-LOG.jsonl, branch
live/requesty-tinylib-experiment @ e51fae66afce4d1ae2bd8ef2e2ac011c692b03ca, .team/LOG.jsonl).
Equal window for all rules. Truth labels are declared in E4-stall-rule-replay.md."""
import json, calendar, time, sys, os
def ts(s): return calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
POLL, WINDOW = 5, 900   # supervisor poll=5 (supervisor.py), window = stall_timeout default 900 (supervisor.py)
BUG = 7200              # buggy mktime parse in a UTC+2 container adds 2h to the apparent age

def rule_a(age, holder, status="running"):      # age rule (turn_since only)
    return holder is not None and status == "running" and age >= WINDOW
def rule_b(age_since_progress, holder, status="running", wait=False, alive=True):
    if holder is None or status != "running": return "no"
    if not alive: return "unreachable"
    if wait: return "no"
    return "stalled" if age_since_progress >= WINDOW else "no"

def replay(path):
    rows = [json.loads(l) for l in open(path)]
    hand = [r for r in rows if r["kind"] == "handoff"]
    ops = [r for r in rows if r["kind"] == "intervention"]
    # holder timeline derived from the log: after handoff n, the holder is the author of handoff n+1,
    # except builder seq2 (null handoff): turn is None until the operator intervention.
    tl = []  # (start_ts, holder)
    for i, h in enumerate(hand):
        t0 = ts(h["ts"]); nxt = hand[i+1]["seat"] if i+1 < len(hand) else None
        if str(h.get("turn_seq")) == "2": tl.append((t0, None)); tl.append((ts(ops[0]["ts"]), nxt))
        elif i+1 < len(hand): tl.append((t0, nxt))
        else: tl.append((t0, "DONE"))
    seat_events = {}
    for r in rows:
        if r["kind"] == "handoff": seat_events.setdefault(r["seat"], []).append(ts(r["ts"]))
    start, end = ts(rows[0]["ts"]), ts(rows[-1]["ts"])
    out = {"A_bug": [], "A_fixed": [], "B": []}
    stalled_bug = set(); stalled_fix = set(); stalled_b = set()
    for t in range(start, end + 1, POLL):
        cur = [x for x in tl if x[0] <= t]
        if not cur: continue
        t0, holder = cur[-1]
        if holder in (None, "DONE"): continue
        age = t - t0
        prog = max([t0] + [e for e in seat_events.get(holder, []) if e <= t])
        if rule_a(age + BUG, holder) and holder not in stalled_bug: stalled_bug.add(holder); out["A_bug"].append((t, holder))
        if rule_a(age, holder) and holder not in stalled_fix: stalled_fix.add(holder); out["A_fixed"].append((t, holder))
        if rule_b(t - prog, holder) == "stalled" and holder not in stalled_b: stalled_b.add(holder); out["B"].append((t, holder))
    observed = [(ts(r["ts"]), r["body"].split()[-1] if False else r["body"][:40]) for r in rows if r["kind"] == "stall"]
    return out, observed, hand
if __name__ == "__main__":
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recorded-requesty-LOG.jsonl")
    out, observed, hand = replay(p)
    fmt = lambda L: [(time.strftime("%H:%M:%S", time.gmtime(t)), h) for t, h in L]
    print("observed supervisor 'stall' rows:", [(time.strftime("%H:%M:%S", time.gmtime(t)), b) for t, b in observed])
    for k, v in out.items(): print(f"{k:8} flags: {fmt(v)}")
    steps = [ts(hand[i+1]["ts"]) - ts(hand[i]["ts"]) for i in range(len(hand)-1)]
    print("handoff-to-handoff seconds:", steps, "max", max(steps), "window", WINDOW)
