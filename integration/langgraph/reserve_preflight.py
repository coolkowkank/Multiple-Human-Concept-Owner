"""Read-only preflight over the Fenced HTTP reserve/result logs.

Fenced (fenced_http.py) OWNS atomic reservation: it writes the durable reserve
line under flock before each request and enforces the lifetime cap. This module
only READS the same logs and answers "may an operator plan N more calls?" before
a live run. It never writes, locks for writing, creates the log directory,
resets, clones, or repairs anything, and it is not a second writer or a budget.
usage_join is unrelated: provider-reported usage is not a budget input.

What it can and cannot establish (kept honest, not a durable-ledger claim):
- It counts 'reserve' lines (each is a spent attempt, even with no 'result').
- It verifies the sha256 prev-chain, line shapes, n sequence, filename/model
  agreement, result-without-reserve, duplicate n, halt lines, symlinks, odd
  file types, and that the dir is owned by this user with no group/other access.
- A MISSING or EMPTY log dir is 'unestablished': it looks identical to a first
  run, a deleted ledger, or a changed HOME. It is never reported as zero spent
  unless the operator passes allow_fresh=True (an operator statement, not proof).
- Tail truncation and wholesale replacement of the dir are NOT detectable from
  the logs alone. With an operator-held anchor (snapshot() output stored OUTSIDE
  the log dir) a log shorter than, or diverging from, the anchor is refused.
  The anchor is same-user storage too: it raises the bar, it does not make the
  ledger tamper-proof.
- A LOCK_SH|LOCK_NB probe reports whether another writer holds a log now. It is
  advisory. Concurrent lifetime-cap behaviour across processes is Fenced's
  concern (each adapter locks only its own file, so two different model/epoch
  logs can pass the cap check at the same time); this module flags that gap and
  does not patch it.
"""
import fcntl
import hashlib
import json
import math
import os
import pwd
import re
import stat

SCHEMA = "reserve-preflight/v1"
_SLUG_EPOCH = re.compile(r"^[a-z0-9-]+\.[a-z0-9-]{1,32}\.jsonl$")
_MAX_LOG_BYTES = 4 * 1024 * 1024
_MAX_FILES = 200
_PHASES = ("reserve", "result", "halt")


def _defaults():
    # Read-only import of the constants Fenced already defines; no calls made.
    import fenced_http
    return fenced_http.HTTP_LOG_DIR, fenced_http.HTTP_LIFETIME_CAP


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _scan_log(path, fname):
    """Parse one log read-only. Returns (facts, problems)."""
    problems = []
    f = {"file": fname, "lines": 0, "reserves": 0, "results": 0, "halts": 0,
         "unmatched_reserves": 0, "tip_sha256": "0", "line_hashes": [], "writer_active": None}
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode):
            return f, ["not a regular file (symlink or special): " + fname]
        if st.st_size > _MAX_LOG_BYTES:
            return f, ["log too large to verify: " + fname]
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        return f, ["cannot open %s: %s" % (fname, exc.__class__.__name__)]
    with os.fdopen(fd, "rb") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_SH | fcntl.LOCK_NB)
            f["writer_active"] = False
            fcntl.flock(fh, fcntl.LOCK_UN)
        except OSError:
            f["writer_active"] = True
        data = fh.read()
    if data and not data.endswith(b"\n"):
        problems.append("partial last line (no newline): " + fname)
    prev, reserved, resulted, seen_n = "0", set(), set(), set()
    for raw in data.split(b"\n"):
        if not raw.strip():
            continue
        f["lines"] += 1
        try:
            e = json.loads(raw)
        except ValueError:
            problems.append("non-JSON line %d in %s" % (f["lines"], fname)); e = None
        if isinstance(e, dict):
            if e.get("prev") != prev:
                problems.append("chain broken at line %d in %s" % (f["lines"], fname))
            ph, n = e.get("phase"), e.get("n")
            if ph not in _PHASES:
                problems.append("unknown phase at line %d in %s" % (f["lines"], fname))
            if ph in ("reserve", "result") and not (isinstance(n, int) and not isinstance(n, bool) and n >= 1):
                problems.append("bad n at line %d in %s" % (f["lines"], fname))
            elif ph == "reserve":
                if n in reserved:
                    problems.append("duplicate reserve n=%s in %s" % (n, fname))
                if n != len(reserved) + 1:
                    problems.append("reserve n=%s out of sequence in %s" % (n, fname))
                reserved.add(n); f["reserves"] += 1
            elif ph == "result":
                if n not in reserved:
                    problems.append("result n=%s without a prior reserve in %s" % (n, fname))
                if n in resulted:
                    problems.append("duplicate result n=%s in %s" % (n, fname))
                resulted.add(n); f["results"] += 1
            elif ph == "halt":
                f["halts"] += 1
            if ph in ("reserve", "result"):
                m = e.get("model")
                slug = re.sub(r"[^a-z0-9]+", "-", str(m).lower()).strip("-") if isinstance(m, str) else None
                if slug is None or not fname.startswith(slug + "."):
                    problems.append("model does not match log name at line %d in %s" % (f["lines"], fname))
            u = e.get("usage")
            if ph == "result" and u is not None:
                if not isinstance(u, dict) or any(
                        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
                        for v in u.values()):
                    problems.append("malformed usage numbers at line %d in %s" % (f["lines"], fname))
        elif e is not None:
            problems.append("non-object line %d in %s" % (f["lines"], fname))
        prev = _sha(raw.rstrip(b"\n"))
        f["line_hashes"].append(prev)
    f["tip_sha256"] = prev
    f["unmatched_reserves"] = len(reserved - resulted)
    return f, problems


def _check_dir(d):
    probs = []
    try:
        st = os.lstat(d)
    except OSError:
        return None
    if stat.S_ISLNK(st.st_mode):
        probs.append("log dir is a symlink")
        st = os.stat(d)
    if not stat.S_ISDIR(st.st_mode):
        probs.append("log path is not a directory"); return probs
    if st.st_uid != os.getuid():
        probs.append("log dir is not owned by this user")
    if st.st_mode & 0o077:
        probs.append("log dir is accessible to group/other (mode %o)" % (st.st_mode & 0o777))
    return probs


def snapshot(preflight_result):
    """Operator-side anchor to store OUTSIDE the log dir: per file, line count and
    chain tip. Only taken from a result with status ok_to_plan/over_cap (verified
    logs); anything else returns None. Fed back as anchor= to detect tail
    truncation or rewritten history."""
    if preflight_result.get("status") not in ("ok_to_plan", "over_cap"):
        return None
    return {"schema": SCHEMA, "reserves": preflight_result.get("reserves_total"),
            "files": {x["file"]: {"lines": x["lines"], "tip_sha256": x["tip_sha256"]}
                      for x in preflight_result.get("files", [])}}


_EPOCH_RE = re.compile(r"^[a-z0-9-]{1,32}$")
HTTP_MAX_BUDGET = 8      # source: langgraph_team.HTTP_MAX_BUDGET


def live_epoch_budgets(cfg_seats, roster_seats, *, strict=False):
    """({'slug.epoch.jsonl': lifetime budget}, None) or (None, problem).

    The single shared computation of what langgraph_team.live_entry will
    configure and what the wrapper gates on: every configured seat
    (model, epoch, budget; the config OVERRIDES the roster entry, exactly as
    live_entry rewrites it) plus every OTHER http seat already in the roster
    at its roster budget. No guessing: a seat that cannot be read, a bad
    budget (not an int in 1..8), a malformed epoch, or two seats sharing one
    log file returns a problem and never an undercount. strict=True (the
    wrapper) also refuses roster seats whose adapter type is neither
    http/mock/queue (a cli adapter is an unbounded spend path)."""
    out = {}

    def add(name, model, epoch, budget):
        if not (isinstance(model, str) and model and isinstance(epoch, str) and _EPOCH_RE.match(epoch)):
            return "seat %r has a malformed model/epoch" % (name,)
        if not (isinstance(budget, int) and not isinstance(budget, bool) and 1 <= budget <= HTTP_MAX_BUDGET):
            return "seat %r budget is not an int in 1..%d" % (name, HTTP_MAX_BUDGET)
        slug = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")
        fn = "%s.%s.jsonl" % (slug, epoch)
        if fn in out:
            return "seats share log file %s; budget is ambiguous" % fn
        out[fn] = budget
        return None
    if not isinstance(cfg_seats, dict) or not isinstance(roster_seats, dict):
        return None, "seats must be objects"
    for name, sc in cfg_seats.items():
        if not isinstance(sc, dict):
            return None, "configured seat %r is not an object" % (name,)
        why = add(name, sc.get("model"), sc.get("epoch"), sc.get("budget"))
        if why:
            return None, why
    for name, rs in roster_seats.items():
        if name in cfg_seats:
            continue
        ad = rs.get("adapter") if isinstance(rs, dict) else None
        if not isinstance(ad, dict):
            return None, "roster seat %r has no adapter object" % (name,)
        kind = ad.get("type", "mock")
        if kind in ("mock", "queue"):
            continue
        if kind != "http":
            if strict:
                return None, "roster seat %r adapter type %r is not covered" % (name, kind)
            continue
        why = add(name, ad.get("model"), ad.get("log_epoch"), ad.get("call_budget"))
        if why:
            return None, why
    return out, None


def _needed(planned_calls, epoch_budgets, files):
    """Calls the plan can still make. Without epoch_budgets: planned_calls
    unchanged. With epoch_budgets ({'slug.epoch.jsonl': lifetime budget}):
    per file max(0, budget - reserves already recorded in that file), summed.
    Fenced's call_budget is a LIFETIME count per model+epoch, so a resume that
    reuses the same epochs must not be charged again for reserves already
    spent in them. Reserves in files not named in epoch_budgets are not
    credited. Never lowers what the global cap check sees below real demand."""
    if epoch_budgets is None:
        return planned_calls
    used = {x["file"]: x["reserves"] for x in files}
    return sum(max(0, b - used.get(fn, 0)) for fn, b in epoch_budgets.items())


def _check_budgets(eb):
    if eb is None:
        return None
    if not isinstance(eb, dict) or not eb:
        return "epoch_budgets must be a non-empty dict"
    for fn, b in eb.items():
        if not (isinstance(fn, str) and _SLUG_EPOCH.match(fn)):
            return "epoch_budgets key is not a slug.epoch.jsonl name: %r" % (fn,)
        if not (isinstance(b, int) and not isinstance(b, bool) and b >= 0):
            return "epoch_budgets value must be a non-negative int: %r" % (fn,)
    return None


def preflight(planned_calls, *, log_dir=None, cap=None, anchor=None, allow_fresh=False,
              expected_min_reserves=None, epoch_budgets=None):
    """Read-only. Returns a dict; status is one of:
      ok_to_plan      logs verify, planned_calls <= remaining (still not a reservation)
      over_cap        verified, but planned_calls > remaining
      refuse          integrity problem, halt line, anchor mismatch, or unsafe dir
      unestablished   no log dir / no logs and allow_fresh not set (cannot tell
                      first run from deleted ledger or changed HOME)
    Never raises on bad input; unknown always degrades to refuse/unestablished."""
    out = {"schema": SCHEMA, "status": "refuse", "planned_calls": planned_calls, "problems": [],
           "files": [], "reserves_total": None, "remaining": None, "cap": None, "log_dir": None,
           "limitations": [
               "reads logs only; Fenced owns atomic reservation and the cap",
               "tail truncation and whole-dir deletion/replacement are not detectable without an operator anchor",
               "same-user storage: not a durable or tamper-proof ledger",
               "lifetime cap across different model/epoch logs is not atomic across processes (Fenced gap, not patched here)"]}
    try:
        if not (isinstance(planned_calls, int) and not isinstance(planned_calls, bool) and planned_calls >= 0):
            out["problems"].append("planned_calls must be a non-negative int"); return out
        bad = _check_budgets(epoch_budgets)
        if bad:
            out["problems"].append(bad); return out
        if epoch_budgets is not None and planned_calls != sum(epoch_budgets.values()):
            out["problems"].append("ambiguous input: planned_calls %d != sum of epoch_budgets %d"
                                   % (planned_calls, sum(epoch_budgets.values())))
            return out
        out["epoch_budgets"] = dict(epoch_budgets) if epoch_budgets is not None else None
        dd, dc = (log_dir, cap)
        if dd is None or dc is None:
            d0, c0 = _defaults(); dd = dd or d0; dc = dc if dc is not None else c0
        if not (isinstance(dc, int) and not isinstance(dc, bool) and dc >= 0):
            out["problems"].append("bad cap"); return out
        dd = os.path.abspath(dd)
        out["log_dir"], out["cap"] = dd, dc
        try:
            home = pwd.getpwuid(os.getuid()).pw_dir
            if log_dir is None and os.path.expanduser("~") != home:
                out["problems"].append("HOME differs from the account home; the default ledger path moved")
        except KeyError:
            out["problems"].append("cannot resolve account home")
        dprobs = _check_dir(dd)
        if dprobs is None:
            out["status"] = "unestablished"
            out["problems"].append("no log directory: first run, deleted ledger and changed HOME look the same")
            if allow_fresh and not out["problems"][:-1] and anchor is None and not expected_min_reserves:
                nd = _needed(planned_calls, epoch_budgets, [])
                out.update(status="ok_to_plan" if nd <= dc else "over_cap", reserves_total=0,
                           remaining=dc, needed_calls=nd, fresh_asserted_by_operator=True)
            return out
        out["problems"].extend(dprobs)
        names = sorted(os.listdir(dd))
        if len(names) > _MAX_FILES:
            out["problems"].append("too many files in log dir"); return out
        total, halted = 0, False
        import fenced_http
        ctl = fenced_http.read_control(dd)
        out["problems"].extend(ctl["problems"])
        floor = ctl["floor"]; out["historic_floor"] = ctl["floor_line"]
        total = floor
        okw, whyw, infow = fenced_http.window_status(dd)
        out["window"] = {"open": okw, "why": whyw, **infow}     # report only; the fence enforces
        for fn in names:
            if fn == fenced_http.CONTROL_NAME:
                continue
            if not fn.endswith(".jsonl"):
                out["problems"].append("unexpected non-log file in ledger dir: " + fn); continue
            if not _SLUG_EPOCH.match(fn):
                out["problems"].append("log file name does not match slug.epoch.jsonl: " + fn)
            facts, pr = _scan_log(os.path.join(dd, fn), fn)
            out["problems"].extend(pr); out["files"].append(facts)
            total += facts["reserves"]; halted = halted or facts["halts"] > 0
        out["reserves_total"] = total
        out["remaining"] = max(0, dc - total)
        if halted:
            out["problems"].append("a halt line exists; Fenced refuses all later calls")
        if total > dc:
            out["problems"].append("recorded reserves exceed the cap")
        if not out["files"]:
            out["status"] = "unestablished"
            out["problems"].append("log dir has no logs: cannot distinguish first run from deletion")
            if allow_fresh and anchor is None and not expected_min_reserves and not out["problems"][:-1]:
                nd = _needed(planned_calls, epoch_budgets, [])
                out.update(status="ok_to_plan" if nd <= dc else "over_cap", needed_calls=nd,
                           fresh_asserted_by_operator=True)
            return out
        if expected_min_reserves is not None and total < expected_min_reserves:
            out["problems"].append("fewer reserves than the operator expects (%d < %d): deletion or truncation"
                                   % (total, expected_min_reserves))
        if anchor is not None:
            af = anchor.get("files") if isinstance(anchor, dict) else None
            if not isinstance(anchor, dict) or anchor.get("schema") != SCHEMA \
                    or not isinstance(af, dict) or not af:
                out["problems"].append("anchor is not a reserve-preflight/v1 snapshot with a non-empty files object")
            elif not all(isinstance(a, dict) and isinstance(a.get("lines"), int) and not isinstance(a.get("lines"), bool)
                         and a["lines"] >= 1 and isinstance(a.get("tip_sha256"), str)
                         and re.fullmatch(r"[0-9a-f]{64}", a["tip_sha256"]) for a in af.values()):
                out["problems"].append("anchor has a malformed file entry (needs lines >= 1 and a sha256 tip)")
            else:
                by = {x["file"]: x for x in out["files"]}
                for fn, a in af.items():
                    cur = by.get(fn)
                    if cur is None:
                        out["problems"].append("anchored log missing now: " + fn); continue
                    if cur["lines"] < a["lines"]:
                        out["problems"].append("log shorter than anchor (tail truncation): " + fn); continue
                    # re-scan to compare the hash AT the anchored line count
                    h = _hash_at(os.path.join(dd, fn), a["lines"])
                    if h != a.get("tip_sha256"):
                        out["problems"].append("log diverges from anchor (rewritten history): " + fn)
        if out["problems"]:
            out["status"] = "refuse"
        else:
            nd = _needed(planned_calls, epoch_budgets, out["files"])
            out["needed_calls"] = nd
            out["status"] = "ok_to_plan" if nd <= out["remaining"] else "over_cap"
        for x in out["files"]:
            x.pop("line_hashes", None)
        return out
    except Exception as exc:   # never open the gate on an unexpected error
        out["status"] = "refuse"
        out["problems"].append("preflight error: " + exc.__class__.__name__)
        return out


def _hash_at(path, nlines):
    prev, i = "0", 0
    try:
        with open(path, "rb") as fh:
            for raw in fh.read().split(b"\n"):
                if not raw.strip():
                    continue
                prev = _sha(raw.rstrip(b"\n")); i += 1
                if i == nlines:
                    return prev
    except OSError:
        return None
    return "0" if nlines == 0 else None


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="read-only Fenced reserve preflight; exit 0 only for ok_to_plan")
    ap.add_argument("--planned", type=int, required=True)
    ap.add_argument("--log-dir"); ap.add_argument("--cap", type=int)
    ap.add_argument("--anchor-file"); ap.add_argument("--expected-min-reserves", type=int)
    ap.add_argument("--allow-fresh", action="store_true")
    ap.add_argument("--epoch-budget", action="append", metavar="FILE=N",
                    help="lifetime call budget of one slug.epoch.jsonl; repeatable; "
                         "charges only what remains in each epoch (resume-safe)")
    a = ap.parse_args(argv)
    anchor = None
    if a.anchor_file:
        try:
            anchor = json.load(open(a.anchor_file, encoding="utf-8"))
        except (OSError, ValueError):
            anchor = {"schema": "unreadable"}
        if not isinstance(anchor, dict):   # null/list/string must never read as "no anchor"
            anchor = {"schema": "unreadable"}
    eb = None
    if a.epoch_budget:
        eb = {}
        for item in a.epoch_budget:
            k, _, v = item.rpartition("=")
            if k in eb:        # a repeated key must never widen or replace a budget
                print(json.dumps({"status": "refuse", "problems": ["duplicate --epoch-budget key: " + k]}))
                return 1
            try:
                eb[k] = int(v)
            except ValueError:
                eb[k] = None   # rejected by preflight as malformed
    r = preflight(a.planned, log_dir=a.log_dir, cap=a.cap, anchor=anchor, allow_fresh=a.allow_fresh,
                  expected_min_reserves=a.expected_min_reserves, epoch_budgets=eb)
    print(json.dumps(r, sort_keys=True))
    return 0 if r["status"] == "ok_to_plan" else 1


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    raise SystemExit(main(sys.argv[1:]))
