"""Scratch-only path-boundary probe for Seat._path_allowed + Seat._write.
Everything lives under one temp dir (repo, an 'outside' dir, a 'dom' sibling of repo); the absolute-path
case targets that temp dir, never a real path. A case PASSES if, after running the exact allow-then-write
sequence the runtime uses (allowed -> _write), nothing outside <repo>/src changed. Refusing (allowed False,
or _write raising) also passes. Exit 1 if any gap. No provider, no process, no network."""
import os, sys, tempfile, shutil, hashlib
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
from launcher.runtime import Seat  # noqa: E402

def snapshot(root, skip):
    snap = {}
    for dp, dns, fns in os.walk(root, followlinks=False):
        if os.path.realpath(dp) == os.path.realpath(skip) or os.path.realpath(dp).startswith(os.path.realpath(skip) + os.sep):
            dns[:] = []; continue
        for n in fns + dns:
            p = os.path.join(dp, n)
            if os.path.islink(p): snap[p] = ("link", os.readlink(p))
            elif os.path.isfile(p): snap[p] = ("file", hashlib.sha256(open(p, "rb").read()).hexdigest())
            else: snap[p] = ("dir",)
    return snap

tmp = os.path.realpath(tempfile.mkdtemp())
try:
    repo = os.path.join(tmp, "repo"); src = os.path.join(repo, "src"); out = os.path.join(tmp, "outside"); dom = os.path.join(tmp, "dom")
    for d in (src, out, dom, os.path.join(repo, "other")): os.makedirs(d)
    open(os.path.join(tmp, "escape.txt"), "w").write("orig")
    os.symlink(out, os.path.join(src, "lnk"))                       # dir symlink out of the repo
    os.symlink(os.path.join(repo, "other"), os.path.join(src, "lnk2"))   # dir symlink to in-repo, out of domain
    os.symlink("../../escape.txt", os.path.join(src, "flink"))      # FILE symlink out of the repo
    import types; s = Seat.__new__(Seat); s.bus = types.SimpleNamespace(repo=repo); s.allowed_paths = ["src", os.path.join(tmp, "dom").lstrip("/")]
    cases = [("plain in-domain", "src/ok.txt", True), ("leading slash", "/src/abs.txt", False),
             ("absolute path of a scratch sibling dir", "/" + os.path.join(tmp, "dom").lstrip("/") + "/abs.txt", False),
             ("double leading slash", "//src/x.txt", False), ("backslash separators", "src\\bs.txt", False),
             ("leading backslash", "\\src\\bs2.txt", False), ("dir symlink out of repo", "src/lnk/pwn.txt", False),
             ("dir symlink to in-repo, out of domain", "src/lnk2/pwn2.txt", False), ("file symlink out of repo", "src/flink", False),
             ("dotdot", "src/../x.txt", False), ("dotdot with backslash", "src\\..\\x.txt", False), ("NUL byte", "src/a\x00b", False)]
    gaps = 0
    for label, p, benign in cases:
        before = snapshot(tmp, src); esc = open(os.path.join(tmp, "escape.txt")).read()
        how = "refused"
        try:
            if s._path_allowed(p):
                try: s._write(repo, p, "PAYLOAD"); how = "written"
                except Exception as e: how = f"write raised {type(e).__name__}"
        except Exception as e: how = f"allow raised {type(e).__name__}"
        after = snapshot(tmp, src); esc2 = open(os.path.join(tmp, "escape.txt")).read()
        changed = sorted(set(after) ^ set(before) | {k for k in before if k in after and before[k] != after[k]})
        bad = bool(changed) or esc != esc2 or how.startswith("allow raised") or (benign and how != "written")
        gaps += bad
        if benign and how == "written":
            os.remove(p_ok := os.path.join(repo, p))
        rel = [os.path.relpath(c, tmp) for c in changed] + (["escape.txt(content)"] if esc != esc2 else [])
        print(("GAP   " if bad else "PASS  ") + f"{label}: {how}" + (f" -> changed outside src: {rel}" if bad else ""), flush=True)
        for c in changed:
            if os.path.isfile(c) and not os.path.islink(c) and os.path.realpath(c).startswith(tmp): os.remove(c)
        open(os.path.join(tmp, "escape.txt"), "w").write("orig")
    print(f"\nPATH BOUNDARY: gaps={gaps}")
    raise SystemExit(1 if gaps else 0)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
