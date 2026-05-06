"""
Strategy Tilt — dynamic long/short sizing bias from rolling per-side Sharpe.

Background
----------
The bot trades both long and short setups, but the DOWN side occasionally
goes through cold streaks where shorting costs money even when the
setups look valid. Conversely, during a strong downtrend longs bleed.
Rather than flat-allocate risk 50/50 across sides, we scale position
size by each side's recent risk-adjusted return.

Math
----
For each side (long, short) we compute the **Sharpe ratio of per-trade
R-multiples** over the last `lookback_days` days:

    R_i      = trade.pnl / trade.risk_amount     (for trade i on that side)
    sharpe_s = mean(R_side) / std(R_side)        (std clipped to >=1e-6)

The side-tilt multiplier is:

    tilt_side = clamp(1 + (sharpe_side - mean_sharpe) / scale, floor, ceiling)

where `scale` controls how aggressively we tilt. Conservative defaults:

    floor   = 0.5       # never drop below 50% size
    ceiling = 1.5       # never more than 150% size
    scale   = 1.0       # one Sharpe delta → ~1.0 multiplier delta
    min_trades_per_side = 10   # no tilt if not enough sample

If either side has too few trades, the tilt is neutral (1.0, 1.0) — we
never over-extrapolate from a tiny sample.

Integration
-----------
Consumed by `opportunity_evaluator.py` — multiplied into the position
size stack alongside confidence-gate and regime multipliers. See
`get_strategy_tilt_cached()` for the memoised accessor the bot should
use at scan-time (re-computed at most every 5 minutes).

Returns (from compute_strategy_tilt) a dict:
    {
        "long_tilt":     float,   # bounded [floor, ceiling]
        "short_tilt":    float,
        "sharpe_long":   float,
        "sharpe_short":  float,
        "n_long":        int,
        "n_short":       int,
        "computed_at":   ISO timestamp,
        "lookback_days": int,
    }
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Iterable, List, Optional

import logging

logger = logging.getLogger(__name__)


# ── pure math ────────────────────────────────────────────────────────────

def _r_multiple(trade: Dict[str, Any]) -> Optional[float]:
    """Return the trade's realised R-multiple, or None if unusable.

    Looks for an explicit `r_multiple` first, then falls back to pnl/risk.
    """
    r = trade.get("r_multiple")
    if r is not None:
        try:
            rv = float(r)
            if math.isfinite(rv):
                return rv
        except (TypeError, ValueError):
            pass
    pnl = trade.get("pnl") if "pnl" in trade else trade.get("realized_pnl")
    risk = trade.get("risk_amount") or trade.get("risk") or 0.0
    try:
        risk = float(risk)
        pnl = float(pnl) if pnl is not None else None
    except (TypeError, ValueError):
        return None
    if pnl is None or risk <= 0:
        return None
    return pnl / risk


def _sharpe(rs: List[float]) -> float:
    """Sharpe of per-trade R-multiples. Zero when sample is degenerate."""
    if len(rs) < 2:
        return 0.0
    mean = statistics.mean(rs)
    std = statistics.pstdev(rs)  # population stdev — stable for small N
    if std < 1e-6:
        return 0.0
    return mean / std


def compute_strategy_tilt(
    trades: Iterable[Dict[str, Any]],
    *,
    lookback_days: int = 30,
    floor: float = 0.5,
    ceiling: float = 1.5,
    scale: float = 1.0,
    min_trades_per_side: int = 10,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Pure function — compute long/short tilt from a list of closed trades.

    Args:
        trades: iterable of trade dicts. Each must have (any of):
                `direction` ("long"|"short"), a closure timestamp
                (`closed_at` | `exit_date` | `created_at`), and
                a signed pnl ref (`pnl` / `realized_pnl`) with
                `risk_amount` — or a pre-computed `r_multiple`.
        lookback_days: only consider trades closed within this window.
        floor/ceiling: tilt bounds (never < floor, never > ceiling).
        scale: Sharpe delta that maps to a 1.0 tilt change.
        min_trades_per_side: below this → neutral tilt (1.0) for that side.
        now: inject current time for testability.

    Returns dict described at module top.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)

    r_long: List[float] = []
    r_short: List[float] = []

    for t in trades:
        direction = (t.get("direction") or "").lower()
        if direction not in ("long", "short"):
            continue

        # Accept ISO timestamps from several fields
        ts_str = t.get("closed_at") or t.get("exit_date") or t.get("created_at")
        if ts_str:
            try:
                ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    continue
            except Exception:
                # Unparseable timestamp → include anyway (conservative)
                pass

        r = _r_multiple(t)
        if r is None:
            continue
        (r_long if direction == "long" else r_short).append(r)

    n_long, n_short = len(r_long), len(r_short)
    sharpe_long = _sharpe(r_long)
    sharpe_short = _sharpe(r_short)

    # Tilt math — recenter around the mean of the two sides
    mean_sharpe = (sharpe_long + sharpe_short) / 2.0
    long_tilt = 1.0
    short_tilt = 1.0
    if n_long >= min_trades_per_side:
        long_tilt = 1.0 + (sharpe_long - mean_sharpe) / max(scale, 1e-6)
    if n_short >= min_trades_per_side:
        short_tilt = 1.0 + (sharpe_short - mean_sharpe) / max(scale, 1e-6)

    # Clip to bounds
    long_tilt = max(floor, min(ceiling, long_tilt))
    short_tilt = max(floor, min(ceiling, short_tilt))

    return {
        "long_tilt": round(long_tilt, 4),
        "short_tilt": round(short_tilt, 4),
        "sharpe_long": round(sharpe_long, 4),
        "sharpe_short": round(sharpe_short, 4),
        "n_long": n_long,
        "n_short": n_short,
        "computed_at": now.isoformat(),
        "lookback_days": lookback_days,
    }


# ── live DB accessor with 5-minute memoisation ───────────────────────────

_cache: Dict[str, Any] = {"at": None, "value": None}
_CACHE_TTL_SECONDS = 300  # 5 minutes


def _fetch_recent_closed_trades(db, lookback_days: int) -> List[Dict[str, Any]]:
    """Pull closed trades from `bot_trades` within the lookback window."""
    if db is None:
        return []
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    try:
        # `bot_trades` is the mongo collection populated by position_manager
        cursor = db["bot_trades"].find(
            {
                "status": {"$in": ["closed", "filled"]},
                "closed_at": {"$gte": cutoff_iso},
            },
            {"_id": 0, "direction": 1, "r_multiple": 1, "pnl": 1,
             "realized_pnl": 1, "risk_amount": 1, "closed_at": 1, "created_at": 1},
        )
        return list(cursor)
    except Exception as e:
        logger.debug(f"[StrategyTilt] Failed to fetch trades: {e}")
        return []


def get_strategy_tilt_cached(
    db,
    *,
    lookback_days: int = 30,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Returns the current tilt dict, re-computing at most every 5 minutes.

    Caller passes the Mongo `db` (or a MotorDB proxy — both work since we
    only use sync find()). If the DB is None or no trades are found, tilt
    is neutral (1.0, 1.0).
    """
    now_ts = datetime.now(timezone.utc).timestamp()
    last_at = _cache.get("at")
    if (
        not force_refresh
        and last_at is not None
        and _cache.get("value") is not None
        and (now_ts - last_at) < _CACHE_TTL_SECONDS
    ):
        return _cache["value"]

    trades = _fetch_recent_closed_trades(db, lookback_days)
    tilt = compute_strategy_tilt(trades, lookback_days=lookback_days)
    _cache["at"] = now_ts
    _cache["value"] = tilt
    return tilt


def reset_cache_for_tests() -> None:
    _cache["at"] = None
    _cache["value"] = None


def get_side_tilt_multiplier(direction: str, tilt: Dict[str, Any]) -> float:
    """Convenience accessor used inside opportunity_evaluator.
    Returns 1.0 for anything that isn't explicitly 'long' or 'short'.
    """
    d = (direction or "").lower()
    if d == "long":
        return float(tilt.get("long_tilt", 1.0))
    if d == "short":
        return float(tilt.get("short_tilt", 1.0))
    return 1.0
