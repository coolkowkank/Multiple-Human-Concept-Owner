"""Bundle/restore offline fault tests (temp dirs, synthetic data)."""
import hashlib, io, os, secrets, shutil, sys, tarfile, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fenced_http as fh, ledger_restore as lr
FAIL = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: FAIL.append(n)
def refused(f):
    try: f(); return False
    except lr.RestoreRefused: return True
tmp = tempfile.mkdtemp(); os.environ["WK"] = "x"
S = os.path.join(tmp, "src"); os.makedirs(S, mode=0o700); fh.HTTP_LOG_DIR = S
H = lambda s: hashlib.sha256(s.encode()).hexdigest()
fh.import_historic_floor(S, 4, 1, 3, ["old-model.o1.jsonl"])
fh.open_window(S, 3, secrets.token_hex(32), H("c"), H("r1"), "0")
a = fh.FencedHttpAdapter("http://127.0.0.1:1", "m-a", "WK", "e1", 9, 16, 1, None); a.reserve(); a.reserve()
raw, sha = lr.bundle(S)
raw2, sha2 = lr.bundle(S)
check("bundle deterministic", raw == raw2 and sha == sha2)
args = dict(expected_sha256=sha, expected_receipt_hash=H("r1"), expected_seq=1, expected_total=6)
D = os.path.join(tmp, "d1"); info = lr.restore(raw, D, **args)
check("good restore: window usable, 1 left, mode 0700", info["used"] == 2 and info["k"] == 3 and os.stat(D).st_mode & 0o777 == 0o700
      and fh._read_all(D) == (6, False, True))
check("restore into non-empty dir refused", refused(lambda: lr.restore(raw, D, **args)))
def bad(**kw):
    a2 = dict(args); a2.update(kw); d = os.path.join(tmp, "x" + secrets.token_hex(3))
    r = refused(lambda: lr.restore(kw.pop("_raw", raw) if False else raw, d, **a2)); return r and not os.path.exists(d)
check("wrong sha refused, nothing left", bad(expected_sha256=H("z")))
check("older receipt (rollback to earlier bundle) refused", bad(expected_receipt_hash=H("r0")))
check("wrong seq refused", bad(expected_seq=2))
check("total mismatch (rolled back / extra) refused", bad(expected_total=5) and bad(expected_total=7))
# tampered bundle with matching claimed sha: truncated log
def retar(mut):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as t:
        for fn in sorted(os.listdir(S)):
            data = open(os.path.join(S, fn), "rb").read(); data = mut(fn, data)
            if data is None: continue
            ti = tarfile.TarInfo(fn); ti.size = len(data); t.addfile(ti, io.BytesIO(data))
    r = out.getvalue(); return r, hashlib.sha256(r).hexdigest()
tr, ts = retar(lambda fn, d: d[:d.rfind(b"\n", 0, len(d) - 1) + 1] if fn.endswith(".jsonl") else d)
check("log truncated inside bundle refused even with matching sha", refused(lambda: lr.restore(tr, os.path.join(tmp, "t1"), **dict(args, expected_sha256=ts))))
tr, ts = retar(lambda fn, d: None if fn == "_control.ctl" else d)
check("bundle without control refused", refused(lambda: lr.restore(tr, os.path.join(tmp, "t2"), **dict(args, expected_sha256=ts))))
out = io.BytesIO()
with tarfile.open(fileobj=out, mode="w") as t:
    ti = tarfile.TarInfo("../evil.jsonl"); ti.size = 1; t.addfile(ti, io.BytesIO(b"x"))
r = out.getvalue()
check("path-escape member refused", refused(lambda: lr.restore(r, os.path.join(tmp, "t3"), **dict(args, expected_sha256=hashlib.sha256(r).hexdigest()))) and not os.path.exists(os.path.join(tmp, "evil.jsonl")))
out = io.BytesIO()
with tarfile.open(fileobj=out, mode="w") as t:
    ti = tarfile.TarInfo("a.b.jsonl"); ti.type = tarfile.SYMTYPE; ti.linkname = "/etc/passwd"; t.addfile(ti)
r = out.getvalue()
check("symlink member refused", refused(lambda: lr.restore(r, os.path.join(tmp, "t4"), **dict(args, expected_sha256=hashlib.sha256(r).hexdigest()))))
check("bundle refuses unexpected file in source dir", (lambda: (open(os.path.join(S, "notes.txt"), "w").write("x"), refused(lambda: lr.bundle(S)))[1])())
shutil.rmtree(tmp)
print("FAILED" if FAIL else "ALL PASS"); sys.exit(1 if FAIL else 0)
