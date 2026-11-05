"""Offline test: the shim blocks network, host files and env, and runs
a normal test. Run from the repo dir. No provider."""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
SHIM = os.path.join(HERE, "sandbox")
ok = True
def check(n, c):
    global ok; ok = ok and bool(c); print(("PASS  " if c else "FAIL  ") + n)
d = tempfile.mkdtemp()
open(os.path.join(d, "good.py"), "w").write("assert 2+3==5\nprint('ok')\n")
open(os.path.join(d, "evil.py"), "w").write("""
import os, socket, sys
res = []
res.append(os.path.exists('/home'))
res.append(os.path.exists('/downloads'))
res.append(os.path.exists('/tmp/src'))
res.append(bool(os.environ.get('SECRET_PROBE')))
try:
    socket.create_connection(('1.1.1.1', 53), 2); res.append(True)
except OSError: res.append(False)
try:
    open('/work/x', 'w'); res.append(True)
except OSError: res.append(False)
print('LEAK' if any(res) else 'CLEAN', res)
""")
env = dict(os.environ, PATH=SHIM + ":" + os.environ["PATH"], SECRET_PROBE="s3cret")
r = subprocess.run(["python3", "good.py"], cwd=d, env=env, capture_output=True, text=True)
check("normal test runs under shim (rc %s)" % r.returncode, r.returncode == 0 and "ok" in r.stdout)
r = subprocess.run(["python3", "evil.py"], cwd=d, env=env, capture_output=True, text=True)
check("hostile probe sees nothing: " + r.stdout.strip(), "CLEAN" in r.stdout)
open(os.path.join(d, "loop.py"), "w").write("while True: pass\n")
import time; t = time.time()
r = subprocess.run(["python3", "loop.py"], cwd=d, env=env, capture_output=True, text=True, timeout=60)
check("CPU limit stops a busy loop (%.0fs, rc %s)" % (time.time() - t, r.returncode), r.returncode != 0 and time.time() - t < 40)
print("\nSANDBOX SHIM:", "ALL CHECKS PASSED" if ok else "FAILURES ABOVE"); raise SystemExit(0 if ok else 1)
