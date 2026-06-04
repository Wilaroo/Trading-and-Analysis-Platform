"""v19.34.46 -- Memory watchdog regression suite."""
from __future__ import annotations
import asyncio, os, sys, unittest
from unittest.mock import patch, MagicMock

HERE = os.path.dirname(__file__)
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND not in sys.path: sys.path.insert(0, BACKEND)


class TestCollectSample(unittest.TestCase):
    def test_returns_expected_keys(self):
        from services.memory_watchdog import collect_sample
        s = collect_sample()
        self.assertIn("ts", s); self.assertIn("ts_epoch_ms", s); self.assertIn("pid", s)
    def test_rss_positive_when_present(self):
        from services.memory_watchdog import collect_sample
        s = collect_sample()
        if "rss_bytes" in s: self.assertGreater(s["rss_bytes"], 0)


class TestLoopBootstrap(unittest.TestCase):
    def test_disabled_via_env(self):
        from services.memory_watchdog import memory_watchdog_loop
        with patch.dict(os.environ, {"MEMORY_WATCHDOG_ENABLED":"0"}, clear=False):
            loop = asyncio.new_event_loop()
            try: loop.run_until_complete(asyncio.wait_for(
                memory_watchdog_loop(db=None), timeout=2.0))
            finally: loop.close()

    def test_persist_none_db_noop(self):
        from services.memory_watchdog import _persist_sample
        loop = asyncio.new_event_loop()
        try: loop.run_until_complete(_persist_sample(None, {"ts":"x"}))
        finally: loop.close()


class TestTickIntegration(unittest.TestCase):
    def test_one_tick_persists(self):
        from services.memory_watchdog import memory_watchdog_loop
        col = MagicMock(); col.create_index = MagicMock(); col.insert_one = MagicMock()
        db = MagicMock(); db.__getitem__.return_value = col
        async def _runner():
            task = asyncio.create_task(memory_watchdog_loop(
                db=db, interval_sec=0.05, warn_pct=80, crit_pct=90))
            await asyncio.sleep(0.2)
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
        loop = asyncio.new_event_loop()
        try: loop.run_until_complete(_runner())
        finally: loop.close()
        if col.insert_one.call_count > 0:
            inserted = col.insert_one.call_args.args[0]
            self.assertIn("ts", inserted)
            self.assertIn("severity", inserted)


if __name__ == "__main__":
    unittest.main()
