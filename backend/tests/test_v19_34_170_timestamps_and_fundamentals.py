"""
v19.34.170 — timestamp helpers + fundamentals fallback regression tests
=======================================================================

Two surfaces tested:

1. ``utils.timestamps`` round-trips between ISO strings and BSON
   datetimes safely (no naive datetimes leak out, no exceptions on
   empty/garbage input).

2. ``TradeContextService._capture_fundamental_context`` no longer
   raises (or warns at WARN) when the IB direct service reports
   ``connected=False``. It must:
     a. Skip the IB call entirely (no ConnectionError logged at WARN).
     b. Fall back to ``FundamentalDataService`` for pe_ratio /
        market_cap when those are missing.
     c. Still populate earnings-proximity fields from the DB when
        an earnings row is within 7 days.

3. Position manager's EOD heartbeat write conforms to the canonical
   ``sentcom_thoughts`` schema (kind + content + timestamp + created_at).
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Make `backend/` importable when running via `pytest backend/tests/`.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# --------------------------------------------------------------------------
# 1) utils.timestamps
# --------------------------------------------------------------------------
class TestTimestampHelpers(unittest.TestCase):

    def test_now_helpers_are_tz_aware(self):
        from utils.timestamps import now_bson, now_iso

        d = now_bson()
        self.assertIsInstance(d, datetime)
        self.assertIsNotNone(d.tzinfo, "now_bson must return tz-aware datetime")

        s = now_iso()
        self.assertIsInstance(s, str)
        # ISO 8601 with offset (Python 3.11+ uses "+00:00")
        self.assertTrue(s.endswith("+00:00") or s.endswith("Z"))

    def test_parse_iso_string_to_bson(self):
        from utils.timestamps import parse_to_bson

        s = "2026-02-15T12:34:56+00:00"
        d = parse_to_bson(s)
        self.assertIsInstance(d, datetime)
        self.assertEqual(d.year, 2026)
        self.assertEqual(d.tzinfo, timezone.utc)

    def test_parse_z_suffix_iso(self):
        from utils.timestamps import parse_to_bson

        s = "2026-02-15T12:34:56Z"  # NB: trailing Z, pre-3.11 fromisoformat-hostile
        d = parse_to_bson(s)
        self.assertIsNotNone(d)
        self.assertEqual(d.minute, 34)

    def test_parse_bson_passthrough(self):
        from utils.timestamps import parse_to_bson

        d = datetime(2026, 2, 15, tzinfo=timezone.utc)
        self.assertIs(parse_to_bson(d), d)

    def test_parse_naive_datetime_assumed_utc(self):
        from utils.timestamps import parse_to_bson

        naive = datetime(2026, 2, 15, 12, 34, 56)
        d = parse_to_bson(naive)
        self.assertEqual(d.tzinfo, timezone.utc)

    def test_parse_none_and_garbage_safe(self):
        from utils.timestamps import parse_to_bson, parse_to_iso

        self.assertIsNone(parse_to_bson(None))
        self.assertIsNone(parse_to_bson(""))
        self.assertIsNone(parse_to_bson("not-a-date"))
        self.assertIsNone(parse_to_iso(None))
        self.assertIsNone(parse_to_iso("garbage"))

    def test_stamps_returns_both_ts_and_ts_dt(self):
        from utils.timestamps import stamps

        out = stamps()
        self.assertIn("ts", out)
        self.assertIn("ts_dt", out)
        self.assertIsInstance(out["ts"], str)
        self.assertIsInstance(out["ts_dt"], datetime)

        # Round trip: ts string parses back to same dt.
        from utils.timestamps import parse_to_bson
        round_trip = parse_to_bson(out["ts"])
        self.assertEqual(round_trip, out["ts_dt"])

    def test_epoch_ms_monotonic(self):
        from utils.timestamps import epoch_ms

        a = epoch_ms()
        b = epoch_ms()
        self.assertGreaterEqual(b, a)
        self.assertGreater(a, 1_700_000_000_000)


# --------------------------------------------------------------------------
# 2) TradeContextService fundamentals fallback
# --------------------------------------------------------------------------
class TestFundamentalsReconnect(unittest.TestCase):

    def setUp(self):
        from services.trade_context_service import TradeContextService
        from models.learning_models import TradeContext

        self.svc = TradeContextService()
        self.ctx = TradeContext()

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_skips_ib_when_not_connected(self):
        """When IB reports connected=False, get_fundamentals must NOT
        be called (no ConnectionError noise in logs)."""
        ib = MagicMock()
        ib.get_connection_status.return_value = {"connected": False}
        ib.get_fundamentals = AsyncMock(
            side_effect=ConnectionError("Not connected to IB")
        )
        self.svc._ib_service = ib

        # No mock for Finnhub → service should silently degrade.
        with patch("services.fundamental_data_service.get_fundamental_data_service") as ff:
            mock_svc = MagicMock()
            mock_svc.get_fundamentals = AsyncMock(return_value=None)
            ff.return_value = mock_svc

            self._run(self.svc._capture_fundamental_context(self.ctx, "AAPL"))

        ib.get_fundamentals.assert_not_called()
        self.assertIsNotNone(self.ctx.fundamentals)

    def test_finnhub_fallback_populates_pe_and_marketcap(self):
        """When IB is down, Finnhub data should populate pe_ratio and market_cap."""
        ib = MagicMock()
        ib.get_connection_status.return_value = {"connected": False}
        self.svc._ib_service = ib

        from services.fundamental_data_service import FundamentalData
        fake = FundamentalData(
            symbol="AAPL",
            pe_ratio=28.4,
            market_cap=3_500_000.0,
            beta=1.2,
        )

        with patch("services.fundamental_data_service.get_fundamental_data_service") as ff:
            mock_svc = MagicMock()
            mock_svc.get_fundamentals = AsyncMock(return_value=fake)
            ff.return_value = mock_svc

            self._run(self.svc._capture_fundamental_context(self.ctx, "AAPL"))

        self.assertAlmostEqual(self.ctx.fundamentals.pe_ratio, 28.4, places=4)
        self.assertAlmostEqual(self.ctx.fundamentals.market_cap, 3_500_000.0)

    def test_ib_call_executes_when_connected(self):
        """When IB reports connected, the IB path should be used and
        Finnhub fallback only fills missing fields."""
        ib = MagicMock()
        ib.get_connection_status.return_value = {"connected": True}
        ib.get_fundamentals = AsyncMock(return_value={
            "success": True,
            "data": {
                "pe_ratio": 22.1,
                "market_cap": 100.0,
                "short_interest_percent": 1.5,
                "float_shares": 1_000_000,
                "institutional_ownership_percent": 75.0,
            },
        })
        self.svc._ib_service = ib

        # Finnhub should NOT be called since IB returned both fields.
        with patch("services.fundamental_data_service.get_fundamental_data_service") as ff:
            mock_svc = MagicMock()
            mock_svc.get_fundamentals = AsyncMock(return_value=None)
            ff.return_value = mock_svc

            self._run(self.svc._capture_fundamental_context(self.ctx, "MSFT"))

            mock_svc.get_fundamentals.assert_not_called()

        self.assertEqual(self.ctx.fundamentals.pe_ratio, 22.1)
        self.assertEqual(self.ctx.fundamentals.market_cap, 100.0)
        self.assertEqual(self.ctx.fundamentals.short_interest_percent, 1.5)


# --------------------------------------------------------------------------
# 3) EOD heartbeat schema (static source inspection — no DB needed)
# --------------------------------------------------------------------------
class TestEodHeartbeatSchema(unittest.TestCase):
    """Static guard against v169 regressing back to an ISO-string
    `created_at` write in the EOD heartbeat (which broke the TTL
    index and the diagnostics tab queries)."""

    def test_heartbeat_uses_bson_created_at_and_iso_timestamp(self):
        from pathlib import Path

        pm = Path(__file__).resolve().parents[1] / "services" / "position_manager.py"
        text = pm.read_text(encoding="utf-8")

        # The heartbeat block is narrow — slice from the marker
        # comment to the end of insert_one call.
        marker = "v19.34.169 — EOD HEARTBEAT"
        self.assertIn(marker, text, "EOD heartbeat marker missing")
        idx = text.index(marker)
        block = text[idx: idx + 4500]

        self.assertIn('"kind": "system"', block,
                      "EOD heartbeat must set kind=system (canonical schema)")
        self.assertIn('"content"', block,
                      "EOD heartbeat must set canonical `content` field")
        self.assertIn('"timestamp": now_iso()', block,
                      "EOD heartbeat must write ISO timestamp for diagnostics queries")
        self.assertIn('"created_at": now_bson()', block,
                      "EOD heartbeat must write BSON datetime for TTL index")
        self.assertIn('"category": "eod_heartbeat"', block,
                      "Keep top-level category for operator queries")


if __name__ == "__main__":
    unittest.main(verbosity=2)
