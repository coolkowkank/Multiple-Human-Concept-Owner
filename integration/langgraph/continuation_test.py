"""Offline dry run of the model-backed Builder -> Reviewer -> QC
continuation on a scratch lane, with a LOCAL FAKE server that returns
structured replies per seat. Proves the wiring (roster swap, fences,
budgets, verify run), not any model's ability. No provider request."""
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

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers["content-length"])))
        text = b["messages"][1]["content"]
        seat = text.split("Seat: ")[1].split(" ")[0]
        HITS.append(seat)
        out = json.dumps({"id": "f", "choices": [{"message": {"content": json.dumps(REPLY[seat])}}],
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
try:
    repo, db = os.path.join(tmp, "lane"), os.path.join(tmp, "db.sqlite")
    lt.init_repo(repo)
    # coordinator (scripted) acts first, then the model-backed seats
    m = "nvidia/nemotron-3-ultra-550b-a55b"
    for seat, ep, bud in (("builder", "b1", 2), ("reviewer", "r1", 2), ("qc", "q1", 1)):
        lt.operator_set_http_seat(repo, seat, m, ep, bud)
    lt.run_graph(repo, db, 4, "dry")
    check("seats hit the fake server in order", HITS[:3] == ["builder", "reviewer", "qc"])
    check("requests == 3 (one per seat, no retries)", len(HITS) == 3)
    check("app + test written by the builder seat",
          os.path.exists(os.path.join(repo, "src/app.py")) and os.path.exists(os.path.join(repo, "tests/test_app.py")))
    check("lifetime reserves counted across epochs == 3",
          fenced_http._read_all(fenced_http.HTTP_LOG_DIR)[0] == 3)
    try:
        lt.operator_set_http_seat(repo, "qc", "openai/gpt-5", "x1", 1); refused = False
    except SystemExit:
        refused = True
    check("operator_set_http_seat refuses a non-allowlisted model", refused)
finally:
    srv.shutdown(); shutil.rmtree(tmp, ignore_errors=True)
print("\nCONTINUATION DRY RUN:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
raise SystemExit(0 if ok else 1)
