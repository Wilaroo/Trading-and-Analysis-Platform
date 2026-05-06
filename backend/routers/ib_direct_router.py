"""
ib_direct_router.py — v19.34.25 (2026-02-XX)

Status + diagnostic endpoints for the direct IB API connection
(see services/ib_direct_service.py).

Deliberately read-mostly in Phase 1: the operator validates the socket
works and the brokerage authorization is good BEFORE any order goes
through this channel. Phase 2 wires it into trade_executor_service.

Endpoints:
    GET  /api/system/ib-direct/status         — connection state + auth
    POST /api/system/ib-direct/connect        — explicitly open the socket
    POST /api/system/ib-direct/disconnect     — close the socket
    GET  /api/system/ib-direct/positions      — authoritative IB positions
    POST /api/system/ib-direct/smoke-test     — read-only smoke test
                                                 (connect → positions →
                                                 disconnect, no orders)
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from services.ib_direct_service import get_ib_direct_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system/ib-direct", tags=["ib-direct"])


@router.get("/status")
async def ib_direct_status() -> Dict[str, Any]:
    """Current state of the direct IB socket.

    Returns success=True even when not connected — the response payload
    carries `connected`/`authorized_to_trade` flags. This matches the
    pattern of other system endpoints (status check itself succeeds).

    v19.34.27 — also surfaces the BOT_ORDER_PATH mode + shadow-observe
    divergence counters so the V5 IB-LIVE chip tooltip can show whether
    pusher/IB-direct have been agreeing in shadow mode.
    """
    payload = get_ib_direct_service().status()
    try:
        from services.trade_executor_service import TradeExecutorService
        payload["shadow"] = TradeExecutorService.shadow_stats()
    except Exception as e:
        logger.debug("ib_direct_status: shadow_stats lookup failed: %s", e)
        payload["shadow"] = {"order_path": "pusher", "counters": {}}
    return payload


@router.post("/connect")
async def ib_direct_connect() -> Dict[str, Any]:
    """Idempotent connect. Returns the result + status."""
    svc = get_ib_direct_service()
    result = await svc.connect()
    result["status"] = svc.status()
    return result


@router.post("/disconnect")
async def ib_direct_disconnect() -> Dict[str, Any]:
    svc = get_ib_direct_service()
    await svc.disconnect()
    return {"success": True, "status": svc.status()}


@router.get("/positions")
async def ib_direct_positions() -> Dict[str, Any]:
    """Authoritative live positions per IB API.

    Useful for cross-checking the bot's `_open_trades` cache when
    investigating phantom-share divergence (today's BMNR 5,472 vs 1,905
    scenario). The pusher's relayed snapshot is no longer the only
    source of truth.
    """
    svc = get_ib_direct_service()
    if not svc.is_connected():
        return {"success": False, "error": "not connected — call /connect first",
                "positions": []}
    positions = await svc.get_positions()
    return {"success": True, "count": len(positions), "positions": positions}


@router.post("/smoke-test")
async def ib_direct_smoke_test() -> Dict[str, Any]:
    """Read-only smoke test: connect → fetch positions → return.

    Operator runs this once after configuring the IB Gateway whitelist
    + clientId to verify the bot can reach the Gateway. Does NOT place
    any orders. Safe to run on a live account.
    """
    svc = get_ib_direct_service()
    connect_result = await svc.connect()
    if not svc.is_connected():
        return {
            "success": False,
            "stage": "connect",
            "error": connect_result.get("error", "connect failed"),
            "details": connect_result,
        }

    positions = await svc.get_positions()
    return {
        "success": True,
        "stage": "complete",
        "connected": svc.is_connected(),
        "authorized_to_trade": svc.is_authorized_to_trade(),
        "positions_count": len(positions),
        "positions": positions,
        "config": {
            "host": svc.config.host,
            "port": svc.config.port,
            "client_id": svc.config.client_id,
            "read_only": svc.config.read_only,
        },
    }
