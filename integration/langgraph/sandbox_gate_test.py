"""Offline: the runtime gate. LG_VERIFY_SANDBOX forces python through the
bwrap shim, refuses other executables, and unittest discovery with imports
of repo code works. No provider."""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from launcher import runtime as rt
ok = True
def check(n, c):
    global ok; ok = ok and bool(c); print(("PASS  " if c else "FAIL  ") + n)
os.environ.pop("LG_VERIFY_SANDBOX", None)
check("off: argv unchanged", rt.sandboxed_verify_argv(["python3", "a.py"]) == ["python3", "a.py"])
os.environ["LG_VERIFY_SANDBOX"] = "1"
for bad in (["pytest"], ["test", "-f", "x"], ["true"]):
    try: rt.sandboxed_verify_argv(bad); check("refuse %s" % bad[0], False)
    except rt.SeatError: check("refuse %s" % bad[0], True)
a = rt.sandboxed_verify_argv(["python3", "tests/test_app.py"])
check("routed through shim", a[0].endswith("sandbox/python3"))
d = tempfile.mkdtemp(); os.makedirs(d + "/src"); os.makedirs(d + "/tests")
open(d + "/src/app.py", "w").write("def add(a,b): return a+b\n")
open(d + "/tests/test_app.py", "w").write("import sys,os\nsys.path.insert(0,os.path.join(os.path.dirname(__file__),'..'))\nfrom src.app import add\nassert add(2,3)==5\nprint('ok')\n")
p = subprocess.run(rt.sandboxed_verify_argv(["python3", "tests/test_app.py"]), cwd=d, env=rt._verify_env(), capture_output=True, text=True)
check("repo test imports src and passes under sandbox (rc %s %s)" % (p.returncode, p.stderr[-80:]), p.returncode == 0)
p = subprocess.run(rt.sandboxed_verify_argv(["python3", "-m", "unittest", "discover", "-s", "tests"]), cwd=d, env=rt._verify_env(), capture_output=True, text=True)
check("unittest -m works (rc %s)" % p.returncode, p.returncode in (0,5))
print("\nGATE:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE"); raise SystemExit(0 if ok else 1)
