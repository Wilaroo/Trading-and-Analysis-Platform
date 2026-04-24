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

from fastapi import APIRouter, HTTPException

from services.backfill_readiness_service import compute_readiness
from services.ib_historical_collector import get_ib_collector

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
