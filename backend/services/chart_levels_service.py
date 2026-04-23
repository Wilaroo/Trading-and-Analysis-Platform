"""
Chart Levels Service — fast PDH/PDL/PML computation for chart overlays.

Kept deliberately thin (not routed through the full SR engine) so the
chart can paint S/R lines in < 50ms.

Returns:
  - PDH  (Previous Day High)
  - PDL  (Previous Day Low)
  - PDC  (Previous Day Close)
  - PML  (Previous Month Low)
  - PMH  (Previous Month High)

Source
------
Reads daily bars from the `ib_historical_data` collection (177M+ rows,
populated by IB Historical Collector + hybrid_data_service cache path).
Falls back to an empty payload when data is missing — the chart simply
won't draw the line.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _prev_trading_day_bar(bars: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return the second-most-recent daily bar (yesterday by calendar)."""
    if not bars or len(bars) < 2:
        return None
    return bars[-2]


def _previous_month_extremes(bars: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    """Return the high/low across all daily bars that belong to the most
    recently *completed* month (i.e. any month before the current one).

    Uses the date field from each bar; silently drops unparseable rows.
    """
    if not bars:
        return {"pmh": None, "pml": None}

    now = datetime.now(timezone.utc)
    this_year, this_month = now.year, now.month

    prev_month_bars: List[Dict[str, Any]] = []
    seen_months: set = set()

    for b in bars:
        ts = b.get("timestamp") or b.get("date") or b.get("time")
        if ts is None:
            continue
        try:
            if isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(float(ts) / (1000 if ts > 1e12 else 1), tz=timezone.utc)
            else:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        # Skip current month's bars
        if dt.year == this_year and dt.month == this_month:
            continue

        seen_months.add((dt.year, dt.month))
        prev_month_bars.append(b)

    if not prev_month_bars or not seen_months:
        return {"pmh": None, "pml": None}

    # Use the most recent completed month only
    target_month = max(seen_months)
    target_bars = [
        b for b in prev_month_bars
        if _bar_month(b) == target_month
    ]
    if not target_bars:
        return {"pmh": None, "pml": None}

    try:
        pmh = max(float(b["high"]) for b in target_bars)
        pml = min(float(b["low"]) for b in target_bars)
        return {"pmh": pmh, "pml": pml}
    except (KeyError, ValueError, TypeError):
        return {"pmh": None, "pml": None}


def _bar_month(b: Dict[str, Any]) -> Optional[tuple]:
    ts = b.get("timestamp") or b.get("date") or b.get("time")
    if ts is None:
        return None
    try:
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(float(ts) / (1000 if ts > 1e12 else 1), tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return (dt.year, dt.month)
    except Exception:
        return None


def compute_chart_levels(bars: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pure function: given daily bars (ordered chronologically), return
    the S/R level overlay for the chart."""
    if not bars:
        return {"pdh": None, "pdl": None, "pdc": None, "pmh": None, "pml": None}

    prev = _prev_trading_day_bar(bars)
    out: Dict[str, Any] = {
        "pdh": float(prev["high"]) if prev and "high" in prev else None,
        "pdl": float(prev["low"]) if prev and "low" in prev else None,
        "pdc": float(prev["close"]) if prev and "close" in prev else None,
    }
    out.update(_previous_month_extremes(bars))
    return out


def get_chart_levels(db, symbol: str, lookback_days: int = 45) -> Dict[str, Any]:
    """Fetch daily bars for `symbol` and compute the level set.

    Always returns a dict — keys that can't be computed are None.
    """
    if db is None or not symbol:
        return compute_chart_levels([])
    try:
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        # Daily bars in ib_historical_data are stored with `date` as an
        # ISO `YYYY-MM-DD` string (see services/hybrid_data_service.py:286).
        cursor = db["ib_historical_data"].find(
            {"symbol": symbol.upper(), "bar_size": "1 day", "date": {"$gte": cutoff_date}},
            {"_id": 0, "date": 1, "high": 1, "low": 1, "close": 1, "open": 1, "volume": 1},
        ).sort("date", 1)
        bars = list(cursor)
        # Downstream helpers expect a `timestamp` alias — normalize.
        for bar in bars:
            if "date" in bar and "timestamp" not in bar:
                bar["timestamp"] = bar["date"]
    except Exception as e:
        logger.debug(f"[ChartLevels] fetch failed for {symbol}: {e}")
        bars = []
    return compute_chart_levels(bars)
