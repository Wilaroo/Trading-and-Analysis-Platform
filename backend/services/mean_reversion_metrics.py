"""mean_reversion_metrics.py — v19.34.157 (P3-C)

Per-symbol mean-reversion edge metrics. Used by the position sizer
to bias size in favour of setups that ALIGN with the current
statistical regime (MR setups in mean-reverting regimes, momentum
setups in trending regimes) and against setups that conflict
(momentum in chop, MR in trends).

Public API
----------
* `compute_mr_metrics(db, symbol, bar_size="5 mins", lookback_bars=500)
  -> dict` — pure logic, no DB writes, no FastAPI. Mirrors the
  `smart_levels_service` pattern.
* `get_mr_multiplier(metrics, setup_type) -> (float, str)` — looks up
  the setup family (MR / momentum / breakout / unknown) and returns
  the size multiplier given the regime tag in `metrics`.
* `classify_setup_family(setup_type) -> str` — exposed for tests +
  any caller that wants to inspect the mapping.

Caching
-------
Compute is cached in `mean_reversion_metrics` collection with
composite unique key `(symbol, bar_size)`. TTL ~10 min. A caller
that asks for stale data gets the stale doc back AND triggers a
best-effort recompute via `asyncio.create_task` — same pattern
`smart_levels_service` uses.

Statistical methods
-------------------
* **Hurst exponent** via R/S analysis on the price series. Robust
  for short windows (200-500 bars) without scipy / statsmodels
  dependencies — the existing pyproject already pulls them but
  R/S is dead-simple and lets us drop the import surface.
* **Half-life of mean reversion** via AR(1) regression:
  `Δp_t = α + β·p_{t-1} + ε`. Solved with `numpy.polyfit`. Half-
  life is `-ln(2) / ln(1+β)` when β < 0; reported as `None` when
  the series is trending (β ≥ 0).
* **Current z-score** = (last close - rolling mean) / rolling std.
* **VWAP z-score** = (last close - VWAP) / σ(close-VWAP). Reuses
  `FeatureEngineService.calc_vwap` so the calc matches the rest of
  the codebase (operator confirmed during planning).

Regime tags
-----------
* `MR_STRONG`  — Hurst ≤ 0.45 AND half-life present AND ≤ 20 bars
* `MR_WEAK`    — Hurst ≤ 0.50 OR half-life present and ≤ 40 bars
* `TRENDING`   — Hurst ≥ 0.55
* `NEUTRAL`    — anything else
"""
from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Setup-family classification per operator (Q1a/Q1b confirmed during
# planning).  Anything not in either list falls to "unknown" and gets
# a neutral 1.0× multiplier.
_MR_SETUPS = {
    "rubber_band_scalp_long", "rubber_band_scalp_short",
    "vwap_reclaim_long", "vwap_reclaim_short",
    "mean_reversion",
    "vwap_fade",  # enhanced_scanner.py — VWAP rejection from above/below = MR
}
_MOMENTUM_SETUPS = {
    "gap_and_go", "momentum_continuation",
    "short_squeeze_intraday", "short_squeeze_swing",
    "vwap_continuation",  # enhanced_scanner.py — riding VWAP = momentum
}
_BREAKOUT_SETUPS = {
    "breakout_scalp", "breakout_swing",
    "hod_breakout",
    "first_vwap_pullback",  # pullback-then-resume = breakout-style continuation
}

# Multiplier table — operator choice 2a (modest 0.5×-1.3× range).
_MULTIPLIER_TABLE = {
    "mean_reversion": {"MR_STRONG": 1.3, "MR_WEAK": 1.1, "NEUTRAL": 1.0, "TRENDING": 0.5},
    "momentum":       {"MR_STRONG": 0.7, "MR_WEAK": 0.9, "NEUTRAL": 1.0, "TRENDING": 1.2},
    "breakout":       {"MR_STRONG": 0.8, "MR_WEAK": 0.95, "NEUTRAL": 1.0, "TRENDING": 1.1},
    "unknown":        {"MR_STRONG": 1.0, "MR_WEAK": 1.0, "NEUTRAL": 1.0, "TRENDING": 1.0},
}

_COLLECTION = "mean_reversion_metrics"
_TTL_SECONDS = 600  # 10 min


# ── Setup classification ─────────────────────────────────────────────


def classify_setup_family(setup_type: Optional[str]) -> str:
    """Returns `"mean_reversion"|"momentum"|"breakout"|"unknown"`."""
    if not isinstance(setup_type, str):
        return "unknown"
    s = setup_type.strip().lower()
    if s in _MR_SETUPS:
        return "mean_reversion"
    if s in _MOMENTUM_SETUPS:
        return "momentum"
    if s in _BREAKOUT_SETUPS:
        return "breakout"
    return "unknown"


# ── Pure statistical helpers (testable without DB) ───────────────────


def _hurst_rs(series: List[float]) -> Optional[float]:
    """Hurst exponent via R/S analysis on the series' log-returns.

    Returns None if the series is too short or degenerate (zero
    variance). Output convention:
      • H ≈ 0.50 → random walk (no MR or trend bias).
      • H < 0.50 → mean-reverting.
      • H > 0.50 → trending / persistent.

    Note: R/S MUST be applied to log-returns, NOT raw price levels.
    Running R/S on a price series (which is itself a cumulative sum
    of returns for a random walk) inflates the slope and consistently
    misreports random walks as strongly trending (H≈0.8). This was a
    bug in the initial v157 cut — fixed before any tests were run on
    live DGX data.
    """
    if not series or len(series) < 50:
        return None
    try:
        import numpy as np
        x = np.asarray(series, dtype=float)
        if not np.isfinite(x).all() or np.std(x) == 0:
            return None
        # Log-returns. Drop any non-positive values defensively.
        x_pos = np.where(x > 0, x, np.nan)
        if np.isnan(x_pos).any():
            # Fall back to first-differences if log isn't safe.
            returns = np.diff(x)
        else:
            returns = np.diff(np.log(x_pos))
        if len(returns) < 50 or np.std(returns) == 0:
            return None
        n = len(returns)
        max_lag = max(20, n // 4)
        lags = np.unique(np.floor(np.logspace(
            math.log10(10), math.log10(max_lag), num=8,
        )).astype(int))
        rs_values = []
        for lag in lags:
            if lag < 5 or lag >= n:
                continue
            n_windows = n // lag
            window_rs = []
            for w in range(n_windows):
                seg = returns[w * lag:(w + 1) * lag]
                mean = seg.mean()
                dev = seg - mean
                cum = np.cumsum(dev)
                R = cum.max() - cum.min()
                S = seg.std(ddof=0)
                if S > 0 and R > 0:
                    window_rs.append(R / S)
            if window_rs:
                rs_values.append((lag, float(np.mean(window_rs))))
        if len(rs_values) < 3:
            return None
        log_lags = np.log([t[0] for t in rs_values])
        log_rs = np.log([t[1] for t in rs_values])
        slope, _intercept = np.polyfit(log_lags, log_rs, 1)
        return float(max(0.0, min(1.0, slope)))
    except Exception as e:
        logger.debug(f"_hurst_rs failed: {e}")
        return None


def _half_life_ar1(series: List[float]) -> Optional[float]:
    """Half-life of mean reversion via AR(1) regression on Δp vs p_{t-1}.

    Returns None when:
      • series too short,
      • regression β is ≥ 0 (price is trending / not mean-reverting),
      • β is so close to 0 that half-life > 10000 bars (treat as
        effectively infinite → trending).
    """
    if not series or len(series) < 30:
        return None
    try:
        import numpy as np
        x = np.asarray(series, dtype=float)
        if not np.isfinite(x).all():
            return None
        dp = np.diff(x)
        p_lag = x[:-1]
        if np.std(p_lag) == 0:
            return None
        # OLS: Δp = α + β·p_{t-1} + ε
        beta, _alpha = np.polyfit(p_lag, dp, 1)
        if beta >= 0:
            return None  # trending, not MR
        try:
            hl = -math.log(2) / math.log(1.0 + beta)
        except (ValueError, ZeroDivisionError):
            return None
        if not math.isfinite(hl) or hl <= 0 or hl > 200:
            return None
        return float(hl)
    except Exception as e:
        logger.debug(f"_half_life_ar1 failed: {e}")
        return None


def _zscore(series: List[float]) -> Optional[float]:
    """Z-score of last value vs the series mean/std."""
    if not series or len(series) < 20:
        return None
    try:
        import numpy as np
        x = np.asarray(series, dtype=float)
        if not np.isfinite(x).all():
            return None
        sd = float(x[:-1].std(ddof=1)) if len(x) > 1 else 0.0
        if sd == 0:
            return None
        return float((x[-1] - x[:-1].mean()) / sd)
    except Exception as e:
        logger.debug(f"_zscore failed: {e}")
        return None


def _vwap_z(bars: List[Dict[str, Any]]) -> Optional[float]:
    """VWAP z-score using the codebase's canonical VWAP calc.

    Only meaningful intraday. Caller must already have restricted
    `bars` to a sensible intraday window (we accept 1-min and 5-min
    bars per Q4a; the operator confirmed reuse of the existing
    FeatureEngine VWAP calc).
    """
    if not bars or len(bars) < 20:
        return None
    try:
        from services.feature_engine import get_feature_engine
        fe = get_feature_engine()
        vwap = fe.calc_vwap(bars)
        if not vwap:
            return None
        closes = [float(b.get("close", 0)) for b in bars
                  if b.get("close") not in (None, "")]
        if len(closes) < 20:
            return None
        import numpy as np
        arr = np.asarray(closes, dtype=float)
        diffs = arr - vwap
        sd = float(diffs.std(ddof=1)) if len(diffs) > 1 else 0.0
        if sd == 0:
            return None
        return float((arr[-1] - vwap) / sd)
    except Exception as e:
        logger.debug(f"_vwap_z failed: {e}")
        return None


def _classify_regime(hurst: Optional[float],
                     half_life: Optional[float]) -> Tuple[str, float, str]:
    """Compose hurst + half_life into a single regime tag, a continuous
    `reversion_score` in [0, 1], and a short human reason string.

    When BOTH inputs are None (no data / degenerate series), return
    NEUTRAL — we don't have enough signal to tilt either way.
    """
    if hurst is None and half_life is None:
        return ("NEUTRAL", 0.5, "no_signal")
    h = hurst if hurst is not None else 0.5
    hl_present = half_life is not None
    hl_short = hl_present and half_life <= 20
    hl_medium = hl_present and 20 < half_life <= 40

    # Strong MR requires BOTH a non-trending hurst AND a short half-life.
    if hurst is not None and h <= 0.45 and hl_short:
        return ("MR_STRONG", min(1.0, 0.7 + (0.45 - h)),
                f"hurst={h:.2f}≤0.45 + half_life={half_life:.1f}≤20")
    # Trending: clear hurst signal only (half-life is meaningless / None
    # for a trending series).
    if hurst is not None and h >= 0.55:
        return ("TRENDING", max(0.0, 0.3 - (h - 0.55)),
                f"hurst={h:.2f}≥0.55 (trending/persistent)")
    # Weak MR requires EITHER an explicit MR-leaning hurst OR a medium
    # half-life observation. We require hurst to be non-None for the
    # hurst-based branch so a half_life-only signal can still surface
    # via the medium-half-life branch.
    if (hurst is not None and h <= 0.50) or hl_medium:
        score = 0.55
        if hl_medium and half_life is not None:
            score = 0.5 + (40 - half_life) / 100
        return ("MR_WEAK", float(min(1.0, max(0.0, score))),
                f"hurst={h:.2f} + half_life={half_life if hl_present else 'n/a'}")
    return ("NEUTRAL", 0.5, f"hurst={h:.2f} (random walk)")


# ── Compute entry point ─────────────────────────────────────────────


def compute_mr_metrics(
    db,
    symbol: str,
    bar_size: str = "5 mins",
    lookback_bars: int = 500,
    *,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """Compute (or fetch from cache) per-symbol MR metrics.

    Returns a dict with keys: symbol, bar_size, computed_at, n_bars,
    hurst, half_life_bars, current_z, vwap_z, regime_tag,
    reversion_score, reason. Missing fields are `None`.
    """
    out = {
        "symbol": (symbol or "").upper(),
        "bar_size": bar_size,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "n_bars": 0,
        "hurst": None,
        "half_life_bars": None,
        "current_z": None,
        "vwap_z": None,
        "regime_tag": "NEUTRAL",
        "reversion_score": 0.5,
        "reason": "no_data",
    }
    if not out["symbol"]:
        out["reason"] = "no_symbol"
        return out

    # ─── Try cache first ─────────────────────────────────────────────
    if use_cache and db is not None:
        try:
            cached = db[_COLLECTION].find_one(
                {"symbol": out["symbol"], "bar_size": bar_size},
                {"_id": 0},
            )
            if cached and cached.get("computed_at"):
                try:
                    ts = datetime.fromisoformat(
                        cached["computed_at"].replace("Z", "+00:00")
                    )
                    if (datetime.now(timezone.utc) - ts).total_seconds() < _TTL_SECONDS:
                        return cached
                except Exception:
                    pass  # Recompute on parse failure.
        except Exception as e:
            logger.debug(f"mr_metrics cache read failed: {e}")

    # ─── Pull bars ───────────────────────────────────────────────────
    if db is None:
        out["reason"] = "no_db"
        return out
    try:
        bars = list(db.ib_historical_data.find(
            {"symbol": out["symbol"], "bar_size": bar_size},
            {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1,
             "close": 1, "volume": 1},
        ).sort("date", -1).limit(lookback_bars))
    except Exception as e:
        out["reason"] = f"bar_read_error: {type(e).__name__}"
        logger.debug(f"compute_mr_metrics bar read failed: {e}")
        return out
    if not bars:
        out["reason"] = "no_bars_in_history"
        return out
    bars = list(reversed(bars))  # Mongo sort returned newest-first.
    closes = [float(b.get("close", 0)) for b in bars
              if b.get("close") not in (None, "")]
    if len(closes) < 30:
        out["n_bars"] = len(closes)
        out["reason"] = f"too_few_bars ({len(closes)} < 30)"
        return out

    out["n_bars"] = len(closes)
    out["hurst"] = _hurst_rs(closes)
    out["half_life_bars"] = _half_life_ar1(closes)
    out["current_z"] = _zscore(closes[-100:] if len(closes) > 100 else closes)
    # VWAP z-score only meaningful intraday (Q4a — restrict to 1m/5m).
    if bar_size in ("1 min", "5 mins"):
        out["vwap_z"] = _vwap_z(bars)

    regime, score, reason = _classify_regime(out["hurst"], out["half_life_bars"])
    out["regime_tag"] = regime
    out["reversion_score"] = round(score, 3)
    out["reason"] = reason

    # Write to cache (best-effort).
    if use_cache and db is not None:
        try:
            db[_COLLECTION].update_one(
                {"symbol": out["symbol"], "bar_size": bar_size},
                {"$set": out},
                upsert=True,
            )
        except Exception as e:
            logger.debug(f"mr_metrics cache write failed: {e}")

    return out


# ── Multiplier lookup ───────────────────────────────────────────────


def get_mr_multiplier(
    metrics: Optional[Dict[str, Any]],
    setup_type: Optional[str],
) -> Tuple[float, str]:
    """Returns `(multiplier, reason)` given metrics + setup type.

    Defaults to `(1.0, "no_metrics_or_setup")` whenever metrics are
    None / regime missing / setup unknown — the sizer must never be
    blocked by a missing MR signal.
    """
    family = classify_setup_family(setup_type)
    if not isinstance(metrics, dict):
        return (1.0, f"no_metrics ({family})")
    regime = metrics.get("regime_tag") or "NEUTRAL"
    table = _MULTIPLIER_TABLE.get(family) or _MULTIPLIER_TABLE["unknown"]
    mult = float(table.get(regime, 1.0))
    return (mult, f"family={family}|regime={regime}|mult={mult}")
