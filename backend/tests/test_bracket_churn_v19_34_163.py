"""v19.34.163 — Bracket churn fix regression suite.

Three guards added to `_naked_position_sweep` after the 2026-05-26 audit
revealed 928 self-cascading reissue events in 7 days (97% triggered by
the previous sweep's own output):

  Guard 1 (PATCH F) — Tier-mismatch blind-guard
      When BOT_ORDER_PATH=direct and the open-orders resolver falls
      through to `pusher_orders_snapshot` (because ib_direct disconnected),
      skip the entire sweep with reason="tier3_blind_to_ib_direct_orders".
      Pusher snapshot is structurally blind to ib_direct's orders (clientId
      visibility gap) so we cannot trust naked-detection from it.

  Guard 2 (PATCH G) — Recent-reissue cooldown
      After a successful reissue, suppress re-detection of the same
      trade for NAKED_REISSUE_COOLDOWN_S seconds (default 90). Covers
      IB's async EWrapper.openOrder callback latency between place
      and snapshot visibility.

  Guard 3 (PATCH H) — Cumulative telemetry fields
      `target_ever_attached`, `bracket_attach_count`, `last_bracket_attach_at`
      are monotonic and updated on every successful reissue. Drives
      v90 P0 audit + future `bracket_completion_telemetry` alert job.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── shared test helpers (mirror test_naked_position_sweep_v19_34_127.py) ───
def _make_trade(*, tid, symbol, shares, stop_order_id, **extra):
    t = MagicMock()
    t.id = tid
    t.symbol = symbol
    t.remaining_shares = shares
    t.stop_order_id = stop_order_id
    t.target_order_id = None
    t.target_order_ids = []
    t.oca_group = None
    # Defaults for new v163 fields — MagicMock auto-creates attrs but
    # we want explicit primitives so getattr(...) defaults work right.
    t.target_ever_attached = extra.get("target_ever_attached", False)
    t.bracket_attach_count = extra.get("bracket_attach_count", 0)
    t.last_bracket_attach_at = extra.get("last_bracket_attach_at", None)
    return t


def _make_bot(*, executor, open_trades):
    from services.trading_bot_service import TradingBotService
    bot = TradingBotService.__new__(TradingBotService)
    bot._trade_executor = executor
    bot._open_trades = open_trades
    bot._db = None
    bot._save_trade = MagicMock(return_value=None)
    return bot


def _make_executor(*, mode="LIVE", oca_result=None):
    executor = MagicMock()
    executor.mode = mode
    if oca_result is not None:
        executor.attach_oca_stop_target = AsyncMock(return_value=oca_result)
    return executor


def _patch_fetch(ib_orders, source_tier="pusher_orders_snapshot"):
    return patch(
        "services.orphan_gtc_reconciler._fetch_ib_open_orders",
        new_callable=AsyncMock,
        return_value=(ib_orders, {"tier": source_tier, "ok": True}),
    )


# ════════════════════════════════════════════════════════════════════
# GUARD 1 — Tier-mismatch blind-guard (PATCH F)
# ════════════════════════════════════════════════════════════════════

class TestGuard1TierMismatch:
    """When BOT_ORDER_PATH=direct AND resolver returns tier 3, abort sweep."""

    @pytest.mark.asyncio
    async def test_skips_when_direct_path_lands_on_tier3(self, monkeypatch):
        monkeypatch.setenv("BOT_ORDER_PATH", "direct")
        # Naked trade present — but should NEVER be reissued because
        # we can't trust the tier-3 view.
        trade = _make_trade(tid="t1", symbol="UAL", shares=210,
                            stop_order_id="8491")
        executor = _make_executor(oca_result={
            "success": True, "stop_order_id": "9999",
            "target_order_id": "TGT-9999", "oca_group": "OCA-9999",
        })
        bot = _make_bot(executor=executor, open_trades={"t1": trade})

        with _patch_fetch([], source_tier="pusher_orders_snapshot"):
            result = await bot._naked_position_sweep()

        assert result["skipped_reason"] == "tier3_blind_to_ib_direct_orders"
        assert result["reissued"] == 0
        assert result["naked_found"] == 0
        # attach_oca_stop_target must NOT have been called
        executor.attach_oca_stop_target.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_skip_when_direct_path_lands_on_tier1(self, monkeypatch):
        """ib_direct healthy → tier 1 → sweep proceeds normally."""
        monkeypatch.setenv("BOT_ORDER_PATH", "direct")
        trade = _make_trade(tid="t1", symbol="UAL", shares=210,
                            stop_order_id="8491")
        executor = _make_executor(oca_result={
            "success": True, "stop_order_id": "9999",
            "target_order_id": "TGT-9999", "oca_group": "OCA-9999",
        })
        bot = _make_bot(executor=executor, open_trades={"t1": trade})

        with _patch_fetch([], source_tier="ib_direct"), patch(
            "services.bracket_reissue_service._persist_lifecycle_event",
            new_callable=AsyncMock,
        ):
            result = await bot._naked_position_sweep()

        # Tier 1 view: empty live_order_ids → 8491 is genuinely missing
        # → naked detection proceeds and reissue fires.
        assert result.get("skipped_reason") is None
        assert result["naked_found"] == 1
        assert result["reissued"] == 1

    @pytest.mark.asyncio
    async def test_does_not_skip_when_pusher_path_lands_on_tier3(self, monkeypatch):
        """BOT_ORDER_PATH=pusher → tier 3 is the AUTHORITATIVE source,
        not a fallback. Sweep must proceed."""
        monkeypatch.setenv("BOT_ORDER_PATH", "pusher")
        trade = _make_trade(tid="t1", symbol="UAL", shares=210,
                            stop_order_id="8491")
        executor = _make_executor(oca_result={
            "success": True, "stop_order_id": "9999",
            "target_order_id": "TGT-9999", "oca_group": "OCA-9999",
        })
        bot = _make_bot(executor=executor, open_trades={"t1": trade})

        with _patch_fetch([], source_tier="pusher_orders_snapshot"), patch(
            "services.bracket_reissue_service._persist_lifecycle_event",
            new_callable=AsyncMock,
        ):
            result = await bot._naked_position_sweep()

        assert result.get("skipped_reason") is None
        assert result["reissued"] == 1

    @pytest.mark.asyncio
    async def test_does_not_skip_when_env_unset_defaults_to_pusher(self, monkeypatch):
        """Default BOT_ORDER_PATH (unset) is 'pusher' — sweep proceeds."""
        monkeypatch.delenv("BOT_ORDER_PATH", raising=False)
        trade = _make_trade(tid="t1", symbol="UAL", shares=210,
                            stop_order_id="8491")
        executor = _make_executor(oca_result={
            "success": True, "stop_order_id": "9999",
            "target_order_id": "TGT-9999", "oca_group": "OCA-9999",
        })
        bot = _make_bot(executor=executor, open_trades={"t1": trade})

        with _patch_fetch([], source_tier="pusher_orders_snapshot"), patch(
            "services.bracket_reissue_service._persist_lifecycle_event",
            new_callable=AsyncMock,
        ):
            result = await bot._naked_position_sweep()

        assert result.get("skipped_reason") is None
        assert result["reissued"] == 1


# ════════════════════════════════════════════════════════════════════
# GUARD 2 — Recent-reissue cooldown (PATCH G)
# ════════════════════════════════════════════════════════════════════

class TestGuard2RecentReissueCooldown:
    """Suppress re-detection within NAKED_REISSUE_COOLDOWN_S of last attach."""

    @pytest.mark.asyncio
    async def test_skips_when_attach_was_30s_ago(self, monkeypatch):
        monkeypatch.setenv("BOT_ORDER_PATH", "pusher")
        monkeypatch.setenv("NAKED_REISSUE_COOLDOWN_S", "90")
        # last_bracket_attach_at = 30s ago → still within 90s cooldown
        recent_ts = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        trade = _make_trade(tid="t1", symbol="UAL", shares=210,
                            stop_order_id="8491",
                            last_bracket_attach_at=recent_ts)
        executor = _make_executor(oca_result={
            "success": True, "stop_order_id": "9999",
            "target_order_id": "TGT-9999", "oca_group": "OCA-9999",
        })
        bot = _make_bot(executor=executor, open_trades={"t1": trade})

        with _patch_fetch([], source_tier="pusher_orders_snapshot"):
            result = await bot._naked_position_sweep()

        # Cooldown should suppress detection — no naked found, no reissue
        assert result["naked_found"] == 0
        assert result["reissued"] == 0
        assert result.get("cooldown_skips") == 1
        executor.attach_oca_stop_target.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_skip_when_attach_was_120s_ago(self, monkeypatch):
        monkeypatch.setenv("BOT_ORDER_PATH", "pusher")
        monkeypatch.setenv("NAKED_REISSUE_COOLDOWN_S", "90")
        # 120s > 90s cooldown → sweep proceeds
        stale_ts = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        trade = _make_trade(tid="t1", symbol="UAL", shares=210,
                            stop_order_id="8491",
                            last_bracket_attach_at=stale_ts)
        executor = _make_executor(oca_result={
            "success": True, "stop_order_id": "9999",
            "target_order_id": "TGT-9999", "oca_group": "OCA-9999",
        })
        bot = _make_bot(executor=executor, open_trades={"t1": trade})

        with _patch_fetch([], source_tier="pusher_orders_snapshot"), patch(
            "services.bracket_reissue_service._persist_lifecycle_event",
            new_callable=AsyncMock,
        ):
            result = await bot._naked_position_sweep()

        assert result["naked_found"] == 1
        assert result["reissued"] == 1

    @pytest.mark.asyncio
    async def test_does_not_skip_when_no_prior_attach(self, monkeypatch):
        """Brand-new trade with no last_bracket_attach_at → no cooldown."""
        monkeypatch.setenv("BOT_ORDER_PATH", "pusher")
        trade = _make_trade(tid="t1", symbol="UAL", shares=210,
                            stop_order_id="8491",
                            last_bracket_attach_at=None)
        executor = _make_executor(oca_result={
            "success": True, "stop_order_id": "9999",
            "target_order_id": "TGT-9999", "oca_group": "OCA-9999",
        })
        bot = _make_bot(executor=executor, open_trades={"t1": trade})

        with _patch_fetch([], source_tier="pusher_orders_snapshot"), patch(
            "services.bracket_reissue_service._persist_lifecycle_event",
            new_callable=AsyncMock,
        ):
            result = await bot._naked_position_sweep()

        assert result["reissued"] == 1
        assert result.get("cooldown_skips", 0) == 0

    @pytest.mark.asyncio
    async def test_cooldown_failure_falls_through_to_detection(self, monkeypatch):
        """If the timestamp parse raises, we MUST NOT silently suppress."""
        monkeypatch.setenv("BOT_ORDER_PATH", "pusher")
        # Garbage timestamp → fromisoformat raises → fallthrough
        trade = _make_trade(tid="t1", symbol="UAL", shares=210,
                            stop_order_id="8491",
                            last_bracket_attach_at="not-a-date")
        executor = _make_executor(oca_result={
            "success": True, "stop_order_id": "9999",
            "target_order_id": "TGT-9999", "oca_group": "OCA-9999",
        })
        bot = _make_bot(executor=executor, open_trades={"t1": trade})

        with _patch_fetch([], source_tier="pusher_orders_snapshot"), patch(
            "services.bracket_reissue_service._persist_lifecycle_event",
            new_callable=AsyncMock,
        ):
            result = await bot._naked_position_sweep()

        # Cooldown raised → fall through → naked detected and reissued
        assert result["naked_found"] == 1
        assert result["reissued"] == 1
        assert result.get("cooldown_skips", 0) == 0


# ════════════════════════════════════════════════════════════════════
# GUARD 3 — Cumulative telemetry fields (PATCH H)
# ════════════════════════════════════════════════════════════════════

class TestGuard3CumulativeFields:
    """Successful reissue must increment counts + stamp ts, never reset."""

    @pytest.mark.asyncio
    async def test_first_successful_reissue_initializes_fields(self, monkeypatch):
        monkeypatch.setenv("BOT_ORDER_PATH", "pusher")
        # First-time trade — defaults: count=0, ever=False, ts=None
        trade = _make_trade(tid="t1", symbol="UAL", shares=210,
                            stop_order_id="8491",
                            bracket_attach_count=0,
                            target_ever_attached=False,
                            last_bracket_attach_at=None)
        executor = _make_executor(oca_result={
            "success": True, "stop_order_id": "9999",
            "target_order_id": "TGT-9999", "oca_group": "OCA-9999",
        })
        bot = _make_bot(executor=executor, open_trades={"t1": trade})

        with _patch_fetch([], source_tier="pusher_orders_snapshot"), patch(
            "services.bracket_reissue_service._persist_lifecycle_event",
            new_callable=AsyncMock,
        ):
            result = await bot._naked_position_sweep()

        assert result["reissued"] == 1
        assert trade.bracket_attach_count == 1
        assert trade.target_ever_attached is True
        assert trade.last_bracket_attach_at is not None
        # Verify ISO format parses correctly
        parsed = datetime.fromisoformat(
            str(trade.last_bracket_attach_at).replace("Z", "+00:00")
        )
        assert (datetime.now(timezone.utc) - parsed).total_seconds() < 5

    @pytest.mark.asyncio
    async def test_subsequent_reissue_increments_count_preserves_ever(self, monkeypatch):
        """target_ever_attached must NEVER flip back from True to False
        even if a later reissue is stop-only (no target_order_id)."""
        monkeypatch.setenv("BOT_ORDER_PATH", "pusher")
        # Trade already has prior history: count=5, ever=True, attached 2h ago
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        trade = _make_trade(tid="t1", symbol="UAL", shares=210,
                            stop_order_id="8491",
                            bracket_attach_count=5,
                            target_ever_attached=True,
                            last_bracket_attach_at=old_ts)
        # This reissue is STOP-ONLY (target_order_id=None) — partial success
        executor = _make_executor(oca_result={
            "success": True, "stop_order_id": "9999",
            "target_order_id": None,  # <-- no target this time
            "oca_group": "OCA-9999", "partial": True,
        })
        bot = _make_bot(executor=executor, open_trades={"t1": trade})

        with _patch_fetch([], source_tier="pusher_orders_snapshot"), patch(
            "services.bracket_reissue_service._persist_lifecycle_event",
            new_callable=AsyncMock,
        ):
            result = await bot._naked_position_sweep()

        assert result["reissued"] == 1
        assert trade.bracket_attach_count == 6  # incremented
        assert trade.target_ever_attached is True  # PRESERVED despite no tgt
        assert trade.last_bracket_attach_at != old_ts  # updated

    @pytest.mark.asyncio
    async def test_failed_reissue_does_not_touch_telemetry(self, monkeypatch):
        """Failed attach must NOT increment count or flip ever."""
        monkeypatch.setenv("BOT_ORDER_PATH", "pusher")
        trade = _make_trade(tid="t1", symbol="UAL", shares=210,
                            stop_order_id="8491",
                            bracket_attach_count=3,
                            target_ever_attached=False,
                            last_bracket_attach_at=None)
        executor = _make_executor(oca_result={
            "success": False, "error": "bracket_attach_blocked:reg_t_cutoff",
            "stop_order_id": None, "target_order_id": None,
        })
        bot = _make_bot(executor=executor, open_trades={"t1": trade})

        with _patch_fetch([], source_tier="pusher_orders_snapshot"), patch(
            "services.bracket_reissue_service._persist_lifecycle_event",
            new_callable=AsyncMock,
        ):
            result = await bot._naked_position_sweep()

        assert result["reissued"] == 0
        assert result["reissue_failed"] == 1
        # Telemetry untouched on failure
        assert trade.bracket_attach_count == 3
        assert trade.target_ever_attached is False
        assert trade.last_bracket_attach_at is None

    @pytest.mark.asyncio
    async def test_stop_only_first_attach_does_not_flip_target_ever_attached(self, monkeypatch):
        """If FIRST-EVER attach is stop-only, target_ever_attached stays False."""
        monkeypatch.setenv("BOT_ORDER_PATH", "pusher")
        trade = _make_trade(tid="t1", symbol="UAL", shares=210,
                            stop_order_id="8491",
                            bracket_attach_count=0,
                            target_ever_attached=False,
                            last_bracket_attach_at=None)
        executor = _make_executor(oca_result={
            "success": True, "stop_order_id": "9999",
            "target_order_id": None,  # stop-only
            "oca_group": "OCA-9999", "partial": True,
        })
        bot = _make_bot(executor=executor, open_trades={"t1": trade})

        with _patch_fetch([], source_tier="pusher_orders_snapshot"), patch(
            "services.bracket_reissue_service._persist_lifecycle_event",
            new_callable=AsyncMock,
        ):
            result = await bot._naked_position_sweep()

        assert result["reissued"] == 1
        assert trade.bracket_attach_count == 1
        # Never had a target attached → stays False
        assert trade.target_ever_attached is False


# ════════════════════════════════════════════════════════════════════
# DATACLASS — Field defaults sanity (preserves existing trade creation)
# ════════════════════════════════════════════════════════════════════

class TestBotTradeFieldDefaults:
    """Brand-new BotTrade instances must default the three v163 fields
    so legacy code paths that construct trades without setting them
    continue to work."""

    def test_new_bot_trade_has_v163_default_fields(self):
        from services.trading_bot_service import (
            BotTrade, TradeDirection, TradeStatus,
        )
        t = BotTrade(
            id="test-id", symbol="UAL",
            direction=TradeDirection.LONG, status=TradeStatus.PENDING,
            setup_type="rubber_band", timeframe="1m",
            quality_score=85, quality_grade="A",
            entry_price=100.0, current_price=100.0, stop_price=98.0,
            target_prices=[103.0],
            shares=100, risk_amount=200.0,
            potential_reward=300.0, risk_reward_ratio=1.5,
        )
        assert t.target_ever_attached is False
        assert t.bracket_attach_count == 0
        assert t.last_bracket_attach_at is None

    def test_to_dict_includes_v163_fields(self):
        from services.trading_bot_service import (
            BotTrade, TradeDirection, TradeStatus,
        )
        t = BotTrade(
            id="test-id", symbol="UAL",
            direction=TradeDirection.LONG, status=TradeStatus.PENDING,
            setup_type="rubber_band", timeframe="1m",
            quality_score=85, quality_grade="A",
            entry_price=100.0, current_price=100.0, stop_price=98.0,
            target_prices=[103.0],
            shares=100, risk_amount=200.0,
            potential_reward=300.0, risk_reward_ratio=1.5,
        )
        t.target_ever_attached = True
        t.bracket_attach_count = 7
        t.last_bracket_attach_at = "2026-05-26T20:30:00+00:00"
        d = t.to_dict()
        # asdict() picks up dataclass fields automatically
        assert d["target_ever_attached"] is True
        assert d["bracket_attach_count"] == 7
        assert d["last_bracket_attach_at"] == "2026-05-26T20:30:00+00:00"
