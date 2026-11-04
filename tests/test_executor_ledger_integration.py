"""Offline integration tests: executor api() lifecycle against
tools/durable_ledger.py. Fake curl only - no network, no credentials.
Failure injection at every persistence/transport boundary."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_self_commit_executor import ExecutorFixture


def _ok_payload():
    return json.dumps({"choices": [{"message": {"role": "assistant", "content": "hi"}}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1}}) + "\n200"


class _FakeCurl:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr



class _FakeClock:
    """Shared fake clock for executor + dledger: fake sleeps advance it."""
    def __init__(self):
        import time as rt
        self.t = rt.time()
        self._rt = rt
    def time(self):
        return self.t
    def sleep(self, s):
        self.t += s
    def strftime(self, *a):
        return self._rt.strftime(*a)
    def gmtime(self, *a):
        return self._rt.gmtime(*a)
    def strptime(self, *a):
        return self._rt.strptime(*a)


class ExecutorLedgerIntegration(ExecutorFixture):
    def setUp(self):
        super().setUp()
        self.ledger = os.path.join(self.tmp, "budget.json")
        os.environ["BUDGET_LEDGER"] = self.ledger
        self.addCleanup(lambda: os.environ.pop("BUDGET_LEDGER", None))

    def load_init(self, cap=5, max_calls=None):
        ns = self.load(max_calls=max_calls)
        ns["dledger"].init_ledger(self.ledger, cap)
        return ns

    def _patch_curl(self, ns, results):
        calls = []
        real_run = ns["subprocess"].run
        it = iter(results)
        def run2(*a, **k):
            if a and a[0] and "curl" in str(a[0][0]):
                calls.append(a[0])
                r = next(it)
                return _FakeCurl(*r) if isinstance(r, tuple) else r
            return real_run(*a, **k)
        ns["subprocess"] = type("S", (), {"run": staticmethod(run2)})
        return calls

    def test_missing_ledger_fails_closed_no_file_created(self):
        ns = self.load(max_calls=5)
        with self.assertRaises(RuntimeError) as cm:
            ns["_reserve_call"]()
        self.assertIn("init_ledger", str(cm.exception))
        self.assertFalse(os.path.exists(self.ledger))

    def test_legacy_schema_fails_closed(self):
        with open(self.ledger, "w") as f:
            json.dump({"used": 0, "history": []}, f)
        ns = self.load(max_calls=5)
        with self.assertRaises(RuntimeError):
            ns["_reserve_call"]()
        data = json.load(open(self.ledger))
        self.assertEqual(data, {"used": 0, "history": []})   # untouched

    def test_completed_transport_recorded_with_http_status(self):
        ns = self.load_init(5)
        calls = self._patch_curl(ns, [(_ok_payload(),)])
        ns["api"]([])
        self.assertEqual(len(calls), 1)
        ents = json.load(open(self.ledger))["entries"]
        self.assertEqual(ents[0]["state"], "completed")
        self.assertEqual(ents[0]["http"], "200")
        self.assertEqual(ns["SENDS"]["n"], 1)

    def test_transport_failure_marks_unknown(self):
        ns = self.load_init(5)
        self._patch_curl(ns, [_FakeCurl("", returncode=1, stderr="conn refused")])
        with self.assertRaises(RuntimeError):
            ns["api"]([])
        ents = json.load(open(self.ledger))["entries"]
        self.assertEqual(ents[0]["state"], "unknown")
        self.assertEqual(ns["SENDS"]["n"], 0)

    def test_response_arrived_but_completion_store_fails(self):
        # Completion store raises AFTER the transport arrived: halt, ambiguous,
        # reservation stays consumed (swept to unknown later), no refund.
        ns = self.load_init(5)
        self._patch_curl(ns, [(_ok_payload(),)])
        real_transition = ns["dledger"].transition
        def boom(path, rid, new, extra=None):
            if new == "completed":
                raise OSError(5, "EIO on completion store")
            return real_transition(path, rid, new, extra)
        ns["dledger"].transition = boom
        try:
            with self.assertRaises(RuntimeError) as cm:
                ns["api"]([])
            self.assertIn("ambiguous", str(cm.exception))
        finally:
            ns["dledger"].transition = real_transition
        ents = json.load(open(self.ledger))["entries"]
        self.assertEqual(ents[0]["state"], "transport_started")   # not lost, not completed
        counts = ns["dledger"].reconcile(self.ledger)["global"]
        self.assertEqual(counts["spent"], 1)                      # stays consumed
        self.assertIn(counts["transport_started"] + counts["unknown"], (0, 1))

    def test_crash_before_transport_start_no_send(self):
        # start_transport fails (I/O): curl must never run, reservation consumed.
        ns = self.load_init(5)
        calls = self._patch_curl(ns, [(_ok_payload(),)])
        real_st = ns["dledger"].start_transport
        ns["dledger"].start_transport = lambda *a, **k: (_ for _ in ()).throw(OSError(5, "EIO"))
        try:
            with self.assertRaises(RuntimeError):
                ns["api"]([])
        finally:
            ns["dledger"].start_transport = real_st
        self.assertEqual(len(calls), 0)
        self.assertEqual(ns["dledger"].summary(self.ledger)["global"]["spent"], 1)

    def test_pacing_enforced_sleep_before_send(self):
        os.environ["MIN_CALL_INTERVAL_S"] = "65"
        self.addCleanup(lambda: os.environ.pop("MIN_CALL_INTERVAL_S", None))
        ns = self.load_init(5)
        clock = _FakeClock()
        real_dl_time = ns["dledger"].time
        ns["dledger"].time = clock
        self.addCleanup(setattr, ns["dledger"], "time", real_dl_time)
        ns["time"] = clock
        self._patch_curl(ns, [(_ok_payload(),), (_ok_payload(),)])
        ns["api"]([])
        t0 = clock.t
        ns["api"]([])
        self.assertAlmostEqual(clock.t - t0, 65.0, places=1)   # second call waited the floor
        ents = json.load(open(self.ledger))["entries"]
        self.assertEqual([e["state"] for e in ents], ["completed", "completed"])

    def test_rate_limit_hint_gates_next_start(self):
        ns = self.load_init(5)
        err = {"error": {"code": "rate_limit_exceeded",
                         "message": "Rate limited. Please try again in 9.0s."}}
        clock = _FakeClock()
        real_dl_time = ns["dledger"].time
        ns["dledger"].time = clock
        self.addCleanup(setattr, ns["dledger"], "time", real_dl_time)
        ns["time"] = clock
        self._patch_curl(ns, [(json.dumps(err) + "\n429",), (_ok_payload(),)])
        with self.assertRaises(RuntimeError):
            ns["api"]([])
        data = json.load(open(self.ledger))
        self.assertGreater(data["rate_reset_until_epoch"], clock.t)  # hint stored
        t0 = clock.t
        ns["api"]([])                              # second call must wait out the hint
        self.assertGreaterEqual(clock.t - t0, 8.9)
        ents = data["entries"]
        self.assertEqual(ents[0]["state"], "completed")   # error response still a completed transport
        self.assertEqual(json.load(open(self.ledger))["entries"][1]["state"], "completed")

    def test_exhaustion_records_budget_stop_and_halts(self):
        ns = self.load_init(1)
        self._patch_curl(ns, [(_ok_payload(),)])
        ns["api"]([])
        with self.assertRaises(RuntimeError):
            ns["_reserve_call"]()
        self.assertTrue(any("budget_stop" in e for e in ns["transcript"] if isinstance(e, dict)))

    def test_legacy_counter_env_still_works_without_ledger(self):
        os.environ.pop("BUDGET_LEDGER", None)
        ns = self.load(max_calls=1)
        self._patch_curl(ns, [(_ok_payload(),)])
        ns["api"]([])
        with self.assertRaises(RuntimeError):
            ns["api"]([])


if __name__ == "__main__":
    unittest.main()
