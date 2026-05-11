"""
v19.34.76 — Retroactive bracket attach for unprotected positions
=================================================================

Background
----------
2026-05-12 forensic audit of TWS orders showed BMNR (658sh, ~$15k) was
naked at IB — no stop, no target. BMNR is the orphan adopted yesterday
during the kill-switch bypass incident; v19.34.68 attaches brackets
when the reconciler claims a NEW orphan, but BMNR was already in
`_open_trades` BEFORE v19.34.68 shipped, so the orphan-adoption code
path was skipped on restart and the retroactive attach never ran.

This endpoint patches the gap: scans `_open_trades` for any trade
whose `stop_order_id` is missing (or starts with "SIM-"), computes a
reasonable stop/target from pusher last-price (or entry-price
fallback), and fires `attach_oca_stop_target` to re-arm protection.

Tested behavior
---------------
1. Dry-run returns the computed stop/target values without firing
   orders. `applied=False` on every candidate.
2. Already-bracketed trades land in `skipped` (real, non-SIM-prefixed
   stop_order_id AND at least one real target_order_id).
3. `dry_run=false` calls `attach_oca_stop_target` per candidate;
   `applied=True` and `result.success=True` on the happy path.
4. `symbols=[...]` filter limits which trades are considered.
5. `overrides={"BMNR": {"stop": 20.0}}` honours operator-supplied
   prices over the computed defaults.
6. Long vs short directions invert the stop/target sign correctly.
7. Trades with no entry_price AND no pusher last_price are skipped
   with `reason="no_reference_price_available"`.
8. SIM- prefixed existing stop_order_ids are treated as unprotected
   (re-arms the bracket on top).
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, "/app/backend")


def _mk_trade(
    trade_id: str, symbol: str, shares: int, entry_price: float,
    direction: str = "long",
    stop_order_id=None, target_order_ids=None,
):
    direction_obj = SimpleNamespace(value=direction)
    return SimpleNamespace(
        id=trade_id, symbol=symbol, shares=shares,
        entry_price=entry_price, fill_price=entry_price,
        stop_price=None, target_prices=None,
        direction=direction_obj,
        stop_order_id=stop_order_id,
        target_order_ids=target_order_ids or [],
    )


def _mk_app_state():
    """Patch routers.trading_bot._trading_bot + _trade_executor."""
    import routers.trading_bot as tb
    return tb


def _save_trade_stub(*a, **kw):
    return None


@pytest.fixture
def patched_app():
    """Install fresh _trading_bot + _trade_executor stubs and yield the
    request/handler pair. Restores originals on teardown."""
    tb = _mk_app_state()
    orig_bot, orig_exec = tb._trading_bot, tb._trade_executor

    bot = SimpleNamespace(
        _open_trades={},
        _save_trade=_save_trade_stub,
    )
    executor = SimpleNamespace(
        attach_oca_stop_target=AsyncMock(return_value={
            "success": True,
            "stop_order_id": "REAL-STP-123",
            "target_order_id": "REAL-TGT-456",
            "oca_group": "OCA-test-v76",
        }),
    )
    tb._trading_bot = bot
    tb._trade_executor = executor

    yield bot, executor, tb.attach_brackets_to_unprotected, tb.AttachBracketsRequest

    tb._trading_bot, tb._trade_executor = orig_bot, orig_exec


@pytest.mark.asyncio
async def test_dry_run_reports_candidates_without_firing(patched_app):
    bot, executor, handler, Req = patched_app
    bot._open_trades = {
        "t-bmnr": _mk_trade("t-bmnr", "BMNR", 658, 22.57),
    }
    with patch("routers.ib._pushed_ib_data", {"quotes": [
        {"symbol": "BMNR", "last": 23.50},
    ]}):
        resp = await handler(Req(dry_run=True))
    assert resp["success"] is True
    assert resp["dry_run"] is True
    assert len(resp["candidates"]) == 1
    cand = resp["candidates"][0]
    assert cand["symbol"] == "BMNR"
    assert cand["applied"] is False
    assert cand["computed"]["stop"] == 23.03   # 23.50 * (1 - 2/100), rounded
    assert cand["computed"]["target"] == 25.38  # 23.50 * (1 + 8/100)
    assert cand["computed"]["source"] == "pusher_last_price"
    # No actual broker call.
    executor.attach_oca_stop_target.assert_not_awaited()


@pytest.mark.asyncio
async def test_already_bracketed_lands_in_skipped(patched_app):
    bot, executor, handler, Req = patched_app
    bot._open_trades = {
        "t-adbe": _mk_trade(
            "t-adbe", "ADBE", 80, 246.95,
            stop_order_id="REAL-STP-existing",
            target_order_ids=["REAL-TGT-existing"],
        ),
    }
    with patch("routers.ib._pushed_ib_data", {"quotes": [
        {"symbol": "ADBE", "last": 247.0},
    ]}):
        resp = await handler(Req(dry_run=True))
    assert resp["candidates"] == []
    assert len(resp["skipped"]) == 1
    assert resp["skipped"][0]["symbol"] == "ADBE"
    assert resp["skipped"][0]["reason"] == "already_bracketed"


@pytest.mark.asyncio
async def test_sim_prefixed_stop_is_treated_as_unprotected(patched_app):
    """SIM- ids are simulator/dry-run placeholders, not real broker
    protection — must be treated as unprotected so the retroactive
    attach re-arms them."""
    bot, executor, handler, Req = patched_app
    bot._open_trades = {
        "t-sim": _mk_trade(
            "t-sim", "BMNR", 658, 22.57,
            stop_order_id="SIM-STP-placeholder",
            target_order_ids=["SIM-TGT-placeholder"],
        ),
    }
    with patch("routers.ib._pushed_ib_data", {"quotes": [
        {"symbol": "BMNR", "last": 22.57},
    ]}):
        resp = await handler(Req(dry_run=True))
    assert len(resp["candidates"]) == 1
    assert resp["skipped"] == []


@pytest.mark.asyncio
async def test_apply_fires_attach_and_records_ids(patched_app):
    bot, executor, handler, Req = patched_app
    trade = _mk_trade("t-bmnr", "BMNR", 658, 22.57)
    bot._open_trades = {"t-bmnr": trade}
    with patch("routers.ib._pushed_ib_data", {"quotes": [
        {"symbol": "BMNR", "last": 23.50},
    ]}):
        resp = await handler(Req(dry_run=False))
    assert resp["dry_run"] is False
    cand = resp["candidates"][0]
    assert cand["applied"] is True
    assert cand["result"]["success"] is True
    assert cand["result"]["stop_order_id"] == "REAL-STP-123"
    # In-memory trade object got the new ids.
    assert trade.stop_order_id == "REAL-STP-123"
    assert trade.target_order_ids == ["REAL-TGT-456"]
    # And the computed stop_price/target_prices were set so attach_oca
    # had the values to submit.
    assert trade.stop_price == 23.03
    assert trade.target_prices == [25.38]
    executor.attach_oca_stop_target.assert_awaited_once()


@pytest.mark.asyncio
async def test_symbol_filter_narrows_candidates(patched_app):
    bot, executor, handler, Req = patched_app
    bot._open_trades = {
        "t-bmnr": _mk_trade("t-bmnr", "BMNR", 658, 22.57),
        "t-pep": _mk_trade("t-pep", "PEP", 323, 149.83),
    }
    with patch("routers.ib._pushed_ib_data", {"quotes": [
        {"symbol": "BMNR", "last": 22.57}, {"symbol": "PEP", "last": 149.83},
    ]}):
        resp = await handler(Req(dry_run=True, symbols=["BMNR"]))
    syms = [c["symbol"] for c in resp["candidates"]]
    assert syms == ["BMNR"]


@pytest.mark.asyncio
async def test_overrides_take_precedence(patched_app):
    bot, executor, handler, Req = patched_app
    bot._open_trades = {
        "t-bmnr": _mk_trade("t-bmnr", "BMNR", 658, 22.57),
    }
    with patch("routers.ib._pushed_ib_data", {"quotes": [
        {"symbol": "BMNR", "last": 23.50},
    ]}):
        resp = await handler(Req(
            dry_run=True,
            overrides={"BMNR": {"stop": 20.00, "target": 26.50}},
        ))
    cand = resp["candidates"][0]
    assert cand["computed"]["stop"] == 20.00
    assert cand["computed"]["target"] == 26.50
    assert cand["computed"]["source"] == "operator_override"


@pytest.mark.asyncio
async def test_short_direction_inverts_stop_and_target(patched_app):
    bot, executor, handler, Req = patched_app
    bot._open_trades = {
        "t-mdt": _mk_trade(
            "t-mdt", "MDT", 412, 74.55,
            direction="short",
        ),
    }
    with patch("routers.ib._pushed_ib_data", {"quotes": [
        {"symbol": "MDT", "last": 74.55},
    ]}):
        resp = await handler(Req(dry_run=True))
    cand = resp["candidates"][0]
    # Short: stop ABOVE current price, target BELOW.
    assert cand["computed"]["stop"] > cand["computed"]["ref_price"]
    assert cand["computed"]["target"] < cand["computed"]["ref_price"]
    assert cand["computed"]["stop"] == 76.04   # 74.55 * 1.02
    assert cand["computed"]["target"] == 68.59  # 74.55 * 0.92


@pytest.mark.asyncio
async def test_no_reference_price_is_skipped(patched_app):
    bot, executor, handler, Req = patched_app
    bot._open_trades = {
        "t-nada": _mk_trade("t-nada", "NADA", 100, 0.0),  # no entry price
    }
    with patch("routers.ib._pushed_ib_data", {"quotes": []}):
        resp = await handler(Req(dry_run=True))
    assert resp["candidates"] == []
    assert len(resp["skipped"]) == 1
    assert resp["skipped"][0]["reason"] == "no_reference_price_available"


@pytest.mark.asyncio
async def test_entry_price_used_when_pusher_quote_missing(patched_app):
    bot, executor, handler, Req = patched_app
    bot._open_trades = {
        "t-bmnr": _mk_trade("t-bmnr", "BMNR", 658, 22.57),
    }
    with patch("routers.ib._pushed_ib_data", {"quotes": []}):
        resp = await handler(Req(dry_run=True))
    cand = resp["candidates"][0]
    assert cand["computed"]["source"] == "entry_price"
    assert cand["computed"]["ref_price"] == 22.57
