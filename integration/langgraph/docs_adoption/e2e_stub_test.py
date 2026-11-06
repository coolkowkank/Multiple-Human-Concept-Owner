"""Offline end-to-end: real live_entry + real run_graph + the pack's real brief against a LOCAL stub
router (no provider, no real key). Checks the request shape, where the reply lands, the
scored output, and that a protocol-invalid reply is refused and spends the single call."""
import os; os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import http.server, json, subprocess, sys, tempfile, threading
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import fenced_http; fenced_http.WINDOW_GATE = False
import langgraph_team as lt, pack
REPO = subprocess.run(["git", "-C", HERE, "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
COMMIT = subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
MODEL = "novita/ling-3.1-flash"; BODIES = []; REPLY = {}
FAIL = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: FAIL.append(n)
class H(http.server.BaseHTTPRequestHandler):
    def log_message(s, *a): pass
    def _send(s, b): s.send_response(200); s.send_header("content-type", "application/json"); s.end_headers(); s.wfile.write(json.dumps(b).encode())
    def do_GET(s): s._send({"data": [{"id": MODEL, "input_price": "0", "output_price": "0"}]})
    def do_POST(s):
        BODIES.append(json.loads(s.rfile.read(int(s.headers.get("content-length", 0)))))
        s._send({"id": "f", "choices": [{"message": {"content": REPLY["text"]}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0}})
tmp = tempfile.mkdtemp(); srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
lt.HTTP_FREE_BASE = "http://127.0.0.1:%d/v1" % srv.server_address[1]
brief, texts = pack.build(REPO, COMMIT)
sent = [s.strip() for s in texts["docs/operating-rules.md"].split("\n") if len(s.strip()) > 30][0]
def run(reply_text, tag):
    REPLY["text"] = reply_text; del BODIES[:]
    fenced_http.HTTP_LOG_DIR = os.path.join(tmp, "logs-" + tag)
    cd = os.path.join(tmp, "cfg-" + tag); os.makedirs(cd); os.chmod(cd, 0o700)
    kf = os.path.join(cd, "k"); open(kf, "w").write("fake-key\n"); os.chmod(kf, 0o600)
    bf = os.path.join(cd, "brief.md"); open(bf, "wb").write(brief); os.chmod(bf, 0o600)
    c = {"key_file": kf, "brief_extra_file": bf, "stop_after": 1, "preflight": {}, "seats": {"coordinator": {"model": MODEL, "epoch": "e" + tag, "budget": 1, "max_tokens": 4096}}}
    cp = os.path.join(cd, "c.json"); open(cp, "w").write(json.dumps(c)); os.chmod(cp, 0o600)
    lane = os.path.join(tmp, "lane-" + tag); lt.init_repo(lane)
    try: rc = lt.live_entry(lane, os.path.join(tmp, "db-" + tag), cp, allow_fresh=True)
    except SystemExit as e: rc = "exit:%s" % e.code
    return lane, rc
assessment = json.dumps({"first_brief": "Convert units from the command line.", "gaps": [{"file": "docs/operating-rules.md", "quote": sent, "question": "Who closes the batch?"}]})
good = json.dumps({"summary": "assessed", "writes": {pack.OUT_PATH: assessment}, "verify_command": None, "handoff": "builder", "gate": None, "status_line": "assessed"})
lane, rc = run(good, "ok")
check("protocol-valid reply: exactly one POST, run stops gracefully (rc 0)", len(BODIES) == 1 and rc == 0)
m = BODIES[0]["messages"]; user = m[-1]["content"]
check("request: system prompt is the Coordinator JSON protocol, user turn carries the pack's task and all four docs", "Reply with ONE JSON object" in m[0]["content"] and all(("=== FILE: %s ===" % p) in user for p in pack.DOCS) and "docs-adoption assessment" in user)
check("request: the agreed-brief add(a,b) line is present and the task says it is replaced for this turn", "add(a,b)" in user and "replaced by the assessment" in user)
check("request carries no key text", "fake-key" not in json.dumps(BODIES[0]) and "Bearer" not in json.dumps(BODIES[0]))
out = pack.read_output(lane)
check("reply capture: the assessment is the committed lane file; scored pass", out is not None and pack.score(out, texts)["pass"])
lane2, rc2 = run(json.dumps(json.loads(assessment)), "bare")
check("bare assessment JSON (not the protocol): refused, and the single budgeted call is spent (no retry)", len(BODIES) == 1 and pack.read_output(lane2) is None)
lane3, rc3 = run("here is my answer: " + good, "prose")
check("prose around the JSON: protocol refused, output absent", pack.read_output(lane3) is None)
bad_path = json.dumps({"summary": "x", "writes": {"docs/out.json": assessment}, "verify_command": None, "handoff": "builder", "gate": None, "status_line": "x"})
lane4, rc4 = run(bad_path, "path")
check("write outside .team/ refused: output absent, one POST only", pack.read_output(lane4) is None and len(BODIES) == 1)
print("FAILED" if FAIL else "ALL PASS"); sys.exit(1 if FAIL else 0)
