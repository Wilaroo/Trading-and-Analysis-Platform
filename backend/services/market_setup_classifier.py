"""
MarketSetupClassifier — Bellafiore-style daily SETUP classification.
=======================================================================

In Mike Bellafiore's playbook (One Good Trade / The Playbook) there are
two orthogonal layers in any trade idea:

    SETUP  = the daily / multi-day market context that "set up" the
             opportunity. e.g. the stock gapped up on earnings (Gap & Go),
             or it spent two weeks chopping then broke out (Range Break),
             or it's grinding parabolic +25% in 5 days (Overextension).

    TRADE  = the specific intraday execution pattern. e.g. a 9-EMA Scalp,
             a VWAP Continuation, a Bella Fade.

A given Trade only has positive expectancy in the right Setup. A 9-EMA
Scalp on a Gap & Go day is gold; a 9-EMA Scalp on an Overextension day
is operator suicide. This module classifies each symbol's *current
daily Setup* once per scan cycle so the scanner can gate alerts via
`TRADE_SETUP_MATRIX` (see below).

The classifier reads daily bars from `ib_historical_data` (no extra IB
calls), computes seven independent setup signals, and returns the
highest-confidence Setup (or NEUTRAL if none score above threshold).
Results cache per-symbol for 5 minutes to keep scanner-cycle latency low.

Public API:
    classifier = get_market_setup_classifier()
    setup = await classifier.classify(symbol)   # MarketSetup enum

Telemetry:
    classifier.stats()          # counts of each setup detected today
    classifier.cache_hit_rate   # 0.0-1.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ──────────────────────────── ENUMS ────────────────────────────

class MarketSetup(str, Enum):
    """Seven Bellafiore daily Setups + NEUTRAL fallback.

    The enum *values* are the canonical strings used everywhere
    downstream (LiveAlert.market_setup, MongoDB, the API).
    """
    GAP_AND_GO              = "gap_and_go"
    RANGE_BREAK             = "range_break"
    DAY_2                   = "day_2"
    GAP_DOWN_INTO_SUPPORT   = "gap_down_into_support"
    GAP_UP_INTO_RESISTANCE  = "gap_up_into_resistance"
    OVEREXTENSION           = "overextension"
    VOLATILITY_IN_RANGE     = "volatility_in_range"
    NEUTRAL                 = "neutral"  # no setup matched — Trade fires uncontested


class TradeContext(str, Enum):
    """Cell semantics in TRADE_SETUP_MATRIX."""
    WITH_TREND   = "with_trend"
    COUNTERTREND = "countertrend"
    NOT_APPLIC   = "not_applicable"   # empty cell — block (or warn) the alert


# ──────────────────────────── TRADE × SETUP MATRIX ────────────────────────────
# Source of truth, transcribed from the operator playbook screenshot
# (2026-04-29). Keys: trade `setup_type` (the historical column name we
# kept rather than mass-renaming). Values: dict mapping each MarketSetup
# to its TradeContext for that trade.
#
# Aliases (deprecated → canonical):
#   puppy_dog       → big_dog              (shorter consolidation, same trade family)
#   tidal_wave      → bouncy_ball          (same fail-bounce-then-break short)
#   vwap_bounce     → first_vwap_pullback  (operator merged these)
#
# The aliasing layer lives in the scanner itself (`_check_setup`); this
# matrix only carries canonical names.

TRADE_SETUP_MATRIX: Dict[str, Dict[MarketSetup, TradeContext]] = {
    # Trade                         Gap&Go  RangeBrk  Day2    GapDn    GapUp    Overext  VolRng
    "the_3_30_trade":              {MarketSetup.GAP_AND_GO: TradeContext.WITH_TREND},
    "second_chance":               {MarketSetup.GAP_AND_GO: TradeContext.WITH_TREND,
                                    MarketSetup.RANGE_BREAK: TradeContext.WITH_TREND},
    "hitchhiker":                  {MarketSetup.GAP_AND_GO: TradeContext.WITH_TREND,
                                    MarketSetup.RANGE_BREAK: TradeContext.WITH_TREND},
    "9_ema_scalp":                 {MarketSetup.GAP_AND_GO: TradeContext.WITH_TREND,
                                    MarketSetup.RANGE_BREAK: TradeContext.WITH_TREND},
    "vwap_continuation":           {MarketSetup.GAP_AND_GO: TradeContext.WITH_TREND,
                                    MarketSetup.RANGE_BREAK: TradeContext.WITH_TREND},
    "gap_give_go":                 {MarketSetup.GAP_AND_GO: TradeContext.WITH_TREND,
                                    MarketSetup.RANGE_BREAK: TradeContext.WITH_TREND},
    "first_vwap_pullback":         {MarketSetup.GAP_AND_GO: TradeContext.WITH_TREND,
                                    MarketSetup.RANGE_BREAK: TradeContext.WITH_TREND},
    "big_dog":                     {MarketSetup.GAP_AND_GO: TradeContext.WITH_TREND,
                                    MarketSetup.RANGE_BREAK: TradeContext.WITH_TREND},
    "bouncy_ball":                 {MarketSetup.GAP_AND_GO: TradeContext.WITH_TREND,
                                    MarketSetup.RANGE_BREAK: TradeContext.WITH_TREND,
                                    MarketSetup.OVEREXTENSION: TradeContext.COUNTERTREND},
    "premarket_high_break":        {MarketSetup.GAP_AND_GO: TradeContext.WITH_TREND,
                                    MarketSetup.RANGE_BREAK: TradeContext.WITH_TREND,
                                    MarketSetup.DAY_2: TradeContext.WITH_TREND},
    "back_through_open":           {MarketSetup.GAP_AND_GO: TradeContext.WITH_TREND,
                                    MarketSetup.RANGE_BREAK: TradeContext.WITH_TREND,
                                    MarketSetup.DAY_2: TradeContext.WITH_TREND,
                                    MarketSetup.GAP_DOWN_INTO_SUPPORT: TradeContext.COUNTERTREND,
                                    MarketSetup.GAP_UP_INTO_RESISTANCE: TradeContext.COUNTERTREND},
    "range_break":                 {MarketSetup.GAP_AND_GO: TradeContext.WITH_TREND,
                                    MarketSetup.RANGE_BREAK: TradeContext.WITH_TREND,
                                    MarketSetup.DAY_2: TradeContext.WITH_TREND,
                                    MarketSetup.GAP_DOWN_INTO_SUPPORT: TradeContext.COUNTERTREND,
                                    MarketSetup.GAP_UP_INTO_RESISTANCE: TradeContext.COUNTERTREND,
                                    MarketSetup.OVEREXTENSION: TradeContext.COUNTERTREND},
    "spencer_scalp":               {MarketSetup.RANGE_BREAK: TradeContext.WITH_TREND,
                                    MarketSetup.DAY_2: TradeContext.WITH_TREND},
    "first_move_up":               {MarketSetup.RANGE_BREAK: TradeContext.WITH_TREND,
                                    MarketSetup.DAY_2: TradeContext.WITH_TREND,
                                    MarketSetup.GAP_UP_INTO_RESISTANCE: TradeContext.COUNTERTREND,
                                    MarketSetup.OVEREXTENSION: TradeContext.COUNTERTREND,
                                    MarketSetup.VOLATILITY_IN_RANGE: TradeContext.COUNTERTREND},
    "first_move_down":             {MarketSetup.RANGE_BREAK: TradeContext.WITH_TREND,
                                    MarketSetup.DAY_2: TradeContext.WITH_TREND,
                                    MarketSetup.GAP_DOWN_INTO_SUPPORT: TradeContext.COUNTERTREND,
                                    MarketSetup.OVEREXTENSION: TradeContext.COUNTERTREND,
                                    MarketSetup.VOLATILITY_IN_RANGE: TradeContext.COUNTERTREND},
    "bella_fade":                  {MarketSetup.RANGE_BREAK: TradeContext.WITH_TREND,
                                    MarketSetup.DAY_2: TradeContext.WITH_TREND,
                                    MarketSetup.GAP_DOWN_INTO_SUPPORT: TradeContext.COUNTERTREND,
                                    MarketSetup.GAP_UP_INTO_RESISTANCE: TradeContext.COUNTERTREND,
                                    MarketSetup.OVEREXTENSION: TradeContext.COUNTERTREND,
                                    MarketSetup.VOLATILITY_IN_RANGE: TradeContext.COUNTERTREND},
    "fashionably_late":            {MarketSetup.DAY_2: TradeContext.WITH_TREND,
                                    MarketSetup.GAP_DOWN_INTO_SUPPORT: TradeContext.COUNTERTREND,
                                    MarketSetup.GAP_UP_INTO_RESISTANCE: TradeContext.COUNTERTREND,
                                    MarketSetup.OVEREXTENSION: TradeContext.COUNTERTREND,
                                    MarketSetup.VOLATILITY_IN_RANGE: TradeContext.COUNTERTREND},
    "backside":                    {MarketSetup.DAY_2: TradeContext.WITH_TREND,
                                    MarketSetup.GAP_DOWN_INTO_SUPPORT: TradeContext.COUNTERTREND,
                                    MarketSetup.GAP_UP_INTO_RESISTANCE: TradeContext.COUNTERTREND,
                                    MarketSetup.OVEREXTENSION: TradeContext.COUNTERTREND,
                                    MarketSetup.VOLATILITY_IN_RANGE: TradeContext.COUNTERTREND},
    "rubber_band":                 {MarketSetup.DAY_2: TradeContext.WITH_TREND,
                                    MarketSetup.GAP_DOWN_INTO_SUPPORT: TradeContext.COUNTERTREND,
                                    MarketSetup.GAP_UP_INTO_RESISTANCE: TradeContext.COUNTERTREND,
                                    MarketSetup.OVEREXTENSION: TradeContext.COUNTERTREND,
                                    MarketSetup.VOLATILITY_IN_RANGE: TradeContext.COUNTERTREND},
    "off_sides":                   {MarketSetup.GAP_DOWN_INTO_SUPPORT: TradeContext.COUNTERTREND,
                                    MarketSetup.GAP_UP_INTO_RESISTANCE: TradeContext.COUNTERTREND,
                                    MarketSetup.OVEREXTENSION: TradeContext.COUNTERTREND,
                                    MarketSetup.VOLATILITY_IN_RANGE: TradeContext.COUNTERTREND},
    "hod_breakout":                {MarketSetup.GAP_AND_GO: TradeContext.WITH_TREND,
                                    MarketSetup.RANGE_BREAK: TradeContext.WITH_TREND,
                                    MarketSetup.DAY_2: TradeContext.WITH_TREND},
}

# Trades NOT in the matrix — keep firing in all contexts but flag
# `experimental=True` so the operator can later decide to consolidate.
EXPERIMENTAL_TRADES: frozenset = frozenset({
    "vwap_fade", "abc_scalp", "breakout", "gap_fade", "chart_pattern",
    "squeeze", "mean_reversion", "relative_strength", "volume_capitulation",
    "approaching_hod",  # diagnostic-only precursor to hod_breakout
    "approaching_range_break", "range_break_confirmed",  # legacy emit-side names
})

# Deprecated trade names that should redirect to a canonical sibling.
# When the scanner sees these in `_enabled_setups`, it logs once and
# treats them as the canonical name.
TRADE_ALIASES: Dict[str, str] = {
    "puppy_dog":   "big_dog",
    "tidal_wave":  "bouncy_ball",
    "vwap_bounce": "first_vwap_pullback",  # also covers vwap_continuation context
}


def lookup_trade_context(trade: str, setup: MarketSetup) -> TradeContext:
    """Look up the validity of a Trade in the current Setup.

    Returns NOT_APPLIC if either the trade isn't in the matrix or the
    current setup isn't allowed for that trade. Caller decides whether
    to block the alert (strict mode) or just warn (soft mode).
    """
    canonical = TRADE_ALIASES.get(trade, trade)
    if canonical in EXPERIMENTAL_TRADES:
        # Experimental trades have no matrix opinion — treat all setups as
        # acceptable but the alert will be tagged `experimental=True`.
        return TradeContext.WITH_TREND
    if setup == MarketSetup.NEUTRAL:
        # Classifier couldn't pin the setup — pass through without context tag.
        return TradeContext.WITH_TREND
    cell = TRADE_SETUP_MATRIX.get(canonical, {}).get(setup)
    return cell or TradeContext.NOT_APPLIC


# ──────────────────────────── CLASSIFIER ────────────────────────────

@dataclass
class ClassificationResult:
    setup: MarketSetup
    confidence: float                        # 0-1 (max across all detectors)
    runner_ups: List[Tuple[MarketSetup, float]] = field(default_factory=list)
    classified_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reasoning: List[str] = field(default_factory=list)


class MarketSetupClassifier:
    """Classifies a symbol's current daily Setup from ~30 daily bars.

    Each `_detect_*` method returns a 0-1 confidence score. The highest
    scorer wins, provided it clears `min_confidence` (default 0.5).
    """

    CACHE_TTL_SECONDS = 300        # 5 min cache per symbol
    MIN_CONFIDENCE    = 0.5
    DAILY_HISTORY_DAYS = 30

    def __init__(self, db=None):
        self.db = db
        self._cache: Dict[str, Tuple[ClassificationResult, datetime]] = {}
        self._daily_count: Dict[MarketSetup, int] = {}  # today's classification tally
        self._cache_hits = 0
        self._cache_misses = 0

    # ───────── Public API ─────────

    async def classify(self, symbol: str, daily_bars: Optional[List[Dict]] = None,
                       intraday_snapshot=None) -> ClassificationResult:
        """Classify the symbol's current daily Setup. Caches for 5 min.

        ``daily_bars`` is an optional pre-loaded list of dicts, each
        with at least: ``date``, ``open``, ``high``, ``low``, ``close``,
        ``volume`` (most-recent-last). If not provided, the classifier
        loads from MongoDB via ``self.db``.

        ``intraday_snapshot`` (TechnicalSnapshot) is optional but lets
        the classifier sharpen Gap & Go vs Day 2 calls when intraday
        gap data is fresher than the latest daily bar.
        """
        cached = self._cache.get(symbol)
        if cached and (datetime.now(timezone.utc) - cached[1]).total_seconds() < self.CACHE_TTL_SECONDS:
            self._cache_hits += 1
            return cached[0]
        self._cache_misses += 1

        bars = daily_bars or await self._load_daily_bars(symbol)
        if not bars or len(bars) < 5:
            return self._make_result(MarketSetup.NEUTRAL, 0.0, ["Insufficient daily bars"])

        # Run all 7 detectors. Each returns (confidence, reasoning).
        scores: List[Tuple[MarketSetup, float, List[str]]] = [
            (MarketSetup.GAP_AND_GO,             *self._detect_gap_and_go(bars, intraday_snapshot)),
            (MarketSetup.RANGE_BREAK,            *self._detect_range_break(bars)),
            (MarketSetup.DAY_2,                  *self._detect_day_2(bars, intraday_snapshot)),
            (MarketSetup.GAP_DOWN_INTO_SUPPORT,  *self._detect_gap_down_into_support(bars, intraday_snapshot)),
            (MarketSetup.GAP_UP_INTO_RESISTANCE, *self._detect_gap_up_into_resistance(bars, intraday_snapshot)),
            (MarketSetup.OVEREXTENSION,          *self._detect_overextension(bars)),
            (MarketSetup.VOLATILITY_IN_RANGE,    *self._detect_volatility_in_range(bars)),
        ]
        scores.sort(key=lambda s: s[1], reverse=True)
        best_setup, best_conf, best_reason = scores[0]

        if best_conf < self.MIN_CONFIDENCE:
            result = self._make_result(MarketSetup.NEUTRAL, best_conf,
                                       [f"Top candidate {best_setup.value} below {self.MIN_CONFIDENCE}: {best_conf:.2f}"])
        else:
            runner_ups = [(s, c) for s, c, _ in scores[1:4] if c >= 0.3]
            result = self._make_result(best_setup, best_conf, best_reason, runner_ups)

        self._cache[symbol] = (result, datetime.now(timezone.utc))
        self._daily_count[result.setup] = self._daily_count.get(result.setup, 0) + 1
        return result

    def stats(self) -> Dict:
        total = self._cache_hits + self._cache_misses
        return {
            "classified_today": dict({s.value: n for s, n in self._daily_count.items()}),
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_hit_rate": (self._cache_hits / total) if total else 0.0,
            "cache_size": len(self._cache),
        }

    def invalidate(self, symbol: Optional[str] = None) -> None:
        if symbol is None:
            self._cache.clear()
        else:
            self._cache.pop(symbol, None)

    # ───────── Detection methods (each returns (confidence_0_to_1, [reasons])) ─────────

    def _detect_gap_and_go(self, bars: List[Dict], snap=None) -> Tuple[float, List[str]]:
        """Big gap candle + recent consolidation breakout + heavy volume."""
        if len(bars) < 5:
            return 0.0, []
        latest = bars[-1]
        prev_close = bars[-2]["close"] if len(bars) >= 2 else latest["open"]
        if prev_close <= 0:
            return 0.0, []
        gap_pct = ((latest["open"] - prev_close) / prev_close) * 100
        # Use intraday snapshot to override stale gap_pct if available
        if snap is not None and getattr(snap, "gap_pct", None) is not None:
            gap_pct = snap.gap_pct
        if abs(gap_pct) < 1.5:
            return 0.0, []
        # Heavy volume on the gap day
        recent_volumes = [b["volume"] for b in bars[-20:-1] if b.get("volume", 0) > 0]
        avg_vol = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0
        vol_ratio = (latest["volume"] / avg_vol) if avg_vol > 0 else 1.0
        # Prior 10-day consolidation tightness (high - low) / mean_close
        recent10 = bars[-11:-1]
        if not recent10:
            return 0.0, []
        rng = max(b["high"] for b in recent10) - min(b["low"] for b in recent10)
        mean_close = sum(b["close"] for b in recent10) / len(recent10)
        consolidation_pct = (rng / mean_close) * 100 if mean_close > 0 else 100
        # Confidence: weight gap size + volume + tightness
        gap_score = min(abs(gap_pct) / 4.0, 1.0)        # 4%+ gap = full credit
        vol_score = min(vol_ratio / 2.0, 1.0)            # 2× avg vol = full credit
        tight_score = max(0.0, 1.0 - (consolidation_pct / 15.0))  # tighter range scores higher
        confidence = (gap_score * 0.5) + (vol_score * 0.3) + (tight_score * 0.2)
        reasons = [
            f"Gap {gap_pct:+.1f}% off prior close",
            f"Volume {vol_ratio:.1f}× 19-day avg",
            f"Prior consolidation range {consolidation_pct:.1f}%",
        ]
        return confidence, reasons

    def _detect_range_break(self, bars: List[Dict]) -> Tuple[float, List[str]]:
        """Multi-day consolidation followed by decisive break with elevated volume.

        To disambiguate from Day 2 (continuation off a prior break-day),
        we require that bars[-2] (the prior day) was STILL inside the
        consolidation range — i.e. today is the actual break, not the
        day after.
        """
        if len(bars) < 12:
            return 0.0, []
        latest = bars[-1]
        prior = bars[-2]
        # Look at bars[-12:-2] as the consolidation period (excluding the latest 2)
        cons = bars[-12:-2]
        if not cons:
            return 0.0, []
        cons_high = max(b["high"] for b in cons)
        cons_low  = min(b["low"]  for b in cons)
        cons_mid  = (cons_high + cons_low) / 2
        cons_range_pct = ((cons_high - cons_low) / cons_mid) * 100 if cons_mid > 0 else 100
        # Tight consolidation: < 12% range over 10 bars
        if cons_range_pct > 12:
            return 0.0, []
        # Disambiguate: prior day must still be inside the consolidation.
        # If the prior day already broke out, this is Day 2, not Range Break.
        if prior["close"] > cons_high * 1.005 or prior["close"] < cons_low * 0.995:
            return 0.0, []
        # Latest must have closed outside the range
        if latest["close"] > cons_high * 1.005:
            direction = "above"
            break_pct = ((latest["close"] - cons_high) / cons_high) * 100
        elif latest["close"] < cons_low * 0.995:
            direction = "below"
            break_pct = ((cons_low - latest["close"]) / cons_low) * 100
        else:
            return 0.0, []
        # Volume confirmation
        recent_vol = [b["volume"] for b in cons if b.get("volume", 0) > 0]
        avg_vol = sum(recent_vol) / len(recent_vol) if recent_vol else 0
        vol_ratio = (latest["volume"] / avg_vol) if avg_vol > 0 else 1.0
        tight_score = max(0.0, 1.0 - (cons_range_pct / 12.0))
        break_score = min(break_pct / 3.0, 1.0)
        vol_score = min(vol_ratio / 1.5, 1.0)
        confidence = (tight_score * 0.4) + (break_score * 0.4) + (vol_score * 0.2)
        return confidence, [
            f"10-day consolidation {cons_range_pct:.1f}% range",
            f"Decisive {direction}-break {break_pct:.1f}%",
            f"Volume {vol_ratio:.1f}× consolidation avg",
        ]

    def _detect_day_2(self, bars: List[Dict], snap=None) -> Tuple[float, List[str]]:
        """Day 1 was >1 ATR move closing top-20% of range → Day 2 continuation."""
        if len(bars) < 16:
            return 0.0, []
        # Day 1 = the *previous* daily bar (bars[-2]). "Today" = bars[-1].
        day1 = bars[-2]
        d1_range = day1["high"] - day1["low"]
        if d1_range <= 0:
            return 0.0, []
        # ATR(14) over the 14 bars ending at day1
        atrs = []
        for i in range(-15, -1):
            b = bars[i]
            tr = b["high"] - b["low"]
            atrs.append(tr)
        atr = sum(atrs) / len(atrs) if atrs else 0
        if atr <= 0:
            return 0.0, []
        range_to_atr = d1_range / atr
        # Close in top 20% of day's range
        close_pct_in_range = (day1["close"] - day1["low"]) / d1_range
        if range_to_atr < 1.0 or close_pct_in_range < 0.8:
            return 0.0, []
        # Today should still be opening near the day-1 close (no overnight gap-fill reversal)
        today_open = bars[-1]["open"]
        if snap is not None and getattr(snap, "open", None):
            today_open = snap.open
        gap_back = abs((today_open - day1["close"]) / day1["close"]) * 100
        gap_back_score = max(0.0, 1.0 - gap_back / 3.0)  # within 3% counts
        atr_score = min(range_to_atr / 1.8, 1.0)
        close_score = (close_pct_in_range - 0.8) / 0.2   # 0.8→0, 1.0→1
        confidence = (atr_score * 0.5) + (close_score * 0.3) + (gap_back_score * 0.2)
        return confidence, [
            f"Day 1 range {range_to_atr:.2f}× ATR(14)",
            f"Day 1 closed {close_pct_in_range*100:.0f}% up the day's range",
            f"Day 2 open within {gap_back:.1f}% of Day 1 close",
        ]

    def _detect_gap_down_into_support(self, bars: List[Dict], snap=None) -> Tuple[float, List[str]]:
        """Negative-catalyst gap-down landing within 1×ATR of a multi-day support level."""
        if len(bars) < 20:
            return 0.0, []
        latest = bars[-1]
        prev_close = bars[-2]["close"] if len(bars) >= 2 else latest["open"]
        if prev_close <= 0:
            return 0.0, []
        gap_pct = ((latest["open"] - prev_close) / prev_close) * 100
        if snap is not None and getattr(snap, "gap_pct", None) is not None:
            gap_pct = snap.gap_pct
        if gap_pct > -1.0:
            return 0.0, []
        # Find recent prior swing low + 50-bar low as support candidates
        recent20 = bars[-21:-1]
        prior_low = min(b["low"] for b in recent20)
        # ATR(14)
        atrs = [bars[i]["high"] - bars[i]["low"] for i in range(-15, -1)]
        atr = sum(atrs) / len(atrs) if atrs else 0
        if atr <= 0:
            return 0.0, []
        # Distance from gap-down low to the support level
        gap_low = latest["low"]
        dist_to_support = abs(gap_low - prior_low) / atr  # in ATR units
        if dist_to_support > 1.0:
            return 0.0, []
        gap_score = min(abs(gap_pct) / 3.0, 1.0)
        proximity_score = max(0.0, 1.0 - dist_to_support)
        confidence = (gap_score * 0.5) + (proximity_score * 0.5)
        return confidence, [
            f"Gap down {gap_pct:.1f}% on negative catalyst",
            f"Gap low ${gap_low:.2f} within {dist_to_support:.2f}× ATR of 20-day low ${prior_low:.2f}",
        ]

    def _detect_gap_up_into_resistance(self, bars: List[Dict], snap=None) -> Tuple[float, List[str]]:
        """Positive-catalyst gap-up landing within 1×ATR of a multi-day resistance."""
        if len(bars) < 20:
            return 0.0, []
        latest = bars[-1]
        prev_close = bars[-2]["close"] if len(bars) >= 2 else latest["open"]
        if prev_close <= 0:
            return 0.0, []
        gap_pct = ((latest["open"] - prev_close) / prev_close) * 100
        if snap is not None and getattr(snap, "gap_pct", None) is not None:
            gap_pct = snap.gap_pct
        if gap_pct < 1.0:
            return 0.0, []
        recent20 = bars[-21:-1]
        prior_high = max(b["high"] for b in recent20)
        atrs = [bars[i]["high"] - bars[i]["low"] for i in range(-15, -1)]
        atr = sum(atrs) / len(atrs) if atrs else 0
        if atr <= 0:
            return 0.0, []
        gap_high = latest["high"]
        dist_to_res = abs(prior_high - gap_high) / atr
        if dist_to_res > 1.0:
            return 0.0, []
        gap_score = min(gap_pct / 3.0, 1.0)
        proximity_score = max(0.0, 1.0 - dist_to_res)
        confidence = (gap_score * 0.5) + (proximity_score * 0.5)
        return confidence, [
            f"Gap up {gap_pct:.1f}% on positive catalyst",
            f"Gap high ${gap_high:.2f} within {dist_to_res:.2f}× ATR of 20-day high ${prior_high:.2f}",
        ]

    def _detect_overextension(self, bars: List[Dict]) -> Tuple[float, List[str]]:
        """Parabolic move: 5+ same-direction candles, RSI≥80 or ≤20, >2× ATR from EMA20."""
        if len(bars) < 21:
            return 0.0, []
        # Consecutive same-direction candles
        same_dir = 1
        prev_dir = 1 if bars[-1]["close"] >= bars[-1]["open"] else -1
        for i in range(-2, -7, -1):
            d = 1 if bars[i]["close"] >= bars[i]["open"] else -1
            if d == prev_dir:
                same_dir += 1
            else:
                break
        if same_dir < 4:
            return 0.0, []
        # 20-EMA proxy: simple mean of last 20 closes
        ema20 = sum(b["close"] for b in bars[-21:-1]) / 20
        latest_close = bars[-1]["close"]
        # ATR(14)
        atrs = [bars[i]["high"] - bars[i]["low"] for i in range(-15, -1)]
        atr = sum(atrs) / len(atrs) if atrs else 0
        if atr <= 0 or ema20 <= 0:
            return 0.0, []
        ext_atr = abs(latest_close - ema20) / atr
        if ext_atr < 1.5:
            return 0.0, []
        # Wilder RSI(14) approximation
        gains = []
        losses = []
        for i in range(-15, 0):
            change = bars[i]["close"] - bars[i - 1]["close"]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))
        avg_gain = sum(gains) / len(gains) if gains else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        rsi = 100 - (100 / (1 + (avg_gain / avg_loss))) if avg_loss > 0 else 100
        rsi_extreme = max(rsi - 70, 30 - rsi, 0) / 30
        consec_score = min((same_dir - 3) / 5, 1.0)
        ext_score = min((ext_atr - 1.5) / 2.0, 1.0)
        confidence = (consec_score * 0.3) + (ext_score * 0.4) + (rsi_extreme * 0.3)
        return confidence, [
            f"{same_dir} consecutive {'green' if prev_dir > 0 else 'red'} candles",
            f"Extended {ext_atr:.2f}× ATR from 20-EMA",
            f"RSI(14) ≈ {rsi:.0f}",
        ]

    def _detect_volatility_in_range(self, bars: List[Dict]) -> Tuple[float, List[str]]:
        """Wide chop: high daily ATR but oscillating in a defined range, no decisive break."""
        if len(bars) < 15:
            return 0.0, []
        recent = bars[-15:]
        rng_high = max(b["high"] for b in recent)
        rng_low  = min(b["low"]  for b in recent)
        rng_mid  = (rng_high + rng_low) / 2
        rng_pct  = ((rng_high - rng_low) / rng_mid) * 100 if rng_mid > 0 else 0
        # ATR(14)
        atrs = [bars[i]["high"] - bars[i]["low"] for i in range(-15, -1)]
        atr = sum(atrs) / len(atrs) if atrs else 0
        if rng_mid <= 0 or atr <= 0:
            return 0.0, []
        atr_pct = (atr / rng_mid) * 100
        # Need elevated ATR (>2%) AND price still inside range (not breaking out)
        if atr_pct < 1.5:
            return 0.0, []
        latest_close = bars[-1]["close"]
        within_range = rng_low * 0.99 <= latest_close <= rng_high * 1.01
        if not within_range:
            return 0.0, []
        # Touches: count how many bars touched the upper or lower 20% of the range
        upper_touches = sum(1 for b in recent if b["high"] >= rng_low + 0.8 * (rng_high - rng_low))
        lower_touches = sum(1 for b in recent if b["low"]  <= rng_low + 0.2 * (rng_high - rng_low))
        oscillation_score = min((min(upper_touches, lower_touches) / 3), 1.0)
        atr_score = min((atr_pct - 1.5) / 2.0, 1.0)
        range_score = min(rng_pct / 15.0, 1.0)
        confidence = (oscillation_score * 0.5) + (atr_score * 0.3) + (range_score * 0.2)
        return confidence, [
            f"15-day range {rng_pct:.1f}% (${rng_low:.2f}-${rng_high:.2f})",
            f"Daily ATR {atr_pct:.1f}% (elevated)",
            f"{upper_touches} upper-band touches, {lower_touches} lower-band",
        ]

    # ───────── Helpers ─────────

    async def _load_daily_bars(self, symbol: str) -> List[Dict]:
        """Load up to N daily bars from MongoDB for the given symbol."""
        if self.db is None:
            return []
        try:
            cursor = self.db["ib_historical_data"].find(
                {"symbol": symbol.upper(), "bar_size": "1 day"},
                {"_id": 0, "symbol": 1, "date": 1, "open": 1, "high": 1,
                 "low": 1, "close": 1, "volume": 1},
            ).sort("date", -1).limit(self.DAILY_HISTORY_DAYS + 5)
            bars = await cursor.to_list(length=self.DAILY_HISTORY_DAYS + 5)
            bars.reverse()  # oldest-first
            return bars
        except Exception as e:
            logger.warning(f"_load_daily_bars({symbol}) failed: {e}")
            return []

    @staticmethod
    def _make_result(setup: MarketSetup, conf: float, reasons: List[str],
                     runner_ups: Optional[List[Tuple[MarketSetup, float]]] = None) -> ClassificationResult:
        return ClassificationResult(
            setup=setup,
            confidence=round(conf, 3),
            runner_ups=runner_ups or [],
            reasoning=reasons,
        )


# ──────────────────────────── Module-level singleton ────────────────────────────

_classifier_instance: Optional[MarketSetupClassifier] = None


def get_market_setup_classifier(db=None) -> MarketSetupClassifier:
    """Singleton accessor — pass `db` once on first call."""
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = MarketSetupClassifier(db=db)
    elif db is not None and _classifier_instance.db is None:
        _classifier_instance.db = db
    return _classifier_instance
