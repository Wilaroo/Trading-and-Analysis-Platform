"""
SentCom Chart API — Stage 2b of the V5 Command Center rebuild.

Serves historical bars + pre-computed indicators (VWAP, EMA 20/50/200,
Bollinger Bands) for the TradingView `lightweight-charts` frontend panel.

We compute server-side because:
  1. Frontend stays dumb — just renders arrays.
  2. All historical bars already live in Mongo/IB cache via hybrid_data_service.
  3. Indicator values are reusable for other panels (backtests, setup scoring).

Endpoint:
  GET /api/sentcom/chart?symbol=X&timeframe=5min&days=5
    -> {
         success: bool,
         symbol, timeframe, bar_count,
         bars:      [{time, open, high, low, close, volume}, ...],
         indicators: {
           vwap:      [{time, value}, ...],   # session-anchored, reset per calendar day
           ema_20:    [{time, value}, ...],
           ema_50:    [...],
           ema_200:   [...],
           bb_upper:  [...],
           bb_middle: [...],
           bb_lower:  [...]
         }
       }
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sentcom", tags=["SentCom Chart"])

_hybrid_data_service = None
_db = None


def init_sentcom_chart_router(service, db=None) -> None:
    """Inject hybrid_data_service (+ optional db for trade-marker lookups)."""
    global _hybrid_data_service, _db
    _hybrid_data_service = service
    _db = db


# ─── Timestamp helpers ──────────────────────────────────────────────────────

def _to_utc_seconds(ts: Any) -> Optional[int]:
    """Coerce any bar timestamp shape into UTC seconds-since-epoch."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        v = int(ts)
        return v // 1000 if v > 10**12 else v
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return int(ts.timestamp())
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def _session_key(ts_seconds: int) -> str:
    """UTC calendar date — our coarse session boundary for intraday VWAP."""
    return datetime.fromtimestamp(ts_seconds, tz=timezone.utc).date().isoformat()


# ─── Indicator math (pure Python, O(N), no pandas dep) ──────────────────────

def _ema(values: List[float], span: int) -> List[Optional[float]]:
    """Exponential Moving Average, seeded with the first span-size simple mean
    (matches pandas `ewm(span=span, adjust=False).mean()` after seed)."""
    if span <= 0:
        return [None] * len(values)
    if len(values) < span:
        return [None] * len(values)
    alpha = 2.0 / (span + 1.0)
    out: List[Optional[float]] = [None] * (span - 1)
    seed = sum(values[:span]) / span
    out.append(seed)
    prev = seed
    for v in values[span:]:
        prev = alpha * v + (1 - alpha) * prev
        out.append(prev)
    return out


def _rolling_mean_std(values: List[float], window: int) -> tuple[List[Optional[float]], List[Optional[float]]]:
    """Simple rolling mean + population std over a fixed window."""
    n = len(values)
    means: List[Optional[float]] = [None] * n
    stds: List[Optional[float]] = [None] * n
    if window <= 0 or n < window:
        return means, stds
    window_sum = sum(values[:window])
    window_sq = sum(v * v for v in values[:window])
    mean = window_sum / window
    var = max(window_sq / window - mean * mean, 0.0)
    means[window - 1] = mean
    stds[window - 1] = var ** 0.5
    for i in range(window, n):
        window_sum += values[i] - values[i - window]
        window_sq += values[i] * values[i] - values[i - window] ** 2
        mean = window_sum / window
        var = max(window_sq / window - mean * mean, 0.0)
        means[i] = mean
        stds[i] = var ** 0.5
    return means, stds


def _vwap(bars: List[Dict[str, Any]], per_session: bool) -> List[Optional[float]]:
    """Volume-weighted average price.

    If per_session=True (intraday timeframes), resets cumulation at each UTC
    calendar-day boundary. For daily/weekly bars, runs cumulatively.
    """
    out: List[Optional[float]] = []
    cum_pv = 0.0
    cum_v = 0.0
    last_session: Optional[str] = None
    for b in bars:
        price = (float(b["high"]) + float(b["low"]) + float(b["close"])) / 3.0
        vol = float(b.get("volume", 0) or 0)
        if per_session:
            sess = _session_key(int(b["time"]))
            if sess != last_session:
                cum_pv = 0.0
                cum_v = 0.0
                last_session = sess
        cum_pv += price * vol
        cum_v += vol
        out.append(cum_pv / cum_v if cum_v > 0 else None)
    return out


def _as_series(times: List[int], values: List[Optional[float]]) -> List[Dict[str, Any]]:
    """Zip time+value into the lightweight-charts `{time, value}` shape.
    Drops points where the indicator hasn't warmed up yet."""
    return [
        {"time": t, "value": float(v)}
        for t, v in zip(times, values)
        if v is not None
    ]


# ─── Trade markers ──────────────────────────────────────────────────────────

def _fetch_trade_markers(
    symbol: str,
    start_ts: int,
    end_ts: int,
) -> List[Dict[str, Any]]:
    """Return lightweight-charts marker objects for closed bot_trades.

    Each closed trade emits UP TO two markers — one at entry, one at exit —
    coloured by win/loss (R-multiple sign). Open trades produce an entry
    marker only. If `_db` was not provided we return [] silently so the
    chart still works in minimal environments.
    """
    if _db is None:
        return []
    try:
        coll = _db["bot_trades"]
        # Filter on symbol + (closed_at OR last_updated) within the chart window.
        window_iso_start = datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat()
        window_iso_end = datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat()
        cursor = coll.find(
            {
                "symbol": symbol.upper(),
                "$or": [
                    {"closed_at": {"$gte": window_iso_start, "$lte": window_iso_end}},
                    {"last_updated": {"$gte": window_iso_start, "$lte": window_iso_end}},
                ],
            },
            {
                "_id": 0,
                "symbol": 1, "direction": 1, "setup_type": 1,
                "entry_price": 1, "stop_price": 1, "exit_price": 1,
                "r_multiple": 1, "pnl": 1,
                "closed_at": 1, "last_updated": 1, "placed_at": 1,
                "entry_at": 1, "entry_time": 1,
            },
        ).limit(500)
    except Exception as exc:  # pragma: no cover
        logger.warning("trade-marker fetch failed: %s", exc)
        return []

    markers: List[Dict[str, Any]] = []
    for doc in cursor:
        direction = (doc.get("direction") or "").lower()
        is_long = direction in {"long", "buy", "up"}
        is_short = direction in {"short", "sell", "down"}
        if not (is_long or is_short):
            continue

        entry_ts = _to_utc_seconds(
            doc.get("entry_at") or doc.get("entry_time") or doc.get("placed_at")
        )
        exit_ts = _to_utc_seconds(doc.get("closed_at") or doc.get("last_updated"))
        r = doc.get("r_multiple")
        pnl = doc.get("pnl")
        setup = doc.get("setup_type") or "trade"

        # Entry marker
        if entry_ts and start_ts <= entry_ts <= end_ts:
            markers.append({
                "time": entry_ts,
                "position": "belowBar" if is_long else "aboveBar",
                "shape": "arrowUp" if is_long else "arrowDown",
                "color": "#06b6d4" if is_long else "#a855f7",
                "text": f"{setup} entry @ {doc.get('entry_price')}",
            })
        # Exit marker (only for closed trades with exit price)
        if exit_ts and doc.get("exit_price") is not None and start_ts <= exit_ts <= end_ts:
            is_win = (r is not None and r > 0) or (pnl is not None and pnl > 0)
            markers.append({
                "time": exit_ts,
                "position": "aboveBar" if is_long else "belowBar",
                "shape": "arrowDown" if is_long else "arrowUp",
                "color": "#10b981" if is_win else "#f43f5e",
                "text": (
                    f"exit @ {doc.get('exit_price')}"
                    + (f" · {float(r):+.2f}R" if isinstance(r, (int, float)) else "")
                ),
            })

    # lightweight-charts needs markers sorted ascending by time
    markers.sort(key=lambda m: m["time"])
    return markers


# ─── Endpoint ───────────────────────────────────────────────────────────────

# Accept exactly what the frontend ChartPanel TIMEFRAMES[].value emits.
_SUPPORTED_TFS = {"1min", "5min", "15min", "1hour", "1day"}


# ─── Model health classification (per-setup scorecard) ──────────────────────

# Floors are kept in sync with MIN_UP_RECALL / MIN_DOWN_RECALL in
# services/ai_modules/timeseries_gbm.py — any change there must mirror here.
_HEALTH_FLOOR_UP = 0.10
_HEALTH_FLOOR_DOWN = 0.10
_HEALTH_COLLAPSE = 0.05


def _classify_model_mode(metrics: Optional[Dict[str, Any]]) -> str:
    """Coarse health mode from stored training metrics.

    MISSING    — no model doc / empty metrics
    MODE_B     — both classes collapsed (recall < 0.05 for UP and DOWN): useless
    MODE_C     — one class usable (argmax works) but the other is collapsed
    HEALTHY    — both classes ≥ 0.10 recall (matches the protection-gate floor)
    """
    if not metrics:
        return "MISSING"
    try:
        up = float(metrics.get("recall_up", 0.0) or 0.0)
        dn = float(metrics.get("recall_down", 0.0) or 0.0)
    except (TypeError, ValueError):
        return "MISSING"
    if up >= _HEALTH_FLOOR_UP and dn >= _HEALTH_FLOOR_DOWN:
        return "HEALTHY"
    if up < _HEALTH_COLLAPSE and dn < _HEALTH_COLLAPSE:
        return "MODE_B"
    return "MODE_C"


# Generic direction_predictor_{bar_slug} models are trained separately
# from the setup-specific ones. We want both rows in the scorecard.
_GENERIC_DIRECTION_TIMEFRAMES = [
    ("1 min",   "direction_predictor_1min"),
    ("5 mins",  "direction_predictor_5min"),
    ("15 mins", "direction_predictor_15min"),
    ("1 hour",  "direction_predictor_1hour"),
    ("1 day",   "direction_predictor_daily"),
]


@router.get("/model-health")
async def get_model_health() -> Dict[str, Any]:
    """Return a compact health card for every (setup_type, bar_size) model
    declared in `SETUP_TRAINING_PROFILES` + the generic directional models.
    The frontend ChartPanel renders this as a colour-coded badge grid.
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="db not initialised")

    # Import here to keep the router import-cycle-free at module load.
    from services.ai_modules.setup_training_config import (
        SETUP_TRAINING_PROFILES,
        get_model_name,
    )

    coll = _db["timeseries_models"]

    # Prefetch every relevant model doc in one query (by name IN [...]).
    expected_names: List[str] = [m for _, m in _GENERIC_DIRECTION_TIMEFRAMES]
    for setup_type, profiles in SETUP_TRAINING_PROFILES.items():
        for p in profiles:
            expected_names.append(get_model_name(setup_type, p["bar_size"]))

    by_name: Dict[str, Dict[str, Any]] = {}
    try:
        for doc in coll.find(
            {"name": {"$in": expected_names}},
            {
                "_id": 0, "name": 1, "version": 1, "saved_at": 1,
                "metrics.accuracy": 1,
                "metrics.recall_up": 1, "metrics.recall_down": 1,
                "metrics.f1_up": 1, "metrics.f1_down": 1,
                "metrics.macro_f1": 1,
            },
        ):
            by_name[doc["name"]] = doc
    except Exception as exc:  # pragma: no cover
        logger.warning("model-health fetch failed: %s", exc)

    def _row(setup_type: str, bar_size: str, model_name: str) -> Dict[str, Any]:
        doc = by_name.get(model_name)
        metrics = (doc or {}).get("metrics") or {}
        return {
            "setup_type": setup_type,
            "bar_size": bar_size,
            "model_name": model_name,
            "version": (doc or {}).get("version"),
            "promoted_at": (doc or {}).get("saved_at"),
            "mode": _classify_model_mode(metrics),
            "metrics": {
                "accuracy": metrics.get("accuracy"),
                "recall_up": metrics.get("recall_up"),
                "recall_down": metrics.get("recall_down"),
                "f1_up": metrics.get("f1_up"),
                "f1_down": metrics.get("f1_down"),
                "macro_f1": metrics.get("macro_f1"),
            },
        }

    rows: List[Dict[str, Any]] = []
    for bar_size, model_name in _GENERIC_DIRECTION_TIMEFRAMES:
        rows.append(_row("__GENERIC__", bar_size, model_name))
    for setup_type, profiles in SETUP_TRAINING_PROFILES.items():
        for p in profiles:
            rows.append(_row(setup_type, p["bar_size"], get_model_name(setup_type, p["bar_size"])))

    counts = {"HEALTHY": 0, "MODE_C": 0, "MODE_B": 0, "MISSING": 0}
    for r in rows:
        counts[r["mode"]] = counts.get(r["mode"], 0) + 1

    return {
        "success": True,
        "total": len(rows),
        "counts": counts,
        "models": rows,
    }


@router.get("/chart")
async def get_chart_bars(
    symbol: str = Query(..., min_length=1, max_length=10),
    timeframe: str = Query("5min"),
    days: int = Query(5, ge=1, le=365),
) -> Dict[str, Any]:
    """Return OHLCV bars + overlay indicator series for `symbol`/`timeframe`."""
    if _hybrid_data_service is None:
        raise HTTPException(status_code=503, detail="hybrid_data_service not initialised")

    tf = timeframe.lower()
    if tf not in _SUPPORTED_TFS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported timeframe '{timeframe}'. Supported: {sorted(_SUPPORTED_TFS)}",
        )

    result = await _hybrid_data_service.get_bars(
        symbol=symbol.upper(),
        timeframe=tf,
        days_back=days,
    )

    if not result.success:
        return {
            "success": False,
            "symbol": symbol.upper(),
            "timeframe": tf,
            "bar_count": 0,
            "bars": [],
            "indicators": {},
            "error": result.error,
        }

    # Normalise + sort
    normalised: List[Dict[str, Any]] = []
    for b in result.bars:
        ts = _to_utc_seconds(b.get("timestamp") or b.get("date") or b.get("time"))
        if ts is None:
            continue
        try:
            normalised.append({
                "time": ts,
                "open": float(b["open"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": float(b["close"]),
                "volume": int(b.get("volume", 0) or 0),
            })
        except (KeyError, ValueError, TypeError):
            continue
    normalised.sort(key=lambda r: r["time"])

    if not normalised:
        return {
            "success": False,
            "symbol": symbol.upper(),
            "timeframe": tf,
            "bar_count": 0,
            "bars": [],
            "indicators": {},
            "error": "no parseable bars",
        }

    times = [r["time"] for r in normalised]
    closes = [r["close"] for r in normalised]

    # Compute indicator arrays
    ema_20 = _ema(closes, 20)
    ema_50 = _ema(closes, 50)
    ema_200 = _ema(closes, 200)
    bb_mid, bb_std = _rolling_mean_std(closes, 20)
    bb_upper = [
        (m + 2.0 * s) if (m is not None and s is not None) else None
        for m, s in zip(bb_mid, bb_std)
    ]
    bb_lower = [
        (m - 2.0 * s) if (m is not None and s is not None) else None
        for m, s in zip(bb_mid, bb_std)
    ]
    per_session = tf in {"1min", "5min", "15min", "1hour"}
    vwap = _vwap(normalised, per_session=per_session)

    # Overlay markers (executed trades). Silent no-op if db isn't wired.
    markers = _fetch_trade_markers(symbol, times[0], times[-1])

    return {
        "success": True,
        "symbol": symbol.upper(),
        "timeframe": tf,
        "bar_count": len(normalised),
        "bars": normalised,
        "indicators": {
            "vwap": _as_series(times, vwap),
            "ema_20": _as_series(times, ema_20),
            "ema_50": _as_series(times, ema_50),
            "ema_200": _as_series(times, ema_200),
            "bb_upper": _as_series(times, bb_upper),
            "bb_middle": _as_series(times, bb_mid),
            "bb_lower": _as_series(times, bb_lower),
        },
        "markers": markers,
    }
