"""v19.34.143 — `/api/diagnostic/bracket-status` endpoint regression.

Pinned tests for the small forensic endpoint that powers
`scripts/verify_naked_orphan_healing.py`. The endpoint must
correctly classify every open fragment into one of:

  - BRACKETED       (real stop_order_id, matches a live IB order)
  - NAKED_NO_STOP   (stop_order_id is None)
  - NAKED_SIM       (stop_order_id starts with SIM- or ADOPT-STOP-)
  - NAKED_STALE     (stop_order_id present but absent from IB live set)

…and respect the optional `?symbols=A,B,C` filter.
"""

from unittest.mock import AsyncMock, MagicMock
import sys

import pytest


def _make_trade(*, tid, symbol, shares, stop_order_id,
                setup_type="momentum_breakout", entered_by="bot_fired"):
    t = MagicMock()
    t.id = tid
    t.symbol = symbol
    t.shares = shares
    t.remaining_shares = shares
    t.stop_order_id = stop_order_id
    t.target_order_ids = []
    t.oca_group = None
    t.setup_type = setup_type
    t.entered_by = entered_by
    return t


@pytest.fixture
def patched_bracket_status(monkeypatch):
    """Wire up: bot with 4 open trades, IB pusher with 1 live order id."""
    fake_orph = type(sys)("services.orphan_gtc_reconciler")

    async def _fake_fetch():
        return (
            [
                {"ib_order_id": "REAL-STP-100", "symbol": "AAPL"},
            ],
            {"tier": "pusher_orders_snapshot", "ok": True},
        )
    fake_orph._fetch_ib_open_orders = _fake_fetch
    monkeypatch.setitem(sys.modules, "services.orphan_gtc_reconciler",
                        fake_orph)

    open_trades = {
        # BRACKETED — stop id matches a live IB order
        "t-aapl": _make_trade(
            tid="t-aapl", symbol="AAPL", shares=100,
            stop_order_id="REAL-STP-100"),
        # NAKED_NO_STOP — stop_order_id is None
        "t-te": _make_trade(
            tid="t-te", symbol="TE", shares=7204, stop_order_id=None,
            setup_type="reconciled_orphan", entered_by="reconciled_external"),
        # NAKED_SIM — SIM- prefix
        "t-ego": _make_trade(
            tid="t-ego", symbol="EGO", shares=2046,
            stop_order_id="SIM-STP-t-ego",
            setup_type="reconciled_orphan",
            entered_by="reconciled_external"),
        # NAKED_STALE — real-looking id but NOT in live order set
        "t-ktos": _make_trade(
            tid="t-ktos", symbol="KTOS", shares=300,
            stop_order_id="OLD-CANCELLED-9",
            setup_type="reconciled_orphan",
            entered_by="reconciled_external"),
    }

    fake_bot = MagicMock()
    fake_bot._open_trades = open_trades

    fake_tb_mod = type(sys)("services.trading_bot_service")
    fake_tb_mod.get_trading_bot_service = lambda: fake_bot
    monkeypatch.setitem(sys.modules, "services.trading_bot_service",
                        fake_tb_mod)
    return open_trades


@pytest.mark.asyncio
async def test_bracket_status_classifies_each_fragment(patched_bracket_status):
    from routers.diagnostic_router import bracket_status_per_symbol
    resp = await bracket_status_per_symbol()
    assert resp["success"] is True
    by_sym = {r["symbol"]: r for r in resp["rows"]}

    assert by_sym["AAPL"]["status"] == "BRACKETED"
    assert by_sym["AAPL"]["in_live_orders"] is True
    assert by_sym["AAPL"]["is_simulated_stop"] is False

    assert by_sym["TE"]["status"] == "NAKED_NO_STOP"
    assert by_sym["TE"]["stop_order_id"] is None

    assert by_sym["EGO"]["status"] == "NAKED_SIM"
    assert by_sym["EGO"]["is_simulated_stop"] is True

    assert by_sym["KTOS"]["status"] == "NAKED_STALE"
    assert by_sym["KTOS"]["is_simulated_stop"] is False
    assert by_sym["KTOS"]["in_live_orders"] is False


@pytest.mark.asyncio
async def test_bracket_status_summary_counts(patched_bracket_status):
    from routers.diagnostic_router import bracket_status_per_symbol
    resp = await bracket_status_per_symbol()
    s = resp["summary"]
    assert s["total"] == 4
    assert s["bracketed"] == 1
    assert s["naked_no_stop"] == 1
    assert s["naked_sim"] == 1
    assert s["naked_stale"] == 1


@pytest.mark.asyncio
async def test_bracket_status_symbol_filter(patched_bracket_status):
    from routers.diagnostic_router import bracket_status_per_symbol
    resp = await bracket_status_per_symbol(symbols="TE,EGO,KTOS")
    syms = {r["symbol"] for r in resp["rows"]}
    assert syms == {"TE", "EGO", "KTOS"}
    assert resp["filter_symbols"] == ["EGO", "KTOS", "TE"]
    # AAPL filtered out.
    assert resp["summary"]["total"] == 3
    assert resp["summary"]["bracketed"] == 0


@pytest.mark.asyncio
async def test_bracket_status_skips_zero_remaining(monkeypatch):
    """A fragment with remaining_shares == 0 is a zombie — it must NOT
    appear in the bracket-status output regardless of its stop_order_id."""
    fake_orph = type(sys)("services.orphan_gtc_reconciler")

    async def _fake_fetch():
        return ([], {"tier": "pusher_orders_snapshot", "ok": True})
    fake_orph._fetch_ib_open_orders = _fake_fetch
    monkeypatch.setitem(sys.modules, "services.orphan_gtc_reconciler",
                        fake_orph)

    zombie = _make_trade(tid="z1", symbol="DEAD", shares=0,
                         stop_order_id=None)
    zombie.remaining_shares = 0
    alive = _make_trade(tid="a1", symbol="LIVE", shares=50,
                        stop_order_id="REAL-1")
    fake_bot = MagicMock()
    fake_bot._open_trades = {"z1": zombie, "a1": alive}
    fake_tb_mod = type(sys)("services.trading_bot_service")
    fake_tb_mod.get_trading_bot_service = lambda: fake_bot
    monkeypatch.setitem(sys.modules, "services.trading_bot_service",
                        fake_tb_mod)

    from routers.diagnostic_router import bracket_status_per_symbol
    resp = await bracket_status_per_symbol()
    syms = {r["symbol"] for r in resp["rows"]}
    assert "DEAD" not in syms
    assert "LIVE" in syms


@pytest.mark.asyncio
async def test_bracket_status_handles_missing_open_orders(monkeypatch):
    """If `_fetch_ib_open_orders` raises, the endpoint must still
    return rows — fragments with non-None stop_order_id classify as
    NAKED_STALE (no live set to confirm against), simulated as
    NAKED_SIM, missing as NAKED_NO_STOP."""
    fake_orph = type(sys)("services.orphan_gtc_reconciler")

    async def _fake_fetch():
        raise RuntimeError("pusher unreachable")
    fake_orph._fetch_ib_open_orders = _fake_fetch
    monkeypatch.setitem(sys.modules, "services.orphan_gtc_reconciler",
                        fake_orph)

    alive = _make_trade(tid="x", symbol="AAPL", shares=100,
                        stop_order_id="STP-123")
    fake_bot = MagicMock()
    fake_bot._open_trades = {"x": alive}
    fake_tb_mod = type(sys)("services.trading_bot_service")
    fake_tb_mod.get_trading_bot_service = lambda: fake_bot
    monkeypatch.setitem(sys.modules, "services.trading_bot_service",
                        fake_tb_mod)

    from routers.diagnostic_router import bracket_status_per_symbol
    resp = await bracket_status_per_symbol()
    assert resp["success"] is True
    # Source string should signal the error.
    assert resp["open_orders_source"].startswith("error:")
    # The fragment couldn't be cross-checked → NAKED_STALE.
    assert resp["rows"][0]["status"] == "NAKED_STALE"
