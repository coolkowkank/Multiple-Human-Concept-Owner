"""Model adapters: how a seat's AI is actually called.

The seat loop is platform-agnostic; an adapter turns a prompt into a
structured seat response. This is where "AI from different platforms"
plugs in:

- MockAdapter   scripted, for tests and the demo (no keys, no spend)
- CliAdapter    any installed agent CLI (command template), e.g. a
                coding-assistant CLI on any platform
- HttpAdapter   OpenAI-compatible chat-completions endpoint (also covers
                compatible providers and local servers); key from env

Only MockAdapter is exercised by the test suite. CliAdapter and
HttpAdapter are real code paths but need a live provider, which the
suite does not use; see docs/proposed-vs-tested.md.
"""

from __future__ import annotations

import json
import re
import os
import subprocess
import time
import urllib.error
import urllib.request


def _read_queue(path):
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return [l for l in fh.read().splitlines() if l.strip()]


def _peek_queue(path):
    lines = _read_queue(path)
    if not lines:
        raise AdapterError(f"response queue empty at {path}")
    return lines[0]


def _consume_queue(path, peeked):
    """Remove the peeked line after the turn was applied. Called by the
    runtime inside the same transact mutation, so a reset after a lost
    race also restores the queue. Raises if the file changed between
    peek and consume (the record would be incoherent)."""
    lines = _read_queue(path)
    if not lines or lines[0] != peeked:
        raise AdapterError(
            f"response queue at {path} changed between peek and consume")
    with open(path, "w") as fh:
        fh.write("\n".join(lines[1:]) + ("\n" if len(lines) > 1 else ""))


class AdapterError(Exception):
    """Adapter failure. `raw` optionally carries the unmodified model
    output that caused a format failure, for evidence preservation."""

    def __init__(self, message, raw=None):
        super().__init__(message)
        self.raw = raw


class Adapter:
    def complete(self, system, prompt):
        raise NotImplementedError


class MockAdapter(Adapter):
    """Scripted adapter. `script` maps call index -> response dict,
    or a callable(system, prompt, call_index) -> dict.

    `script_path` (JSONL file) is the multi-process variant: complete()
    PEEKS the first line, and the runtime calls consume() only after the
    response has been applied inside the same transact mutation. A lost
    commit race resets the tree (including the queue file), so a retried
    turn re-reads the same response - no response is ever lost or
    double-consumed, and separate `seat --once` processes consume
    successive prepared responses instead of restarting at script[0]."""

    def consume(self):
        """Remove the peeked line after the turn was applied; see
        _consume_queue. A lost-race reset restores the queue file."""
        if not self.script_path or self._peeked is None:
            return
        _consume_queue(self.script_path, self._peeked)
        self._peeked = None


    def __init__(self, script, script_path=None):
        self.script = script
        self.script_path = script_path
        self.calls = []
        self._peeked = None

    def complete(self, system, prompt):
        self.calls.append({"system": system, "prompt": prompt})
        if self.script_path:
            self._peeked = _peek_queue(self.script_path)
            try:
                return json.loads(self._peeked)
            except json.JSONDecodeError as exc:
                raise AdapterError(
                    f"queued response at {self.script_path} is not "
                    f"valid JSON: {exc} - NOT consumed; fix or remove "
                    f"the bad line", raw=self._peeked) from exc
        i = len(self.calls) - 1
        if callable(self.script):
            return self.script(system, prompt, i)
        if i >= len(self.script):
            raise AdapterError(f"mock script exhausted at call {i}")
        return self.script[i]


class QueueAdapter(Adapter):
    """A file-backed queue of responses reasoned OUTSIDE this process:
    an interactive seat (a human pasting into a chat session on any
    platform) or an assistant-mediated seat (another agent reads the
    prompt, reasons, and queues its response). The transport is honest
    glue: the harness owns the turn, lease, verify and record; the
    reasoning happens wherever the operator ran it. It is not an
    autonomous model call and evidence must not label it as one.

    The queue file lives inside the bus (e.g. .team/queues/NAME.jsonl),
    one JSON response object per line, consumed with the same
    peek-then-consume-inside-transact semantics as the mock script
    queue: a lost commit race restores the line, so a reasoned response
    is never lost or applied twice."""

    def __init__(self, path):
        self.path = path
        self._peeked = None

    def complete(self, system, prompt):
        self._peeked = _peek_queue(self.path)
        # M2 (peer review of 7d40565): a hand-edited malformed line
        # must surface as a normalized AdapterError (handled by the
        # seat loop), not a raw JSONDecodeError escaping it. The line
        # is NOT consumed - peek-only - so the queue is preserved.
        try:
            return json.loads(self._peeked)
        except json.JSONDecodeError as exc:
            raise AdapterError(
                f"queued response at {self.path} is not valid JSON: "
                f"{exc} - NOT consumed; fix or remove the bad line",
                raw=self._peeked) from exc

    def consume(self):
        if self._peeked is None:
            return
        _consume_queue(self.path, self._peeked)
        self._peeked = None


class CliAdapter(Adapter):
    """Run an installed agent CLI. Template placeholders: {prompt_file}.

    Example: ["claude", "-p", "{prompt_file}"] or ["codex", "exec", "{prompt_file}"].
    The CLI must print the seat's JSON response on stdout.
    """

    def __init__(self, command, timeout=1800):
        self.command = command
        self.timeout = timeout

    def complete(self, system, prompt):
        import tempfile
        with tempfile.NamedTemporaryFile(
                "w", suffix=".md", delete=False) as fh:
            fh.write(f"# System\n\n{system}\n\n# Task\n\n{prompt}\n")
            path = fh.name
        try:
            argv = [a.replace("{prompt_file}", path) for a in self.command]
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=self.timeout)
            if proc.returncode != 0:
                raise AdapterError(
                    f"CLI adapter exited {proc.returncode}: {proc.stderr.strip()[:500]}")
            return parse_response(proc.stdout)
        finally:
            os.unlink(path)


class HttpAdapter(Adapter):
    # Class-level capability: only adapters that really call a provider and set
    # last_call from its response declare this. The audit wrapper checks the
    # CLASS, not instance data, before trusting last_call.
    REPORTS_PROVIDER_USAGE = True

    """OpenAI-compatible chat completions. Works with any provider or
    local server exposing that API shape. API key from env var."""

    def __init__(self, base_url, model, api_key_env, timeout=600,
                 max_retries=3, backoff=2.0, sleeper=time.sleep,
                 max_tokens=None, reasoning_effort=None,
                 call_budget=None, usage_log=None, require_zero_cost=False):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_env = api_key_env
        self.timeout = timeout
        # Optional completion-token cap (request field
        # max_completion_tokens). Reasoning models can burn the
        # provider default entirely on reasoning and return EMPTY
        # content (observed live: Groq gpt-oss-20b, finish_reason
        # length, 2041 reasoning tokens, 0 content, 2026-11-04) - set
        # this high enough for reasoning plus the answer.
        self.max_tokens = max_tokens
        # Optional reasoning effort hint (request field
        # reasoning_effort: low/medium/high). Reasoning models scale
        # thinking with token headroom; low keeps latency inside
        # constrained run windows while preserving structured output
        # (observed live: Groq gpt-oss-120b, low -> 12 reasoning
        # tokens and a 1.1s complete response vs ~6.7k reasoning
        # tokens and truncation at the same task, 2026-11-04).
        self.reasoning_effort = reasoning_effort
        # 429/backoff policy: retry rate-limited requests with
        # exponential backoff, honoring Retry-After when the provider
        # sends one. Other HTTP errors are not retried (a 4xx will not
        # heal by waiting; a 5xx storm should not be hammered either -
        # only 429 carries an explicit "come back later" meaning).
        # Every retry consumes the call budget below.
        self.max_retries = max_retries
        self.backoff = backoff
        self.sleeper = sleeper
        # call_budget: maximum provider REQUESTS this adapter will
        # ATTEMPT (a request count, NOT a token or money cap - usage
        # varies per request; token spend is only measurable from the
        # usage record). Every try counts - successes, HTTP errors, 429
        # retries and unreachable transport - and the check runs BEFORE
        # the request is issued (the D11 lesson: attempts count, fail
        # closed). None keeps legacy unbounded behavior; `launcher
        # launch` refuses unbounded http seats unless the operator
        # explicitly overrides.
        self.call_budget = call_budget
        # usage_log: one JSON line appended per attempt ({ts, model,
        # attempt, outcome, usage}) so runs are auditable. When a budget
        # is set the log is REQUIRED and the count is DERIVED FROM THE
        # LOG at startup: a restarted (or resumed) seat process resumes
        # its count instead of resetting it, and the single-session
        # lease keeps one writer per seat so the file is the counter.
        # Refuse the contradictory configuration (budget without a
        # durable counter) rather than silently resetting.
        if call_budget is not None and not usage_log:
            raise AdapterError(
                "call_budget requires usage_log: the attempt count is "
                "derived from the log so it survives restarts")
        self.usage_log = usage_log
        self._calls = self._prior_attempts()
        # require_zero_cost: for zero-price routes only. If a response's
        # usage reports a nonzero "cost", STOP fail-closed before any
        # further request - an unexpected charge means the route is not
        # what the roster claimed, and continuing would spend unbounded.
        self.require_zero_cost = require_zero_cost

    def _prior_attempts(self):
        if not self.usage_log or not os.path.exists(self.usage_log):
            return 0
        try:
            with open(self.usage_log) as fh:
                return sum(1 for line in fh if line.strip())
        except OSError:
            return 0

    def complete(self, system, prompt):
        key = os.environ.get(self.api_key_env)
        if not key:
            raise AdapterError(f"missing API key env var {self.api_key_env}")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if self.max_tokens:
            payload["max_completion_tokens"] = self.max_tokens
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body,
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {key}",
                # Some providers' edge rules 403 the bare
                # Python-urllib user agent; send an explicit one.
                "user-agent": "team-launcher-http-adapter/0.1",
            })
        self.last_call = None  # cleared so a failed call never leaks a stale id
        data = self._post(req)
        # Provider-REPORTED fields of the last successful response (raw, kept in
        # memory only). Reported, not verified; consumers must sanitize.
        # The request returned a JSON body, so the call happened and may be
        # billed: keep reported fields even if the text below fails to parse.
        self.last_call = {"origin": "provider", "response_id": data.get("id"),
                          "usage": data.get("usage")}
        text = data["choices"][0]["message"]["content"]
        return parse_response(text)

    def _record(self, attempt, outcome, usage=None, response_id=None):
        if not self.usage_log:
            return
        import datetime
        line = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "model": self.model, "attempt": attempt, "outcome": outcome,
                "usage": usage}
        if response_id is not None:
            # Provider-reported completion id (body "id"), recorded verbatim
            # as join evidence. Absent when the provider sends none.
            line["response_id"] = response_id
        os.makedirs(os.path.dirname(os.path.abspath(self.usage_log)),
                    exist_ok=True)
        with open(self.usage_log, "a") as fh:
            fh.write(json.dumps(line) + "\n")

    def _post(self, req):
        delay = self.backoff
        for attempt in range(self.max_retries + 1):
            if self.call_budget is not None and self._calls >= self.call_budget:
                raise AdapterError(
                    f"provider call budget exhausted "
                    f"({self._calls}/{self.call_budget}); refusing further "
                    f"requests (fail-closed)")
            self._calls += 1  # counted BEFORE the request: errors and retries consume budget too
            try:
                with urllib.request.urlopen(req, timeout=self.timeout)                         as resp:
                    data = json.loads(resp.read())
                    rid = data.get("id")
                    self._record(attempt + 1, "ok", data.get("usage"),
                                 rid if isinstance(rid, str) and re.match(
                                     r"^[A-Za-z0-9._:-]{1,128}$", rid) else None)
                    if self.require_zero_cost:
                        cost = (data.get("usage") or {}).get("cost")
                        if cost:
                            raise AdapterError(
                                f"provider reported nonzero cost {cost} on a "
                                f"zero-price route; stopping fail-closed")
                    return data
            except urllib.error.HTTPError as exc:
                self._record(attempt + 1, f"http_{exc.code}")
                if exc.code != 429 or attempt == self.max_retries:
                    raise AdapterError(
                        f"provider HTTP {exc.code} after {attempt + 1} "
                        f"attempt(s): {exc.read()[:200]!r}") from exc
                retry_after = exc.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else delay
                self.sleeper(wait)
                delay *= 2
            except urllib.error.URLError as exc:
                self._record(attempt + 1, "unreachable")
                if attempt == self.max_retries:
                    raise AdapterError(
                        f"provider unreachable after {attempt + 1} "
                        f"attempt(s): {exc.reason}") from exc
                self.sleeper(delay)
                delay *= 2
        raise AdapterError("unreachable")  # pragma: no cover


def parse_response(text):
    """Extract the seat's JSON response from model output.

    STRICT ONLY: the whole reply is one bare JSON object, or exactly
    one ```json fence with nothing but whitespace around it. Anything
    else is a protocol error the runtime records instead of guessing -
    free-prose salvage and first-parseable-fence picking were both
    rejected on review (2026-11-04): text outside the object can carry
    intent ("cancel that", a second instruction), so dropping it
    silently is unsafe even with exactly one balanced object. Recovery
    lives in the seat's explicit format-correction round, where the
    model re-answers and the reply is revalidated strictly.
    """
    text = text.strip()
    # N3 (peer review of e08769a): only treat the reply as fence-form
    # when it STARTS with a fence. A bare JSON object whose string
    # values contain ``` is valid JSON and must not be forced into the
    # fence branch (that burned a correction round on valid output).
    if text.startswith("```"):
        # N2 (peer review of 7d40565, 2026-11-04, reproduced): the
        # ENTIRE reply must be exactly one fence plus whitespace -
        # picking the first parseable fence out of a larger message
        # discards outside prose that can carry intent ("Actually
        # cancel that; do not apply.") and silently applies the rest.
        parts = text.split("```")
        if len(parts) != 3 or parts[0].strip() or parts[2].strip():
            raise AdapterError(
                "model output is not JSON: expected exactly one json "
                "fence (plus surrounding whitespace) or one bare "
                "object; prose outside the fence and multiple fences "
                "are rejected, never picked through", raw=text)
        block = parts[1].strip()
        if block.startswith("json"):
            block = block[4:].strip()
        try:
            return json.loads(block)
        except json.JSONDecodeError as exc:
            raise AdapterError(
                f"model output is not JSON: fenced block: {exc}",
                raw=text) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AdapterError(f"model output is not JSON: {exc}",
                           raw=text) from exc


def build_adapter(spec):
    """Build an adapter from a roster spec dict."""
    kind = spec.get("type", "mock")
    if kind == "mock":
        return MockAdapter(spec.get("script", []),
                           script_path=spec.get("script_path"))
    if kind == "cli":
        return CliAdapter(spec["command"], timeout=spec.get("timeout", 1800))
    if kind == "queue":
        return QueueAdapter(spec["path"])
    if kind == "http":
        return HttpAdapter(
            spec["base_url"], spec["model"], spec["api_key_env"],
            timeout=spec.get("timeout", 600),
            max_tokens=spec.get("max_tokens"),
            reasoning_effort=spec.get("reasoning_effort"),
            call_budget=spec.get("call_budget"),
            usage_log=spec.get("usage_log"),
            require_zero_cost=spec.get("require_zero_cost", False))
    raise AdapterError(f"unknown adapter type {kind!r}")
