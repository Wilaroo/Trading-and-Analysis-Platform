"""
Context Quality Service - 20% of TQS Score

Evaluates market context and timing:
- Market regime (trending vs choppy)
- Time of day optimization
- Sector strength/rotation
- VIX/Volatility regime
- Day of week patterns
"""

import logging
import math
import time
from typing import Optional, Dict, List
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from data.index_symbols import benchmark_for

logger = logging.getLogger(__name__)

# v19.34.254 — per-symbol Relative-Strength → 0-100 mapping. Calibrated from the
# v253 live diag: rs_1d (stock-minus-benchmark daily %) has stdev ~5.5% with a
# fat right tail to +44%. A linear ±3% map saturated hard (p10=0/p90=100, all
# info lost), so we use a smooth tanh squash that only saturates at true
# extremes. blended = 0.6*rs_1d + 0.4*rs_5d (percent points).
#   ±3% → ~63/37 · ±6% → ~75/25 · ±9% → ~87/13 · +44% → ~99
RS_SCALE = 9.0      # divisor inside tanh (lower = more sensitive)
RS_AMPLITUDE = 48.0  # max deviation from the 50 midpoint


def _rs_to_score(blended_pct: float) -> float:
    return max(1.0, min(99.0, 50.0 + RS_AMPLITUDE * math.tanh(blended_pct / RS_SCALE)))


@dataclass
class ContextQualityScore:
    """Result of context quality evaluation"""
    score: float = 50.0  # 0-100
    grade: str = "C"
    
    # Component scores (0-100 each)
    regime_score: float = 50.0
    time_score: float = 50.0
    sector_score: float = 50.0
    vix_score: float = 50.0
    day_score: float = 50.0
    rs_score: float = 50.0  # v19.34.254 — per-symbol relative strength
    ai_score: float = 50.0  # v391 — AI-model alignment (was factor-only)

    # Raw values
    market_regime: str = "unknown"
    time_of_day: str = "midday"
    sector: str = "unknown"
    sector_rank: int = 6
    is_sector_leader: bool = False
    vix_level: float = 18.0
    day_of_week: int = 2  # Wednesday
    spy_change_pct: float = 0.0
    # v19.34.254 — relative strength raw values
    rs_benchmark: str = ""       # QQQ | SPY | IWM
    rs_1d: float = 0.0           # stock-minus-benchmark 1-day %
    rs_5d: float = 0.0           # stock-minus-benchmark 5-day %
    
    # Reasoning
    factors: list = None
    display_ctx: dict = None  # v391 — extra raw bits for sub-score descriptors
    
    def __post_init__(self):
        if self.factors is None:
            self.factors = []
        if self.display_ctx is None:
            self.display_ctx = {}

    def _display(self, is_long: bool = True) -> Dict:
        from services.tqs.descriptors import disp, humanize, weekday_name, vix_descriptor
        c = self.display_ctx
        side = "longs" if is_long else "shorts"
        reg = humanize(self.market_regime)
        bias = {
            "strong_uptrend": "favors longs" if is_long else "against shorts",
            "weak_uptrend": "mild tailwind for longs" if is_long else "headwind for shorts",
            "range_bound": f"neutral for {side}",
            "weak_downtrend": "headwind for longs" if is_long else "mild tailwind for shorts",
            "strong_downtrend": "against longs" if is_long else "favors shorts",
        }.get(self.market_regime, f"neutral for {side}")
        reg_read = f"{reg} · {bias}"
        if self.rs_benchmark:
            rs_read = f"{self.rs_1d:+.1f}% 1d / {self.rs_5d:+.1f}% 5d vs {self.rs_benchmark}"
        else:
            rs_read = "No relative-strength data"
        time_read = humanize(self.time_of_day)
        if c.get("sector_absent") or self.sector in (None, "", "unknown"):
            sector_read = "Sector data unavailable"
            sector_absent = True
        else:
            lead = " · leader" if self.is_sector_leader else ""
            sector_read = f"{humanize(self.sector)} · rank {self.sector_rank}/11{lead}"
            sector_absent = False
        vix_read = f"VIX {self.vix_level:.1f} · {vix_descriptor(self.vix_level)}"
        day_read = weekday_name(self.day_of_week)
        if c.get("ai_has_signal"):
            ad = c.get("ai_direction") or "—"
            ac = c.get("ai_confidence")
            conf = f" ({ac*100:.0f}% conf)" if ac is not None else ""
            if c.get("ai_agrees"):
                ai_read = f"Model confirms {ad}{conf}"
            else:
                ai_read = f"Model predicts {ad} · against trade{conf}"
        else:
            ai_read = "No model signal"
        return {
            "regime": disp("Market Regime", self.regime_score, reg_read),
            "relative_strength": disp("Relative Strength", self.rs_score, rs_read,
                                      absent=not self.rs_benchmark),
            "time": disp("Time of Day", self.time_score, time_read),
            "sector": disp("Sector", self.sector_score, sector_read, absent=sector_absent),
            "vix": disp("VIX", self.vix_score, vix_read),
            "day": disp("Day of Week", self.day_score, day_read),
            "ai_model": disp("AI Model", self.ai_score, ai_read,
                             absent=not c.get("ai_has_signal")),
        }
    
    def to_dict(self) -> Dict:
        return {
            "score": round(self.score, 1),
            "grade": self.grade,
            "components": {
                "regime": round(self.regime_score, 1),
                "relative_strength": round(self.rs_score, 1),
                "time": round(self.time_score, 1),
                "sector": round(self.sector_score, 1),
                "vix": round(self.vix_score, 1),
                "day": round(self.day_score, 1),
                "ai_model": round(self.ai_score, 1)
            },
            "display": self._display(self.display_ctx.get("is_long", True)),
            "raw_values": {
                "market_regime": self.market_regime,
                "time_of_day": self.time_of_day,
                "sector": self.sector,
                "sector_rank": self.sector_rank,
                "is_sector_leader": self.is_sector_leader,
                "vix_level": round(self.vix_level, 1),
                "day_of_week": self.day_of_week,
                "spy_change_pct": round(self.spy_change_pct, 2),
                "rs_benchmark": self.rs_benchmark,
                "rs_1d": round(self.rs_1d, 2),
                "rs_5d": round(self.rs_5d, 2)
            },
            "factors": self.factors
        }


class ContextQualityService:
    """Evaluates context quality - 20% of TQS"""
    
    # Setup performance by time of day (based on SMB research)
    TIME_SCORES = {
        "opening_auction": {"momentum": 85, "reversal": 40, "default": 60},
        "opening_drive": {"momentum": 95, "reversal": 45, "default": 75},
        "morning_momentum": {"momentum": 90, "reversal": 60, "default": 80},
        "late_morning": {"momentum": 70, "reversal": 75, "default": 70},
        "midday": {"momentum": 40, "reversal": 60, "default": 45},
        "afternoon": {"momentum": 65, "reversal": 70, "default": 65},
        "close": {"momentum": 55, "reversal": 50, "default": 55},
        "pre_market": {"momentum": 50, "reversal": 35, "default": 40},
        "after_hours": {"momentum": 30, "reversal": 25, "default": 25}
    }
    
    # Setup performance by regime
    REGIME_SCORES = {
        "strong_uptrend": {"long": 90, "short": 25},
        "weak_uptrend": {"long": 75, "short": 45},
        "range_bound": {"long": 55, "short": 55},
        "weak_downtrend": {"long": 45, "short": 75},
        "strong_downtrend": {"long": 25, "short": 90},
        "volatile": {"long": 50, "short": 50},
        "unknown": {"long": 50, "short": 50}
    }
    
    def __init__(self):
        self._alpaca_service = None
        self._sector_service = None
        self._ib_service = None
        self._db = None
        # short-lived cache of benchmark daily closes (SPY/QQQ/IWM) so a full
        # scan doesn't re-read the same index bars for every symbol.
        self._bench_cache = {}  # bench -> (ts, [closes newest-first])
        self._bench_ttl = 300

    def set_services(self, alpaca_service=None, sector_service=None, ib_service=None, db=None):
        """Wire up dependencies"""
        self._alpaca_service = alpaca_service
        self._sector_service = sector_service
        self._ib_service = ib_service
        if db is not None:
            self._db = db

    # ── daily-bar helpers (v19.34.254) ──────────────────────────────────────
    # On the ib-direct DGX the live alpaca quote path is effectively dead, so
    # regime/RS sourced from live quotes froze the pillar at ~62. These read
    # `ib_historical_data` daily bars (which ARE populated) instead.
    def _recent_closes(self, symbol: str, n: int = 8) -> List[float]:
        if self._db is None or not symbol:
            return []
        try:
            rows = list(self._db["ib_historical_data"].find(
                {"symbol": symbol.upper(), "bar_size": "1 day"},
                {"_id": 0, "date": 1, "close": 1},
            ).sort("date", -1).limit(n))
            return [r["close"] for r in rows if r.get("close")]
        except Exception as e:
            logger.debug(f"[context] daily-bar read failed {symbol}: {e}")
            return []

    def _benchmark_closes(self, bench: str) -> List[float]:
        now = time.time()
        c = self._bench_cache.get(bench)
        if c and now - c[0] < self._bench_ttl:
            return c[1]
        closes = self._recent_closes(bench, 8)
        self._bench_cache[bench] = (now, closes)
        return closes

    @staticmethod
    def _ret(closes: List[float], lookback: int) -> Optional[float]:
        if len(closes) <= lookback or not closes[lookback]:
            return None
        return (closes[0] - closes[lookback]) / closes[lookback] * 100.0

    def _compute_relative_strength(self, symbol: str, is_long: bool):
        """Per-symbol RS vs the index it belongs to (QQQ/SPY/IWM).
        Returns (rs_score, benchmark, rs_1d, rs_5d) or None if no bars."""
        bench = benchmark_for(symbol)
        sc = self._recent_closes(symbol, 8)
        bc = self._benchmark_closes(bench)
        if len(sc) < 2 or len(bc) < 2:
            return None
        rs_1d = (self._ret(sc, 1) or 0.0) - (self._ret(bc, 1) or 0.0)
        if len(sc) > 5 and len(bc) > 5:
            rs_5d = (self._ret(sc, 5) or 0.0) - (self._ret(bc, 5) or 0.0)
        else:
            rs_5d = rs_1d
        blended = 0.6 * rs_1d + 0.4 * rs_5d
        # For a short, outperformance is a HEADWIND — invert so the RS score
        # rewards the side the trade is actually taking.
        directional = blended if is_long else -blended
        return _rs_to_score(directional), bench, rs_1d, rs_5d

    def _multi_index_regime_change(self) -> Optional[float]:
        """v19.34.254 — composite SPY/QQQ/IWM 1-day % change (0.5/0.3/0.2 blend)
        from daily bars, used to classify regime when no live SPY quote is
        available (the common case on the ib-direct DGX). Mirrors the
        market_regime_engine TrendSignalBlock blend weights."""
        blend = [("SPY", 0.5), ("QQQ", 0.3), ("IWM", 0.2)]
        total, wsum = 0.0, 0.0
        for idx, w in blend:
            r = self._ret(self._benchmark_closes(idx), 1)
            if r is not None:
                total += r * w
                wsum += w
        return (total / wsum) if wsum > 0 else None

    async def calculate_score(
        self,
        symbol: str,
        direction: str = "long",
        setup_type: str = "",
        # Pre-fetched context (optional)
        market_regime: Optional[str] = None,
        spy_change_pct: Optional[float] = None,
        vix_level: Optional[float] = None,
        sector: Optional[str] = None,
        sector_rank: Optional[int] = None,
        is_sector_leader: Optional[bool] = None,
        time_of_day: Optional[str] = None,
        # AI model signals (from Confidence Gate pipeline)
        ai_model_direction: Optional[str] = None,  # "up", "down", "flat"
        ai_model_confidence: Optional[float] = None,  # 0.0-1.0
        ai_model_agrees: Optional[bool] = None,  # Does AI agree with trade direction?
    ) -> ContextQualityScore:
        """
        Calculate context quality score (0-100).
        
        Components:
        - Market regime fit (25%): Setup matches market conditions
        - Time of day (20%): Optimal trading window
        - Sector context (20%): Sector strength alignment
        - VIX regime (15%): Volatility environment
        - AI model alignment (10%): ML models agree with direction
        - Day of week (10%): Historical patterns
        """
        result = ContextQualityScore()
        is_long = direction.lower() == "long"
        
        # Determine setup category
        setup_lower = setup_type.lower()
        if any(s in setup_lower for s in ["breakout", "momentum", "drive", "orb", "flag"]):
            setup_category = "momentum"
        elif any(s in setup_lower for s in ["reversal", "bounce", "fade", "rubber"]):
            setup_category = "reversal"
        else:
            setup_category = "default"
            
        # Get current time info
        now = datetime.now(ZoneInfo("America/New_York"))  # ET
        result.day_of_week = now.weekday()
        
        # Determine time of day if not provided
        if time_of_day is None:
            hour = now.hour
            minute = now.minute
            time_minutes = hour * 60 + minute
            
            if time_minutes < 9 * 60 + 30:
                time_of_day = "pre_market"
            elif time_minutes < 9 * 60 + 35:
                time_of_day = "opening_auction"
            elif time_minutes < 10 * 60:
                time_of_day = "opening_drive"
            elif time_minutes < 11 * 60:
                time_of_day = "morning_momentum"
            elif time_minutes < 12 * 60:
                time_of_day = "late_morning"
            elif time_minutes < 14 * 60:
                time_of_day = "midday"
            elif time_minutes < 15 * 60 + 30:
                time_of_day = "afternoon"
            elif time_minutes < 16 * 60:
                time_of_day = "close"
            else:
                time_of_day = "after_hours"
                
        result.time_of_day = time_of_day
        
        # Fetch market data if not provided
        if self._alpaca_service and (spy_change_pct is None or market_regime is None):
            try:
                quotes = await self._alpaca_service.get_quotes_batch(["SPY"])
                if "SPY" in quotes:
                    spy_change_pct = quotes["SPY"].get("change_percent", 0)
            except Exception as e:
                logger.debug(f"Could not fetch SPY data: {e}")
                
        # Get VIX from IB pushed data or service
        if vix_level is None:
            try:
                # Try pushed data first (most reliable)
                from routers.ib import get_vix_from_pushed_data
                vix_data = get_vix_from_pushed_data()
                if vix_data and vix_data.get("price"):
                    vix_level = vix_data.get("price")
            except Exception:
                pass
            
            # Fallback to IB service
            if vix_level is None and self._ib_service:
                try:
                    vix_data = self._ib_service.get_vix()
                    if vix_data:
                        vix_level = vix_data.get("price", 18)
                except Exception:
                    pass
                
        # Fetch sector data if not provided
        if self._sector_service and (sector is None or sector_rank is None):
            try:
                sector_context = await self._sector_service.get_stock_sector_context(symbol)
                if sector_context:
                    sector = sector_context.get("sector", "unknown")
                    sector_rank = sector_context.get("sector_rank", 6)
                    is_sector_leader = sector_context.get("is_sector_leader", False)
            except Exception as e:
                logger.debug(f"Could not fetch sector data: {e}")
                
        # Use defaults
        # v19.34.254 — when no live SPY quote is available (the common case on
        # the ib-direct DGX, which froze regime at range_bound→55), fall back to
        # the multi-index SPY/QQQ/IWM composite computed from daily bars.
        if spy_change_pct is None:
            spy_change_pct = self._multi_index_regime_change()
        spy_change_pct = spy_change_pct if spy_change_pct is not None else 0.0
        vix_level = vix_level if vix_level is not None else 18.0
        sector = sector if sector else "unknown"
        sector_rank = sector_rank if sector_rank is not None else 6
        is_sector_leader = is_sector_leader if is_sector_leader is not None else False
        
        # Classify market regime from SPY change
        if market_regime is None:
            if spy_change_pct >= 1.0:
                market_regime = "strong_uptrend"
            elif spy_change_pct >= 0.3:
                market_regime = "weak_uptrend"
            elif spy_change_pct <= -1.0:
                market_regime = "strong_downtrend"
            elif spy_change_pct <= -0.3:
                market_regime = "weak_downtrend"
            else:
                market_regime = "range_bound"
                
        result.market_regime = market_regime
        result.spy_change_pct = spy_change_pct
        result.vix_level = vix_level
        result.sector = sector
        result.sector_rank = sector_rank
        result.is_sector_leader = is_sector_leader
        
        # 1. Market Regime Score (30% weight)
        regime_scores = self.REGIME_SCORES.get(market_regime, {"long": 50, "short": 50})
        result.regime_score = regime_scores["long" if is_long else "short"]
        
        if is_long and market_regime == "strong_uptrend":
            result.factors.append(f"Strong uptrend (SPY +{spy_change_pct:.1f}%) favors longs (++)")
        elif is_long and market_regime == "strong_downtrend":
            result.factors.append(f"Strong downtrend (SPY {spy_change_pct:.1f}%) against longs (--)")
        elif not is_long and market_regime == "strong_downtrend":
            result.factors.append(f"Strong downtrend (SPY {spy_change_pct:.1f}%) favors shorts (++)")
        elif not is_long and market_regime == "strong_uptrend":
            result.factors.append(f"Strong uptrend (SPY +{spy_change_pct:.1f}%) against shorts (--)")
        elif market_regime == "range_bound":
            result.factors.append("Range-bound market - favor mean reversion")
            
        # 2. Time of Day Score (25% weight)
        time_scores = self.TIME_SCORES.get(time_of_day, {"default": 50})
        result.time_score = time_scores.get(setup_category, time_scores.get("default", 50))
        
        if time_of_day == "opening_drive" and setup_category == "momentum":
            result.factors.append("Opening drive - optimal for momentum setups (+)")
        elif time_of_day == "midday":
            result.factors.append("Midday lull - reduced edge (-)")
        elif time_of_day == "morning_momentum":
            result.factors.append("Morning momentum window (+)")
            
        # 3. Sector Score (20% weight)
        # Sector rank 1-3 is hot, 9-11 is cold
        if is_long:
            if is_sector_leader:
                result.sector_score = 95
                result.factors.append(f"{sector} sector leader (++)")
            elif sector_rank <= 3:
                result.sector_score = 85
                result.factors.append(f"{sector} in top 3 sectors (+)")
            elif sector_rank <= 5:
                result.sector_score = 70
            elif sector_rank <= 7:
                result.sector_score = 50
            elif sector_rank <= 9:
                result.sector_score = 35
            else:
                result.sector_score = 25
                result.factors.append(f"{sector} in bottom sectors (-)")
        else:  # short
            if sector_rank >= 9:
                result.sector_score = 85
                result.factors.append(f"{sector} weak sector - favors shorts (+)")
            elif sector_rank >= 7:
                result.sector_score = 70
            elif sector_rank >= 5:
                result.sector_score = 55
            else:
                result.sector_score = 40
                result.factors.append(f"{sector} strong sector - shorts harder (-)")
                
        # 4. VIX Score (15% weight)
        # VIX 15-22 is ideal, very high or very low is challenging
        if 15 <= vix_level <= 22:
            result.vix_score = 85
            result.factors.append(f"VIX {vix_level:.1f} - normal volatility (+)")
        elif 12 <= vix_level < 15:
            result.vix_score = 70
            result.factors.append(f"VIX {vix_level:.1f} - low volatility")
        elif 22 < vix_level <= 28:
            result.vix_score = 65
            result.factors.append(f"VIX {vix_level:.1f} - elevated volatility")
        elif vix_level < 12:
            result.vix_score = 50
            result.factors.append(f"VIX {vix_level:.1f} - very low, expect choppy action (-)")
        elif 28 < vix_level <= 35:
            result.vix_score = 45
            result.factors.append(f"VIX {vix_level:.1f} - high volatility, reduce size (-)")
        else:  # > 35
            result.vix_score = 30
            result.factors.append(f"VIX {vix_level:.1f} - extreme volatility, high risk (--)")
            
        # 5. Day of Week Score (10% weight)
        # Tuesday-Thursday typically best, Monday/Friday more random
        day_scores = {
            0: 55,  # Monday - weekend gap risk
            1: 75,  # Tuesday - good
            2: 80,  # Wednesday - best
            3: 75,  # Thursday - good
            4: 50   # Friday - EOW positioning
        }
        result.day_score = day_scores.get(result.day_of_week, 60)
        
        if result.day_of_week == 2:
            result.factors.append("Wednesday - historically best trading day (+)")
        elif result.day_of_week == 4:
            result.factors.append("Friday - EOW effects may impact")
        
        # 6. AI Model Alignment Score (10% weight)
        # Does the ML model agree with the proposed trade direction?
        # MODE-C calibration (2026-04-23): 3-class setup-specific LONG models
        # peak at 0.44-0.53 conf on triple-barrier data. An UP argmax at 0.50
        # is a real edge — bucket agreement at >=0.50 into CONFIRMS, not leans.
        ai_score = 50  # Neutral default (no model data)
        CONFIRMS_THRESHOLD = 0.50
        if ai_model_agrees is not None and ai_model_confidence is not None:
            if ai_model_agrees and ai_model_confidence >= CONFIRMS_THRESHOLD:
                ai_score = 90
                result.factors.append(f"AI model CONFIRMS {direction} ({ai_model_confidence:.0%} conf) (++)")
            elif ai_model_agrees:
                ai_score = 70
                result.factors.append(f"AI model leans {direction} ({ai_model_confidence:.0%} conf) (+)")
            elif ai_model_direction == "flat":
                ai_score = 45
                result.factors.append("AI model sees no edge (flat) (-)")
            elif not ai_model_agrees and ai_model_confidence >= 0.60:
                ai_score = 20
                result.factors.append(f"AI model DISAGREES — predicts {ai_model_direction} ({ai_model_confidence:.0%} conf) (--)")
            else:
                ai_score = 35
                result.factors.append("AI model weakly disagrees (-)")
            
        # 7. Relative Strength Score (per-symbol) — v19.34.254
        # The single per-symbol input with real dynamic range. Computed vs the
        # index the symbol belongs to (QQQ/SPY/IWM via benchmark_for), from
        # daily bars. This is what de-compresses the pillar off its frozen ~62.
        rs = self._compute_relative_strength(symbol, is_long)
        if rs is not None:
            result.rs_score, result.rs_benchmark, result.rs_1d, result.rs_5d = rs
            # Direction-aware wording (a +1d move is a TAILWIND for a long but a
            # HEADWIND for a short) — show both timeframes so the drill-down
            # explanation never contradicts the score.
            _tf = f"1d {result.rs_1d:+.1f}% / 5d {result.rs_5d:+.1f}% vs {result.rs_benchmark}"
            if result.rs_score >= 70:
                result.factors.append(f"Relative strength favors {direction} ({_tf}) (+)")
            elif result.rs_score <= 30:
                result.factors.append(f"Relative strength against {direction} ({_tf}) (-)")
        else:
            result.rs_score = 50.0  # neutral when no daily bars

        # v391 — persist AI sub-score + stash raw bits for the descriptor layer.
        result.ai_score = ai_score
        result.display_ctx = {
            "is_long": is_long,
            "sector_absent": (sector == "unknown"),
            "ai_has_signal": (ai_model_agrees is not None and ai_model_confidence is not None),
            "ai_direction": ai_model_direction,
            "ai_confidence": ai_model_confidence,
            "ai_agrees": ai_model_agrees,
        }

        # Calculate weighted total (v19.34.254 weights — added per-symbol RS at
        # 20%, fed regime the multi-index composite, and trimmed the dead
        # day-of-week slice 10%→3% since it carries zero per-symbol information).
        result.score = (
            result.regime_score * 0.22 +
            result.rs_score * 0.20 +
            result.time_score * 0.18 +
            result.sector_score * 0.15 +
            result.vix_score * 0.12 +
            ai_score * 0.10 +
            result.day_score * 0.03
        )
        
        # Assign grade
        if result.score >= 85:
            result.grade = "A"
        elif result.score >= 75:
            result.grade = "B+"
        elif result.score >= 65:
            result.grade = "B"
        elif result.score >= 55:
            result.grade = "C+"
        elif result.score >= 45:
            result.grade = "C"
        elif result.score >= 35:
            result.grade = "D"
        else:
            result.grade = "F"
            
        return result


# Singleton
_context_quality_service: Optional[ContextQualityService] = None


def get_context_quality_service() -> ContextQualityService:
    global _context_quality_service
    if _context_quality_service is None:
        _context_quality_service = ContextQualityService()
    return _context_quality_service
