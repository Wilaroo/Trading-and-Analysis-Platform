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

from fastapi import APIRouter

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


@router.get("/historical/{symbol}")
async def ib_direct_historical(
    symbol: str,
    duration: str = "1 Y",
    bar_size: str = "1 day",
    what_to_show: str = "TRADES",
    use_rth: bool = True,
) -> Dict[str, Any]:
    """Historical bars over the live IB-direct socket (the only working
    historical path on this deploy). Handles VIX as a CBOE index. Used by the
    VIX-history backfill so the system can percentile-rank current vol against
    COVID / tariff / geopolitical spike-and-bottom regimes."""
    svc = get_ib_direct_service()
    if not svc.is_connected():
        return {"success": False, "error": "not connected — call /connect first", "bars": []}
    bars = await svc.get_historical_data(
        symbol, duration=duration, bar_size=bar_size,
        what_to_show=what_to_show, use_rth=use_rth,
    )
    return {"success": True, "symbol": symbol.upper(), "bar_size": bar_size,
            "duration": duration, "count": len(bars), "bars": bars}


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



# ── v19.34.28 Patch L2c — Migration-status banner endpoint ────────────
#
# Single-shot green/amber/red banner the operator UI consumes to make
# the Monday "unlock kill switch" go/no-go call. Aggregates every signal
# that has to be healthy before flipping BOT_ORDER_PATH=direct:
#   - ib-direct socket connected + authorized
#   - drop_count low / no recent drops
#   - heartbeat ok
#   - watchdog running
#   - L1/L2a write paths code-present in trade_executor
#   - L2b read paths wired in reconcilers
# The endpoint returns a flat verdict ("ready" | "degraded" | "blocked")
# so the UI just renders one chip — no client-side aggregation logic.

import os as _os_l2c
import time as _time_l2c


@router.get("/migration-status")
async def ib_direct_migration_status() -> Dict[str, Any]:
    """v19.34.28 L2c — Aggregated go/no-go status for the IB-Direct migration.

    Returns:
      {
        verdict: "ready" | "degraded" | "blocked",
        order_path: "pusher" | "shadow" | "direct",
        checks: {
          ib_direct_connected: bool,
          ib_direct_authorized: bool,
          watchdog_running: bool,
          recent_drops_5m: int,
          heartbeat_ok: bool,
          write_paths_scaffolded: bool,
          read_paths_wired: bool,
        },
        ib_direct: {...status snapshot...},
        recommendations: [...operator-facing strings...],
      }
    """
    svc = get_ib_direct_service()
    status = svc.status()
    stability = status.get("stability", {}) or {}

    order_path = (_os_l2c.environ.get("BOT_ORDER_PATH", "pusher") or "pusher").strip().lower()

    # Drop frequency in the last 5 minutes.
    now_ts = _time_l2c.time()
    last_drop_at = stability.get("last_drop_at") or 0
    drops_recent_5m = (
        int(stability.get("drop_count_total", 0) or 0)
        if last_drop_at and (now_ts - float(last_drop_at)) < 300
        else 0
    )

    # Heartbeat ok if last heartbeat success is more recent than last failure
    # (or no failures recorded yet).
    last_hb_ok = stability.get("last_heartbeat_ok_at") or 0
    last_hb_fail = stability.get("last_heartbeat_failed_at") or 0
    heartbeat_ok = bool(last_hb_ok and (not last_hb_fail or last_hb_ok > last_hb_fail))

    # L1/L2a write-path scaffold check: presence of methods on the
    # service object. Cheap import-time validation.
    write_paths_scaffolded = all(
        callable(getattr(svc, m, None))
        for m in ("place_bracket_order", "place_entry", "place_stop",
                  "place_oca_stop_target")
    )
    # L2a read-path scaffold check.
    read_paths_scaffolded = all(
        callable(getattr(svc, m, None))
        for m in ("get_positions_fresh", "get_open_orders", "get_account_summary")
    )
    # L2b wiring check — module-level helper present in position_reconciler.
    try:
        from services.position_reconciler import _l2b_fetch_ib_positions  # noqa: F401
        read_paths_wired = True
    except Exception:
        read_paths_wired = False

    checks = {
        "ib_direct_connected": status.get("connected", False),
        "ib_direct_authorized": status.get("authorized_to_trade", False),
        "watchdog_running": stability.get("watchdog_running", False),
        "recent_drops_5m": drops_recent_5m,
        "heartbeat_ok": heartbeat_ok,
        "write_paths_scaffolded": write_paths_scaffolded and read_paths_scaffolded,
        "read_paths_wired": read_paths_wired,
    }

    recommendations: list = []
    if not checks["write_paths_scaffolded"] or not checks["read_paths_wired"]:
        recommendations.append("L1/L2a/L2b code not fully present — re-apply patches.")
    if not checks["ib_direct_connected"]:
        recommendations.append("ib-direct socket DOWN — POST /api/system/ib-direct/connect")
    elif not checks["ib_direct_authorized"]:
        recommendations.append("ib-direct connected but managedAccounts empty "
                                "— check IB Gateway 'logged in elsewhere'")
    if not checks["watchdog_running"]:
        recommendations.append("watchdog not running — restart backend or call connect")
    if drops_recent_5m > 0:
        recommendations.append(f"{drops_recent_5m} ib-direct drop(s) in last 5 min — "
                                "wait for stability before flipping to direct")
    if not heartbeat_ok and status.get("connected"):
        recommendations.append("heartbeat has not confirmed yet — wait ~30s for first ping")

    # Verdict aggregation.
    code_ok = checks["write_paths_scaffolded"] and checks["read_paths_wired"]
    socket_ok = checks["ib_direct_connected"] and checks["ib_direct_authorized"]
    stable = drops_recent_5m == 0 and checks["watchdog_running"]
    if code_ok and socket_ok and stable:
        verdict = "ready"
    elif code_ok and socket_ok:
        verdict = "degraded"
    else:
        verdict = "blocked"

    if order_path == "direct" and verdict != "ready":
        recommendations.insert(0,
            "BOT_ORDER_PATH=direct but verdict != ready — "
            "consider flipping back to pusher until stable.")

    return {
        "success": True,
        "verdict": verdict,
        "order_path": order_path,
        "checks": checks,
        "ib_direct": status,
        "recommendations": recommendations,
        "checked_at": now_ts,
    }
