"""Offline: write-path boundary. Allow check and write use ONE canonical
relative path; absolute/backslash/control/traversal/empty-segment keys and
symlink escapes are refused BEFORE any write. Scratch dirs only: a sentinel
directory OUTSIDE the lane must stay empty; the lane's HEAD/worktree must not
change on refusal."""
import os as _os; _os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
import os, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import langgraph_team as lt  # noqa: E402
from launcher.bus import Bus  # noqa: E402
from launcher.runtime import Seat, SeatError  # noqa: E402
ok = True
def check(n, c):
    global ok; ok = ok and bool(c); print(("PASS  " if c else "FAIL  ") + n, flush=True)
def git(r, *a): return subprocess.run(["git", "-C", r, *a], capture_output=True, text=True).stdout.strip()
tmp = tempfile.mkdtemp()
try:
    outside = os.path.join(tmp, "outside"); os.makedirs(outside)
    def lane(name):
        r = os.path.join(tmp, name); lt.init_repo(r)
        b = Bus(r, lt.BRANCH); s = Seat(b, "coordinator", instance_id="A"); s.adapter.consume = lambda: None
        s.allowed_paths = ["src", ".team"]
        os.makedirs(os.path.join(r, "src"), exist_ok=True)
        subprocess.run(["git", "-C", r, "add", "-A"], capture_output=True); subprocess.run(["git", "-C", r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "src"], capture_output=True) if git(r, "status", "--porcelain") else None
        return r, b, s
    def attempt(name, writes, setup=None):
        r, b, s = lane(name)
        if setup: setup(r)
        resp = {"summary": "x", "writes": writes, "verify_command": None, "handoff": "builder", "status_line": "s"}
        s._call_adapter = lambda state: dict(resp)
        h, st0 = git(r, "rev-parse", "HEAD"), b.state(); dirty0 = git(r, "status", "--porcelain")
        try: s.act_once(); err = None
        except SeatError as e: err = str(e)
        except Exception as e: err = "CRASH " + repr(e)
        clean = git(r, "rev-parse", "HEAD") == h and b.state() == st0 and git(r, "status", "--porcelain") == dirty0
        return r, b, err, clean
    leaked = lambda: os.listdir(outside)
    bad = {"absolute into outside dir": os.path.join(outside, "x"), "absolute /src/x": "/src/x", "backslash rootfile": "src\\x", "leading backslash": "\\x",
           "dotdot": "src/../x", "dotdot twice": "src/../../outside/x", "empty segment": "src//x", "trailing slash": "src/", "dot segment": "src/./x",
           "dot lead": "./src/x", "newline": "src/a\nb", "NUL": "src/a\x00b", "tab": "src/a\tb", ".git component": ".git/hooks/x", "nested .git config": "src/.git/config", "nested .GIT": "src/sub/.GIT/hooks/x", ".git as a file name": "src/.git", "not allowed root": "other/x", "empty": ""}
    for nm, path in bad.items():
        r, b, err, clean = attempt("b-" + str(abs(hash(nm))), {path: "pwn\n"})
        check(f"{nm}: refused with a clean SeatError, no crash, HEAD/state/worktree unchanged, nothing outside", err and "CRASH" not in err and clean and leaked() == [])
    # file-and-directory conflict in one batch
    r, b, err, clean = attempt("fd", {"src/a": "1", "src/a/b": "2"})
    check("a file and a path under it in one batch: refused before any write", err and "CRASH" not in err and clean)
    # symlink escapes
    r, b, err, clean = attempt("s1", {"src/link/x": "pwn\n"}, setup=lambda r: os.symlink(outside, os.path.join(r, "src", "link")))
    check("symlinked directory component: refused, nothing written outside", err and "CRASH" not in err and leaked() == [] and clean)
    open(os.path.join(outside, "target"), "w").write("orig\n")
    r, b, err, clean = attempt("s2", {"src/f": "pwn\n"}, setup=lambda r: os.symlink(os.path.join(outside, "target"), os.path.join(r, "src", "f")))
    check("symlinked final file: refused, outside file unchanged", err and "CRASH" not in err and open(os.path.join(outside, "target")).read() == "orig\n" and clean)
    def whole(r):
        shutil.rmtree(os.path.join(r, "src")); os.symlink(outside, os.path.join(r, "src"))
    r, b, err, clean = attempt("s3", {"src/x": "pwn\n"}, setup=whole)
    check("allowed root itself a symlink to outside: refused, outside empty of x", err and "CRASH" not in err and "x" not in leaked())
    r, b, err, clean = attempt("dots", {".team/.hidden": "h\n", ".team/a.gitignore": "x\n", ".team/.github/w.yml": "y\n"})
    check("ordinary dotfiles (.hidden, a.gitignore, .github/) are still allowed", err is None and os.path.exists(os.path.join(r, ".team/.github/w.yml")))
    for nm, pth in (("mixed-case .Git", "src/.Git/x"), ("existing dir as target", "src/adir")):
        r, b, err, clean = attempt("k-" + nm.split()[0], {pth: "x"}, setup=lambda r: os.makedirs(os.path.join(r, "src", "adir"), exist_ok=True))
        check(f"{nm}: refused before any write", err and "CRASH" not in err and clean)
    r, b, err, clean = attempt("anc", {"src/ok": "1\n", "src/existingfile/b": "2\n"}, setup=lambda r: open(os.path.join(r, "src", "existingfile"), "w").write("f\n"))
    check("write under an EXISTING FILE ancestor: refused before ANY write; src/ok is not left behind", err and "CRASH" not in err and clean and not os.path.exists(os.path.join(r, "src", "ok")))
    # legitimate paths preserved
    r, b, err, clean = attempt("ok", {".team/a/b.md": "pass\n", ".team/NOTE.md": "n\n"})
    check("legitimate nested and .team writes still applied and committed", err is None and open(os.path.join(r, ".team/a/b.md")).read() == "pass\n" and git(r, "status", "--porcelain") == "" and leaked() == ["target"])
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nPATH BOUNDARY:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE")
raise SystemExit(0 if ok else 1)
