"""v19.34.153 — First-tick bracket reaper regression suite.

Pins the 2026-05-13 incident fix:
  The operator manually flattened 10 positions in TWS at ~3:57 PM ET.
  Bot's OCA brackets were NOT cancelled (OCA links stop↔target only,
  not stop↔manual-MKT-close). Around 3:58 PM the orphan bracket STOPS
  fired, creating REVERSE positions at IB for all 10 symbols. Bot's
  phantom-share sweep noticed at 3:59 PM and closed the bot_trade
  records, but didn't address the IB reverse positions → operator
  rolled overnight holding the inverse of every intended trade.

v19.34.153 fix: when `_close_drift_trades_zero` detection fires
(bot=OPEN, IB=0), IMMEDIATELY cancel every IB order tied to that
symbol BEFORE the existing 2-tick gate. Eliminates the 30s window
in which orphan brackets can fire.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _StubTrade:
    def __init__(
        self, symbol="X", entry_oid=1001, stop_oid=1002,
        target_oid=1003, target_oids=None,
    ):
        self.id = f"t-{symbol}"
        self.symbol = symbol
        self.entry_order_id = entry_oid
        self.stop_order_id = stop_oid
        self.target_order_id = target_oid
        self.target_order_ids = list(target_oids or [])


@pytest.mark.asyncio
async def test_reaper_collects_all_tracked_order_ids(monkeypatch):
    """The reaper must collect entry_order_id, stop_order_id, AND
    target_order_id from every tracked trade."""
    from services.position_reconciler import PositionReconciler

    pr = PositionReconciler()
    trades = [_StubTrade("AAPL", entry_oid=100, stop_oid=200, target_oid=300)]

    cancelled = []

    async def _fake_cancel(oid):
        cancelled.append(oid)
        return True

    mock_ib = SimpleNamespace(cancel_order=_fake_cancel)
    with patch("routers.ib._ib_service", mock_ib):
        with patch(
            "services.orphan_gtc_reconciler._fetch_ib_open_orders",
            new=AsyncMock(return_value=([], {})),
        ):
            out = await pr._cancel_orders_for_symbol_v153(
                sym="AAPL", bot_trades=trades, drift_kind="zero",
            )

    assert set(cancelled) == {100, 200, 300}
    assert set(out["cancelled"]) == {100, 200, 300}
    assert out["source_counts"]["tracked_entry"] == 1
    assert out["source_counts"]["tracked_stop"] == 1
    assert out["source_counts"]["tracked_target"] == 1


@pytest.mark.asyncio
async def test_reaper_handles_multiple_target_order_ids():
    """v19.34.x scaled-out trades have a target_order_ids LIST.
    The reaper must cancel every one of them."""
    from services.position_reconciler import PositionReconciler

    pr = PositionReconciler()
    trades = [_StubTrade(
        "TSLA", entry_oid=10, stop_oid=20,
        target_oid=None, target_oids=[30, 31, 32],
    )]

    cancelled = []

    async def _fake_cancel(oid):
        cancelled.append(oid)
        return True

    mock_ib = SimpleNamespace(cancel_order=_fake_cancel)
    with patch("routers.ib._ib_service", mock_ib):
        with patch(
            "services.orphan_gtc_reconciler._fetch_ib_open_orders",
            new=AsyncMock(return_value=([], {})),
        ):
            await pr._cancel_orders_for_symbol_v153(
                sym="TSLA", bot_trades=trades, drift_kind="zero",
            )

    assert set(cancelled) == {10, 20, 30, 31, 32}


@pytest.mark.asyncio
async def test_reaper_safety_net_catches_untracked_orders():
    """If an IB order is open for the symbol but NOT on the bot_trade
    object (placed via a non-standard path), the safety-net scan
    must still find and cancel it."""
    from services.position_reconciler import PositionReconciler

    pr = PositionReconciler()
    trades = [_StubTrade(
        "NVDA", entry_oid=1, stop_oid=2, target_oid=3,
    )]

    # IB has the 3 tracked orders + 1 mystery order #99.
    safety_net_orders = [
        {"symbol": "NVDA", "ib_order_id": 1, "status": "Submitted"},
        {"symbol": "NVDA", "ib_order_id": 2, "status": "Submitted"},
        {"symbol": "NVDA", "ib_order_id": 3, "status": "Submitted"},
        {"symbol": "NVDA", "ib_order_id": 99, "status": "Submitted"},
        # Different symbol — must NOT be cancelled.
        {"symbol": "AAPL", "ib_order_id": 500, "status": "Submitted"},
    ]

    cancelled = []

    async def _fake_cancel(oid):
        cancelled.append(oid)
        return True

    mock_ib = SimpleNamespace(cancel_order=_fake_cancel)
    with patch("routers.ib._ib_service", mock_ib):
        with patch(
            "services.orphan_gtc_reconciler._fetch_ib_open_orders",
            new=AsyncMock(return_value=(safety_net_orders, {})),
        ):
            out = await pr._cancel_orders_for_symbol_v153(
                sym="NVDA", bot_trades=trades, drift_kind="zero",
            )

    assert set(cancelled) == {1, 2, 3, 99}, (
        "must cancel all 3 tracked + the untracked #99 on NVDA, "
        "but NOT touch AAPL's #500"
    )
    assert 500 not in cancelled
    assert out["source_counts"]["open_orders_safety_net"] == 1


@pytest.mark.asyncio
async def test_reaper_skips_zero_and_invalid_ids():
    """Empty / None / non-numeric IDs (e.g. SIM-STOP-<uuid> from
    paper mode) MUST be silently skipped, not raise."""
    from services.position_reconciler import PositionReconciler

    pr = PositionReconciler()
    trade = _StubTrade("X", entry_oid=None, stop_oid="SIM-STOP-abc", target_oid=0)
    cancelled = []

    async def _fake_cancel(oid):
        cancelled.append(oid)
        return True

    mock_ib = SimpleNamespace(cancel_order=_fake_cancel)
    with patch("routers.ib._ib_service", mock_ib):
        with patch(
            "services.orphan_gtc_reconciler._fetch_ib_open_orders",
            new=AsyncMock(return_value=([], {})),
        ):
            out = await pr._cancel_orders_for_symbol_v153(
                sym="X", bot_trades=[trade], drift_kind="zero",
            )

    assert cancelled == []
    assert out["cancelled"] == []


@pytest.mark.asyncio
async def test_reaper_failure_is_non_fatal():
    """Individual cancel exceptions must NOT propagate — they go into
    the `errors` list but the reaper continues with the others."""
    from services.position_reconciler import PositionReconciler

    pr = PositionReconciler()
    trades = [_StubTrade("ITT", entry_oid=10, stop_oid=20, target_oid=30)]

    async def _fake_cancel(oid):
        if oid == 20:
            raise RuntimeError("IB connection dropped")
        return True

    mock_ib = SimpleNamespace(cancel_order=_fake_cancel)
    with patch("routers.ib._ib_service", mock_ib):
        with patch(
            "services.orphan_gtc_reconciler._fetch_ib_open_orders",
            new=AsyncMock(return_value=([], {})),
        ):
            out = await pr._cancel_orders_for_symbol_v153(
                sym="ITT", bot_trades=trades, drift_kind="zero",
            )

    assert set(out["cancelled"]) == {10, 30}
    assert len(out["errors"]) == 1
    assert out["errors"][0]["id"] == 20
    assert "IB connection dropped" in out["errors"][0]["error"]


@pytest.mark.asyncio
async def test_reaper_handles_no_orders_gracefully():
    """A trade with zero order IDs (e.g., a paper-mode SIM trade
    with all SIM-* IDs) must early-return without errors."""
    from services.position_reconciler import PositionReconciler

    pr = PositionReconciler()
    trade = SimpleNamespace(
        id="t-1", symbol="X",
        entry_order_id=None, stop_order_id=None,
        target_order_id=None, target_order_ids=[],
    )

    with patch(
        "services.orphan_gtc_reconciler._fetch_ib_open_orders",
        new=AsyncMock(return_value=([], {})),
    ):
        out = await pr._cancel_orders_for_symbol_v153(
            sym="X", bot_trades=[trade], drift_kind="zero",
        )

    assert out["cancelled"] == []
    assert out["errors"] == []


@pytest.mark.asyncio
async def test_reaper_emits_stream_event():
    """V5 BracketReaperPill listens for this event to update its
    counter. Must fire whenever any orders are cancelled."""
    from services.position_reconciler import PositionReconciler

    pr = PositionReconciler()
    trades = [_StubTrade("STZ", entry_oid=42, stop_oid=None, target_oid=None)]

    captured = []

    async def _capture(ev):
        captured.append(ev)

    mock_ib = SimpleNamespace(cancel_order=AsyncMock(return_value=True))
    with patch("routers.ib._ib_service", mock_ib):
        with patch(
            "services.orphan_gtc_reconciler._fetch_ib_open_orders",
            new=AsyncMock(return_value=([], {})),
        ):
            with patch(
                "services.sentcom_service.emit_stream_event",
                new=_capture,
            ):
                await pr._cancel_orders_for_symbol_v153(
                    sym="STZ", bot_trades=trades, drift_kind="zero",
                )

    assert len(captured) == 1
    e = captured[0]
    assert e["event"] == "first_tick_bracket_reaper_v19_34_153"
    assert e["symbol"] == "STZ"
    assert e["metadata"]["cancelled_count"] == 1


@pytest.mark.asyncio
async def test_reaper_no_event_when_nothing_to_cancel():
    """Don't spam the stream when there are no orders to cancel."""
    from services.position_reconciler import PositionReconciler

    pr = PositionReconciler()
    trade = SimpleNamespace(
        id="t-1", symbol="X",
        entry_order_id=None, stop_order_id=None,
        target_order_id=None, target_order_ids=[],
    )

    captured = []

    async def _capture(ev):
        captured.append(ev)

    with patch(
        "services.orphan_gtc_reconciler._fetch_ib_open_orders",
        new=AsyncMock(return_value=([], {})),
    ):
        with patch(
            "services.sentcom_service.emit_stream_event", new=_capture,
        ):
            await pr._cancel_orders_for_symbol_v153(
                sym="X", bot_trades=[trade], drift_kind="zero",
            )

    assert captured == []
