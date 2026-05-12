"""
trail_anchor_service.py  ·  v19.34.104  (Feb 2026)
─────────────────────────────────────────────────────────────────────────────
Computes moving-average trail-anchor stop candidates for long-horizon trades.

Why this exists
───────────────
v19.34.100 stood up `services.order_policy_registry`, which dictates a
per-style trail anchor:
  scalp/intraday → ATR
  multi_day/swing → 20-EMA
  investment     → 50-SMA
  position       → 150-SMA (a.k.a. 30-week SMA)

`stop_manager.py` historically only knew how to trail on ATR / fixed-%.
This module is the indicator-lookup + safety-buffered translator: given a
trade and the desired anchor name, it returns the protective stop level
the trailing stop should ratchet toward.

Operator contract (per ask_human in v19.34.101 plan):
  "When an anchor MA hasn't been computed yet for a freshly opened
   position, fall back to the original ATR stop until the anchor is
   available."

Implementation:
  • Read daily closes from `ib_historical_data` (bar_size = '1 day').
  • Need enough warmup bars: 20 for EMA-20, 50 for SMA-50, 150 for SMA-150.
  • If we don't have N bars, return None → caller falls back to ATR/%.
  • Otherwise compute the anchor value and apply a small protective
    buffer (8% of ATR if available, else 0.25% of price) so wicks
    that briefly tag the MA don't immediately stop the trade out.
  • Return the candidate stop price — caller (StopManager) applies the
    same ratchet/direction guards the ATR path uses.

Single source of truth = order_policy_registry.OrderPolicy.stop_trail_anchor.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# Indicator → minimum number of daily bars required for a meaningful value.
_MIN_BARS: Dict[str, int] = {
    "ema_9": 9,
    "ema_20": 20,
    "sma_50": 50,
    "sma_150": 150,
    "sma_200": 200,
    "ema_50": 50,
}


def _calc_sma(closes: List[float], period: int) -> Optional[float]:
    if len(closes) < period or period <= 0:
        return None
    return sum(closes[-period:]) / period


def _calc_ema(closes: List[float], period: int) -> Optional[float]:
    """Standard EMA: seed with the SMA of the first `period` bars, then
    apply 2/(period+1) smoothing over the remaining bars."""
    if len(closes) < period or period <= 0:
        return None
    k = 2.0 / (period + 1)
    seed = sum(closes[:period]) / period
    ema = seed
    for px in closes[period:]:
        ema = px * k + ema * (1 - k)
    return ema


def compute_anchor_value(
    closes: List[float],
    anchor: str,
) -> Optional[float]:
    """Return the indicator value for `anchor` over the supplied daily
    closes (oldest → newest). Returns None if we don't have enough
    warmup bars to compute the indicator meaningfully.

    Treats unknown anchors (including "atr", "structure", "fixed") as
    "no MA value available" and returns None — caller falls back to its
    legacy trail logic.
    """
    if not closes:
        return None
    key = (anchor or "").strip().lower()
    min_bars = _MIN_BARS.get(key)
    if min_bars is None:
        return None
    if len(closes) < min_bars:
        return None

    if key.startswith("ema_"):
        period = int(key.split("_", 1)[1])
        return _calc_ema(closes, period)
    if key.startswith("sma_"):
        period = int(key.split("_", 1)[1])
        return _calc_sma(closes, period)
    return None


def _fetch_daily_closes(db, symbol: str, limit: int = 250) -> Optional[List[float]]:
    """Pull the most recent N daily closes from `ib_historical_data`,
    ordered oldest → newest. Returns None if DB is missing or no rows.
    Matches the pattern in `realtime_technical_service._get_daily_bars_from_db`
    so we share the same data contract.
    """
    if db is None:
        return None
    try:
        rows = list(
            db["ib_historical_data"].find(
                {"symbol": symbol.upper(), "bar_size": "1 day"},
                {"_id": 0, "date": 1, "close": 1},
            ).sort("date", -1).limit(limit)
        )
        if not rows:
            return None
        # Reverse to oldest → newest for indicator math.
        rows.reverse()
        closes = [float(r["close"]) for r in rows if r.get("close") is not None]
        return closes if closes else None
    except Exception as exc:
        logger.debug(f"trail_anchor: daily-close fetch failed for {symbol}: {exc}")
        return None


def compute_anchor_stop(
    db,
    symbol: str,
    anchor: str,
    direction: str,
    current_price: Optional[float] = None,
    atr: Optional[float] = None,
    buffer_atr_mult: float = 0.08,
    buffer_pct_fallback: float = 0.0025,
) -> Optional[float]:
    """Translate an anchor name + market data into a protective trailing
    stop price.

    Returns None when:
      • db is None
      • not enough daily bars to compute the anchor
      • anchor is "atr"/"structure"/"fixed"/None (caller handles those)

    The returned price has a small protective buffer baked in so wicks
    that briefly tag the MA don't trip the stop:
      • For LONG  → stop = anchor_value - buffer (so price must
        meaningfully break the MA before we exit)
      • For SHORT → stop = anchor_value + buffer

    Buffer sizing:
      • If `atr` is provided → buffer = atr * buffer_atr_mult (8%)
      • Else                → buffer = current_price * buffer_pct_fallback (0.25%)
      • Else                → no buffer (raw anchor value)

    The caller (StopManager) MUST apply the ratchet check — this helper
    never reasons about the existing stop level.
    """
    if not anchor or anchor.strip().lower() in {"atr", "structure", "fixed", ""}:
        return None

    closes = _fetch_daily_closes(db, symbol, limit=max(_MIN_BARS.get(anchor.lower(), 50), 50) + 10)
    if not closes:
        return None

    anchor_value = compute_anchor_value(closes, anchor)
    if anchor_value is None or anchor_value <= 0:
        return None

    # Protective buffer
    if atr and atr > 0:
        buffer = atr * buffer_atr_mult
    elif current_price and current_price > 0:
        buffer = current_price * buffer_pct_fallback
    else:
        buffer = 0.0

    dir_lower = (direction or "").strip().lower()
    if dir_lower in {"short", "sell", "sht"}:
        return round(anchor_value + buffer, 2)
    # default to long
    return round(anchor_value - buffer, 2)
