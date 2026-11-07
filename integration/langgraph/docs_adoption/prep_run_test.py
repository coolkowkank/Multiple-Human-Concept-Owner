"""Offline tests for prep_run.py: deterministic rebuild of the recorded run inputs,
cap refusal, open-window refusal, ledger untouched, emitted receipt stageable.
No network, no window opened by prep, no spawn."""
import hashlib, json, os, stat, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import fenced_http as fh, ledger_restore, private_record as pr, prep_run

REPO = subprocess.run(["git", "-C", HERE, "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
FAIL = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: FAIL.append(n)

def fresh_ledger(d, burn=False):
    os.makedirs(d, mode=0o700)
    fh.import_historic_floor(d, 11, 11, 0, [], external_manifest_present=False)
    if burn:
        fh.burn_window(d, "00" * 32, "11" * 32, "22" * 32, "0", pending_k=1)

tmp = tempfile.mkdtemp()
L = os.path.join(tmp, "ledger"); fresh_ledger(L, burn=True)     # floor 11 + burnt K1: committed 12
ctl_before = open(os.path.join(L, "_control.ctl"), "rb").read()

# 1. cap refusal: committed 12 + K 1 > cap 12; nothing is created
rd = os.path.join(tmp, "run-cap")
try:
    prep_run.prep(rd, REPO, L, 12); refused = "no refusal"
except prep_run.PrepRefused as e:
    refused = str(e)
check("cap refusal: committed 12 + K1 > cap 12 refuses with the exact accounting, nothing created",
      "committed 12" in refused and "cap 12" in refused and not os.path.exists(rd))

# 2. happy path with the amended cap 13
rd = os.path.join(tmp, "run-a")
s = prep_run.prep(rd, REPO, L, 13)
brief = open(os.path.join(rd, "cfg", "brief.md"), "rb").read()
check("brief bytes exact: 8807 bytes, recorded sha256",
      len(brief) == 8807 and hashlib.sha256(brief).hexdigest() == prep_run.BRIEF_SHA256)
cfg = json.load(open(os.path.join(rd, "cfg", "c.json")))
check("config shape: allowed keys only, one coordinator seat, recorded model/budget/tokens",
      set(cfg) <= {"key_file", "seats", "brief_extra_file", "stop_after", "preflight", "no_verify_command"}
      and set(cfg["seats"]) == {"coordinator"}
      and cfg["seats"]["coordinator"] == {"model": "novita/ling-3.1-flash", "epoch": "docs1",
                                          "budget": 1, "max_tokens": 4096}
      and cfg["stop_after"] == 1 and cfg["no_verify_command"] is True)
body = json.load(open(os.path.join(rd, "pending.json")))
check("receipt body: pending-window, k 1, seq continues the ledger, recorded epoch budgets",
      body["kind"] == "pending-window" and body["k"] == 1 and body["seq"] == 2
      and body["epoch_budgets"] == {"novita-ling-3-1-flash.docs1.jsonl": 1}
      and body["prev_receipt_hash"] == "22" * 32 and "receipt_hash" not in body)
tok = open(os.path.join(rd, "window.token")).read()
check("token: fresh 64-hex, 0600, only its sha256 (owner_hash) is in the receipt",
      len(tok) == 64 and stat.S_IMODE(os.lstat(os.path.join(rd, "window.token")).st_mode) == 0o600
      and body["owner_hash"] == hashlib.sha256(tok.encode()).hexdigest())
check("ledger untouched by prep (read-only)", open(os.path.join(L, "_control.ctl"), "rb").read() == ctl_before)
check("wrapper's local receipt copy present with the exact canonical bytes",
      open(os.path.join(rd, "window-receipt-%s.json" % body["nonce"]), "rb").read()
      == json.dumps(body, sort_keys=True).encode())

# 3. the emitted receipt is stageable + loadable by the record rules, and binds this ledger
fin = pr.finalize_receipt(body)
check("receipt_hash = sha256 of the canonical body, matches prep.json",
      fin["receipt_hash"] == hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
      and fin["receipt_hash"] == s["receipt_hash"])
tar, tar_sha = ledger_restore.bundle(L)
stage_dir = os.path.join(tmp, "stage")
msha = pr.stage(stage_dir, "pending", tar, rev_no=4, prev_revision_id="filerevision-test",
                prev_manifest_sha="00" * 32, last_receipt_hash="22" * 32, seq=1, total=12, receipt=fin)
r = pr.load(stage_dir)
check("private_record stage+load round-trip: binds this ledger's tar/seq/tips",
      r["manifest"]["tar_sha256"] == tar_sha and r["receipt"]["nonce"] == body["nonce"])

# 4. open window in the ledger: prep refuses
L2 = os.path.join(tmp, "ledger2"); fresh_ledger(L2)
fh.HTTP_LIFETIME_CAP = 13          # in-process amended cap, as in the gate-on e2e; prep itself takes cap as an argument
fh.open_window(L2, 1, "ab" * 32, "cd" * 32, "ef" * 32, "0", "99" * 32)
try:
    prep_run.prep(os.path.join(tmp, "run-open"), REPO, L2, 13); refused2 = "no refusal"
except prep_run.PrepRefused as e:
    refused2 = str(e)
check("open window in the ledger: prep refuses", "open" in refused2)

# 5. existing run dir: refused (never clobber)
try:
    prep_run.prep(rd, REPO, L, 13); refused3 = "no refusal"
except prep_run.PrepRefused as e:
    refused3 = str(e)
check("existing run dir refused", "clobber" in refused3)

# 6. a second prep into a fresh dir: identical brief/config/argv binding, fresh token+nonce
rd2 = os.path.join(tmp, "run-b")
s2 = prep_run.prep(rd2, REPO, L, 13)
body2 = json.load(open(os.path.join(rd2, "pending.json")))
check("same path-independent inputs, but path-bound hashes differ across run dirs; token+nonce always fresh",
      s["brief_sha256"] == s2["brief_sha256"] and s["epoch_budgets"] == s2["epoch_budgets"]
      and s["config_hash"] != s2["config_hash"] and body["nonce"] != body2["nonce"]
      and open(os.path.join(rd, "window.token")).read() != open(os.path.join(rd2, "window.token")).read())

print("FAILED" if FAIL else "ALL PASS"); sys.exit(1 if FAIL else 0)
