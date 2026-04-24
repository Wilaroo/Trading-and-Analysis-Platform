"""
Overnight Sentiment Service — P2-A Morning Briefing rich UI
===========================================================
Compares news sentiment between two windows:
    * yesterday_close  : 16:00 ET prior trading day → 00:00 ET today
    * premarket        : 00:00 ET today → 09:30 ET today

Uses the existing news_service headline pipeline + the keyword scorer
borrowed from SentimentAnalysisService (so scores are comparable to the
per-symbol sentiment the rest of the app already shows).

Swing threshold: ±0.30 (moderate, user-locked). A symbol with
|premarket_score − yesterday_close_score| ≥ threshold is flagged
`notable=true` so the UI can visually emphasise it.

Bounded to ≤12 symbols per call so a briefing build doesn't DoS the
news provider.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SWING_THRESHOLD = 0.30     # locked with user — "moderate" tier
MAX_SYMBOLS = 12           # DoS guard on the news provider
MAX_HEADLINES_PER_SYMBOL = 40


def _et_offset_hours(now: datetime) -> int:
    """Rough DST-aware America/New_York offset (EST=-5, EDT=-4). We don't
    pull in zoneinfo just for this — for bucket boundaries, ±1h accuracy
    is perfectly fine."""
    # DST roughly: 2nd Sunday of March → 1st Sunday of November
    month = now.month
    if 3 < month < 11:
        return -4
    if month == 3:
        return -4 if now.day >= 8 else -5
    if month == 11:
        return -5 if now.day >= 2 else -4
    return -5


def compute_windows(now_utc: Optional[datetime] = None) -> Dict[str, Dict[str, datetime]]:
    """Return {yesterday_close: {start, end}, premarket: {start, end}} in UTC.

    Both windows are anchored to ET wall-clock:
        yesterday_close  = prior-day 16:00 ET  → today 00:00 ET
        premarket        = today 00:00 ET      → today 09:30 ET (or now, whichever earlier)

    If `now` is before 09:30 ET, premarket end = now.
    If `now` is after 09:30 ET, premarket end = 09:30 ET today (frozen).
    """
    now = now_utc or datetime.now(timezone.utc)
    et_offset = _et_offset_hours(now)

    # "today ET midnight" in UTC
    et_now = now + timedelta(hours=et_offset)
    et_midnight_today = et_now.replace(hour=0, minute=0, second=0, microsecond=0)
    utc_midnight_today = et_midnight_today - timedelta(hours=et_offset)

    utc_16_yesterday = utc_midnight_today - timedelta(hours=8)   # 16:00 ET prior day
    utc_09_30_today = utc_midnight_today + timedelta(hours=9, minutes=30)

    premarket_end = min(now, utc_09_30_today)

    return {
        "yesterday_close": {
            "start": utc_16_yesterday,
            "end": utc_midnight_today,
        },
        "premarket": {
            "start": utc_midnight_today,
            "end": premarket_end,
        },
    }


def _parse_headline_ts(item: Dict[str, Any]) -> Optional[datetime]:
    """News providers return timestamps in varied shapes — normalise."""
    ts = item.get("timestamp") or item.get("datetime") or item.get("published_at")
    if ts is None:
        return None
    try:
        if isinstance(ts, (int, float)):
            # epoch seconds (Finnhub style)
            if ts > 10_000_000_000:
                ts = ts / 1000
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        s = str(ts).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _score_headlines(headlines: List[str]) -> float:
    """Reuse SentimentAnalysisService._analyze_keywords — guarantees scores
    are apples-to-apples with the per-symbol sentiment the app already
    displays in other surfaces."""
    try:
        from services.sentiment_analysis_service import get_sentiment_service
        svc = get_sentiment_service()
        score, _bull, _bear = svc._analyze_keywords(headlines)  # noqa: SLF001
        return float(score)
    except Exception as exc:
        logger.warning("overnight_sentiment._score_headlines error: %s", exc)
        return 0.0


async def _get_ticker_news(symbol: str) -> List[Dict[str, Any]]:
    """Pull up to MAX_HEADLINES_PER_SYMBOL recent news items for a symbol."""
    try:
        from services.news_service import get_news_service
        news_svc = get_news_service()
        if news_svc is None:
            return []
        return await news_svc.get_ticker_news(symbol, max_items=MAX_HEADLINES_PER_SYMBOL)
    except Exception as exc:
        logger.info("overnight_sentiment news fetch %s skipped: %s", symbol, exc)
        return []


async def compute_symbol(symbol: str) -> Dict[str, Any]:
    """Score yesterday_close vs premarket for a single symbol."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return _empty(sym)

    windows = compute_windows()
    yc_start, yc_end = windows["yesterday_close"]["start"], windows["yesterday_close"]["end"]
    pm_start, pm_end = windows["premarket"]["start"], windows["premarket"]["end"]

    items = await _get_ticker_news(sym)

    yc_headlines: List[str] = []
    pm_headlines: List[str] = []
    top_headline: Optional[str] = None
    top_headline_ts: Optional[datetime] = None

    for item in items:
        ts = _parse_headline_ts(item)
        if ts is None:
            continue
        headline = (item.get("headline") or item.get("title") or "").strip()
        if not headline:
            continue
        if yc_start <= ts < yc_end:
            yc_headlines.append(headline)
        elif pm_start <= ts < pm_end:
            pm_headlines.append(headline)
            # Pick the most recent premarket headline as "top_headline"
            if top_headline_ts is None or ts > top_headline_ts:
                top_headline = headline
                top_headline_ts = ts

    yc_score = _score_headlines(yc_headlines) if yc_headlines else 0.0
    pm_score = _score_headlines(pm_headlines) if pm_headlines else 0.0
    swing = round(pm_score - yc_score, 3)
    notable = abs(swing) >= SWING_THRESHOLD

    # Direction for the UI chip
    if swing > SWING_THRESHOLD:
        direction = "up"
    elif swing < -SWING_THRESHOLD:
        direction = "down"
    else:
        direction = "flat"

    return {
        "symbol": sym,
        "sentiment_yesterday_close": round(yc_score, 3),
        "sentiment_premarket": round(pm_score, 3),
        "swing": swing,
        "swing_direction": direction,
        "notable": notable,
        "news_count_yesterday_close": len(yc_headlines),
        "news_count_premarket": len(pm_headlines),
        "news_count_overnight": len(yc_headlines) + len(pm_headlines),
        "top_headline": top_headline,
        "top_headline_ts": top_headline_ts.isoformat() if top_headline_ts else None,
        "window": {
            "yesterday_close": {
                "start": yc_start.isoformat(),
                "end": yc_end.isoformat(),
            },
            "premarket": {
                "start": pm_start.isoformat(),
                "end": pm_end.isoformat(),
            },
        },
    }


async def compute_batch(symbols: List[str]) -> List[Dict[str, Any]]:
    """Score multiple symbols in parallel, capped at MAX_SYMBOLS."""
    syms = [s for s in (symbols or []) if s][:MAX_SYMBOLS]
    if not syms:
        return []
    results = await asyncio.gather(
        *(compute_symbol(s) for s in syms),
        return_exceptions=True,
    )
    out: List[Dict[str, Any]] = []
    for sym, res in zip(syms, results):
        if isinstance(res, Exception):
            logger.warning("overnight_sentiment compute failed for %s: %s", sym, res)
            out.append(_empty(sym, error=str(res)[:200]))
        else:
            out.append(res)
    # Rank: notable first, then by |swing|
    out.sort(key=lambda r: (
        0 if r.get("notable") else 1,
        -abs(r.get("swing") or 0.0),
    ))
    return out


def _empty(symbol: str, *, error: Optional[str] = None) -> Dict[str, Any]:
    w = compute_windows()
    return {
        "symbol": symbol,
        "sentiment_yesterday_close": 0.0,
        "sentiment_premarket": 0.0,
        "swing": 0.0,
        "swing_direction": "flat",
        "notable": False,
        "news_count_yesterday_close": 0,
        "news_count_premarket": 0,
        "news_count_overnight": 0,
        "top_headline": None,
        "top_headline_ts": None,
        "error": error,
        "window": {
            "yesterday_close": {
                "start": w["yesterday_close"]["start"].isoformat(),
                "end": w["yesterday_close"]["end"].isoformat(),
            },
            "premarket": {
                "start": w["premarket"]["start"].isoformat(),
                "end": w["premarket"]["end"].isoformat(),
            },
        },
    }
