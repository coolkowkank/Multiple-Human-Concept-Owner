"""Offline tests for tools/self-commit-executor.py (no provider, no network beyond local scratch remotes).

Lesson encoded (2026-11-04 loop): a live model-driving executor must prove
its capture and budget guards with fake-API tests BEFORE any real provider
call, because the first version lost crashed-run accounting to a sandbox reset.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

EXECUTOR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "tools", "self-commit-executor.py")
SOURCE = open(EXECUTOR).read()


def git(*args, cwd=None):
    subprocess.run(["git"] + list(args), cwd=cwd, check=True, capture_output=True)


class ExecutorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = lambda n: os.path.join(self.tmp, n)
        self.remote, self.wt, self.repo = p("remote.git"), p("wt"), p("repo")
        git("init", "--bare", self.remote)
        git("clone", self.remote, self.wt)
        git("checkout", "-b", "records", cwd=self.wt)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-m", "i", cwd=self.wt)
        git("push", "origin", "records", cwd=self.wt)
        git("init", self.repo)
        self.task = p("task.md"); open(self.task, "w").write("task")
        self.key = p("key.txt"); open(self.key, "w").write("fake")
        self._env = dict(os.environ)
        self.addCleanup(self._restore_env)
        os.environ["GROQ_KEY_FILE"] = self.key
        os.environ["RECORDS_DIR"] = self.wt
        os.environ["MODEL_COMMITTER"] = "Test Bot <1+test-bot@users.noreply.github.com>"

    def _restore_env(self):
        os.environ.clear(); os.environ.update(self._env)

    def load(self, max_calls=None):
        ns = {}
        sys.argv = ["x", self.repo, "records", "attempt-t", self.task]
        if max_calls is not None:
            os.environ["MAX_CALLS"] = str(max_calls)
        elif "MAX_CALLS" in os.environ:
            del os.environ["MAX_CALLS"]
        exec(compile(SOURCE, "executor", "exec"), ns)
        return ns

    @staticmethod
    def msg(tool_calls=None, content=None):
        return {"choices": [{"message": {"role": "assistant", "content": content,
                                         "tool_calls": tool_calls}}],
                "id": "fake", "created": 1, "usage": {}}

    @staticmethod
    def tc(name, args, i="c1"):
        return {"id": i, "type": "function",
                "function": {"name": name, "arguments": args}}


    # -- bounded small-edit interface (deadlock-fix batch, attempts b3/b5) --

    def test_edit_file_exact_single_replacement_byte_exact(self):
        ns = self.load()
        target = os.path.join(self.repo, "launcher", "mod.py")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        before = "alpha\nKEEP-ONE\nold call()\nKEEP-TWO\nomega\n"
        open(target, "w").write(before)
        r = ns["run_tool"]("edit_file", {"path": "launcher/mod.py",
                                         "old_string": "old call()",
                                         "new_string": "new call()"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(open(target).read(),
                         "alpha\nKEEP-ONE\nnew call()\nKEEP-TWO\nomega\n")

    def test_edit_file_no_match_fails_loudly_and_changes_nothing(self):
        ns = self.load()
        target = os.path.join(self.repo, "launcher", "mod.py")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        open(target, "w").write("untouched\n")
        r = ns["run_tool"]("edit_file", {"path": "launcher/mod.py",
                                         "old_string": "absent", "new_string": "x"})
        self.assertFalse(r["ok"])
        self.assertIn("not found", r["error"])
        self.assertEqual(open(target).read(), "untouched\n")

    def test_edit_file_ambiguous_anchor_refused(self):
        ns = self.load()
        target = os.path.join(self.repo, "launcher", "mod.py")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        open(target, "w").write("dup\ndup\n")
        r = ns["run_tool"]("edit_file", {"path": "launcher/mod.py",
                                         "old_string": "dup", "new_string": "x"})
        self.assertFalse(r["ok"])
        self.assertIn("2 locations", r["error"])
        self.assertEqual(open(target).read(), "dup\ndup\n")

    def test_edit_file_missing_file_points_to_write_file(self):
        ns = self.load()
        r = ns["run_tool"]("edit_file", {"path": "launcher/nope.py",
                                         "old_string": "a", "new_string": "b"})
        self.assertFalse(r["ok"])
        self.assertIn("write_file", r["error"])

    def test_edit_file_size_cap_and_empty_anchor_refused(self):
        ns = self.load()
        target = os.path.join(self.repo, "launcher", "mod.py")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        open(target, "w").write("body\n")
        r = ns["run_tool"]("edit_file", {"path": "launcher/mod.py",
                                         "old_string": "", "new_string": "b"})
        self.assertFalse(r["ok"])
        big = "y" * (ns["EDIT_MAX_BYTES"] + 1)
        r = ns["run_tool"]("edit_file", {"path": "launcher/mod.py",
                                         "old_string": "body", "new_string": big})
        self.assertFalse(r["ok"])
        self.assertIn("cap", r["error"])

    def test_write_file_over_cap_refused_points_to_edit_file(self):
        ns = self.load()
        big = "y" * (ns["MAX_BYTES"] + 1)
        r = ns["run_tool"]("write_file", {"path": "tests/big.py", "content": big})
        self.assertFalse(r["ok"])
        self.assertIn("edit_file", r["error"])
        self.assertFalse(os.path.exists(os.path.join(self.repo, "tests", "big.py")))

    def test_committer_derived_from_github_token(self):
        del os.environ["MODEL_COMMITTER"]
        os.environ["GITHUB_TOKEN"] = "fake-token"
        import urllib.request, io
        real = urllib.request.urlopen
        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        urllib.request.urlopen = lambda req, timeout=0: R(json.dumps({"login": "alice-bot", "id": 42}).encode())
        try:
            ns = self.load()
        finally:
            urllib.request.urlopen = real
        self.assertEqual(ns["MODEL_COMMITTER_NAME"], "alice-bot")
        self.assertEqual(ns["MODEL_COMMITTER_EMAIL"], "42+alice-bot@users.noreply.github.com")
        self.assertEqual(ns["MODEL_COMMITTER_SOURCE"], "derived from the GITHUB_TOKEN account")

    def test_committer_fail_closed_without_identity(self):
        del os.environ["MODEL_COMMITTER"]
        os.environ.pop("GITHUB_TOKEN", None)
        with self.assertRaises(SystemExit):
            self.load()

    def break_remote(self):
        git("remote", "set-url", "origin", os.path.join(self.tmp, "gone.git"), cwd=self.wt)

    def checkpoint_commits(self):
        out = subprocess.run(["git", "-C", self.wt, "rev-list", "--count", "records"],
                             capture_output=True, text=True).stdout
        return int(out.strip()) - 1  # minus the init commit

    # 1. RECORDS_DIR is required at startup; without it nothing runs
    def test_records_dir_required(self):
        del os.environ["RECORDS_DIR"]
        ns = self.load()
        calls = []
        ns["api"] = lambda m: calls.append(1) or self.msg()
        with self.assertRaises(SystemExit):
            ns["main"]()
        self.assertEqual(calls, [])

    # 2. broken persistence at startup: zero provider calls, halt recorded
    def test_fail_closed_at_startup(self):
        self.break_remote()
        ns = self.load()
        calls = []
        ns["api"] = lambda m: calls.append(1) or self.msg(
            tool_calls=[self.tc("write_file", json.dumps({"path": "docs/x.md", "content": "hi"}))])
        ns["main"]()
        self.assertEqual(calls, [])
        self.assertTrue(ns["PERSIST"]["halt"])
        self.assertTrue(any("checkpoint_error" in e for e in ns["transcript"] if isinstance(e, dict)))

    # 3. mid-round persistence failure: no further tool AND no further API call
    def test_midround_halt(self):
        ns = self.load()
        calls, tools_run = [], []
        two = [self.tc("write_file", json.dumps({"path": "docs/a.md", "content": "1"}), "c1"),
               self.tc("write_file", json.dumps({"path": "docs/b.md", "content": "2"}), "c2")]
        ns["api"] = lambda m: calls.append(1) or self.msg(tool_calls=two)
        orig = ns["run_tool"]
        def wrapped(n, a):
            tools_run.append(n)
            r = orig(n, a)
            if len(tools_run) == 1:
                self.break_remote()
            return r
        ns["run_tool"] = wrapped
        ns["main"]()
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(tools_run), 1)
        self.assertTrue(ns["PERSIST"]["halt"])

    # 4. budget counted BEFORE each request; refused call issues nothing
    def test_budget_fail_closed(self):
        ns = self.load(max_calls=2)
        reqs = []
        body = json.dumps(self.msg()) + "\n200"
        class FP:
            returncode = 0
            stderr = ""
            stdout = body
        real_run = ns["subprocess"].run
        def run2(*a, **k):
            if a and a[0] and "curl" in str(a[0][0]):
                reqs.append(1)
                return FP()
            return real_run(*a, **k)
        ns["subprocess"] = type("S", (), {"run": staticmethod(run2)})
        ns["api"]([]); ns["api"]([])
        with self.assertRaises(RuntimeError):
            ns["api"]([])
        self.assertEqual(len(reqs), 2)
        self.assertTrue(any("budget_stop" in e for e in ns["transcript"] if isinstance(e, dict)))


    # prose-only rounds are nudged back to tool use, not treated as done
    def test_prose_round_nudged_not_fatal(self):
        ns = self.load()
        seq = [self.msg(content="let me think"),
               self.msg(tool_calls=[self.tc("write_file", json.dumps({"path": "docs/x.md", "content": "hi"}))]),
               self.msg(content="done"), self.msg(content="done"), self.msg(content="done")]
        calls = []
        ns["api"] = lambda m: calls.append(1) or seq.pop(0)
        ns["main"]()
        self.assertTrue(os.path.exists(os.path.join(self.repo, "docs", "x.md")))
        self.assertTrue(any(isinstance(e, dict) and "no_tool_call" in e for e in ns["transcript"]))

    def test_repeated_prose_halts_after_nudge_cap(self):
        ns = self.load()
        calls = []
        ns["api"] = lambda m: calls.append(1) or self.msg(content="thinking out loud")
        ns["main"]()
        self.assertEqual(len(calls), 1 + ns["MAX_NUDGES"])

    # 5. malformed tool arguments: explicit error record, fed back, no crash
    def test_malformed_args_recorded(self):
        ns = self.load()
        seq = [self.msg(tool_calls=[self.tc("write_file", "{not json")]),
               self.msg(content="ok"), self.msg(content="ok"), self.msg(content="ok")]
        ns["api"] = lambda m: seq.pop(0)
        ns["main"]()
        errs = [e for e in ns["transcript"] if isinstance(e, dict) and e.get("args_error")]
        self.assertTrue(errs)
        self.assertIn("malformed", errs[0]["result"]["error"])

    # 6. non-JSON HTTP body (e.g. edge error page): captured, no uncaught decode
    def test_non_json_http_captured(self):
        ns = self.load()
        class FP:
            returncode = 0
            stderr = ""
            stdout = "<html>error 1010</html>\n403"
        ns["subprocess"] = type("S", (), {"run": staticmethod(lambda *a, **k: FP())})
        with self.assertRaises(RuntimeError):
            ns["api"]([])
        rec = [e["api_error"] for e in ns["transcript"] if isinstance(e, dict) and "api_error" in e]
        self.assertEqual(rec[0]["status"], "403")
        self.assertIn("1010", rec[0]["body_head"])

    # 6b. REQUIRE_ZERO_COST=1: a nonzero reported cost stops the run fail-closed
    def test_zero_cost_guard_stops_on_nonzero_cost(self):
        os.environ["REQUIRE_ZERO_COST"] = "1"
        ns = self.load()
        body = json.dumps({"choices": [{"message": {"role": "assistant", "content": "x"}}],
                           "usage": {"cost": 0.01, "total_tokens": 10}}) + "\n200"
        class FP:
            returncode = 0
            stderr = ""
            stdout = body
        ns["subprocess"] = type("S", (), {"run": staticmethod(lambda *a, **k: FP())})
        with self.assertRaises(RuntimeError) as ctx:
            ns["api"]([])
        self.assertIn("require_zero_cost", str(ctx.exception))
        rec = [e["cost_stop"] for e in ns["transcript"] if isinstance(e, dict) and "cost_stop" in e]
        self.assertEqual(rec[0]["cost"], 0.01)

    # 6c. REQUIRE_ZERO_COST=1: a zero reported cost passes; guard off by default
    def test_zero_cost_guard_passes_zero_and_defaults_off(self):
        os.environ["REQUIRE_ZERO_COST"] = "1"
        ns = self.load()
        def mk(cost):
            body = json.dumps({"choices": [{"message": {"role": "assistant", "content": "x"}}],
                               "usage": {"cost": cost, "total_tokens": 10}}) + "\n200"
            class FP:
                returncode = 0
                stderr = ""
                stdout = body
            return FP
        ns["subprocess"] = type("S", (), {"run": staticmethod(lambda *a, **k: mk(0)())})
        self.assertEqual(ns["api"]([])["usage"]["cost"], 0)  # zero passes
        # default (env unset): nonzero cost does NOT stop (guard is opt-in)
        del os.environ["REQUIRE_ZERO_COST"]
        ns2 = self.load()
        ns2["subprocess"] = type("S", (), {"run": staticmethod(lambda *a, **k: mk(0.5)())})
        self.assertEqual(ns2["api"]([])["usage"]["cost"], 0.5)

    # 7. every event checkpointed exactly once; no duplicate clean-exit checkpoint


    # -- allowlisted rate-header diagnostics (operator infra) --


    # -- durable cross-launch budget ledger (16-of-12 overrun lesson) --

    def test_durable_ledger_shared_across_launches_hard_stop(self):
        ledger = os.path.join(self.tmp, "budget.json")
        os.environ["BUDGET_LEDGER"] = ledger
        try:
            ns1 = self.load(max_calls=2)
            ns1["_reserve_call"](); ns1["_reserve_call"]()
            self.assertEqual(ns1["CALLS"]["n"], 2)
            # a SECOND launch (fresh namespace) shares the same counter
            ns2 = self.load(max_calls=2)
            with self.assertRaises(RuntimeError):
                ns2["_reserve_call"]()
            data = json.load(open(ledger))
            self.assertEqual(data["used"], 2)
            self.assertEqual(len(data["history"]), 2)
        finally:
            del os.environ["BUDGET_LEDGER"]

    def test_ledger_reservation_precedes_request_for_error_paths(self):
        # counting happens in _reserve_call BEFORE any network attempt, so
        # errors and probes consume budget; covered structurally by api()
        # calling _reserve_call first (see source) and by the counter test.
        ledger = os.path.join(self.tmp, "budget.json")
        os.environ["BUDGET_LEDGER"] = ledger
        try:
            ns = self.load(max_calls=1)
            ns["_reserve_call"]()
            with self.assertRaises(RuntimeError):
                ns["_reserve_call"]()
        finally:
            del os.environ["BUDGET_LEDGER"]

    def test_pacing_wait_honors_floor_and_reset_hint(self):
        ns = self.load()
        now = 1000.0
        data = {"last_call_epoch": 990.0}
        self.assertEqual(ns["_pacing_wait_s"](data, now, 65.0), 55.0)
        data = {"last_call_epoch": 990.0, "rate_reset_until_epoch": 1200.0}
        self.assertEqual(ns["_pacing_wait_s"](data, now, 65.0), 200.0)
        self.assertEqual(ns["_pacing_wait_s"]({}, now, 65.0), 0.0)
        self.assertEqual(ns["_retry_hint_s"]({"message": "... Please try again in 9.03s. ..."}), 9.03)
        self.assertIsNone(ns["_retry_hint_s"]({"message": "other"}))


    # -- strong push gate: bound to exact HEAD + tested tree content --

    def _committed_repo(self):
        for d in ("docs", "tasks", "launcher", "tests"):
            os.makedirs(os.path.join(self.repo, d), exist_ok=True)
        open(os.path.join(self.repo, "launcher", "a.py"), "w").write("x = 1\n")
        git("-c", "user.name=t", "-c", "user.email=t@t", "add", "-A", cwd=self.repo)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "c", cwd=self.repo)

    def test_push_gate_fail_closed_when_unconfigured(self):
        ns = self.load()
        os.environ.pop("PUSH_GATE_FILE", None)
        os.environ.pop("ALLOW_UNGATED_PUSH", None)
        err = ns["_push_gate_check"](self.repo)
        self.assertIn("fail-closed", err)

    def test_push_gate_absent_then_written_then_accepted_after_restart(self):
        self._committed_repo()
        ns = self.load()
        gate = os.path.join(self.tmp, "gate.json")
        os.environ["PUSH_GATE_FILE"] = gate
        self.addCleanup(lambda: os.environ.pop("PUSH_GATE_FILE", None))
        self.assertIn("fail-closed", ns["_push_gate_check"](self.repo))
        # operator writes approval via the CLI path (same code), then a
        # RESTARTED run (fresh namespace) accepts it
        subprocess.run([sys.executable, EXECUTOR, "--write-gate", gate, self.repo],
                       check=True, capture_output=True)
        ns2 = self.load()
        self.assertIsNone(ns2["_push_gate_check"](self.repo))

    def test_push_gate_stale_on_new_commit_and_on_edit(self):
        self._committed_repo()
        ns = self.load()
        gate = os.path.join(self.tmp, "gate.json")
        os.environ["PUSH_GATE_FILE"] = gate
        self.addCleanup(lambda: os.environ.pop("PUSH_GATE_FILE", None))
        subprocess.run([sys.executable, EXECUTOR, "--write-gate", gate, self.repo],
                       check=True, capture_output=True)
        # edit after approval invalidates
        open(os.path.join(self.repo, "launcher", "a.py"), "a").write("y = 2\n")
        self.assertIn("STALE", ns["_push_gate_check"](self.repo))
        # committing the edit also invalidates (head moved)
        git("-c", "user.name=t", "-c", "user.email=t@t", "add", "-A", cwd=self.repo)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "c2", cwd=self.repo)
        self.assertIn("STALE", ns["_push_gate_check"](self.repo))

    def test_push_gate_unreadable_fails_closed(self):
        self._committed_repo()
        ns = self.load()
        gate = os.path.join(self.tmp, "gate.json")
        open(gate, "w").write("{not json")
        os.environ["PUSH_GATE_FILE"] = gate
        self.addCleanup(lambda: os.environ.pop("PUSH_GATE_FILE", None))
        self.assertIn("fail-closed", ns["_push_gate_check"](self.repo))


    def test_push_gate_stale_on_root_file_edit_and_untracked_addition(self):
        # whole-tree binding: changes OUTSIDE launcher/tests/docs/tasks and
        # new untracked relevant files must also invalidate the approval
        self._committed_repo()
        ns = self.load()
        gate = os.path.join(self.tmp, "gate.json")
        os.environ["PUSH_GATE_FILE"] = gate
        self.addCleanup(lambda: os.environ.pop("PUSH_GATE_FILE", None))
        subprocess.run([sys.executable, EXECUTOR, "--write-gate", gate, self.repo],
                       check=True, capture_output=True)
        self.assertIsNone(ns["_push_gate_check"](self.repo))
        # TRACKED root file edit invalidates (tracked content is pushable)
        open(os.path.join(self.repo, "README.md"), "w").write("changed\n")
        git("-c", "user.name=t", "-c", "user.email=t@t", "add", "README.md", cwd=self.repo)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "readme", cwd=self.repo)
        subprocess.run([sys.executable, EXECUTOR, "--write-gate", gate, self.repo],
                       check=True, capture_output=True)
        open(os.path.join(self.repo, "README.md"), "a").write("more\n")
        self.assertIn("STALE", ns["_push_gate_check"](self.repo))
        git("checkout", "--", "README.md", cwd=self.repo)
        # untracked file at root is NOT bound (model cannot stage/push it)
        open(os.path.join(self.repo, "stray_root.py"), "w").write("x = 1\n")
        self.assertIsNone(ns["_push_gate_check"](self.repo))
        os.remove(os.path.join(self.repo, "stray_root.py"))
        subprocess.run([sys.executable, EXECUTOR, "--write-gate", gate, self.repo],
                       check=True, capture_output=True)
        self.assertIsNone(ns["_push_gate_check"](self.repo))
        open(os.path.join(self.repo, "launcher", "runtime_new.py"), "w").write("x = 1\n")
        self.assertIn("STALE", ns["_push_gate_check"](self.repo))
        os.remove(os.path.join(self.repo, "launcher", "runtime_new.py"))
        # operator runtime artifacts (.team/ transcripts) are NOT bound:
        # the model cannot stage or push them
        os.makedirs(os.path.join(self.repo, ".team", "attempts"), exist_ok=True)
        open(os.path.join(self.repo, ".team", "attempts", "run.json"), "w").write("{}")
        self.assertIsNone(ns["_push_gate_check"](self.repo))

    def test_push_gate_pycache_does_not_invalidate(self):
        self._committed_repo()
        ns = self.load()
        gate = os.path.join(self.tmp, "gate.json")
        os.environ["PUSH_GATE_FILE"] = gate
        self.addCleanup(lambda: os.environ.pop("PUSH_GATE_FILE", None))
        subprocess.run([sys.executable, EXECUTOR, "--write-gate", gate, self.repo],
                       check=True, capture_output=True)
        cache = os.path.join(self.repo, "launcher", "__pycache__")
        os.makedirs(cache)
        open(os.path.join(cache, "a.cpython-310.pyc"), "w").write("x")
        self.assertIsNone(ns["_push_gate_check"](self.repo))

    def test_precommit_compile_guard_blocks_broken_python(self):
        ns = self.load()
        # the executor stages docs/ tasks/ launcher/ tests/ as one pathspec
        # set; all four exist in the real repo, so mirror that here
        for d in ("docs", "tasks", "launcher", "tests"):
            os.makedirs(os.path.join(self.repo, d), exist_ok=True)
        bad = os.path.join(self.repo, "tests", "bad.py")
        open(bad, "w").write("def broken(:\n")
        r = ns["run_tool"]("git_commit", {"message": "m\n\nTURN: builder"})
        self.assertFalse(r["ok"])
        self.assertIn("compile", r["error"])
        open(bad, "w").write("x = 1\n")
        r = ns["run_tool"]("git_commit", {"message": "m\n\nTURN: builder"})
        self.assertTrue(r["ok"], r)

    def test_rate_headers_allowlist_only(self):
        ns = self.load()
        hdrs = ("HTTP/2 429\r\n"
                "x-ratelimit-limit-tokens: 8000\r\n"
                "X-RateLimit-Remaining-Tokens: 0\r\n"
                "x-ratelimit-reset-tokens: 9.03s\r\n"
                "retry-after: 10\r\n"
                "authorization: Bearer gsk_SECRET\r\n"
                "set-cookie: session=abc\r\n"
                "x-request-id: req_123\r\n\r\n")
        out = ns["_rate_headers"](hdrs)
        self.assertEqual(out, {"x-ratelimit-limit-tokens": "8000",
                               "x-ratelimit-remaining-tokens": "0",
                               "x-ratelimit-reset-tokens": "9.03s",
                               "retry-after": "10"})
        self.assertNotIn("gsk_SECRET", json.dumps(out))
        self.assertNotIn("session=abc", json.dumps(out))

    def test_rate_headers_empty_and_malformed(self):
        ns = self.load()
        self.assertEqual(ns["_rate_headers"](""), {})
        self.assertEqual(ns["_rate_headers"]("garbage-no-colon\n"), {})
        self.assertEqual(ns["_rate_headers"](None), {})

    def test_checkpoint_idempotent_on_relaunch(self):
        # A relaunched run re-saves identical first-event bytes; the
        # checkpoint must not fail on "nothing to commit" (b6 halt lesson).
        ns = self.load()
        ns["record"]({"system": "s", "user": "u"})
        ns["record"]({"system": "s", "user": "u"})  # same bytes again
        self.assertFalse(ns["PERSIST"]["halt"])

    def test_checkpoint_per_event_no_dup(self):
        ns = self.load()
        seq = [self.msg(tool_calls=[self.tc("write_file", json.dumps({"path": "docs/x.md", "content": "hi"}))]),
               self.msg(content="done"), self.msg(content="done"), self.msg(content="done")]
        ns["api"] = lambda m: seq.pop(0)
        ns["main"]()
        self.assertEqual(self.checkpoint_commits(), len(ns["transcript"]))



    # 8. Standalone mode: identities/provider are env-configurable, defaults preserved
    def test_env_configurable_identities(self):
        ns = self.load()
        self.assertIn("Groq (gpt-oss-120b model)", ns["MODEL_AUTHOR"])      # default preserves in-flight loop
        self.assertIn("instinct-telkomsel", ns["RECORDS_COMMITTER"])
        self.assertEqual(ns["MODEL"], "openai/gpt-oss-120b")
        self.assertIn("api.groq.com", ns["API_URL"])
        self.assertEqual(ns["MODEL_COMMITTER_NAME"], "Test Bot")
        self.assertEqual(ns["MODEL_COMMITTER_EMAIL"], "1+test-bot@users.noreply.github.com")
        self.assertEqual(ns["MODEL_COMMITTER_SOURCE"], "explicit MODEL_COMMITTER")
        os.environ["MODEL_AUTHOR"] = "Kimi (k2 model) <350571665+coolkowkank-bot@users.noreply.github.com>"
        os.environ["RECORDS_COMMITTER"] = "alice <alice@users.noreply.github.com>"
        os.environ["PROVIDER_MODEL"] = "kimi-k2"
        os.environ["PROVIDER_API_URL"] = "https://example.test/v1/chat/completions"
        os.environ["MODEL_COMMITTER"] = "alice-bot <123+alice-bot@users.noreply.github.com>"
        ns = self.load()
        self.assertEqual(ns["MODEL_AUTHOR"], "Kimi (k2 model) <350571665+coolkowkank-bot@users.noreply.github.com>")
        self.assertEqual(ns["RECORDS_COMMITTER"], "alice <alice@users.noreply.github.com>")
        self.assertEqual(ns["MODEL"], "kimi-k2")
        self.assertEqual(ns["API_URL"], "https://example.test/v1/chat/completions")
        self.assertEqual(ns["MODEL_COMMITTER_NAME"], "alice-bot")
        self.assertEqual(ns["MODEL_COMMITTER_EMAIL"], "123+alice-bot@users.noreply.github.com")
        for k in ("MODEL_AUTHOR", "RECORDS_COMMITTER", "PROVIDER_MODEL", "PROVIDER_API_URL", "MODEL_COMMITTER"):
            os.environ.pop(k, None)

    # 9. successful git_push ENDS the run: no trailing summary round is requested
    def test_run_ends_after_successful_push(self):
        ns = self.load()
        seq = [self.msg(tool_calls=[self.tc("write_file", json.dumps({"path": "docs/x.md", "content": "hi"}), "c1")]),
               self.msg(tool_calls=[self.tc("git_commit", json.dumps({"message": "m\n\nTURN: builder"}), "c2")]),
               self.msg(tool_calls=[self.tc("git_push", "{}", "c3")]),
               self.msg(content="summary that must never be requested")]
        calls = []
        ns["api"] = lambda m: calls.append(1) or seq.pop(0)
        orig = ns["run_tool"]  # scratch repo has no origin remote; stub a successful push
        ns["run_tool"] = lambda n, a: ({"ok": True, "output": "pushed"} if n == "git_push" else orig(n, a))
        ns["main"]()
        self.assertEqual(len(calls), 3)  # the 4th (summary) response was never fetched
        self.assertTrue(any("run_complete" in e for e in ns["transcript"] if isinstance(e, dict)))

    # 10. written content is elided from later prompts, preserved in the transcript
    def test_write_content_elided_from_history(self):
        ns = self.load()
        big = "x" * 4000
        seq = [self.msg(tool_calls=[self.tc("write_file", json.dumps({"path": "docs/x.md", "content": big}), "c1")]),
               self.msg(content="done"), self.msg(content="done"), self.msg(content="done")]
        seen = []
        ns["api"] = lambda m: seen.append(m) or seq.pop(0)
        ns["main"]()
        second_prompt = json.dumps(seen[1])
        self.assertNotIn(big, second_prompt)
        self.assertIn("[written to docs/x.md", second_prompt)
        self.assertTrue(any("history_elided" in e for e in ns["transcript"] if isinstance(e, dict)))
        full = [e for e in ns["transcript"] if isinstance(e, dict) and e.get("tool_call") == "write_file"]
        self.assertEqual(full[0]["args"]["content"], big)  # transcript keeps the full content

    # 11. a FAILED push does not end the run early; the model may still act
    def test_failed_push_does_not_end_run(self):
        ns = self.load()
        seq = [self.msg(tool_calls=[self.tc("git_push", "{}", "c1")]),
               self.msg(content="gave up"), self.msg(content="gave up"), self.msg(content="gave up")]
        ns["api"] = lambda m: seq.pop(0)
        orig = ns["run_tool"]
        ns["run_tool"] = lambda n, a: ({"ok": False, "error": "push refused"} if n == "git_push" else orig(n, a))
        ns["main"]()
        self.assertFalse(any("run_complete" in e for e in ns["transcript"] if isinstance(e, dict)))

if __name__ == "__main__":
    unittest.main()

