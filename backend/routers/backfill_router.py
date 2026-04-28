"""
Backfill Readiness Router
=========================

One-call "am I ready to train?" endpoint. Mounted at `/api/backfill`.

Separated from `ib_collector_router` on purpose — that router already
owns the collector's internal lifecycle (start/stop/queue/purge). This
one is strictly a read-only readiness gate consumed by the UI (the
FreshnessInspector / Health Dashboard) and by any pre-train automation.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query

from services.backfill_readiness_service import compute_readiness
from services.ib_historical_collector import get_ib_collector
from services.symbol_universe import (
    get_pusher_l1_recommendations,
    get_universe,
    get_universe_stats,
    reset_unqualifiable,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/backfill", tags=["backfill"])


@router.get("/readiness")
async def backfill_readiness():
    """
    Return a single-source-of-truth "OK to train?" readiness report.

    Runs five independent checks (queue drained, critical symbols fresh,
    overall freshness %, duplicate spot-check, density adequacy) and
    produces one green / yellow / red verdict.

    Shape (abridged):
    ```
    {
      "success": true,
      "verdict": "green" | "yellow" | "red",
      "ready_to_train": bool,
      "summary": "...",
      "blockers": [...],
      "warnings": [...],
      "next_steps": [...],
      "checks": {
        "queue_drained": {status, detail, pending, claimed, failed_recent_24h},
        "critical_symbols_fresh": {status, detail, all_fresh, stale_symbols, per_symbol},
        "overall_freshness": {status, detail, fresh_pct, universe_size, per_timeframe},
        "no_duplicates": {status, detail, checked, dupes},
        "density_adequate": {status, detail, dense_pct, low_density_sample, ...},
      },
      "generated_at": "...iso..."
    }
    ```

    All checks are <3s combined and read-only. Safe to poll every 30s.
    """
    try:
        collector = get_ib_collector()
        db = collector._db
        if db is None:
            raise HTTPException(status_code=503, detail="Database not initialized")
        return await asyncio.to_thread(compute_readiness, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"backfill/readiness failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/universe")
async def backfill_universe(tier: str = "all", include_unqualifiable: bool = False):
    """Return the canonical symbol universe at a given tier.

    `tier` ∈ {`intraday` (≥$50M/d), `swing` (≥$10M/d), `investment`
    (≥$2M/d), `all`}. Unqualifiable symbols (3+ IB "No security
    definition" strikes) are excluded by default.

    Used by the AI training pipeline + readiness checks to ensure
    everything operates on the same slice. See
    `services/symbol_universe.py` for the source of truth.
    """
    try:
        collector = get_ib_collector()
        db = collector._db
        if db is None:
            raise HTTPException(status_code=503, detail="Database not initialized")
        symbols = sorted(
            await asyncio.to_thread(
                get_universe, db, tier,
                include_unqualifiable=include_unqualifiable,
            )
        )
        stats = await asyncio.to_thread(get_universe_stats, db)
        return {
            "success": True,
            "tier": tier,
            "count": len(symbols),
            "symbols": symbols,
            "stats": stats,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"backfill/universe failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/universe/reset-unqualifiable/{symbol}")
async def backfill_universe_reset(symbol: str):
    """Operator escape hatch — clear `unqualifiable=true` for a symbol."""
    try:
        collector = get_ib_collector()
        db = collector._db
        if db is None:
            raise HTTPException(status_code=503, detail="Database not initialized")
        ok = await asyncio.to_thread(reset_unqualifiable, db, symbol)
        return {"success": ok, "symbol": symbol.upper()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"backfill/universe/reset-unqualifiable failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pusher-l1-recommendations")
async def backfill_pusher_l1_recommendations(
    top_n: int = Query(60, ge=1, le=100,
                       description="Top-N symbols by avg_dollar_volume "
                                   "to pin into the L1 list."),
    max_total: int = Query(80, ge=1, le=100,
                           description="Hard cap on the returned list "
                                       "(IB Gateway paper has a 100-line "
                                       "ceiling — keep ≤80 to leave "
                                       "headroom for dynamic L2 routing)."),
):
    """Recommended Level-1 subscription list for the IB pusher.

    The pusher reads this on startup (when `IB_PUSHER_L1_AUTO_TOP_N` env
    var is set) to decide which symbols to stream live. Symbols off this
    list still scan against the Mongo `ib_historical_data` cache via the
    tiered scanner — they just won't have sub-second freshness.

    See afternoon-7 RPC gate in `HybridDataService.fetch_latest_session_bars`
    — only symbols on the pusher's active subs list go through the live
    RPC path.
    """
    collector = get_ib_collector()
    db = collector._db
    if db is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    rec = await asyncio.to_thread(
        get_pusher_l1_recommendations, db,
        top_n=top_n, max_total=max_total,
    )
    if not rec.get("success"):
        raise HTTPException(status_code=500, detail=rec.get("error") or "failed")
    return rec

