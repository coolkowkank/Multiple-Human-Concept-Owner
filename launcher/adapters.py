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
import os
import subprocess
import urllib.request


class AdapterError(Exception):
    pass


class Adapter:
    def consume(self):
        """Remove the peeked line after the turn was applied. Called by
        the runtime inside the same transact mutation, so a reset after
        a lost race also restores the queue. Raises if the file changed
        between peek and consume (record would be incoherent)."""
        if not self.script_path or self._peeked is None:
            return
        with open(self.script_path) as fh:
            lines = [l for l in fh.read().splitlines() if l.strip()]
        if not lines or lines[0] != self._peeked:
            raise AdapterError(
                f"mock script queue at {self.script_path} changed "
                "between peek and consume")
        with open(self.script_path, "w") as fh:
            fh.write("\n".join(lines[1:]) + ("\n" if len(lines) > 1 else ""))
        self._peeked = None

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

    def __init__(self, script, script_path=None):
        self.script = script
        self.script_path = script_path
        self.calls = []
        self._peeked = None

    def consume(self):
        """Remove the peeked line after the turn was applied. Called by
        the runtime inside the same transact mutation, so a reset after
        a lost race also restores the queue. Raises if the file changed
        between peek and consume (record would be incoherent)."""
        if not self.script_path or self._peeked is None:
            return
        with open(self.script_path) as fh:
            lines = [l for l in fh.read().splitlines() if l.strip()]
        if not lines or lines[0] != self._peeked:
            raise AdapterError(
                f"mock script queue at {self.script_path} changed "
                "between peek and consume")
        with open(self.script_path, "w") as fh:
            fh.write("\n".join(lines[1:]) + ("\n" if len(lines) > 1 else ""))
        self._peeked = None

    def complete(self, system, prompt):
        self.calls.append({"system": system, "prompt": prompt})
        if self.script_path:
            with open(self.script_path) as fh:
                lines = [l for l in fh.read().splitlines() if l.strip()]
            if not lines:
                raise AdapterError(
                    f"mock script queue empty at {self.script_path}")
            self._peeked = lines[0]
            return json.loads(lines[0])
        i = len(self.calls) - 1
        if callable(self.script):
            return self.script(system, prompt, i)
        if i >= len(self.script):
            raise AdapterError(f"mock script exhausted at call {i}")
        return self.script[i]


class CliAdapter(Adapter):
    """Run an installed agent CLI. Template placeholders: {prompt_file}.

    Example: ["claude", "-p", "{prompt_file}"] or ["codex", "exec", "{prompt_file}"].
    The CLI must print the seat's JSON response on stdout.
    """

    def __init__(self, command, timeout=1800):
        self.command = command
        self.timeout = timeout

    def consume(self):
        """Remove the peeked line after the turn was applied. Called by
        the runtime inside the same transact mutation, so a reset after
        a lost race also restores the queue. Raises if the file changed
        between peek and consume (record would be incoherent)."""
        if not self.script_path or self._peeked is None:
            return
        with open(self.script_path) as fh:
            lines = [l for l in fh.read().splitlines() if l.strip()]
        if not lines or lines[0] != self._peeked:
            raise AdapterError(
                f"mock script queue at {self.script_path} changed "
                "between peek and consume")
        with open(self.script_path, "w") as fh:
            fh.write("\n".join(lines[1:]) + ("\n" if len(lines) > 1 else ""))
        self._peeked = None

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
    """OpenAI-compatible chat completions. Works with any provider or
    local server exposing that API shape. API key from env var."""

    def __init__(self, base_url, model, api_key_env, timeout=600):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_env = api_key_env
        self.timeout = timeout

    def consume(self):
        """Remove the peeked line after the turn was applied. Called by
        the runtime inside the same transact mutation, so a reset after
        a lost race also restores the queue. Raises if the file changed
        between peek and consume (record would be incoherent)."""
        if not self.script_path or self._peeked is None:
            return
        with open(self.script_path) as fh:
            lines = [l for l in fh.read().splitlines() if l.strip()]
        if not lines or lines[0] != self._peeked:
            raise AdapterError(
                f"mock script queue at {self.script_path} changed "
                "between peek and consume")
        with open(self.script_path, "w") as fh:
            fh.write("\n".join(lines[1:]) + ("\n" if len(lines) > 1 else ""))
        self._peeked = None

    def complete(self, system, prompt):
        key = os.environ.get(self.api_key_env)
        if not key:
            raise AdapterError(f"missing API key env var {self.api_key_env}")
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body,
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {key}",
            })
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read())
        text = data["choices"][0]["message"]["content"]
        return parse_response(text)


def parse_response(text):
    """Extract the seat's JSON response from model output.

    Accepts a bare JSON object or one inside a ```json fence. Anything
    else is a protocol error the runtime records instead of guessing.
    """
    text = text.strip()
    if "```" in text:
        for block in text.split("```")[1::2]:
            block = block.strip()
            if block.startswith("json"):
                block = block[4:].strip()
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                continue
        raise AdapterError("no parseable JSON fence in model output")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AdapterError(f"model output is not JSON: {exc}") from exc


def build_adapter(spec):
    """Build an adapter from a roster spec dict."""
    kind = spec.get("type", "mock")
    if kind == "mock":
        return MockAdapter(spec.get("script", []),
                           script_path=spec.get("script_path"))
    if kind == "cli":
        return CliAdapter(spec["command"], timeout=spec.get("timeout", 1800))
    if kind == "http":
        return HttpAdapter(
            spec["base_url"], spec["model"], spec["api_key_env"],
            timeout=spec.get("timeout", 600))
    raise AdapterError(f"unknown adapter type {kind!r}")
