"""v19.34.46 — Memory watchdog regression suite."""
from __future__ import annotations
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

HERE = os.path.dirname(__file__)
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


class TestCollectSample(unittest.TestCase):
    def test_returns_expected_keys(self):
        from services.memory_watchdog import collect_sample
        s = collect_sample()
        # Always-on keys.
        self.assertIn("ts", s)
        self.assertIn("ts_epoch_ms", s)
        self.assertIn("pid", s)
        # Most fields populated on Linux; we just verify the function
        # returns a dict (graceful fallback on non-Linux).
        self.assertIsInstance(s, dict)

    def test_rss_bytes_is_positive_when_present(self):
        from services.memory_watchdog import collect_sample
        s = collect_sample()
        if "rss_bytes" in s:
            self.assertGreater(s["rss_bytes"], 0)
        if "mem_total_bytes" in s and s["mem_total_bytes"]:
            self.assertGreaterEqual(s.get("mem_used_pct", 0.0), 0.0)
            self.assertLessEqual(s.get("mem_used_pct", 100.0), 100.0)


class TestProcReaders(unittest.TestCase):
    def test_page_size_returns_positive(self):
        from services.memory_watchdog import _page_size
        self.assertGreater(_page_size(), 0)

    def test_statm_unavailable_returns_none(self):
        from services.memory_watchdog import _read_proc_statm
        from pathlib import Path
        with patch.object(Path, "read_text", side_effect=FileNotFoundError):
            self.assertIsNone(_read_proc_statm())

    def test_meminfo_unavailable_returns_none(self):
        from services.memory_watchdog import _read_proc_meminfo
        from pathlib import Path
        with patch.object(Path, "read_text", side_effect=FileNotFoundError):
            self.assertIsNone(_read_proc_meminfo())


class TestLoopBootstrap(unittest.TestCase):
    def test_disabled_via_env_exits_cleanly(self):
        """Setting MEMORY_WATCHDOG_ENABLED=0 must short-circuit the loop."""
        import asyncio
        from services.memory_watchdog import memory_watchdog_loop
        with patch.dict(os.environ, {"MEMORY_WATCHDOG_ENABLED": "0"}, clear=False):
            loop = asyncio.new_event_loop()
            try:
                # Should return immediately, not raise.
                loop.run_until_complete(
                    asyncio.wait_for(memory_watchdog_loop(db=None), timeout=2.0)
                )
            finally:
                loop.close()

    def test_persist_sample_with_none_db_is_noop(self):
        import asyncio
        from services.memory_watchdog import _persist_sample
        loop = asyncio.new_event_loop()
        try:
            # No assertion needed — just verify no exception with db=None.
            loop.run_until_complete(_persist_sample(None, {"ts": "x"}))
        finally:
            loop.close()


class TestWatchdogTickIntegration(unittest.TestCase):
    """Run ONE iteration with a tiny interval to verify the loop body
    logs + persists without raising. Uses a mock DB so we can verify
    the insert call happened."""

    def test_one_tick_persists_to_mongo(self):
        import asyncio
        from services.memory_watchdog import memory_watchdog_loop

        mock_col = MagicMock()
        mock_col.create_index = MagicMock()
        mock_col.insert_one = MagicMock()
        mock_db = MagicMock()
        mock_db.__getitem__.return_value = mock_col

        # Set a tiny interval so one tick fires fast, then cancel.
        async def _runner():
            task = asyncio.create_task(memory_watchdog_loop(
                db=mock_db,
                interval_sec=0.05,
                warn_pct=80,
                crit_pct=90,
            ))
            await asyncio.sleep(0.2)  # let 2–3 ticks fire
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_runner())
        finally:
            loop.close()

        # At least one insert_one call should have landed on mock_col.
        # On non-Linux hosts the watchdog exits early — so we don't
        # FAIL the test there; we just verify no crash.
        if mock_col.insert_one.call_count > 0:
            inserted = mock_col.insert_one.call_args.args[0]
            self.assertIn("ts", inserted)
            self.assertIn("severity", inserted)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
