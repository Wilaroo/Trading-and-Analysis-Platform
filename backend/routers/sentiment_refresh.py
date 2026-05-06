"""
Sentiment refresh router — standalone news collection + FinBERT scoring.

Decoupled from the 44h training pipeline. Runs fast (~2-5 min) so it can
fire daily at 7:45 AM ET pre-market to refresh sentiment before morning
briefing assembly.

Endpoints:
    POST /api/sentiment/refresh   — run Finnhub + Yahoo RSS collection, then score
    GET  /api/sentiment/schedule  — status of the APScheduler job
    GET  /api/sentiment/latest    — last refresh summary (from mongo metadata)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sentiment", tags=["sentiment"])

_db = None
_scheduler = None
# How many symbols to pull news for (expanded from 100 → 500 per user request).
DEFAULT_UNIVERSE_SIZE = 500
# Upper cap for FinBERT scoring per run so a backlog surge can't balloon runtime.
SCORING_MAX_ARTICLES = 20000
# Collection where we write last-run metadata
META_COLLECTION = "sentiment_refresh_history"


def init_sentiment_router(db, scheduler=None):
    """Wire the database + scheduler handles. Called from server.py startup."""
    global _db, _scheduler
    _db = db
    _scheduler = scheduler


def _get_db():
    if _db is not None:
        return _db
    try:
        from database import get_database
        return get_database()
    except Exception:
        return None


async def _run_refresh(universe_size: int = DEFAULT_UNIVERSE_SIZE) -> Dict[str, Any]:
    """Core refresh flow: pick universe → collect (Finnhub + Yahoo) → score with FinBERT."""
    db = _get_db()
    if db is None:
        raise RuntimeError("No database handle available for sentiment refresh")

    # Import inside so scheduler can start before heavy modules finish loading
    from services.ai_modules.finbert_sentiment import (
        FinnhubNewsCollector,
        YahooRSSNewsCollector,
        FinBERTSentiment,
    )
    from services.ai_modules.training_pipeline import get_cached_symbols

    started_at = datetime.now(timezone.utc)
    results: Dict[str, Any] = {
        "started_at": started_at.isoformat(),
        "universe_size": universe_size,
        "sources": {},
        "scored": {},
        "errors": [],
    }

    # 1) Build the ticker universe (top-N by daily bar coverage, same as training P12)
    try:
        symbols = await get_cached_symbols(db, "1 day", min_bars=50, max_symbols=universe_size)
    except Exception as e:
        logger.error(f"[SENT-REFRESH] Failed to build universe: {e}")
        results["errors"].append({"stage": "universe", "error": str(e)})
        return results
    results["symbols_count"] = len(symbols)
    logger.info(f"[SENT-REFRESH] Universe built: {len(symbols)} symbols")

    # 2) Finnhub collection (if key is configured)
    finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
    if finnhub_key:
        try:
            finnhub = FinnhubNewsCollector(db=db, api_key=finnhub_key)
            fn_res = await finnhub.collect_news(symbols=symbols, days_back=14)
            results["sources"]["finnhub"] = fn_res
            logger.info(f"[SENT-REFRESH] Finnhub done: {fn_res}")
        except Exception as e:
            logger.error(f"[SENT-REFRESH] Finnhub collection error: {e}")
            results["errors"].append({"stage": "finnhub", "error": str(e)})
    else:
        results["sources"]["finnhub"] = {"skipped": "FINNHUB_API_KEY not set"}

    # 3) Yahoo RSS collection (no key required)
    try:
        yahoo = YahooRSSNewsCollector(db=db)
        yh_res = await yahoo.collect_news(symbols=symbols)
        results["sources"]["yahoo_rss"] = yh_res
        logger.info(f"[SENT-REFRESH] Yahoo RSS done: {yh_res}")
    except Exception as e:
        logger.error(f"[SENT-REFRESH] Yahoo RSS collection error: {e}")
        results["errors"].append({"stage": "yahoo_rss", "error": str(e)})

    # 4) Score everything unscored with FinBERT
    try:
        scorer = FinBERTSentiment(db=db)
        score_res = await scorer.score_unscored_articles(
            batch_size=64, max_articles=SCORING_MAX_ARTICLES
        )
        results["scored"] = score_res
        logger.info(f"[SENT-REFRESH] FinBERT scored: {score_res}")
    except Exception as e:
        logger.error(f"[SENT-REFRESH] FinBERT scoring error: {e}")
        results["errors"].append({"stage": "finbert", "error": str(e)})

    ended_at = datetime.now(timezone.utc)
    results["ended_at"] = ended_at.isoformat()
    results["duration_s"] = (ended_at - started_at).total_seconds()

    # Persist run metadata so /latest can report it back quickly
    try:
        db[META_COLLECTION].insert_one({**results, "kind": "scheduled_refresh"})
        db[META_COLLECTION].create_index([("started_at", -1)])
    except Exception as e:
        logger.warning(f"[SENT-REFRESH] Failed to persist metadata: {e}")

    return results


@router.post("/refresh")
async def refresh_sentiment(universe_size: int = DEFAULT_UNIVERSE_SIZE) -> Dict[str, Any]:
    """Manually trigger a sentiment refresh. Same logic the scheduler runs."""
    try:
        res = await _run_refresh(universe_size=universe_size)
        return {"success": True, **res}
    except Exception as e:
        logger.exception("[SENT-REFRESH] Refresh failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schedule")
async def get_schedule_status() -> Dict[str, Any]:
    """Next scheduled run time + job config — useful for a HUD chip."""
    if _scheduler is None:
        return {"enabled": False, "reason": "Scheduler not initialized"}
    job = _scheduler.get_job("sentiment_refresh")
    if job is None:
        return {"enabled": False, "reason": "Job not registered"}
    return {
        "enabled": True,
        "job_id": job.id,
        "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
        "trigger": str(job.trigger),
    }


@router.get("/latest")
async def get_latest_refresh() -> Dict[str, Any]:
    """Summary of the most recent refresh (from mongo metadata)."""
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    doc = db[META_COLLECTION].find_one(
        {}, {"_id": 0}, sort=[("started_at", -1)]
    )
    if not doc:
        return {"success": True, "message": "No refresh has run yet"}
    return {"success": True, **doc}
