"""v19.34.91 — Sizing-aware cancel-excess-bracket-legs.

Locks in:
  - Pre-flight: when sum(stops) == |bot_position|, nothing is cancelled (LIN case)
  - Greedy fill: keep enough brackets to cover |bot_position|, cancel rest
  - target_qty operator override works
  - Zero-position symbols cancel everything (no kept bracket)
  - Backward-compat `kept` singleton view still emitted
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, "/app/backend")


def _leg(order_id, qty, price, oca_group, order_type, symbol="LIN", action="SELL"):
    return {
        "order_id": order_id,
        "quantity": qty,
        "stop_price" if order_type.startswith("STP") else "limit_price": price,
        "oca_group": oca_group,
        "action": action,
        "order_type": order_type,
        "status": "PreSubmitted",
        "symbol": symbol,
    }


@pytest.fixture
def patched_app():
    import routers.trading_bot as tb
    orig_bot = tb._trading_bot
    bot = SimpleNamespace(_open_trades={})
    tb._trading_bot = bot
    yield bot, tb.cancel_excess_bracket_legs, tb.CancelExcessBracketLegsRequest
    tb._trading_bot = orig_bot


@pytest.mark.asyncio
async def test_perfect_match_keeps_everything(patched_app):
    """LIN case: pos=68, legs=21+47=68 → nothing to cancel."""
    bot, handler, Req = patched_app
    bot._open_trades = {
        "t-1": SimpleNamespace(
            symbol="LIN", remaining_shares=21, stop_order_id="101",
            target_order_ids=["102"],
        ),
        "t-2": SimpleNamespace(
            symbol="LIN", remaining_shares=47, stop_order_id="103",
            target_order_ids=["104"],
        ),
    }
    orders = [
        _leg(101, 21, 494.5, "OCA-A", "STP"),
        _leg(102, 21, 528.0, "OCA-A", "LMT"),
        _leg(103, 47, 495.2, "OCA-B", "STP"),
        _leg(104, 47, 528.6, "OCA-B", "LMT"),
    ]
    with patch("routers.ib._pushed_ib_data", {"orders": orders}):
        resp = await handler(Req(symbol="LIN", dry_run=True))
    assert resp["bot_position_qty"] == 68
    assert resp["target_qty"] == 68
    assert resp["kept_total_qty"] == 68
    assert len(resp["kept_brackets"]) == 2
    assert resp["cancelled"] == []


@pytest.mark.asyncio
async def test_oversized_cancels_down_to_position(patched_app):
    """ADBE-like case: pos=80, legs=40+40+80+80=240 → cancel 160 worth."""
    bot, handler, Req = patched_app
    bot._open_trades = {
        "t-1": SimpleNamespace(
            symbol="ADBE", remaining_shares=80, stop_order_id="999",
            target_order_ids=[],
        ),
    }
    orders = [
        _leg(101, 40, 237.0, "OCA-A", "STP", symbol="ADBE"),
        _leg(102, 40, 270.0, "OCA-A", "LMT", symbol="ADBE"),
        _leg(103, 40, 237.5, "OCA-B", "STP", symbol="ADBE"),
        _leg(104, 40, 270.5, "OCA-B", "LMT", symbol="ADBE"),
        _leg(105, 80, 238.0, "OCA-C", "STP", symbol="ADBE"),
        _leg(106, 80, 271.0, "OCA-C", "LMT", symbol="ADBE"),
    ]
    with patch("routers.ib._pushed_ib_data", {"orders": orders}):
        resp = await handler(Req(symbol="ADBE", dry_run=True))
    assert resp["target_qty"] == 80
    assert resp["kept_total_qty"] == 80
    # Greedy picks the newest 80-qty OCA-C bracket → kept = 105+106.
    kept_ids = {leg["order_id"] for b in resp["kept_brackets"]
                for leg in b["stops"] + b["targets"]}
    assert kept_ids == {105, 106}
    cancelled_ids = sorted(l["order_id"] for l in resp["cancelled"])
    assert cancelled_ids == [101, 102, 103, 104]


@pytest.mark.asyncio
async def test_zero_position_cancels_everything(patched_app):
    """LIN orphan case: pos=0, legs=21+47=68 → cancel everything."""
    bot, handler, Req = patched_app
    # No open trades for LIN.
    orders = [
        _leg(101, 21, 494.5, "OCA-A", "STP"),
        _leg(103, 47, 495.2, "OCA-B", "STP"),
    ]
    # With no bot_position AND no target_qty, target_qty=None which
    # triggers the LEGACY fallback (keep newest one). That's the safe
    # default for ambiguous state — operator should pass target_qty=0
    # to explicitly request "cancel everything".
    with patch("routers.ib._pushed_ib_data", {"orders": orders}):
        resp = await handler(Req(symbol="LIN", dry_run=True))
    # Legacy fallback: keeps newest (103).
    assert resp["used_legacy_fallback"] is True
    assert resp["kept"]["stop"]["order_id"] == 103
    # Now request target_qty=0 explicitly:
    with patch("routers.ib._pushed_ib_data", {"orders": orders}):
        resp2 = await handler(Req(symbol="LIN", dry_run=True, target_qty=0))
    assert resp2["target_qty"] == 0
    assert resp2["kept_total_qty"] == 0
    assert resp2["kept_brackets"] == []
    # All legs cancelled.
    cancelled_ids = sorted(l["order_id"] for l in resp2["cancelled"])
    assert cancelled_ids == [101, 103]


@pytest.mark.asyncio
async def test_target_qty_override(patched_app):
    """Operator can override bot_position via target_qty."""
    bot, handler, Req = patched_app
    bot._open_trades = {
        "t-1": SimpleNamespace(
            symbol="ADBE", remaining_shares=80, stop_order_id="999",
            target_order_ids=[],
        ),
    }
    orders = [
        _leg(101, 40, 237.0, "OCA-A", "STP", symbol="ADBE"),
        _leg(103, 80, 238.0, "OCA-B", "STP", symbol="ADBE"),
    ]
    # Bot says pos=80, operator overrides to pos=40 (e.g. just sold half)
    with patch("routers.ib._pushed_ib_data", {"orders": orders}):
        resp = await handler(Req(symbol="ADBE", dry_run=True, target_qty=40))
    assert resp["target_qty"] == 40
    assert resp["kept_total_qty"] == 40
    # 40-qty leg fits cleanly; 80-qty leg would exceed.
    kept_ids = {leg["order_id"] for b in resp["kept_brackets"]
                for leg in b["stops"] + b["targets"]}
    assert kept_ids == {101}


@pytest.mark.asyncio
async def test_oca_keeps_full_bracket(patched_app):
    """Single OCA's stop+target legs are kept atomically (don't split)."""
    bot, handler, Req = patched_app
    bot._open_trades = {
        "t-1": SimpleNamespace(
            symbol="MDT", remaining_shares=412, stop_order_id="999",
            target_order_ids=[],
        ),
    }
    orders = [
        _leg(101, 412, 76.0, "OCA-A", "STP", symbol="MDT", action="BUY"),
        _leg(102, 412, 70.0, "OCA-A", "LMT", symbol="MDT", action="BUY"),
        _leg(103, 412, 76.5, None, "STP", symbol="MDT", action="BUY"),
        _leg(104, 412, 70.5, None, "LMT", symbol="MDT", action="BUY"),
    ]
    with patch("routers.ib._pushed_ib_data", {"orders": orders}):
        resp = await handler(Req(symbol="MDT", dry_run=True))
    # Should prefer OCA'd bracket over non-OCA singletons.
    kept = resp["kept_brackets"]
    assert len(kept) == 1
    assert kept[0]["oca_group"] == "OCA-A"
    cancelled_ids = sorted(l["order_id"] for l in resp["cancelled"])
    assert cancelled_ids == [103, 104]


@pytest.mark.asyncio
async def test_backward_compat_kept_singleton_emitted(patched_app):
    """`kept` (singleton) field still emitted for backward compat with
    pre-v91 callers that look at `resp["kept"]["stop"]`."""
    bot, handler, Req = patched_app
    bot._open_trades = {
        "t-1": SimpleNamespace(
            symbol="ADBE", remaining_shares=40, stop_order_id="999",
            target_order_ids=[],
        ),
    }
    orders = [
        _leg(101, 40, 237.0, "OCA-A", "STP", symbol="ADBE"),
        _leg(102, 40, 270.0, "OCA-A", "LMT", symbol="ADBE"),
        _leg(103, 40, 238.0, "OCA-B", "STP", symbol="ADBE"),
        _leg(104, 40, 271.0, "OCA-B", "LMT", symbol="ADBE"),
    ]
    with patch("routers.ib._pushed_ib_data", {"orders": orders}):
        resp = await handler(Req(symbol="ADBE", dry_run=True))
    assert resp["kept"] is not None
    assert resp["kept"]["stop"] is not None
    assert resp["kept"]["target"] is not None


@pytest.mark.asyncio
async def test_keep_oca_group_override_still_works(patched_app):
    """v91 must preserve the v80 operator override `keep_oca_group`."""
    bot, handler, Req = patched_app
    bot._open_trades = {
        "t-1": SimpleNamespace(
            symbol="ADBE", remaining_shares=40, stop_order_id="999",
            target_order_ids=[],
        ),
    }
    orders = [
        _leg(101, 40, 237.0, "OCA-A", "STP", symbol="ADBE"),
        _leg(102, 40, 270.0, "OCA-A", "LMT", symbol="ADBE"),
        _leg(103, 40, 238.0, "OCA-B", "STP", symbol="ADBE"),
        _leg(104, 40, 271.0, "OCA-B", "LMT", symbol="ADBE"),
    ]
    with patch("routers.ib._pushed_ib_data", {"orders": orders}):
        resp = await handler(Req(
            symbol="ADBE", dry_run=True, keep_oca_group="OCA-A",
        ))
    assert resp["kept"]["decision_source"] == "keep_oca_group"
    kept_ids = {leg["order_id"] for b in resp["kept_brackets"]
                for leg in b["stops"] + b["targets"]}
    assert kept_ids == {101, 102}


@pytest.mark.asyncio
async def test_under_protected_keeps_all(patched_app):
    """If sum(legs) < target_qty, keep everything (under-protected;
    attach-brackets-to-unprotected should re-arm the gap)."""
    bot, handler, Req = patched_app
    bot._open_trades = {
        "t-1": SimpleNamespace(
            symbol="EFA", remaining_shares=963, stop_order_id="999",
            target_order_ids=[],
        ),
    }
    orders = [
        _leg(101, 500, 100.0, "OCA-A", "STP", symbol="EFA"),
        _leg(102, 500, 110.0, "OCA-A", "LMT", symbol="EFA"),
    ]
    with patch("routers.ib._pushed_ib_data", {"orders": orders}):
        resp = await handler(Req(symbol="EFA", dry_run=True))
    assert resp["target_qty"] == 963
    assert resp["kept_total_qty"] == 500  # under-protected by 463
    assert resp["cancelled"] == []
