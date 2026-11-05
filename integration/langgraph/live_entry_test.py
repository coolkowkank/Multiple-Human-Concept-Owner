"""Offline tests for the multi-seat live entry (`langgraph_team.py live`).
A local fake router stands in (HTTP_FREE_BASE patched inside this process
only). No provider, no real key, scripted responses - not model output."""
import os as _os; _os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import contextlib, http.server, io, json, os, shutil, sys, tempfile, threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fenced_http  # noqa: E402
import langgraph_team as lt  # noqa: E402

NEM, LING = "nvidia/nemotron-3-ultra-550b-a55b", "novita/ling-3.1-flash"
POSTS, GETS = [], []
MODE = {"list": "ok"}
KEY = "fake-key-not-real-0123456789"


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        GETS.append((self.path, self.headers.get("authorization")))
        m = MODE["list"]
        if m == "500":
            self.send_response(500); self.end_headers(); return
        if m == "redirect":
            self.send_response(302); self.send_header("location", "http://127.0.0.1:9/x"); self.end_headers(); return
        price = {"nonzero": "0.000001", "missing": None}.get(m, "0")
        rows = [{"id": NEM, "input_price": price, "output_price": price},
                {"id": LING, "input_price": price, "output_price": price}]
        if m == "missing":
            rows = [{"id": NEM}]
        if m == "unlisted":
            rows = [{"id": "other/model", "input_price": 0, "output_price": 0}]
        body = json.dumps({"data": rows}).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", 0)))
        POSTS.append(self.path)
        body = json.dumps({"id": "f", "choices": [{"message": {"content": "not structured"}}],
                           "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0}}).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers(); self.wfile.write(body)


ok = True
def check(name, cond):
    global ok
    ok = ok and bool(cond)
    print(("PASS  " if cond else "FAIL  ") + name, flush=True)


def refused(fn):
    try:
        fn()
    except SystemExit as e:
        return str(e.code) if isinstance(e.code, str) else "exit"
    except BaseException as e:
        return None
    return None


tmp = tempfile.mkdtemp()
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
lt.HTTP_FREE_BASE = "http://127.0.0.1:%d/v1" % srv.server_address[1]
fenced_http.HTTP_LOG_DIR = os.path.join(tmp, "logs")
cdir = os.path.join(tmp, "cfg"); os.makedirs(cdir); os.chmod(cdir, 0o700)
keyf = os.path.join(cdir, "k"); open(keyf, "w").write(KEY + "\n"); os.chmod(keyf, 0o600)
rules = os.path.join(cdir, "rules.md"); open(rules, "w").write("\nREPLY-RULES-MARKER\n"); os.chmod(rules, 0o600)
n = [0]


def lane():
    n[0] += 1
    r, d = os.path.join(tmp, f"lane{n[0]}"), os.path.join(tmp, f"db{n[0]}.sqlite")
    lt.init_repo(r); return r, d


def cfg(**over):
    n[0] += 1
    c = {"key_file": keyf, "brief_extra_file": rules, "stop_after": 1, "preflight": {"allow_fresh": True},
         "seats": {"coordinator": {"model": NEM, "epoch": f"b{n[0]}", "budget": 1, "max_tokens": 100},
                   "reviewer": {"model": LING, "epoch": f"r{n[0]}", "budget": 1, "max_tokens": 100}}}
    c.update(over)
    for k in [k for k, v in c.items() if v is None]: del c[k]
    p = os.path.join(cdir, f"c{n[0]}.json"); open(p, "w").write(json.dumps(c)); os.chmod(p, 0o600)
    return p


def roster(r):
    return open(os.path.join(r, ".team", "roster.json")).read()


def untouched(r, before):
    return roster(r) == before and not POSTS


def attempt(c, r, d):
    del POSTS[:]; del GETS[:]
    before = roster(r)
    msg = refused(lambda: lt.live_entry(r, d, c))
    return msg, untouched(r, before)


try:
    r, d = lane(); msg, clean = attempt(cfg(), r, d) if False else (None, True)
    # refusals before any listing request
    for name, c in [
        ("unknown config key", cfg(extra="x")),
        ("unknown seat", cfg(seats={"nobody": {"model": NEM, "epoch": "x1", "budget": 1}})),
        ("model off the allowlist", cfg(seats={"builder": {"model": "openai/gpt-5", "epoch": "x2", "budget": 1}})),
        ("budget 9", cfg(seats={"builder": {"model": NEM, "epoch": "x3", "budget": 9}})),
        ("extra seat key", cfg(seats={"builder": {"model": NEM, "epoch": "x4", "budget": 1, "base_url": "http://evil"}})),
    ]:
        r, d = lane(); msg, clean = attempt(c, r, d)
        check(f"refused before any request: {name}", msg and "refused" in msg and clean and not GETS)
    r, d = lane(); c = cfg(); os.chmod(c, 0o644)
    msg, clean = attempt(c, r, d); check("config mode 0644 refused", msg and clean and not GETS)
    r, d = lane(); c = os.path.join(r, "inlane.json"); open(c, "w").write(json.dumps({"key_file": keyf, "seats": {}})); os.chmod(c, 0o600)
    msg, clean = attempt(c, r, d); check("config inside the lane refused", msg and clean and not GETS)
    bk = os.path.join(cdir, "k2"); open(bk, "w").write(KEY); os.chmod(bk, 0o644)
    r, d = lane(); msg, clean = attempt(cfg(key_file=bk), r, d); check("key file mode 0644 refused", msg and clean and not GETS)
    r, d = lane(); os.environ.pop("LG_VERIFY_SANDBOX"); msg, clean = attempt(cfg(), r, d); os.environ["LG_VERIFY_SANDBOX"] = "1"
    check("sandbox not ready refused before any request", msg and "sandbox" in msg and clean and not GETS)
    # listing-based refusals: lane untouched, zero POSTs
    for m in ("nonzero", "missing", "unlisted", "500", "redirect"):
        MODE["list"] = m; r, d = lane(); msg, clean = attempt(cfg(), r, d)
        check(f"listing '{m}' refused, roster untouched, zero POSTs", msg and "refused" in msg and clean and len(GETS) == 1)
    # happy path: heterogeneous seats, fresh listing price 0, key in-process only
    MODE["list"] = "ok"; r, d = lane(); c = cfg(); del POSTS[:]; del GETS[:]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            rc = lt.live_entry(r, d, c)
        except BaseException as e:
            rc = "ended:" + type(e).__name__
    out = buf.getvalue()
    ro = json.load(open(os.path.join(r, ".team", "roster.json")))["seats"]
    check("fresh listing requested once with the key as bearer", len(GETS) == 1 and GETS[0][1] == "Bearer " + KEY)
    check("seat models split (coordinator nemotron, reviewer ling)", ro["coordinator"]["adapter"]["model"] == NEM and ro["reviewer"]["adapter"]["model"] == LING)
    check("untouched seats stay mock", all(ro[s]["adapter"].get("type") != "http" for s in ro if s not in ("coordinator", "reviewer")))
    check("requests within the seat budget", 0 < len(POSTS) <= 2)
    check("key never printed, env key removed after the run", KEY not in out and lt.HTTP_KEY_ENV not in os.environ)
    check("listing prices printed as listing, not billing proof", "not billing proof" in out)
    brief = open(os.path.join(r, ".team", "brief.md")).read()
    check("extra reply rules appended once", brief.count("REPLY-RULES-MARKER") == 1)
    check("no key or model text in usage logs", all(KEY not in open(os.path.join(fenced_http.HTTP_LOG_DIR, f)).read() and "not structured" not in open(os.path.join(fenced_http.HTTP_LOG_DIR, f)).read() for f in os.listdir(fenced_http.HTTP_LOG_DIR)))
    # idempotent re-entry: no duplicate rules
    before = len(POSTS)
    with contextlib.redirect_stdout(io.StringIO()):
        try: lt.live_entry(r, d, c)
        except BaseException: pass
    brief = open(os.path.join(r, ".team", "brief.md")).read()
    check("re-entry does not duplicate the rules", brief.count("REPLY-RULES-MARKER") == 1)

    # ---- reserve preflight integration ----
    # (the happy-path lane above created real fenced logs under HTTP_LOG_DIR)
    import reserve_preflight as rp
    base = rp.preflight(0)
    check("fenced created the log dir private (0700)", (os.stat(fenced_http.HTTP_LOG_DIR).st_mode & 0o077) == 0)
    check("preflight sees the reserves the first run made", base["status"] == "ok_to_plan" and base["reserves_total"] >= 1)
    anchor_f = os.path.join(cdir, "anchor.json"); open(anchor_f, "w").write(json.dumps(rp.snapshot(base))); os.chmod(anchor_f, 0o600)
    # existing ledger + no fresh assertion: allowed
    MODE["list"] = "ok"; r2, d2 = lane(); del POSTS[:]; del GETS[:]
    c2 = cfg(preflight={"anchor_file": anchor_f, "expected_min_reserves": base["reserves_total"]})
    with contextlib.redirect_stdout(io.StringIO()):
        try: lt.live_entry(r2, d2, c2)
        except SystemExit as e: print("EXIT", e)
        except BaseException: pass
    check("verified ledger + anchor + min reserves: proceeds to the listing", len(GETS) == 1)
    # planned over the remaining cap: refused before any request
    r3, d3 = lane(); big = {"coordinator": {"model": NEM, "epoch": "o1", "budget": 8}, "reviewer": {"model": LING, "epoch": "o2", "budget": 8}}
    msg, clean = attempt(cfg(seats=big, preflight={"anchor_file": anchor_f}), r3, d3)
    check("planned calls over the remaining lifetime cap refused, lane untouched, no request", msg and "over_cap" in msg and clean and not GETS)
    # missing ledger without a fresh assertion: unestablished -> refused
    saved = fenced_http.HTTP_LOG_DIR; fenced_http.HTTP_LOG_DIR = os.path.join(tmp, "nologs")
    r4, d4 = lane(); msg, clean = attempt(cfg(preflight={}), r4, d4)
    check("no ledger and no fresh assertion: unestablished, refused, no request", msg and "unestablished" in msg and clean and not GETS)
    r4b, d4b = lane(); msg, clean = attempt(cfg(preflight={"expected_min_reserves": 7}), r4b, d4b)
    check("expected_min_reserves with a missing ledger: refused", msg and clean and not GETS)
    fenced_http.HTTP_LOG_DIR = saved
    # tail truncation of a log is caught by the anchor
    lf = os.path.join(saved, sorted(os.listdir(saved))[0]); lines = open(lf).read().splitlines(True)
    open(lf, "w").write("".join(lines[:-1]))
    r5, d5 = lane(); msg, clean = attempt(cfg(preflight={"anchor_file": anchor_f}), r5, d5)
    check("truncated log vs anchor refused, no request", msg and "refuse" in msg and clean and not GETS)
    open(lf, "w").write("".join(lines))
    # bad preflight config values
    r6, d6 = lane(); msg, clean = attempt(cfg(preflight={"allow_fresh": "yes"}), r6, d6); check("allow_fresh must be a bool", msg and clean)
    r7, d7 = lane(); msg, clean = attempt(cfg(preflight={"surprise": 1}), r7, d7); check("unknown preflight key refused", msg and clean)
finally:
    srv.shutdown(); shutil.rmtree(tmp, ignore_errors=True)
print("\nLIVE ENTRY TESTS:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
raise SystemExit(0 if ok else 1)
