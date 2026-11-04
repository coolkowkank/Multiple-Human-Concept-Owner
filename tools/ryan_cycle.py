#!/usr/bin/env python3
"""Ryan pipeline runner: Researcher -> Verifier -> Team Resources (Ryan).

One step = at most ONE provider request. Stdlib only. State is plain
files under docs/team/ryan/ so every step is reviewable in git:
  queue.json    open questions with source packets and per-question state
  ledger.jsonl  append-only: a 'reserved' line is written BEFORE each
                request; a reserve with no result line counts as consumed
                (unknown outcome). Nothing here says 'billed'.
  runs/<qid>/   verbatim model outputs, one file per attempt

Hard rules (all enforced in code, all tested with a mock transport):
  - free gate before EVERY request: exact id, all-zero prices, listing
    fetched <= 30 min ago with a named source (model_resources.py)
  - verifier model must differ from researcher model
  - the verdict is computed here from per-claim verdicts; the model's
    own 'overall' field is ignored
  - Ryan only ever sees claims the verifier marked SUPPORTED (or claims
    the researcher labelled UNVERIFIED and the verifier agreed)
  - no automatic retry. Any 429, unknown outcome, 401/403 or nonzero
    cost -> PAUSED (halt line in the ledger). It resumes only when a
    human appends a 'cleared' line citing an external source condition
    (provider/console evidence). No probes, no assumed quota reset.
  - daily cap 24 reserves in a rolling 24h window (4 cycles x 6, all
    roles combined); max 4 distinct questions started per 24h; spacing
    >= 10 s; per-question role caps; input <= 12288 bytes. The org-wide
    pool is shared with other project work and its remaining quota is
    UNKNOWN: this cap bounds OUR use only.
  - empty queue -> zero requests, zero listing fetches
  - adoption is never done here: finished questions stop at
    'ready-for-chain' (Coordinator -> owner decides).
"""
import json
import math, os, sys, datetime, time, urllib.request, urllib.error
import contextlib, re, socket
try:
    import fcntl
except ImportError:  # non-POSIX: refuse to run unlocked
    fcntl = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model_resources as mr

BASE_URL = "https://router.requesty.ai/v1"
# CANDIDATES only, NOT assignments. Model choice and assignment belong to
# the project operator (main), never to Ryan: assign_manual() is the only
# way assignments.json is written, and step() refuses any file that does
# not carry decided_by == OPERATOR.
OPERATOR = "main"
CANDIDATES = {
    "researcher": "nvidia/nemotron-3-ultra-550b-a55b",
    "verifier": "google/gemma-4-31b-it",
    "ryan": "nvidia/nemotron-3-ultra-550b-a55b",
}
BLOCKED_STATUS = ("not-qualified", "uncallable", "capped", "cooldown")
ROLES = ("researcher", "verifier", "ryan")
CEILINGS = {"researcher": 2048, "verifier": 1536, "ryan": 2048}
ROLE_CAP = {"researcher": 2, "verifier": 2, "ryan": 2}  # per question
QUESTION_BUDGET = 5  # <= 5 requests per question; clean path = 3
DAILY_CAP = 24      # 4 cycles x 6 requests, all three roles combined
CYCLES_PER_DAY = 4
SPACING_S = 10
MAX_INPUT_BYTES = 12288


class Halt(Exception):
    pass


def utc(now):
    return datetime.datetime.fromtimestamp(now, datetime.timezone.utc)


def iso(now):
    return utc(now).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return datetime.datetime.fromisoformat(
        s.replace("Z", "+00:00")).timestamp()


class Store:
    def __init__(self, root):
        self.root = root
        self.qpath = os.path.join(root, "queue.json")
        self.lpath = os.path.join(root, "ledger.jsonl")

    @contextlib.contextmanager
    def lock(self):
        """Single-writer transaction lock (flock on root/.lock). All
        gate-check + reserve + queue/assignment writes happen inside it;
        it is never held across a provider request."""
        if fcntl is None:
            raise Halt("no flock on this platform; refusing to run")
        os.makedirs(self.root, exist_ok=True)
        with open(os.path.join(self.root, ".lock"), "a") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)

    def reserve(self, now, entry, qid):
        """Atomic: ledger_gate then append the reserve under the lock.
        Returns ('ok','') or ('wait',reason); raises Halt if paused."""
        with self.lock():
            state, why = ledger_gate(self, now, qid)
            if state == "ok":
                if not entry.get("rid"):  # id minted INSIDE the lock
                    entry["rid"] = "%s-%d" % (entry["role"],
                                              len(self.ledger()))
                self.append(entry)
            return state, why

    def queue(self):
        if not os.path.exists(self.qpath):
            return {"questions": []}
        with open(self.qpath) as f:
            return json.load(f)

    def save_queue(self, q):
        tmp = self.qpath + ".tmp"
        with open(tmp, "w") as f:
            json.dump(q, f, indent=2)
        os.replace(tmp, self.qpath)

    def ledger(self):
        if not os.path.exists(self.lpath):
            return []
        out = []
        with open(self.lpath) as f:
            for line in f:
                if line.strip():
                    out.append(json.loads(line))
        return out

    def append(self, entry):
        os.makedirs(self.root, exist_ok=True)
        with open(self.lpath, "a") as f:
            f.write(json.dumps(entry) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def write_run(self, qid, name, text):
        d = os.path.join(self.root, "runs", qid)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "w") as f:
            f.write(text)


def strict_json(text):
    """Whole reply is one JSON object, bare or in exactly one fence."""
    t = text.strip()
    if t.startswith("```"):
        parts = t.split("```")
        if len(parts) != 3 or parts[0].strip() or parts[2].strip():
            raise ValueError("not exactly one fence")
        t = parts[1].strip()
        if t.startswith("json"):
            t = t[4:].strip()
    obj = json.loads(t)
    if not isinstance(obj, dict):
        raise ValueError("not an object")
    return obj


def ledger_gate(store, now, qid=None):
    """Raise Halt or return ('ok'|'wait', reason)."""
    led = store.ledger()
    halts = [e for e in led if e["phase"] == "halt"]
    cleared = [e for e in led if e["phase"] == "cleared"]
    last_clear = cleared[-1]["ts"] if cleared else ""
    if halts and halts[-1]["ts"] >= last_clear and (
            not cleared or halts[-1]["ts"] > last_clear
            or led.index(halts[-1]) > led.index(cleared[-1])):
        raise Halt("PAUSED: " + halts[-1]["reason"])
    reserves = [e for e in led if e["phase"] == "reserved"]
    results = {e["rid"]: e for e in led if e["phase"] == "result"}
    for r in reserves:
        if r["rid"] not in results and (
                not cleared or led.index(r) > led.index(cleared[-1])):
            raise Halt("reserve %s has no result: unknown outcome, "
                       "consumed, human must clear" % r["rid"])
    done = sorted(results.values(), key=lambda e: e["ts"])
    if done and now - parse_iso(done[-1]["ts"]) < SPACING_S:
        return "wait", "spacing %ss" % SPACING_S
    window = [r for r in reserves if now - parse_iso(r["ts"]) < 86400]
    if len(window) >= DAILY_CAP:
        return "wait", "daily cap %d reached (rolling 24h)" % DAILY_CAP
    started = {r["qid"] for r in window}
    if qid is not None and qid not in started and \
            len(started) >= CYCLES_PER_DAY:
        return "wait", "%d cycles already started in 24h" % CYCLES_PER_DAY
    return "ok", ""


def clear(root, source_note, now):
    """Human/main clears a pause. A note naming the external source
    condition is mandatory; nothing here probes the provider."""
    if not source_note or len(source_note.strip()) < 10:
        raise ValueError("clearing needs a source note (>=10 chars)")
    Store(root).append({"phase": "cleared", "ts": iso(now),
                        "note": source_note.strip()})


def listing_fresh(listing, now):
    """Named source, fetched 0..30 min before NOW (the injected clock;
    a future-dated listing is refused too)."""
    try:
        if not listing.get("source"):
            return False
        age = now - parse_iso(listing["fetched_at"])
        return 0 <= age <= mr.FRESH_LISTING_MAX_AGE_MIN * 60
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


def free_gate(listing, model, now):
    if not listing_fresh(listing, now):
        raise Halt("no fresh named-source listing; price unverified")
    if not mr.price_zero(listing, model):
        raise Halt("%s not price-0 (or absent) in fresh listing" % model)


def lab(listing, model_id):
    """Model lab from the provider listing's own model_lab field for the
    EXACT id. An id prefix is a reseller/route name, never a family.
    None = unknown (fail closed)."""
    for m in listing.get("data", []):
        if m.get("id") == model_id:
            v = m.get("model_lab")
            if isinstance(v, str) and v.strip():
                return v.strip().lower()
    return None


def independent(listing, researcher, verifier):
    """'' or reason: different exact model AND different listed lab."""
    if researcher == verifier:
        return "verifier must be a different model than the researcher"
    a, b = lab(listing, researcher), lab(listing, verifier)
    if a is None or b is None:
        return "model_lab unknown in listing (independence unverifiable)"
    if a == b:
        return "verifier must be from a different model lab (%s)" % a
    return ""


OK_STATUS = ("working", "untested")  # untested = human-recorded, first
#                                       cycle tests it; absent = UNKNOWN


def route_gate(record, model):
    """'' or reason. The route must be RECORDED under this exact id, with
    a non-blocked status, and its provider must not be blocked. An
    unrecorded id is unknown, not working."""
    rec = mr.get_route(record, model) if isinstance(record, dict) else None
    if rec is None:
        return "%s has no route record (unknown, not working)" % model
    if rec.get("status") not in OK_STATUS:
        return "%s recorded %s" % (model, rec.get("status"))
    if rec.get("provider") in (record.get("provider_blocks") or {}):
        return "provider of %s is blocked" % model
    return ""


def validate_assignments(assign, record, listing, now):
    """Mechanical gate on Ryan's choice. Returns '' or the reason.
    Ryan may not waive: exact price-0 (all fields numeric 0) in the
    fresh listing, a recorded non-blocked route for the exact id,
    verifier different model AND family from the researcher, provider
    blocks, or the per-role justification."""
    if not isinstance(assign, dict) or set(assign.get("models", {})) != \
            set(ROLES):
        return "assignments must name exactly researcher, verifier, ryan"
    m = assign["models"]
    why = assign.get("why", {})
    if not listing_fresh(listing, now):
        return "no fresh named-source listing"
    for r in ROLES:
        if not isinstance(m[r], str):
            return "role %s model must be an id string" % r
        if not isinstance(why.get(r), str) or len(why[r].strip()) < 10:
            return "role %s needs a justification" % r
        if not mr.price_zero(listing, m[r]):
            return "%s not price-0 in the fresh listing" % m[r]
        bad = route_gate(record, m[r])
        if bad:
            return bad
    return independent(listing, m["researcher"], m["verifier"])


def load_assignments(root):
    p = os.path.join(root, "assignments.json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def allocate(*args, **kwargs):
    """DISABLED. Ryan no longer chooses or assigns models (owner steering
    2026-11-04 19:44 EET). Kept as a refusing stub so no caller can make
    a model request to pick models. Use assign_manual()."""
    return {"action": "disabled", "calls": 0,
            "reason": "Ryan does not assign models; use assign_manual"}


def assign_manual(root, models, why, listing, record, now, source_ref):
    """Operator-made assignment, validated by the SAME gates as before
    (exact price-0 in a fresh listing, recorded non-blocked route, lab
    independence, justification per role). Makes NO model request, writes
    no ledger line, and does not clear a pause. Returns {'action':
    'assigned'|'rejected', ...}. SOURCE_REF names the operator decision."""
    if not isinstance(source_ref, str) or len(source_ref.strip()) < 10:
        return {"action": "rejected", "reason": "source_ref required"}
    obj = {"models": models, "why": why}
    bad = validate_assignments(obj, record, listing, now)
    if bad:
        return {"action": "rejected", "reason": bad, "calls": 0}
    obj["decided_by"] = OPERATOR
    obj["source_ref"] = source_ref.strip()
    obj["decided_at"] = iso(now)
    store = Store(root)
    with store.lock():
        ap = os.path.join(root, "assignments.json")
        with open(ap + ".tmp", "w") as f:
            json.dump(obj, f, indent=2)
        os.replace(ap + ".tmp", ap)
    return {"action": "assigned", "calls": 0, "models": models}


def settle(store, rid, qid, role, model, res, now):
    """Record a result line; returns a dict for failures, None on 'ok'.
    Raises Halt for 429/unknown/auth/nonzero cost (PAUSED)."""
    done = {"phase": "result", "rid": rid, "ts": iso(now), "qid": qid,
            "role": role, "model": model, "usage": res.get("usage")}
    if res.get("diag"):
        done["diag"] = clean_diag(res["diag"])
    sig = res.get("cost_signal")
    if sig is None and (res.get("usage") or {}).get("cost"):
        sig = "nonzero"
    bad = sig in ("nonzero", "invalid") or res.get("usage_flag") == "invalid"
    if bad:
        # any nonzero/invalid cost or invalid usage halts for EVERY kind,
        # keeping the original outcome and the signal.
        done["outcome"] = ("unknown" if res["kind"] == "unknown" else
                           "http_%d" % res["code"] if res["kind"] == "http"
                           else "ok")
        done["cost_signal"] = sig or "usage_invalid"
        store.append(done)
        store.append({"phase": "halt", "ts": iso(now),
                      "reason": "cost/usage signal %s on %s"
                                % (done["cost_signal"], rid)})
        raise Halt("nonzero or invalid cost/usage signal")
    if res.get("usage_flag") == "extra_keys":
        done["usage_extra_keys"] = 1
    if res["kind"] == "unknown":
        done["outcome"] = "unknown"
        store.append(done)
        store.append({"phase": "halt", "ts": iso(now),
                      "reason": "unknown transport outcome " + rid})
        raise Halt("unknown transport outcome")
    if res["kind"] == "http":
        done["outcome"] = "http_%d" % res["code"]
        store.append(done)
        if res["code"] in (401, 403, 429):
            store.append({"phase": "halt", "ts": iso(now),
                          "reason": "http %d on %s" % (res["code"], rid)})
            raise Halt("paused on http %d" % res["code"])
        return {"action": "failed", "qid": qid, "role": role,
                "outcome": done["outcome"], "calls": 1}
    if (res.get("usage") or {}).get("cost"):
        done["outcome"] = "nonzero_cost"
        store.append(done)
        store.append({"phase": "halt", "ts": iso(now),
                      "reason": "nonzero cost %s" % res["usage"]["cost"]})
        raise Halt("nonzero cost reported")
    done["outcome"] = "ok"
    store.append(done)
    return None


def build_prompt(role, q):
    packet = json.dumps(q["packet"], indent=1)
    if role == "researcher":
        fb = ""
        if q.get("feedback"):
            fb = "\nCorrection feedback:\n" + q["feedback"]
        return ("Question: %s\nSource packet (cite ONLY these ids; never "
                "add sources from memory):\n%s\n%s\nReply with ONE JSON "
                'object: {"findings":[{"id":"C1","claim":"...",'
                '"sources":["P1"],"status":"SUPPORTED_BY_PACKET|'
                'UNVERIFIED|MISSING_SOURCE"}],"summary":"..."}. A claim '
                "with status SUPPORTED_BY_PACKET needs >=1 source id.") % (
                    q["question"], packet, fb)
    fb = ""
    if q.get("fb_" + role):
        fb = "\nYour previous reply was rejected: " + q["fb_" + role] + "\n"
    if role == "verifier":
        return ("Check each finding against the packet passages only. For "
                "every finding id give SUPPORTED, NOT_SUPPORTED or "
                "UNVERIFIED. SUPPORTED needs a source id from that "
                "finding and a quote copied EXACTLY (verbatim substring) "
                "from that packet passage.\nPacket:\n%s\n"
                "Findings:\n%s\n%sReply with ONE JSON object: "
                '{"verdicts":[{"id":"C1","verdict":"SUPPORTED|'
                'NOT_SUPPORTED|UNVERIFIED","source":"P1","quote":"exact '
                'text","evidence":"..."}]}') % (
                    packet, json.dumps(q["findings"], indent=1), fb)
    ok = [f for f in q["findings"] if f["id"] in q["verified_ids"]]
    return ("Question: %s\nVerified findings only:\n%s\nFor each, rate "
            "usefulness to the team's speed and token use and propose an "
            "action for the Coordinator. Proposals are not adopted by you. "
            '%sReply with ONE JSON object: {"usefulness":[{"id":"C1",'
            '"useful":"HIGH|MEDIUM|LOW|NONE","why":"...",'
            '"proposed_action":"..."}],"note":"..."}') % (
                q["question"], json.dumps(ok, indent=1), fb)


def norm(t):
    return " ".join(str(t).split()).lower()


def precheck(role, q, obj):
    """Mechanical checks before the next paid step. Returns '' or reason."""
    ids = {p["id"] for p in q["packet"]}
    if role == "researcher":
        fs = obj.get("findings")
        if not isinstance(fs, list) or not fs:
            return "no findings list"
        seen = set()
        for f in fs:
            if not isinstance(f, dict) or not f.get("id") or not f.get("claim"):
                return "finding without id/claim"
            if f["id"] in seen:
                return "duplicate finding id " + f["id"]
            seen.add(f["id"])
            src = f.get("sources", [])
            if not isinstance(src, list) or any(s not in ids for s in src):
                return "finding %s cites id outside the packet" % f["id"]
            if f.get("status") == "SUPPORTED_BY_PACKET" and not src:
                return "finding %s supported but no source" % f["id"]
            if f.get("status") not in ("SUPPORTED_BY_PACKET", "UNVERIFIED",
                                       "MISSING_SOURCE"):
                return "finding %s bad status" % f["id"]
        return ""
    if role == "verifier":
        vs = obj.get("verdicts")
        if not isinstance(vs, list):
            return "no verdicts list"
        want = {f["id"] for f in q["findings"]}
        got = [v.get("id") for v in vs if isinstance(v, dict)]
        if set(got) != want or len(got) != len(want):
            return "verdict ids do not match finding ids exactly"
        fmap = {f["id"]: f for f in q["findings"]}
        pmap = {p["id"]: norm(p.get("passage", "")) for p in q["packet"]}
        for v in vs:
            if v.get("verdict") not in ("SUPPORTED", "NOT_SUPPORTED",
                                        "UNVERIFIED"):
                return "bad verdict value"
            if v["verdict"] == "SUPPORTED":
                src, quote = v.get("source"), v.get("quote")
                if src not in fmap[v["id"]].get("sources", []) or \
                        src not in pmap:
                    return "verdict %s source not among the finding's " \
                        "packet sources" % v["id"]
                if not isinstance(quote, str) or len(norm(quote)) < 8 \
                        or norm(quote) not in pmap[src]:
                    return "verdict %s quote is not a verbatim passage " \
                        "substring (mechanical check; whether it " \
                        "supports the claim stays model judgment)" % v["id"]
        return ""
    us = obj.get("usefulness")
    if not isinstance(us, list):
        return "no usefulness list"
    for u in us:
        if not isinstance(u, dict) or u.get("id") not in q["verified_ids"]:
            return "usefulness row outside verified ids"
        if u.get("useful") not in ("HIGH", "MEDIUM", "LOW", "NONE"):
            return "bad usefulness value"
    return ""


def compute_overall(q, obj):
    """PASS only if every claim is SUPPORTED, or UNVERIFIED on both
    sides (researcher labelled it and verifier agreed). The model's own
    'overall' is ignored."""
    lab = {f["id"]: f.get("status") for f in q["findings"]}
    verified, bad = [], []
    for v in obj["verdicts"]:
        cid, vd = v["id"], v["verdict"]
        if vd == "SUPPORTED" and lab[cid] == "SUPPORTED_BY_PACKET":
            verified.append(cid)
        elif vd == "UNVERIFIED" and lab[cid] in ("UNVERIFIED",
                                                  "MISSING_SOURCE"):
            continue
        else:
            bad.append(cid)
    return ("PASS" if not bad else "FAIL"), verified, bad


def next_action(q):
    s = q["status"]
    if s == "open":
        return "researcher"
    if s == "drafted":
        return "verifier"
    if s == "verified":
        return "ryan"
    return None


def pick(queue):
    for q in queue["questions"]:
        if next_action(q):
            return q
    return None


def step(root, post, list_models, now, record):
    """One step. post(model, system, prompt, max_tokens) ->
    {'kind': 'ok'|'http'|'unknown', 'code': int, 'content': str,
     'usage': dict}. RECORD is the route record (model-availability).
    Gate+reserve+queue write are one locked transaction; the lock is not
    held across the request. Returns a dict describing what happened."""
    store = Store(root)
    with store.lock():
        queue = store.queue()
        q = pick(queue)
        if q is None:
            return {"action": "idle", "calls": 0}
        qid = q["id"]
        role = next_action(q)
        assign = load_assignments(root)
        if assign is None:
            return {"action": "needs-allocation", "calls": 0}
        if assign.get("decided_by") != OPERATOR:
            return {"action": "needs-allocation", "calls": 0,
                    "reason": "assignments.json not made by the operator"}
        model = assign["models"][role]
        if sum(q["attempts"].values()) >= QUESTION_BUDGET:
            q["status"] = "needs-human"
            q["reason"] = "question budget %d requests used" % QUESTION_BUDGET
            store.save_queue(queue)
            return {"action": "needs-human", "qid": qid, "calls": 0}
        if q["attempts"].get(role, 0) >= ROLE_CAP[role]:
            q["status"] = "needs-human"
            q["reason"] = role + " attempts exhausted"
            store.save_queue(queue)
            return {"action": "needs-human", "qid": qid, "calls": 0}
        state, why = ledger_gate(store, now, qid)
        if state == "wait":
            return {"action": "wait", "reason": why, "calls": 0}
        bad = route_gate(record, model)
        if bad:
            return {"action": "needs-human", "qid": qid, "calls": 0,
                    "reason": bad}
        prompt = build_prompt(role, q)
        system = "You are the %s in a source-bound review pipeline." % role
        if len((system + prompt).encode()) > MAX_INPUT_BYTES:
            q["status"] = "needs-human"
            q["reason"] = "input over %d bytes" % MAX_INPUT_BYTES
            store.save_queue(queue)
            return {"action": "needs-human", "qid": qid, "calls": 0}
        listing = list_models()
        free_gate(listing, model, now)
        if role == "verifier":
            why_not = independent(listing, assign["models"]["researcher"],
                                  model)
            if why_not:
                raise Halt("verifier not independent: " + why_not)
        rid = "%s-%s-%d" % (qid, role, len(store.ledger()))
        store.append({"phase": "reserved", "rid": rid, "ts": iso(now),
                      "qid": qid, "role": role, "model": model})
        q["attempts"][role] = q["attempts"].get(role, 0) + 1
        store.save_queue(queue)
        n = q["attempts"][role]
    res = post(model, system, prompt, CEILINGS[role])
    with store.lock():
        out = settle(store, rid, qid, role, model, res, now)
        if out:
            return out
        store.write_run(qid, "%s-%d.txt" % (role, n), res["content"])
        queue = store.queue()
        q = next((x for x in queue["questions"] if x["id"] == qid), None)
        if q is None:
            store.append({"phase": "halt", "ts": iso(now),
                          "reason": "queue entry %s vanished mid-flight; "
                          "result kept in runs/, explicit recovery" % qid})
            raise Halt("queue entry vanished mid-flight")
        try:
            obj = strict_json(res["content"])
            bad = precheck(role, q, obj)
        except ValueError as e:
            obj, bad = None, "format: %s" % e
        if bad:
            if role == "researcher":
                q["feedback"] = "format/consistency problem: " + bad
            else:
                q["fb_" + role] = bad
            if q["attempts"][role] >= ROLE_CAP[role]:
                q["status"] = "needs-human"
                q["reason"] = bad
            store.save_queue(queue)
            return {"action": "precheck-failed", "qid": qid, "role": role,
                    "reason": bad, "calls": 1}
        q.pop("fb_" + role, None)
        if role == "researcher":
            q["findings"] = obj["findings"]
            q["status"] = "drafted"
            q.pop("feedback", None)
        elif role == "verifier":
            overall, verified, bad_ids = compute_overall(q, obj)
            q["verifier_verdict"] = {"overall": overall, "bad": bad_ids}
            q["verified_ids"] = verified
            if overall == "PASS":
                q["status"] = "verified"
            elif q["attempts"].get("researcher", 0) < ROLE_CAP["researcher"]:
                q["status"] = "open"
                q["feedback"] = "claims not supported: %s. Evidence: %s" % (
                    ",".join(bad_ids),
                    json.dumps([v for v in obj["verdicts"]
                                if v["id"] in bad_ids]))
            else:
                q["status"] = "needs-human"
                q["reason"] = "verification failed, no correction left"
        else:
            q["ryan_review"] = obj
            q["status"] = "ready-for-chain"
        store.save_queue(queue)
        return {"action": "done-" + role, "qid": qid, "status": q["status"],
                "calls": 1}


def jobdesc_scan(repo, root, now, max_packet=6, passage_chars=600):
    """Standing job: keep project job descriptions lean. Deterministic
    and zero-token: hash each blueprint, and only when the set changed
    since the last reviewed digest enqueue ONE question whose packet is
    the most repeated passages (real text, quoted by file and line).
    Measurement is bytes/chars only; chars/4 is a labelled heuristic,
    never provider tokens. Unchanged text is never re-read or re-sent.
    Public project files only."""
    import hashlib, glob, collections
    store = Store(root)
    os.makedirs(root, exist_ok=True)
    files = sorted(glob.glob(os.path.join(
        repo, "docs/team/blueprints/*.md")) + [os.path.join(
            repo, "docs/team/registry.md")])
    files = [f for f in files if not f.endswith("_template.md")
             and os.path.exists(f)]
    sizes, texts = {}, {}
    h = hashlib.sha256()
    for f in files:
        with open(f, "rb") as fh:
            b = fh.read()
        rel = os.path.relpath(f, repo)
        sizes[rel] = {"bytes": len(b), "chars": len(b.decode("utf-8",
                                                              "replace"))}
        texts[rel] = b.decode("utf-8", "replace")
        h.update(rel.encode() + b"\0" + hashlib.sha256(b).digest())
    digest = h.hexdigest()
    sp = os.path.join(root, "jobdesc-state.json")
    prev = {}
    if os.path.exists(sp):
        with open(sp) as f:
            prev = json.load(f)
    total = sum(v["bytes"] for v in sizes.values())
    base = {"digest": digest, "sizes": sizes, "total_bytes": total,
            "chars_div4_heuristic_not_tokens": total // 4,
            "scanned_at": iso(now)}
    if prev.get("digest") == digest:
        return {"action": "unchanged", "total_bytes": total, "calls": 0}
    K = 10  # repeated 10-word runs; whole-line matching misses hard-wrapped text
    words = {}
    for rel, t in texts.items():
        ws = []
        for i, line in enumerate(t.split("\n"), 1):
            for w in line.split():
                ws.append((w.lower().strip("*`_.,;:()"), i, w))
        words[rel] = ws
    sh = collections.defaultdict(set)
    for rel, ws in words.items():
        for j in range(len(ws) - K + 1):
            sh[tuple(x[0] for x in ws[j:j + K])].add((rel, j))
    runs = {}
    for rel, ws in words.items():
        j = 0
        while j <= len(ws) - K:
            key = tuple(x[0] for x in ws[j:j + K])
            if len(sh[key]) > 1:
                e = j + K
                while e < len(ws) and len(sh.get(tuple(
                        x[0] for x in ws[e - K + 1:e + 1]), ())) > 1:
                    e += 1
                text = " ".join(x[2] for x in ws[j:e])
                runs.setdefault(text.lower(), []).append(
                    (rel, ws[j][1], text))
                j = e
            else:
                j += 1
    reps = sorted((v for v in runs.values()
                   if len(v) > 1 and len(v[0][2]) >= 80),
                  key=lambda v: -len(v) * len(v[0][2]))[:2]
    # Largest blocks (verbatim, file:line) are the usual real waste;
    # duplicated wording is rare in these files, so it is only added when
    # it exists and is 80+ chars.
    blocks = []
    for rel, t in texts.items():
        start, cur = 1, []
        lines = t.split("\n")
        for i, line in enumerate(lines + [""], 1):
            if line.startswith("|"):  # each table row is its own block
                if cur:
                    blocks.append((len("\n".join(cur)), rel, start,
                                   "\n".join(cur)))
                    cur = []
                blocks.append((len(line), rel, i, line))
            elif line.strip():
                if not cur:
                    start = i
                cur.append(line)
            elif cur:
                blocks.append((len("\n".join(cur)), rel, start,
                               "\n".join(cur)))
                cur = []
    blocks.sort(key=lambda b: -b[0])
    packet = []
    for size, rel, ln, text in blocks[:max_packet - len(reps)]:
        cut = text[:passage_chars]
        if len(text) > passage_chars:
            cut += " [truncated: %d of %d chars shown]" % (passage_chars,
                                                           len(text))
        packet.append({"id": "P%d" % (len(packet) + 1),
                       "title": "block in %s (%d chars)" % (rel, size),
                       "locations": ["%s:%d" % (rel, ln)],
                       "passage": cut})
    for v in reps:
        packet.append({"id": "P%d" % (len(packet) + 1),
                       "title": "repeated passage x%d" % len(v),
                       "locations": ["%s:%d" % (r, i) for r, i, _ in v],
                       "passage": v[0][2][:passage_chars]})
    if not packet:
        base["note"] = "no blocks found"
        with open(sp, "w") as f:
            json.dump(base, f, indent=2)
        return {"action": "changed-no-repeats", "total_bytes": total,
                "calls": 0}
    q = store.queue()
    qid = "jobdesc-" + digest[:8]
    if not any(x["id"] == qid for x in q["questions"]):
        q["questions"].append({
            "id": qid, "status": "open", "attempts": {},
            "question": "Which of these job-description passages (largest "
                        "blocks or repeated wording) can be shortened or "
                        "merged without removing a duty or a safety "
                        "check? Each finding names the passage id, what "
                        "can be cut, and a shorter wording. Cite packet "
                        "ids only.",
            "packet": packet, "kind": "jobdesc-efficiency"})
        store.save_queue(q)
    with open(sp, "w") as f:
        json.dump(base, f, indent=2)
    return {"action": "enqueued", "qid": qid, "total_bytes": total,
            "calls": 0}


_REDACT = [re.compile(r"(?i)bearer\s+\S+"),
           re.compile(r"(?i)\b(?:sk|rk|pk|key|tok|ghp|gho|xox[a-z])[-_][A-Za-z0-9_\-]{6,}"),
           re.compile(r"[A-Za-z0-9_\-+/=]{32,}")]


def redact(text, n=200, secret=None):
    """Allowlist-style scrub for ledger diagnostics: strip control chars,
    mask key-shaped strings and the live key if known, bound the size.
    Never used on request bodies or headers."""
    t = "".join(c if c.isprintable() else " " for c in str(text))
    if secret:
        t = t.replace(secret, "[REDACTED]")
    for rx in _REDACT:
        t = rx.sub("[REDACTED]", t)
    return t[:n]


# Structural only: no response-body text is ever persisted.
DIAG_KEYS = ("stage", "class", "error_type", "status", "content_type",
             "elapsed_s", "body_len", "body_kind", "finish_reason",
             "reasoning_present")


def body_kind(raw):
    b = (raw or b"").lstrip()[:1]
    if not raw:
        return "empty"
    if b == b"<":
        return "html-or-xml"
    if b == b"{":
        return "json-object-like"
    if b == b"[":
        return "json-array-like"
    try:
        raw[:200].decode("utf-8")
        return "text"
    except UnicodeDecodeError:
        return "binary"


def clean_diag(d):
    """Only allowlisted keys, bounded, scalars only."""
    if not isinstance(d, dict):
        return None
    out = {}
    for k in DIAG_KEYS:
        v = d.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = round(v, 2) if isinstance(v, float) else v
        elif isinstance(v, str):
            out[k] = redact(v, 60)
    return out


FINISH_ENUM = ("stop", "length", "content_filter", "tool_calls",
               "function_call", "error")
USAGE_TOP = ("prompt_tokens", "completion_tokens", "total_tokens", "cost",
             "prompt_tokens_details", "completion_tokens_details")
USAGE_NEST = ("cached_tokens", "reasoning_tokens", "audio_tokens",
              "accepted_prediction_tokens", "rejected_prediction_tokens",
              "caching_tokens", "cache_creation_tokens")


def _num_ok(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v) and v >= 0)


def finish_enum(fr):
    if not isinstance(fr, str):
        return None
    return fr if fr in FINISH_ENUM else "unknown"


def sanitize_usage(u):
    """-> (clean, flag). Explicit key allowlist per level; finite
    non-negative numbers only. flag None | 'invalid' (an allowlisted key
    with a bad value, incl. string/bool/negative cost) | 'extra_keys'
    (provider keys dropped). 'invalid' must pause the run."""
    if u is None:
        return None, None
    if not isinstance(u, dict):
        return None, "invalid"
    out, flag = {}, None
    for k, v in u.items():
        if k in USAGE_TOP and k.endswith("_details"):
            if not isinstance(v, dict):
                flag = "invalid"
                continue
            sub = {}
            for k2, v2 in v.items():
                if k2 not in USAGE_NEST:
                    flag = flag or "extra_keys"
                elif _num_ok(v2):
                    sub[k2] = v2
                else:
                    flag = "invalid"
            out[k] = sub
        elif k in USAGE_TOP:
            if _num_ok(v):
                out[k] = v
            else:
                flag = "invalid"
        else:
            flag = flag or "extra_keys"
    return out, flag


def cost_signal(usage_raw):
    """Judge cost on the RAW usage value, before any sanitization:
    None absent, 'zero', 'nonzero', 'invalid' (string, bool, negative,
    non-finite)."""
    if not isinstance(usage_raw, dict) or "cost" not in usage_raw:
        return None
    c = usage_raw["cost"]
    if not _num_ok(c):
        return "invalid"
    return "zero" if c == 0 else "nonzero"


def raw_usage(raw):
    try:
        d = json.loads(raw)
    except (ValueError, TypeError):
        return None
    u = d.get("usage") if isinstance(d, dict) else None
    return u if isinstance(u, dict) else None


def http_post_factory(env="REQUESTY_API_KEY"):
    def post(model, system, prompt, max_tokens):
        key = os.environ.get(env)
        if not key:
            raise Halt("missing key env " + env)
        t0 = time.monotonic()

        def unk(stage, cls, exc=None, raw=None, ctype=None):
            d = {"stage": stage, "class": cls,
                 "elapsed_s": time.monotonic() - t0}
            if exc is not None:
                d["error_type"] = type(exc).__name__   # class only, no text
            if ctype:
                d["content_type"] = ctype
            if raw is not None:
                d["body_len"] = len(raw)
                d["body_kind"] = body_kind(raw)
            return {"kind": "unknown", "usage": None, "content": "",
                    "cost_signal": cost_signal(raw_usage(raw)),
                    "diag": clean_diag(d)}
        body = json.dumps({
            "model": model, "temperature": 0,
            # documented chat-completions fields (docs.requesty.ai):
            # max_tokens (reasoning tokens count against it) and
            # reasoning_effort "low"; never raised silently.
            "max_tokens": max_tokens,
            "reasoning_effort": "low",
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(
            BASE_URL + "/chat/completions", data=body, headers={
                "content-type": "application/json",
                "authorization": "Bearer " + key,
                "user-agent": "team-launcher-ryan-cycle/0.1"})
        try:
            resp = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as e:
            ct = e.headers.get("content-type", "") if e.headers else ""
            eb = e.read()[:2000]
            return {"kind": "http", "code": e.code, "usage": None,
                    "content": "",
                    "cost_signal": cost_signal(raw_usage(eb)),
                    "diag": clean_diag({
                        "stage": "http-status", "class": "http",
                        "status": e.code, "content_type": ct.split(";")[0],
                        "body_len": len(eb), "body_kind": body_kind(eb),
                        "elapsed_s": time.monotonic() - t0})}
        except urllib.error.URLError as e:
            r = e.reason
            cls = "timeout" if isinstance(r, (TimeoutError, socket.timeout)) \
                else "network"
            return unk("connect-or-send", cls, r)
        except (TimeoutError, socket.timeout) as e:
            return unk("connect-or-send", "timeout", e)
        except OSError as e:
            return unk("connect-or-send", "network", e)
        with resp:
            ctype = (resp.headers.get("content-type", "") or "").split(
                ";")[0]
            try:
                raw = resp.read()
            except (TimeoutError, socket.timeout) as e:
                return unk("read-body", "timeout", e, ctype=ctype)
            except OSError as e:
                return unk("read-body", "network", e, ctype=ctype)
        try:
            data = json.loads(raw)
        except ValueError as e:
            return unk("parse-json", "malformed", e, raw, ctype)
        try:
            ch = data["choices"][0]
            content = ch["message"]["content"]
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            return unk("response-shape", "malformed", e, raw, ctype)
        usage_raw = data.get("usage") if isinstance(data, dict) else None
        usage, uflag = sanitize_usage(usage_raw)
        csig = cost_signal(usage_raw)
        fr = finish_enum(ch.get("finish_reason")
                         if isinstance(ch, dict) else None)
        if not isinstance(content, str) or not content.strip():
            # a 200 with no usable content is a response-shape failure,
            # never a success; tokens may have been consumed (unknown).
            r = unk("response-shape", "empty-content", None, raw, ctype)
            r["diag"]["finish_reason"] = fr
            msg = ch.get("message") if isinstance(ch, dict) else None
            r["diag"]["reasoning_present"] = int(bool(
                isinstance(msg, dict) and (msg.get("reasoning_content")
                                           or msg.get("reasoning"))))
            r["usage"], r["usage_flag"], r["cost_signal"] = usage, uflag, csig
            return r
        return {"kind": "ok", "usage": usage, "content": content,
                "finish_reason": fr, "usage_flag": uflag,
                "cost_signal": csig}
    return post


def main(argv):
    root = argv[2] if len(argv) > 2 else "docs/team/ryan"
    if len(argv) < 2 or argv[1] not in ("step", "status"):
        print(__doc__); return 2
    store = Store(root)
    if argv[1] == "status":
        q = store.queue()
        led = store.ledger()
        print(json.dumps({"questions": [(x["id"], x["status"])
                                        for x in q["questions"]],
                          "reserves": sum(1 for e in led
                                          if e["phase"] == "reserved")}))
        return 0
    print("live stepping is wired by the authorized operator flow only "
          "(listing fetch + key); use ryan_cycle.step() with a vetted "
          "transport")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
