"""
v19.30.9 (2026-05-02) — Degraded-mode UI fixes + cancel-all-pending-orders.

Three independent surface bugs were filed by the operator on the post-
v19.30.8 deploy:

  1. `/api/ib/account/positions` returned blanket 503 whenever the
     direct IB Gateway connection was unavailable, even though the
     Windows pusher was healthily delivering positions via
     `_pushed_ib_data["positions"]`. The V5 Top Movers / positions
     panels rendered "Failed to fetch".
  2. "Bar fetch failed" on the SPY chart — root-cause was a sync
     pymongo `find().sort()` cursor materialisation inside
     `hybrid_data_service._get_from_cache` that could tie the event
     loop up long enough for the 30s axios timeout on the frontend
     to fire. Same wedge class as v19.30.1 / v19.30.2 / v19.30.7,
     different call site.
  3. No pre-open safety endpoint to cancel pending GTC bracket
     orders before the bell. If an operator manually flattened a
     position via TWS, the IB-side OCA stop/target legs lingered
     and could trigger naked shorts on the next entry.

The tests below pin each fix at source level so a future refactor
can't silently drop them.

NOTE: These are pure unit tests (no IB, no live MongoDB, no DGX
hardware). They run inside the standard pytest container.
"""
from __future__ import annotations

import asyncio
import inspect
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── Fix 1: /api/ib/account/positions degraded-mode fallback ─────────────────


def test_positions_endpoint_falls_back_to_pushed_data_when_ib_unavailable():
    """ConnectionError from direct IB must NOT 503 — fall back to pusher.

    The Spark backend frequently boots in degraded mode (IB Gateway
    TimeoutError on initial qualify). Pre-v19.30.9 the positions
    endpoint raised 503 in that state, breaking the V5 HUD. The fix
    catches ConnectionError and returns the pusher snapshot with a
    `degraded: True` flag.
    """
    from routers import ib as ib_module

    fake_pushed = {
        "connected": True,
        "positions": [
            {"symbol": "SBUX", "qty": 100, "avg_cost": 95.50},
            {"symbol": "SOFI", "qty": 200, "avg_cost": 18.75},
        ],
    }
    fake_ib = MagicMock()
    fake_ib.get_positions = AsyncMock(side_effect=ConnectionError("ib gateway down"))

    with patch.object(ib_module, "_pushed_ib_data", fake_pushed), \
         patch.object(ib_module, "_ib_service", fake_ib):
        result = asyncio.run(ib_module.get_positions())

    assert result["count"] == 2
    assert result["degraded"] is True
    assert result["source"] == "pusher"
    assert result["positions"][0]["symbol"] == "SBUX"
    assert "ib_gateway_unavailable" in result["reason"]


def test_positions_endpoint_uses_ib_direct_when_connected():
    """Happy path: when IB is reachable, return its data and mark
    degraded=False so the UI doesn't show a stale badge.
    """
    from routers import ib as ib_module

    fake_ib = MagicMock()
    fake_ib.get_positions = AsyncMock(return_value=[
        {"symbol": "SPY", "qty": 50, "avg_cost": 580.0},
    ])

    with patch.object(ib_module, "_ib_service", fake_ib):
        result = asyncio.run(ib_module.get_positions())

    assert result["count"] == 1
    assert result["degraded"] is False
    assert result["source"] == "ib_direct"


def test_positions_endpoint_handles_no_ib_service_gracefully():
    """If _ib_service is None at all (initialisation race), still
    return pushed positions instead of crashing the endpoint.
    """
    from routers import ib as ib_module

    fake_pushed = {"connected": False, "positions": []}

    with patch.object(ib_module, "_pushed_ib_data", fake_pushed), \
         patch.object(ib_module, "_ib_service", None):
        result = asyncio.run(ib_module.get_positions())

    assert result["count"] == 0
    assert result["degraded"] is True
    assert result["source"] == "pusher_stale"
    assert result["reason"] == "ib_service_not_initialized"


def test_account_summary_alt_falls_back_to_pushed_data():
    """Same degraded-mode pattern for the async ALT account summary
    handler. The PRIMARY `/account/summary` route resolves to a sync
    handler defined earlier in `routers/ib.py` that already reads
    pushed data; this async variant is the defensive safety net should
    registration order ever change.
    """
    from routers import ib as ib_module

    fake_pushed = {
        "connected": True,
        "account": {
            "NetLiquidation": "108543.21",
            "BuyingPower": "215000.00",
            "AvailableFunds": "32100.00",
            "TotalCashValue": "12000.00",
            "RealizedPnL": "0.0",
            "UnrealizedPnL": "1234.56",
            "AccountCode": "DU1234567",
        },
    }
    fake_ib = MagicMock()
    fake_ib.get_account_summary = AsyncMock(side_effect=ConnectionError("ib down"))

    with patch.object(ib_module, "_pushed_ib_data", fake_pushed), \
         patch.object(ib_module, "_ib_service", fake_ib):
        result = asyncio.run(ib_module.get_account_summary_alt())

    assert result["degraded"] is True
    assert result["source"] == "pusher"
    assert pytest.approx(result["net_liquidation"]) == 108543.21
    assert pytest.approx(result["buying_power"]) == 215000.0
    assert pytest.approx(result["unrealized_pnl"]) == 1234.56
    assert result["account_id"] == "DU1234567"


# ─── Fix 2: hybrid_data_service async-safety pin ─────────────────────────────


def test_get_from_cache_offloads_sync_pymongo_to_to_thread():
    """The sync pymongo `find().sort()` cursor materialisation MUST run
    via `asyncio.to_thread` so the event loop stays responsive even
    when the bars collection has millions of rows.

    Source-level pin: a future contributor can't silently re-introduce
    the bare `list(self._bars_collection.find(...))` pattern that was
    flagged in the v19.30 audit and very likely caused the
    "Bar fetch failed" UI symptom on the SPY chart.
    """
    import services.hybrid_data_service as mod
    src = inspect.getsource(mod.HybridDataService._get_from_cache)
    # Must NOT do bare list(self._bars_collection.find(...)) at top level
    forbidden = "bars = list(self._bars_collection.find("
    assert forbidden not in src, (
        "Source-level regression: bare sync pymongo find() reintroduced "
        "in HybridDataService._get_from_cache. Wrap in asyncio.to_thread."
    )
    # Must call asyncio.to_thread at least twice (window query + stale fallback)
    assert src.count("asyncio.to_thread(") >= 2, (
        "_get_from_cache should offload BOTH the window query AND the "
        "stale-fallback query via asyncio.to_thread."
    )


def test_cache_bars_offloads_sync_upserts_to_to_thread():
    """The per-bar sync `update_one(..., upsert=True)` loop in
    `_cache_bars` must run inside `asyncio.to_thread` — N round-trips
    inside a coroutine is exactly the wedge profile v19.30 was built
    to prevent.
    """
    import services.hybrid_data_service as mod
    src = inspect.getsource(mod.HybridDataService._cache_bars)
    assert "asyncio.to_thread(" in src, (
        "_cache_bars must wrap its sync upsert loop in asyncio.to_thread"
    )


@pytest.mark.asyncio
async def test_get_from_cache_returns_bars_via_to_thread_path():
    """Functional smoke: with a fake collection, the cache helper
    returns bars via the to_thread path without raising.
    """
    from services.hybrid_data_service import HybridDataService
    from datetime import datetime, timezone, timedelta

    svc = HybridDataService.__new__(HybridDataService)
    svc.TIMEFRAMES = {"1day": {"ib_bar_size": "1 day"}}

    fake_bars = [
        {"symbol": "SPY", "bar_size": "1 day", "date": "2026-04-30",
         "open": 580.0, "high": 585.0, "low": 578.0, "close": 583.0, "volume": 50000000},
    ]

    class _FakeCursor:
        def __init__(self, rows: List[dict]):
            self._rows = rows

        def sort(self, *args, **kwargs):
            return self

        def limit(self, _n):
            return self

        def __iter__(self):
            return iter(self._rows)

    fake_coll = MagicMock()
    fake_coll.find = MagicMock(return_value=_FakeCursor(fake_bars))
    svc._bars_collection = fake_coll

    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=5)
    out = await svc._get_from_cache("SPY", "1day", start_dt, end_dt)

    assert out["success"] is True
    assert len(out["bars"]) == 1
    assert out["bars"][0]["symbol"] == "SPY"


# ─── Fix 3: POST /api/trading-bot/cancel-all-pending-orders ──────────────────


def test_cancel_all_pending_orders_requires_confirm_token():
    """Defense-in-depth: missing or wrong confirm token must 400."""
    from routers import trading_bot as tb_module
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        asyncio.run(tb_module.cancel_all_pending_orders(
            tb_module.CancelAllPendingRequest(confirm=None)
        ))
    assert exc.value.status_code == 400
    assert "CANCEL_ALL_PENDING" in exc.value.detail

    with pytest.raises(HTTPException) as exc:
        asyncio.run(tb_module.cancel_all_pending_orders(
            tb_module.CancelAllPendingRequest(confirm="wrong-token")
        ))
    assert exc.value.status_code == 400


def test_cancel_all_pending_orders_drains_queue():
    """When confirm is correct, every pending+claimed row in the
    Mongo order_queue must be cancelled. Symbol filter must scope.
    """
    from routers import trading_bot as tb_module
    from services import order_queue_service as oq_module

    fake_queue_service = MagicMock()
    fake_queue_service.get_orders_by_status.side_effect = lambda status: {
        "pending": [
            {"order_id": "o1", "symbol": "SPY"},
            {"order_id": "o2", "symbol": "SOFI"},
        ],
        "claimed": [
            {"order_id": "o3", "symbol": "SBUX"},
        ],
    }.get(status, [])
    fake_queue_service.cancel_order.return_value = True

    with patch.object(oq_module, "get_order_queue_service", return_value=fake_queue_service):
        result = asyncio.run(tb_module.cancel_all_pending_orders(
            tb_module.CancelAllPendingRequest(confirm="CANCEL_ALL_PENDING")
        ))

    assert result["success"] is True
    assert result["queue_cancelled"] == 3
    assert fake_queue_service.cancel_order.call_count == 3


def test_cancel_all_pending_orders_dry_run_does_not_mutate():
    """dry_run=True must count rows without calling cancel_order."""
    from routers import trading_bot as tb_module
    from services import order_queue_service as oq_module

    fake_queue_service = MagicMock()
    fake_queue_service.get_orders_by_status.side_effect = lambda status: (
        [{"order_id": "o1", "symbol": "SPY"}] if status == "pending" else []
    )

    with patch.object(oq_module, "get_order_queue_service", return_value=fake_queue_service):
        result = asyncio.run(tb_module.cancel_all_pending_orders(
            tb_module.CancelAllPendingRequest(confirm="CANCEL_ALL_PENDING", dry_run=True)
        ))

    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["queue_cancelled"] == 1
    fake_queue_service.cancel_order.assert_not_called()


def test_cancel_all_pending_orders_symbol_filter():
    """`symbols=[...]` must scope which queue rows are cancelled.

    Operator's prime use case: SOFI bracket misbehaving, kill only
    SOFI's pending orders without nuking SPY/SBUX.
    """
    from routers import trading_bot as tb_module
    from services import order_queue_service as oq_module

    fake_queue_service = MagicMock()
    fake_queue_service.get_orders_by_status.side_effect = lambda status: (
        [
            {"order_id": "o1", "symbol": "SPY"},
            {"order_id": "o2", "symbol": "SOFI"},
            {"order_id": "o3", "symbol": "SBUX"},
        ] if status == "pending" else []
    )
    fake_queue_service.cancel_order.return_value = True

    with patch.object(oq_module, "get_order_queue_service", return_value=fake_queue_service):
        result = asyncio.run(tb_module.cancel_all_pending_orders(
            tb_module.CancelAllPendingRequest(
                confirm="CANCEL_ALL_PENDING",
                symbols=["sofi"],  # case-insensitive
            )
        ))

    assert result["queue_cancelled"] == 1
    assert result["queue_skipped"] == 2
    fake_queue_service.cancel_order.assert_called_once_with("o2")


def test_cancel_all_pending_orders_handles_ib_unavailable_gracefully():
    """When direct IB is None, response must surface
    `ib_unavailable: True` instead of 503'ing the whole endpoint —
    so the queue layer still drained even in degraded mode.
    """
    from routers import trading_bot as tb_module
    from routers import ib as ib_module
    from services import order_queue_service as oq_module

    fake_queue_service = MagicMock()
    fake_queue_service.get_orders_by_status.return_value = []
    fake_queue_service.cancel_order.return_value = True

    with patch.object(oq_module, "get_order_queue_service", return_value=fake_queue_service), \
         patch.object(ib_module, "_ib_service", None):
        result = asyncio.run(tb_module.cancel_all_pending_orders(
            tb_module.CancelAllPendingRequest(confirm="CANCEL_ALL_PENDING")
        ))

    assert result["success"] is True
    assert result["ib_unavailable"] is True
    assert result["ib_error"] == "ib_service_not_initialized"
    assert result["ib_cancelled"] == 0


def test_cancel_all_pending_orders_cancels_ib_open_orders_when_connected():
    """When direct IB is reachable, fetch open orders and cancel each."""
    from routers import trading_bot as tb_module
    from routers import ib as ib_module
    from services import order_queue_service as oq_module

    fake_queue_service = MagicMock()
    fake_queue_service.get_orders_by_status.return_value = []

    fake_ib = MagicMock()
    fake_ib.get_open_orders = AsyncMock(return_value=[
        {"order_id": 1001, "symbol": "SPY"},
        {"order_id": 1002, "symbol": "SOFI"},
    ])
    fake_ib.cancel_order = AsyncMock(return_value=True)

    with patch.object(oq_module, "get_order_queue_service", return_value=fake_queue_service), \
         patch.object(ib_module, "_ib_service", fake_ib):
        result = asyncio.run(tb_module.cancel_all_pending_orders(
            tb_module.CancelAllPendingRequest(confirm="CANCEL_ALL_PENDING")
        ))

    assert result["success"] is True
    assert result["ib_cancelled"] == 2
    assert result["ib_unavailable"] is False
    assert fake_ib.cancel_order.call_count == 2
    fake_ib.cancel_order.assert_any_call(1001)
    fake_ib.cancel_order.assert_any_call(1002)


def test_cancel_all_pending_orders_source_level_async_safety_pin():
    """The handler must wrap the queue drain in `asyncio.to_thread`.

    Without this, every row in the order_queue (often 50+) does a
    sync `update_one` round-trip inline on the event loop — exactly
    the wedge pattern v19.30.x exists to prevent.
    """
    from routers import trading_bot as tb_module
    src = inspect.getsource(tb_module.cancel_all_pending_orders)
    assert "asyncio.to_thread(" in src, (
        "cancel_all_pending_orders must use asyncio.to_thread for the "
        "Mongo order_queue drain (avoid event-loop wedge under load)."
    )


# ─── Pytest config ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _cleanup_event_loop():
    """Tests use plain asyncio.run() — no extra event-loop hygiene needed."""
    yield
