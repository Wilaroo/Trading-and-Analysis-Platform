"""
Multi-Timeframe Regime Classifier
=================================
Pure, dependency-free trend/context logic for the Market Regime Engine. Kept
isolated from data-fetching so it is fully unit-testable with injected bars.

Lanes (per the agreed design):
  LONG  (anchor)  — daily   — 20 SMA / 50 SMA / 200 SMA + price structure
  MID             — 1 hour  — 20 EMA / 50 EMA + structure
  SHORT           — 5 mins  — 9 EMA / 21 EMA + VWAP   (21 EMA + VWAP per operator)
  MICRO (trigger) — 1 min   — 9 EMA / 21 EMA + VWAP

Each lane -> 0-100 score -> bias (UP >=60 / DOWN <=40 / NEUTRAL otherwise).
Intraday lanes are blended (MID 0.5 / SHORT 0.3 / MICRO 0.2, renormalized over
available lanes). The LONG anchor + blended intraday produce a CONTEXT label
that maps to a per-direction trading mode (long vs short scored separately).
"""
from typing import Dict, List, Optional


# Tolerance band around a moving average (matches engine's ±0.25%). Price inside
# the band gets half credit (neutral) instead of a hard 0/full flip.
_TOL = 0.0025


def _sma(vals: List[float], p: int) -> float:
    if not vals:
        return 0.0
    if len(vals) < p:
        return sum(vals) / len(vals)
    return sum(vals[-p:]) / p


def _ema(vals: List[float], p: int) -> float:
    if not vals:
        return 0.0
    if len(vals) < p:
        return vals[-1]
    k = 2 / (p + 1)
    e = sum(vals[:p]) / p
    for v in vals[p:]:
        e = (v - e) * k + e
    return e


def _band(price: float, level: float, full: float) -> float:
    """`full` pts when price clearly > level, 0 when clearly <, half inside band."""
    if level <= 0:
        return 0.0
    diff = (price - level) / level
    if diff > _TOL:
        return full
    if diff < -_TOL:
        return 0.0
    return full * 0.5


def _structure(highs: List[float], lows: List[float]) -> float:
    """0-100: 100 = clean higher-highs/higher-lows uptrend, 0 = downtrend."""
    if len(highs) < 5 or len(lows) < 5:
        return 50.0
    up = dn = 0
    for i in range(1, len(highs)):
        if highs[i] > highs[i - 1]:
            up += 1
        if lows[i] > lows[i - 1]:
            up += 1
        if highs[i] < highs[i - 1]:
            dn += 1
        if lows[i] < lows[i - 1]:
            dn += 1
    t = up + dn
    return 50.0 if t == 0 else up / t * 100


def _ohlc(bars: List[Dict]):
    closes = [b.get("close", b.get("c", 0)) for b in bars]
    highs = [b.get("high", b.get("h", 0)) for b in bars]
    lows = [b.get("low", b.get("l", 0)) for b in bars]
    return closes, highs, lows


def _vwap(bars: List[Dict]) -> float:
    """Volume-weighted average price over the provided bar window (rolling).
    Typical price = (H+L+C)/3. Falls back to last close when volume is absent."""
    num = den = 0.0
    for b in bars:
        h = b.get("high", b.get("h", 0))
        l = b.get("low", b.get("l", 0))
        c = b.get("close", b.get("c", 0))
        v = b.get("volume", b.get("v", 0)) or 0
        num += ((h + l + c) / 3) * v
        den += v
    if den:
        return num / den
    return bars[-1].get("close", bars[-1].get("c", 0)) if bars else 0.0


def lane_bias(score: Optional[float]) -> str:
    if score is None:
        return "UNKNOWN"
    if score >= 60:
        return "UP"
    if score <= 40:
        return "DOWN"
    return "NEUTRAL"


def score_long_lane(daily_bars: List[Dict]) -> Optional[float]:
    """Daily anchor — 20 SMA / 50 SMA / 200 SMA + structure (operator: 20 SMA)."""
    if not daily_bars or len(daily_bars) < 50:
        return None
    closes, highs, lows = _ohlc(daily_bars)
    p = closes[-1]
    sma20, sma50, sma200 = _sma(closes, 20), _sma(closes, 50), _sma(closes, 200)
    s = 0.0
    s += _band(p, sma20, 25)        # price vs 20 SMA
    s += _band(p, sma50, 20)        # price vs 50 SMA
    s += _band(p, sma200, 15)       # price vs 200 SMA
    s += _band(sma20, sma50, 15)    # 20 SMA vs 50 SMA alignment
    s += _structure(highs[-20:], lows[-20:]) * 25 / 100
    return round(s, 1)


def score_intraday_lane(bars: List[Dict], fast: int = 9, slow: int = 21,
                        use_vwap: bool = False) -> Optional[float]:
    """Intraday lane — fast/slow EMA + (VWAP for short/micro, else structure).

    SHORT (5m) and MICRO (1m) use VWAP as the 4th component (operator spec:
    "VWAP, EMA9/21"); MID (1h) keeps structure since session VWAP is less
    meaningful across multi-day 1h bars."""
    if not bars or len(bars) < slow:
        return None
    closes, highs, lows = _ohlc(bars)
    p = closes[-1]
    ef, es = _ema(closes, fast), _ema(closes, slow)
    s = 0.0
    s += _band(p, ef, 30)       # price vs fast EMA
    s += _band(p, es, 25)       # price vs slow EMA
    s += _band(ef, es, 15)      # fast vs slow EMA alignment
    if use_vwap:
        s += _band(p, _vwap(bars), 30)   # price vs VWAP
    else:
        s += _structure(highs[-20:], lows[-20:]) * 30 / 100
    return round(s, 1)


def blend_intraday(mid: Optional[float], short: Optional[float],
                   micro: Optional[float]) -> Optional[float]:
    """Weighted blend MID 0.5 / SHORT 0.3 / MICRO 0.2, renormalized over available."""
    weights = {"mid": 0.5, "short": 0.3, "micro": 0.2}
    vals = {"mid": mid, "short": short, "micro": micro}
    total_w = blended = 0.0
    for k, v in vals.items():
        if v is None:
            continue
        blended += v * weights[k]
        total_w += weights[k]
    if total_w == 0:
        return None
    return round(blended / total_w, 1)


def classify_context(long_score: Optional[float], intraday_score: Optional[float]) -> str:
    """Map (long anchor bias, intraday bias) -> context label."""
    lb = lane_bias(long_score)
    ib = lane_bias(intraday_score)
    if lb == "UNKNOWN":
        return "UNKNOWN"
    if ib == "UNKNOWN":
        # No intraday read — fall back to the anchor only.
        return {"UP": "ALIGNED_UP", "DOWN": "ALIGNED_DOWN"}.get(lb, "MIXED")
    if lb == "UP" and ib == "UP":
        return "ALIGNED_UP"
    if lb == "DOWN" and ib == "DOWN":
        return "ALIGNED_DOWN"
    if lb == "UP" and ib == "DOWN":
        return "PULLBACK_IN_UPTREND"
    if lb == "DOWN" and ib == "UP":
        return "BOUNCE_IN_DOWNTREND"
    return "MIXED"


# Per-direction trading mode by context. Strings match TradingMode enum values.
def mode_for_direction(context: str, direction: str, long_score: Optional[float]) -> str:
    d = "long" if direction == "long" else "short"
    ls = long_score if long_score is not None else 50.0
    if context == "ALIGNED_UP":
        if d == "long":
            return "aggressive" if ls >= 70 else "normal"
        return "defensive"  # shorts against a confirmed up anchor
    if context == "PULLBACK_IN_UPTREND":
        return "normal" if d == "long" else "cautious"
    if context == "BOUNCE_IN_DOWNTREND":
        return "cautious" if d == "long" else "normal"
    if context == "ALIGNED_DOWN":
        if d == "short":
            return "aggressive" if ls <= 30 else "normal"
        return "defensive"  # longs against a confirmed down anchor
    # MIXED / UNKNOWN
    return "cautious"


def tf_alignment(scores: List[Optional[float]]) -> Dict:
    """How strongly the lanes agree. Returns dominant bias + agreement ratio."""
    biases = [lane_bias(s) for s in scores if s is not None]
    if not biases:
        return {"dominant": "UNKNOWN", "ratio": 0.0, "lanes_counted": 0}
    up = biases.count("UP")
    dn = biases.count("DOWN")
    neutral = biases.count("NEUTRAL")
    counts = {"UP": up, "DOWN": dn, "NEUTRAL": neutral}
    dominant = max(counts, key=counts.get)
    ratio = round(counts[dominant] / len(biases), 2)
    return {"dominant": dominant, "ratio": ratio, "lanes_counted": len(biases),
            "up": up, "down": dn, "neutral": neutral}


_CONTEXT_RECO = {
    "ALIGNED_UP": "All timeframes aligned up — favor momentum longs, full size.",
    "PULLBACK_IN_UPTREND": "Daily uptrend with an intraday pullback — buy the dip into support; longs at normal size, shorts scalp-only.",
    "MIXED": "Conflicting timeframes — be selective, reduce size, quick profits.",
    "BOUNCE_IN_DOWNTREND": "Daily downtrend with an intraday bounce — sell the rip into resistance; shorts at normal size, longs scalp-only.",
    "ALIGNED_DOWN": "All timeframes aligned down — favor shorts/cash, avoid catching knives.",
    "UNKNOWN": "Insufficient data for multi-timeframe classification.",
}


def build_multi_tf(long_score: Optional[float], mid_score: Optional[float],
                   short_score: Optional[float], micro_score: Optional[float]) -> Dict:
    """Assemble the full multi-timeframe analysis dict (pure)."""
    intraday = blend_intraday(mid_score, short_score, micro_score)
    context = classify_context(long_score, intraday)
    align = tf_alignment([long_score, mid_score, short_score, micro_score])
    return {
        "context": context,
        "intraday_score": intraday,
        "intraday_bias": lane_bias(intraday),
        "tf_alignment": align,
        "lanes": {
            "long": {"timeframe": "1 day", "score": long_score, "bias": lane_bias(long_score)},
            "mid": {"timeframe": "1 hour", "score": mid_score, "bias": lane_bias(mid_score)},
            "short": {"timeframe": "5 mins", "score": short_score, "bias": lane_bias(short_score)},
            "micro": {"timeframe": "1 min", "score": micro_score, "bias": lane_bias(micro_score)},
        },
        "modes": {
            "long": mode_for_direction(context, "long", long_score),
            "short": mode_for_direction(context, "short", long_score),
        },
        "recommendation": _CONTEXT_RECO.get(context, _CONTEXT_RECO["UNKNOWN"]),
    }
