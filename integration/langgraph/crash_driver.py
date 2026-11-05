import os, sys, signal
os.environ.setdefault("LG_VERIFY_SANDBOX", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import langgraph_team as lt
from launcher.bus import Bus
from launcher import runtime
from launcher.runtime import Seat
repo, point, mode = sys.argv[1], sys.argv[2], sys.argv[3]
seat = sys.argv[4] if len(sys.argv) > 4 else "coordinator"
b = Bus(repo, lt.BRANCH)
s = Seat(b, seat, poll_interval=1)
orig = s._call_adapter
def call(state):
    r = orig(state)
    r = dict(r); r["writes"] = {".team/NOTE.md": "n\n", ".team/chk.py": "pass\n"}; r["verify_command"] = "python3 .team/chk.py"
    return r
s._call_adapter = call
def die(*a, **k): os.kill(os.getpid(), signal.SIGKILL)
if mode == "crash":
    if point == "before_call": s._call_adapter = die
    elif point == "before_commit": b.commit_all = die
    elif point == "after_commit":
        real = b.commit_all
        def ca(m):
            real(m); die()
        b.commit_all = ca
    elif point == "during_verify":
        real_run = runtime.subprocess.run
        def run(argv, *a, **k):
            if any(str(x).endswith("chk.py") for x in (argv if isinstance(argv,(list,tuple)) else [argv])): die()
            return real_run(argv, *a, **k)
        runtime.subprocess.run = run
try: print("RESULT acted=%s" % s.act_once())
except BaseException as e: print("RESULT error=%s: %s" % (type(e).__name__, str(e)[:300]))
