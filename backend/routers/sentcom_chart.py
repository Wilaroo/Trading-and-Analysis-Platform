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
import os
import time
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

    v19.34.25 (May 2026) — Operator request: stop showing entry markers
    in cyan/purple (which read as "exit" colors on every other trading
    platform). New convention:

      • LONG  entry → green `arrowUp`   (#10b981)
      • SHORT entry → red   `arrowDown` (#f43f5e)
      • Stop-loss exit (loss) → amber `arrowDown`/`arrowUp` with SL tag
      • Target  exit (win)   → emerald `arrowDown`/`arrowUp` with PT tag
      • Partial scale-out    → small circle dot (no text label — full
        details surface via the lightweight-charts hover tooltip)

    Each closed trade emits UP TO two arrow markers — one at entry, one
    at the FINAL exit. Partial exits (scale-outs) each emit one dot
    marker. Open trades produce an entry marker only. If `_db` was not
    provided we return [] silently so the chart still works in minimal
    environments.
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
                    # v19.34.25 — include trades whose entry falls in the
                    # window even if they're still open (no closed_at yet).
                    # Pre-v19.34.25 these only matched when the trade closed
                    # within the window, so live trades opened earlier in
                    # the session never painted an entry arrow.
                    {"entry_at":     {"$gte": window_iso_start, "$lte": window_iso_end}},
                    {"entry_time":   {"$gte": window_iso_start, "$lte": window_iso_end}},
                ],
            },
            {
                "_id": 0,
                "symbol": 1, "direction": 1, "setup_type": 1,
                "entry_price": 1, "stop_price": 1, "exit_price": 1,
                "r_multiple": 1, "pnl": 1,
                "closed_at": 1, "last_updated": 1, "placed_at": 1,
                "entry_at": 1, "entry_time": 1,
                # v19.34.25 — fetch partial exits + exit reason so we can
                # paint scale-out dots and color-code the final exit by
                # cause (SL hit vs PT hit).
                "partial_exits": 1, "exit_reason": 1, "close_reason": 1,
                "scale_out_state": 1, "scale_out_config": 1,
                # v19.34.25 — adopted-trade timing alignment. Original
                # IB fill time is the gold standard; entry_at often lags
                # because it's set when the bot records the trade, which
                # for reconciled positions can be many seconds after the
                # IB fill itself.
                "ib_fill_time": 1, "filled_at": 1,
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

        # v19.34.25 — Prefer IB fill timestamp when present so adopted
        # trades land on the bar where the actual fill happened (not the
        # bot's record-keeping moment). Falls back through the prior
        # timestamp chain so non-adopted bot trades still resolve.
        entry_ts = _to_utc_seconds(
            doc.get("ib_fill_time")
            or doc.get("filled_at")
            or doc.get("entry_at")
            or doc.get("entry_time")
            or doc.get("placed_at")
        )
        exit_ts = _to_utc_seconds(doc.get("closed_at") or doc.get("last_updated"))
        r = doc.get("r_multiple")
        pnl = doc.get("pnl")
        setup = doc.get("setup_type") or "trade"

        # Entry marker — v19.34.25 colors: green ▲ for long, red ▼ for
        # short. Matches universal trading-chart convention so entries
        # read at a glance.
        if entry_ts and start_ts <= entry_ts <= end_ts:
            markers.append({
                "time": entry_ts,
                "position": "belowBar" if is_long else "aboveBar",
                "shape": "arrowUp" if is_long else "arrowDown",
                "color": "#10b981" if is_long else "#f43f5e",
                "text": f"{setup} entry @ {doc.get('entry_price')}",
            })

        # v19.34.25 — Partial-exit dots. Each entry in `partial_exits`
        # paints a small circle marker (no text) on the bar where the
        # scale-out fired. The lightweight-charts hover tooltip surfaces
        # the full text on demand so we don't clutter the chart with
        # labels for routine scale-outs.
        partials = doc.get("partial_exits") or []
        if isinstance(partials, list):
            for pe in partials:
                if not isinstance(pe, dict):
                    continue
                pe_ts = _to_utc_seconds(
                    pe.get("exited_at") or pe.get("filled_at") or pe.get("time")
                )
                if not pe_ts or pe_ts < start_ts or pe_ts > end_ts:
                    continue
                pe_pnl = pe.get("partial_pnl") or pe.get("pnl") or 0
                pe_color = "#10b981" if (isinstance(pe_pnl, (int, float)) and pe_pnl >= 0) else "#f43f5e"
                target_idx = pe.get("target_idx")
                tip = (
                    f"scale-out{(' T' + str(target_idx + 1)) if isinstance(target_idx, int) else ''}"
                    f" · {pe.get('shares_sold', '?')}sh @ {pe.get('fill_price', '?')}"
                    + (f" · {float(pe_pnl):+.2f}" if isinstance(pe_pnl, (int, float)) else "")
                )
                markers.append({
                    "time": pe_ts,
                    "position": "aboveBar" if is_long else "belowBar",
                    "shape": "circle",
                    "color": pe_color,
                    # No `text` field → lightweight-charts renders the
                    # dot only; tooltip uses the title-like text below.
                    "text": tip,
                    # Custom field — frontend can read this to style the
                    # marker as a "scale-out dot" if extended later.
                    "size": 0,
                })

        # Final exit marker — v19.34.25 colors: amber ✕-style for stop
        # exits (loss), emerald for target exits (win). The shape stays
        # consistent (arrow against the position) so the operator reads
        # direction instantly; color tells outcome.
        if exit_ts and doc.get("exit_price") is not None and start_ts <= exit_ts <= end_ts:
            is_win = (r is not None and r > 0) or (pnl is not None and pnl > 0)
            exit_reason = (doc.get("exit_reason") or doc.get("close_reason") or "").lower()
            is_stop_exit = any(
                k in exit_reason for k in ("stop", "sl", "trail")
            )
            if is_stop_exit and not is_win:
                exit_color = "#f59e0b"          # amber — stop hit
                exit_tag = "SL"
            elif is_win:
                exit_color = "#22d3ee"          # cyan — winner (target / trail-out in profit)
                exit_tag = "PT"
            else:
                exit_color = "#f43f5e"          # rose — manual close at a loss / other
                exit_tag = "X"
            markers.append({
                "time": exit_ts,
                "position": "aboveBar" if is_long else "belowBar",
                "shape": "arrowDown" if is_long else "arrowUp",
                "color": exit_color,
                "text": (
                    f"{exit_tag} exit @ {doc.get('exit_price')}"
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


def _sanitize_intraday_bars(bars: List[Dict[str, Any]], tol: float = 0.5, win: int = 5):
    """v19.34.265 — transient bad-tick guard for intraday candles.

    A single corrupt IB print (e.g. a $36 tick on a $260 stock) produces a
    bar whose wick/close deviates absurdly from its neighbours, blowing out
    the candle autoscale and squashing every real candle into an unreadable
    band for minutes. Clamp each bar's O/H/L/C into a ±`tol` band around the
    LOCAL median close (±`win` bars). The median is robust to a single
    outlier, so genuine trends/gaps are untouched — only lone spikes get
    clipped. Mutates the dicts in place; returns (bars, fixed_count).
    """
    n = len(bars)
    if n < 3:
        return bars, 0
    closes = [r["close"] for r in bars]   # snapshot BEFORE any mutation
    fixed = 0
    for i, r in enumerate(bars):
        window = sorted(closes[max(0, i - win):min(n, i + win + 1)])
        ref = window[len(window) // 2]
        if ref <= 0:
            continue
        lob, hib = ref * (1.0 - tol), ref * (1.0 + tol)
        o = min(max(r["open"],  lob), hib)
        c = min(max(r["close"], lob), hib)
        h = min(max(r["high"],  lob), hib)
        lw = min(max(r["low"],  lob), hib)
        h = max(h, o, c)        # restore OHLC invariants
        lw = min(lw, o, c)
        if (o, h, lw, c) != (r["open"], r["high"], r["low"], r["close"]):
            r["open"], r["high"], r["low"], r["close"] = o, h, lw, c
            fixed += 1
    return bars, fixed


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

    # ── v19.25 Tier 1: response cache. Try to serve from the
    # `chart_response_cache` collection FIRST. Hits return in <50ms
    # regardless of bar count, indicator math, or pusher latency. Cache
    # is keyed by (symbol, tf, session, days). Survives backend restarts
    # via Mongo TTL index. Best-effort — any failure falls through to
    # the live compute path below. ────────────────────────────────────
    from services.chart_response_cache import (
        get_chart_response_cache, make_cache_key, chart_cache_ttl_for,
    )

    # v322o — phase-timing instrumentation. Every /chart response carries a
    # `timings` block (cache_ms / mongo_ms / rpc_ms / indicators_ms /
    # markers_ms / total_ms) so a slow load can be ATTRIBUTED to a specific
    # phase instead of guessed at. Loads slower than CHART_SLOW_LOG_MS
    # (default 1500ms) also emit a WARNING log line with the breakdown.
    _t_start = time.perf_counter()

    cache = get_chart_response_cache(db=_db)
    cache_key = make_cache_key(symbol.upper(), tf, session, days)
    cached_response = await cache.get(cache_key)
    _cache_ms = round((time.perf_counter() - _t_start) * 1000.0, 1)
    if cached_response is not None:
        # Stamp `cache: 'hit'` so the frontend can surface freshness
        # in dev tooling without the operator needing a separate curl.
        return {
            **cached_response,
            "cache": "hit",
            "timings": {"cache_ms": _cache_ms, "total_ms": _cache_ms},
        }

    _t_phase = time.perf_counter()
    result = await _hybrid_data_service.get_bars(
        symbol=symbol.upper(),
        timeframe=tf,
        days_back=days,
    )
    _mongo_ms = round((time.perf_counter() - _t_phase) * 1000.0, 1)

    if not result.success:
        return {
            "success": False,
            "symbol": symbol.upper(),
            "timeframe": tf,
            "bar_count": 0,
            "bars": [],
            "indicators": {},
            "error": result.error,
            # v322o — failed loads still report where the time went.
            "timings": {
                "cache_ms": _cache_ms,
                "mongo_ms": _mongo_ms,
                "total_ms": round((time.perf_counter() - _t_start) * 1000.0, 1),
            },
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
    _t_phase = time.perf_counter()
    try:
        tf_cfg = _hybrid_data_service.TIMEFRAMES.get(tf)
        live_bar_size = tf_cfg.get("ib_bar_size") if tf_cfg else None
        if live_bar_size and tf in {"1min", "5min", "15min", "1hour"}:
            # v19.34.197 — TIME-BOUND the live pusher-RPC merge. On a cache
            # MISS this on-demand IB historical request (rpc.latest_bars) can
            # take 15-21s for quote-subscribed symbols, blocking the ENTIRE
            # cold chart load (measured: 18-21s for 5min/1min, vs <300ms for
            # daily which skips the merge). The chart-tail WS/poll already
            # backfills the freshest bars within ~5s, so cap the merge tightly
            # and serve the historical window immediately on timeout. The slow
            # RPC keeps running in its threadpool and populates live_bar_cache,
            # so the NEXT load gets the merged bars fast. Env-tunable via
            # CHART_LIVE_MERGE_TIMEOUT_S (default 3.0s).
            import asyncio as _asyncio_merge
            import os as _os_merge
            try:
                _merge_to = float(_os_merge.environ.get("CHART_LIVE_MERGE_TIMEOUT_S", "3.0"))
            except (TypeError, ValueError):
                _merge_to = 3.0
            try:
                live_res = await _asyncio_merge.wait_for(
                    _hybrid_data_service.fetch_latest_session_bars(
                        symbol.upper(),
                        live_bar_size,
                        active_view=True,  # /chart calls ARE active-view
                        use_rth=False,
                    ),
                    timeout=_merge_to,
                )
            except _asyncio_merge.TimeoutError:
                logger.info(
                    "[v19.34.197 chart-merge] %s %s live merge exceeded %.1fs — "
                    "serving historical window now; chart-tail will backfill "
                    "the live bars.", symbol.upper(), tf, _merge_to,
                )
                live_res = {"success": False, "error": "live_merge_timeout"}
            if live_res.get("success"):
                live_bars = live_res.get("bars") or []
                result.bars.extend(live_bars)
                live_appended = len(live_bars)
                live_source = live_res.get("source")
                live_market_state = live_res.get("market_state")
    except Exception as _live_exc:
        logger.info("live-bars merge skipped: %s", _live_exc)
    _rpc_ms = round((time.perf_counter() - _t_phase) * 1000.0, 1)

    # Normalise + sort
    _t_phase = time.perf_counter()
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

    # v19.34.265 — bad-tick sanitization (intraday only; daily bars come
    # from EOD historical and rarely carry transient ticks). Runs BEFORE
    # the session filter + indicator math so a corrupt print can't poison
    # the candle autoscale, EMAs/BB, the volume profile, OR the served
    # bars the frontend renders.
    if tf in {"1min", "5min", "15min", "1hour"} and normalised:
        normalised, _bt_fixed = _sanitize_intraday_bars(normalised)
        if _bt_fixed:
            logger.info(
                "[v19.34.265 bad-tick] %s %s clamped %d outlier bar(s)",
                symbol.upper(), tf, _bt_fixed,
            )

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
    _indicators_ms = round((time.perf_counter() - _t_phase) * 1000.0, 1)

    # Overlay markers (executed trades). Silent no-op if db isn't wired.
    _t_phase = time.perf_counter()
    markers = _fetch_trade_markers(symbol, times[0], times[-1])
    _markers_ms = round((time.perf_counter() - _t_phase) * 1000.0, 1)

    _total_ms = round((time.perf_counter() - _t_start) * 1000.0, 1)
    _timings = {
        "cache_ms": _cache_ms,
        "mongo_ms": _mongo_ms,
        "rpc_ms": _rpc_ms,
        "indicators_ms": _indicators_ms,
        "markers_ms": _markers_ms,
        "total_ms": _total_ms,
    }
    try:
        _slow_ms = float(os.environ.get("CHART_SLOW_LOG_MS", "1500") or 1500.0)
    except (TypeError, ValueError):
        _slow_ms = 1500.0
    if _total_ms >= _slow_ms:
        logger.warning(
            "[v322o chart-slow] %s %s days=%d session=%s — total=%.0fms "
            "(mongo=%.0fms rpc=%.0fms indicators=%.0fms markers=%.0fms "
            "live_appended=%d)",
            symbol.upper(), tf, days, session, _total_ms,
            _mongo_ms, _rpc_ms, _indicators_ms, _markers_ms, live_appended,
        )

    response = {
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
        # v322o — per-phase latency attribution for slow-chart diagnosis.
        "timings": _timings,
    }

    # ── v19.25 Tier 1: persist to cache for subsequent requests.
    # TTL is bar-size aware (30s intraday / 180s daily). Best-effort —
    # never blocks the response. ──────────────────────────────────────
    try:
        ttl = chart_cache_ttl_for(tf)
        await cache.set(cache_key, response, ttl_seconds=ttl)
    except Exception as cache_err:
        logger.debug(f"chart cache write failed for {symbol} {tf}: {cache_err}")

    return {**response, "cache": "miss"}


# ─── v19.25 Tier 2: tail-only refresh endpoint ──────────────────────────────
# `/chart` returns the full window — bars + indicators + markers. The
# frontend used to poll this endpoint every 30s, re-shipping ~5,000 bars
# to draw 1 new bar. `/chart-tail` returns only what changed since the
# operator's last poll: new bars, last indicator values, new markers.
# Frontend uses lightweight-charts `update()` for partial bar updates
# instead of `setData()` for the full series.

@router.get("/chart-tail")
async def get_chart_tail(
    symbol: str = Query(..., min_length=1, max_length=10),
    timeframe: str = Query("5min"),
    since: int = Query(
        0,
        ge=0,
        description=(
            "Unix-seconds timestamp of the most recent bar the client "
            "already has. The endpoint returns only bars with `time > "
            "since`, plus indicator values for those bars. `since=0` "
            "(the default) returns the last 50 bars — useful for the "
            "first poll after a stale-while-revalidate hydration."
        ),
    ),
    session: str = Query("rth_plus_premarket"),
    rth_only: bool = Query(None),
    cap: int = Query(
        50, ge=1, le=500,
        description=(
            "Max number of trailing bars returned. The tail endpoint is "
            "designed for incremental updates so the cap is intentionally "
            "low — set higher only when bridging a longer client gap."
        ),
    ),
) -> Dict[str, Any]:
    """Return ONLY new/updated bars since `since` + matching indicator
    values + any new trade markers. Designed for high-frequency polling
    (5s during RTH on the focused chart) so the auto-refresh path
    drops from ~5,000 bars / 30s to ~1-3 bars / 5s.

    Reads through the same `chart_response_cache` as `/chart` — if the
    cache has a fresh entry, we slice the tail off it without re-paying
    the indicator math. On cache miss, we delegate to the live path
    (which itself populates the cache for the next request).

    Response shape:
      {
        success: bool,
        symbol, timeframe, since, latest_time,
        bar_count: int,                # new bars only
        bars: [{time, open, high, low, close, volume}, ...],
        indicators: {                  # latest values only — frontend
                                       # can splice them onto its series
          vwap: [{time, value}, ...],
          ema_20: ..., ema_50: ..., ema_200: ...,
          bb_upper: ..., bb_middle: ..., bb_lower: ...,
        },
        markers: [...],                # markers with time > since
        from_cache: bool,
      }

    No stale flags, partial flags, or session-filter info — those don't
    change tail-to-tail and are already on the full `/chart` response
    the client hydrated from.
    """
    if _hybrid_data_service is None:
        raise HTTPException(status_code=503, detail="hybrid_data_service not initialised")

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

    sym_upper = symbol.upper()

    from services.chart_response_cache import (
        get_chart_response_cache, make_cache_key,
    )
    cache = get_chart_response_cache(db=_db)

    # Probe a few common day-window sizes so a /chart-tail call after
    # a /chart hydrate finds the matching cache entry. The frontend
    # passes `daysLoaded` on the full /chart load, so the cache key is
    # already (sym, tf, session, days). We try the tf-canonical default
    # first, then the broader windows we ship from the V5 frontend.
    # v324 — aligned with the frontend TIMEFRAMES daysBack defaults
    # (7/14/30/60/365) so the tail probe actually finds the cache entry
    # the full /chart load wrote, instead of recomputing a tiny window.
    tf_default_days = {
        "1min": 7, "5min": 14, "15min": 30, "1hour": 60, "1day": 365,
    }
    candidate_days = [
        tf_default_days.get(tf, 5),
        5, 7, 10, 14, 30, 60, 90, 365,
    ]
    seen = set()
    cached_full = None
    for d in candidate_days:
        if d in seen:
            continue
        seen.add(d)
        key = make_cache_key(sym_upper, tf, session, d)
        cached_full = await cache.get(key)
        if cached_full is not None:
            break

    if cached_full is not None:
        # Slice the tail off the cached full payload.
        all_bars = cached_full.get("bars") or []
        new_bars = [b for b in all_bars if int(b.get("time", 0)) > int(since)]
        if cap and len(new_bars) > cap:
            new_bars = new_bars[-cap:]

        new_times = {int(b.get("time", 0)) for b in new_bars}
        sliced_indicators: Dict[str, list] = {}
        for ind_key, series in (cached_full.get("indicators") or {}).items():
            sliced_indicators[ind_key] = [
                pt for pt in (series or [])
                if int(pt.get("time", 0)) in new_times
            ]
        sliced_markers = [
            m for m in (cached_full.get("markers") or [])
            if int(m.get("time", 0)) > int(since)
        ]
        latest_time = (
            int(all_bars[-1].get("time", 0)) if all_bars else int(since)
        )
        return {
            "success": True,
            "symbol": sym_upper,
            "timeframe": tf,
            "since": int(since),
            "latest_time": latest_time,
            "bar_count": len(new_bars),
            "bars": new_bars,
            "indicators": sliced_indicators,
            "markers": sliced_markers,
            "from_cache": True,
            "cache": "hit",
        }

    # Cache miss — fall back to the full path so we (a) build the cache
    # for next call and (b) return a usable tail. The cap on returned
    # bars keeps the response small.
    full = await get_chart_bars(
        symbol=sym_upper,
        timeframe=tf,
        days=tf_default_days.get(tf, 5),
        session=session,
        rth_only=None,
    )
    if not full or not full.get("success"):
        return {
            "success": False,
            "symbol": sym_upper,
            "timeframe": tf,
            "since": int(since),
            "latest_time": int(since),
            "bar_count": 0,
            "bars": [],
            "indicators": {},
            "markers": [],
            "from_cache": False,
            "cache": "miss",
            "error": (full or {}).get("error", "no_data"),
        }
    all_bars = full.get("bars") or []
    new_bars = [b for b in all_bars if int(b.get("time", 0)) > int(since)]
    if cap and len(new_bars) > cap:
        new_bars = new_bars[-cap:]
    new_times = {int(b.get("time", 0)) for b in new_bars}
    sliced_indicators = {}
    for ind_key, series in (full.get("indicators") or {}).items():
        sliced_indicators[ind_key] = [
            pt for pt in (series or [])
            if int(pt.get("time", 0)) in new_times
        ]
    sliced_markers = [
        m for m in (full.get("markers") or [])
        if int(m.get("time", 0)) > int(since)
    ]
    latest_time = int(all_bars[-1].get("time", 0)) if all_bars else int(since)
    return {
        "success": True,
        "symbol": sym_upper,
        "timeframe": tf,
        "since": int(since),
        "latest_time": latest_time,
        "bar_count": len(new_bars),
        "bars": new_bars,
        "indicators": sliced_indicators,
        "markers": sliced_markers,
        "from_cache": False,
        "cache": full.get("cache", "miss"),
    }


# ═══════════════════════════════════════════════════════════════════
# v324 (2026-06-13) — Infinite history scrolling + tf availability
# ═══════════════════════════════════════════════════════════════════
#
# `/chart-history` returns the next OLDER chunk of bars strictly before
# a unix-seconds cursor, with indicators computed over a ~220-bar
# warm-up pad so EMA-200/BB lines stay continuous across the seam. The
# V5 ChartPanel calls this when the user scrolls/zooms near the
# leftmost loaded bar and PREPENDS the result — no more full-window
# doubling refetches, no 365-day ceiling.
#
# IMPORTANT: reads `ib_historical_data` DIRECTLY instead of
# hybrid_data_service.get_bars() because get_bars has a staleness
# fallback that returns the NEWEST bars when the requested (old) window
# is empty — which would poison a prepend with duplicate recent bars.

_HISTORY_CHUNK_CAPS = {
    "1min": 1500,   # ≈2 sessions incl. premarket
    "5min": 1500,   # ≈7 sessions
    "15min": 1000,  # ≈20 sessions
    "1hour": 1000,  # ≈3 months
    "1day": 500,    # ≈2 years
}
_HISTORY_WARMUP_BARS = 220  # EMA-200 + BB-20 seed pad

_TF_TO_BARSIZE = {
    "1min": "1 min", "5min": "5 mins", "15min": "15 mins",
    "1hour": "1 hour", "1day": "1 day",
}


@router.get("/chart-history")
async def get_chart_history(
    symbol: str = Query(..., min_length=1, max_length=10),
    timeframe: str = Query("5min"),
    before: int = Query(
        ..., ge=1,
        description=(
            "Unix-seconds cursor. Returns only bars strictly OLDER than "
            "this. Use the response's `next_before` as the cursor for the "
            "following page — it resumes correctly even when a chunk was "
            "entirely weekend/overnight rows."
        ),
    ),
    session: str = Query("rth_plus_premarket"),
    cap: Optional[int] = Query(None, ge=100, le=5000),
) -> Dict[str, Any]:
    """v324 — paginated older-history chunks for infinite chart scroll."""
    if _db is None:
        raise HTTPException(status_code=503, detail="db not initialised")
    tf = timeframe.lower()
    if tf not in _SUPPORTED_TFS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported timeframe '{timeframe}'. Supported: {sorted(_SUPPORTED_TFS)}",
        )
    sym = symbol.upper()
    chunk_cap = int(cap or _HISTORY_CHUNK_CAPS.get(tf, 1000))
    bar_size = _TF_TO_BARSIZE[tf]

    before_dt = datetime.fromtimestamp(int(before), tz=timezone.utc)
    # `date` storage convention mirrors hybrid_data_service._get_from_cache:
    # YYYY-MM-DD strings for daily bars, full ISO strings for intraday.
    before_key = before_dt.strftime("%Y-%m-%d") if tf == "1day" else before_dt.isoformat()

    import asyncio as _aio
    coll = _db["ib_historical_data"]
    fetch_n = chunk_cap + _HISTORY_WARMUP_BARS

    def _sync_fetch():
        return list(
            coll.find(
                {"symbol": sym, "bar_size": bar_size, "date": {"$lt": before_key}},
                {"_id": 0},
            ).sort("date", -1).limit(fetch_n)
        )

    docs = await _aio.to_thread(_sync_fetch)
    has_more = len(docs) >= fetch_n
    if not docs:
        return {
            "success": True, "symbol": sym, "timeframe": tf,
            "before": int(before), "bar_count": 0, "bars": [],
            "indicators": {}, "markers": [],
            "has_more": False, "next_before": None, "earliest_time": None,
        }

    # Oldest doc of the RETURNED chunk (docs is newest-first). Rows older
    # than this are the indicator warm-up pad — sliced off the response.
    boundary_ts = _to_utc_seconds(
        docs[min(chunk_cap, len(docs)) - 1].get("date")
    )

    docs.reverse()  # ascending
    normalised: List[Dict[str, Any]] = []
    for b in docs:
        ts = _to_utc_seconds(b.get("date") or b.get("timestamp") or b.get("time"))
        if ts is None or ts >= int(before):
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
    deduped: List[Dict[str, Any]] = []
    for r in normalised:
        if deduped and deduped[-1]["time"] == r["time"]:
            deduped[-1] = r
        else:
            deduped.append(r)
    normalised = deduped

    if boundary_ts is None and normalised:
        boundary_ts = normalised[0]["time"]

    if tf in {"1min", "5min", "15min", "1hour"} and normalised:
        normalised, _ = _sanitize_intraday_bars(normalised)

    # Session filter — same contract as /chart (tags session: pre|rth).
    if tf in {"1min", "5min", "15min", "1hour"} and session != "all":
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
        if session == "rth_plus_premarket":
            window_open, window_close = 4 * 60, 16 * 60
        else:  # "rth"
            window_open, window_close = 9 * 60 + 30, 16 * 60
        kept: List[Dict[str, Any]] = []
        for r in normalised:
            dt_et = datetime.fromtimestamp(r["time"], tz=et)
            if dt_et.weekday() >= 5:
                continue
            mod = dt_et.hour * 60 + dt_et.minute
            if not (window_open <= mod < window_close):
                continue
            r["session"] = "pre" if mod < (9 * 60 + 30) else "rth"
            kept.append(r)
        normalised = kept
    else:
        for r in normalised:
            r.setdefault("session", "rth")

    if tf == "1day":
        seen_days = set()
        snapped: List[Dict[str, Any]] = []
        for r in normalised:
            day_ts = (r["time"] // 86400) * 86400
            if day_ts in seen_days:
                continue
            seen_days.add(day_ts)
            r["time"] = day_ts
            snapped.append(r)
        normalised = snapped
        if boundary_ts is not None:
            boundary_ts = (boundary_ts // 86400) * 86400

    if not normalised or boundary_ts is None:
        # Chunk was entirely weekend/overnight rows — hand back the
        # cursor so the client immediately walks to the next older page.
        return {
            "success": True, "symbol": sym, "timeframe": tf,
            "before": int(before), "bar_count": 0, "bars": [],
            "indicators": {}, "markers": [],
            "has_more": has_more, "next_before": boundary_ts,
            "earliest_time": None,
        }

    # Indicators over warm-up + chunk, then slice to the chunk only.
    times = [r["time"] for r in normalised]
    closes = [r["close"] for r in normalised]
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
    vwap = _vwap(normalised, per_session=tf != "1day")

    def _slice(series: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [p for p in series if p["time"] >= boundary_ts]

    chunk = [r for r in normalised if r["time"] >= boundary_ts]
    markers = (
        _fetch_trade_markers(sym, chunk[0]["time"], chunk[-1]["time"])
        if chunk else []
    )

    return {
        "success": True,
        "symbol": sym,
        "timeframe": tf,
        "before": int(before),
        "bar_count": len(chunk),
        "bars": chunk,
        "indicators": {
            "vwap": _slice(_as_series(times, vwap)),
            "ema_20": _slice(_as_series(times, ema_20)),
            "ema_50": _slice(_as_series(times, ema_50)),
            "ema_200": _slice(_as_series(times, ema_200)),
            "bb_upper": _slice(_as_series(times, bb_upper)),
            "bb_middle": _slice(_as_series(times, bb_mid)),
            "bb_lower": _slice(_as_series(times, bb_lower)),
        },
        "markers": markers,
        "has_more": has_more,
        "next_before": boundary_ts,
        "earliest_time": chunk[0]["time"] if chunk else None,
    }


@router.get("/chart/available-timeframes")
async def get_available_timeframes(
    symbol: str = Query(..., min_length=1, max_length=12),
) -> Dict[str, Any]:
    """v324 — bar counts per timeframe for `symbol` from
    ib_historical_data. The V5 ChartPanel grays out timeframe buttons
    with no collected history (Tier 2/3 investment symbols usually only
    carry daily — sometimes hourly — bars)."""
    if _db is None:
        raise HTTPException(status_code=503, detail="db not initialised")
    sym = symbol.upper()
    barsize_to_tf = {v: k for k, v in _TF_TO_BARSIZE.items()}

    import asyncio as _aio

    def _sync_counts():
        return list(_db["ib_historical_data"].aggregate([
            {"$match": {"symbol": sym}},
            {"$group": {"_id": "$bar_size", "n": {"$sum": 1}}},
        ]))

    try:
        rows = await _aio.to_thread(_sync_counts)
    except Exception as exc:  # pragma: no cover
        logger.warning("available-timeframes failed for %s: %s", sym, exc)
        return {"success": False, "symbol": sym, "available": {}, "error": str(exc)}

    available: Dict[str, int] = {}
    for r in rows:
        tf_val = barsize_to_tf.get(r.get("_id"))
        if tf_val:
            available[tf_val] = int(r.get("n", 0) or 0)
    return {"success": True, "symbol": sym, "available": available}


@router.get("/chart/reach-meta")
async def get_chart_reach_meta(
    symbol: str = Query(..., min_length=1, max_length=12),
) -> Dict[str, Any]:
    """v325b — daily-ATR basis for the chart bracket-geometry overlay.

    Returns `atr_pct` (FRACTION of price) preferring the collector's
    symbol_adv_cache (14d daily ATR / close), falling back to a 14-bar
    ATR computed from stored daily bars. The overlay multiplies by the
    entry price to get $ATR and builds the √time reach cone client-side.
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="db not initialised")
    sym = symbol.upper()
    import asyncio as _aio

    def _sync():
        try:
            doc = _db["symbol_adv_cache"].find_one(
                {"symbol": sym}, {"atr_pct": 1, "_id": 0})
            if doc and doc.get("atr_pct"):
                v = float(doc["atr_pct"])
                if 0.001 <= v <= 0.30:
                    return {"atr_pct": round(v, 6), "source": "symbol_adv_cache"}
        except Exception:
            pass
        try:
            rows = list(_db["ib_historical_data"].find(
                {"symbol": sym, "bar_size": "1 day"},
                {"_id": 0, "high": 1, "low": 1, "close": 1, "date": 1},
            ).sort("date", -1).limit(15))
        except Exception:
            rows = []
        if len(rows) >= 5:
            rows.reverse()
            trs = []
            prev_close = None
            for r in rows:
                try:
                    h, l, c = float(r["high"]), float(r["low"]), float(r["close"])
                except (KeyError, TypeError, ValueError):
                    continue
                tr = (h - l) if prev_close is None else max(
                    h - l, abs(h - prev_close), abs(l - prev_close))
                trs.append(tr)
                prev_close = c
            if trs and prev_close:
                atr = sum(trs[-14:]) / len(trs[-14:])
                return {"atr_pct": round(atr / prev_close, 6), "source": "daily_bars"}
        return None

    meta = await _aio.to_thread(_sync)
    if not meta:
        return {"success": False, "symbol": sym, "atr_pct": None, "source": None}
    return {"success": True, "symbol": sym, **meta}


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



# ═══════════════════════════════════════════════════════════════════
# v19.32 (2026-05-04) — Chart Cache Warmer
# ═══════════════════════════════════════════════════════════════════
#
# Operator's "cold chart load is 400ms even though the cache is fast"
# pain-point. The fix isn't faster cold compute — `/chart` does correct
# work — it's making sure the operator's NEXT click finds a warm cache.
#
# Strategy: when the scanner produces a top-N watchlist, the frontend
# fires this endpoint with `{symbols, timeframes}`. Backend computes
# each (symbol, tf) chart payload concurrently using the same code
# path as `GET /chart`, populates `chart_response_cache`, and returns
# a thin summary `{warmed, skipped, failed, ms}`. Operator's click on
# any of those symbols is then a <50ms cache hit.
#
# Concurrency is bounded (default 4 workers) so we don't hammer Mongo
# / pusher RPC under load. Per-cell timeout protects the whole batch
# from a single slow symbol.

from fastapi import Body
from pydantic import field_validator
import asyncio as _asyncio_warm


class ChartWarmRequest(BaseModel):
    """Request shape for `POST /chart/warm`. All fields except `symbols`
    are optional and have sensible defaults that match the V5 frontend's
    typical chart load."""
    symbols: List[str] = Field(..., min_length=1, max_length=48)
    timeframes: List[str] = Field(default=["1min", "5min", "15min"], max_length=5)
    days: int = Field(default=5, ge=1, le=365)
    session: str = Field(default="rth_plus_premarket")
    max_concurrent: int = Field(default=4, ge=1, le=8)
    per_cell_timeout_s: float = Field(default=8.0, ge=1.0, le=30.0)

    @field_validator("symbols")
    @classmethod
    def _upper_dedupe_symbols(cls, v):
        seen = []
        for s in v:
            u = (s or "").strip().upper()
            if u and u not in seen:
                seen.append(u)
        if not seen:
            raise ValueError("symbols must contain at least one non-empty value")
        return seen

    @field_validator("timeframes")
    @classmethod
    def _normalize_timeframes(cls, v):
        out = []
        for t in v:
            tl = (t or "").strip().lower()
            if tl in _SUPPORTED_TFS and tl not in out:
                out.append(tl)
        if not out:
            raise ValueError(f"timeframes must include at least one of {sorted(_SUPPORTED_TFS)}")
        return out


@router.post("/chart/warm")
async def warm_chart_cache(req: ChartWarmRequest = Body(...)) -> Dict[str, Any]:
    """v19.32 — Pre-compute `chart_response_cache` entries for the given
    symbol × timeframe matrix. Returns once all cells settle (success or
    timeout), so the caller can fire-and-forget without leaking.

    Idempotent: cells that already have a fresh cache entry are skipped
    (counted as `skipped`). Cells that miss are computed and cached, so
    the operator's NEXT chart click for any of these symbols is <50ms.
    """
    started_ms = datetime.now(timezone.utc)

    if _hybrid_data_service is None:
        raise HTTPException(status_code=503, detail="hybrid_data_service not initialised")

    from services.chart_response_cache import (
        get_chart_response_cache, make_cache_key,
    )
    cache = get_chart_response_cache(db=_db)

    cells: List[Dict[str, Any]] = [
        {"symbol": s, "timeframe": tf}
        for s in req.symbols
        for tf in req.timeframes
    ]

    sem = _asyncio_warm.Semaphore(req.max_concurrent)

    async def _warm_cell(cell: Dict[str, Any]) -> Dict[str, Any]:
        sym = cell["symbol"]
        tf = cell["timeframe"]
        async with sem:
            try:
                # Cache HIT short-circuit so we don't re-run the chain.
                key = make_cache_key(sym, tf, req.session, req.days)
                if (await cache.get(key)) is not None:
                    return {"symbol": sym, "timeframe": tf, "status": "skipped",
                            "reason": "already_warm"}
                # Reuse the public endpoint logic so the warmed payload
                # is byte-identical to a future `GET /chart` response.
                # We call it with a fresh task to honor the per-cell timeout.
                async def _run():
                    return await get_chart_bars(
                        symbol=sym, timeframe=tf, days=req.days,
                        session=req.session, rth_only=None,
                    )
                payload = await _asyncio_warm.wait_for(
                    _run(), timeout=req.per_cell_timeout_s,
                )
                if not payload or not payload.get("success"):
                    return {"symbol": sym, "timeframe": tf, "status": "failed",
                            "reason": (payload or {}).get("error", "compute_failed")}
                return {
                    "symbol": sym, "timeframe": tf, "status": "warmed",
                    "bar_count": int(payload.get("bar_count") or 0),
                }
            except _asyncio_warm.TimeoutError:
                return {"symbol": sym, "timeframe": tf, "status": "failed",
                        "reason": f"timeout_{req.per_cell_timeout_s:.0f}s"}
            except Exception as e:
                logger.debug(f"warm cell {sym}/{tf} failed: {e}")
                return {"symbol": sym, "timeframe": tf, "status": "failed",
                        "reason": str(e)[:120]}

    results = await _asyncio_warm.gather(*[_warm_cell(c) for c in cells])

    summary = {
        "warmed": sum(1 for r in results if r["status"] == "warmed"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "total": len(results),
    }
    elapsed_ms = (datetime.now(timezone.utc) - started_ms).total_seconds() * 1000.0

    return {
        "success": True,
        "summary": summary,
        "elapsed_ms": round(elapsed_ms, 1),
        "results": results,
    }


# ═══════════════════════════════════════════════════════════════════
# v19.33 (2026-05-04) — Chart Tail WebSocket
# ═══════════════════════════════════════════════════════════════════
#
# Replaces the 5s polling loop on the focused chart with a server-pushed
# tail stream. Latency drops from ~5s avg → ~2s ceiling (the server tick
# interval), and the client doesn't pay round-trip overhead for empty
# "no new bars" responses. Falls back transparently to polling when the
# WS connection drops or the feature is disabled by env-var.
#
# Wire format
# -----------
# Client connects to `/api/sentcom/ws/chart-tail?symbol=AAPL&timeframe=5min&since=0`.
# Server sends JSON frames in two shapes:
#
#   1. Initial / on-tick "tail" frames — same payload as the REST
#      `/chart-tail` endpoint, so the frontend merge code is identical.
#      Only emitted when there's actually new data (server filters out
#      empty ticks to save bandwidth).
#
#   2. "ping" frames every 15s when there are no new bars. Lets the
#      frontend confirm the connection is alive without re-firing
#      lightweight-charts updates.
#
# Server tick interval defaults to 2s during RTH, 30s otherwise.
# REALIZED_PNL_AUTOSYNC_INTERVAL_S-style toggle: env var
# `CHART_WS_TICK_S` overrides the RTH interval.

from fastapi import WebSocket, WebSocketDisconnect


@router.websocket("/ws/chart-tail")
async def chart_tail_ws(websocket: WebSocket):
    """v19.33 — WebSocket-pushed chart tail. Drop-in for the 5s polling
    loop on `/chart-tail`. The frontend should attempt the WS first and
    fall back to polling if the connection fails.

    Query params (parsed from URL):
      symbol     (str, required)  — e.g. "AAPL"
      timeframe  (str, required)  — one of _SUPPORTED_TFS
      since      (int, default 0) — unix-seconds of last bar client has
      session    (str, default rth_plus_premarket)

    Frame shape: identical to the REST `/chart-tail` response, but only
    sent when `bar_count > 0`. Heartbeats `{type:'ping', t:...}` go out
    every 15s during silent windows.
    """
    import os as _os3

    # Feature-flag escape hatch. If a future regression surfaces, the
    # operator can flip this off without a redeploy. Default is ON.
    if _os3.environ.get("CHART_WS_ENABLED", "true").strip().lower() in ("0", "false", "no", "off"):
        await websocket.close(code=1008, reason="chart_ws_disabled")
        return

    qp = websocket.query_params
    symbol = (qp.get("symbol") or "").strip().upper()
    timeframe = (qp.get("timeframe") or "5min").strip().lower()
    try:
        since = int(qp.get("since") or 0)
    except Exception:
        since = 0
    session = (qp.get("session") or "rth_plus_premarket").strip().lower()

    if not symbol or timeframe not in _SUPPORTED_TFS:
        await websocket.close(code=1008, reason="bad_args")
        return

    await websocket.accept()
    logger.info(f"[v19.33 CHART-WS] open sym={symbol} tf={timeframe} since={since}")

    last_sent_time = since
    last_heartbeat = datetime.now(timezone.utc)

    # RTH-aware tick interval.
    def _tick_seconds():
        try:
            return float(_os3.environ.get("CHART_WS_TICK_S") or 0) or _default_tick_s()
        except Exception:
            return _default_tick_s()

    def _default_tick_s():
        from routers.ib_collector_router import _rth_throttle_decision
        try:
            policy = _rth_throttle_decision()
            return 2.0 if policy.get("rth_active") else 30.0
        except Exception:
            return 5.0

    try:
        while True:
            tick_s = _tick_seconds()

            # Pull a tail payload by reusing the REST handler's logic —
            # cache hits are virtually free, and on miss the upstream
            # `/chart` endpoint handles the heavy lift.
            try:
                tail = await get_chart_tail(
                    symbol=symbol, timeframe=timeframe, since=last_sent_time,
                    session=session, rth_only=None, cap=50,
                )
            except Exception as e:
                # Don't kill the WS for a transient compute error — log
                # and retry on the next tick.
                logger.debug(f"[v19.33 CHART-WS] tail fetch failed sym={symbol}: {e}")
                tail = None

            now = datetime.now(timezone.utc)
            if tail and tail.get("success") and int(tail.get("bar_count") or 0) > 0:
                # Stamp the WS-source flag so the frontend can show a
                # "live" pip in the chart header without a separate API.
                tail = dict(tail)
                tail["from_ws"] = True
                tail["server_t"] = now.isoformat()
                await websocket.send_json(tail)
                last_sent_time = int(tail.get("latest_time") or last_sent_time)
                last_heartbeat = now
            else:
                # Heartbeat every 15s of silence.
                if (now - last_heartbeat).total_seconds() >= 15.0:
                    await websocket.send_json({
                        "type": "ping",
                        "t": now.isoformat(),
                        "symbol": symbol,
                    })
                    last_heartbeat = now

            await _asyncio_warm.sleep(tick_s)

    except WebSocketDisconnect:
        logger.info(f"[v19.33 CHART-WS] disconnect sym={symbol} tf={timeframe}")
    except Exception as e:
        logger.warning(f"[v19.33 CHART-WS] error sym={symbol}: {e}")
        try:
            await websocket.close(code=1011, reason="server_error")
        except Exception:
            pass
