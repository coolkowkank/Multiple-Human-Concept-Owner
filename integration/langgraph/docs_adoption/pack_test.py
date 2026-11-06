"""Offline tests of the docs-adoption pack. No provider IO."""
import hashlib, json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import pack
REPO = subprocess.run(["git", "-C", HERE, "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
COMMIT = subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
FAIL = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: FAIL.append(n)
b1, texts = pack.build(REPO, COMMIT); b2, _ = pack.build(REPO, COMMIT)
check("brief is deterministic and within 16 KB", b1 == b2 and len(b1) <= pack.MAX_BRIEF)
check("brief holds all four docs and the task, and no key or secret-looking text", all(("=== FILE: %s ===" % p).encode() in b1 for p in pack.DOCS) and b"api_key" not in b1.lower() and b"Bearer" not in b1)
sent = [s.strip() for s in texts["docs/operating-rules.md"].split("\n") if len(s.strip()) > 30][0]
good = json.dumps({"first_brief": "Build a unit converter CLI. Coordinator owns the brief.", "gaps": [{"file": "docs/operating-rules.md", "quote": sent, "question": "Who decides when the batch is done?"}]})
s = pack.score(good, texts)
check("grounded answer passes", s["pass"] and s["gaps_grounded"] == 1)
check("not JSON: scored, no exception, no pass", not pack.score("sure! here you go", texts)["pass"])
check("extra key refused", not pack.score(json.dumps({"first_brief": "x", "gaps": [], "extra": 1}), texts)["keys_ok"])
inv = json.dumps({"first_brief": "x", "gaps": [{"file": "docs/operating-rules.md", "quote": "this sentence is not in the file at all", "question": "q?"}]})
check("invented quote is ungrounded and fails", pack.score(inv, texts)["gaps_ungrounded"] == 1 and not pack.score(inv, texts)["pass"])
wrongfile = json.dumps({"first_brief": "x", "gaps": [{"file": "docs/delegation.md", "quote": sent, "question": "q?"}]})
check("quote from a different file than named fails", not pack.score(wrongfile, texts)["pass"] if sent not in texts["docs/delegation.md"] else True)
dup = json.dumps({"first_brief": "x", "gaps": [{"file": "docs/operating-rules.md", "quote": sent, "question": "a?"}] * 2})
check("duplicate quote counted once", pack.score(dup, texts)["gaps_grounded"] == 1 and pack.score(dup, texts)["gaps_duplicate"] == 1)
many = json.dumps({"first_brief": "x", "gaps": [{"file": "docs/operating-rules.md", "quote": sent, "question": "a?"}] * 9})
check("more than 8 gaps fails", pack.score(many, texts)["gaps_over_limit"] == 1 and not pack.score(many, texts)["pass"])
long_ = json.dumps({"first_brief": "w " * 121, "gaps": [{"file": "docs/operating-rules.md", "quote": sent, "question": "a?"}]})
check("first_brief over 120 words fails", not pack.score(long_, texts)["pass"])
check("whitespace-only differences in a quote are tolerated", pack.score(json.dumps({"first_brief": "x", "gaps": [{"file": "docs/operating-rules.md", "quote": sent.replace(" ", "  ", 1), "question": "q?"}]}), texts)["gaps_grounded"] == 1)
for nm, bad in (("int", 5), ("list", ["x"]), ("null", None), ("object", {"a": 1})):
    for fld in ("quote", "question", "file"):
        g = {"file": "docs/operating-rules.md", "quote": sent, "question": "q?"}; g[fld] = bad
        try: r = pack.score(json.dumps({"first_brief": "x", "gaps": [g]}), texts); okk = r["pass"] is False and r["gaps_ungrounded"] == 1
        except Exception as e: okk = False
        check("non-string %s in %s: scored false without throwing" % (nm, fld), okk)
for nm, bad in (("gaps null", {"first_brief": "x", "gaps": None}), ("gaps object", {"first_brief": "x", "gaps": {}}), ("first_brief int", {"first_brief": 3, "gaps": []}), ("gap is a string", {"first_brief": "x", "gaps": ["s"]}), ("top-level list", [1])):
    try: r = pack.score(json.dumps(bad), texts); okk = r["pass"] is False
    except Exception: okk = False
    check("shape %s: false without throwing" % nm, okk)
print("FAILED" if FAIL else "ALL PASS"); sys.exit(1 if FAIL else 0)
