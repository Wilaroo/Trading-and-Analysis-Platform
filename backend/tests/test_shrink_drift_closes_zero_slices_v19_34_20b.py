"""
v19.34.20b — Verify `_shrink_drift_trades` closes fully-peeled slices.

Pre-fix bug: in `/app/backend/services/position_reconciler.py`, the
`_shrink_drift_trades` LIFO loop set `t.remaining_shares = 0` on a full
peel without flipping `t.status` to CLOSED, removing from
`bot._open_trades`, or stamping `closed_at`. That manufactured zombie
BotTrades (status=OPEN, rs=0) which the v19.34.19 detector then had to
catch every cycle. v19.34.20b prevents creation upstream.
"""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class _FakeBot:
    def __init__(self):
        self._open_trades = {}
        self._closed_trades = []
        self._save_trade_calls = 0
        self._stop_manager = SimpleNamespace(
            forget_trade=MagicMock(),
        )

    async def _save_trade(self, trade):
        self._save_trade_calls += 1


def _make_trade(tid: str, sym: str, rs: int, executed_at: str):
    """Mock a BotTrade with just the fields the shrinker reads."""
    from services.trading_bot_service import TradeStatus, TradeDirection
    return SimpleNamespace(
        id=tid,
        symbol=sym,
        direction=TradeDirection.LONG,
        status=TradeStatus.OPEN,
        remaining_shares=rs,
        shares=rs,
        notes="",
        executed_at=executed_at,
        entry_time=executed_at,
        created_at=executed_at,
        closed_at=None,
        close_reason=None,
        unrealized_pnl=0.0,
    )


@pytest.mark.asyncio
async def test_shrink_drift_closes_fully_peeled_slices_v19_34_20b():
    """Two trades, peel enough to fully zero the newest one. Newest must be
    CLOSED + popped from _open_trades; oldest survives untouched."""
    from services.position_reconciler import PositionReconciler
    from services.trading_bot_service import TradeStatus

    bot = _FakeBot()

    older = _make_trade("OLD-1", "FDX", 100, "2026-05-05T15:00:00+00:00")
    newer = _make_trade("NEW-1", "FDX", 50, "2026-05-05T16:00:00+00:00")
    bot._open_trades[older.id] = older
    bot._open_trades[newer.id] = newer

    reconciler = PositionReconciler(db=MagicMock())
    drift_record = {}

    # Peel: cur_total=150, target=100 → to_remove=50. LIFO peels newer
    # entirely (rs 50 → 0).
    await reconciler._shrink_drift_trades(
        bot, "FDX", [older, newer],
        new_total_abs=100, drift_record=drift_record,
    )

    # Newer slice fully peeled.
    assert newer.remaining_shares == 0
    assert newer.status == TradeStatus.CLOSED, (
        "v19.34.20b regression: full-peel must flip status to CLOSED."
    )
    assert newer.closed_at is not None
    assert newer.close_reason == "shrunk_to_zero_v19_34_20b"
    assert "NEW-1" not in bot._open_trades, (
        "v19.34.20b regression: full-peel must pop from _open_trades."
    )
    assert newer in bot._closed_trades
    bot._stop_manager.forget_trade.assert_called_with("NEW-1")

    # Older slice untouched (rs still 100, status still OPEN).
    assert older.remaining_shares == 100
    assert older.status == TradeStatus.OPEN
    assert "OLD-1" in bot._open_trades

    # Drift record carries the audit trail.
    assert drift_record.get("shrink_strategy") == "lifo"
    assert "NEW-1" in drift_record.get("fully_peeled_closed", [])


@pytest.mark.asyncio
async def test_shrink_drift_partial_peel_does_not_close_v19_34_20b():
    """Peel half a slice's shares — must NOT close it."""
    from services.position_reconciler import PositionReconciler
    from services.trading_bot_service import TradeStatus

    bot = _FakeBot()
    t = _make_trade("PARTIAL-1", "UPS", 200, "2026-05-05T16:00:00+00:00")
    bot._open_trades[t.id] = t

    reconciler = PositionReconciler(db=MagicMock())
    drift_record = {}
    # Peel 50 of 200.
    await reconciler._shrink_drift_trades(
        bot, "UPS", [t], new_total_abs=150, drift_record=drift_record,
    )

    assert t.remaining_shares == 150
    assert t.status == TradeStatus.OPEN, (
        "Partial peel must not close the trade — only full peels close."
    )
    assert t.closed_at is None
    assert "PARTIAL-1" in bot._open_trades
    assert drift_record.get("fully_peeled_closed", []) == []


@pytest.mark.asyncio
async def test_shrink_drift_full_cascade_closes_all_peeled_v19_34_20b():
    """Peel enough to wipe TWO slices fully — both must be closed."""
    from services.position_reconciler import PositionReconciler
    from services.trading_bot_service import TradeStatus

    bot = _FakeBot()
    t1 = _make_trade("T1", "FDX", 100, "2026-05-05T14:00:00+00:00")
    t2 = _make_trade("T2", "FDX", 50,  "2026-05-05T15:00:00+00:00")
    t3 = _make_trade("T3", "FDX", 30,  "2026-05-05T16:00:00+00:00")
    for t in (t1, t2, t3):
        bot._open_trades[t.id] = t

    reconciler = PositionReconciler(db=MagicMock())
    drift_record = {}
    # cur_total=180, target=100 → to_remove=80. LIFO order: T3(30) then T2(50).
    # Both should be fully peeled. T1 untouched.
    await reconciler._shrink_drift_trades(
        bot, "FDX", [t1, t2, t3],
        new_total_abs=100, drift_record=drift_record,
    )

    assert t3.remaining_shares == 0 and t3.status == TradeStatus.CLOSED
    assert t2.remaining_shares == 0 and t2.status == TradeStatus.CLOSED
    assert t1.remaining_shares == 100 and t1.status == TradeStatus.OPEN
    assert "T3" not in bot._open_trades
    assert "T2" not in bot._open_trades
    assert "T1" in bot._open_trades
    closed_ids = drift_record.get("fully_peeled_closed", [])
    assert "T2" in closed_ids and "T3" in closed_ids and "T1" not in closed_ids


def test_source_contains_v19_34_20b_close_block():
    """Static guard against accidental revert."""
    import os
    src_path = os.path.join(
        os.path.dirname(__file__), "..", "services", "position_reconciler.py"
    )
    src_path = os.path.abspath(src_path)
    with open(src_path, "r") as f:
        src = f.read()
    assert "v19.34.20b" in src, "v19.34.20b marker missing — patch reverted?"
    assert "shrunk_to_zero_v19_34_20b" in src, (
        "v19.34.20b close_reason missing — full-peel close path removed?"
    )
    assert "fully_peeled" in src, (
        "v19.34.20b fully_peeled tracking missing — patch reverted?"
    )
