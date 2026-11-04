"""Eva source-fidelity support: deterministic pre-check + queue intake.

MECHANICAL ONLY. This is text matching, not a verdict and not a model:
  - quotes: a "double-quoted" string in a claim is FOUND if it occurs
    (whitespace-normalised, case-insensitive) in a cited passage,
    IN_OTHER_SOURCE if only in an uncited passage, else NOT_FOUND.
  - numbers: each numeric token in a claim is PRESENT/ABSENT in the cited
    passages. ABSENT can mean computed, rephrased or taken from elsewhere;
    PRESENT does not check units, denominators or context.
Nothing here marks a claim true or false. Eva (a model verifier) is
assigned but not wired or qualified; intake only builds a HELD queue item.

Usage:
  eva_check.py check  PUBLICATION.md PACKET.json   -> JSON report
  eva_check.py intake PUBLICATION.md PACKET.json QUEUE_ID [AUTHOR_MODEL]
PACKET.json: a list of {"id","title","locations","passage"}; a passage
belongs to a claim group when the title starts with the claim's tag (M1..).
"""
import json
import re
import sys

NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?")
TAG = re.compile(r"^\*\*(M\d+)\.")
# ONLY straight double-quoted strings of 6+ characters are checked as
# quotes; single quotes, curly quotes and shorter strings are not.
QUOTE = re.compile(r'"([^"\n]{6,})"')


def norm(t):
    return " ".join(str(t).split()).lower()


def parse_publication(md):
    """Claims = bullet lines under 'Evidence', tagged by the preceding
    '**Mx. ...**' header line. Returns [{id,tag,text}]."""
    claims, tag, n, in_ev = [], None, 0, False
    for line in md.splitlines():
        if line.startswith("## "):
            in_ev = line.strip().lower() == "## evidence"
            tag = None
            continue
        if not in_ev:
            continue
        m = TAG.match(line.strip())
        if m:
            tag, n = m.group(1), 0
            continue
        if tag and line.lstrip().startswith("- "):
            n += 1
            claims.append({"id": "%s.%d" % (tag, n), "tag": tag,
                           "text": line.lstrip()[2:].strip()})
    return claims


def passages_for(packet, tag):
    return [p for p in packet if str(p.get("title", "")).split()[:1] == [tag]]


def numbers(text):
    return sorted({m.group(0).rstrip("%") if False else m.group(0)
                   for m in NUM.finditer(text)})


def num_in(tok, text):
    """Exact numeric token match: '13%' does not match '13.7%' or '113%',
    '13' does not match '13.7' or '13%'. Units, scale, denominators and
    context are never validated."""
    pct = tok.endswith("%")
    bare = tok.rstrip("%")
    tail = r"%" if pct else r"(?![\w%])(?!\.\d)"
    return re.search(r"(?<![\w.,])" + re.escape(bare) + tail,
                     text) is not None


def check_claim(claim, packet):
    own = passages_for(packet, claim["tag"])
    own_txt = norm(" ".join(p["passage"] for p in own))
    other_txt = norm(" ".join(p["passage"] for p in packet
                              if p not in own))
    res = {"id": claim["id"], "tag": claim["tag"],
           "cited_passages": [p["id"] for p in own],
           "quotes": [], "numbers_present": [], "numbers_absent": []}
    if not own:
        res["flag"] = "NO_PASSAGE_FOR_TAG"
    for q in QUOTE.findall(claim["text"]):
        nq = norm(q)
        st = ("FOUND" if nq in own_txt else
              "IN_OTHER_SOURCE" if nq in other_txt else "NOT_FOUND")
        res["quotes"].append({"len": len(q), "status": st})
    for tok in numbers(claim["text"]):
        hit = num_in(tok, own_txt)
        (res["numbers_present"] if hit else res["numbers_absent"]).append(tok)
    res["review"] = bool(res["numbers_absent"] or any(
        q["status"] != "FOUND" for q in res["quotes"]) or res.get("flag"))
    return res


def report(md, packet):
    rows = [check_claim(c, packet) for c in parse_publication(md)]
    return {"kind": "mechanical-text-match-not-a-verdict-not-Eva",
            "review_false_means": "no flagged quote or number by this "
            "mechanical match only; NOT a publication pass, NOT fact "
            "validation (units, denominators, context, paraphrase, "
            "unquoted claims and non-straight quotes are unchecked)",
            "claims": len(rows),
            "needs_human_or_model_review": sum(r["review"] for r in rows),
            "rows": rows}


def intake(md, packet, queue_id, author_model=None):
    """HELD queue item shaped for the runner's verify kind. Fails closed
    (ValueError) on no claims, an empty packet, a claim group without a
    passage, or a truncated/empty passage. author_model (the publication
    author's model id, if known) is stored for the independence gate; the
    runner refuses to run an item without it. Not runnable until an
    operator sets status to 'ready-verify', an Eva model is assigned
    (assign_eva_manual) and the route is qualified."""
    claims = parse_publication(md)
    if not claims or not packet:
        raise ValueError("no claims or no packet: unsupported source")
    for p in packet:
        t = str(p.get("passage", ""))
        if not t.strip() or "[truncated" in t:
            raise ValueError("partial source passage %s" % p.get("id"))
    findings = []
    for c in claims:
        ids = [p["id"] for p in passages_for(packet, c["tag"])]
        if not ids:
            raise ValueError("claim %s has no source passage (%s)"
                             % (c["id"], c["tag"]))
        findings.append({"id": c["id"], "claim": c["text"], "sources": ids,
                         "status": "UNVERIFIED"})
    item = {"id": queue_id, "kind": "verify", "status": "held",
            "lineage": queue_id, "attempts": {},
            "question": "Verify each publication claim against the cited "
                        "source passages only.",
            "packet": packet, "findings": findings,
            "note": "Held: verifier not wired or qualified. Intake of a "
                    "publication, not a Researcher run. Mechanical pre-check "
                    "via eva_check.py is not a verdict."}
    if author_model:
        item["author_model"] = author_model
    return item


def main(argv):
    if len(argv) < 4 or argv[1] not in ("check", "intake") or (
            argv[1] == "intake" and len(argv) < 5):
        print(__doc__)
        return 2
    md = open(argv[2]).read()
    packet = json.load(open(argv[3]))
    if argv[1] == "check":
        print(json.dumps(report(md, packet), indent=1))
    else:
        print(json.dumps(intake(md, packet, argv[4],
                                argv[5] if len(argv) > 5 else None),
                         indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
