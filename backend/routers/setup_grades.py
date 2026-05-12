"""
routers/setup_grades.py — v19.34.113 (Feb 2026)

Read + recompute endpoints for the SetupGradingService. Mounted under
`/api/setup-grades`.

Endpoints:
  GET  /api/setup-grades                         — list all rolling cards
  GET  /api/setup-grades/{setup_type}            — single rolling card
  POST /api/setup-grades/compute                 — recompute EOD snapshot
  GET  /api/setup-grades/history/{setup_type}    — raw daily records
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from services.setup_grading_service import (
    GRADE_COLLECTION,
    get_setup_grading_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/setup-grades", tags=["setup-grades"])


@router.get("")
def list_setup_grades(days: int = Query(30, ge=1, le=365)):
    """Return one rolling grade card per setup_type observed in the
    last `days`. Sorted by avg_r desc."""
    try:
        svc = get_setup_grading_service()
        rolling = svc.get_all_rolling_grades(days=days)
        return {
            "success": True,
            "window_days": days,
            "count": len(rolling),
            "grades": [r.__dict__ for r in rolling],
        }
    except Exception as e:
        logger.error(f"list_setup_grades error: {e}")
        return {
            "success": False,
            "error": str(e),
            "window_days": days,
            "count": 0,
            "grades": [],
        }


@router.get("/yesterday-recap")
def get_yesterday_grade_recap(reference_date: Optional[str] = Query(None)):
    """v19.34.114 — Yesterday's grade card, formatted for the morning
    briefing. Walks back up to 7 calendar days to find the most recent
    trading day with grade data, so weekend / holiday loads return a
    valid recap instead of a blank.

    IMPORTANT: this route is declared BEFORE `/{setup_type}` so FastAPI
    doesn't route `/yesterday-recap` into the generic path-param handler.
    """
    try:
        svc = get_setup_grading_service()
        recap = svc.get_yesterday_recap(reference_date=reference_date)
        return {"success": True, "recap": recap}
    except Exception as e:
        logger.error(f"get_yesterday_grade_recap error: {e}")
        return {
            "success": False,
            "error": str(e),
            "recap": {
                "trading_date": None, "total_setups": 0,
                "winners": [], "losers": [],
                "summary_line": "Grade recap unavailable — service error.",
                "has_data": False,
            },
        }


@router.get("/{setup_type}")
def get_setup_grade(setup_type: str, days: int = Query(30, ge=1, le=365)):
    """Return the rolling card for a single setup_type. 404 if the
    setup has zero closed trades in the window."""
    try:
        svc = get_setup_grading_service()
        rolling = svc.get_rolling_grade(setup_type, days=days)
        if rolling is None:
            raise HTTPException(
                status_code=404,
                detail=f"No grade records for setup_type={setup_type!r} in last {days}d",
            )
        return {"success": True, "grade": rolling.__dict__}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_setup_grade({setup_type}) error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compute")
def compute_setup_grades(trading_date: Optional[str] = Query(None)):
    """Recompute EOD grade snapshot for `trading_date` (default = today
    US/Eastern). Idempotent — upserts the daily records keyed on
    (setup_type, trading_date)."""
    try:
        svc = get_setup_grading_service()
        result = svc.compute_eod_grades(trading_date=trading_date)
        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"compute_setup_grades error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{setup_type}")
def get_setup_grade_history(setup_type: str, days: int = Query(30, ge=1, le=365)):
    """Raw daily grade records for `setup_type` — useful for sparklines
    in the V5 chip popover."""
    from datetime import timedelta
    try:
        from zoneinfo import ZoneInfo
        from database import get_database

        et = ZoneInfo("US/Eastern")
        today = datetime.now(et).date()
        from_date = (today - timedelta(days=days)).strftime("%Y-%m-%d")

        db = get_database()
        cursor = db[GRADE_COLLECTION].find(
            {
                "setup_type": setup_type,
                "trading_date": {"$gte": from_date},
            },
            {"_id": 0},
        ).sort("trading_date", 1)
        history = list(cursor)
        return {
            "success": True,
            "setup_type": setup_type,
            "window_days": days,
            "count": len(history),
            "history": history,
        }
    except Exception as e:
        logger.error(f"get_setup_grade_history({setup_type}) error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
