"""
Weekend Briefing Router
=======================

Endpoints for the Sunday-afternoon weekly briefing surface.

  GET  /api/briefings/weekend/latest    — return the cached briefing for
                                          the current ISO week (or the
                                          most recent one if the current
                                          hasn't been generated yet).

  POST /api/briefings/weekend/generate  — force a fresh fetch + LLM
                                          synthesis. Idempotent within
                                          the same ISO week unless `?force=1`.

The Sunday 14:00 ET cron lives in `eod_generation_service.py` and calls
the same `WeekendBriefingService.generate()` so behaviour is identical
between scheduled + manual triggers.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from services.weekend_briefing_service import get_weekend_briefing_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/briefings/weekend", tags=["Weekend Briefing"])


@router.get("/latest")
async def get_latest_weekend_briefing():
    """Return the most recent cached weekend briefing.

    Response shape (stable):
      {
        "success": True,
        "found": bool,
        "briefing": {...} | None
      }

    The `briefing` payload contains:
      iso_week, generated_at, last_week_recap (sectors + closed_trades),
      major_news, earnings_calendar, macro_calendar, sector_catalysts,
      ipo_calendar, gameplan, risk_map, positions_held, sources.
    """
    svc = get_weekend_briefing_service()
    if svc is None:
        return {"success": False, "found": False, "error": "service_not_initialized"}
    doc = svc.get_latest()
    return {"success": True, "found": doc is not None, "briefing": doc}


@router.post("/generate")
async def generate_weekend_briefing(force: bool = Query(False, description=
                                                        "Force regeneration even if a briefing already exists for this week.")):
    """Generate (or regenerate) the briefing for the current ISO week."""
    svc = get_weekend_briefing_service()
    if svc is None:
        return {"success": False, "error": "service_not_initialized"}
    try:
        briefing = await svc.generate(force=force)
        return {"success": True, "briefing": briefing}
    except Exception as exc:
        logger.exception("weekend_briefing generate failed")
        return {"success": False, "error": str(exc)}
