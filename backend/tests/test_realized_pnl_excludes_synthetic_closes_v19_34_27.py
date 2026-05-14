"""
test_realized_pnl_excludes_synthetic_closes_v19_34_27.py
=========================================================

Pins the v19.34.27 fix: `/api/sentcom/positions` MUST bifurcate
`total_realized_pnl` so the HUD's `R` chip matches IB's "Realized
P&L today" exactly, by EXCLUDING bot_trades whose `close_reason`
indicates a passive / synthetic / reconciler-stamped closure (OCA
external close, operator flatten in TWS, zombie cleanup, phantom
close, consolidator merge, stale-pending cleanup, etc.).

Operator-observed bug (2026-05-14 09:13 ET, pre-market):
  - App showed `R −$2,056.86` BEFORE the bell even rang.
  - IB showed `Realized PnL −$272.82` after the open.
  - Discrepancy = $1,784, matched yesterday's overnight passenger
    losses being booked as "today" because the reconciler
    discovered them at 09:22 ET pre-market and stamped each
    bot_trade's closed_at with NOW().

Contract after this fix:
  - `total_realized_pnl`         → today, EXCLUDES synthetic closures (matches IB)
  - `total_realized_pnl_session` → legacy behaviour (every closed_at >= midnight)
  - `realized_pnl_synthetic_*`   → diagnostic count / sum for the tooltip
  - `total_pnl_today`            → unrealized + total_realized_pnl (today, IB-matching)
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Reuse the FakeDB harness from the v19.31.7 file.
from tests.test_closed_today_realized_pnl_v19_31_7 import _FakeDB, _make_closed_trade  # noqa: E402


@pytest.mark.asyncio
async def test_synthetic_closes_excluded_from_today_realized_pnl():
    """The headline realized PnL must match IB by excluding reconciler-stamped closures."""
    from routers import sentcom as sentcom_router

    fake_db = _FakeDB()
    fake_db.bot_trades.docs = [
        # Real bot exit today (target hit) — COUNTS
        _make_closed_trade("real1", "NVDA", realized_pnl=200.0, close_reason="target_hit"),
        # Real bot exit today (stop loss) — COUNTS
        _make_closed_trade("real2", "AAPL", realized_pnl=-50.0, close_reason="stop_loss"),
        # OCA fired externally — IB realized this YESTERDAY. EXCLUDED.
        _make_closed_trade("syn1", "DKS", realized_pnl=-1500.0, close_reason="oca_closed_externally_v19_31"),
        # Operator flattened in TWS — same story. EXCLUDED.
        _make_closed_trade("syn2", "SHLD", realized_pnl=-300.0, close_reason="operator_external_flatten"),
        # Zombie cleanup — EXCLUDED.
        _make_closed_trade("syn3", "ICLN", realized_pnl=-100.0, close_reason="zombie_cleanup_v19_34_19"),
        # Phantom close prefix — EXCLUDED (matched by prefix rule).
        _make_closed_trade("syn4", "RJF", realized_pnl=-25.0, close_reason="phantom_close:reverse_detected"),
    ]
    fake_service = MagicMock()
    fake_service.get_our_positions = AsyncMock(return_value=[])

    with patch.object(sentcom_router, "_get_service", return_value=fake_service):
        with patch.object(sentcom_router, "logger"):
            with patch.dict(sys.modules, {"server": MagicMock(db=fake_db)}):
                res = await sentcom_router.get_positions()

    assert res["success"] is True
    # Today-only realized = NVDA +200 + AAPL -50 = +150 (matches IB)
    assert res["total_realized_pnl"] == 150.0, (
        f"Expected today's R to exclude synthetic closures, got {res['total_realized_pnl']}"
    )
    # Session bucket sums everything (today + reconciler-stamped passengers)
    # = 200 + -50 + -1500 + -300 + -100 + -25 = -1775
    assert res["total_realized_pnl_session"] == -1775.0
    # Diagnostic counters
    assert res["realized_pnl_synthetic_count"] == 4
    assert res["realized_pnl_synthetic_sum"] == -1925.0  # sum of the 4 synthetic rows
    # total_pnl_today excludes synthetic (no unrealized in this fixture)
    assert res["total_pnl_today"] == 150.0


@pytest.mark.asyncio
async def test_close_reason_missing_defaults_to_today_bucket():
    """Trades with no close_reason set are TRUSTED as real bot exits.
    
    This keeps the v19.31.7 tests passing (those don't set close_reason)
    AND it's the right semantic — close_reason gets stamped explicitly
    when something synthetic happens. A bare bot exit with no annotation
    is a real one."""
    from routers import sentcom as sentcom_router

    fake_db = _FakeDB()
    docs = [
        _make_closed_trade("t1", "X", realized_pnl=75.0),  # default close_reason="target_hit"
        _make_closed_trade("t2", "Y", realized_pnl=25.0),
    ]
    # Strip close_reason on one to simulate legacy behaviour
    docs[0].pop("close_reason", None)
    fake_db.bot_trades.docs = docs
    fake_service = MagicMock()
    fake_service.get_our_positions = AsyncMock(return_value=[])

    with patch.object(sentcom_router, "_get_service", return_value=fake_service):
        with patch.object(sentcom_router, "logger"):
            with patch.dict(sys.modules, {"server": MagicMock(db=fake_db)}):
                res = await sentcom_router.get_positions()

    assert res["total_realized_pnl"] == 100.0
    assert res["total_realized_pnl_session"] == 100.0
    assert res["realized_pnl_synthetic_count"] == 0


@pytest.mark.asyncio
async def test_all_synthetic_closures_returns_zero_today_realized():
    """If every closed trade is a reconciler artifact, today R = 0 (matches IB)."""
    from routers import sentcom as sentcom_router

    fake_db = _FakeDB()
    fake_db.bot_trades.docs = [
        _make_closed_trade("a", "A", realized_pnl=-500, close_reason="external_close_v19_34_15b"),
        _make_closed_trade("b", "B", realized_pnl=-300, close_reason="consolidated_v19_34_42"),
        _make_closed_trade("c", "C", realized_pnl=-200, close_reason="stale_pending_v19_34_78"),
    ]
    fake_service = MagicMock()
    fake_service.get_our_positions = AsyncMock(return_value=[])

    with patch.object(sentcom_router, "_get_service", return_value=fake_service):
        with patch.object(sentcom_router, "logger"):
            with patch.dict(sys.modules, {"server": MagicMock(db=fake_db)}):
                res = await sentcom_router.get_positions()

    assert res["total_realized_pnl"] == 0.0           # matches IB
    assert res["total_realized_pnl_session"] == -1000.0
    assert res["realized_pnl_synthetic_count"] == 3


@pytest.mark.asyncio
async def test_response_includes_all_v19_34_27_fields():
    """Defensive: every new field is present on a normal response."""
    from routers import sentcom as sentcom_router

    fake_db = _FakeDB()
    fake_db.bot_trades.docs = [_make_closed_trade("t1", "X", realized_pnl=100)]
    fake_service = MagicMock()
    fake_service.get_our_positions = AsyncMock(return_value=[])

    with patch.object(sentcom_router, "_get_service", return_value=fake_service):
        with patch.object(sentcom_router, "logger"):
            with patch.dict(sys.modules, {"server": MagicMock(db=fake_db)}):
                res = await sentcom_router.get_positions()

    required = {
        "total_realized_pnl", "total_realized_pnl_session",
        "realized_pnl_synthetic_count", "realized_pnl_synthetic_sum",
        "total_pnl_today", "total_unrealized_pnl",
    }
    missing = required - set(res.keys())
    assert not missing, f"Missing fields: {missing}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
