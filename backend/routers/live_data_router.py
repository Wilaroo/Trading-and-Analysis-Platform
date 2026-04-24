"""
Live Data Router — Phase 1 endpoints for pusher RPC visibility.

Exposes:
    GET  /api/live/pusher-rpc-health   - status of DGX -> pusher RPC channel
    GET  /api/live/latest-bars         - on-demand latest-session bars
    GET  /api/live/quote-snapshot      - on-demand IB quote snapshot
    POST /api/live/cache-invalidate    - purge a symbol from live_bar_cache

Meant for operators + frontend DataFreshnessInspector (future P3).
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from services.hybrid_data_service import get_hybrid_data_service
from services.ib_pusher_rpc import get_pusher_rpc_client
from services.live_bar_cache import (
    classify_market_state,
    get_live_bar_cache,
    ttl_for_state,
)
from services.live_subscription_manager import get_live_subscription_manager

router = APIRouter(prefix="/api/live", tags=["live-data"])


@router.get("/pusher-rpc-health")
async def pusher_rpc_health() -> Dict[str, Any]:
    """
    Probe the Windows pusher RPC endpoint and return its health plus the
    DGX-side configuration (env flag, URL, failure counter).
    """
    client = get_pusher_rpc_client()
    client_status = client.status()

    remote_health = None
    if client.is_configured():
        remote_health = await asyncio.to_thread(client.health)

    return {
        "client": client_status,
        "remote": remote_health,
        "reachable": remote_health is not None,
        "market_state": classify_market_state(),
    }


@router.get("/latest-bars")
async def latest_bars(
    symbol: str = Query(..., min_length=1, max_length=12),
    bar_size: str = Query("5 mins"),
    active_view: bool = Query(False),
    use_rth: bool = Query(False),
) -> Dict[str, Any]:
    service = get_hybrid_data_service()
    if service is None:
        raise HTTPException(status_code=503, detail="hybrid_data_service not initialised")
    res = await service.fetch_latest_session_bars(
        symbol,
        bar_size,
        active_view=active_view,
        use_rth=use_rth,
    )
    return res


@router.get("/quote-snapshot")
async def quote_snapshot(
    symbol: str = Query(..., min_length=1, max_length=12),
) -> Dict[str, Any]:
    client = get_pusher_rpc_client()
    if not client.is_configured():
        return {"success": False, "error": "pusher_rpc_disabled_or_unconfigured"}
    quote = await asyncio.to_thread(client.quote_snapshot, symbol)
    return {"success": quote is not None, "symbol": symbol.upper(), "quote": quote}


@router.post("/cache-invalidate")
async def cache_invalidate(
    symbol: str = Query(..., min_length=1, max_length=12),
    bar_size: Optional[str] = Query(None),
) -> Dict[str, Any]:
    cache = get_live_bar_cache()
    if cache is None or cache._col is None:  # noqa: SLF001 - internal
        return {"success": False, "deleted": 0, "error": "cache_not_initialised"}
    q: Dict[str, Any] = {"symbol": symbol.upper()}
    if bar_size:
        q["bar_size"] = bar_size
    try:
        n = cache._col.delete_many(q).deleted_count  # noqa: SLF001
        return {"success": True, "deleted": int(n), "query": q}
    except Exception as exc:
        return {"success": False, "deleted": 0, "error": str(exc)}


@router.get("/ttl-plan")
async def ttl_plan() -> Dict[str, Any]:
    """Show the TTL plan per market state — useful for operator debugging."""
    state = classify_market_state()
    return {
        "market_state": state,
        "ttl_by_state": {
            s: ttl_for_state(s, active_view=False) for s in
            ("rth", "extended", "overnight", "weekend")
        },
        "ttl_active_view": ttl_for_state(state, active_view=True),
    }


# ========================================================================
# Phase 2 — Live subscription layer (ref-counted watchlist → pusher RPC)
# ========================================================================

@router.post("/subscribe/{symbol}")
async def subscribe_symbol(symbol: str) -> Dict[str, Any]:
    """Increment ref-count for `symbol`. Pusher RPC is called only on the
    0→1 transition. Safe to call from multiple UI surfaces for the same
    symbol — each unmount unsubscribe will decrement, pusher only stops
    pushing when the last consumer leaves."""
    mgr = get_live_subscription_manager()
    return await asyncio.to_thread(mgr.subscribe, symbol)


@router.post("/unsubscribe/{symbol}")
async def unsubscribe_symbol(symbol: str) -> Dict[str, Any]:
    mgr = get_live_subscription_manager()
    return await asyncio.to_thread(mgr.unsubscribe, symbol)


@router.post("/heartbeat/{symbol}")
async def heartbeat_symbol(symbol: str) -> Dict[str, Any]:
    """Renew the 5-min heartbeat so the sweep doesn't auto-expire this sub.
    Frontend hook calls this every 2 min while a symbol is on screen."""
    mgr = get_live_subscription_manager()
    return mgr.heartbeat(symbol)


@router.get("/subscriptions")
async def list_subscriptions() -> Dict[str, Any]:
    mgr = get_live_subscription_manager()
    return mgr.list_subscriptions()


@router.post("/subscriptions/sweep")
async def sweep_subscriptions() -> Dict[str, Any]:
    """Operator endpoint — manually trigger the stale-sub sweep."""
    mgr = get_live_subscription_manager()
    expired = await asyncio.to_thread(mgr.sweep_expired)
    return {"expired_count": len(expired), "expired": expired}


# ========================================================================
# Phase 3 — Snapshot primitive (scanner / briefing / AI-chat consumer)
# ========================================================================

@router.get("/symbol-snapshot/{symbol}")
async def symbol_snapshot(
    symbol: str,
    bar_size: str = Query("5 mins"),
    active_view: bool = Query(False),
) -> Dict[str, Any]:
    """One-liner freshest price for a symbol. Returns success=False on any
    failure — never 5xx. Safe to poll from UI / chat / scanner."""
    from services.live_symbol_snapshot import get_latest_snapshot
    return await get_latest_snapshot(symbol, bar_size, active_view=active_view)


@router.post("/symbol-snapshots")
async def symbol_snapshots_bulk(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Batch snapshot — body `{symbols: [...], bar_size: "5 mins"}`.
    Bounded to 20 symbols per call."""
    from services.live_symbol_snapshot import get_snapshots_bulk
    syms = payload.get("symbols") or []
    bs = payload.get("bar_size", "5 mins")
    if not isinstance(syms, list):
        return {"success": False, "error": "symbols must be a list", "snapshots": []}
    results = await get_snapshots_bulk(syms, bs)
    return {
        "success": True,
        "snapshots": results,
        "count": len(results),
    }


@router.get("/briefing-snapshot")
async def briefing_snapshot(
    symbols: str = Query("SPY,QQQ,IWM,DIA,VIX"),
    bar_size: str = Query("5 mins"),
) -> Dict[str, Any]:
    """Aggregate snapshot for briefings (pre-market / mid-day / power-hour /
    close). Accepts comma-separated symbols. Returns ranked by absolute
    change_pct (biggest movers first) so the briefing UI can highlight the
    top shifts immediately."""
    from services.live_symbol_snapshot import get_snapshots_bulk
    from services.live_bar_cache import classify_market_state
    syms = [s.strip().upper() for s in (symbols or "").split(",") if s.strip()]
    snaps = await get_snapshots_bulk(syms, bar_size)
    # Rank by |change_pct|, failed snapshots go last
    ranked = sorted(
        snaps,
        key=lambda s: (
            0 if s.get("success") else 1,
            -(abs(s.get("change_pct") or 0)),
        ),
    )
    return {
        "success": True,
        "count": len(ranked),
        "market_state": classify_market_state(),
        "bar_size": bar_size,
        "snapshots": ranked,
    }


# ========================================================================
# P2-A — Morning Briefing rich UI support
# ========================================================================

_CORE_INDICES = ("SPY", "QQQ", "IWM", "DIA", "VIX")


async def _build_briefing_watchlist(db) -> List[str]:
    """Pull briefing-watchlist symbols from:
        (1) open positions (ib_live_snapshot)
        (2) scanner top-10 recent cards (market_scanner_results)
        (3) core indices (always included)
    Deduped, capped at 12 symbols to stay under news-provider + pusher RPC
    budgets."""
    watchlist: List[str] = []
    try:
        if db is not None:
            snap = db["ib_live_snapshot"].find_one(
                {"_id": "current"}, {"_id": 0, "positions": 1}
            )
            for p in (snap or {}).get("positions", []) or []:
                sym = (p.get("symbol") or "").upper().strip()
                if sym and sym not in watchlist:
                    watchlist.append(sym)
    except Exception:
        pass
    try:
        if db is not None:
            # Most recent scanner result set (if any)
            latest = db["market_scanner_results"].find_one(
                sort=[("created_at", -1)],
                projection={"_id": 0, "candidates": 1, "results": 1, "top_picks": 1},
            )
            if latest:
                candidates = (
                    latest.get("top_picks")
                    or latest.get("candidates")
                    or latest.get("results")
                    or []
                )
                for c in candidates[:10]:
                    if isinstance(c, dict):
                        sym = (c.get("symbol") or "").upper().strip()
                    else:
                        sym = str(c or "").upper().strip()
                    if sym and sym not in watchlist:
                        watchlist.append(sym)
    except Exception:
        pass
    for idx in _CORE_INDICES:
        if idx not in watchlist:
            watchlist.append(idx)
    return watchlist[:12]


@router.get("/briefing-watchlist")
async def briefing_watchlist() -> Dict[str, Any]:
    """Return the dynamic watchlist the MorningBriefing UI uses for its
    top-movers + overnight-sentiment rows. Positions + scanner top-10 +
    core indices, deduped, capped at 12."""
    from server import db as _app_db
    syms = await _build_briefing_watchlist(_app_db)
    return {
        "success": True,
        "symbols": syms,
        "count": len(syms),
        "sources": {
            "positions": True,
            "scanner_top_10": True,
            "core_indices": list(_CORE_INDICES),
        },
    }


@router.get("/briefing-top-movers")
async def briefing_top_movers(bar_size: str = Query("5 mins")) -> Dict[str, Any]:
    """Top movers across the DYNAMIC briefing watchlist (positions + scanner
    + core indices). Wrapper around /api/live/briefing-snapshot with the
    watchlist auto-built server-side."""
    from server import db as _app_db
    from services.live_symbol_snapshot import get_snapshots_bulk
    from services.live_bar_cache import classify_market_state
    syms = await _build_briefing_watchlist(_app_db)
    snaps = await get_snapshots_bulk(syms, bar_size)
    ranked = sorted(
        snaps,
        key=lambda s: (
            0 if s.get("success") else 1,
            -(abs(s.get("change_pct") or 0)),
        ),
    )
    return {
        "success": True,
        "watchlist": syms,
        "count": len(ranked),
        "market_state": classify_market_state(),
        "bar_size": bar_size,
        "snapshots": ranked,
    }


@router.get("/overnight-sentiment")
async def overnight_sentiment(
    symbols: str = Query("", description="Comma-separated. Omit to auto-build from positions+scanner+indices."),
) -> Dict[str, Any]:
    """Compare yesterday-close vs premarket news sentiment per symbol.
    Swing threshold ±0.30 (notable=true when |swing| >= 0.30).
    Max 12 symbols per call."""
    from services.overnight_sentiment_service import compute_batch, SWING_THRESHOLD
    if symbols:
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        from server import db as _app_db
        syms = await _build_briefing_watchlist(_app_db)
    results = await compute_batch(syms)
    notable_count = sum(1 for r in results if r.get("notable"))
    return {
        "success": True,
        "watchlist": syms,
        "count": len(results),
        "notable_count": notable_count,
        "swing_threshold": SWING_THRESHOLD,
        "results": results,
    }
