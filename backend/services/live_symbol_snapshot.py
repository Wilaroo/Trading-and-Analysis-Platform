"""
Live Symbol Snapshot — Phase 3 helper
=====================================
One-liner freshest-price service. Any surface that just wants "what's
the latest price for SYM and how old is that data" calls this instead of
reinventing its own pusher-RPC + cache logic. Builds on
HybridDataService.fetch_latest_session_bars (Phase 1) and the DGX pusher
RPC bridge (Phase 2).

Consumers:
    * Scanner: validate latest bar freshness before producing a signal
    * Briefings: pre-market / mid-day / power-hour snapshot rows
    * AI chat context: inject {sym, price, change_pct, market_state}
    * Trade Journal: immutable close-price snapshot

The snapshot is deliberately minimal — no indicator math, no history.
Callers that need bars should use fetch_latest_session_bars directly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def get_latest_snapshot(
    symbol: str,
    bar_size: str = "5 mins",
    *,
    active_view: bool = False,
) -> Dict[str, Any]:
    """
    Return the freshest snapshot for a single symbol.

    Response shape (stable — safe for frontend / AI to bind to):
        {
            symbol: "SPY",
            latest_price: 452.37,        # last bar close
            latest_bar_time: "2026-...",  # ISO ts of last bar
            prev_close: 451.90,          # bar before last (same slice)
            change_abs: 0.47,
            change_pct: 0.104,           # percent, not fraction
            bar_size: "5 mins",
            bar_count: 78,               # bars in the slice used
            market_state: "rth",
            source: "cache" | "pusher_rpc" | "none",
            fetched_at: ISO ts,
            success: bool,
            error: str | None,
        }

    On any failure returns success=False with the reason. Never raises.
    """
    from services.hybrid_data_service import get_hybrid_data_service

    svc = get_hybrid_data_service()
    if svc is None:
        return _fail(symbol, bar_size, "hybrid_data_service_uninitialised")

    res = await svc.fetch_latest_session_bars(
        symbol,
        bar_size,
        active_view=active_view,
        use_rth=False,  # extended hours — most useful for pre/post-market
    )

    if not res.get("success"):
        return _fail(
            symbol, bar_size,
            res.get("error") or "fetch_failed",
            source=res.get("source"),
            market_state=res.get("market_state"),
        )

    bars: List[Dict[str, Any]] = res.get("bars") or []
    if not bars:
        return _fail(
            symbol, bar_size, "no_bars_returned",
            source=res.get("source"),
            market_state=res.get("market_state"),
        )

    last = bars[-1]
    prev = bars[-2] if len(bars) >= 2 else None

    try:
        last_price = float(last.get("close") or 0.0)
    except (TypeError, ValueError):
        last_price = 0.0
    try:
        prev_close = float(prev.get("close")) if prev else last_price
    except (TypeError, ValueError):
        prev_close = last_price

    change_abs = round(last_price - prev_close, 4)
    change_pct = (
        round((change_abs / prev_close) * 100.0, 4)
        if prev_close
        else 0.0
    )

    return {
        "success": True,
        "symbol": symbol.upper(),
        "latest_price": last_price,
        "latest_bar_time": last.get("date") or last.get("timestamp"),
        "prev_close": prev_close,
        "change_abs": change_abs,
        "change_pct": change_pct,
        "bar_size": bar_size,
        "bar_count": len(bars),
        "market_state": res.get("market_state"),
        "source": res.get("source"),
        "fetched_at": res.get("fetched_at")
            or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "error": None,
    }


async def get_snapshots_bulk(
    symbols: List[str],
    bar_size: str = "5 mins",
) -> List[Dict[str, Any]]:
    """
    Batch variant. Runs each snapshot sequentially — the pusher RPC rate
    limit is well below "100 snapshots/second" so parallelism isn't worth
    the extra complexity. Bounded to 20 symbols per call to avoid
    cache-stampede DoS on a slow pusher.
    """
    out: List[Dict[str, Any]] = []
    for sym in (symbols or [])[:20]:
        s = (sym or "").upper().strip()
        if not s:
            continue
        out.append(await get_latest_snapshot(s, bar_size))
    return out


def _fail(
    symbol: str,
    bar_size: str,
    reason: str,
    *,
    source: Optional[str] = None,
    market_state: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "success": False,
        "symbol": symbol.upper(),
        "bar_size": bar_size,
        "latest_price": None,
        "latest_bar_time": None,
        "prev_close": None,
        "change_abs": None,
        "change_pct": None,
        "bar_count": 0,
        "market_state": market_state,
        "source": source or "none",
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "error": reason,
    }
