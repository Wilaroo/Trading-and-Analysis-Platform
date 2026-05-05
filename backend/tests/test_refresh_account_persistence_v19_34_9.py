"""
test_refresh_account_persistence_v19_34_9.py — pin v19.34.9 fix
for the refresh-account read/write source mismatch.

Operator surfaced the bug 2026-05-05 PM:

  Spark output:
    BEFORE: starting_capital=100000.0  max_daily_loss_usd=1000.0
    Refresh: success=true, old=$236487, new=$236487, delta=$0, source=rpc
    AFTER:  starting_capital=100000.0  max_daily_loss_usd=1000.0  ← STILL STALE

Root cause:
  1. `refresh-account` wrote ONLY to `_trading_bot.risk_params.starting_capital`
     (in-memory) — never persisted to Mongo `bot_state`.
  2. `effective-limits` reads from Mongo `bot_state.risk_params.starting_capital`
     via `risk_caps_service.compute_effective_risk_caps`.
  3. So in-memory was correct ($236k) but Mongo was stale ($100k).

v19.34.9 fix:
  (a) `refresh-account` now `await bot._save_state()` after the in-memory
      update, persisting risk_params to Mongo.
  (b) `refresh-account` also recomputes `max_daily_loss` (USD absolute).
  (c) `risk_caps_service._read_bot_risk_params` adds explicit
      `_id="bot_state"` filter to guard against legacy alternative docs.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# --------------------------------------------------------------------------
# refresh-account end-to-end persistence
# --------------------------------------------------------------------------

class TestRefreshAccountPersistsToMongo:

    @pytest.mark.asyncio
    async def test_refresh_account_calls_save_state(self):
        """The fix: after the in-memory update, the endpoint MUST
        await `bot._save_state()` so risk_caps_service sees the new
        value in Mongo."""
        from routers import trading_bot as tb
        from services.trading_bot_service import RiskParameters

        bot = MagicMock()
        bot.risk_params = RiskParameters()
        bot.risk_params.starting_capital = 100000.0
        bot.risk_params.max_daily_loss = 0.0
        bot.risk_params.max_daily_loss_pct = 1.0
        bot._save_state = AsyncMock()

        original_bot = tb._trading_bot
        tb._trading_bot = bot

        # Patch routers.ib._pushed_ib_data via the import path the endpoint uses
        with patch.dict(
            "routers.ib._pushed_ib_data",
            {"account": {"NetLiquidation": 236487.27}},
            clear=True,
        ):
            try:
                resp = await tb.refresh_account()
            finally:
                tb._trading_bot = original_bot

        assert resp["success"] is True
        assert resp["old_starting_capital"] == 100000.0
        assert resp["new_starting_capital"] == 236487.27
        assert resp["delta"] == 236487.27 - 100000.0
        assert resp["persisted_to_mongo"] is True
        # CRITICAL: _save_state was actually awaited
        bot._save_state.assert_awaited_once()
        assert bot.risk_params.starting_capital == 236487.27

    @pytest.mark.asyncio
    async def test_refresh_account_recomputes_max_daily_loss(self):
        """Refresh-account should also recompute the absolute USD
        daily-loss cap from new starting_capital × max_daily_loss_pct."""
        from routers import trading_bot as tb
        from services.trading_bot_service import RiskParameters

        bot = MagicMock()
        bot.risk_params = RiskParameters()
        bot.risk_params.starting_capital = 100000.0
        bot.risk_params.max_daily_loss = 1000.0
        bot.risk_params.max_daily_loss_pct = 1.0
        bot._save_state = AsyncMock()

        original_bot = tb._trading_bot
        tb._trading_bot = bot

        with patch.dict(
            "routers.ib._pushed_ib_data",
            {"account": {"NetLiquidation": 500000.0}},
            clear=True,
        ):
            try:
                resp = await tb.refresh_account()
            finally:
                tb._trading_bot = original_bot

        # New starting_capital = $500k, pct = 1% → max_daily_loss = $5000
        assert bot.risk_params.max_daily_loss == 5000.0
        assert resp["max_daily_loss_usd_recomputed"] == 5000.0

    @pytest.mark.asyncio
    async def test_refresh_account_save_failure_does_not_block_response(self):
        """If `_save_state` raises, the in-memory update has happened —
        endpoint must return success on the in-memory side (next manage-
        loop save will retry persisting)."""
        from routers import trading_bot as tb
        from services.trading_bot_service import RiskParameters

        bot = MagicMock()
        bot.risk_params = RiskParameters()
        bot.risk_params.starting_capital = 100000.0
        bot.risk_params.max_daily_loss_pct = 1.0
        bot._save_state = AsyncMock(side_effect=RuntimeError("mongo down"))

        original_bot = tb._trading_bot
        tb._trading_bot = bot

        with patch.dict(
            "routers.ib._pushed_ib_data",
            {"account": {"NetLiquidation": 250000.0}},
            clear=True,
        ):
            try:
                resp = await tb.refresh_account()
            finally:
                tb._trading_bot = original_bot

        # MUST NOT raise — endpoint returns success despite save failure
        assert resp["success"] is True
        assert bot.risk_params.starting_capital == 250000.0


# --------------------------------------------------------------------------
# risk_caps_service: explicit _id filter
# --------------------------------------------------------------------------

class TestRiskCapsServiceExplicitIdFilter:

    def test_uses_explicit_id_bot_state_filter(self):
        """v19.34.9 — risk_caps_service must filter by `_id="bot_state"`
        first (the canonical persisted id), falling back to ANY doc only
        if that fails. Guards against legacy `_id="main"` docs that
        accidentally win the natural-order race in `find_one({})`."""
        from services.risk_caps_service import _read_bot_risk_params

        captured_queries = []

        class _FakeColl:
            def __init__(self, return_for_canonical, return_for_fallback):
                self.return_for_canonical = return_for_canonical
                self.return_for_fallback = return_for_fallback

            def find_one(self, q, projection=None):
                captured_queries.append(q)
                if q == {"_id": "bot_state"}:
                    return self.return_for_canonical
                if q == {}:
                    return self.return_for_fallback
                return None

        canonical_doc = {"risk_params": {"starting_capital": 236487.27}}
        legacy_doc = {"risk_params": {"starting_capital": 100000.0}}

        # Case 1: canonical doc exists — it MUST win
        coll1 = _FakeColl(canonical_doc, legacy_doc)
        db1 = {"bot_state": coll1}
        result = _read_bot_risk_params(db1)
        assert result["starting_capital"] == 236487.27
        assert captured_queries[0] == {"_id": "bot_state"}

        # Case 2: canonical doc missing → fallback to any
        captured_queries.clear()
        coll2 = _FakeColl(None, legacy_doc)
        db2 = {"bot_state": coll2}
        result = _read_bot_risk_params(db2)
        assert result["starting_capital"] == 100000.0
        assert captured_queries == [{"_id": "bot_state"}, {}]

    def test_returns_empty_on_missing_doc(self):
        """No bot_state doc anywhere → returns {} cleanly."""
        from services.risk_caps_service import _read_bot_risk_params
        coll = MagicMock()
        coll.find_one = MagicMock(return_value=None)
        db = {"bot_state": coll}
        assert _read_bot_risk_params(db) == {}

    def test_returns_empty_on_db_none(self):
        from services.risk_caps_service import _read_bot_risk_params
        assert _read_bot_risk_params(None) == {}
