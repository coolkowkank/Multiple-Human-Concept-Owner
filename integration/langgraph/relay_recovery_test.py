"""Offline: relay hints stay hints, but stop dying silently. Real loopback
servers (127.0.0.1, ephemeral ports), real RelayClient, real Seat._wait.
No provider, no model, no external network."""
import os as _os; _os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import contextlib, http.client, io, json, os, shutil, sys, tempfile, threading, time
from http.server import ThreadingHTTPServer
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import langgraph_team as lt  # noqa: E402
from launcher import relay as R  # noqa: E402
from launcher.bus import Bus  # noqa: E402
from launcher.runtime import Seat  # noqa: E402
ok = True
def check(n, c):
    global ok; ok = ok and bool(c); print(("PASS  " if c else "FAIL  ") + n, flush=True)

TOKEN = "t0ken-test"
def start(port=0):
    st = R.RelayState(TOKEN)
    srv = ThreadingHTTPServer(("127.0.0.1", port), R.make_handler(st))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, st, srv.server_address[1]
def raw(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {R.TOKEN_HEADER: TOKEN}; h.update(headers or {})
    c.request(method, path, body=body, headers=h); r = c.getresponse(); data = r.read(); c.close()
    return r.status, data
def quiet(fn):
    err = io.StringIO()
    with contextlib.redirect_stderr(err): fn()
    return err.getvalue()

tmp = tempfile.mkdtemp()
try:
    srv, st, port = start()
    # ---- server hardening ----
    for i in range(R.MAX_MESSAGES + 5): st.post("s", "wake", "x")
    check("seq is monotonic and independent of trimming (latest == posted count)", st.latest == R.MAX_MESSAGES + 5 and len(st.messages) == R.MAX_MESSAGES and st.messages[-1]["seq"] == st.latest)
    check("a cursor inside the retained window still gets exactly the newer hints", len(st.since(st.latest - 3)) == 3)
    st.post("S" * 5000, "K" * 5000, "B" * 5000)
    m = st.messages[-1]; check("field lengths capped", max(len(m["seat"]), len(m["kind"]), len(m["body"])) <= R.MAX_FIELD)
    s, d = raw(port, "GET", "/messages?since=0&wait=0"); j = json.loads(d)
    check("reply carries epoch and latest", s == 200 and j["epoch"] == st.epoch and j["latest"] == st.latest)
    check("bad token: 403", raw(port, "GET", "/messages", headers={R.TOKEN_HEADER: "nope"})[0] == 403)
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5); c.request("GET", "/messages"); r = c.getresponse(); check("missing token: 403", r.status == 403); r.read(); c.close()
    check("non-integer since: 400 (no handler crash)", raw(port, "GET", "/messages?since=x")[0] == 400)
    check("non-numeric wait: 400", raw(port, "GET", "/messages?wait=abc")[0] == 400)
    t0 = time.time(); s, _ = raw(port, "GET", "/messages?since=999999&wait=nan"); check("NaN wait does not hang (treated as 0)", s == 200 and time.time() - t0 < 3)
    t0 = time.time(); s, _ = raw(port, "GET", "/messages?since=999999&wait=-5"); check("negative wait treated as 0", s == 200 and time.time() - t0 < 3)
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5); c.putrequest("POST", "/messages"); c.putheader(R.TOKEN_HEADER, TOKEN); c.putheader("content-length", str(R.MAX_BODY + 1)); c.endheaders(); r = c.getresponse(); check("oversized content-length refused with 413 before reading", r.status == 413); c.close()
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5); c.putrequest("POST", "/messages"); c.putheader(R.TOKEN_HEADER, TOKEN); c.putheader("content-length", "abc"); c.endheaders(); r = c.getresponse(); check("bad content-length: 400", r.status == 400); c.close()
    check("JSON array body: 400", raw(port, "POST", "/messages", body="[1]")[0] == 400)
    check("invalid JSON body: 400", raw(port, "POST", "/messages", body="{nope")[0] == 400)
    check("valid post still works", raw(port, "POST", "/messages", body=json.dumps({"seat": "a", "kind": "wake", "body": "turn -> b"}))[0] == 200)
    srv.shutdown(); srv.server_close()

    # ---- seat side ----
    repo = os.path.join(tmp, "l"); lt.init_repo(repo)
    def mkseat(client):
        s = Seat(Bus(repo, lt.BRANCH), "coordinator", poll_interval=0.3, relay=client); return s
    # restart: same port, new server state (seq numbering restarts)
    srv, st, port = start()
    cl = R.RelayClient(f"http://127.0.0.1:{port}", TOKEN, timeout=5)
    for i in range(6): st.post("x", "wake", "w")
    seat = mkseat(cl); seat._wait(); check("seat consumed existing hints (cursor at 6)", seat._relay_seq == 6)
    srv.shutdown(); srv.server_close(); time.sleep(0.2)
    srv2, st2, _ = start(port)          # restarted relay: new epoch, seq from 1
    out = quiet(lambda: seat._wait())
    check("restart detected: cursor resynced, message printed", seat._relay_seq == 0 and "restarted" in out)
    st2.post("y", "wake", "after restart")
    t0 = time.time(); seat._wait()
    check("a hint posted AFTER the restart is seen (before: silently deaf forever)", seat._relay_seq == 1 and time.time() - t0 < 2)
    # outage: server down -> clean fallback, visible once, retried later
    srv2.shutdown(); srv2.server_close(); time.sleep(0.2)
    out = quiet(lambda: seat._wait())
    check("outage: relay disabled for now, one visible message, no exception", seat.relay is None and "unavailable" in out)
    out = quiet(lambda: seat._wait())
    check("inside the retry window the relay is not hammered and nothing is printed again", seat.relay is None and out == "")
    srv3, st3, _ = start(port)
    seat._relay_retry_at = 0            # retry window elapsed
    st3.post("z", "wake", "back")
    seat._wait()
    check("relay re-enabled after the retry window and hints flow again", seat.relay is not None and seat._relay_seq >= 1)
    srv3.shutdown(); srv3.server_close()
    # old server without epoch/poll: plain since() client still works
    class Old:
        def __init__(self): self.calls = 0
        def since(self, after, wait=0): self.calls += 1; return [{"seq": after + 1}]
    old = Old(); s_old = mkseat(old); s_old._wait()
    check("older client/server without epoch: unchanged behaviour", s_old._relay_seq == 1 and old.calls == 1 and s_old.relay is old)
    # relay=None seat never tries to use a relay
    s_none = mkseat(None); t0 = time.time(); s_none._wait(); check("no relay configured: plain sleep path", s_none.relay is None and time.time() - t0 >= 0.25)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nRELAY RECOVERY:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
raise SystemExit(0 if ok else 1)
