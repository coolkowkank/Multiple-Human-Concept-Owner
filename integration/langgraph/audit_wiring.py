"""Opt-in audit wrapper for fenced model seats (offline-tested).

Order: GuardedAdapter(AuditedFenced(FencedHttpAdapter)). Enabled only when
the operator passes an audit directory (env LG_AUDIT_DIR); off by default.

What it adds on top of the product's PromptAuditAdapter (vendored byte-exact
in launcher/prompt_audit.py, md5 pinned below):
- the exact system/prompt the runtime passes is checked against the prompt
  rebuilt from the seat's own inputs (fail closed BEFORE any request on a
  mismatch). A correction round is accepted only if the prompt equals
  base_task + the EXACT suffix rebuilt from the structured metadata the
  runtime recorded for that round (Seat.correction_meta: kind plus the
  actual exception text or bad/allowed paths), by string EQUALITY through
  the runtime's own correction_suffix(). No pattern matching, no free text.
- every complete() gets its own audit call_id; a link row ties
  call_id -> (fenced log file, reserve number n) read from the fenced log,
  never guessed from order. n is None when no reserve was written (a
  refusal before any I/O).
- no raw prompt, model text or ids are written.
ONE WRITER: n is read from the fenced log's reserve count before and after a call, so it is only correct with a single writer per fenced log (n is null if the count did not move by exactly one). Audit rows are evidence, NOT a budget or authorization: the fenced log and
lifetime cap own those.
"""
import hashlib, json, os, stat

from launcher.prompt_audit import PromptAuditAdapter, render_audited_prompt
from launcher.runtime import correction_suffix

PINS = {"launcher/prompt_audit.py": "7cf175ed1f2a78adf3fca04f8a567e49",
        "launcher/usage_join.py": "d00259978e57bebfba30ee5f6e8121ab"}

_HERE = os.path.dirname(os.path.abspath(__file__))


def verify_pins():
    for rel, md5 in PINS.items():
        got = hashlib.md5(open(os.path.join(_HERE, rel), "rb").read()).hexdigest()
        if got != md5:
            raise RuntimeError(f"vendored {rel} md5 mismatch")


def _reserves(path):
    if not os.path.exists(path):
        return 0
    return sum(1 for l in open(path, "rb") if b'"phase": "reserve"' in l)


class AuditLinkError(RuntimeError):
    """Link row could not be written after a call that may have happened.
    Evidence for that call is UNKNOWN to the audit; do not retry blindly."""


def _private_dir(path, repo):
    """Audit dir must be a real directory (no symlink), mode 0700, owned by
    us, and OUTSIDE the lane repo (so it can never be committed)."""
    path = os.path.abspath(path)
    if os.path.islink(path):
        raise RuntimeError("audit dir must not be a symlink")
    os.makedirs(path, mode=0o700, exist_ok=True)
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise RuntimeError("audit dir must be a directory owned by this user")
    os.chmod(path, 0o700)
    real, repo_real = os.path.realpath(path), os.path.realpath(repo)
    if real == repo_real or real.startswith(repo_real + os.sep):
        raise RuntimeError("audit dir must be outside the lane repo")
    return path


class AuditedFenced:
    """Wraps a FencedHttpAdapter; `inner` is the fenced adapter."""
    REPORTS_PROVIDER_USAGE = False   # evidence is read from inner by PromptAudit

    def __init__(self, fenced, seat_obj, audit_dir):
        verify_pins()
        self.inner = fenced
        self._seat = seat_obj
        audit_dir = _private_dir(audit_dir, seat_obj.bus.repo)
        self.audit_path = os.path.join(audit_dir, f"{seat_obj.name}.audit.jsonl")
        self.link_path = os.path.join(audit_dir, f"{seat_obj.name}.links.jsonl")
        self._suffix = ""
        self._audit = PromptAuditAdapter(fenced, self.audit_path, self._context)

    def _context(self):
        s = self._seat
        brief = s._read(s.bus.repo, ".team/brief.md")
        return dict(seat=s.name, role=s.role, brief=brief,
                    state=s.bus.state(), recent_log=s.bus.log(limit=20),
                    batch=s.spec.get("batch"), correction_suffix=self._suffix)

    def _append(self, path, row):
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=True) + "\n")
            fh.flush(); os.fsync(fh.fileno())

    def complete(self, system, prompt):
        self._suffix = ""
        ctx = self._context(); ctx.pop("correction_suffix")
        _, base_task, _ = render_audited_prompt(**ctx)
        meta = getattr(self._seat, "correction_meta", None)
        expected = correction_suffix(**meta) if meta else ""
        if prompt != base_task + expected:
            raise ValueError("audit: prompt is not the seat's base task plus "
                             "the runtime-recorded correction (exact match)")
        self._suffix = expected
        before = _reserves(self.inner.path) if getattr(self.inner, "path", None) else 0
        rows_before = sum(1 for _ in open(self.audit_path)) if os.path.exists(self.audit_path) else 0
        result, err = None, None
        try:
            result = self._audit.complete(system, prompt)
        except BaseException as e:
            err = e
        try:
            self._link(before, rows_before)
        except Exception as link_exc:
            raise AuditLinkError("audit link not written; call evidence "
                                 "unknown to the audit") from (err or link_exc)
        finally:
            self._suffix = ""
        if err is not None:
            raise err
        return result

    def _link(self, before, rows_before):
        rows = [json.loads(l) for l in open(self.audit_path)][rows_before:]
        starts = [r for r in rows if r.get("event") == "adapter_call_start"]
        if not starts:
            return   # refused before the audit started: no call_id exists
        path = getattr(self.inner, "path", None)
        after = _reserves(path) if path else 0
        self._append(self.link_path, {
            "event": "audit_fenced_link", "call_id": starts[0]["call_id"],
            "fenced_log": os.path.basename(path) if path else None,
            "n": after if after == before + 1 else None,
            "correction_round": bool(self._suffix)})

    def consume(self):
        return None
