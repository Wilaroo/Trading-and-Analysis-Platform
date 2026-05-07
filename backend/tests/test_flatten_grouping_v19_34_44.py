"""
v19.34.44 — Flatten-All grouping + zombie-cancel regression tests.
====================================================================

Pins the two fixes shipped after operator-caught BMNR
"FLATTEN FAILED 19/19 close returned False" (IB Error 201).

1. flatten-all groups by (symbol, direction); 19 fragments for one IB
   position fire ONE close MKT, not 19.
2. Pre-cancel step calls ib_direct.cancel_all_open_orders_for_symbol
   for each (symbol, side) BEFORE submitting any close MKT.
"""
from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, "/app/backend")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _ns(tid, sym="BMNR", direction="long", shares=100, t="2026-05-08T10:00:00+00:00"):
    return SimpleNamespace(
        id=tid, symbol=sym,
        direction=SimpleNamespace(value=direction),
        remaining_shares=shares,
        shares=shares,
        entry_time=t, executed_at=t, created_at=t,
        entered_by="reconciled_excess_v19_34_15b",
        setup_type="reconciled_excess_slice",
        fill_price=22.45, entry_price=22.45,
        stop_price=22.23,
        target_prices=[22.67],
        notes="",
        unrealized_pnl=0,
        realized_pnl=0,
        stop_order_id=None,
        target_order_id=None,
        oca_group=None,
        risk_amount=0,
    )


def _fake_db_chain():
    fake_db = MagicMock()
    fake_db.order_queue.update_many = AsyncMock(
        return_value=SimpleNamespace(modified_count=0)
    )
    fake_client = MagicMock()
    fake_client.__getitem__.return_value = fake_db
    return fake_client


def test_flatten_groups_19_bmnr_fragments_into_one_close_call():
    """The headline regression: 19 BMNR fragments must result in EXACTLY
    ONE close_trade() call with the canonical's id, not 19 separate calls."""
    from routers.safety_router import flatten_all
    import services.trading_bot_service as tbs_mod

    # Stub TradeStatus so the sibling-close path in _close_one_group works.
    tbs_mod.TradeStatus = SimpleNamespace(
        OPEN=SimpleNamespace(value="open"),
        CLOSED=SimpleNamespace(value="closed"),
    )

    # 19 BMNR fragments. First is non-reconciled (canonical), rest are
    # reconciled_excess slices.
    canonical = _ns("canon", shares=1352, t="2026-05-08T09:00:00+00:00")
    canonical.entered_by = "squeeze"
    canonical.setup_type = "squeeze"
    fragments = [_ns(f"frag{i}", shares=100, t=f"2026-05-08T10:0{i}:00+00:00")
                 for i in range(18)]
    all_trades = [canonical, *fragments]

    bot = MagicMock()
    bot._open_trades = {t.id: t for t in all_trades}
    bot.close_trade = AsyncMock(return_value=True)
    bot._save_trade = MagicMock(return_value=None)
    bot._closed_trades = []

    with patch("services.trading_bot_service.get_trading_bot_service",
               return_value=bot, create=True), \
         patch("motor.motor_asyncio.AsyncIOMotorClient",
               return_value=_fake_db_chain(), create=True), \
         patch.dict("os.environ", {"MONGO_URL": "mongodb://x", "DB_NAME": "test"}):
        result = _run(flatten_all(confirm="FLATTEN"))

    # close_trade should fire EXACTLY ONCE — for the canonical.
    assert bot.close_trade.await_count == 1, (
        f"expected 1 close_trade call, got {bot.close_trade.await_count} — "
        "grouping by (symbol, direction) is broken"
    )
    called_id = bot.close_trade.await_args_list[0].args[0]
    assert called_id == "canon"

    # Canonical was grown to total = 1352 + 18*100 = 3152 sh before the close.
    assert canonical.remaining_shares == 1352 + 18 * 100

    # All 19 trades reported as succeeded (1 canonical + 18 absorbed siblings).
    s = result["summary"]
    assert s["positions_requested_close"] == 19
    assert s["positions_succeeded"] == 19
    assert s["positions_failed"] == 0
    # 18 siblings must have been popped from in-memory.
    assert "canon" in bot._open_trades
    for f in fragments:
        assert f.id not in bot._open_trades


def test_flatten_calls_zombie_cancel_for_each_symbol_when_ib_direct_connected():
    """The 15-order-cap fix: pre-cancel zombie working orders per
    (symbol, close-side) before any close MKT is submitted."""
    from routers.safety_router import flatten_all
    import services.trading_bot_service as tbs_mod

    tbs_mod.TradeStatus = SimpleNamespace(
        OPEN=SimpleNamespace(value="open"),
        CLOSED=SimpleNamespace(value="closed"),
    )

    bot = MagicMock()
    # Two distinct symbols, one long one short.
    bot._open_trades = {
        "a": _ns("a", sym="BMNR", direction="long", shares=4443),
        "b": _ns("b", sym="DDOG", direction="short", shares=378,
                 t="2026-05-08T08:00:00+00:00"),
    }
    bot.close_trade = AsyncMock(return_value=True)
    bot._save_trade = MagicMock(return_value=None)
    bot._closed_trades = []

    fake_ib_direct = MagicMock()
    fake_ib_direct.ensure_connected = AsyncMock(return_value=True)
    fake_ib_direct.cancel_all_open_orders_for_symbol = AsyncMock(
        return_value={"success": True, "cancelled": [{"order_id": 1}, {"order_id": 2}], "errors": []}
    )

    with patch("services.trading_bot_service.get_trading_bot_service",
               return_value=bot, create=True), \
         patch("services.ib_direct_service.get_ib_direct_service",
               return_value=fake_ib_direct, create=True), \
         patch("motor.motor_asyncio.AsyncIOMotorClient",
               return_value=_fake_db_chain(), create=True), \
         patch.dict("os.environ", {"MONGO_URL": "mongodb://x", "DB_NAME": "test"}):
        result = _run(flatten_all(confirm="FLATTEN"))

    # cancel_all_open_orders_for_symbol called ONCE per (symbol, close-side).
    # BMNR long → SELL side; DDOG short → BUY side.
    assert fake_ib_direct.cancel_all_open_orders_for_symbol.await_count == 2
    seen = sorted(
        (c.args[0], c.kwargs.get("side"))
        for c in fake_ib_direct.cancel_all_open_orders_for_symbol.await_args_list
    )
    assert seen == [("BMNR", "SELL"), ("DDOG", "BUY")]

    # Pre-cancel results surfaced in the summary.
    s = result["summary"]
    assert "zombie_cancel_results" in s
    assert any(r.get("symbol") == "BMNR" and r.get("cancelled_count") == 2
               for r in s["zombie_cancel_results"])


def test_flatten_proceeds_without_zombie_cancel_if_ib_direct_unreachable():
    """When IB direct can't connect within the 2s budget, flatten should
    still attempt the close burst. Best-effort — the operator may see
    Error 201 in close_errors if zombies remain, but flatten won't hang."""
    from routers.safety_router import flatten_all
    import services.trading_bot_service as tbs_mod

    tbs_mod.TradeStatus = SimpleNamespace(
        OPEN=SimpleNamespace(value="open"),
        CLOSED=SimpleNamespace(value="closed"),
    )

    bot = MagicMock()
    bot._open_trades = {"a": _ns("a", sym="LIN")}
    bot.close_trade = AsyncMock(return_value=True)
    bot._save_trade = MagicMock(return_value=None)
    bot._closed_trades = []

    fake_ib_direct = MagicMock()
    # ensure_connected returns False (or raises).
    fake_ib_direct.ensure_connected = AsyncMock(return_value=False)
    fake_ib_direct.cancel_all_open_orders_for_symbol = AsyncMock()

    with patch("services.trading_bot_service.get_trading_bot_service",
               return_value=bot, create=True), \
         patch("services.ib_direct_service.get_ib_direct_service",
               return_value=fake_ib_direct, create=True), \
         patch("motor.motor_asyncio.AsyncIOMotorClient",
               return_value=_fake_db_chain(), create=True), \
         patch.dict("os.environ", {"MONGO_URL": "mongodb://x", "DB_NAME": "test"}):
        result = _run(flatten_all(confirm="FLATTEN"))

    # cancel_all should NOT have been called.
    fake_ib_direct.cancel_all_open_orders_for_symbol.assert_not_awaited()
    # But close_trade WAS called.
    assert bot.close_trade.await_count == 1
    # And summary records why zombie-cancel was skipped.
    assert any("ib_direct_not_connected" in r.get("err", "")
               for r in result["summary"]["zombie_cancel_results"])
