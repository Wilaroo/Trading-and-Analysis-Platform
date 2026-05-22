"""
v19.34.79 — Bracket-stacking auto-cancel endpoint.

Validates `POST /api/trading-bot/bracket-stacking-cancel` correctly picks
the keep-set (most recent complete OCA pair) and cancels excess legs via
the safe `ib_direct_service.cancel_order()` path.

Test scenarios (8):
  1. dry_run=True returns a plan, no cancellations executed
  2. 3 stops + 1 target with 80sh position → keeps newest complete OCA
     pair, cancels 240sh of excess stops
  3. clean symbol (pos == stop == target qty) → not in output
  4. pos_qty==0 → refused with reason="pos_qty_zero"
  5. no stop leg exists in ANY oca group → refused with
     reason="would_leave_naked_no_stop_to_keep"
  6. symbols filter restricts processing to a subset
  7. when no complete pair exists, picks the leg closest to pos_qty
  8. cancel returns error from ib_direct → propagated as status string,
     overall response still success=true
"""
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


# ─────────────────────── Test scaffolding ───────────────────────


def _audit_row(symbol, pos_qty, stop_legs, target_legs):
    """Build one row of the bracket_stacking_audit response."""
    pending_stop = sum(int(l["qty"]) for l in stop_legs)
    pending_tgt = sum(int(l["qty"]) for l in target_legs)
    return {
        "symbol": symbol,
        "bot_position_qty": pos_qty,
        "ib_position_qty": pos_qty,
        "pending_stop_qty_total": pending_stop,
        "pending_target_qty_total": pending_tgt,
        "stop_legs": stop_legs,
        "target_legs": target_legs,
        "excess_stop_qty": max(0, pending_stop - abs(pos_qty)),
        "excess_target_qty": max(0, pending_tgt - abs(pos_qty)),
        "severity": "high" if pending_stop > abs(pos_qty) * 2 else "medium",
        "recommendation": "test",
    }


def _leg(order_id, qty, oca, kind="stop", price=100.0):
    return {
        "order_id": order_id,
        "qty": qty,
        "price": price,
        "oca_group": oca,
        "action": "BUY" if kind == "stop" else "SELL",
        "order_type": "STP" if kind == "stop" else "LMT",
        "status": "PreSubmitted",
    }


def _make_audit_response(rows):
    return {
        "success": True,
        "as_of": "2026-05-22T15:30:00+00:00",
        "symbols": rows,
        "clean_symbols": [],
    }


@pytest.fixture
def mock_trading_bot():
    """Patch _trading_bot in the router so the endpoint doesn't 503."""
    with patch("routers.trading_bot._trading_bot", MagicMock()):
        yield


@pytest.fixture
def mock_ib_direct():
    """Patch ib_direct_service.get_ib_direct_service so cancel_order is
    a no-op AsyncMock returning success."""
    mock_svc = MagicMock()
    mock_svc.cancel_order = AsyncMock(return_value={"success": True})
    with patch(
        "services.ib_direct_service.get_ib_direct_service",
        return_value=mock_svc,
    ):
        yield mock_svc


# ─────────────────────── Test 1: dry_run plan only ───────────────


def test_dry_run_returns_plan_no_cancellations(mock_trading_bot, mock_ib_direct):
    from routers.trading_bot import (
        bracket_stacking_cancel,
        BracketStackingCancelRequest,
    )

    rows = [_audit_row(
        "GM", 80,
        stop_legs=[
            _leg(101, 80, "OCA-GM-keep", "stop"),
            _leg(99, 40, "OCA-GM-old", "stop"),
        ],
        target_legs=[
            _leg(102, 80, "OCA-GM-keep", "target"),
            _leg(100, 40, "OCA-GM-old", "target"),
        ],
    )]
    with patch(
        "routers.trading_bot.bracket_stacking_audit",
        AsyncMock(return_value=_make_audit_response(rows)),
    ):
        result = asyncio.run(bracket_stacking_cancel(
            BracketStackingCancelRequest(dry_run=True)
        ))

    assert result["success"] is True
    assert result["dry_run"] is True
    assert mock_ib_direct.cancel_order.await_count == 0
    syms = result["symbols_processed"]
    assert len(syms) == 1
    cancelled = syms[0]["cancelled_legs"]
    assert all(c["status"] == "dry_run_planned" for c in cancelled)
    assert result["totals"]["cancelled"] == 0


# ─────────────────────── Test 2: keep newest complete OCA pair ───


def test_keeps_newest_complete_oca_pair_cancels_rest(mock_trading_bot, mock_ib_direct):
    from routers.trading_bot import (
        bracket_stacking_cancel,
        BracketStackingCancelRequest,
    )

    # 3 stop legs + 1 target, 80sh position. Only OCA-keep has a
    # complete pair AND qty match — that's what should be kept.
    rows = [_audit_row(
        "GM", 80,
        stop_legs=[
            _leg(99, 80, "OCA-old-1", "stop"),
            _leg(105, 80, "OCA-keep", "stop"),
            _leg(101, 80, "OCA-old-2", "stop"),
        ],
        target_legs=[
            _leg(106, 80, "OCA-keep", "target"),
        ],
    )]
    with patch(
        "routers.trading_bot.bracket_stacking_audit",
        AsyncMock(return_value=_make_audit_response(rows)),
    ):
        result = asyncio.run(bracket_stacking_cancel(
            BracketStackingCancelRequest(dry_run=False)
        ))

    syms = result["symbols_processed"]
    assert len(syms) == 1
    s = syms[0]
    assert s["symbol"] == "GM"
    assert s["kept_oca_group"] == "OCA-keep"
    kept_oids = {l["order_id"] for l in s["kept_legs"]}
    assert kept_oids == {105, 106}
    cancelled_oids = {c["order_id"] for c in s["cancelled_legs"]}
    assert cancelled_oids == {99, 101}
    # All cancellations succeeded (mock_ib_direct returns success).
    assert all(c["status"] == "cancel_ok" for c in s["cancelled_legs"])
    assert result["totals"]["cancelled"] == 2


# ─────────────────────── Test 3: clean symbol ───────────────────


def test_clean_symbol_not_processed(mock_trading_bot, mock_ib_direct):
    from routers.trading_bot import (
        bracket_stacking_cancel,
        BracketStackingCancelRequest,
    )

    # Audit shouldn't include clean symbols, but defend even if it does.
    rows = [_audit_row(
        "MSFT", 100,
        stop_legs=[_leg(201, 100, "OCA-A", "stop")],
        target_legs=[_leg(202, 100, "OCA-A", "target")],
    )]
    # Manually clear excess so this looks like a clean row.
    rows[0]["excess_stop_qty"] = 0
    rows[0]["excess_target_qty"] = 0
    with patch(
        "routers.trading_bot.bracket_stacking_audit",
        AsyncMock(return_value=_make_audit_response(rows)),
    ):
        result = asyncio.run(bracket_stacking_cancel(
            BracketStackingCancelRequest(dry_run=False)
        ))
    # Defensive code in endpoint should skip this — no entry in output.
    assert result["symbols_processed"] == []
    assert result["totals"]["cancelled"] == 0


# ─────────────────────── Test 4: pos_qty==0 refused ────────────


def test_pos_qty_zero_refused(mock_trading_bot, mock_ib_direct):
    from routers.trading_bot import (
        bracket_stacking_cancel,
        BracketStackingCancelRequest,
    )

    rows = [_audit_row(
        "PHANTOM", 0,
        stop_legs=[_leg(301, 50, "OCA-X", "stop")],
        target_legs=[_leg(302, 50, "OCA-X", "target")],
    )]
    with patch(
        "routers.trading_bot.bracket_stacking_audit",
        AsyncMock(return_value=_make_audit_response(rows)),
    ):
        result = asyncio.run(bracket_stacking_cancel(
            BracketStackingCancelRequest(dry_run=False)
        ))

    syms = result["symbols_processed"]
    assert len(syms) == 1
    assert syms[0]["refused_reason"] == "pos_qty_zero"
    assert syms[0]["cancelled_legs"] == []
    assert mock_ib_direct.cancel_order.await_count == 0
    assert result["totals"]["refused_symbols"] == 1


# ─────────────────────── Test 5: no stop leg → refuse ───────────


def test_no_stop_leg_anywhere_refused_to_avoid_naked(mock_trading_bot, mock_ib_direct):
    from routers.trading_bot import (
        bracket_stacking_cancel,
        BracketStackingCancelRequest,
    )

    rows = [_audit_row(
        "NAKEDTGT", 50,
        stop_legs=[],
        target_legs=[
            _leg(401, 50, "OCA-A", "target"),
            _leg(402, 50, "OCA-B", "target"),
        ],
    )]
    with patch(
        "routers.trading_bot.bracket_stacking_audit",
        AsyncMock(return_value=_make_audit_response(rows)),
    ):
        result = asyncio.run(bracket_stacking_cancel(
            BracketStackingCancelRequest(dry_run=False)
        ))

    syms = result["symbols_processed"]
    assert len(syms) == 1
    assert syms[0]["refused_reason"] == "would_leave_naked_no_stop_to_keep"
    assert syms[0]["cancelled_legs"] == []
    assert mock_ib_direct.cancel_order.await_count == 0


# ─────────────────────── Test 6: symbols filter ─────────────────


def test_symbols_filter_restricts_processing(mock_trading_bot, mock_ib_direct):
    from routers.trading_bot import (
        bracket_stacking_cancel,
        BracketStackingCancelRequest,
    )

    rows = [
        _audit_row("GM", 80,
                   stop_legs=[_leg(501, 80, "OCA-A", "stop"),
                              _leg(502, 80, "OCA-B", "stop")],
                   target_legs=[_leg(503, 80, "OCA-A", "target")]),
        _audit_row("LIN", 50,
                   stop_legs=[_leg(601, 50, "OCA-C", "stop"),
                              _leg(602, 50, "OCA-D", "stop")],
                   target_legs=[_leg(603, 50, "OCA-C", "target")]),
    ]
    with patch(
        "routers.trading_bot.bracket_stacking_audit",
        AsyncMock(return_value=_make_audit_response(rows)),
    ):
        result = asyncio.run(bracket_stacking_cancel(
            BracketStackingCancelRequest(dry_run=False, symbols=["LIN"])
        ))

    syms = result["symbols_processed"]
    assert len(syms) == 1
    assert syms[0]["symbol"] == "LIN"


# ─────────────────────── Test 7: no complete pair, qty match ────


def test_no_complete_pair_keeps_qty_match(mock_trading_bot, mock_ib_direct):
    from routers.trading_bot import (
        bracket_stacking_cancel,
        BracketStackingCancelRequest,
    )

    # Each OCA group has only ONE leg. The 80sh stop in OCA-keep should
    # win the keep-spot (qty match to pos_qty=80), the 40sh stops get
    # cancelled.
    rows = [_audit_row(
        "MSFT", 80,
        stop_legs=[
            _leg(701, 40, "OCA-a", "stop"),
            _leg(702, 80, "OCA-keep", "stop"),
            _leg(703, 40, "OCA-c", "stop"),
        ],
        target_legs=[],
    )]
    with patch(
        "routers.trading_bot.bracket_stacking_audit",
        AsyncMock(return_value=_make_audit_response(rows)),
    ):
        result = asyncio.run(bracket_stacking_cancel(
            BracketStackingCancelRequest(dry_run=False)
        ))

    s = result["symbols_processed"][0]
    assert s["kept_oca_group"] == "OCA-keep"
    kept_oids = {l["order_id"] for l in s["kept_legs"]}
    assert kept_oids == {702}
    cancelled_oids = {c["order_id"] for c in s["cancelled_legs"]}
    assert cancelled_oids == {701, 703}


# ─────────────────────── Test 8: cancel error propagated ────────


def test_cancel_error_propagated_response_still_success(mock_trading_bot):
    from routers.trading_bot import (
        bracket_stacking_cancel,
        BracketStackingCancelRequest,
    )

    mock_svc = MagicMock()
    # First call succeeds, second returns error
    mock_svc.cancel_order = AsyncMock(side_effect=[
        {"success": True},
        {"success": False, "error": "order_id 999 not found in live trades"},
    ])
    rows = [_audit_row(
        "GM", 80,
        stop_legs=[
            _leg(801, 80, "OCA-keep", "stop"),
            _leg(802, 80, "OCA-old1", "stop"),
            _leg(999, 80, "OCA-old2", "stop"),
        ],
        target_legs=[_leg(803, 80, "OCA-keep", "target")],
    )]
    with patch("services.ib_direct_service.get_ib_direct_service",
               return_value=mock_svc), \
         patch("routers.trading_bot.bracket_stacking_audit",
               AsyncMock(return_value=_make_audit_response(rows))):
        result = asyncio.run(bracket_stacking_cancel(
            BracketStackingCancelRequest(dry_run=False)
        ))

    assert result["success"] is True
    s = result["symbols_processed"][0]
    statuses = {c["order_id"]: c["status"] for c in s["cancelled_legs"]}
    assert statuses[802] == "cancel_ok"
    assert "cancel_err" in statuses[999]
    # Only the OK one counts in totals.
    assert result["totals"]["cancelled"] == 1
