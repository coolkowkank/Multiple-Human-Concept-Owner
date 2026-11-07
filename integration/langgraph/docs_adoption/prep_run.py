"""Offline (re)prep of the run dir for the ONE bounded docs-adoption assessment (K=1).

Why this exists: the 2026-11-07 sandbox loss showed the run dir (lane,
config, brief, token, prep data) was local-only, while only the ledger and
the pending receipt were durable in the private File. The brief bytes are
deterministic from the pinned public docs and every other input is small
and fixed, so the whole pre-window state can be rebuilt by one command
instead of hand reconstruction.

This script NEVER: opens a window, spawns the entry, uploads anything,
touches the network, or prints/copies the window token. The ledger dir is
only READ. It REFUSES (fail closed) when the pin or the brief bytes differ
from the recorded values, the ledger is not clean, a window is open or a
halt exists, or the explicit lifetime cap has no room for K. The cap is a
required argument: it is an owner/main amendment, never assumed here.

Layout it creates (run_dir, fresh 0700; an existing dir is refused):
  lane/                  fresh git lane from init_repo (blueprint roster)
  cfg/brief.md           the exact recorded brief bytes (0600)
  cfg/c.json             live config (0600). key_file points at
                         cfg/requesty.key, which is written 0600 from the
                         vault only at go time; it is never created here.
                         config_hash covers config+roster+brief bytes, not
                         the key, so placing the key later changes nothing.
  window.token           fresh run token (0600). Only its sha256
                         (owner_hash) leaves this directory, in the receipt.
  window-receipt-<nonce>.json  canonical receipt bytes (0600); at go time
                         the wrapper reads this exact file from its state
                         dir and compares it field by field to the window.
  prep.json              every pin/hash/path + ledger accounting (no secrets)
  pending.json           the pending-window receipt BODY (no receipt_hash),
                         ready for private_record staging and upload BEFORE
                         any open_window call.
"""
import hashlib, json, os, secrets, stat, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import bounded_run as br
import fenced_http as fh
import ledger_restore
import pack
import langgraph_team as lt

# Recorded run pins (the cap-12 lineage). Changing any of these is a new
# run shape and needs the same review + amendment path as the original.
PROPOSAL_PIN = "fa6cad803ff28414329edbd98d596e3735803720"   # docs source (proposal/cap12-v5)
BRIEF_SHA256 = "952fe75e9c07ac0f42ea497453fd3011b76d4f0214b8baab7ead89f42fac8c6b"
BRIEF_BYTES = 8807
MODEL = "novita/ling-3.1-flash"
SEAT = "coordinator"
EPOCH = "docs1"
K = 1
MAX_TOKENS = 4096
STOP_AFTER = 1
DEADLINE_S = 80
THREAD = "live-1"
RECORDED_EPOCH_BUDGETS = {"novita-ling-3-1-flash.docs1.jsonl": 1}


class PrepRefused(Exception):
    pass


def _write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def _committed(c):
    return c["floor"] + sum(w["k"] for w in c["windows"]
                            if not (w["kind"] == "window-burn" and w["supersedes"]))


def prep(run_dir, repo, ledger_dir, cap):
    """Build the complete pre-window run state. Returns the prep summary
    (also written to prep.json). Raises PrepRefused and leaves nothing
    behind on any failed check."""
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        raise PrepRefused("cap must be a positive int (the explicit owner/main amendment)")
    if os.path.exists(run_dir):
        raise PrepRefused("run dir already exists; refusing to clobber: " + run_dir)

    r = subprocess.run(["git", "-C", repo, "cat-file", "-t", PROPOSAL_PIN],
                       capture_output=True, text=True)
    if r.returncode != 0 or r.stdout.strip() != "commit":
        raise PrepRefused("proposal pin %s is not a commit in %s" % (PROPOSAL_PIN, repo))
    code = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

    brief, _texts = pack.build(repo, PROPOSAL_PIN)
    if len(brief) != BRIEF_BYTES or hashlib.sha256(brief).hexdigest() != BRIEF_SHA256:
        raise PrepRefused("brief bytes differ from the recorded pin (docs changed?)")

    c = fh.read_control(ledger_dir)
    if c["problems"]:
        raise PrepRefused("ledger control invalid: " + c["problems"][0])
    res, halted, ok, _hs, tips = fh._log_scan(ledger_dir)
    if not ok:
        raise PrepRefused("ledger log chain broken")
    if halted:
        raise PrepRefused("ledger is halted; a halt is cleared only by main's go")
    if c["windows"] and c["windows"][-1]["kind"] == "window-open":
        raise PrepRefused("a window is open; typed-close or restore first")
    committed = _committed(c)
    if committed + K > cap:
        raise PrepRefused(
            "lifetime cap has no room: committed %d (floor %d + windows) + K %d > cap %d; "
            "a new cap amendment is required before any re-prep" % (committed, c["floor"], K, cap))
    tar, tar_sha = ledger_restore.bundle(ledger_dir)
    del tar
    w = c["windows"][-1] if c["windows"] else None
    prev_receipt = w["receipt_hash"] if w else "0"
    seq = (w["seq"] if w else 0) + 1

    os.makedirs(run_dir, mode=0o700)
    try:
        lane = os.path.join(run_dir, "lane")
        cfgd = os.path.join(run_dir, "cfg")
        os.makedirs(cfgd, mode=0o700)
        brief_path = os.path.join(cfgd, "brief.md")
        _write_private(brief_path, brief)
        config = {"key_file": os.path.join(cfgd, "requesty.key"),
                  "brief_extra_file": brief_path,
                  "stop_after": STOP_AFTER, "preflight": {},
                  "no_verify_command": True,
                  "seats": {SEAT: {"model": MODEL, "epoch": EPOCH,
                                   "budget": K, "max_tokens": MAX_TOKENS}}}
        config_path = os.path.join(cfgd, "c.json")
        _write_private(config_path, json.dumps(config, sort_keys=True).encode())
        lt.init_repo(lane)
        db = os.path.join(run_dir, "entry.db")
        argv, eb, why = br.live_binding(lane, db, config_path, THREAD)
        if why:
            raise PrepRefused("entry binding: " + why)
        if dict(eb) != RECORDED_EPOCH_BUDGETS:
            raise PrepRefused("epoch budgets differ from the recorded run: %r" % (eb,))
        config_hash = br.live_config_hash(lane, config_path)

        token = secrets.token_hex(32)
        _write_private(os.path.join(run_dir, "window.token"), token.encode())
        owner_hash = hashlib.sha256(token.encode()).hexdigest()
        nonce = secrets.token_hex(32)

        body = {"kind": "pending-window", "seq": seq, "k": K, "nonce": nonce,
                "config_hash": config_hash,
                "argv_sha256": hashlib.sha256("\0".join(argv).encode()).hexdigest(),
                "epoch_budgets": dict(eb),
                "prev_receipt_hash": prev_receipt, "tar_sha256": tar_sha,
                "tips": tips, "owner_hash": owner_hash}
        canonical = json.dumps(body, sort_keys=True).encode()
        receipt_hash = hashlib.sha256(canonical).hexdigest()
        _write_private(os.path.join(run_dir, "window-receipt-%s.json" % nonce), canonical)
        _write_private(os.path.join(run_dir, "pending.json"), canonical)

        summary = {"purpose": "ONE bounded docs-adoption assessment (K=1), pre-window state only",
                   "created_by": "docs_adoption/prep_run.py (offline; no window, no spawn, no upload)",
                   "proposal_pin": PROPOSAL_PIN, "observed_code_head": code,
                   "brief_sha256": BRIEF_SHA256, "brief_bytes": BRIEF_BYTES,
                   "model": MODEL, "seat": SEAT, "epoch": EPOCH, "k": K,
                   "max_tokens": MAX_TOKENS, "stop_after": STOP_AFTER,
                   "deadline_s": DEADLINE_S, "thread": THREAD,
                   "cap_argument": cap, "ledger_committed_before": committed,
                   "ledger": {"prev_receipt_hash": prev_receipt, "seq": seq,
                              "tar_sha256": tar_sha, "tips": tips},
                   "config_hash": config_hash, "argv": argv,
                   "argv_sha256": body["argv_sha256"],
                   "epoch_budgets": dict(eb),
                   "receipt_hash": receipt_hash,
                   "next_steps": ["stage pending.json via private_record and upload the new "
                                  "pending revision to the private File (before any open)",
                                  "main ack, then open_window with the amended cap in-process",
                                  "separate go, then bounded_run.run_live with deadline_s",
                                  "key file cfg/requesty.key written 0600 from the vault at go time only"]}
        _write_private(os.path.join(run_dir, "prep.json"),
                       json.dumps(summary, indent=2, sort_keys=True).encode())
        os.chmod(os.path.join(run_dir, "prep.json"), 0o600)
        fh._fsync_dir(run_dir)
        return summary
    except BaseException:
        import shutil
        shutil.rmtree(run_dir, ignore_errors=True)
        raise
