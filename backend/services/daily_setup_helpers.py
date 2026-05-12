"""
daily_setup_helpers.py  ·  v19.34.95
─────────────────────────────────────────────────────────────────────────────
Shared, pure-function helpers used by the new swing / investment / position
daily-bar detectors (pocket_pivot, vcp_breakout, stage_2_breakout, etc).

All helpers operate on plain `bars` lists of dicts with keys:
  date · open · high · low · close · volume

No I/O, no DB, no async — fully unit-testable.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────
# Basic indicators (mirror realtime_technical_service ones, kept
# local so detectors don't pull a service handle)
# ─────────────────────────────────────────────────────────────────
def sma(values: List[float], period: int) -> Optional[float]:
    if not values or len(values) < period or period <= 0:
        return None
    return sum(values[-period:]) / period


def ema(values: List[float], period: int) -> Optional[float]:
    if not values or len(values) < period or period <= 0:
        return None
    k = 2.0 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def sma_series(values: List[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for i in range(len(values)):
        if i + 1 < period:
            out.append(None)
        else:
            out.append(sum(values[i + 1 - period : i + 1]) / period)
    return out


def ema_series(values: List[float], period: int) -> List[Optional[float]]:
    if period <= 0:
        return [None] * len(values)
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    k = 2.0 / (period + 1)
    e = sum(values[:period]) / period
    out[period - 1] = e
    for i in range(period, len(values)):
        e = values[i] * k + e * (1 - k)
        out[i] = e
    return out


def atr(bars: List[Dict], period: int = 14) -> Optional[float]:
    if len(bars) < period + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, low, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - low, abs(h - pc), abs(low - pc)))
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def rsi(closes: List[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[-period:]) / period
    avg_l = sum(losses[-period:]) / period
    if avg_l == 0:
        return 100.0
    rs_ = avg_g / avg_l
    return 100.0 - (100.0 / (1.0 + rs_))


# ─────────────────────────────────────────────────────────────────
# Bar-frame aggregation
# ─────────────────────────────────────────────────────────────────
def _parse_date(s) -> Optional[datetime]:
    if not s:
        return None
    if isinstance(s, datetime):
        return s
    s = str(s)[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None


def aggregate_to_weekly(daily_bars: List[Dict]) -> List[Dict]:
    """Aggregate daily bars to weekly (ISO week-anchored, Mon-Fri).

    Each weekly bar:  open=Mon open, close=Fri close, high=max, low=min,
    volume=sum, date=Monday's date.
    """
    if not daily_bars:
        return []
    weekly: List[Dict] = []
    cur: Optional[Dict] = None
    cur_year_week: Optional[Tuple[int, int]] = None
    for b in daily_bars:
        d = _parse_date(b.get("date"))
        if not d:
            continue
        iso_y, iso_w, _ = d.isocalendar()
        key = (iso_y, iso_w)
        if cur is None or key != cur_year_week:
            if cur is not None:
                weekly.append(cur)
            cur = {
                "date": (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d"),
                "open": float(b["open"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": float(b["close"]),
                "volume": float(b.get("volume", 0) or 0),
            }
            cur_year_week = key
        else:
            cur["high"] = max(cur["high"], float(b["high"]))
            cur["low"] = min(cur["low"], float(b["low"]))
            cur["close"] = float(b["close"])
            cur["volume"] += float(b.get("volume", 0) or 0)
    if cur is not None:
        weekly.append(cur)
    return weekly


def aggregate_to_monthly(daily_bars: List[Dict]) -> List[Dict]:
    if not daily_bars:
        return []
    monthly: List[Dict] = []
    cur: Optional[Dict] = None
    cur_year_month: Optional[Tuple[int, int]] = None
    for b in daily_bars:
        d = _parse_date(b.get("date"))
        if not d:
            continue
        key = (d.year, d.month)
        if cur is None or key != cur_year_month:
            if cur is not None:
                monthly.append(cur)
            cur = {
                "date": d.replace(day=1).strftime("%Y-%m-%d"),
                "open": float(b["open"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": float(b["close"]),
                "volume": float(b.get("volume", 0) or 0),
            }
            cur_year_month = key
        else:
            cur["high"] = max(cur["high"], float(b["high"]))
            cur["low"] = min(cur["low"], float(b["low"]))
            cur["close"] = float(b["close"])
            cur["volume"] += float(b.get("volume", 0) or 0)
    if cur is not None:
        monthly.append(cur)
    return monthly


# ─────────────────────────────────────────────────────────────────
# Pattern primitives
# ─────────────────────────────────────────────────────────────────
def pct_change(a: float, b: float) -> float:
    if not b:
        return 0.0
    return (a - b) / b * 100.0


def consolidation_range_pct(bars: List[Dict], n: int) -> Optional[float]:
    """Return (high - low) / midpoint × 100 over the last n bars."""
    if len(bars) < n or n <= 0:
        return None
    seg = bars[-n:]
    hi = max(b["high"] for b in seg)
    lo = min(b["low"] for b in seg)
    mid = (hi + lo) / 2.0
    if mid <= 0:
        return None
    return (hi - lo) / mid * 100.0


def detect_flat_base(
    bars: List[Dict],
    min_bars: int,
    max_bars: int,
    max_range_pct: float,
) -> Optional[Dict]:
    """Find the longest flat base in the last `max_bars` bars.

    A base is "flat" if its peak-to-trough range / midpoint ≤ max_range_pct.
    Returns {"start_idx", "end_idx", "high", "low", "midpoint", "range_pct"}
    or None.
    """
    n = len(bars)
    if n < min_bars:
        return None
    best: Optional[Dict] = None
    end = n - 1  # base anchored at most-recent bar
    for length in range(min_bars, min(max_bars, n) + 1):
        start = end - length + 1
        seg = bars[start : end + 1]
        hi = max(b["high"] for b in seg)
        lo = min(b["low"] for b in seg)
        mid = (hi + lo) / 2.0
        if mid <= 0:
            continue
        rng_pct = (hi - lo) / mid * 100.0
        if rng_pct <= max_range_pct:
            best = {
                "start_idx": start,
                "end_idx": end,
                "length": length,
                "high": hi,
                "low": lo,
                "midpoint": mid,
                "range_pct": rng_pct,
            }
    return best


def is_breaking_out(bars: List[Dict], resistance: float, vol_mult: float = 1.3, vol_lookback: int = 20) -> bool:
    """Today's close > resistance, today's volume ≥ vol_mult × avg(vol_lookback)."""
    if not bars:
        return False
    last = bars[-1]
    if last["close"] <= resistance:
        return False
    if len(bars) < vol_lookback + 1:
        return True  # no vol context — accept on price alone
    avg_v = sum(b["volume"] for b in bars[-vol_lookback - 1 : -1]) / vol_lookback
    if avg_v <= 0:
        return True
    return last["volume"] >= vol_mult * avg_v


def find_pivot_high(bars: List[Dict], lookback: int = 5, lookahead: int = 5) -> Optional[int]:
    """Return index of the most-recent confirmed pivot high.

    A pivot high is the highest `high` over a (lookback + lookahead + 1) window
    centered on bar i. We scan backwards from the latest fully-confirmed bar.
    """
    n = len(bars)
    if n < lookback + lookahead + 1:
        return None
    for i in range(n - lookahead - 1, lookback - 1, -1):
        win = bars[i - lookback : i + lookahead + 1]
        if bars[i]["high"] == max(b["high"] for b in win):
            return i
    return None


def find_pivot_low(bars: List[Dict], lookback: int = 5, lookahead: int = 5) -> Optional[int]:
    n = len(bars)
    if n < lookback + lookahead + 1:
        return None
    for i in range(n - lookahead - 1, lookback - 1, -1):
        win = bars[i - lookback : i + lookahead + 1]
        if bars[i]["low"] == min(b["low"] for b in win):
            return i
    return None


# ─────────────────────────────────────────────────────────────────
# Mansfield Relative Strength (vs benchmark, default SPY)
# ─────────────────────────────────────────────────────────────────
def mansfield_rs(symbol_closes: List[float], benchmark_closes: List[float], lookback: int = 130) -> Optional[float]:
    """Mansfield RS — symbol return vs benchmark return over `lookback` bars,
    scaled so 0 = on-par with benchmark, positive = outperforming.

    Returns None if not enough data on either side.
    """
    if len(symbol_closes) < lookback + 1 or len(benchmark_closes) < lookback + 1:
        return None
    s0, s1 = symbol_closes[-lookback - 1], symbol_closes[-1]
    b0, b1 = benchmark_closes[-lookback - 1], benchmark_closes[-1]
    if s0 <= 0 or b0 <= 0:
        return None
    sym_ret = (s1 / s0) - 1.0
    bm_ret = (b1 / b0) - 1.0
    return (sym_ret - bm_ret) * 100.0


def relative_strength_rank(
    symbol_closes: List[float],
    benchmark_closes: List[float],
    lookback: int = 130,
) -> Optional[float]:
    """Convenience: 0-100 RS rank approximation based on Mansfield value.

    +20% outperformance → 95, parity → 50, -20% → 5. Soft sigmoid scaling.
    """
    val = mansfield_rs(symbol_closes, benchmark_closes, lookback)
    if val is None:
        return None
    # Logistic squash: each 10% of outperf shifts ~25 rank points
    return 100.0 / (1.0 + math.exp(-val / 10.0))
