"""
test_orphan_reconciler_skips_excess_slice_v19_34_22.py — pins the v19.34.22
fix for the orphan-reconciler duplication bug discovered during the
v19.34.19 zombie-cleanup forensics.

Bug class: `reconcile_orphan_positions` builds its `bot_tracked` set from
`bot._open_trades` only. If a `reconciled_excess_v19_34_15b` /
`reconciled_excess_v19_34_19` / `reconciled_external` BotTrade is persisted
to the `bot_trades` collection but NOT yet hydrated into `_open_trades`
(restart race window, or out-of-band insert from another worker), the
orphan reconciler treats the symbol as "untracked" and spawns a duplicate
`reconciled_orphan` BotTrade against the same IB position — the bot then
believes it owns 2× the IB qty.

v19.34.22 hardens the check by:
  1. Loading the canonical "tracked" symbol set from `bot_trades` where
     `status==open` IN ADDITION to `_open_trades`.
  2. Adding a final per-symbol DB lookup right before spawning, so we
     never double-write against an existing open row regardless of when
     it landed in Mongo relative to this reconcile call.

Tests below cover:
  - `_open_trades`-tracked excess slice → `already_tracked` (regression pin).
  - DB-only excess slice (`entered_by=reconciled_excess_v19_34_15b`) →
    `db_already_tracked` (new behavior).
  - DB-only `reconciled_excess_v19_34_19` → `db_already_tracked`.
  - DB-only `reconciled_external` → `db_already_tracked`.
  - Symbol present neither in memory nor DB → spawn proceeds (no false skip).
"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _prep_direction_history(symbol: str, direction: str = "long",
                            stable_for_seconds: int = 60) -> None:
    """v19.29 — Pre-populate direction history so the stability gate passes."""
    from services.position_reconciler import _ib_direction_history
    sym = (symbol or "").upper()
    now = datetime.now(timezone.utc)
    _ib_direction_history[sym] = [
        (now - timedelta(seconds=stable_for_seconds), direction.lower()),
        (now - timedelta(seconds=max(1, stable_for_seconds // 2)), direction.lower()),
        (now - timedelta(seconds=1), direction.lower()),
    ]


def _mock_ib_position(symbol, qty, avg_cost, market_price=None):
    return {
        "symbol": symbol,
        "position": qty,
        "avgCost": avg_cost,
        "marketPrice": market_price or avg_cost,
    }


def _mock_bot(open_trades_map=None):
    from services.trading_bot_service import RiskParameters
    bot = MagicMock()
    bot.risk_params = RiskParameters()
    bot._open_trades = open_trades_map if open_trades_map is not None else {}
    bot._persist_trade = MagicMock()
    bot._db = MagicMock()
    return bot


def _mock_db_with_open_trades(open_trade_docs):
    """Build a MagicMock db where db['bot_trades'].find(query) returns the
    open_trade_docs that match `status==open`. Other collections return
    empty cursors / no-ops so misc reconciler-internal lookups don't break.
    """
    db = MagicMock()

    def _getitem(name):
        coll = MagicMock()
        if name == "bot_trades":
            def _find(query=None, projection=None, *_args, **_kwargs):
                # Return docs that satisfy a `status: open` filter.
                if query and query.get("status") == "open":
                    if "symbol" in query:
                        sym = query["symbol"]
                        return [d for d in open_trade_docs
                                if d.get("symbol") == sym]
                    return list(open_trade_docs)
                return []
            def _find_one(query=None, projection=None, *_args, **_kwargs):
                if query and query.get("status") == "open" and "symbol" in query:
                    for d in open_trade_docs:
                        if d.get("symbol") == query["symbol"]:
                            return d
                return None
            coll.find = MagicMock(side_effect=_find)
            coll.find_one = MagicMock(side_effect=_find_one)
        else:
            # sentcom_thoughts and any other collection — return empty cursor.
            coll.find = MagicMock(return_value=[])
            coll.find_one = MagicMock(return_value=None)
            coll.insert_one = MagicMock()
            coll.create_index = MagicMock()
        return coll

    db.__getitem__.side_effect = _getitem
    return db


# --------------------------------------------------------------------------
# 1. Regression pin — excess slice in _open_trades is recognized.
# --------------------------------------------------------------------------

def test_orphan_reconciler_skips_when_excess_slice_in_open_trades():
    """When a `reconciled_excess_v19_34_15b` BotTrade exists in
    `bot._open_trades` for the symbol, the orphan reconciler must skip
    with reason `already_tracked` and NOT spawn a duplicate.
    """
    from services.position_reconciler import PositionReconciler
    from services.trading_bot_service import (
        BotTrade, TradeDirection, TradeStatus,
    )

    # Existing v19.34.15b excess slice tracking 100 sh of UPS.
    existing = BotTrade(
        id="excess-15b-abc",
        symbol="UPS",
        direction=TradeDirection.LONG,
        status=TradeStatus.OPEN,
        setup_type="reconciled_excess_slice",
        timeframe="intraday",
        quality_score=50,
        quality_grade="R",
        entry_price=180.00,
        current_price=180.50,
        stop_price=178.20,
        target_prices=[182.30],
        shares=100,
        risk_amount=180.0,
        potential_reward=180.0,
        risk_reward_ratio=1.0,
    )
    existing.remaining_shares = 100
    existing.original_shares = 100
    existing.entered_by = "reconciled_excess_v19_34_15b"

    bot = _mock_bot(open_trades_map={"excess-15b-abc": existing})
    ib_positions = [_mock_ib_position("UPS", qty=100, avg_cost=180.00,
                                       market_price=180.50)]
    pr = PositionReconciler(db=_mock_db_with_open_trades([]))

    with patch("routers.ib._pushed_ib_data",
               {"positions": ib_positions, "quotes": {}}), \
         patch("routers.ib.is_pusher_connected", return_value=True):
        result = _run(pr.reconcile_orphan_positions(bot, symbols=["UPS"]))

    assert len(result["reconciled"]) == 0
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["symbol"] == "UPS"
    assert result["skipped"][0]["reason"] == "already_tracked"
    # No duplicate trade added.
    assert len(bot._open_trades) == 1


# --------------------------------------------------------------------------
# 2. NEW v19.34.22 — DB-only excess slice is also recognized.
# --------------------------------------------------------------------------

def test_orphan_reconciler_skips_when_excess_slice_only_in_db():
    """When a `reconciled_excess_v19_34_15b` row exists in the
    `bot_trades` collection (`status==open`) but is NOT yet in
    `bot._open_trades` (e.g. restart race or out-of-band insert), the
    orphan reconciler MUST detect the DB row and skip with reason
    `db_already_tracked`. Pre-v19.34.22 this case spawned a duplicate.
    """
    from services.position_reconciler import PositionReconciler

    db_open_trades = [{
        "id": "db-only-excess-1",
        "symbol": "UPS",
        "status": "open",
        "entered_by": "reconciled_excess_v19_34_15b",
        "remaining_shares": 100,
    }]

    bot = _mock_bot(open_trades_map={})  # nothing in memory.
    ib_positions = [_mock_ib_position("UPS", qty=100, avg_cost=180.00,
                                       market_price=180.50)]
    pr = PositionReconciler(db=_mock_db_with_open_trades(db_open_trades))

    with patch("routers.ib._pushed_ib_data",
               {"positions": ib_positions, "quotes": {}}), \
         patch("routers.ib.is_pusher_connected", return_value=True):
        result = _run(pr.reconcile_orphan_positions(bot, symbols=["UPS"]))

    assert len(result["reconciled"]) == 0
    assert len(result["skipped"]) == 1
    sk = result["skipped"][0]
    assert sk["symbol"] == "UPS"
    assert sk["reason"] in ("already_tracked", "db_already_tracked"), (
        f"Expected DB-aware skip, got reason={sk['reason']!r}"
    )
    # Critical: NOT spawned, so no entries in _open_trades.
    assert len(bot._open_trades) == 0


def test_orphan_reconciler_skips_when_v19_34_19_slice_only_in_db():
    """Same as above but for the v19.34.19 zombie-heal slice variant."""
    from services.position_reconciler import PositionReconciler

    db_open_trades = [{
        "id": "db-only-excess-19",
        "symbol": "FDX",
        "status": "open",
        "entered_by": "reconciled_excess_v19_34_19",
        "remaining_shares": 369,
    }]

    bot = _mock_bot(open_trades_map={})
    ib_positions = [_mock_ib_position("FDX", qty=369, avg_cost=360.00,
                                       market_price=361.00)]
    pr = PositionReconciler(db=_mock_db_with_open_trades(db_open_trades))

    with patch("routers.ib._pushed_ib_data",
               {"positions": ib_positions, "quotes": {}}), \
         patch("routers.ib.is_pusher_connected", return_value=True):
        result = _run(pr.reconcile_orphan_positions(bot, symbols=["FDX"]))

    assert len(result["reconciled"]) == 0
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["symbol"] == "FDX"
    assert result["skipped"][0]["reason"] in (
        "already_tracked", "db_already_tracked"
    )


def test_orphan_reconciler_skips_when_external_orphan_only_in_db():
    """Same hardening for `entered_by=reconciled_external` rows (the
    classic v19.24 orphan-reconcile origin)."""
    from services.position_reconciler import PositionReconciler

    db_open_trades = [{
        "id": "db-only-external-1",
        "symbol": "VALE",
        "status": "open",
        "entered_by": "reconciled_external",
        "remaining_shares": 500,
    }]

    bot = _mock_bot(open_trades_map={})
    ib_positions = [_mock_ib_position("VALE", qty=500, avg_cost=12.50,
                                       market_price=12.55)]
    pr = PositionReconciler(db=_mock_db_with_open_trades(db_open_trades))

    with patch("routers.ib._pushed_ib_data",
               {"positions": ib_positions, "quotes": {}}), \
         patch("routers.ib.is_pusher_connected", return_value=True):
        result = _run(pr.reconcile_orphan_positions(bot, symbols=["VALE"]))

    assert len(result["reconciled"]) == 0
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["symbol"] == "VALE"
    assert result["skipped"][0]["reason"] in (
        "already_tracked", "db_already_tracked"
    )


# --------------------------------------------------------------------------
# 3. Negative case — true orphan still gets reconciled.
# --------------------------------------------------------------------------

def test_orphan_reconciler_still_spawns_for_true_orphan():
    """Sanity guard: if the symbol exists in IB but has NO bot_trade
    anywhere (memory OR DB), the orphan reconciler MUST still spawn
    the `reconciled_orphan` trade. The DB-aware check must not over-skip.
    """
    from services.position_reconciler import PositionReconciler

    bot = _mock_bot(open_trades_map={})
    ib_positions = [_mock_ib_position("AAPL", qty=200, avg_cost=200.00,
                                       market_price=200.50)]
    ib_quotes = {"AAPL": {"last": 200.50}}
    _prep_direction_history("AAPL", "long")

    pr = PositionReconciler(db=_mock_db_with_open_trades([]))  # DB is empty.

    with patch("routers.ib._pushed_ib_data",
               {"positions": ib_positions, "quotes": ib_quotes}), \
         patch("routers.ib.is_pusher_connected", return_value=True), \
         patch("services.sentcom_service.emit_stream_event",
               new=AsyncMock(return_value=True)):
        result = _run(pr.reconcile_orphan_positions(bot, symbols=["AAPL"]))

    assert result["success"] is True
    assert len(result["reconciled"]) == 1
    assert result["reconciled"][0]["symbol"] == "AAPL"
    assert len(result["skipped"]) == 0
    # The new trade made it to _open_trades.
    assert len(bot._open_trades) == 1


# --------------------------------------------------------------------------
# 4. all_orphans=True path uses the same DB-aware tracked set.
# --------------------------------------------------------------------------

def test_orphan_reconciler_all_orphans_excludes_db_tracked():
    """When called with `all_orphans=True`, the candidate list (built
    from IB positions minus tracked symbols) MUST also exclude symbols
    that have an open `bot_trades` row in Mongo. Operator-caught failure
    mode: a v19.34.19 heal slice persisted to DB but `_open_trades`
    repopulation lagged → boot-reconcile spawned a duplicate orphan.
    """
    from services.position_reconciler import PositionReconciler

    db_open_trades = [{
        "id": "db-only-excess-19",
        "symbol": "FDX",
        "status": "open",
        "entered_by": "reconciled_excess_v19_34_19",
        "remaining_shares": 369,
    }]

    bot = _mock_bot(open_trades_map={})
    # Two IB positions: FDX (already tracked in DB) + AAPL (truly orphan).
    ib_positions = [
        _mock_ib_position("FDX", qty=369, avg_cost=360.00, market_price=361.00),
        _mock_ib_position("AAPL", qty=200, avg_cost=200.00, market_price=200.50),
    ]
    ib_quotes = {"AAPL": {"last": 200.50}, "FDX": {"last": 361.00}}
    _prep_direction_history("AAPL", "long")
    _prep_direction_history("FDX", "long")

    pr = PositionReconciler(db=_mock_db_with_open_trades(db_open_trades))

    with patch("routers.ib._pushed_ib_data",
               {"positions": ib_positions, "quotes": ib_quotes}), \
         patch("routers.ib.is_pusher_connected", return_value=True), \
         patch("services.sentcom_service.emit_stream_event",
               new=AsyncMock(return_value=True)):
        result = _run(pr.reconcile_orphan_positions(bot, all_orphans=True))

    # AAPL must be reconciled, FDX must be skipped (DB-tracked).
    reconciled_syms = {r["symbol"] for r in result["reconciled"]}
    assert "AAPL" in reconciled_syms, (
        "AAPL is a true orphan and must be reconciled"
    )
    assert "FDX" not in reconciled_syms, (
        "FDX has an open bot_trades row in DB and must NOT be re-spawned"
    )
