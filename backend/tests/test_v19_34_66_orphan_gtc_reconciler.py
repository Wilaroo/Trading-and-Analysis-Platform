"""
test_v19_34_66_orphan_gtc_reconciler.py — pin v19.34.66 orphan-GTC
reconciler.

Triggered by 2026-02-09 forensic: user had 10 GTC sell-side bracket
legs from 5/4 sitting at IB after multiple bot restarts. The bot had
completely lost track of them. If any stop had triggered, IB would
have shorted the user that many shares with no protection.

This test suite pins the four classification verdicts using realistic
data shapes and the actual NXPI/VALE/NCLH/ELV symbols from that event.

All tests pure-Python — no IB, no Mongo, no live network.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ════════════════════════════════════════════════════════════════════════
# Pure classifier — the heart of the audit
# ════════════════════════════════════════════════════════════════════════


def _open_order(**kwargs):
    """Build an IB-open-order dict in the shape the classifier expects."""
    base = {
        "ib_order_id": 1000,
        "symbol": "XYZ",
        "action": "SELL",
        "quantity": 100,
        "order_type": "STP",
        "limit_price": None,
        "stop_price": 50.00,
        "time_in_force": "GTC",
        "status": "PreSubmitted",
    }
    base.update(kwargs)
    return base


def _bot_trade(**kwargs):
    base = {
        "id": "trade-xyz-1",
        "symbol": "XYZ",
        "status": "open",
        "remaining_shares": 100,
        "stop_order_id": None,
        "target_order_id": None,
    }
    base.update(kwargs)
    return base


def test_naked_no_position_classifies_correctly():
    """The exact 2026-05-04 case: GTC sell-stop alive at IB, position
    flattened manually, no IB shares left → would short on trigger."""
    from services.orphan_gtc_reconciler import (
        VERDICT_NAKED_NO_POSITION,
        classify_open_orders,
    )
    verdicts = classify_open_orders(
        ib_open_orders=[_open_order(
            ib_order_id=870896460, symbol="NXPI", action="SELL",
            quantity=192, order_type="STP", stop_price=287.02,
            time_in_force="GTC",
        )],
        ib_positions=[],          # ← user holds nothing
        bot_trades=[],
    )
    assert len(verdicts) == 1
    v = verdicts[0]
    assert v.verdict == VERDICT_NAKED_NO_POSITION
    assert v.symbol == "NXPI"
    assert v.ib_order_id == 870896460
    assert v.ib_position_size == 0.0
    assert any("would short on trigger" in r for r in v.reasons)


def test_orphan_no_trade_classifies_correctly():
    """Position exists, but bot has no trade row tracking the order_id."""
    from services.orphan_gtc_reconciler import (
        VERDICT_ORPHAN_NO_TRADE,
        classify_open_orders,
    )
    verdicts = classify_open_orders(
        ib_open_orders=[_open_order(
            ib_order_id=1077452802, symbol="VALE",
            action="SELL", quantity=2586,
        )],
        ib_positions=[{"symbol": "VALE", "position": 2586}],
        bot_trades=[
            # bot tracks DIFFERENT order_ids — none of these match 1077452802
            _bot_trade(id="t-vale-old", symbol="VALE",
                       stop_order_id=999_999, target_order_id=999_998),
        ],
    )
    assert verdicts[0].verdict == VERDICT_ORPHAN_NO_TRADE
    assert "no bot_trade row references" in verdicts[0].reasons[0]


def test_mismatched_size_classifies_correctly():
    """Bot tracks order, but order qty > IB position (over-protected)."""
    from services.orphan_gtc_reconciler import (
        VERDICT_MISMATCHED_SIZE,
        classify_open_orders,
    )
    verdicts = classify_open_orders(
        ib_open_orders=[_open_order(
            ib_order_id=42, symbol="ELV", action="SELL", quantity=113,
        )],
        ib_positions=[{"symbol": "ELV", "position": 50}],  # only 50 left
        bot_trades=[_bot_trade(id="t-elv", symbol="ELV", stop_order_id=42)],
    )
    assert verdicts[0].verdict == VERDICT_MISMATCHED_SIZE
    assert "would over-execute on trigger" in verdicts[0].reasons[0]


def test_tracked_classifies_correctly():
    """Healthy case: bot tracks the order, qty ≤ IB position."""
    from services.orphan_gtc_reconciler import (
        VERDICT_TRACKED,
        classify_open_orders,
    )
    verdicts = classify_open_orders(
        ib_open_orders=[_open_order(
            ib_order_id=42, symbol="ELV", action="SELL", quantity=113,
        )],
        ib_positions=[{"symbol": "ELV", "position": 113}],
        bot_trades=[_bot_trade(id="t-elv", symbol="ELV", stop_order_id=42)],
    )
    assert verdicts[0].verdict == VERDICT_TRACKED
    assert verdicts[0].bot_trade_id == "t-elv"


def test_perm_id_fallback_for_match():
    """If bot stored permId instead of orderId, the classifier still joins."""
    from services.orphan_gtc_reconciler import (
        VERDICT_TRACKED,
        classify_open_orders,
    )
    verdicts = classify_open_orders(
        ib_open_orders=[_open_order(
            ib_order_id=42, perm_id=999_111, symbol="ELV",
            action="SELL", quantity=113,
        )],
        ib_positions=[{"symbol": "ELV", "position": 113}],
        bot_trades=[_bot_trade(id="t-elv", symbol="ELV",
                               stop_order_id=999_111)],
    )
    assert verdicts[0].verdict == VERDICT_TRACKED


def test_target_order_ids_list_form_matches():
    """Bot stores `target_order_ids: [a, b, c]` — must still join."""
    from services.orphan_gtc_reconciler import (
        VERDICT_TRACKED,
        classify_open_orders,
    )
    verdicts = classify_open_orders(
        ib_open_orders=[_open_order(
            ib_order_id=2002, symbol="ELV", action="SELL", quantity=50,
        )],
        ib_positions=[{"symbol": "ELV", "position": 113}],
        bot_trades=[_bot_trade(id="t-elv", symbol="ELV",
                               target_order_ids=[2001, 2002, 2003])],
    )
    assert verdicts[0].verdict == VERDICT_TRACKED


def test_day_orders_filtered_out_by_default():
    """DAY orders auto-expire; v19.34.66 only audits GTC by default."""
    from services.orphan_gtc_reconciler import classify_open_orders
    verdicts = classify_open_orders(
        ib_open_orders=[_open_order(time_in_force="DAY")],
        ib_positions=[],
        bot_trades=[],
    )
    assert verdicts == []


def test_day_orders_included_when_only_gtc_false():
    from services.orphan_gtc_reconciler import classify_open_orders
    verdicts = classify_open_orders(
        ib_open_orders=[_open_order(time_in_force="DAY")],
        ib_positions=[],
        bot_trades=[],
        only_gtc=False,
    )
    assert len(verdicts) == 1


def test_non_working_status_orders_skipped():
    """Cancelled / Filled orders in a stale snapshot must not be audited."""
    from services.orphan_gtc_reconciler import classify_open_orders
    for status in ("Cancelled", "Filled", "ApiCancelled"):
        verdicts = classify_open_orders(
            ib_open_orders=[_open_order(status=status)],
            ib_positions=[],
            bot_trades=[],
        )
        assert verdicts == [], f"{status!r} should not be audited"


def test_yesterdays_event_full_forensic_replay():
    """End-to-end: feed the exact 10 GTCs from 5/4 + zero positions +
    no bot tracking. Every single one MUST be naked_no_position."""
    from services.orphan_gtc_reconciler import (
        VERDICT_NAKED_NO_POSITION,
        classify_open_orders,
    )
    yesterdays_orders = [
        _open_order(ib_order_id=870896459, symbol="NXPI", action="SELL",
                    quantity=192, order_type="LMT", limit_price=310.28,
                    stop_price=None),
        _open_order(ib_order_id=870896460, symbol="NXPI", action="SELL",
                    quantity=192, order_type="STP", stop_price=287.02),
        _open_order(ib_order_id=1077452802, symbol="VALE", action="SELL",
                    quantity=2586, order_type="LMT", limit_price=16.91,
                    stop_price=None),
        _open_order(ib_order_id=1077452803, symbol="VALE", action="SELL",
                    quantity=2586, order_type="STP", stop_price=15.64),
        _open_order(ib_order_id=1077452766, symbol="VALE", action="SELL",
                    quantity=2593, order_type="LMT", limit_price=16.91,
                    stop_price=None),
        _open_order(ib_order_id=1077452767, symbol="VALE", action="SELL",
                    quantity=2593, order_type="STP", stop_price=15.64),
        _open_order(ib_order_id=1077452742, symbol="NCLH", action="SELL",
                    quantity=2422, order_type="LMT", limit_price=18.75,
                    stop_price=None),
        _open_order(ib_order_id=1077452743, symbol="NCLH", action="SELL",
                    quantity=2422, order_type="STP", stop_price=16.80),
        _open_order(ib_order_id=1077452697, symbol="ELV", action="SELL",
                    quantity=113, order_type="LMT", limit_price=388.48,
                    stop_price=None),
        _open_order(ib_order_id=1077452698, symbol="ELV", action="SELL",
                    quantity=113, order_type="STP", stop_price=366.18),
    ]
    verdicts = classify_open_orders(
        ib_open_orders=yesterdays_orders,
        ib_positions=[],
        bot_trades=[],
    )
    assert len(verdicts) == 10
    assert all(v.verdict == VERDICT_NAKED_NO_POSITION for v in verdicts)
    syms = {v.symbol for v in verdicts}
    assert syms == {"NXPI", "VALE", "NCLH", "ELV"}


# ════════════════════════════════════════════════════════════════════════
# Cancellation gate — refuses unsafe verdicts
# ════════════════════════════════════════════════════════════════════════


def test_cancel_helper_refuses_tracked_verdicts():
    """`mismatched_size` and `tracked` must NEVER be auto-cancelled."""
    from services.orphan_gtc_reconciler import (
        OrderVerdict,
        VERDICT_MISMATCHED_SIZE,
        VERDICT_TRACKED,
        cancel_orphan_gtc_orders,
    )
    safe_inputs = [
        OrderVerdict(
            ib_order_id=1, perm_id=None, symbol="X", action="SELL",
            quantity=10, order_type="STP", limit_price=None,
            stop_price=50.0, time_in_force="GTC", status="PreSubmitted",
            verdict=VERDICT_MISMATCHED_SIZE,
        ),
        OrderVerdict(
            ib_order_id=2, perm_id=None, symbol="X", action="SELL",
            quantity=10, order_type="STP", limit_price=None,
            stop_price=50.0, time_in_force="GTC", status="PreSubmitted",
            verdict=VERDICT_TRACKED,
        ),
    ]
    summary = asyncio.run(cancel_orphan_gtc_orders(verdicts_to_cancel=safe_inputs))
    assert summary["cancelled"] == []
    assert len(summary["refused_unsafe"]) == 2
    assert {r["verdict"] for r in summary["refused_unsafe"]} == {
        VERDICT_MISMATCHED_SIZE, VERDICT_TRACKED
    }


def test_cancel_helper_uses_ib_direct_for_safe_verdicts():
    """Safe verdicts route through ib_direct.cancel_order."""
    from services.orphan_gtc_reconciler import (
        OrderVerdict,
        VERDICT_NAKED_NO_POSITION,
        cancel_orphan_gtc_orders,
    )
    naked = OrderVerdict(
        ib_order_id=42, perm_id=None, symbol="NXPI", action="SELL",
        quantity=192, order_type="STP", limit_price=None, stop_price=287.0,
        time_in_force="GTC", status="PreSubmitted",
        verdict=VERDICT_NAKED_NO_POSITION,
    )
    fake_ib = MagicMock()
    fake_ib.ensure_connected = AsyncMock(return_value=True)
    fake_ib.cancel_order = AsyncMock(return_value={"success": True, "order_id": 42})

    with patch(
        "services.ib_direct_service.get_ib_direct_service",
        return_value=fake_ib,
    ):
        summary = asyncio.run(cancel_orphan_gtc_orders(verdicts_to_cancel=[naked]))

    assert len(summary["cancelled"]) == 1
    assert summary["cancelled"][0]["ib_order_id"] == 42
    assert summary["errors"] == []
    fake_ib.cancel_order.assert_awaited_once_with(42)


def test_cancel_helper_handles_ib_disconnected_gracefully():
    """If IB-direct can't connect, return error, do NOT crash."""
    from services.orphan_gtc_reconciler import (
        OrderVerdict,
        VERDICT_NAKED_NO_POSITION,
        cancel_orphan_gtc_orders,
    )
    naked = OrderVerdict(
        ib_order_id=42, perm_id=None, symbol="NXPI", action="SELL",
        quantity=192, order_type="STP", limit_price=None, stop_price=287.0,
        time_in_force="GTC", status="PreSubmitted",
        verdict=VERDICT_NAKED_NO_POSITION,
    )
    fake_ib = MagicMock()
    fake_ib.ensure_connected = AsyncMock(return_value=False)

    with patch(
        "services.ib_direct_service.get_ib_direct_service",
        return_value=fake_ib,
    ):
        summary = asyncio.run(cancel_orphan_gtc_orders(verdicts_to_cancel=[naked]))

    # v19.34.89 — with ib_direct disconnected the helper falls through to
    # the pusher cancel QUEUE instead of erroring out. The leg reports
    # via="cancel_queue" with a pending queue status.
    assert len(summary["cancelled"]) == 1
    assert summary["cancelled"][0]["via"] == "cancel_queue"
    assert summary["errors"] == []


# ════════════════════════════════════════════════════════════════════════
# Orchestrator-level audit (mocked data sources)
# ════════════════════════════════════════════════════════════════════════


def test_audit_returns_failure_envelope_when_ib_unreachable():
    """Reconciler must NEVER raise — returns success=False instead."""
    from services.orphan_gtc_reconciler import audit_orphan_gtc_orders

    # Patch both fetch tiers to return None — simulating a fully-unreachable
    # IB Gateway.
    with patch(
        "services.orphan_gtc_reconciler._fetch_ib_open_orders",
        new=AsyncMock(return_value=(None, {"tier": "none", "ok": False})),
    ):
        result = asyncio.run(audit_orphan_gtc_orders(bot=None))

    assert result["success"] is False
    assert result["reason"] == "ib_orders_unavailable"
    assert result["verdicts"] == []


def test_audit_happy_path_combines_all_sources():
    """Orchestrator wires open_orders + positions + bot_trades correctly."""
    from services.orphan_gtc_reconciler import audit_orphan_gtc_orders, VERDICT_NAKED_NO_POSITION

    fake_orders = [_open_order(
        ib_order_id=99, symbol="NXPI", action="SELL", quantity=192,
        order_type="STP", stop_price=287.02,
    )]
    with patch(
        "services.orphan_gtc_reconciler._fetch_ib_open_orders",
        new=AsyncMock(return_value=(fake_orders, {"tier": "ib_direct", "ok": True})),
    ), patch(
        # M0c — patch the ASYNC positions fetcher (the one the orchestrator
        # actually calls) and mark the pusher feed FRESH so the empty
        # positions read is trustworthy (bot tracks no trades → genuine
        # naked zombie must still classify).
        "services.orphan_gtc_reconciler._fetch_ib_positions_async",
        new=AsyncMock(return_value=(
            [], {"tier": "pusher_snapshot", "ok": True, "pusher_connected": True},
        )),
    ), patch(
        "services.orphan_gtc_reconciler._fetch_bot_trades",
        return_value=([], {"tier": "mongo_bot_trades", "ok": True}),
    ):
        result = asyncio.run(audit_orphan_gtc_orders(bot=None))

    assert result["success"] is True
    assert result["summary"][VERDICT_NAKED_NO_POSITION] == 1
    assert len(result["verdicts"]) == 1
    assert result["verdicts"][0]["symbol"] == "NXPI"
