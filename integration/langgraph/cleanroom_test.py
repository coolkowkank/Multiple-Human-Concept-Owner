"""Clean-room install-and-run proof: a pristine export of THIS commit,
a fresh venv, the documented commands, a fake HOME - and the team cycle
must complete with every check green.

Proves the repo "installs and runs" end to end with no keys and no model
calls: the only network step is pip installing the two pinned public
packages from requirements.txt (PyPI). No provider IO, no window, no
ledger writes outside the scratch HOME, no secrets.

Covers (exactly the OPERATOR_GUIDE offline sequence plus the stdlib demo):
  python -m launcher demo                          (stdlib-only full cycle)
  langgraph_team.py init lane-a / run lane-a 2     (graceful bounded stop)
  langgraph_team.py init lane-b / lane-c
  parallel_team.py                                 (3-lane parent graph)
  controls_demo.py                                 (pause/update/resume/assign)
"""
import os, subprocess, sys, tempfile, venv

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = subprocess.run(["git", "-C", HERE, "rev-parse", "--show-toplevel"],
                      capture_output=True, text=True).stdout.strip()
FAIL = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: FAIL.append(n)

def run(argv, cwd, env, timeout=240):
    r = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout + r.stderr

tmp = tempfile.mkdtemp(prefix="cleanroom-")
src = os.path.join(tmp, "src"); os.makedirs(src)
r = subprocess.run(["git", "-C", REPO, "archive", "HEAD"], capture_output=True)
check("git archive HEAD", r.returncode == 0 and len(r.stdout) > 1000)
open(os.path.join(tmp, "head.tar"), "wb").write(r.stdout)
subprocess.run(["tar", "-x", "-C", src, "-f", os.path.join(tmp, "head.tar")], check=True)
lg = os.path.join(src, "integration", "langgraph")
check("pristine export carries the harness + requirements.txt",
      os.path.isfile(os.path.join(lg, "langgraph_team.py"))
      and os.path.isfile(os.path.join(lg, "requirements.txt")))

venv_dir = os.path.join(tmp, "venv")
venv.create(venv_dir, with_pip=True)
vp = os.path.join(venv_dir, "bin", "python")
rc, out = run([vp, "-m", "pip", "install", "--quiet", "-r",
               os.path.join(lg, "requirements.txt")], lg, os.environ.copy())
check("venv pip install -r requirements.txt (the only network step)", rc == 0)

home = os.path.join(tmp, "home"); os.makedirs(home)
env = dict(os.environ); env["HOME"] = home; env["LG_VERIFY_SANDBOX"] = "1"

scratch = os.path.join(tmp, "scratch")
rc, out = run([vp, "-m", "launcher", "demo", "--dir", os.path.join(scratch, "demo-launcher")], lg, env)
check("stdlib demo: full team cycle, no deps", rc == 0 and "all checks passed" in out)

demo = os.path.join(scratch, "demo")
ok = True
for lane in ("a", "b", "c"):
    rc, out = run([vp, "langgraph_team.py", "init", os.path.join(demo, "lane-" + lane),
                   os.path.join(demo, "db-" + lane + ".sqlite")], lg, env)
    ok = ok and rc == 0
check("init lanes a/b/c", ok)
rc, out = run([vp, "langgraph_team.py", "run", os.path.join(demo, "lane-a"),
               os.path.join(demo, "db-a.sqlite"), "2", "team-demo-a"], lg, env)
check("run lane-a stops gracefully after 2 seat actions",
      rc == 0 and "stopped gracefully after 2 seat actions" in out)
rc, out = run([vp, "parallel_team.py", demo], lg, env)
check("parallel 3-lane parent graph: all checks passed",
      rc == 0 and "PARALLEL RUN: ALL CHECKS PASSED" in out)
rc, out = run([vp, "controls_demo.py", os.path.join(scratch, "controls")], lg, env)
check("controls demo (pause/update/resume/assign): all checks passed",
      rc == 0 and "CONTROLS DEMO: ALL CHECKS PASSED" in out)

led = os.path.join(home, ".lg-http-usage")
check("no provider ledger written under the fake HOME (no model calls happened)",
      not os.path.exists(led) or not open(os.path.join(led, "_control.ctl")).read().strip())
print("FAILED" if FAIL else "ALL PASS")
sys.exit(1 if FAIL else 0)
