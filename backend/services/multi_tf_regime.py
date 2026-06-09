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


# ---------------------------------------------------------------------------
# A(a) — blend SPY/QQQ/IWM per lane; B1(c) — per-index TICK internals;
# B2(c) — confirm/contradict + climax. Pure, testable.
# ---------------------------------------------------------------------------
INDEX_WEIGHTS = {"SPY": 0.5, "QQQ": 0.3, "IWM": 0.2}

# TICK internals tuning (operator-tunable).
_TICK_SCALE = 400.0      # smoothed TICK that maps to a full +/-50 score swing
_TICK_BIAS_HI = 60.0
_TICK_BIAS_LO = 40.0
_CLIMAX_NYSE = 1000.0
_CLIMAX_NASD = 1200.0
_DIVERGENCE_PTS = 15.0   # index score gap that flags a divergence


def weighted_blend(values: Dict[str, Optional[float]], weights: Dict[str, float]) -> Optional[float]:
    """Weighted blend over available (non-None) members, renormalized."""
    total_w = blended = 0.0
    for k, v in values.items():
        if v is None:
            continue
        w = weights.get(k, 0.0)
        blended += v * w
        total_w += w
    if total_w == 0:
        return None
    return round(blended / total_w, 1)


def score_internals(tick_bars: List[Dict], market: str = "NYSE") -> Optional[Dict]:
    """Map intraday TICK 1-min bars -> a 0-100 internals score + climax flag.

    smoothed = EMA(10) of 1-min TICK closes (net up/down-tick pressure);
    cumulative = session sum; score = 50 +/- (smoothed/scale)*50 clipped.
    Climax when the recent window prints a TICK extreme (NYSE +/-1000, NASD +/-1200)."""
    if not tick_bars or len(tick_bars) < 5:
        return None
    closes = [b.get("close", b.get("c", 0)) for b in tick_bars]
    highs = [b.get("high", b.get("h", 0)) for b in tick_bars]
    lows = [b.get("low", b.get("l", 0)) for b in tick_bars]
    smoothed = _ema(closes, 10)
    cumulative = sum(closes)
    score = 50.0 + max(-50.0, min(50.0, smoothed / _TICK_SCALE * 50.0))
    bias = "UP" if score >= _TICK_BIAS_HI else "DOWN" if score <= _TICK_BIAS_LO else "NEUTRAL"
    clim = _CLIMAX_NASD if market == "NASD" else _CLIMAX_NYSE
    recent_hi = max(highs[-30:]) if highs else 0
    recent_lo = min(lows[-30:]) if lows else 0
    climax_dir = None
    if recent_hi >= clim and recent_lo <= -clim:
        climax_dir = "BUY_CLIMAX" if recent_hi >= abs(recent_lo) else "SELL_CLIMAX"
    elif recent_hi >= clim:
        climax_dir = "BUY_CLIMAX"
    elif recent_lo <= -clim:
        climax_dir = "SELL_CLIMAX"
    return {"market": market, "smoothed": round(smoothed, 1), "cumulative": round(cumulative, 1),
            "score": round(score, 1), "bias": bias,
            "climax": climax_dir is not None, "climax_dir": climax_dir,
            "recent_high": recent_hi, "recent_low": recent_lo}


def combine_internals(nyse: Optional[Dict], nasd: Optional[Dict]) -> Optional[Dict]:
    """Market-level internals: NYSE covers SPY+IWM (0.7), Nasdaq covers QQQ (0.3)."""
    sc = weighted_blend(
        {"nyse": nyse["score"] if nyse else None, "nasd": nasd["score"] if nasd else None},
        {"nyse": 0.7, "nasd": 0.3},
    )
    if sc is None:
        return None
    bias = "UP" if sc >= _TICK_BIAS_HI else "DOWN" if sc <= _TICK_BIAS_LO else "NEUTRAL"
    climax = bool((nyse and nyse["climax"]) or (nasd and nasd["climax"]))
    climax_dir = (nyse and nyse.get("climax_dir")) or (nasd and nasd.get("climax_dir"))
    return {"score": sc, "bias": bias, "climax": climax, "climax_dir": climax_dir,
            "nyse": nyse, "nasdaq": nasd}


def apply_internals_adjustment(intraday_score: Optional[float], internals: Optional[Dict]) -> Optional[float]:
    """B2(c) confirm/contradict: pull intraday toward neutral when internals
    contradict the price bias (selloff/rally not broad), gently reinforce when
    they agree. Bounded so internals refine but never dominate price."""
    if not internals or intraday_score is None:
        return intraday_score
    isc = internals["score"]
    price_dir = 1 if intraday_score > 52 else -1 if intraday_score < 48 else 0
    int_dir = 1 if isc > 55 else -1 if isc < 45 else 0
    if price_dir == 0 or int_dir == 0:
        return intraday_score
    mag = min(1.0, abs(isc - 50) / 40.0)
    if price_dir == int_dir:          # confirm -> mild reinforcement
        adjust = price_dir * 4.0 * mag
    else:                             # contradict -> pull toward neutral
        adjust = -price_dir * 8.0 * mag
    return round(max(0.0, min(100.0, intraday_score + adjust)), 1)


def index_divergence(spy: Optional[float], qqq: Optional[float], iwm: Optional[float]) -> List[str]:
    """Flag index divergence from SPY on the intraday read (today's move)."""
    flags = []
    if spy is not None and qqq is not None:
        if qqq <= spy - _DIVERGENCE_PTS:
            flags.append("TECH_WEAK")
        elif qqq >= spy + _DIVERGENCE_PTS:
            flags.append("TECH_STRONG")
    if spy is not None and iwm is not None:
        if iwm <= spy - _DIVERGENCE_PTS:
            flags.append("SMALLCAP_WEAK")
        elif iwm >= spy + _DIVERGENCE_PTS:
            flags.append("SMALLCAP_STRONG")
    return flags



_CONTEXT_RECO = {
    "ALIGNED_UP": "All timeframes aligned up — favor momentum longs, full size.",
    "PULLBACK_IN_UPTREND": "Daily uptrend with an intraday pullback — buy the dip into support; longs at normal size, shorts scalp-only.",
    "MIXED": "Conflicting timeframes — be selective, reduce size, quick profits.",
    "BOUNCE_IN_DOWNTREND": "Daily downtrend with an intraday bounce — sell the rip into resistance; shorts at normal size, longs scalp-only.",
    "ALIGNED_DOWN": "All timeframes aligned down — favor shorts/cash, avoid catching knives.",
    "UNKNOWN": "Insufficient data for multi-timeframe classification.",
}


def build_multi_tf(long_score: Optional[float], mid_score: Optional[float],
                   short_score: Optional[float], micro_score: Optional[float],
                   internals: Optional[Dict] = None,
                   divergence: Optional[List[str]] = None,
                   per_index: Optional[Dict] = None) -> Dict:
    """Assemble the full multi-timeframe analysis dict (pure).

    Lanes are already market-blended (SPY/QQQ/IWM) by the caller. Internals
    (TICK) refine the intraday read (confirm/contradict) and, on a climax,
    cap an aggressive mode so the bot doesn't chase an exhausted thrust.
    """
    raw_intraday = blend_intraday(mid_score, short_score, micro_score)
    intraday = apply_internals_adjustment(raw_intraday, internals)
    context = classify_context(long_score, intraday)
    align = tf_alignment([long_score, mid_score, short_score, micro_score])

    modes = {
        "long": mode_for_direction(context, "long", long_score),
        "short": mode_for_direction(context, "short", long_score),
    }
    # B2(c) climax: caution against chasing an exhausted thrust → cap aggressive.
    caution = None
    if internals and internals.get("climax"):
        cd = internals.get("climax_dir")
        if cd == "BUY_CLIMAX" and modes["long"] == "aggressive":
            modes["long"] = "normal"
            caution = "NYSE/NASD buy-climax — longs capped to normal (don't chase)"
        elif cd == "SELL_CLIMAX" and modes["short"] == "aggressive":
            modes["short"] = "normal"
            caution = "NYSE/NASD sell-climax — shorts capped to normal (don't chase)"
        elif cd:
            caution = f"{cd.replace('_', ' ').title()} — intraday exhaustion risk"

    reco = _CONTEXT_RECO.get(context, _CONTEXT_RECO["UNKNOWN"])
    if caution:
        reco = f"{reco}  ⚠ {caution}"

    return {
        "context": context,
        "intraday_score": intraday,
        "intraday_score_raw": raw_intraday,
        "intraday_bias": lane_bias(intraday),
        "tf_alignment": align,
        "lanes": {
            "long": {"timeframe": "1 day", "score": long_score, "bias": lane_bias(long_score)},
            "mid": {"timeframe": "1 hour", "score": mid_score, "bias": lane_bias(mid_score)},
            "short": {"timeframe": "5 mins", "score": short_score, "bias": lane_bias(short_score)},
            "micro": {"timeframe": "1 min", "score": micro_score, "bias": lane_bias(micro_score)},
        },
        "internals": internals,
        "divergence": divergence or [],
        "per_index": per_index or {},
        "modes": modes,
        "caution": caution,
        "recommendation": reco,
    }

