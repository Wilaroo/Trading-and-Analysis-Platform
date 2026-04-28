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
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sentcom", tags=["SentCom Chart"])


# ─── Bar-size normalisation (frontend may send compact or verbose forms) ────

_BAR_SIZE_ALIASES = {
    "1min": "1 min", "1m": "1 min", "1 min": "1 min",
    "5min": "5 mins", "5m": "5 mins", "5 mins": "5 mins", "5 min": "5 mins",
    "15min": "15 mins", "15m": "15 mins", "15 mins": "15 mins", "15 min": "15 mins",
    "30min": "30 mins", "30m": "30 mins", "30 mins": "30 mins",
    "1h": "1 hour", "1hour": "1 hour", "1 hour": "1 hour",
    "1d": "1 day", "1day": "1 day", "daily": "1 day", "1 day": "1 day",
}


def _normalise_bar_size(raw: str) -> Optional[str]:
    if not raw:
        return None
    key = str(raw).strip().lower()
    return _BAR_SIZE_ALIASES.get(key) or _BAR_SIZE_ALIASES.get(key.replace(" ", ""))

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


@router.get("/chart/levels")
async def get_chart_levels_endpoint(
    symbol: str = Query(..., min_length=1, max_length=12),
    lookback_days: int = Query(default=45, ge=7, le=180),
):
    """Thin S/R overlay for the chart: PDH / PDL / PDC / PMH / PML.

    Computed fast from `historical_bars` (daily bars). Used by the
    V5 ChartPanel to draw horizontal support/resistance price lines.
    Returns a dict with nullable values — missing levels simply don't
    render on the chart.
    """
    try:
        from services.chart_levels_service import get_chart_levels
        levels = get_chart_levels(_db, symbol, lookback_days=lookback_days)
        return {"success": True, "symbol": symbol.upper(), "levels": levels}
    except Exception as e:
        logger.error(f"chart levels failed for {symbol}: {e}")
        return {"success": False, "error": str(e), "levels": {}}


@router.get("/chart/smart-levels")
async def get_smart_levels_endpoint(
    symbol: str = Query(..., min_length=1, max_length=12),
    timeframe: str = Query("5min"),
):
    """Fused, ranked Smart S/R levels for `(symbol, timeframe)` —
    combines Volume Profile (POC + HVN), swing pivots, and floor pivots
    (PP/S1/S2/R1/R2/S3/R3) into a single clustered output. The frontend
    chart uses this to draw timeframe-appropriate S/R lines that
    automatically refresh when the user toggles 1m → 5m → 1d.
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="db not initialised")
    try:
        from services.smart_levels_service import compute_smart_levels
        result = compute_smart_levels(_db, symbol.upper(), timeframe.lower())
        return {"success": True, "symbol": symbol.upper(), **result}
    except Exception as e:
        logger.error(f"smart levels failed for {symbol} {timeframe}: {e}")
        return {"success": False, "error": str(e), "support": [], "resistance": []}



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
    session: str = Query(
        "rth_plus_premarket",
        description=(
            "Which trading session(s) to include for intraday timeframes:\n"
            "  • `rth_plus_premarket` (default) — 4:00am-16:00 ET, weekdays. "
            "Drops post-market and overnight; includes premarket so gap "
            "context survives. Each bar is tagged with `session: 'pre'|'rth'`.\n"
            "  • `rth` — 9:30-16:00 ET only.\n"
            "  • `all` — full 24h, no filter (legacy)."
        ),
    ),
    # Legacy alias kept for back-compat. When provided, overrides `session`:
    #   rth_only=true  → session='rth'
    #   rth_only=false → session='all'
    rth_only: bool = Query(None),
) -> Dict[str, Any]:
    """Return OHLCV bars + overlay indicator series for `symbol`/`timeframe`.

    `session` (added 2026-04-28, expanded 2026-04-28-b) controls which
    trading window the chart includes. Default `rth_plus_premarket`
    keeps the gap context the operator wanted (4am-9:30am ET premarket
    + 9:30-16:00 ET RTH) while still dropping the noisy overnight /
    post-market bars that produce the "lots of time gaps" complaint.
    """
    if _hybrid_data_service is None:
        raise HTTPException(status_code=503, detail="hybrid_data_service not initialised")

    # Legacy `rth_only` shim.
    if rth_only is True:
        session = "rth"
    elif rth_only is False:
        session = "all"

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

    # ---- Phase 1: merge latest-session bars via pusher RPC --------------
    # For intraday timeframes we ask the Windows pusher for the freshest
    # slice IB has (extended hours included). The dedup pass below merges
    # the seam — if the historical collector already stored the same bars
    # this becomes a no-op. When the pusher RPC is disabled / unreachable
    # (feature flag off, Windows PC down, etc.), we silently fall through
    # to the historical-only result.
    live_appended = 0
    live_source = None
    live_market_state = None
    try:
        tf_cfg = _hybrid_data_service.TIMEFRAMES.get(tf)
        live_bar_size = tf_cfg.get("ib_bar_size") if tf_cfg else None
        if live_bar_size and tf in {"1min", "5min", "15min", "1hour"}:
            live_res = await _hybrid_data_service.fetch_latest_session_bars(
                symbol.upper(),
                live_bar_size,
                active_view=True,  # /chart calls ARE active-view
                use_rth=False,
            )
            if live_res.get("success"):
                live_bars = live_res.get("bars") or []
                result.bars.extend(live_bars)
                live_appended = len(live_bars)
                live_source = live_res.get("source")
                live_market_state = live_res.get("market_state")
    except Exception as _live_exc:
        logger.info("live-bars merge skipped: %s", _live_exc)

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

    # De-duplicate by `time` — chunked backfills occasionally emit two rows
    # with the same second-resolution timestamp at session boundaries
    # (last bar of chunk N == first bar of chunk N+1). Two identical times
    # crash lightweight-charts on the frontend AND corrupt the EMA/BB
    # windows here. Keep the *last* occurrence: the backfill walks
    # backward, so later writes overwrite earlier ones with freshest data.
    deduped: List[Dict[str, Any]] = []
    for r in normalised:
        if deduped and deduped[-1]["time"] == r["time"]:
            deduped[-1] = r
        else:
            deduped.append(r)
    normalised = deduped

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

    # 2026-04-28: session filter for intraday timeframes. Closes the
    # visual overnight/weekend/post-market gaps while preserving
    # premarket (operator-flagged: gap context matters). Each kept bar
    # is tagged with `session: "pre" | "rth"` so the frontend can shade
    # the premarket strip differently. Daily/weekly timeframes are
    # already 1-bar-per-session so we don't filter them.
    if tf in {"1min", "5min", "15min", "1hour"} and session != "all":
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
        # Window in minutes-of-day, ET.
        if session == "rth_plus_premarket":
            window_open = 4 * 60          # 4:00 AM ET
            window_close = 16 * 60        # 4:00 PM ET
        else:  # session == "rth"
            window_open = 9 * 60 + 30
            window_close = 16 * 60

        before = len(normalised)
        kept: List[Dict[str, Any]] = []
        for r in normalised:
            dt = datetime.fromtimestamp(r["time"], tz=et)
            if dt.weekday() >= 5:
                continue
            mod = dt.hour * 60 + dt.minute
            if not (window_open <= mod < window_close):
                continue
            r["session"] = "pre" if mod < (9 * 60 + 30) else "rth"
            kept.append(r)
        if not kept:
            # Fall back to unfiltered if the filter wipes everything
            # (e.g., test data is purely overnight). Better gappy data
            # than empty chart.
            return {
                "success": False,
                "symbol": symbol.upper(),
                "timeframe": tf,
                "bar_count": 0,
                "bars": [],
                "indicators": {},
                "error": f"no bars in session={session}",
                "session_filter_dropped": before,
            }
        normalised = kept
    else:
        # session == "all" or daily/weekly — annotate everything as RTH
        # so the frontend's session-shading code has a stable contract.
        for r in normalised:
            r.setdefault("session", "rth")

    # 2026-04-28d: For daily timeframes, normalize each bar's `time` to
    # midnight UTC of its calendar day. IB returns daily bars with the
    # session-open timestamp (e.g. "2026-03-25T13:30:00Z" = 9:30am ET),
    # which lightweight-charts then treats as an intraday tick and
    # emits "1:30 PM" labels on the x-axis. By snapping to midnight UTC,
    # the chart sees one bar per calendar day and only emits DayOfMonth
    # / Month / Year tick types — exactly what the operator expects.
    if tf == "1day":
        seen_days = set()
        snapped: List[Dict[str, Any]] = []
        for r in normalised:
            day_ts = (r["time"] // 86400) * 86400
            if day_ts in seen_days:
                continue   # de-dupe if two bars collapse onto the same day
            seen_days.add(day_ts)
            r["time"] = day_ts
            snapped.append(r)
        normalised = snapped

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
        # Freshness flags — frontend can show "STALE" banner / "PARTIAL" badge.
        "stale": bool(getattr(result, "stale", False)),
        "stale_reason": getattr(result, "stale_reason", None),
        "latest_available_date": getattr(result, "latest_available_date", None),
        "partial": bool(getattr(result, "partial", False)),
        "coverage": getattr(result, "coverage", None),
        # Phase 1: live-bar overlay observability
        "live_appended": live_appended,
        "live_source": live_source,
        "market_state": live_market_state,
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


@router.get("/chart-diagnostic")
async def chart_diagnostic(
    symbol: str = Query(..., min_length=1, max_length=10),
    timeframe: str = Query("5min"),
) -> Dict[str, Any]:
    """Why is my chart empty? Dump what `ib_historical_data` actually contains
    for (symbol, bar_size) so the user can see if data is missing / wrong
    bar_size / stale / different date type.

    Returns rich diagnostics including: latest & earliest date (via true BSON
    sort, so datetime objects and strings are both handled), date type
    distribution, recent `collected_at` timestamps (shows when the last
    backfill actually ran), top-10 freshest bars, distinct bar_sizes, per-
    bar-size counts, and pusher health. Read-only, safe.
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="DB handle not wired")

    tf_to_barsize = {
        "1min": "1 min", "5min": "5 mins", "15min": "15 mins",
        "30min": "30 mins", "1hour": "1 hour", "1day": "1 day",
    }
    bar_size = tf_to_barsize.get(timeframe.lower())
    if not bar_size:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown timeframe '{timeframe}'. Supported: {list(tf_to_barsize)}",
        )

    sym = symbol.upper()
    coll = _db["ib_historical_data"]
    q = {"symbol": sym, "bar_size": bar_size}

    total = coll.count_documents(q)

    # BSON-native sort. If `date` is stored as a string in some docs and a
    # datetime in others, MongoDB's type-bracket sort returns the newest of
    # each type — we surface both so the user can see the heterogeneity.
    earliest_asc = coll.find_one(q, {"_id": 0, "date": 1, "collected_at": 1}, sort=[("date", 1)])
    latest_desc = coll.find_one(q, {"_id": 0, "date": 1, "collected_at": 1}, sort=[("date", -1)])

    # Recency via `collected_at` — a real datetime field the collector writes
    # on every insert/update. If this is fresh but `date` looks stale, the
    # backfill IS running but writing backdated bars (or the `date` query
    # window is wrong in hybrid_data_service).
    latest_by_collected = list(
        coll.find(q, {"_id": 0, "date": 1, "collected_at": 1})
            .sort("collected_at", -1).limit(10)
    )

    # Date type breakdown — catches the "bars exist but as datetime objects
    # while hybrid_data_service queries with ISO strings" footgun.
    date_type_counts = {
        "string":   coll.count_documents({**q, "date": {"$type": "string"}}),
        "datetime": coll.count_documents({**q, "date": {"$type": "date"}}),
        "int":      coll.count_documents({**q, "date": {"$type": "int"}}),
        "long":     coll.count_documents({**q, "date": {"$type": "long"}}),
        "double":   coll.count_documents({**q, "date": {"$type": "double"}}),
    }

    # All bar_sizes we have for this symbol + their counts
    distinct_bar_sizes = sorted(coll.distinct("bar_size", {"symbol": sym}))
    by_bar_size: Dict[str, int] = {}
    for bs in distinct_bar_sizes:
        by_bar_size[bs] = coll.count_documents({"symbol": sym, "bar_size": bs})

    # Top-5 freshest bars (by date) so user sees actual values
    freshest = list(
        coll.find(q, {"_id": 0, "date": 1, "close": 1, "volume": 1, "collected_at": 1})
            .sort("date", -1).limit(5)
    )

    # Rough age of latest data (using collected_at if present)
    age_seconds = None
    if latest_by_collected:
        ca = latest_by_collected[0].get("collected_at")
        if ca:
            try:
                if isinstance(ca, str):
                    ca_dt = datetime.fromisoformat(ca.replace("Z", "+00:00"))
                else:
                    ca_dt = ca
                if ca_dt.tzinfo is None:
                    ca_dt = ca_dt.replace(tzinfo=timezone.utc)
                age_seconds = (datetime.now(timezone.utc) - ca_dt).total_seconds()
            except Exception:
                age_seconds = None

    return {
        "success": True,
        "symbol": sym,
        "requested_timeframe": timeframe,
        "resolved_bar_size": bar_size,
        "total_bars": total,
        "earliest_date_bson_sort": (earliest_asc or {}).get("date"),
        "latest_date_bson_sort": (latest_desc or {}).get("date"),
        "latest_10_by_collected_at": latest_by_collected,
        "collected_at_age_seconds": age_seconds,
        "date_type_breakdown": date_type_counts,
        "distinct_bar_sizes_for_symbol": distinct_bar_sizes,
        "bar_counts_by_bar_size": by_bar_size,
        "freshest_5_bars_by_date": freshest,
    }


@router.get("/chart-diagnostic-universe")
async def chart_diagnostic_universe(
    timeframe: str = Query("5min"),
    limit: int = Query(20, ge=1, le=200),
) -> Dict[str, Any]:
    """Top-N symbols by latest bar-date for (bar_size) — shows whether the
    backfill ran recently across the universe or just for SPY. Groups by
    symbol, returns the max `collected_at` and max `date` per symbol."""
    if _db is None:
        raise HTTPException(status_code=503, detail="DB handle not wired")

    tf_to_barsize = {
        "1min": "1 min", "5min": "5 mins", "15min": "15 mins",
        "30min": "30 mins", "1hour": "1 hour", "1day": "1 day",
    }
    bar_size = tf_to_barsize.get(timeframe.lower())
    if not bar_size:
        raise HTTPException(status_code=400, detail=f"Unknown timeframe '{timeframe}'")

    pipeline = [
        {"$match": {"bar_size": bar_size}},
        {"$group": {
            "_id": "$symbol",
            "max_date": {"$max": "$date"},
            "max_collected_at": {"$max": "$collected_at"},
            "bars": {"$sum": 1},
        }},
        {"$sort": {"max_collected_at": -1}},
        {"$limit": int(limit)},
        {"$project": {
            "_id": 0,
            "symbol": "$_id",
            "max_date": 1,
            "max_collected_at": 1,
            "bars": 1,
        }},
    ]
    rows = list(_db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True))
    return {
        "success": True,
        "bar_size": bar_size,
        "count": len(rows),
        "symbols": rows,
    }



# ─── Scorecard tile → targeted retrain ──────────────────────────────────────

class ScorecardRetrainRequest(BaseModel):
    """POST body for /api/sentcom/retrain-model.

    `setup_type` = "__GENERIC__" → enqueues a `training` job (full-universe retrain
    of the generic directional predictor for that bar_size).
    Any other value → enqueues a `setup_training` job for that (setup, bar_size) pair.
    """
    setup_type: str = Field(..., min_length=1)
    bar_size: str = Field(..., min_length=1)


@router.post("/retrain-model")
async def retrain_model_from_scorecard(request: ScorecardRetrainRequest) -> Dict[str, Any]:
    """Enqueue a targeted retrain for a single scorecard tile.

    Wired from `ModelHealthScorecard.jsx` — user clicks a MODE_C / MODE_B / MISSING
    tile and the UI fires this endpoint. Returns a `job_id` the caller can poll via
    `GET /api/jobs/{job_id}`.
    """
    # Lazy imports so this router stays import-cycle-free at module load.
    from services.ai_modules import ML_AVAILABLE
    if not ML_AVAILABLE:
        return {
            "success": False,
            "ml_not_available": True,
            "error": "ML libraries not installed on this node",
        }

    bar_size = _normalise_bar_size(request.bar_size)
    if not bar_size:
        raise HTTPException(
            status_code=400,
            detail=f"Unrecognised bar_size '{request.bar_size}'. "
                   f"Supported: 1 min, 5 mins, 15 mins, 1 hour, 1 day.",
        )

    setup_raw = (request.setup_type or "").strip()
    is_generic = setup_raw.upper() == "__GENERIC__"

    try:
        from services.job_queue_manager import job_queue_manager
    except Exception as exc:  # pragma: no cover
        logger.error("job_queue_manager unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="job queue unavailable")

    if is_generic:
        result = await job_queue_manager.create_job(
            job_type="training",
            params={
                "bar_size": bar_size,
                "full_universe": True,
                "max_bars_per_symbol": 99999,
                "symbol_batch_size": 500,
            },
            priority=6,
            metadata={"description": f"Scorecard retrain: generic direction ({bar_size})"},
        )
        kind = "generic_direction"
        target = f"direction_predictor {bar_size}"
    else:
        setup_upper = setup_raw.upper()
        # Validate against declared profiles so a typo fails loudly.
        try:
            from services.ai_modules.setup_training_config import SETUP_TRAINING_PROFILES
        except Exception as exc:  # pragma: no cover
            logger.error("setup_training_config import failed: %s", exc)
            raise HTTPException(status_code=503, detail="setup config unavailable")

        if setup_upper not in SETUP_TRAINING_PROFILES:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown setup_type '{setup_upper}'. "
                       f"Valid: {sorted(SETUP_TRAINING_PROFILES.keys())}",
            )

        valid_bars = {p["bar_size"] for p in SETUP_TRAINING_PROFILES[setup_upper]}
        if bar_size not in valid_bars:
            raise HTTPException(
                status_code=400,
                detail=f"bar_size '{bar_size}' not declared for setup '{setup_upper}'. "
                       f"Valid: {sorted(valid_bars)}",
            )

        result = await job_queue_manager.create_job(
            job_type="setup_training",
            params={
                "setup_type": setup_upper,
                "bar_size": bar_size,
                "max_symbols": None,
                "max_bars_per_symbol": None,
            },
            priority=7,
            metadata={"description": f"Scorecard retrain: {setup_upper} {bar_size}"},
        )
        kind = "setup_specific"
        target = f"{setup_upper} {bar_size}"

    if not result.get("success"):
        return {"success": False, "error": result.get("error", "Failed to enqueue job")}

    job = result["job"]
    return {
        "success": True,
        "job_id": job["job_id"],
        "kind": kind,
        "target": target,
        "setup_type": setup_raw.upper(),
        "bar_size": bar_size,
        "message": f"Retrain queued for {target}. Poll /api/jobs/{job['job_id']} for progress.",
    }
