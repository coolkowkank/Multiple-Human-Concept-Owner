"""Offline tests for usage_report.py. Synthetic rows plus rows written by the real
PromptAuditAdapter (stub inner adapter, no network, no provider). Mock/synthetic
data only: nothing here is a live measurement."""
import os as _os; _os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import io, json, os, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import usage_report as U  # noqa: E402
from launcher.prompt_audit import PromptAuditAdapter  # noqa: E402
ok = True
def check(n, c):
    global ok; ok = ok and bool(c); print(("PASS  " if c else "FAIL  ") + n, flush=True)
def start(cid): return {"event": "adapter_call_start", "call_id": cid, "audit": {"system": {"est_tokens_chars_div_4": 10}, "task": {"est_tokens_chars_div_4": 20}}}
def ret(cid, p=None, c=None, rid="r", origin="provider"):
    r = {"event": "adapter_call_returned", "call_id": cid, "provider_tokens": None}
    if p is not None:
        r["reported"] = {"origin": origin, "response_id_sha256": rid * 64 if rid else None, "reported_usage": {"prompt_tokens": p, "completion_tokens": c}}
    return r
def wr(d, name, rows, raw=None):
    with open(os.path.join(d, name), "w") as fh:
        fh.write(raw if raw is not None else "".join(json.dumps(r) + "\n" for r in rows))

# ---- pure seat_report
r = U.seat_report([start("a"), ret("a", 100, 20, "1"), start("b"), ret("b", 50, 5, "2")])
check("two provider-joined calls: sums, complete", (r["prompt_tokens"], r["completion_tokens"], r["total_tokens"], r["complete"], r["unknown"]) == (150, 25, 175, True, 0))
r = U.seat_report([start("a"), ret("a", 100, 20, "1"), start("b"), ret("b")])
check("a call with no usage is UNKNOWN, not zero; totals partial and not complete", r["unknown"] == 1 and r["total_tokens"] == 120 and r["complete"] is False)
r = U.seat_report([start("a"), ret("a")])
check("no usage at all: totals None (not 0), not complete", r["total_tokens"] is None and r["prompt_tokens"] is None and r["complete"] is False and r["unknown"] == 1)
r = U.seat_report([start("a"), ret("a", 7, 7, "1"), start("m"), {"event": "adapter_call_returned", "call_id": "m"}], usage_rows=[{"call_id": "m", "origin": "mock", "prompt_tokens": 999, "completion_tokens": 999}])
check("mock rows counted but never in totals; not complete", r["mock"] == 1 and r["total_tokens"] == 14 and r["complete"] is False)
r = U.seat_report([start("a"), ret("a", 1, 1, "1")], usage_rows=[{"call_id": "a", "origin": "provider", "prompt_tokens": 5, "completion_tokens": 5}])
check("usage in both audit evidence and explicit file: duplicate error, neither used", r["status_counts"].get("error:duplicate_usage") == 1 and r["total_tokens"] is None and r["complete"] is False)
r = U.seat_report([start("a"), ret("a", 1, 1, "1"), start("b"), ret("b", 1, 1, "1")])
check("provider response id reused across calls: both error, excluded", r["status_counts"].get("error:response_id_reused") == 2 and r["total_tokens"] is None)
for label, p, c in [("bool count", True, 1), ("negative", -1, 1), ("float", 1.5, 1), ("1e9", 10**9, 1), ("string", "9", 1)]:
    r = U.seat_report([start("a"), {"event": "adapter_call_returned", "call_id": "a"}], usage_rows=[{"call_id": "a", "origin": "provider", "prompt_tokens": p, "completion_tokens": c}])
    check(f"explicit usage {label}: rejected, unknown, no total", r["total_tokens"] is None and r["unknown"] == 1)
r = U.seat_report([start("a"), ret("a", 1, 1, "1"), ret("a", 1, 1, "1")])
check("two terminal rows for one call: incomplete audit, excluded", r["status_counts"].get("error:incomplete_or_duplicate_audit") == 1 and r["total_tokens"] is None)
r = U.seat_report([start("a"), start("a"), ret("a", 1, 1, "1")])
check("two start rows: incomplete audit, excluded", r["total_tokens"] is None)
r = U.seat_report([1, "x", None, {"call_id": 3}, start("a"), ret("a", 2, 3, "1")], usage_rows=["junk", {"call_id": None}])
check("non-dict / bad rows ignored and counted, never raise", r["ignored_audit_rows"] == 4 and r["ignored_usage_rows"] == 2 and r["total_tokens"] == 5)
check("non-list inputs never raise", U.seat_report("x", "y", "z")["calls"] == 0 and U.seat_report(None)["total_tokens"] is None)
check("empty audit: not complete (zero calls is not coverage)", U.seat_report([])["complete"] is False)
r = U.seat_report([start("a"), ret("a", 1, 1, "1"), start("b"), ret("b", 1, 1, "2")],
                  link_rows=[{"call_id": "a", "n": 3, "correction_round": True}, {"call_id": "b", "n": None, "correction_round": False},
                             {"call_id": "a", "n": 4, "correction_round": True}, {"call_id": "ghost", "n": 1}, "bad"])
check("links: correction rounds and reserve numbers tallied; duplicate/unknown/bad link rows ignored and counted", (r["correction_round_calls"], r["calls_with_reserve_number"], r["ignored_link_rows"]) == (1, 1, 3))

# ---- real-shape rows from the real PromptAuditAdapter (stub inner, no network)
tmp = tempfile.mkdtemp()
try:
    class Inner:
        REPORTS_PROVIDER_USAGE = True
        def __init__(self): self.last_call = None
        def complete(self, system, prompt):
            self.last_call = {"origin": "provider", "response_id": "resp-1", "usage": {"prompt_tokens": 321, "completion_tokens": 45}}
            return "x"
    ctx = dict(seat="builder", role="builder", brief="b", state={"turn": "builder", "turn_seq": 1}, recent_log="", batch=None, correction_suffix="")
    from launcher.prompt_audit import render_audited_prompt
    c2 = dict(ctx); c2.pop("correction_suffix"); sysm, task, _ = render_audited_prompt(**c2)
    ap = os.path.join(tmp, "builder.audit.jsonl"); PromptAuditAdapter(Inner(), ap, lambda: dict(ctx)).complete(sysm, task)
    class NoUsage(Inner):
        REPORTS_PROVIDER_USAGE = False
    PromptAuditAdapter(NoUsage(), ap, lambda: dict(ctx)).complete(sysm, task)
    rep = U.run_report(tmp)
    s = rep["seats"]["builder"]
    check("real PromptAuditAdapter rows: 2 calls, 1 provider-joined (321+45), 1 unknown, not complete", (s["calls"], s["provider_joined"], s["unknown"], s["total_tokens"], rep["complete"]) == (2, 1, 1, 366, False))
    check("report holds only counts: no prompt text, no response id", "resp-1" not in json.dumps(rep) and "builder" in rep["seats"] and task[:30] not in json.dumps(rep))

    # ---- run_report refusals
    d = os.path.join(tmp, "d1"); os.mkdir(d)
    wr(d, "good.audit.jsonl", [start("a"), ret("a", 4, 4, "1")])
    wr(d, "bad.audit.jsonl", None, raw=json.dumps(start("z")) + "\n{not json\n")
    rep = U.run_report(d)
    check("malformed line refuses that seat only; refused seats make the run not complete", "bad" in rep["refused_seats"] and "good" in rep["seats"] and rep["complete"] is False and rep["total_tokens"] == 8)
    d = os.path.join(tmp, "d2"); os.mkdir(d)
    wr(d, "real.audit.jsonl", [start("a"), ret("a", 4, 4, "1")])
    os.symlink(os.path.join(d, "real.audit.jsonl"), os.path.join(d, "ln.audit.jsonl"))
    rep = U.run_report(d); check("symlinked audit file refused (O_NOFOLLOW)", "ln" in rep["refused_seats"])
    wr(d, "real.usage.jsonl", None, raw="[1\n"); rep = U.run_report(d)
    check("malformed optional usage file refuses the seat (does not silently ignore it)", "real" in rep["refused_seats"])
    os.symlink(d, os.path.join(tmp, "dlink"))
    try: U.run_report(os.path.join(tmp, "dlink")); sl = False
    except U.ReportError: sl = True
    check("audit dir that is a symlink refused", sl)
    try: U.run_report(os.path.join(tmp, "nope")); nd = False
    except U.ReportError: nd = True
    check("missing audit dir refused", nd)
    d = os.path.join(tmp, "d3"); os.mkdir(d); rep = U.run_report(d)
    check("empty dir: no seats, not complete, totals None", rep["complete"] is False and rep["total_tokens"] is None and rep["seats"] == {})
    # explicit usage file joins by local call_id
    d = os.path.join(tmp, "d4"); os.mkdir(d)
    wr(d, "s.audit.jsonl", [start("a"), ret("a")]); wr(d, "s.usage.jsonl", [{"call_id": "a", "origin": "provider", "prompt_tokens": 9, "completion_tokens": 1}])
    rep = U.run_report(d); check("explicit <seat>.usage.jsonl joins on local call_id", rep["total_tokens"] == 10 and rep["complete"] is True)
    # pin
    real = U.USAGE_JOIN_MD5; U.USAGE_JOIN_MD5 = "0" * 32
    try: U.run_report(d); pin = False
    except U.ReportError: pin = True
    finally: U.USAGE_JOIN_MD5 = real
    check("changed usage_join.py (pin mismatch) refuses to report", pin)
    check("run_report does not write anything into the audit dir", sorted(os.listdir(d)) == ["s.audit.jsonl", "s.usage.jsonl"])

    # ---- cross-seat collisions
    def run_dir(name, seats):
        d = os.path.join(tmp, name); os.mkdir(d)
        for sn, rows in seats.items(): wr(d, sn + ".audit.jsonl", rows)
        return d
    d = run_dir("x1", {"s1": [start("c1"), ret("c1", 100, 20, "1")], "s2": [start("c1"), ret("c1", 100, 20, "1")]})
    rep = U.run_report(d)
    check("same call_id + same response id in two seats: BOTH refused, not double counted, not complete", set(rep["refused_seats"]) == {"s1", "s2"} and rep["total_tokens"] is None and rep["complete"] is False and rep["seats"] == {})
    d = run_dir("x2", {"s1": [start("a"), ret("a", 100, 20, "1")], "s2": [start("b"), ret("b", 100, 20, "1")]})
    rep = U.run_report(d); check("same provider response id across seats (different call_ids): both refused", set(rep["refused_seats"]) == {"s1", "s2"} and rep["total_tokens"] is None)
    d = run_dir("x3", {"s1": [start("c1"), ret("c1", 1, 1, "1")], "s2": [start("c1"), ret("c1", 2, 2, "2")], "s3": [start("z"), ret("z", 5, 5, "3")]})
    rep = U.run_report(d); check("call_id collision refuses only the colliding seats; the clean seat still reports, run not complete", set(rep["refused_seats"]) == {"s1", "s2"} and rep["total_tokens"] == 10 and rep["complete"] is False and rep["cross_seat_collision_seats"] == ["s1", "s2"])
    d = run_dir("x4", {"s1": [start("a"), ret("a", 1, 1, "1")], "s2": [start("b"), ret("b", 2, 2, "2")]})
    rep = U.run_report(d); check("distinct ids across seats: no collision, complete, sums", rep["complete"] and rep["total_tokens"] == 6 and not rep["refused_seats"])
    check("report carries a digest that matches its body; changing a field changes it", rep["digest"] == U.digest(rep) and U.digest(dict(rep, calls=99)) != rep["digest"])
    check("report labels explicit-file usage provenance (0 here) and says so in the note", rep["usage_from_explicit_file_calls"] == 0 and "operator-supplied" in rep["note"])
    d = os.path.join(tmp, "d4"); rep = U.run_report(d)
    check("explicit usage file calls are counted in provenance label", rep["usage_from_explicit_file_calls"] == 1 and rep["seats"]["s"]["usage_from_explicit_file_calls"] == 1)

    # ---- compare (recomputes from dirs; operator-attested outcomes bound to the run digest)
    dirA = run_dir("cA", {"s": [start("a"), ret("a", 600, 400, "1")]}); dirB = run_dir("cB", {"s": [start("b"), ret("b", 400, 300, "2")]})
    dA, dB = U.run_report(dirA)["digest"], U.run_report(dirB)["digest"]
    good = lambda dg, tid="T1": {"task_id": tid, "accepted": True, "acceptance_evidence": "review abc123", "report_digest": dg}
    r = U.compare(dirA, dirB, good(dA), good(dB))
    check("matched, bound, accepted, complete: difference shown, operator-attested and not a savings claim", r["comparable"] and r["difference_b_minus_a"] == -300 and "OPERATOR-ATTESTED" in r["note"] and "not a savings claim" in r["note"])
    cases = [("different task_id", good(dA), good(dB, "T2")),
             ("B not accepted", good(dA), dict(good(dB), accepted=False)),
             ("accepted truthy string", good(dA), dict(good(dB), accepted="true")),
             ("accepted is 1", dict(good(dA), accepted=1), good(dB)),
             ("no evidence", good(dA), {k: v for k, v in good(dB).items() if k != "acceptance_evidence"}),
             ("blank evidence", good(dA), dict(good(dB), acceptance_evidence="  ")),
             ("no task_id", {k: v for k, v in good(dA).items() if k != "task_id"}, good(dB)),
             ("outcome bound to the OTHER run's digest", good(dB), good(dA)),
             ("outcome without report_digest", {k: v for k, v in good(dA).items() if k != "report_digest"}, good(dB)),
             ("stale digest (run changed after sign-off)", good("0" * 64), good(dB)),
             ("outcome not an object", good(dA), "ok")]
    for label, oa, ob in cases:
        r = U.compare(dirA, dirB, oa, ob); check(f"compare refuses: {label}", r["comparable"] is False and r["reasons"] and "difference_b_minus_a" not in r)
    r = U.compare(dirA, dirA, good(dA), good(dA)); check("self-comparison (same dir) refused", r["comparable"] is False and "same directory" in r["reasons"][0])
    copyA = os.path.join(tmp, "cA2"); shutil.copytree(dirA, copyA)
    r = U.compare(dirA, copyA, good(dA), good(dA)); check("copied identical run refused (identical digest)", r["comparable"] is False and any("identical" in x for x in r["reasons"]))
    dirU = run_dir("cU", {"s": [start("a2"), ret("a2")]}); dU = U.run_report(dirU)["digest"]
    r = U.compare(dirA, dirU, good(dA), good(dU)); check("incomplete run (unknown call) refused", r["comparable"] is False and any("incomplete" in x for x in r["reasons"]))
    dirK = run_dir("cK", {"s1": [start("k"), ret("k", 1, 1, "7")], "s2": [start("k"), ret("k", 1, 1, "7")]}); dK = U.run_report(dirK)["digest"]
    r = U.compare(dirA, dirK, good(dA), good(dK)); check("run with cross-seat collision refused", r["comparable"] is False)
    # forged saved report cannot matter: compare takes dirs; a report file as a dir is refused
    wr(tmp, "forged.json", None, raw=json.dumps({"schema": "usage-report/v1", "complete": True, "total_tokens": 10}))
    try: U.compare(os.path.join(tmp, "forged.json"), dirB, good(dA), good(dB)); fg = False
    except U.ReportError: fg = True
    check("a hand-written report file is not accepted as run evidence (compare needs audit dirs)", fg)
    import subprocess
    def cli(*a):
        p = subprocess.run([sys.executable, os.path.join(HERE, "usage_report.py"), *a], capture_output=True, text=True); return p.returncode, p.stdout, p.stderr
    rc, out, err = cli("report", os.path.join(tmp, "d4")); check("CLI report: exit 0, valid JSON, schema usage-report/v1, digest present", rc == 0 and json.loads(out)["schema"] == "usage-report/v1" and json.loads(out)["digest"])
    p = lambda n: os.path.join(tmp, n)
    wr(tmp, "oa.json", None, raw=json.dumps(good(dA))); wr(tmp, "ob.json", None, raw=json.dumps(good(dB))); wr(tmp, "obad.json", None, raw=json.dumps(dict(good(dB), accepted=False)))
    rc, out, err = cli("compare", dirA, dirB, p("oa.json"), p("obad.json")); check("CLI compare not matched: exit 2, no figure", rc == 2 and "difference_b_minus_a" not in out)
    rc, out, err = cli("compare", dirA, dirB, p("oa.json"), p("ob.json")); check("CLI compare matched: exit 0", rc == 0 and json.loads(out)["difference_b_minus_a"] == -300)
    wr(tmp, "oweird.json", None, raw="[1,2]"); rc, out, err = cli("compare", dirA, dirB, p("oa.json"), p("oweird.json")); check("CLI compare with non-object outcome: exit 2, no traceback", rc == 2 and "Traceback" not in err)
    rc, out, err = cli("compare", dirA, dirB, p("oa.json"), p("missing.json")); check("CLI compare missing outcome file: exit 1, one line, no traceback", rc == 1 and "Traceback" not in err)
    rc, out, err = cli("report", p("missing")); check("CLI bad dir: exit 1, one-line error, no traceback", rc == 1 and "Traceback" not in err)
    rc, out, err = cli(); check("CLI no args: usage, exit 1", rc == 1 and "usage" in err)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nUSAGE REPORT:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
raise SystemExit(0 if ok else 1)
