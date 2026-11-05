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
# verifier 1536 -> 4096 (operator ordinary bounded config, 2026-11-05):
# the 1536 ceiling produced empty/truncated output twice; both reasoning
# tokens and content count against max_tokens. Listing max output for the
# candidate models is 32768/65536, so 4096 stays far inside it.
CEILINGS = {"researcher": 2048, "verifier": 4096, "ryan": 2048}
# per-role reasoning_effort (docs.requesty.ai/features/reasoning lists
# none|min|low|medium|high; whether a given route accepts a value is
# unknown until used - an unsupported field halts, there is no fallback).
EFFORT = {"researcher": "low", "verifier": "none", "ryan": "low"}
EFFORT_VALUES = ("none", "min", "low", "medium", "high")
ROLE_CAP = {"researcher": 2, "verifier": 2, "ryan": 2}  # per question
QUESTION_BUDGET = 5  # <= 5 requests per question; clean path = 3
ENVELOPE_TOTAL = 7   # envelope: ALL reserves ever (incl. the allocation
                     # attempt). 6 -> 7 = 4 historic + at most 3 new
                     # requests (operator edit, 2026-11-05). The historic
                     # ledger is never reset or rewritten.
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
    if len(reserves) >= ENVELOPE_TOTAL:
        return "wait", ("qualification envelope of %d requests used"
                        % ENVELOPE_TOTAL)
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
    try:
        lm = {x["id"]: lineage_of(x) for x in store.queue()["questions"]}
    except Exception:
        lm = {}
    started = {r.get("lineage") or lm.get(r["qid"], r["qid"])
               for r in window}
    if qid is not None:
        qid = lm.get(qid, qid)
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
            "role": role, "model": model}
    # final persistence boundary: validate here, never trust caller helpers
    raw_u = res.get("usage")
    clean_u, u_flag = sanitize_usage(raw_u)
    done["usage"] = clean_u
    if res.get("diag"):
        done["diag"] = clean_diag(res["diag"])
    sigs = [res.get("cost_signal"), cost_signal(raw_u)]
    if "nonzero" in sigs:
        sig = "nonzero"
    elif "invalid" in sigs or res.get("cost_signal") not in (
            None, "zero", "nonzero", "invalid"):
        sig = "invalid"
    elif "zero" in sigs:
        sig = "zero"
    else:
        sig = None
    flags = (u_flag, res.get("usage_flag"))
    bad = sig in ("nonzero", "invalid") or "invalid" in flags or \
        (res.get("usage_flag") not in (None, "invalid", "extra_keys"))
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
    if "extra_keys" in flags:
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
        if res["code"] in (400, 401, 403, 404, 422, 429):
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
                "Findings:\n%s\n%sOutput format: your ENTIRE reply is the "
                "JSON object and nothing else - no analysis text, no "
                "preface, no code fence; the first character is {. One "
                "verdict per finding id, in order; keep each evidence "
                "under 25 words. Reply with ONE JSON object: "
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
        if len(got) != len(vs) or any(not isinstance(i, str) for i in got):
            return "verdict rows need string ids"
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


def _nes(x):
    """Non-empty STRING only: no coercion of None, dict, list, bool."""
    return isinstance(x, str) and bool(x.strip())


def packet_gate(q):
    """'' or reason: every packet row is a dict with a unique non-empty
    string id and a non-empty string passage, none truncated."""
    pk = q.get("packet")
    if not isinstance(pk, list) or not pk:
        return "empty or malformed packet"
    seen = set()
    for p in pk:
        if not isinstance(p, dict) or not _nes(p.get("id")) \
                or not _nes(p.get("passage")):
            return "packet row needs a string id and a string passage"
        if p["id"] in seen:
            return "duplicate packet id " + p["id"]
        seen.add(p["id"])
        if "[truncated" in p["passage"]:
            return "packet passage %s truncated" % p["id"]
    return ""


def verify_gate(q):
    """'' or reason: fail closed on unsupported, partial or malformed
    sources and findings (strict types, no str() coercion)."""
    bad = packet_gate(q)
    if bad:
        return bad
    ids = {p["id"] for p in q["packet"]}
    fs = q.get("findings")
    if not isinstance(fs, list) or not fs:
        return "verify item needs findings"
    seen = set()
    for f in fs:
        if not isinstance(f, dict) or not _nes(f.get("id")) \
                or not _nes(f.get("claim")):
            return "finding needs a string id and a string claim"
        if f["id"] in seen:
            return "duplicate finding id " + f["id"]
        seen.add(f["id"])
        src = f.get("sources")
        if not isinstance(src, list) or not src or any(
                not _nes(x) or x not in ids for x in src) or \
                len(set(src)) != len(src):
            return "finding %s sources must be unique packet ids" % f["id"]
    if not _nes(q.get("author_model")):
        return "author_model missing (verifier independence unverifiable)"
    return ""


def work_fp(q):
    """Fingerprint of the claim set (normalised claim texts), so the same
    work cannot get fresh budgets by renaming its qid, kind or lineage."""
    fs = q.get("findings")
    if not isinstance(fs, list) or not fs:
        return None
    try:
        t = sorted(norm(f["claim"]) for f in fs if _nes(f.get("claim")))
    except (TypeError, KeyError):
        return None
    if not t:
        return None
    import hashlib
    return hashlib.sha256("\n".join(t).encode()).hexdigest()


def compute_verify(q, obj):
    """Dedicated verdict contract for publication claims: PASS only if
    EVERY claim got SUPPORTED with a verified quote. UNVERIFIED or
    NOT_SUPPORTED never passes; findings' own status is irrelevant
    (publication claims carry no Researcher SUPPORTED prerequisite)."""
    bad = [v["id"] for v in obj["verdicts"] if v["verdict"] != "SUPPORTED"]
    return ("PASS" if not bad else "FAIL"), bad


def load_eva_assignment(root):
    p = os.path.join(root, "eva-assignment.json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def assign_eva_manual(root, model, why, listing, record, now, source_ref):
    """Operator-made Eva (publication verifier) assignment under the SAME
    gates as assign_manual: exact price 0 in a fresh listing, recorded
    non-blocked route, justification. No model request, no ledger line,
    no pause cleared, and it does not promote any held queue item."""
    if not isinstance(source_ref, str) or len(source_ref.strip()) < 10:
        return {"action": "rejected", "reason": "source_ref required"}
    if not isinstance(why, str) or len(why.strip()) < 10:
        return {"action": "rejected", "reason": "justification required"}
    if not isinstance(model, str) or not listing_fresh(listing, now):
        return {"action": "rejected", "reason": "no fresh listing or model"}
    if not mr.price_zero(listing, model):
        return {"action": "rejected", "reason": "not price-0"}
    bad = route_gate(record, model)
    if bad:
        return {"action": "rejected", "reason": bad}
    obj = {"models": {"eva": model}, "why": {"eva": why.strip()},
           "decided_by": OPERATOR, "source_ref": source_ref.strip(),
           "decided_at": iso(now)}
    store = Store(root)
    with store.lock():
        ap = os.path.join(root, "eva-assignment.json")
        with open(ap + ".tmp", "w") as f:
            json.dump(obj, f, indent=2)
        os.replace(ap + ".tmp", ap)
    return {"action": "assigned", "calls": 0, "models": {"eva": model}}


def next_action(q):
    s = q["status"]
    if q.get("kind") == "verify":
        # publication verification: only an operator-set ready-verify runs
        # (held, drafted or anything else never does); no Ryan step.
        return "verifier" if s == "ready-verify" else None
    if s == "open":
        return "researcher"
    if s == "drafted":
        return "verifier"
    if s == "verified":
        return "ryan"
    return None


def lineage_of(q):
    return q.get("lineage") or q["id"]


def lineage_counts(store, queue, q):
    """Reserved requests per role for q's work. Counts every reserve that
    shares the item's persisted lineage, its claim-set fingerprint
    (work_fp), or a lineage bound to that fingerprint by a lineage-bind
    ledger line; legacy reserves without fields fall back to the queue
    alias. Renaming the qid, kind or lineage cannot reset the count, and
    deleting a queue item cannot hide past requests. A qid whose ledger
    lineage differs from its current lineage raises Halt."""
    L, fp = lineage_of(q), work_fp(q)
    led = store.ledger()
    related, bound_qids = {L}, set()
    for e in led:
        if e["phase"] == "lineage-bind" and fp and e.get("work_fp") == fp:
            related.add(e["lineage"])
            bound_qids.update(e.get("qids", []))
    ids = {x["id"] for x in queue["questions"]
           if lineage_of(x) in related} | bound_qids
    n = {}
    for e in led:
        if e["phase"] != "reserved" or "role" not in e:
            continue
        el = e.get("lineage")
        if e.get("qid") == q["id"] and el is not None and el != L:
            raise Halt("lineage of %s changed (%s -> %s)"
                       % (q["id"], el, L))
        if el in related or (fp and e.get("work_fp") == fp) or (
                el is None and e.get("qid") in ids):
            n[e["role"]] = n.get(e["role"], 0) + 1
    for k, v in q.get("attempts", {}).items():
        n[k] = max(n.get(k, 0), v)
    return n


def bind_lineage(root, queue_id):
    """Append a lineage-bind ledger line tying an existing item's lineage
    to its claim-set fingerprint (append-only; no rewrite)."""
    store = Store(root)
    with store.lock():
        q = next(x for x in store.queue()["questions"]
                 if x["id"] == queue_id)
        fp = work_fp(q)
        if not fp:
            raise ValueError("item has no claim set")
        L = lineage_of(q)
        qids = sorted({x["id"] for x in store.queue()["questions"]
                       if lineage_of(x) == L})
        store.append({"phase": "lineage-bind", "ts": iso(time.time()),
                      "lineage": L, "work_fp": fp, "qids": qids})
    return fp


def pick(queue):
    for q in queue["questions"]:
        if next_action(q):
            return q
    return None


def verified_rev(q):
    """sha256 of the item identity (id, kind, explicit lineage), the reviewed
    question, and the exact findings, packet, verified ids and author that a
    Verifier PASS covered. An UNKEYED digest: a guard against accidental
    between-call edits or transplants, not tamper-proof and not
    authentication (anyone who can edit the queue can recompute it). Stored at PASS and re-checked before anything
    downstream (Ryan) consumes the verified markers."""
    import hashlib
    body = {"id": q.get("id"), "kind": q.get("kind"),
            "lineage": q.get("lineage"), "question": q.get("question"),
            "findings": q.get("findings"), "packet": q.get("packet"),
            "verified_ids": q.get("verified_ids"),
            "author_model": q.get("author_model")}
    return hashlib.sha256(json.dumps(body, sort_keys=True,
                                     ensure_ascii=True).encode()).hexdigest()


def verified_rev_ok(q):
    """True only if q carries a verified_rev equal to its current one."""
    try:
        return q.get("verified_rev") == verified_rev(q)
    except Exception:
        return False


def input_snapshot(q, role, model, system, prompt, assign):
    """sha256 over everything a provider call depended on: the EXACT
    system+prompt submitted, item identity, status, role, model, lineage,
    claims, packet, author, and the whole assignment record (decided_by,
    source_ref, decided_at, models). A result is applied only if this and
    the apply-time authority are unchanged. Other items do not enter it."""
    import hashlib
    body = {"system": system, "prompt": prompt, "id": q.get("id"),
            "kind": q.get("kind"), "status": q.get("status"),
            "role": role, "model": model, "lineage": lineage_of(q),
            "findings": q.get("findings"), "packet": q.get("packet"),
            "author_model": q.get("author_model"),
            "verified_ids": q.get("verified_ids"), "assign": assign}
    return hashlib.sha256(json.dumps(body, sort_keys=True,
                                     ensure_ascii=True).encode()).hexdigest()


ALLOWANCE_MAX_REQUESTS = 2   # hard ceiling for any one window
ALLOWANCE_MAX_TTL_S = 6 * 3600
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def allowance_sign(key, body):
    """HMAC-SHA256 over the canonical body."""
    import hmac, hashlib
    return hmac.new(key, _canon(body), hashlib.sha256).hexdigest()


def _canon(body):
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode()


def grant_digest(body):
    import hashlib
    return hashlib.sha256(_canon(body)).hexdigest()


def _allowance_key():
    """(key, '') or (None, reason). The key file must be absolute, a
    regular file, owner-only (no group/other bits) and outside the
    repository tree (after resolving links). Otherwise it is refused."""
    p = os.environ.get("RYAN_ALLOWANCE_KEY_FILE")
    if not p:
        return None, "no allowance key configured"
    if not os.path.isabs(p):
        return None, "allowance key path is not absolute"
    try:
        real = os.path.realpath(p)
        st = os.stat(real)
    except OSError:
        return None, "allowance key file missing"
    import stat as _st
    if not _st.S_ISREG(st.st_mode):
        return None, "allowance key is not a regular file"
    if st.st_mode & 0o077:
        return None, "allowance key file is readable by group or others"
    if real == _REPO_ROOT or real.startswith(_REPO_ROOT + os.sep):
        return None, "allowance key lies inside the repository"
    with open(real, "rb") as f:
        k = f.read().strip()
    return (k, "") if k else (None, "allowance key file is empty")


def _load_grant(root):
    """('none'|'bad'|'ok', body, reason). 'none' = no governing grant."""
    import hmac
    key, why = _allowance_key()
    p = os.path.join(root, "allowance.json")
    if key is None or not os.path.exists(p):
        return "none", None, why or "no allowance"
    try:
        with open(p) as f:
            doc = json.load(f)
        body, sig = doc["body"], doc["sig"]
        if not isinstance(body, dict) or not isinstance(sig, str):
            return "none", None, "allowance shape"
        if not hmac.compare_digest(sig, allowance_sign(key, body)):
            return "none", None, "allowance signature invalid"
    except Exception as e:
        return "none", None, "allowance unreadable: %s" % type(e).__name__
    return "ok", body, ""


def _shape_ok(b):
    """'' or reason for a signed body's structure."""
    roles, models = b.get("roles"), b.get("models")
    base, mx = b.get("baseline"), b.get("max_counts")
    if b.get("version") != 2 or not isinstance(b.get("id"), str) \
            or not b["id"]:
        return "version/id"
    if not isinstance(roles, list) or not roles or \
            len(set(roles)) != len(roles) or \
            set(roles) - {"verifier", "ryan"} or \
            roles != [r for r in ("verifier", "ryan") if r in roles]:
        return "roles must be verifier then optionally ryan, once each"
    if not isinstance(models, dict) or set(models) != set(roles) or \
            not all(isinstance(m, str) and m for m in models.values()):
        return "one pinned model per window role"
    if not isinstance(base, dict) or set(base) != set(ROLE_CAP) or \
            not isinstance(mx, dict) or set(mx) != set(roles):
        return "baseline for every role, max_counts for window roles"
    for r in ROLE_CAP:
        if not isinstance(base[r], int) or isinstance(base[r], bool) \
                or base[r] < 0:
            return "baseline counts"
    for r in roles:
        if mx[r] != base[r] + 1 or isinstance(mx[r], bool) or \
                mx[r] > ROLE_CAP[r] + 1:
            return "max_counts must be baseline+1 and at most cap+1"
    if b.get("max_requests") != len(roles) or \
            len(roles) > ALLOWANCE_MAX_REQUESTS:
        return "max_requests must equal the number of window roles (<=2)"
    return ""


def allowance_window(root, store, q, role, used, model, now):
    """('none'|'ok'|'blocked', aid, digest, reason).
    'none': no valid grant governs this item, ordinary rules apply.
    Once a validly signed grant for this item's lineage and claim set
    exists, EVERY request on it (verifier and Ryan, within or beyond the
    ordinary cap) must pass this window and is tagged and debited to it.
    Expired, stopped or exhausted windows block the item. Deny by default:
    a window reserve counts as clean only with an explicit
    allowance-done line, so crashes, unknown outcomes, HTTP errors, auth,
    cost and stale results all end the window. History is never edited and
    a later global clear does not revive it."""
    st, b, why = _load_grant(root)
    led = store.ledger()
    L, fp = lineage_of(q), work_fp(q)
    binds = [e for e in led if e.get("phase") == "allowance-bind"
             and (e.get("lineage") == L or e.get("work_fp") == fp)]
    if binds:   # durably bound: authority must still be exactly this grant
        last = binds[-1]
        if st != "ok" or b.get("id") != last.get("allowance") or \
                grant_digest(b) != last.get("digest"):
            return ("blocked", None, None, "bound window authority is "
                    "absent, invalid, deleted or replaced")
    elif st != "ok":
        return "none", None, None, why
    elif b.get("lineage") != L or b.get("work_fp") != fp:
        return "none", None, None, "grant is for another lineage/claim set"
    if binds and (b.get("lineage") != L or b.get("work_fp") != fp):
        # a bound window never widens: an OR-match only finds the
        # restriction. The edited claim set or renamed lineage is blocked.
        return ("blocked", None, None, "bound window does not cover this "
                "lineage and claim set")
    bad = _shape_ok(b)
    if bad:
        return "blocked", None, None, "allowance malformed: " + bad
    try:
        t0, t1 = parse_iso(b["issued_at"]), parse_iso(b["expires_at"])
    except Exception:
        return "blocked", None, None, "allowance times unreadable"
    if not (t0 <= now < t1) or t1 - t0 > ALLOWANCE_MAX_TTL_S:
        return "blocked", None, None, "allowance expired or ttl too long"
    aid = b["id"]
    if any(e.get("phase") == "allowance-stop" and e.get("allowance") == aid
           for e in led):
        return "blocked", None, None, "allowance stopped"
    mine = [e for e in led if e.get("phase") == "reserved"
            and e.get("allowance") == aid]
    done = {e.get("rid") for e in led if e.get("phase") == "allowance-done"
            and e.get("allowance") == aid}
    if any(e["rid"] not in done for e in mine):
        return "blocked", None, None, "a window request did not finish clean"
    if len(mine) >= b["max_requests"] or role != b["roles"][len(mine)] or \
            [e["role"] for e in mine] != b["roles"][:len(mine)]:
        return "blocked", None, None, "role is not the next window step"
    if b["models"][role] != model:
        return "blocked", None, None, "window pins a different model"
    wused = {}
    for e in mine:
        wused[e["role"]] = wused.get(e["role"], 0) + 1
    for r in ROLE_CAP:   # pinned baseline: nobody else used this lineage
        if used.get(r, 0) - wused.get(r, 0) != b["baseline"][r]:
            return "blocked", None, None, "lineage counts moved off baseline"
    if used.get(role, 0) >= b["max_counts"][role]:
        return "blocked", None, None, "role max count reached"
    if not binds:   # first accepted use: bind lineage, claims and digest
        store.append({"phase": "allowance-bind", "ts": iso(now),
                      "allowance": aid, "lineage": L, "work_fp": fp,
                      "digest": grant_digest(b)})
    return "ok", aid, grant_digest(b), ""


def grant_digest_now(root, store, q, aid, now):
    """Digest of the CURRENT valid, unexpired, unstopped grant, or None."""
    st, b, _ = _load_grant(root)
    if st != "ok" or b.get("id") != aid or _shape_ok(b):
        return None
    try:
        if not (parse_iso(b["issued_at"]) <= now < parse_iso(b["expires_at"])):
            return None
    except Exception:
        return None
    if any(e.get("phase") == "allowance-stop" and e.get("allowance") == aid
           for e in store.ledger()):
        return None
    return grant_digest(b)


def allowance_stop(store, aid, now, why, kind="failure",
                   format_valid=False, supported=False):
    """Terminal. Records separate facts: format validity (qualification
    evidence) and support (eligibility for downstream steps)."""
    if aid:
        store.append({"phase": "allowance-stop", "ts": iso(now),
                      "allowance": aid, "reason": why, "kind": kind,
                      "format_valid": format_valid, "supported": supported})


def allowance_done(store, aid, rid, role, now):
    if aid:
        store.append({"phase": "allowance-done", "ts": iso(now),
                      "allowance": aid, "rid": rid, "role": role})


def _active_halt(led):
    halts = [e for e in led if e["phase"] == "halt"]
    cleared = [e for e in led if e["phase"] == "cleared"]
    if not halts:
        return None
    if cleared and led.index(halts[-1]) < led.index(cleared[-1]):
        return None
    return halts[-1]


def _io_boundary(root, store, rid, qid, role, model, snap, aid, listing,
                 now, clock, is_verify):
    """'' when the request may be sent, else a short reason. Runs under
    the store lock, reading CURRENT state: ledger, queue, assignments,
    grant. Nothing here trusts what step() read before the reserve."""
    try:
        with store.lock():
            led = store.ledger()
            h = _active_halt(led)
            if h is not None:
                return "halted: " + str(h.get("reason"))[:120]
            mine = [e for e in led if e.get("phase") == "reserved"
                    and e.get("rid") == rid]
            if len(mine) != 1 or mine[0].get("model") != model \
                    or mine[0].get("qid") != qid \
                    or mine[0].get("role") != role:
                return "own reserve line missing or changed"
            if any(e.get("rid") == rid and e.get("phase") == "result"
                   for e in led):
                return "reserve already has a result"
            if aid and any(e.get("phase") == "allowance-stop"
                           and e.get("allowance") == aid for e in led):
                return "allowance stopped"
            queue = store.queue()
            q = next((x for x in queue["questions"] if x["id"] == qid),
                     None)
            if q is None:
                return "queue entry vanished"
            cur = (load_eva_assignment(root) if q.get("kind") == "verify"
                   else load_assignments(root))
            cur_model = ((cur or {}).get("models") or {}).get(
                "eva" if q.get("kind") == "verify" else role)
            if (cur or {}).get("decided_by") != OPERATOR \
                    or cur_model != model:
                return "assignment authority or model changed"
            gnow = grant_digest_now(root, store, q, aid, clock()) \
                if aid else None
            if aid and gnow is None:
                return "grant missing, expired or invalid"
            sysm = "You are the %s in a source-bound review pipeline." % role
            snow = input_snapshot(q, role, model, sysm,
                                  build_prompt(role, q),
                                  {"a": cur, "g": gnow})
            if snow != snap:
                return "item, prompt or assignment changed after reserve"
            if not mr.price_zero(listing, model):
                return "model not price-0 in the listing"
            if not listing_fresh(listing, clock()):
                return "listing not fresh at the actual clock"
    except Exception as e:
        return "boundary check failed closed: %s" % type(e).__name__
    return ""


def step(root, post, list_models, now, record, clock=None, before_io=None):
    """One step. post(model, system, prompt, max_tokens) ->
    {'kind': 'ok'|'http'|'unknown', 'code': int, 'content': str,
     'usage': dict}. RECORD is the route record (model-availability).
    Gate+reserve+queue write are one locked transaction; the lock is not
    held across the request. Immediately before network I/O the step
    re-validates (under the store lock) halt/stop state, its own reserve
    line, operator assignment, the rendered-input snapshot, the grant
    and the price-0 listing fact; any change means NO request is sent
    (result outcome not_sent + halt; the reserve stays consumed).
    before_io is a test seam only: called after the reserve and before
    that boundary check. Returns a dict describing what happened."""
    store = Store(root)
    with store.lock():
        queue = store.queue()
        q = pick(queue)
        if q is None:
            return {"action": "idle", "calls": 0}
        qid = q["id"]
        role = next_action(q)
        is_verify = q.get("kind") == "verify"
        if is_verify:
            why_not = verify_gate(q)
            if why_not:
                q["status"] = "needs-human"
                q["reason"] = why_not
                store.save_queue(queue)
                return {"action": "needs-human", "qid": qid, "calls": 0,
                        "reason": why_not}
            assign = load_eva_assignment(root)
            if assign is None or assign.get("decided_by") != OPERATOR:
                return {"action": "needs-allocation", "calls": 0,
                        "reason": "no operator Eva assignment"}
            model = assign["models"]["eva"]
        else:
            assign = load_assignments(root)
            if assign is None:
                return {"action": "needs-allocation", "calls": 0}
            if assign.get("decided_by") != OPERATOR:
                return {"action": "needs-allocation", "calls": 0,
                        "reason": "assignments.json not made by the "
                        "operator"}
            model = assign["models"][role]
        if not is_verify:
            why_not = packet_gate(q)
            if why_not:
                q["status"] = "needs-human"
                q["reason"] = why_not
                store.save_queue(queue)
                return {"action": "needs-human", "qid": qid, "calls": 0,
                        "reason": why_not}
        if role == "ryan" and not verified_rev_ok(q):
            q["status"] = "needs-human"
            q["reason"] = ("verified markers are not bound to the current "
                           "findings/packet revision; re-verify")
            store.save_queue(queue)
            return {"action": "needs-human", "qid": qid, "calls": 0,
                    "reason": q["reason"]}
        used = lineage_counts(store, queue, q)
        if sum(used.values()) >= QUESTION_BUDGET:
            q["status"] = "needs-human"
            q["reason"] = "question budget %d requests used" % QUESTION_BUDGET
            store.save_queue(queue)
            return {"action": "needs-human", "qid": qid, "calls": 0}
        wstate, aid, gdig, wwhy = allowance_window(
            root, store, q, role, used, model, now)
        if wstate == "blocked" or (wstate == "none" and
                                   used.get(role, 0) >= ROLE_CAP[role]):
            q["status"] = "needs-human"
            q["reason"] = (role + " attempts exhausted" if wstate == "none"
                           else "allowance: " + wwhy)
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
            why_not = independent(
                listing, q["author_model"] if is_verify
                else assign["models"]["researcher"], model)
            if why_not:
                raise Halt("verifier not independent: " + why_not)
        rid = "%s-%s-%d" % (qid, role, len(store.ledger()))
        store.append({"phase": "reserved", "rid": rid, "ts": iso(now),
                      "qid": qid, "role": role, "model": model,
                      "lineage": lineage_of(q), "work_fp": work_fp(q),
                      **({"allowance": aid} if aid else {})})
        q["attempts"][role] = q["attempts"].get(role, 0) + 1
        status0 = q["status"]
        snap = input_snapshot(q, role, model, system, prompt,
                              {"a": assign, "g": gdig})
        store.save_queue(queue)
        n = q["attempts"][role]
    clock = clock or time.time
    if before_io is not None:
        before_io()
    refuse = _io_boundary(root, store, rid, qid, role, model, snap, aid,
                          listing, now, clock, is_verify)
    if refuse:
        with store.lock():
            store.append({"phase": "result", "rid": rid, "ts": iso(now),
                          "qid": qid, "role": role, "model": model,
                          "outcome": "not_sent", "usage": None,
                          "diag": {"stage": "pre-io-boundary",
                                   "class": "refused"}})
            store.append({"phase": "halt", "ts": iso(now),
                          "reason": "pre-I/O boundary refused %s: %s"
                                    % (rid, refuse)})
            allowance_stop(store, aid, now, "pre-I/O refused " + rid,
                           kind="stale")
        return {"action": "pre-io-refused", "qid": qid, "role": role,
                "reason": refuse, "calls": 0}
    res = post(model, system, prompt, CEILINGS[role], effort=EFFORT[role])
    with store.lock():
        try:
            out = settle(store, rid, qid, role, model, res, now)
        except Halt:
            allowance_stop(store, aid, now, "settle halted " + rid)
            raise
        if out:
            allowance_stop(store, aid, now, "request failed " + rid)
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
            cur = (load_eva_assignment(root) if q.get("kind") == "verify"
                   else load_assignments(root))
            cur_model = ((cur or {}).get("models") or {}).get(
                "eva" if q.get("kind") == "verify" else role)
        except Exception:
            cur, cur_model = None, None
        authority_ok = (cur or {}).get("decided_by") == OPERATOR
        try:  # re-render from the CURRENT item; fail closed
            now_prompt = build_prompt(role, q)
            now_system = ("You are the %s in a source-bound review "
                          "pipeline." % role)
        except Exception:
            now_prompt = now_system = None
        gnow = grant_digest_now(root, store, q, aid, clock()) if aid \
            else None
        try:
            if now_prompt is None:
                raise ValueError("render failed")
            now_snap = input_snapshot(q, role, model, now_system,
                                      now_prompt, {"a": cur, "g": gnow})
        except Exception:
            now_snap = None
        if (not authority_ok or cur_model != model or now_snap != snap
                or (aid and gnow is None)):
            # Raw result stays in runs/ and the call stays consumed. It is
            # never applied. A durable halt needs explicit reconciliation,
            # so the item cannot run again automatically. A hold or
            # supersession set during the call is left exactly as is; a
            # still-runnable item moves to needs-human.
            why = ("stale result not applied: item, status, assignment "
                   "authority or model changed during call %s" % rid)
            store.append({"phase": "halt", "ts": iso(now), "reason": why})
            allowance_stop(store, aid, now, why, kind="stale")
            if q.get("status") == status0 and next_action(q):
                q["status"] = "needs-human"
                q["reason"] = why
                store.save_queue(queue)
            return {"action": "stale-result-halt", "qid": qid,
                    "role": role, "status": q.get("status"), "calls": 1}
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
            if q["attempts"][role] >= ROLE_CAP[role] or \
                    q.get("kind") == "verify":
                q["status"] = "needs-human"
                q["reason"] = bad
            allowance_stop(store, aid, now, "precheck failed: " + bad,
                           kind="format-failure")
            store.save_queue(queue)
            return {"action": "precheck-failed", "qid": qid, "role": role,
                    "reason": bad, "calls": 1}
        q.pop("fb_" + role, None)
        if role == "researcher":
            q["findings"] = obj["findings"]
            q["status"] = "drafted"
            q.pop("feedback", None)
        elif role == "verifier" and q.get("kind") == "verify":
            overall, bad_ids = compute_verify(q, obj)
            q["verifier_verdict"] = {"overall": overall, "bad": bad_ids}
            q["verified_ids"] = [v["id"] for v in obj["verdicts"]
                                 if v["verdict"] == "SUPPORTED"]
            q.pop("verified_rev", None)
            if overall == "PASS":
                q["status"] = "verify-complete"
                q["verified_rev"] = verified_rev(q)
            else:
                q["status"] = "needs-human"
                q["reason"] = "claims not SUPPORTED: " + ",".join(bad_ids)
        elif role == "verifier":
            overall, verified, bad_ids = compute_overall(q, obj)
            q["verifier_verdict"] = {"overall": overall, "bad": bad_ids}
            q["verified_ids"] = verified
            q.pop("verified_rev", None)
            if overall == "PASS":
                q["status"] = "verified"
                q["verified_rev"] = verified_rev(q)
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
        if q["status"] in ("verified", "verify-complete",
                           "ready-for-chain"):
            allowance_done(store, aid, rid, role, now)
        else:   # valid format, negative verdict: qualifies format only
            allowance_stop(store, aid, now, "valid negative verdict: "
                           + q["status"], kind="negative-verdict",
                           format_valid=True, supported=False)
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
        if k == "finish_reason":
            fe = finish_enum(v)
            if fe is not None:
                out[k] = fe
            continue
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
    except (ValueError, TypeError, RecursionError, MemoryError):
        return None
    u = d.get("usage") if isinstance(d, dict) else None
    return u if isinstance(u, dict) else None


def http_post_factory(env="REQUESTY_API_KEY"):
    def post(model, system, prompt, max_tokens, effort="low"):
        if effort not in EFFORT_VALUES:
            raise Halt("invalid reasoning_effort")
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
            # reasoning_effort per role (EFFORT); budgets never raised silently.
            "max_tokens": max_tokens,
            "reasoning_effort": effort,
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
