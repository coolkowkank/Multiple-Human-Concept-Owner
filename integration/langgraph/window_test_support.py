"""Test helper: make the current process look like the wrapper's live run for a window
(held lock file + run-bind + env run id). Offline tests only."""
import fcntl, os, secrets, tempfile
import fenced_http as fh
_HELD = []
def bind_live_run(dirpath):
    w = fh.read_control(dirpath)["windows"][-1]
    d = tempfile.mkdtemp(); p = os.path.join(d, "lock")
    fd = os.open(p, os.O_RDWR | os.O_CREAT, 0o600); fcntl.flock(fd, fcntl.LOCK_EX); _HELD.append(fd)
    rid = secrets.token_hex(8); os.environ[fh.RUN_ID_ENV] = rid
    fh.bind_run(dirpath, w["nonce"], rid, p)
    return fd, p
