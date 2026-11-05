"""Independent adversarial probes of the loopback relay + Seat._wait (ac110c8).
Local 127.0.0.1 ephemeral servers only, no provider, no external network. Hints are never commands.
Group 1: PASS/FAIL regressions. Group 2: findings printed as GAP (desired behaviour asserted); --strict fails on gaps.
Does not claim multi-machine or unattended safety."""
import os as _os; _os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import contextlib, http.client, io, json, os, shutil, socket, subprocess, sys, tempfile, threading, time
from http.server import ThreadingHTTPServer
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import langgraph_team as lt  # noqa: E402
from launcher import relay as R  # noqa: E402
from launcher.bus import Bus  # noqa: E402
from launcher.runtime import Seat  # noqa: E402
STRICT = "--strict" in sys.argv; good = True; gaps = 0
def check(n, c):
    global good; good = good and bool(c); print(("PASS  " if c else "FAIL  ") + n, flush=True)
def gap(n, c):
    global gaps; gaps += (not c); print(("PASS  " if c else "GAP   ") + n, flush=True)
TOKEN = "t0ken-probe"
def start(port=0, token=TOKEN):
    st = R.RelayState(token); srv = ThreadingHTTPServer(("127.0.0.1", port), R.make_handler(st))
    srv.daemon_threads = True; threading.Thread(target=srv.serve_forever, daemon=True).start(); return srv, st, srv.server_address[1]
def stop(srv): srv.shutdown(); srv.server_close()
def raw(port, method, path, body=None, headers=None, token=TOKEN, timeout=5):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout); h = {} if token is None else {R.TOKEN_HEADER: token}
    h.update(headers or {})
    try:
        c.request(method, path, body=body, headers=h); r = c.getresponse(); return r.status, r.read()
    except Exception as e: return type(e).__name__, b""
    finally: c.close()
def quiet(fn):
    err = io.StringIO()
    with contextlib.redirect_stderr(err): fn()
    return err.getvalue()
tmp = tempfile.mkdtemp(); repo = os.path.join(tmp, "r"); lt.init_repo(repo)
def mkseat(client): return Seat(Bus(repo, lt.BRANCH), "coordinator", poll_interval=0.3, relay=client)
try:
    # ---- G1 restart: old cursor, new epoch, new hint visible; no deafness
    srv, st, port = start(); cl = R.RelayClient(f"http://127.0.0.1:{port}", TOKEN, timeout=3)
    for _ in range(9): st.post("s", "wake", "x")
    seat = mkseat(cl); seat._wait(); c0 = seat._relay_seq; stop(srv)
    srv2, st2, _ = start(port); st2.post("s", "wake", "after-restart")
    out = quiet(lambda: seat._wait())
    check("restart on same port: epoch change detected, cursor resynced (<= new latest), one log line", seat._relay_seq <= st2.latest and out.count("restarted") == 1 and c0 == 9)
    st2.post("s", "wake", "second"); t0 = time.time(); seat._wait()
    check("hint posted after resync is consumed (cursor advances)", seat._relay_seq == st2.latest)
    # ---- G1 prior-version deafness (reproduce on the pre-fix tree extracted from git)
    old = os.path.join(tmp, "old")
    try:
        os.makedirs(old)
        subprocess.run(f"cd {HERE}/../.. && git archive dd2f93d integration/langgraph | tar -x -C {old}", shell=True, check=True, capture_output=True)
        script = r'''
import sys, os, threading, time, io, contextlib
os.environ["LG_VERIFY_SANDBOX"]="1"; sys.path.insert(0, sys.argv[1])
from http.server import ThreadingHTTPServer
from launcher import relay as R
from launcher.runtime import Seat
from launcher.bus import Bus
import langgraph_team as lt
def start(port=0):
    st=R.RelayState("t"); s=ThreadingHTTPServer(("127.0.0.1",port),R.make_handler(st)); s.daemon_threads=True
    threading.Thread(target=s.serve_forever,daemon=True).start(); return s,st,s.server_address[1]
s,st,p=start(); [st.post("a","wake","x") for _ in range(9)]
cl=R.RelayClient(f"http://127.0.0.1:{p}","t",timeout=3)
seat=Seat(Bus(sys.argv[2],lt.BRANCH),"coordinator",poll_interval=0.3,relay=cl); seat._wait()
s.shutdown(); s.server_close(); s2,st2,_=start(p); st2.post("a","wake","new")
seat._wait(); print("CURSOR", seat._relay_seq, "NEWSEQ", len(st2.messages))
'''
        r = subprocess.run([sys.executable, "-c", script, os.path.join(old, "integration/langgraph"), repo], capture_output=True, text=True, timeout=60)
        if "CURSOR" not in r.stdout: print("   old-tree stderr:", r.stderr[-300:])
        line = [l for l in r.stdout.splitlines() if l.startswith("CURSOR")]
        cur, new = (int(line[0].split()[1]), int(line[0].split()[3])) if line else (None, None)
        check(f"pre-fix dd2f93d reproduces deafness (cursor {cur} stays above the restarted server's seq {new}, hint never seen)", cur is not None and cur > new)
        check("same scenario on ac110c8: seat resynced and not above server latest", seat._relay_seq <= st2.latest)
    except Exception as e:
        print("SKIP  pre-fix repro unavailable:", type(e).__name__, str(e)[:100])
    # ---- G1 forged / hostile server replies
    class Fake:
        def __init__(self, reply): self.reply = reply; self.calls = 0
        def poll(self, a, wait=0): self.calls += 1; return self.reply
        def post(self, *a): pass
    s = mkseat(Fake({"messages": [{"seq": 10**15}], "epoch": "E1", "latest": 5})); quiet(lambda: s._wait())
    check("forged huge hint seq: cursor jumps, but next poll (latest=5 < cursor) resyncs, not deaf forever", (quiet(lambda: s._wait()) or True) and s._relay_seq <= 5)
    for label, reply in [("seq is a string", {"messages": [{"seq": "9"}], "epoch": "E", "latest": 1}), ("messages not a list", {"messages": 7}), ("reply not a dict", [1, 2]), ("message w/o seq", {"messages": [{}]})]:
        s = mkseat(Fake(reply)); t0 = time.time()
        try: out = quiet(lambda: s._wait()); crashed = False
        except BaseException: crashed = True
        check(f"hostile reply ({label}): _wait never raises, falls back to git polling", not crashed)
    # ---- G1 outage: one log line, backoff, no hammering, retry after window
    class Down:
        calls = 0
        def poll(self, a, wait=0): Down.calls += 1; raise ConnectionRefusedError("secret-token-xyz")
        def post(self, *a): pass
    s = mkseat(Down()); outs = [quiet(lambda: s._wait()) for _ in range(5)]
    check("outage: exactly one log line, one relay attempt across 5 waits (no hammering)", "".join(outs).count("relay: unavailable") == 1 and Down.calls == 1)
    check("outage log names the exception type only (no secret/token text)", "secret-token-xyz" not in "".join(outs) and TOKEN not in "".join(outs))
    s._relay_retry_at = 0; quiet(lambda: s._wait()); check("after the backoff window the relay is retried exactly once more, silently", Down.calls == 2)
    # ---- G1 server robustness
    srv, st, port = start(); st.post("s", "k", "b")
    for label, kw in [("content-length -1", dict(headers={"content-length": "-1"})), ("content-length 1e3", dict(headers={"content-length": "1e3"})), ("content-length 10**30", dict(headers={"content-length": str(10**30)}))]:
        code, _ = raw(port, "POST", "/messages", **kw); check(f"POST {label}: 4xx", code in (400, 413))
    check("POST JSON array body: 400", raw(port, "POST", "/messages", body=b"[1]")[0] == 400)
    check("POST invalid UTF-8/JSON: 400", raw(port, "POST", "/messages", body=b"\xff\xfe{")[0] == 400)
    for q in ("since=abc", f"since={'9'*5000}", "since=1&wait=abc", "since=1&wait=1e999x"):
        code, _ = raw(port, "GET", "/messages?" + q); check(f"GET ?{q[:20]}: 400, server alive", code == 400 and raw(port, "GET", "/messages")[0] == 200)
    for w in ("nan", "-5", "-inf"):
        t0 = time.time(); code, _ = raw(port, "GET", f"/messages?since=1000&wait={w}"); check(f"GET wait={w}: returns immediately", code == 200 and time.time() - t0 < 1)
    t0 = time.time(); code, b = raw(port, "GET", "/messages?since=0&wait=inf"); check("GET wait=inf with pending hint: immediate", code == 200 and time.time() - t0 < 1)
    code, b = raw(port, "GET", "/messages", token="wrong"); check("wrong token: 403 and body does not echo any token", code == 403 and TOKEN.encode() not in b and b"wrong" not in b)
    check("no token header: 403", raw(port, "GET", "/messages", token=None)[0] == 403)
    check("non-ASCII token header: 403 not 500/crash", raw(port, "GET", "/messages", token="tök\u00e9n")[0] in (403, "RemoteDisconnected", "ConnectionResetError") and raw(port, "GET", "/messages")[0] == 200)
    # truncated body / slow client must not block other clients
    s1 = socket.create_connection(("127.0.0.1", port)); s1.sendall(f"POST /messages HTTP/1.1\r\nHost: x\r\n{R.TOKEN_HEADER}: {TOKEN}\r\nContent-Length: 100\r\n\r\n{{\"a\":".encode())
    t0 = time.time(); code, _ = raw(port, "GET", "/messages"); check("stalled half-sent POST does not block other requests", code == 200 and time.time() - t0 < 2)
    # ---- G2 gaps
    gap("deeply nested JSON body does not kill the handler thread without a reply (RecursionError is not ValueError)", raw(port, "POST", "/messages", body=b"[" * 60000)[0] == 400)
    check("body over the 64KB cap: 413", raw(port, "POST", "/messages", body=b"[" * 100000)[0] == 413)
    before = len(st.messages); raw(port, "POST", "/messages", body=None, headers={"transfer-encoding": "chunked"})
    gap("POST with no body / chunked (no content-length) does not append a phantom hint", len(st.messages) == before)
    stop(srv)
    try: R.RelayState(""); empty_refused = False
    except ValueError: empty_refused = True
    gap("a server cannot be started with an empty token (refused at construction)", empty_refused)
    srv, st, port = start(); s1.close()
    g = socket.create_connection(("127.0.0.1", port)); g.sendall(f"POST /messages HTTP/1.1\r\nHost: x\r\n{R.TOKEN_HEADER}: {TOKEN}\r\nContent-Length: 100\r\n\r\nab".encode()); time.sleep(6)
    g.settimeout(1)
    try: dead = g.recv(100) == b""   # server closed the connection (EOF)
    except socket.timeout: dead = False
    except OSError: dead = True
    gap("a stalled half-sent request is dropped by the server within ~5s (no per-connection read timeout today: thread held until the client closes)", dead)
    g.close(); stop(srv)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print(f"\nRELAY PROBES: {'regressions ALL PASS' if good else 'FAILURES ABOVE'}; gaps at this head: {gaps}")
raise SystemExit(0 if good and not (STRICT and gaps) else 1)
