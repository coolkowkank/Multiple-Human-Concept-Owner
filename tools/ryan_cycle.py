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
    'ready-for-chain' (Sam -> Coordinator -> owner decides).
"""
import json, os, sys, datetime, time, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model_resources as mr

BASE_URL = "https://router.requesty.ai/v1"
# CANDIDATES only (owner 2026-11-04: Ryan chooses the role models).
# Nothing here is an assignment. BOOTSTRAP_RYAN is the one default: the
# route Ryan uses to make the allocation decision itself, because Ryan
# cannot choose his own model before he has one. It is gated like any
# other call (fresh price-0 listing, ledger caps).
CANDIDATES = {
    "researcher": "nvidia/nemotron-3-ultra-550b-a55b",
    "verifier": "google/gemma-4-31b-it",
    "ryan": "nvidia/nemotron-3-ultra-550b-a55b",
}
BOOTSTRAP_RYAN = CANDIDATES["ryan"]
BLOCKED_STATUS = ("not-qualified", "uncallable", "capped", "cooldown")
ROLES = ("researcher", "verifier", "ryan")
CEILINGS = {"researcher": 2048, "verifier": 1536, "ryan": 2048,
            "allocation": 1024}
ROLE_CAP = {"researcher": 2, "verifier": 2, "ryan": 2}  # per question
DAILY_CAP = 24      # 4 cycles x 6 requests, all three roles combined
CYCLES_PER_DAY = 4
SPACING_S = 10
MAX_INPUT_BYTES = 12288
FIRST_PASS = ("SUPPORTED",)


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


def family(model_id):
    return model_id.split("/")[0]


def validate_assignments(assign, record, listing, now):
    """Mechanical gate on Ryan's choice. Returns '' or the reason.
    Ryan may not waive: exact price-0 in the fresh listing, verifier
    different execution AND different model family from the researcher,
    routes recorded not-qualified/uncallable/capped/cooldown, provider
    blocks, or the per-role justification."""
    if not isinstance(assign, dict) or set(assign.get("models", {})) != \
            set(ROLES):
        return "assignments must name exactly researcher, verifier, ryan"
    m = assign["models"]
    why = assign.get("why", {})
    for r in ROLES:
        if not isinstance(why.get(r), str) or len(why[r].strip()) < 10:
            return "role %s needs a justification" % r
        if not listing_fresh(listing, now):
            return "no fresh named-source listing"
        if not mr.price_zero(listing, m[r]):
            return "%s not price-0 in the fresh listing" % m[r]
        rec = mr.get_route(record, m[r]) if record else None
        if rec and rec.get("status") in BLOCKED_STATUS:
            return "%s recorded %s" % (m[r], rec["status"])
        if rec and rec.get("provider") in record.get("provider_blocks", {}):
            return "provider of %s is blocked" % m[r]
    if m["verifier"] == m["researcher"]:
        return "verifier must be a different model than the researcher"
    if family(m["verifier"]) == family(m["researcher"]):
        return "verifier must be a different model family"
    return ""


def load_assignments(root):
    p = os.path.join(root, "assignments.json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def allocate(root, post, list_models, record, now):
    """Ryan's model-backed allocation decision: ONE request, counted in
    the daily cap like any other. The choice is saved ONLY if it passes
    validate_assignments; otherwise it is stored as rejected and a human
    decides. Ryan's choice is a decision, not proof the routes work:
    cycle 1 tests them."""
    store = Store(root)
    state, why = ledger_gate(store, now, None)
    if state == "wait":
        return {"action": "wait", "reason": why, "calls": 0}
    listing = list_models()
    free_gate(listing, BOOTSTRAP_RYAN, now)
    pool = sorted(m["id"] for m in listing.get("data", [])
                  if mr.price_zero(listing, m["id"]))
    prompt = ("Choose one model per role (researcher, verifier, ryan) "
              "from this price-0 list ONLY. Verifier must be a different "
              "model family than the researcher. Candidates already "
              "tried: %s. Route record: %s\nPrice-0 ids: %s\nReply "
              'with ONE JSON object: {"models":{"researcher":"id",'
              '"verifier":"id","ryan":"id"},"why":{"researcher":"...",'
              '"verifier":"...","ryan":"..."}}') % (
                  json.dumps(CANDIDATES),
                  json.dumps((record or {}).get("routes", [])), pool)
    system = "You are Ryan, Team Resources."
    if len((system + prompt).encode()) > MAX_INPUT_BYTES:
        return {"action": "needs-human", "reason": "allocation input too "
                "large", "calls": 0}
    rid = "alloc-%d" % len(store.ledger())
    store.append({"phase": "reserved", "rid": rid, "ts": iso(now),
                  "qid": "alloc", "role": "allocation",
                  "model": BOOTSTRAP_RYAN})
    res = post(BOOTSTRAP_RYAN, system, prompt, CEILINGS["allocation"])
    out = settle(store, rid, "alloc", "allocation", BOOTSTRAP_RYAN, res, now)
    if out:
        return out
    store.write_run("alloc", "allocation-%d.txt" % len(store.ledger()),
                    res["content"])
    try:
        obj = strict_json(res["content"])
    except ValueError as e:
        return {"action": "rejected", "reason": "format: %s" % e,
                "calls": 1}
    bad = validate_assignments(obj, record, listing, now)
    if bad:
        return {"action": "rejected", "reason": bad, "calls": 1}
    obj["decided_by"] = "ryan"
    obj["decided_at"] = iso(now)
    with open(os.path.join(root, "assignments.json"), "w") as f:
        json.dump(obj, f, indent=2)
    return {"action": "assigned", "calls": 1, "models": obj["models"]}


def settle(store, rid, qid, role, model, res, now):
    """Record a result line; returns a dict for failures, None on 'ok'.
    Raises Halt for 429/unknown/auth/nonzero cost (PAUSED)."""
    done = {"phase": "result", "rid": rid, "ts": iso(now), "qid": qid,
            "role": role, "model": model, "usage": res.get("usage")}
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
            fb = "\nCorrection feedback from the verifier:\n" + q["feedback"]
        return ("Question: %s\nSource packet (cite ONLY these ids; never "
                "add sources from memory):\n%s\n%s\nReply with ONE JSON "
                'object: {"findings":[{"id":"C1","claim":"...",'
                '"sources":["P1"],"status":"SUPPORTED_BY_PACKET|'
                'UNVERIFIED|MISSING_SOURCE"}],"summary":"..."}. A claim '
                "with status SUPPORTED_BY_PACKET needs >=1 source id.") % (
                    q["question"], packet, fb)
    if role == "verifier":
        return ("Check each finding against the packet passages only. For "
                "every finding id give SUPPORTED, NOT_SUPPORTED or "
                "UNVERIFIED and quote the passage evidence.\nPacket:\n%s\n"
                "Findings:\n%s\nReply with ONE JSON object: "
                '{"verdicts":[{"id":"C1","verdict":"SUPPORTED|'
                'NOT_SUPPORTED|UNVERIFIED","evidence":"..."}]}') % (
                    packet, json.dumps(q["findings"], indent=1))
    ok = [f for f in q["findings"] if f["id"] in q["verified_ids"]]
    return ("Question: %s\nVerified findings only:\n%s\nFor each, rate "
            "usefulness to the team's speed and token use and propose an "
            "action for the Coordinator. Proposals are not adopted by you. "
            'Reply with ONE JSON object: {"usefulness":[{"id":"C1",'
            '"useful":"HIGH|MEDIUM|LOW|NONE","why":"...",'
            '"proposed_action":"..."}],"note":"..."}') % (
                q["question"], json.dumps(ok, indent=1))


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
        for v in vs:
            if v.get("verdict") not in ("SUPPORTED", "NOT_SUPPORTED",
                                        "UNVERIFIED"):
                return "bad verdict value"
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


def step(root, post, list_models, now):
    """One step. post(model, system, prompt, max_tokens) ->
    {'kind': 'ok'|'http'|'unknown', 'code': int, 'content': str,
     'usage': dict}. Returns a dict describing what happened."""
    store = Store(root)
    queue = store.queue()
    q = pick(queue)
    if q is None:
        return {"action": "idle", "calls": 0}
    role = next_action(q)
    assign = load_assignments(root)
    if assign is None:
        return {"action": "needs-allocation", "calls": 0}
    model = assign["models"][role]
    if role == "verifier" and (model == assign["models"]["researcher"]
                               or family(model) == family(
                                   assign["models"]["researcher"])):
        raise Halt("verifier not independent of researcher")
    if q["attempts"].get(role, 0) >= ROLE_CAP[role]:
        q["status"] = "needs-human"
        q["reason"] = role + " attempts exhausted"
        store.save_queue(queue)
        return {"action": "needs-human", "qid": q["id"], "calls": 0}
    try:
        state, why = ledger_gate(store, now, q["id"])
    except Halt as e:
        raise
    if state == "wait":
        return {"action": "wait", "reason": why, "calls": 0}
    prompt = build_prompt(role, q)
    system = "You are the %s in a source-bound review pipeline." % role
    if len((system + prompt).encode()) > MAX_INPUT_BYTES:
        q["status"] = "needs-human"
        q["reason"] = "input over %d bytes" % MAX_INPUT_BYTES
        store.save_queue(queue)
        return {"action": "needs-human", "qid": q["id"], "calls": 0}
    free_gate(list_models(), model, now)
    rid = "%s-%s-%d" % (q["id"], role, len(store.ledger()))
    store.append({"phase": "reserved", "rid": rid, "ts": iso(now),
                  "qid": q["id"], "role": role, "model": model})
    q["attempts"][role] = q["attempts"].get(role, 0) + 1
    store.save_queue(queue)
    res = post(model, system, prompt, CEILINGS[role])
    out = settle(store, rid, q["id"], role, model, res, now)
    if out:
        return out
    n = q["attempts"][role]
    store.write_run(q["id"], "%s-%d.txt" % (role, n), res["content"])
    try:
        obj = strict_json(res["content"])
        bad = precheck(role, q, obj)
    except ValueError as e:
        obj, bad = None, "format: %s" % e
    if bad:
        q["feedback"] = "format/consistency problem: " + bad
        if role == "researcher" and q["attempts"][role] < ROLE_CAP[role]:
            pass  # stays 'open' for one correction
        elif role == "researcher":
            q["status"] = "needs-human"; q["reason"] = bad
        elif q["attempts"][role] >= ROLE_CAP[role]:
            q["status"] = "needs-human"; q["reason"] = bad
        store.save_queue(queue)
        return {"action": "precheck-failed", "qid": q["id"], "role": role,
                "reason": bad, "calls": 1}
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
            q["reason"] = "verification failed, no correction attempt left"
    else:
        q["ryan_review"] = obj
        q["status"] = "ready-for-chain"
    store.save_queue(queue)
    return {"action": "done-" + role, "qid": q["id"], "status": q["status"],
            "calls": 1}


def jobdesc_scan(repo, root, now, max_packet=8, passage_chars=360):
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
    reps = sorted((v for v in runs.values() if len(v) > 1),
                  key=lambda v: -len(v) * len(v[0][2]))[:max_packet]
    packet = []
    for n, v in enumerate(reps, 1):
        packet.append({"id": "P%d" % n,
                       "title": "repeated passage x%d" % len(v),
                       "locations": ["%s:%d" % (r, i) for r, i, _ in v],
                       "passage": v[0][2][:passage_chars]})
    if not packet:
        base["note"] = "no repeated lines of 40+ chars found"
        with open(sp, "w") as f:
            json.dump(base, f, indent=2)
        return {"action": "changed-no-repeats", "total_bytes": total,
                "calls": 0}
    q = store.queue()
    qid = "jobdesc-" + digest[:8]
    if not any(x["id"] == qid for x in q["questions"]):
        q["questions"].append({
            "id": qid, "status": "open", "attempts": {},
            "question": "Which of these repeated passages in the project "
                        "job descriptions can be shortened or merged "
                        "without removing a duty or a safety check? Cite "
                        "packet ids only.",
            "packet": packet, "kind": "jobdesc-efficiency"})
        store.save_queue(q)
    with open(sp, "w") as f:
        json.dump(base, f, indent=2)
    return {"action": "enqueued", "qid": qid, "total_bytes": total,
            "calls": 0}


def http_post_factory(env="REQUESTY_API_KEY"):
    def post(model, system, prompt, max_tokens):
        key = os.environ.get(env)
        if not key:
            raise Halt("missing key env " + env)
        body = json.dumps({
            "model": model, "temperature": 0,
            "max_completion_tokens": max_tokens,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(
            BASE_URL + "/chat/completions", data=body, headers={
                "content-type": "application/json",
                "authorization": "Bearer " + key,
                "user-agent": "team-launcher-ryan-cycle/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read())
            return {"kind": "ok", "usage": data.get("usage"),
                    "content": data["choices"][0]["message"]["content"] or ""}
        except urllib.error.HTTPError as e:
            return {"kind": "http", "code": e.code, "usage": None,
                    "content": e.read()[:300].decode("utf-8", "replace")}
        except (urllib.error.URLError, TimeoutError, OSError,
                ValueError, KeyError):
            return {"kind": "unknown", "usage": None, "content": ""}
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
