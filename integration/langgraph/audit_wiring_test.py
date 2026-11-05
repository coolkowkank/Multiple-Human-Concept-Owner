"""AUDIT WIRING variant. Offline dry run of the model-backed Builder -> Reviewer -> QC
continuation on a scratch lane, with a LOCAL FAKE server that returns
structured replies per seat. Proves the wiring (roster swap, fences,
budgets, verify run), not any model's ability. No provider request."""
import os as _os; _os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import http.server, json, os, shutil, sys, tempfile, threading
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fenced_http
import langgraph_team as lt

APP = "def add(a, b):\n    return a + b\n"
TEST = ("import sys, os\nsys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))\n"
        "from app import add\nassert add(2, 3) == 5\nprint('ok')\n")
REPLY = {
 "builder": {"summary": "add() and test", "writes": {"src/app.py": APP, "tests/test_app.py": TEST},
             "verify_command": "python3 tests/test_app.py", "handoff": "reviewer", "gate": None,
             "status_line": "built"},
 "reviewer": {"summary": "reviewed", "writes": {"review/findings-1.md": "None.\n"},
              "verify_command": "python3 tests/test_app.py", "handoff": "qc", "gate": None,
              "status_line": "reviewed"},
 "qc": {"summary": "pass", "writes": {"review/qc-verdict-1.md": "PASS\n"},
        "verify_command": "python3 tests/test_app.py", "handoff": "records", "gate": None,
        "status_line": "qc pass"}}
HITS = []
CALLS = {"builder": 0}

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers["content-length"])))
        text = b["messages"][1]["content"]
        seat = text.split("Seat: ")[1].split(" ")[0]
        HITS.append(seat)
        content = json.dumps(REPLY[seat])
        if seat == "builder":
            CALLS["builder"] += 1
            if CALLS["builder"] == 1:
                content = json.dumps(dict(REPLY["builder"], writes={"docs/outside.md": "x"}))
        out = json.dumps({"id": "f", "choices": [{"message": {"content": content}}],
                          "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0}}).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers()
        self.wfile.write(out)

ok = True
def check(n, c):
    global ok; ok = ok and bool(c); print(("PASS  " if c else "FAIL  ") + n, flush=True)

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
tmp = tempfile.mkdtemp()
lt.HTTP_FREE_BASE = "http://127.0.0.1:%d/v1" % srv.server_address[1]
fenced_http.HTTP_LOG_DIR = os.path.join(tmp, "logs")
os.environ[lt.HTTP_KEY_ENV] = "fake-key-not-real"
os.environ["LG_AUDIT_DIR"] = os.path.join(tmp, "audit")
try:
    repo, db = os.path.join(tmp, "lane"), os.path.join(tmp, "db.sqlite")
    lt.init_repo(repo)
    # coordinator (scripted) acts first, then the model-backed seats
    m = "nvidia/nemotron-3-ultra-550b-a55b"
    for seat, ep, bud in (("builder", "b1", 2), ("reviewer", "r1", 2), ("qc", "q1", 1)):
        lt.operator_set_http_seat(repo, seat, m, ep, bud)
    lt.run_graph(repo, db, 4, "dry")
    check("requests == 4 (builder needed one path-guard correction)", len(HITS) == 4 and HITS == ["builder", "builder", "reviewer", "qc"])
    ad = os.environ["LG_AUDIT_DIR"]
    links = {sn: [json.loads(l) for l in open(os.path.join(ad, sn + ".links.jsonl"))] for sn in ("builder", "reviewer", "qc")}
    check("builder: 2 link rows, n = 1 then 2, second is a correction round",
          [r["n"] for r in links["builder"]] == [1, 2] and [r["correction_round"] for r in links["builder"]] == [False, True])
    check("reviewer and qc: one link row each, n = 1",
          [r["n"] for r in links["reviewer"]] == [1] and [r["n"] for r in links["qc"]] == [1])
    check("link names the fenced log file, call_ids unique",
          links["builder"][0]["fenced_log"].endswith(".b1.jsonl") and len({r["call_id"] for sn in links for r in links[sn]}) == 4)
    from launcher.usage_join import join, usage_from_audit
    rows = [json.loads(l) for l in open(os.path.join(ad, "builder.audit.jsonl"))]
    rep = join(rows, usage_from_audit(rows))
    check("join: 2 builder calls both with reported usage (1+1 tokens each)",
          rep.get("provider_prompt_tokens") == 2 and rep.get("provider_completion_tokens") == 2)
    raw = "".join(open(os.path.join(ad, f)).read() for f in os.listdir(ad))
    check("no prompt text, model text or raw id in audit files",
          "outside.md" not in raw and "Agreed brief" not in raw and '"id": "f"' not in raw)
    check("lifetime reserves == 4", fenced_http._read_all(fenced_http.HTTP_LOG_DIR)[0] == 4)
    # mismatch fails closed before any request
    import audit_wiring
    class FakeSeat:  # prompt not built from the seat's inputs
        pass
    from launcher.runtime import Seat
    n0 = len(HITS)
    bad = None
    try:
        from launcher.bus import Bus
        bus = Bus(repo, lt.BRANCH)
        seat_obj = Seat(bus, "qc")
        aw = audit_wiring.AuditedFenced(fenced_http.FencedHttpAdapter(lt.HTTP_FREE_BASE, m, lt.HTTP_KEY_ENV, "z9", 1, 100, 5, "low"), seat_obj, ad)
        aw.complete("sys", "arbitrary prompt not from the seat")
    except ValueError as e:
        bad = e
    check("arbitrary prompt refused before any request", bad is not None and len(HITS) == n0)
    try:
        aw.complete("sys", seat_obj.build_prompt(bus.state())[1] + "\n\nCORRECTION REQUIRED: do something else entirely")
        bad2 = None
    except ValueError as e:
        bad2 = e
    check("arbitrary correction-looking suffix refused before any request", bad2 is not None and len(HITS) == n0)
finally:
    srv.shutdown(); shutil.rmtree(tmp, ignore_errors=True)
print("\nCONTINUATION DRY RUN:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
raise SystemExit(0 if ok else 1)
