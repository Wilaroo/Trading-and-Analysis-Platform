#!/usr/bin/env python3
"""
v19.34.44 — Stale Alert TTL deploy patch (CHUNK 5 of 5)

Scope: Drop the new pytest file into place.
Purely additive (overwrites if present, idempotent on rerun).

Usage on DGX:
    cd ~/Trading-and-Analysis-Platform
    python3 v19_34_44_chunk5_test_file.py
    cd backend && python -m pytest tests/test_stale_alert_ttl_v19_34_44.py tests/test_trade_drop_instrumentation.py -v
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
TEST_PATH = ROOT / "backend" / "tests" / "test_stale_alert_ttl_v19_34_44.py"

CONTENT = '''"""v19.34.44 -- Stale Alert TTL regression suite."""
from __future__ import annotations

import asyncio
import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

HERE = os.path.dirname(__file__)
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def _make_bot():
    bot = MagicMock()
    bot._open_trades = {}
    bot.risk_params = MagicMock(allow_multiple_entries_per_symbol_dir=False)
    bot._db = None
    bot.record_rejection = MagicMock()
    return bot


def _alert(symbol="AAPL", setup_type="9_ema_scalp", direction="long",
           age_seconds=None, iso_age_seconds=None, no_timestamp=False):
    now = time.time()
    alert = {"symbol": symbol, "setup_type": setup_type, "direction": direction}
    if no_timestamp:
        return alert
    if age_seconds is not None:
        alert["triggered_at_unix"] = int(now - age_seconds)
    if iso_age_seconds is not None:
        iso_dt = datetime.now(timezone.utc) - timedelta(seconds=iso_age_seconds)
        alert["triggered_at"] = iso_dt.isoformat()
    return alert


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Base(unittest.TestCase):
    def _evaluate(self, alert, bot, env=None):
        from services.opportunity_evaluator import OpportunityEvaluator
        with patch.dict(os.environ, env or {}, clear=False):
            return _run(OpportunityEvaluator().evaluate_opportunity(alert, bot))


class TestStaleAlertTTL(_Base):
    def test_stale_alert_unix_age_above_ttl_is_rejected(self):
        bot = _make_bot()
        result = self._evaluate(_alert(age_seconds=45), bot,
                                env={"STALE_ALERT_TTL_SECONDS": "30"})
        self.assertIsNone(result)
        bot.record_rejection.assert_called_once()
        kw = bot.record_rejection.call_args.kwargs
        self.assertEqual(kw.get("reason_code"), "stale_alert_ttl")
        self.assertGreaterEqual(kw["context"]["alert_age_seconds"], 30.0)

    def test_fresh_alert_within_ttl_bypasses_gate(self):
        bot = _make_bot()
        try:
            self._evaluate(_alert(age_seconds=5), bot,
                           env={"STALE_ALERT_TTL_SECONDS": "30"})
        except Exception:
            pass
        for c in bot.record_rejection.call_args_list:
            self.assertNotEqual(c.kwargs.get("reason_code"), "stale_alert_ttl")

    def test_missing_timestamp_is_fail_open(self):
        bot = _make_bot()
        try:
            self._evaluate(_alert(no_timestamp=True), bot,
                           env={"STALE_ALERT_TTL_SECONDS": "30"})
        except Exception:
            pass
        for c in bot.record_rejection.call_args_list:
            self.assertNotEqual(c.kwargs.get("reason_code"), "stale_alert_ttl")

    def test_disabled_when_ttl_zero(self):
        bot = _make_bot()
        try:
            self._evaluate(_alert(age_seconds=600), bot,
                           env={"STALE_ALERT_TTL_SECONDS": "0"})
        except Exception:
            pass
        for c in bot.record_rejection.call_args_list:
            self.assertNotEqual(c.kwargs.get("reason_code"), "stale_alert_ttl")

    def test_env_override_extends_ttl(self):
        bot = _make_bot()
        try:
            self._evaluate(_alert(age_seconds=45), bot,
                           env={"STALE_ALERT_TTL_SECONDS": "60"})
        except Exception:
            pass
        for c in bot.record_rejection.call_args_list:
            self.assertNotEqual(c.kwargs.get("reason_code"), "stale_alert_ttl")

    def test_iso_triggered_at_fallback_parses(self):
        bot = _make_bot()
        alert = _alert(iso_age_seconds=120)
        alert.pop("triggered_at_unix", None)
        result = self._evaluate(alert, bot, env={"STALE_ALERT_TTL_SECONDS": "30"})
        self.assertIsNone(result)
        self.assertTrue(any(
            c.kwargs.get("reason_code") == "stale_alert_ttl"
            for c in bot.record_rejection.call_args_list
        ))

    def test_default_ttl_is_30_seconds(self):
        bot = _make_bot()
        env = {k: v for k, v in os.environ.items() if k != "STALE_ALERT_TTL_SECONDS"}
        with patch.dict(os.environ, env, clear=True):
            from services.opportunity_evaluator import OpportunityEvaluator
            result = _run(OpportunityEvaluator().evaluate_opportunity(
                _alert(age_seconds=31), bot,
            ))
        self.assertIsNone(result)


class TestGateRegistration(unittest.TestCase):
    def test_stale_alert_ttl_is_known_gate(self):
        from services.trade_drop_recorder import KNOWN_GATES
        self.assertIn("stale_alert_ttl", KNOWN_GATES)

    def test_rejection_analytics_normalises_stale_alert_ttl(self):
        from routers.rejection_analytics_router import _normalise_reason, REASON_MAP
        self.assertEqual(_normalise_reason("stale_alert_ttl"), "stale_alert")
        self.assertIn("stale_alert_ttl", REASON_MAP)


class TestNarrative(unittest.TestCase):
    def test_compose_narrative_handles_stale_alert_ttl(self):
        from services.trading_bot_service import TradingBotService
        bot = TradingBotService.__new__(TradingBotService)
        msg = TradingBotService._compose_rejection_narrative(
            bot,
            symbol="AAPL", setup_type="9_ema_scalp", direction="long",
            reason_code="stale_alert_ttl",
            ctx={"alert_age_seconds": 42.0, "ttl_seconds": 30.0},
        )
        self.assertIn("AAPL", msg)
        self.assertIn("pipeline", msg.lower())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
'''


def main() -> int:
    TEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEST_PATH.write_text(CONTENT)
    print(f"✅ Wrote {TEST_PATH} ({len(CONTENT)} bytes)")
    print()
    print("Now run the full v19.34.44 verification:")
    print("    cd backend && python -m pytest \\")
    print("      tests/test_stale_alert_ttl_v19_34_44.py \\")
    print("      tests/test_trade_drop_instrumentation.py \\")
    print("      tests/test_rejection_analytics_v19_34_41.py -v")
    return 0


if __name__ == "__main__":
    sys.exit(main())
