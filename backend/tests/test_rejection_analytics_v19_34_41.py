"""v19.34.41 — Rejection Analytics + Scanner Quality Score test suite."""
import os
import sys
import unittest
from datetime import datetime, time, timedelta, timezone
from unittest.mock import MagicMock

HERE = os.path.dirname(__file__)
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def _fake_db_with(bot_trades=(), trade_drops=()):
    """Build a stub db that returns the given rows from .find()."""
    bt_coll = MagicMock()
    bt_coll.find = MagicMock(return_value=iter(bot_trades))

    td_coll = MagicMock()
    td_cursor = MagicMock()
    td_cursor.sort = MagicMock(return_value=iter(trade_drops))
    td_coll.find = MagicMock(return_value=td_cursor)

    db = MagicMock()
    db.__getitem__ = lambda self, name: {
        "bot_trades": bt_coll,
        "trade_drops": td_coll,
    }[name]
    return db


class TestReasonNormalisation(unittest.TestCase):
    def test_normalise_stale(self):
        from routers.rejection_analytics_router import _normalise_reason
        self.assertEqual(_normalise_reason("rejected_stale_alert"), "stale_alert")
        self.assertEqual(_normalise_reason("Stale alert from scanner"), "stale_alert")

    def test_normalise_live_price_gate(self):
        from routers.rejection_analytics_router import _normalise_reason
        self.assertEqual(_normalise_reason("live_price_gate"), "live_price_gate")
        self.assertEqual(_normalise_reason("live-price REJECTED"), "live_price_gate")

    def test_normalise_min_tick(self):
        from routers.rejection_analytics_router import _normalise_reason
        self.assertEqual(_normalise_reason("Error 110: min tick"), "min_tick")

    def test_normalise_error_202(self):
        from routers.rejection_analytics_router import _normalise_reason
        self.assertEqual(_normalise_reason("Error 202: cancelled by ib"), "error_202")

    def test_unknown_to_other(self):
        from routers.rejection_analytics_router import _normalise_reason
        self.assertEqual(_normalise_reason("some random thing"), "other")
        self.assertEqual(_normalise_reason(""), "other")
        self.assertEqual(_normalise_reason(None), "other")


class TestScoreBucket(unittest.TestCase):
    def test_buckets(self):
        from routers.rejection_analytics_router import _score_bucket
        self.assertEqual(_score_bucket(0.95), "excellent")
        self.assertEqual(_score_bucket(0.90), "excellent")
        self.assertEqual(_score_bucket(0.80), "good")
        self.assertEqual(_score_bucket(0.60), "fair")
        self.assertEqual(_score_bucket(0.40), "poor")
        self.assertEqual(_score_bucket(0.0), "poor")


class TestAggregation(unittest.TestCase):
    def _make_bot_trade(self, status, reason=None, setup="orb_breakout", symbol="AAPL"):
        return {
            "id": f"T-{symbol}",
            "symbol": symbol,
            "setup_type": setup,
            "setup_variant": setup,
            "direction": "long",
            "status": status,
            "entered_at": "2026-02-17T14:30:00+00:00",
            "rejection_reason": reason,
        }

    def _make_drop(self, gate, reason, setup="9_ema_scalp"):
        return {
            "ts": "2026-02-17T14:35:00+00:00",
            "ts_epoch_ms": 1739803500000,
            "gate": gate,
            "symbol": "MSFT",
            "setup_type": setup,
            "direction": "long",
            "reason": reason,
        }

    def test_empty_returns_perfect_score(self):
        from routers.rejection_analytics_router import _aggregate_bot_trades, _aggregate_trade_drops, _compose_response
        db = _fake_db_with()
        start = datetime(2026, 2, 17, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        bot = _aggregate_bot_trades(db, start, end)
        drops = _aggregate_trade_drops(db, start, end)
        out = _compose_response("2026-02-17", bot, drops)
        self.assertEqual(out["totals"]["accepted"], 0)
        self.assertEqual(out["totals"]["rejected"], 0)
        self.assertEqual(out["scanner_quality_score"], 1.0)
        self.assertEqual(out["score_bucket"], "excellent")
        self.assertEqual(out["by_reason"], [])

    def test_mixed_scores_correctly(self):
        """8 filled + 2 stale_alert (scanner_quality) = 8/(8+2) = 0.80 → good"""
        from routers.rejection_analytics_router import _aggregate_bot_trades, _aggregate_trade_drops, _compose_response
        rows = []
        for i in range(8):
            rows.append(self._make_bot_trade("filled", symbol=f"AAA{i}"))
        for i in range(2):
            rows.append(self._make_bot_trade("rejected_stale_alert",
                                             reason="rejected_stale_alert",
                                             symbol=f"BBB{i}"))
        db = _fake_db_with(bot_trades=rows)
        start = datetime(2026, 2, 17, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        bot = _aggregate_bot_trades(db, start, end)
        drops = _aggregate_trade_drops(db, start, end)
        out = _compose_response("2026-02-17", bot, drops)
        self.assertEqual(out["totals"]["accepted"], 8)
        self.assertEqual(out["totals"]["rejected"], 2)
        self.assertEqual(out["totals"]["scanner_signals"], 10)
        self.assertAlmostEqual(out["scanner_quality_score"], 0.80, places=2)
        self.assertEqual(out["score_bucket"], "good")
        self.assertEqual(out["by_category"]["scanner_quality"], 2)
        # Reason breakdown
        reasons = {r["reason_key"]: r["count"] for r in out["by_reason"]}
        self.assertEqual(reasons.get("stale_alert"), 2)

    def test_broker_rejection_does_not_penalise_scanner_score(self):
        """Broker-category rejections should NOT pull the scanner score down."""
        from routers.rejection_analytics_router import _aggregate_bot_trades, _aggregate_trade_drops, _compose_response
        rows = []
        for i in range(10):
            rows.append(self._make_bot_trade("filled", symbol=f"AAA{i}"))
        drops_rows = [
            self._make_drop("broker_rejected", "Error 202: cancelled by ib"),
            self._make_drop("execution_exception", "Error 110: min tick violation"),
        ]
        db = _fake_db_with(bot_trades=rows, trade_drops=drops_rows)
        start = datetime(2026, 2, 17, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        bot = _aggregate_bot_trades(db, start, end)
        drops = _aggregate_trade_drops(db, start, end)
        out = _compose_response("2026-02-17", bot, drops)
        # 10 filled, 0 scanner-quality rejections → score = 10/(10+0) = 1.0
        self.assertEqual(out["scanner_quality_score"], 1.0)
        self.assertEqual(out["score_bucket"], "excellent")
        # But broker rejections ARE counted in totals
        self.assertEqual(out["totals"]["rejected"], 2)
        self.assertEqual(out["by_category"]["broker"], 2)

    def test_recent_rejections_capped(self):
        from routers.rejection_analytics_router import _aggregate_bot_trades, _compose_response
        rows = []
        for i in range(40):
            rows.append(self._make_bot_trade("rejected_stale_alert",
                                             reason="rejected_stale_alert",
                                             symbol=f"S{i}"))
        db = _fake_db_with(bot_trades=rows)
        start = datetime(2026, 2, 17, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        bot = _aggregate_bot_trades(db, start, end)
        # bot_trades aggregator caps at 20 internally
        self.assertEqual(len(bot["recent_rejections"]), 20)

    def test_by_setup_breakdown(self):
        from routers.rejection_analytics_router import _aggregate_bot_trades, _aggregate_trade_drops, _compose_response
        rows = [
            self._make_bot_trade("filled", setup="orb_breakout", symbol="A"),
            self._make_bot_trade("filled", setup="orb_breakout", symbol="B"),
            self._make_bot_trade("rejected_stale_alert", reason="stale",
                                 setup="orb_breakout", symbol="C"),
            self._make_bot_trade("filled", setup="9_ema_scalp", symbol="D"),
        ]
        db = _fake_db_with(bot_trades=rows)
        start = datetime(2026, 2, 17, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        bot = _aggregate_bot_trades(db, start, end)
        drops = _aggregate_trade_drops(db, start, end)
        out = _compose_response("2026-02-17", bot, drops)
        self.assertEqual(out["by_setup"]["orb_breakout"]["accepted"], 2)
        self.assertEqual(out["by_setup"]["orb_breakout"]["rejected"], 1)
        self.assertEqual(out["by_setup"]["9_ema_scalp"]["accepted"], 1)


class TestEndpointShape(unittest.TestCase):
    def test_endpoint_returns_complete_shape_with_no_db(self):
        """When db is None, endpoint returns a degraded-but-complete payload."""
        from routers import rejection_analytics_router as mod
        # Patch _get_db to return None
        orig = mod._get_db
        try:
            mod._get_db = lambda: None
            out = mod.rejection_analytics(date="2026-02-17")
        finally:
            mod._get_db = orig
        self.assertFalse(out["success"])
        self.assertEqual(out["error"], "db_unavailable")
        # Shape contract preserved
        for key in ("trading_date_et", "scanner_quality_score",
                    "scanner_quality_score_pct", "score_bucket",
                    "totals", "by_category", "by_reason",
                    "by_setup", "recent_rejections"):
            self.assertIn(key, out)

    def test_bad_date_raises_400(self):
        from routers import rejection_analytics_router as mod
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            mod.rejection_analytics(date="not-a-date")
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
