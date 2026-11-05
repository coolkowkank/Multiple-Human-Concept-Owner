"""Opt-in audit wrapper for fenced model seats (offline-tested).

Order: GuardedAdapter(AuditedFenced(FencedHttpAdapter)). Enabled only when
the operator passes an audit directory (env LG_AUDIT_DIR); off by default.

What it adds on top of the product's PromptAuditAdapter (vendored byte-exact
in launcher/prompt_audit.py, md5 pinned below):
- the exact system/prompt the runtime passes is checked against the prompt
  rebuilt from the seat's own inputs (fail closed BEFORE any request on a
  mismatch). A correction round is accepted only if the prompt equals
  base_task + one of the two EXACT runtime correction templates (regex
  full match with the fixed text, not a free suffix).
- every complete() gets its own audit call_id; a link row ties
  call_id -> (fenced log file, reserve number n) read from the fenced log,
  never guessed from order. n is None when no reserve was written (a
  refusal before any I/O).
- no raw prompt, model text or ids are written.
Audit rows are evidence, NOT a budget or authorization: the fenced log and
lifetime cap own those.
"""
import hashlib, json, os, re

from launcher.prompt_audit import PromptAuditAdapter, render_audited_prompt

PINS = {"launcher/prompt_audit.py": "7cf175ed1f2a78adf3fca04f8a567e49",
        "launcher/usage_join.py": "d00259978e57bebfba30ee5f6e8121ab"}

_HERE = os.path.dirname(os.path.abspath(__file__))


def verify_pins():
    for rel, md5 in PINS.items():
        got = hashlib.md5(open(os.path.join(_HERE, rel), "rb").read()).hexdigest()
        if got != md5:
            raise RuntimeError(f"vendored {rel} md5 mismatch")


_FORMAT_CORR = re.compile(
    r"\n\nCORRECTION REQUIRED: your previous reply was not a single JSON "
    r"object per the response contract \((?:[^\n]{0,400})\)\. Reply with "
    r"EXACTLY ONE JSON object matching the contract and nothing else - no "
    r"prose, no fences, no tool calls\.\Z")
_PATH_CORR = re.compile(
    r"\n\nCORRECTION REQUIRED: your previous reply tried to write "
    r"\[[^\n]{0,400}\], outside your allowed paths \[[^\n]{0,400}\]\. "
    r"Reply again with the same JSON contract, writing ONLY inside your "
    r"allowed paths; leave every other file untouched\.\Z")


def _reserves(path):
    if not os.path.exists(path):
        return 0
    return sum(1 for l in open(path, "rb") if b'"phase": "reserve"' in l)


class AuditedFenced:
    """Wraps a FencedHttpAdapter; `inner` is the fenced adapter."""
    REPORTS_PROVIDER_USAGE = False   # evidence is read from inner by PromptAudit

    def __init__(self, fenced, seat_obj, audit_dir):
        verify_pins()
        self.inner = fenced
        self._seat = seat_obj
        os.makedirs(audit_dir, exist_ok=True)
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
        if prompt != base_task:
            if not prompt.startswith(base_task):
                raise ValueError("audit: prompt does not match the seat's inputs")
            extra = prompt[len(base_task):]
            if not (_FORMAT_CORR.match(extra) or _PATH_CORR.match(extra)):
                raise ValueError("audit: prompt suffix is not an exact "
                                 "runtime correction template")
            self._suffix = extra
        before = _reserves(self.inner.path) if getattr(self.inner, "path", None) else 0
        rows_before = sum(1 for _ in open(self.audit_path)) if os.path.exists(self.audit_path) else 0
        try:
            return self._audit.complete(system, prompt)
        finally:
            self._link(before, rows_before)
            self._suffix = ""

    def _link(self, before, rows_before):
        try:
            rows = [json.loads(l) for l in open(self.audit_path)][rows_before:]
        except OSError:
            return
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
