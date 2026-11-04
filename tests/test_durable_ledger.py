"""Offline tests for tools/durable_ledger.py. Temp dirs, no network, no
credentials. Crash cases use fork+_exit to simulate SIGKILL-style death.
Each probe from the design's probe corpus maps to a distinct method."""
import fcntl, json, multiprocessing as mp, os, stat, sys, tempfile, time, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import durable_ledger as L


def _tmp():
    return tempfile.mkdtemp(prefix="ledger-test-")


class TestFailClosedLoads(unittest.TestCase):
    def setUp(self):
        self.d = _tmp()
        self.p = os.path.join(self.d, "ledger.json")

    def _write(self, content):
        with open(self.p, "w") as f:
            f.write(content)

    def test_missing_ledger_fails_closed(self):
        with self.assertRaises(L.LedgerError):
            L.reserve(self.p, "r1")
        self.assertFalse(os.path.exists(self.p))

    def test_reinit_refused(self):
        L.init_ledger(self.p, 5)
        with self.assertRaises(L.LedgerError):
            L.init_ledger(self.p, 5)

    def _bad_fails_closed(self, content):
        self._write(content)
        with self.assertRaises(L.LedgerError):
            L.reserve(self.p, "r")
        with open(self.p) as f:
            self.assertEqual(f.read(), content)  # file untouched

    def test_empty_fails_closed(self):
        self._bad_fails_closed("")

    def test_corrupt_fails_closed(self):
        self._bad_fails_closed("{trunc")

    def test_negative_count_fails_closed(self):
        self._bad_fails_closed(json.dumps({
            "version": 1, "global_cap": 5, "run_caps": {}, "entries": [],
            "counts": {"global": {"reserved": -1, "transport_started": 0,
                                  "completed": 0, "unknown": 0, "spent": -1},
                       "runs": {}}}))

    def test_negative_cap_fails_closed(self):
        self._bad_fails_closed(json.dumps(
            {"version": 1, "global_cap": -1, "run_caps": {}, "entries": []}))

    def test_wrong_type_fails_closed(self):
        self._bad_fails_closed("[]")

    def test_legacy_schema_fails_closed(self):
        self._bad_fails_closed(json.dumps({"used": 3, "history": []}))

    def test_counts_mismatch_detected(self):
        L.init_ledger(self.p, 10)
        L.reserve(self.p, "r")
        j = json.load(open(self.p))
        j["counts"]["global"]["spent"] = 0
        self._write(json.dumps(j))
        with self.assertRaises(L.LedgerError):
            L.reserve(self.p, "r")

    def test_duplicate_id_detected(self):
        L.init_ledger(self.p, 10)
        L.reserve(self.p, "r")
        L.reserve(self.p, "r")
        j = json.load(open(self.p))
        j["entries"][1]["id"] = j["entries"][0]["id"]
        j["counts"] = L._counts(j["entries"])
        self._write(json.dumps(j))
        with self.assertRaises(L.LedgerError):
            L.reserve(self.p, "r")

    def test_delete_does_not_reset_budget(self):
        L.init_ledger(self.p, 2)
        L.reserve(self.p, "r")
        os.unlink(self.p)
        with self.assertRaises(L.LedgerError):  # missing => fail closed, no implicit fresh start
            L.reserve(self.p, "r")


class TestAccounting(unittest.TestCase):
    def setUp(self):
        self.d = _tmp()
        self.p = os.path.join(self.d, "ledger.json")
        L.init_ledger(self.p, 5, {"r1": 3})

    def test_status_accounting(self):
        rid, _ = L.reserve(self.p, "r1")
        L.transition(self.p, rid, "transport_started")
        L.transition(self.p, rid, "completed", {"http": 200})
        L.reserve(self.p, "r1")
        rid3, _ = L.reserve(self.p, "r1")
        L.transition(self.p, rid3, "transport_started")
        L.transition(self.p, rid3, "unknown")
        c = L.summary(self.p)
        self.assertEqual(c["global"], {"reserved": 1, "transport_started": 0,
                                       "completed": 1, "unknown": 1, "spent": 3})

    def test_run_cap_enforced(self):
        for _ in range(3):
            L.reserve(self.p, "r1")
        with self.assertRaises(L.LedgerError):
            L.reserve(self.p, "r1")

    def test_global_cap_enforced_run_scopes_independent(self):
        for _ in range(3):
            L.reserve(self.p, "r1")
        L.reserve(self.p, "r2")
        L.reserve(self.p, "r2")
        with self.assertRaises(L.LedgerError):
            L.reserve(self.p, "r2")
        self.assertEqual(L.summary(self.p)["runs"]["r2"]["spent"], 2)

    def test_illegal_transitions_rejected(self):
        rid, _ = L.reserve(self.p, "r1")
        L.transition(self.p, rid, "transport_started")
        L.transition(self.p, rid, "completed", {"http": 200})
        rid2, _ = L.reserve(self.p, "r1")
        with self.assertRaises(L.LedgerError):
            L.transition(self.p, rid, "unknown")        # completed -> unknown
        with self.assertRaises(L.LedgerError):
            L.transition(self.p, rid2, "completed")     # reserved -> completed
        with self.assertRaises(L.LedgerError):
            L.transition(self.p, "not-a-real-id", "completed")

    def test_uuid_disambiguates_same_run_reservations(self):
        u1, _ = L.reserve(self.p, "r1")
        u2, _ = L.reserve(self.p, "r1")
        L.transition(self.p, u1, "transport_started")
        st = {e["id"]: e["state"] for e in json.load(open(self.p))["entries"]}
        self.assertEqual(st[u1], "transport_started")
        self.assertEqual(st[u2], "reserved")

    def test_every_reservation_consumes_budget_no_refund(self):
        rid, _ = L.reserve(self.p, "r1")
        L.transition(self.p, rid, "transport_started")
        L.transition(self.p, rid, "unknown")   # ambiguous outcome still spent
        self.assertEqual(L.summary(self.p)["global"]["spent"], 1)


class TestCrashWindows(unittest.TestCase):
    def _crash_at(self, stage):
        d = _tmp()
        p = os.path.join(d, "c.json")
        L.init_ledger(p, 10)
        L.reserve(p, "r")
        pid = os.fork()
        if pid == 0:
            L._hook = lambda s: os._exit(7) if s == stage else None
            try:
                L.reserve(p, "r")
            finally:
                os._exit(0)
        os.waitpid(pid, 0)
        return d, p

    def _check_crash(self, stage):
        d, p = self._crash_at(stage)
        n = L.summary(p)["global"]["spent"]   # ledger valid: old (1) or new (2), never empty
        self.assertIn(n, (1, 2))
        self.assertEqual(n == 2, stage == "replaced")
        L.reserve(p, "r")                      # next launch proceeds
        return n

    def test_crash_at_tmp_opened(self):
        self._check_crash("tmp_opened")

    def test_crash_at_tmp_written(self):
        self._check_crash("tmp_written")

    def test_crash_at_tmp_fsynced(self):
        self._check_crash("tmp_fsynced")

    def test_crash_at_replaced(self):
        self._check_crash("replaced")


class TestIOFailures(unittest.TestCase):
    def setUp(self):
        self.d = _tmp()
        self.p = os.path.join(self.d, "c.json")
        L.init_ledger(self.p, 10)

    def tearDown(self):
        L._fsync = lambda fd: os.fsync(fd)
        L._replace = lambda a, b: os.replace(a, b)

    def test_fsync_failure_raises_ledger_unchanged_tmp_cleaned(self):
        with open(self.p) as f:
            before = f.read()
        L._fsync = lambda fd: (_ for _ in ()).throw(OSError(5, "EIO"))
        with self.assertRaises(OSError):
            L.reserve(self.p, "r")
        self.assertEqual(open(self.p).read(), before)
        self.assertFalse([f for f in os.listdir(self.d) if ".tmp." in f])

    def test_replace_failure_raises_ledger_unchanged_tmp_cleaned(self):
        before = open(self.p).read()
        L._replace = lambda a, b: (_ for _ in ()).throw(OSError(28, "ENOSPC"))
        with self.assertRaises(OSError):
            L.reserve(self.p, "r")
        self.assertEqual(open(self.p).read(), before)
        self.assertFalse([f for f in os.listdir(self.d) if ".tmp." in f])

    def test_dir_fsync_failure_raises_no_rollback_no_reset(self):
        calls = {"n": 0}
        real = os.fsync
        def flaky(fd):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError(5, "EIO dir")
            real(fd)
        L._fsync = flaky
        with self.assertRaises(OSError):
            L.reserve(self.p, "r")
        L._fsync = lambda fd: os.fsync(fd)
        sp = L.summary(self.p)["global"]["spent"]
        self.assertIn(sp, (0, 1))              # OLD-OR-NEW, durability ambiguous
        L.reserve(self.p, "r")                 # continues from visible state, never resets
        self.assertEqual(L.summary(self.p)["global"]["spent"], sp + 1)


class TestDeadOwnerSweep(unittest.TestCase):
    def test_dead_owner_transport_started_swept_to_unknown(self):
        d = _tmp()
        p = os.path.join(d, "c.json")
        L.init_ledger(p, 10)
        pid = os.fork()
        if pid == 0:
            rid, _ = L.reserve(p, "r")
            L.transition(p, rid, "transport_started")
            os._exit(0)                        # owner dies mid-transport
        os.waitpid(pid, 0)
        L.reserve(p, "r")                      # next reserve sweeps
        c = L.summary(p)["global"]
        self.assertEqual(c["unknown"], 1)
        self.assertEqual(c["transport_started"], 0)
        self.assertEqual(c["spent"], 2)


def _reserve_worker(args):
    path, attempts = args
    got = 0
    for _ in range(attempts):
        try:
            L.reserve(path, "r")
            got += 1
        except L.LedgerError:
            break
    return got


class TestConcurrency(unittest.TestCase):
    def test_parallel_reserves_exactly_cap_granted(self):
        d = _tmp()
        p = os.path.join(d, "c.json")
        L.init_ledger(p, 60)
        with mp.Pool(8) as pool:
            grants = pool.map(_reserve_worker, [(p, 15)] * 8)
        self.assertEqual(sum(grants), 60)
        self.assertEqual(L.summary(p)["global"]["spent"], 60)


class TestMetadata(unittest.TestCase):
    def test_permissions_preserved_across_replace(self):
        d = _tmp()
        p = os.path.join(d, "c.json")
        L.init_ledger(p, 10)
        os.chmod(p, 0o640)
        L.reserve(p, "r")
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o640)


if __name__ == "__main__":
    unittest.main()


class TestStartTransport(unittest.TestCase):
    def setUp(self):
        self.d = _tmp()
        self.p = os.path.join(self.d, "s.json")
        L.init_ledger(self.p, 10)

    def test_marks_started_when_pacing_satisfied(self):
        rid, _ = L.reserve(self.p, "r")
        self.assertEqual(L.start_transport(self.p, rid), 0.0)
        st = {e["id"]: e["state"] for e in json.load(open(self.p))["entries"]}
        self.assertEqual(st[rid], "transport_started")

    def test_per_reservation_slots_from_shared_cursor(self):
        r1, w1 = L.reserve(self.p, "r", min_interval=60.0, now=1000.0)
        r2, w2 = L.reserve(self.p, "r", min_interval=60.0, now=1030.0)
        self.assertEqual(w1, 0.0)          # first slot: now
        self.assertAlmostEqual(w2, 30.0)   # second slot: cursor 1060
        self.assertAlmostEqual(L.start_transport(self.p, r2, now=1030.0), 30.0)
        st = {e["id"]: e["state"] for e in json.load(open(self.p))["entries"]}
        self.assertEqual(st[r2], "reserved")   # no state change while waiting
        self.assertEqual(L.start_transport(self.p, r2, now=1060.0), 0.0)

    def test_new_shared_reset_gates_after_sleep(self):
        rid, w = L.reserve(self.p, "r", min_interval=60.0, now=1000.0)
        self.assertEqual(w, 0.0)           # slot was immediate...
        L.note_rate_limit(self.p, 2000.0)  # ...but a newer shared reset lands
        self.assertAlmostEqual(L.start_transport(self.p, rid, now=1060.0), 940.0)
        st = {e["id"]: e["state"] for e in json.load(open(self.p))["entries"]}
        self.assertEqual(st[rid], "reserved")

    def test_rejects_non_reserved(self):
        rid, _ = L.reserve(self.p, "r")
        L.start_transport(self.p, rid)
        with self.assertRaises(L.LedgerError):
            L.start_transport(self.p, rid)

    def test_unknown_reservation_id(self):
        with self.assertRaises(L.LedgerError):
            L.start_transport(self.p, "not-a-real-id")


class TestHardening(unittest.TestCase):
    def setUp(self):
        self.d = _tmp()
        self.p = os.path.join(self.d, "h.json")

    def test_symlink_rejected(self):
        real = os.path.join(self.d, "real.json")
        L.init_ledger(real, 5)
        os.symlink(real, self.p)
        with self.assertRaises(L.LedgerError):
            L.reserve(self.p, "r")

    def test_hardlink_rejected(self):
        L.init_ledger(self.p, 5)
        os.link(self.p, os.path.join(self.d, "second.json"))
        with self.assertRaises(L.LedgerError):
            L.reserve(self.p, "r")

    def test_bad_timestamps_fail_closed(self):
        L.init_ledger(self.p, 5)
        j = json.load(open(self.p))
        j["entries"] = [{"id": "12345678-1234-1234-1234-123456789012",
                         "run": "r", "state": "reserved", "pid": 1,
                         "reserved_utc": "not-a-timestamp"}]
        j["counts"] = L._counts(j["entries"])
        with open(self.p, "w") as f:
            json.dump(j, f)
        with self.assertRaises(L.LedgerError):
            L.reserve(self.p, "r")

    def test_missing_pid_transport_started_swept_unknown_not_rejected(self):
        L.init_ledger(self.p, 5)
        j = json.load(open(self.p))
        j["entries"] = [{"id": "12345678-1234-1234-1234-123456789012",
                         "run": "r", "state": "transport_started",
                         "reserved_utc": "2026-11-04T00:00:00Z",
                         "started_utc": "2026-11-04T00:00:01Z"}]
        j["counts"] = L._counts(j["entries"])
        with open(self.p, "w") as f:
            json.dump(j, f)
        L.reserve(self.p, "r")   # load OK, sweep fires
        c = L.summary(self.p)["global"]
        self.assertEqual(c["unknown"], 1)
        self.assertEqual(c["spent"], 2)      # still counted, no refund

    def test_orphan_cleanup_only_dead_writers(self):
        L.init_ledger(self.p, 10)
        L.reserve(self.p, "r")
        dead_tmp = self.p + ".tmp.999999"     # no such pid
        live_tmp = self.p + f".tmp.{os.getppid()}"
        weird_tmp = self.p + ".tmp.notapid"
        for f in (dead_tmp, live_tmp, weird_tmp):
            open(f, "w").write("{}")
        L.reserve(self.p, "r")
        self.assertFalse(os.path.exists(dead_tmp))
        self.assertTrue(os.path.exists(live_tmp))
        self.assertTrue(os.path.exists(weird_tmp))

    def test_reconcile_sweeps_and_reports(self):
        L.init_ledger(self.p, 10)
        pid = os.fork()
        if pid == 0:
            rid, _ = L.reserve(self.p, "r")
            L.start_transport(self.p, rid)
            os._exit(0)
        os.waitpid(pid, 0)
        c = L.reconcile(self.p)["global"]
        self.assertEqual(c["unknown"], 1)
        self.assertEqual(c["transport_started"], 0)

    def test_note_rate_limit_persists(self):
        L.init_ledger(self.p, 10)
        L.note_rate_limit(self.p, 12345.0)
        j = json.load(open(self.p))
        self.assertEqual(j["rate_reset_until_epoch"], 12345.0)
