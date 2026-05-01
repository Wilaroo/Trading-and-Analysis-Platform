"""
v19.30.9 + v19.30.10 (2026-05-02) — Pusher-source-of-truth simplification +
async-safety hardening + cancel-all-pending-orders.

Operator pushback: "why do we need degraded mode at all? didn't yesterday's
chart change fix this?". Two distinct points addressed:

  1. The chart fix (v19.25 cache + tail-polling) was unrelated to the
     positions 503. The 503 was a separate bug: `/account/positions`
     was calling a dead `_ib_service.get_positions()` path that has
     never worked in this deployment (the DGX backend has no direct
     IB Gateway connection — the Windows pusher does).

  2. The "try direct IB → fall back to pusher" pattern was theatre.
     v19.30.10 simplifies to a clean two-tier read: in-memory
     `_pushed_ib_data["positions"]` first, then the Mongo
     `ib_live_snapshot.current` collection (which the push-data
     handler writes on every push) as a post-restart safety net.
     No "degraded" flag, no doomed direct-IB call.

Plus the async-safety pin on `_get_from_cache` / `_cache_bars` from
v19.30.9 is preserved (those WERE the actual cause of "Bar fetch
failed" via 30s axios timeout), and the new
`POST /api/trading-bot/cancel-all-pending-orders` endpoint stays
unchanged.

NOTE: These are pure unit tests — no IB, no live MongoDB, no DGX
hardware. They run inside the standard pytest container.
"""
from __future__ import annotations

import asyncio
import inspect
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── Fix 1: /api/ib/account/positions — pusher source of truth ───────────────


def test_positions_endpoint_returns_in_memory_pusher_data():
    """Hot path: when `_pushed_ib_data["positions"]` is populated,
    the endpoint returns it immediately as `source: "memory"` without
    hitting Mongo or any IB direct call.
    """
    from routers import ib as ib_module

    fake_pushed = {
        "last_update": "2026-05-02T18:00:00+00:00",
        "positions": [
            {"symbol": "SBUX", "qty": 100, "avg_cost": 95.50},
            {"symbol": "SOFI", "qty": 200, "avg_cost": 18.75},
        ],
    }

    with patch.object(ib_module, "_pushed_ib_data", fake_pushed):
        result = asyncio.run(ib_module.get_positions())

    assert result["count"] == 2
    assert result["source"] == "memory"
    assert result["last_update"] == "2026-05-02T18:00:00+00:00"
    assert result["positions"][0]["symbol"] == "SBUX"
    # `degraded` flag intentionally removed (v19.30.10)
    assert "degraded" not in result
    assert "reason" not in result


def test_positions_endpoint_falls_back_to_mongo_snapshot():
    """When in-memory `_pushed_ib_data["positions"]` is empty (the
    classic post-backend-restart window before the pusher's first push
    has landed), fall back to the Mongo `ib_live_snapshot.current`
    document. This collection is written by `/api/ib/push-data` on
    every push so it survives backend restarts.
    """
    from routers import ib as ib_module

    fake_pushed = {"last_update": None, "positions": []}

    fake_db = MagicMock()
    fake_db["ib_live_snapshot"].find_one.return_value = {
        "positions": [{"symbol": "SPY", "qty": 50, "avg_cost": 580.0}],
        "last_update": "2026-05-02T17:55:00+00:00",
    }

    with patch.object(ib_module, "_pushed_ib_data", fake_pushed), \
         patch("database.get_database", return_value=fake_db):
        result = asyncio.run(ib_module.get_positions())

    assert result["count"] == 1
    assert result["source"] == "mongo_snapshot"
    assert result["last_update"] == "2026-05-02T17:55:00+00:00"
    assert result["positions"][0]["symbol"] == "SPY"


def test_positions_endpoint_returns_empty_when_nothing_available():
    """Both in-memory and Mongo empty → return clean empty payload
    with `source: "empty"` so the UI can render "no positions" state
    without showing an error banner.
    """
    from routers import ib as ib_module

    fake_pushed = {"last_update": None, "positions": []}

    fake_db = MagicMock()
    fake_db["ib_live_snapshot"].find_one.return_value = None

    with patch.object(ib_module, "_pushed_ib_data", fake_pushed), \
         patch("database.get_database", return_value=fake_db):
        result = asyncio.run(ib_module.get_positions())

    assert result["count"] == 0
    assert result["source"] == "empty"
    assert result["positions"] == []
    assert result["last_update"] is None


def test_positions_endpoint_handles_mongo_error_gracefully():
    """If the Mongo read raises (db down, schema mismatch, etc.),
    swallow and return empty — never 503 the operator's HUD.
    """
    from routers import ib as ib_module

    fake_pushed = {"last_update": None, "positions": []}

    with patch.object(ib_module, "_pushed_ib_data", fake_pushed), \
         patch("database.get_database", side_effect=Exception("db unreachable")):
        result = asyncio.run(ib_module.get_positions())

    assert result["count"] == 0
    assert result["source"] == "empty"


def test_positions_endpoint_no_longer_calls_direct_ib():
    """Source-level pin: the endpoint must NOT touch
    `_ib_service.get_positions()`. The whole point of v19.30.10 is
    that the DGX backend never connects directly to IB Gateway, so
    that call was always a dead path. A future contributor can't
    silently re-introduce it.
    """
    from routers import ib as ib_module
    src = inspect.getsource(ib_module.get_positions)
    assert "_ib_service.get_positions" not in src, (
        "v19.30.10 simplification: get_positions must read pusher "
        "data unconditionally, not call the dead direct-IB path."
    )
    assert "ConnectionError" not in src, (
        "ConnectionError handling implies direct-IB attempts. The "
        "endpoint should never raise on IB Gateway state."
    )
    # Must use asyncio.to_thread for the Mongo find_one (event-loop
    # safety per v19.30 audit contract).
    assert "asyncio.to_thread(" in src, (
        "Mongo find_one in async handler must run via asyncio.to_thread"
    )


# ─── Fix 2: hybrid_data_service async-safety pin (preserved from v19.30.9) ───


def test_get_from_cache_offloads_sync_pymongo_to_to_thread():
    """The sync pymongo `find().sort()` cursor materialisation MUST run
    via `asyncio.to_thread` so the event loop stays responsive even
    when the bars collection has millions of rows.

    Source-level pin: this WAS the actual cause of "Bar fetch failed"
    on the V5 chart panel — slow Mongo round-trip ties up the loop
    long enough for the 30s axios timeout on the frontend to fire.
    """
    import services.hybrid_data_service as mod
    src = inspect.getsource(mod.HybridDataService._get_from_cache)
    forbidden = "bars = list(self._bars_collection.find("
    assert forbidden not in src, (
        "Source-level regression: bare sync pymongo find() reintroduced "
        "in HybridDataService._get_from_cache. Wrap in asyncio.to_thread."
    )
    assert src.count("asyncio.to_thread(") >= 2, (
        "_get_from_cache should offload BOTH the window query AND the "
        "stale-fallback query via asyncio.to_thread."
    )


def test_cache_bars_offloads_sync_upserts_to_to_thread():
    """The per-bar sync `update_one(..., upsert=True)` loop in
    `_cache_bars` must run inside `asyncio.to_thread`.
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
    """`symbols=[...]` must scope which queue rows are cancelled."""
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
    """The handler must wrap the queue drain in `asyncio.to_thread`."""
    from routers import trading_bot as tb_module
    src = inspect.getsource(tb_module.cancel_all_pending_orders)
    assert "asyncio.to_thread(" in src, (
        "cancel_all_pending_orders must use asyncio.to_thread for the "
        "Mongo order_queue drain (avoid event-loop wedge under load)."
    )
