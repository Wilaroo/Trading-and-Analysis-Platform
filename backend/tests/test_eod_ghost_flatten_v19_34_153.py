"""Offline unit tests for v19.34.153 EOD ghost-flatten logic.

These tests stub IB + ib_direct_service so they run on any machine
(no DGX / IB Gateway required). They verify:

  1. Ghosts at IB that are NOT in `bot._open_trades` AND NOT in the
     recent-swing set get flattened via `place_emergency_mkt_close`.
  2. IB symbols that ARE tracked in `bot._open_trades` are left alone.
  3. IB symbols matching a recent-swing row (close_at_eod=False,
     executed_at within 48h) are SKIPPED (not flattened).
  4. Per-symbol-per-day fire cap: a SUCCESSFUL flatten does NOT re-fire
     on the next tick; an UNSUCCESSFUL flatten retries up to 3 times.
  5. A correctly-signed action is computed (long ghost -> SELL,
     short ghost -> BUY).
  6. With no IB positions, function returns ghosts_found=0 and does not
     touch the order service.

Run:
    cd /app/backend && PYTHONPATH=. python3 -m pytest tests/test_eod_ghost_flatten_v19_34_153.py -v
"""
from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Path setup so `services.*` imports resolve from /app/backend. ────
import os
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)


# ── Stub routers.ib._pushed_ib_data for the snapshot reader. ─────────
def _install_ib_router_stub(positions):
    mod = types.ModuleType("routers.ib")
    mod._pushed_ib_data = {"positions": list(positions)}
    # Ensure parent package exists.
    sys.modules.setdefault("routers", types.ModuleType("routers"))
    sys.modules["routers.ib"] = mod


# ── Stub services.ib_direct_service.get_ib_direct_service. ───────────
def _install_ibdirect_stub(emergency_results):
    """`emergency_results` is a list of dicts the stub returns in order
    of calls. Last entry is reused if the test fires more calls."""
    calls = []

    class _StubSvc:
        def is_available(self):
            return True
        def is_connected(self):
            return True
        async def place_emergency_mkt_close(self, *, symbol, qty, action, **kw):
            calls.append({"symbol": symbol, "qty": qty, "action": action})
            idx = min(len(calls) - 1, len(emergency_results) - 1)
            return emergency_results[idx]

    # Force-import the REAL module first so its IBDirectService class
    # remains importable for other test files in the same pytest run
    # (e.g. test_place_oca_stop_target_polling_v154.py imports
    # `IBDirectService` directly). Pre-fix this fixture created a bare
    # ModuleType stub that shadowed the real module for the rest of the
    # session.
    try:
        import services.ib_direct_service as _real_ids  # noqa: F401
        mod = sys.modules["services.ib_direct_service"]
    except Exception:
        mod = sys.modules.get("services.ib_direct_service")
        if mod is None:
            mod = types.ModuleType("services.ib_direct_service")
            sys.modules["services.ib_direct_service"] = mod
    stub_svc = _StubSvc()
    mod.get_ib_direct_service = lambda: stub_svc
    return calls


def _make_bot(open_trades, *, db_swing_rows=None):
    """Build a minimal bot stand-in. `open_trades` is {trade_id: symbol}.

    We deliberately use `SimpleNamespace` instead of `MagicMock` for the
    bot object: MagicMock auto-generates attributes (so `hasattr(bot, X)`
    is ALWAYS True), which masks the helper's first-call initializers
    like `if not hasattr(bot, "_ghost_flatten_fired"): bot._ghost_flatten_fired = {}`.
    SimpleNamespace mirrors a real `TradingBotService`'s attribute model.
    """
    from types import SimpleNamespace
    class _Trade:
        def __init__(self, sym):
            self.symbol = sym
    bot_trades = MagicMock()
    bot_trades.find = MagicMock(return_value=db_swing_rows or [])
    bot_events = MagicMock()
    bot_events.insert_one = MagicMock(return_value=None)
    db = SimpleNamespace(bot_trades=bot_trades, bot_events=bot_events)
    return SimpleNamespace(
        _open_trades={tid: _Trade(sym) for tid, sym in (open_trades or {}).items()},
        _broadcast_event=AsyncMock(),
        _db=db,
    )


@pytest.mark.asyncio
async def test_no_ib_positions_returns_zero():
    from services.position_manager import PositionManager
    _install_ib_router_stub([])
    bot = _make_bot({})
    pm = PositionManager()
    result = await pm._flatten_ghost_positions(bot, reason="unit_test")
    assert result["ghosts_found"] == 0
    assert result["flattened"] == []


@pytest.mark.asyncio
async def test_tracked_symbols_are_left_alone():
    from services.position_manager import PositionManager
    _install_ib_router_stub([
        {"symbol": "AAPL", "position": 100},
        {"symbol": "MSFT", "position": -50},
    ])
    calls = _install_ibdirect_stub([{"success": True, "status": "filled", "order_id": 1}])
    bot = _make_bot({"t1": "AAPL", "t2": "MSFT"})
    pm = PositionManager()
    result = await pm._flatten_ghost_positions(bot, reason="unit_test")
    assert result["ghosts_found"] == 0
    assert calls == []  # No emergency closes fired.


@pytest.mark.asyncio
async def test_long_ghost_fires_sell():
    from services.position_manager import PositionManager
    _install_ib_router_stub([{"symbol": "TSLA", "position": 250}])
    calls = _install_ibdirect_stub([{"success": True, "status": "filled", "order_id": 42}])
    bot = _make_bot({})  # No tracked trades.
    pm = PositionManager()
    result = await pm._flatten_ghost_positions(bot, reason="unit_test")
    assert result["ghosts_found"] == 1
    assert len(calls) == 1
    assert calls[0] == {"symbol": "TSLA", "qty": 250, "action": "SELL"}
    assert len(result["flattened"]) == 1


@pytest.mark.asyncio
async def test_short_ghost_fires_buy():
    from services.position_manager import PositionManager
    _install_ib_router_stub([{"symbol": "NVDA", "position": -73}])
    calls = _install_ibdirect_stub([{"success": True, "status": "filled", "order_id": 7}])
    bot = _make_bot({})
    pm = PositionManager()
    result = await pm._flatten_ghost_positions(bot, reason="unit_test")
    assert result["ghosts_found"] == 1
    assert calls[0] == {"symbol": "NVDA", "qty": 73, "action": "BUY"}


@pytest.mark.asyncio
async def test_recent_swing_is_skipped():
    from services.position_manager import PositionManager
    now_iso = datetime.now(timezone.utc).isoformat()
    _install_ib_router_stub([
        {"symbol": "SWNG", "position": 500},
        {"symbol": "GHST", "position": 100},
    ])
    calls = _install_ibdirect_stub([{"success": True, "status": "filled", "order_id": 1}])
    bot = _make_bot(
        {},
        db_swing_rows=[{"symbol": "SWNG", "close_at_eod": False, "executed_at": now_iso}],
    )
    pm = PositionManager()
    result = await pm._flatten_ghost_positions(bot, reason="unit_test")
    # SWNG → skipped; GHST → flattened.
    assert result["ghosts_found"] == 1
    assert calls == [{"symbol": "GHST", "qty": 100, "action": "SELL"}]
    skipped_syms = {s["symbol"] for s in result["skipped"]}
    assert "SWNG" in skipped_syms


@pytest.mark.asyncio
async def test_successful_fire_does_not_repeat():
    from services.position_manager import PositionManager
    _install_ib_router_stub([{"symbol": "GHST", "position": 100}])
    calls = _install_ibdirect_stub([{"success": True, "status": "filled", "order_id": 1}])
    bot = _make_bot({})
    pm = PositionManager()
    r1 = await pm._flatten_ghost_positions(bot, reason="tick1")
    r2 = await pm._flatten_ghost_positions(bot, reason="tick2")
    # Only ONE actual emergency MKT submitted across two ticks because
    # the first one filled.
    assert len(calls) == 1
    assert r1["ghosts_found"] == 1 and len(r1["flattened"]) == 1
    # Second call still detects the ghost but skips re-fire.
    assert r2["ghosts_found"] == 1
    assert r2["flattened"] == []


@pytest.mark.asyncio
async def test_failed_fire_retries_up_to_three_times():
    from services.position_manager import PositionManager
    _install_ib_router_stub([{"symbol": "FAIL", "position": 100}])
    # Always returns failure → expect 3 retries then permanent skip.
    calls = _install_ibdirect_stub([{"success": False, "error": "ib_busy"}])
    bot = _make_bot({})
    pm = PositionManager()
    for _ in range(5):
        await pm._flatten_ghost_positions(bot, reason="retry_test")
    assert len(calls) == 3, f"expected 3 retries, got {len(calls)}"
