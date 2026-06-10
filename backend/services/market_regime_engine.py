"""
Market Regime Engine
====================
A sophisticated market state analyzer inspired by VectorVest and IBD methodologies.

Outputs:
- Market State: CONFIRMED_UP | HOLD | CONFIRMED_DOWN
- Risk Level: 0-100 scale
- Confidence Score: 0-100 scale

Signal Blocks:
1. Trend (35%): SPY vs moving averages, price structure
2. Breadth (25%): Market participation via sector analysis
3. Follow-Through Day (20%): IBD-style rally confirmation
4. Volume/VIX (20%): Fear gauge and volume patterns

TO DEPLOY:
----------
1. In server.py, add:
   from services.market_regime_engine import MarketRegimeEngine
   market_regime_engine = MarketRegimeEngine(alpaca_service, ib_service, db)
   
2. In server.py, register the router:
   from routers.market_regime import router as market_regime_router, init_market_regime_engine
   init_market_regime_engine(market_regime_engine)
   app.include_router(market_regime_router)

3. In frontend, add MarketRegimeWidget to the dashboard

Author: TradeCommand AI System
Version: 1.0
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
from enum import Enum
import statistics


class MarketState(str, Enum):
    """Market regime states"""
    CONFIRMED_UP = "CONFIRMED_UP"
    HOLD = "HOLD"
    CONFIRMED_DOWN = "CONFIRMED_DOWN"


class FTDState(str, Enum):
    """Follow-Through Day tracking states"""
    CORRECTION = "CORRECTION"
    RALLY_ATTEMPT = "RALLY_ATTEMPT"
    CONFIRMED_UP = "CONFIRMED_UP"
    CONFIRMED_DOWN = "CONFIRMED_DOWN"


class SignalBlock:
    """Base class for signal blocks"""
    
    def __init__(self, name: str, weight: float):
        self.name = name
        self.weight = weight
        self.score = 0
        self.signals = {}
        self.last_updated = None
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "weight": self.weight,
            "score": self.score,
            "signals": self.signals,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None
        }


class TrendSignalBlock(SignalBlock):
    """
    Trend Signal Block (Weight: 35%)
    Determines primary market direction using moving averages and price structure.

    v19.34.176 — COMPOSITE SPY/QQQ/IWM + tolerance band.
    Pre-fix this block scored SPY *only* (it accepted `qqq_bars` but never
    used it) with strict boolean MA comparisons. A SPY close 0.01% under
    the 21-EMA flipped a 20-pt signal off, so a flat tape where QQQ/IWM
    were green could still print a market-wide "downtrend" — the
    operator's "SPY downtrend hallucination". Now each index is scored
    independently with a ±0.25% tolerance band (matching v166) and the
    three are blended (SPY 0.5 / QQQ 0.3 / IWM 0.2, renormalized over
    whatever is available). Per-index scores + a divergence flag are
    surfaced in `signals` for observability.
    """

    # Blend weights — SPY stays dominant; QQQ/IWM temper single-index noise.
    _INDEX_WEIGHTS = {"spy": 0.5, "qqq": 0.3, "iwm": 0.2}
    # Tolerance band around each moving average (v166 = 0.25%). Price within
    # the band scores HALF credit (neutral) instead of a hard 0/full flip.
    _TREND_TOLERANCE_PCT = 0.0025

    def __init__(self):
        super().__init__("trend", 0.35)

    def _band_points(self, price: float, level: float, full: float) -> float:
        """Award `full` pts when price is clearly above `level`, 0 when
        clearly below, and half when inside the ±tolerance band."""
        if level <= 0:
            return 0.0
        diff = (price - level) / level
        if diff > self._TREND_TOLERANCE_PCT:
            return full
        if diff < -self._TREND_TOLERANCE_PCT:
            return 0.0
        return full * 0.5

    def _score_index(self, bars: List[Dict]) -> Optional[Dict]:
        """Score a single index 0-100 from its daily bars (tolerance-aware).
        Returns None when there is insufficient data so the caller can
        renormalize the blend over only the available indexes."""
        if not bars or len(bars) < 200:
            return None

        closes = [bar.get("close", bar.get("c", 0)) for bar in bars]
        highs = [bar.get("high", bar.get("h", 0)) for bar in bars]
        lows = [bar.get("low", bar.get("l", 0)) for bar in bars]
        current_price = closes[-1]

        ema_21 = self._calculate_ema(closes, 21)
        sma_50 = self._calculate_sma(closes, 50)
        sma_200 = self._calculate_sma(closes, 200)

        score = 0.0
        score += self._band_points(current_price, ema_21, 20)
        score += self._band_points(current_price, sma_50, 20)
        score += self._band_points(current_price, sma_200, 15)
        # 21-EMA vs 50-SMA alignment (tolerance-aware, 15 pts)
        score += self._band_points(ema_21, sma_50, 15)
        # Higher-highs / higher-lows structure (30 pts)
        score += self._analyze_price_structure(highs[-20:], lows[-20:]) * 30 / 100

        return {
            "score": round(score, 1),
            "current_price": round(current_price, 2),
            "ema_21": round(ema_21, 2),
            "sma_50": round(sma_50, 2),
            "sma_200": round(sma_200, 2),
            "above_21_ema": current_price > ema_21,
            "above_50_sma": current_price > sma_50,
            "above_200_sma": current_price > sma_200,
        }

    async def calculate(
        self,
        spy_bars: List[Dict],
        qqq_bars: List[Dict] = None,
        iwm_bars: List[Dict] = None,
    ) -> float:
        """
        Composite trend score (0-100) blended across SPY/QQQ/IWM.

        Per-index indicators (each tolerance-aware, ±0.25%):
        - price vs 21 EMA (20 pts)
        - price vs 50 SMA (20 pts)
        - price vs 200 SMA (15 pts)
        - 21 EMA vs 50 SMA alignment (15 pts)
        - higher highs/lows structure (30 pts)
        """
        per_index = {
            "spy": self._score_index(spy_bars),
            "qqq": self._score_index(qqq_bars),
            "iwm": self._score_index(iwm_bars),
        }

        # SPY is the anchor — if it's missing we can't classify the tape.
        if per_index["spy"] is None:
            self.score = 50  # Neutral if insufficient data
            self.signals = {"error": "Insufficient SPY data for trend analysis"}
            return self.score

        # Weighted blend over whatever indexes have data, renormalized.
        total_w = 0.0
        blended = 0.0
        index_scores = {}
        for key, data in per_index.items():
            if data is None:
                continue
            w = self._INDEX_WEIGHTS[key]
            blended += data["score"] * w
            total_w += w
            index_scores[key] = data["score"]
        score = blended / total_w if total_w > 0 else per_index["spy"]["score"]

        # Divergence: the indexes disagree on bull (>=60) vs bear (<=40).
        any_bull = any(s >= 60 for s in index_scores.values())
        any_bear = any(s <= 40 for s in index_scores.values())
        divergence_flag = any_bull and any_bear

        self.score = round(score, 1)
        self.signals = {
            "composite_score": round(score, 1),
            "index_scores": index_scores,
            "indexes_used": list(index_scores.keys()),
            "blend_weights": {k: self._INDEX_WEIGHTS[k] for k in index_scores},
            "divergence_flag": divergence_flag,
            "tolerance_pct": self._TREND_TOLERANCE_PCT,
            # Back-compat: keep SPY's raw MA signals for existing consumers.
            "current_price": per_index["spy"]["current_price"],
            "ema_21": per_index["spy"]["ema_21"],
            "sma_50": per_index["spy"]["sma_50"],
            "sma_200": per_index["spy"]["sma_200"],
            "above_21_ema": per_index["spy"]["above_21_ema"],
            "above_50_sma": per_index["spy"]["above_50_sma"],
            "above_200_sma": per_index["spy"]["above_200_sma"],
            "trend_direction": "BULLISH" if score >= 60 else "BEARISH" if score <= 40 else "NEUTRAL",
        }
        self.last_updated = datetime.now(timezone.utc)

        return self.score
    
    def _calculate_ema(self, prices: List[float], period: int) -> float:
        """Calculate Exponential Moving Average"""
        if len(prices) < period:
            return prices[-1] if prices else 0
        
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period  # Start with SMA
        
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        
        return ema
    
    def _calculate_sma(self, prices: List[float], period: int) -> float:
        """Calculate Simple Moving Average"""
        if len(prices) < period:
            return sum(prices) / len(prices) if prices else 0
        return sum(prices[-period:]) / period
    
    def _analyze_price_structure(self, highs: List[float], lows: List[float]) -> float:
        """
        Analyze for higher highs / higher lows (bullish) or lower highs / lower lows (bearish).
        Returns 0-100 score where 100 = perfect uptrend, 0 = perfect downtrend.
        """
        if len(highs) < 5 or len(lows) < 5:
            return 50
        
        # Find swing points (simplified)
        higher_highs = 0
        lower_lows = 0
        
        for i in range(1, len(highs)):
            if highs[i] > highs[i-1]:
                higher_highs += 1
            if lows[i] > lows[i-1]:
                higher_highs += 1  # Higher low is bullish
            if highs[i] < highs[i-1]:
                lower_lows += 1  # Lower high is bearish
            if lows[i] < lows[i-1]:
                lower_lows += 1
        
        total = higher_highs + lower_lows
        if total == 0:
            return 50
        
        return (higher_highs / total) * 100


class BreadthSignalBlock(SignalBlock):
    """
    Breadth Signal Block (Weight: 25%)
    Measures market participation using sector ETF analysis as proxy.
    """
    
    SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLC", "XLY", "XLP", "XLU", "XLRE", "XLB"]
    
    def __init__(self):
        super().__init__("breadth", 0.25)
    
    async def calculate(self, sector_data: Dict[str, Dict], 
                       spy_change: float = 0, 
                       qqq_change: float = 0,
                       iwm_change: float = 0,
                       vold_ratio: float = 1.0) -> float:
        """
        Calculate breadth score from sector and index data.
        
        Indicators:
        - All indices aligned (25 pts)
        - Sectors positive count (35 pts)
        - VOLD ratio positive (20 pts)
        - Small caps participating (20 pts)
        """
        score = 0
        
        # Index alignment (25 pts)
        indices_bullish = sum([
            1 if spy_change > 0 else 0,
            1 if qqq_change > 0 else 0,
            1 if iwm_change > 0 else 0
        ])
        indices_bearish = sum([
            1 if spy_change < 0 else 0,
            1 if qqq_change < 0 else 0,
            1 if iwm_change < 0 else 0
        ])
        
        if indices_bullish == 3:
            score += 25
            indices_aligned = "BULLISH"
        elif indices_bearish == 3:
            score += 0
            indices_aligned = "BEARISH"
        else:
            score += 12  # Partial alignment
            indices_aligned = "MIXED"
        
        # Sector participation (35 pts)
        sectors_positive = 0
        sectors_negative = 0
        sector_details = {}
        
        for etf in self.SECTOR_ETFS:
            if etf in sector_data:
                change = sector_data[etf].get("change_pct", 0)
                sector_details[etf] = round(change, 2)
                if change > 0:
                    sectors_positive += 1
                elif change < 0:
                    sectors_negative += 1
        
        total_sectors = len(self.SECTOR_ETFS)
        sector_score = (sectors_positive / total_sectors) * 35 if total_sectors > 0 else 17.5
        score += sector_score
        
        # VOLD ratio (20 pts)
        if vold_ratio >= 2.0:
            score += 20
            vold_status = "STRONG_BULLISH"
        elif vold_ratio >= 1.5:
            score += 15
            vold_status = "BULLISH"
        elif vold_ratio >= 1.0:
            score += 10
            vold_status = "NEUTRAL"
        elif vold_ratio >= 0.5:
            score += 5
            vold_status = "BEARISH"
        else:
            score += 0
            vold_status = "STRONG_BEARISH"
        
        # Small cap participation (20 pts)
        if iwm_change > 0.5:
            score += 20
            small_cap_status = "STRONG"
        elif iwm_change > 0:
            score += 15
            small_cap_status = "POSITIVE"
        elif iwm_change > -0.5:
            score += 10
            small_cap_status = "NEUTRAL"
        else:
            score += 0
            small_cap_status = "WEAK"
        
        self.score = round(score, 1)
        self.signals = {
            "indices_aligned": indices_aligned,
            "spy_change": round(spy_change, 2),
            "qqq_change": round(qqq_change, 2),
            "iwm_change": round(iwm_change, 2),
            "sectors_positive": sectors_positive,
            "sectors_negative": sectors_negative,
            "sector_details": sector_details,
            "vold_ratio": round(vold_ratio, 2),
            "vold_status": vold_status,
            "small_cap_status": small_cap_status
        }
        self.last_updated = datetime.now(timezone.utc)
        
        return self.score


class FTDSignalBlock(SignalBlock):
    """
    Follow-Through Day Signal Block (Weight: 20%)
    Implements IBD's Follow-Through Day methodology for detecting market turns.
    """
    
    # IBD thresholds
    FTD_MIN_GAIN = 1.25  # Minimum % gain for FTD
    DISTRIBUTION_MIN_LOSS = 0.2  # Minimum % loss for distribution day
    DISTRIBUTION_MAX_COUNT = 5  # Max distribution days before signal weakens
    RALLY_MIN_DAYS = 4  # Minimum days before FTD can occur
    
    def __init__(self):
        super().__init__("ftd", 0.20)
        self.ftd_state = FTDState.CORRECTION
        self.rally_start_date = None
        self.ftd_date = None
        self.distribution_days = []
        self.days_in_rally = 0
    
    async def calculate(self, spy_bars: List[Dict], 
                       stored_state: Dict = None) -> float:
        """
        Calculate FTD score based on market structure.
        
        Indicators:
        - FTD confirmed (50 pts)
        - Distribution day count low (30 pts)
        - Rally intact (20 pts)
        """
        if not spy_bars or len(spy_bars) < 30:
            self.score = 50
            self.signals = {"error": "Insufficient data for FTD analysis"}
            return self.score
        
        # Restore state from storage if available
        if stored_state:
            self._restore_state(stored_state)
        
        # Analyze recent bars for FTD signals
        self._update_ftd_state(spy_bars)

        # Collapse duplicate distribution entries to one-per-trading-day. Defends
        # against legacy now()-stamped duplicates persisted before the dedup fix
        # (which had inflated the count to 25 → "CRITICAL" and floored the score).
        _seen_days = set()
        _deduped = []
        for _d in self.distribution_days:
            _day = str(_d.get("date", ""))[:10]
            if _day and _day not in _seen_days:
                _seen_days.add(_day)
                _deduped.append(_d)
        self.distribution_days = _deduped[-25:]

        score = 0
        
        # FTD confirmed (50 pts)
        if self.ftd_state == FTDState.CONFIRMED_UP:
            score += 50
            ftd_status = "CONFIRMED_RALLY"
        elif self.ftd_state == FTDState.RALLY_ATTEMPT:
            score += 25
            ftd_status = "RALLY_ATTEMPT"
        elif self.ftd_state == FTDState.CONFIRMED_DOWN:
            score += 0
            ftd_status = "CONFIRMED_CORRECTION"
        else:
            score += 15
            ftd_status = "IN_CORRECTION"
        
        # Distribution day count (30 pts)
        recent_distribution = len([d for d in self.distribution_days 
                                   if d.get("date") and 
                                   (datetime.now(timezone.utc) - datetime.fromisoformat(d["date"].replace("Z", "+00:00"))).days <= 25])
        
        if recent_distribution <= 2:
            score += 30
            distribution_status = "HEALTHY"
        elif recent_distribution <= 4:
            score += 20
            distribution_status = "ELEVATED"
        elif recent_distribution <= 5:
            score += 10
            distribution_status = "WARNING"
        else:
            score += 0
            distribution_status = "CRITICAL"
        
        # Rally intact (20 pts)
        if self.ftd_state in [FTDState.CONFIRMED_UP, FTDState.RALLY_ATTEMPT]:
            if self.days_in_rally >= 10:
                score += 20
                rally_status = "STRONG"
            elif self.days_in_rally >= 5:
                score += 15
                rally_status = "DEVELOPING"
            else:
                score += 10
                rally_status = "EARLY"
        else:
            score += 0
            rally_status = "NO_RALLY"
        
        self.score = round(score, 1)
        self.signals = {
            "ftd_state": self.ftd_state.value,
            "ftd_status": ftd_status,
            "rally_start_date": self.rally_start_date,
            "ftd_date": self.ftd_date,
            "days_in_rally": self.days_in_rally,
            "distribution_day_count": recent_distribution,
            "distribution_status": distribution_status,
            "rally_status": rally_status,
            "distribution_days": self.distribution_days[-5:]  # Last 5
        }
        self.last_updated = datetime.now(timezone.utc)
        
        return self.score
    
    def _update_ftd_state(self, bars: List[Dict]):
        """Update the FTD state machine based on recent price action"""
        if len(bars) < 5:
            return
        
        # Get recent bar data
        today = bars[-1]
        yesterday = bars[-2]
        
        today_close = today.get("close", today.get("c", 0))
        today_volume = today.get("volume", today.get("v", 0))
        yesterday_close = yesterday.get("close", yesterday.get("c", 0))
        yesterday_volume = yesterday.get("volume", yesterday.get("v", 0))
        
        if yesterday_close == 0:
            return
        
        daily_change_pct = ((today_close - yesterday_close) / yesterday_close) * 100
        volume_increased = today_volume > yesterday_volume
        
        # Check for distribution day — dedupe by the BAR's trading date, not
        # wall-clock now(). Previously this stamped datetime.now() and appended
        # on EVERY calculate() call, so a single down-day was re-counted on each
        # refresh and inflated the distribution count (observed 25 duplicates →
        # "CRITICAL" → score floored to 15).
        if daily_change_pct <= -self.DISTRIBUTION_MIN_LOSS and volume_increased:
            bar_date = today.get("timestamp") or today.get("date")
            bar_day = str(bar_date)[:10] if bar_date else datetime.now(timezone.utc).strftime("%Y-%m-%d")
            already_logged = any(str(d.get("date", ""))[:10] == bar_day for d in self.distribution_days)
            if not already_logged:
                self.distribution_days.append({
                    "date": f"{bar_day}T00:00:00+00:00",
                    "change_pct": round(daily_change_pct, 2),
                    "volume_ratio": round(today_volume / yesterday_volume, 2) if yesterday_volume > 0 else 1
                })
                # Keep only the last 25 distinct distribution days
                self.distribution_days = self.distribution_days[-25:]
        
        # State machine logic
        if self.ftd_state == FTDState.CORRECTION:
            # Look for rally attempt (first up day after correction)
            if daily_change_pct > 0:
                self.ftd_state = FTDState.RALLY_ATTEMPT
                self.rally_start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                self.days_in_rally = 1
        
        elif self.ftd_state == FTDState.RALLY_ATTEMPT:
            self.days_in_rally += 1
            
            # Check for FTD confirmation
            if (self.days_in_rally >= self.RALLY_MIN_DAYS and 
                daily_change_pct >= self.FTD_MIN_GAIN and 
                volume_increased):
                self.ftd_state = FTDState.CONFIRMED_UP
                self.ftd_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                self.distribution_days = []  # Reset distribution count
            
            # Check for failed rally
            elif daily_change_pct < -2.0:  # Big down day fails rally
                self.ftd_state = FTDState.CORRECTION
                self.rally_start_date = None
                self.days_in_rally = 0
        
        elif self.ftd_state == FTDState.CONFIRMED_UP:
            self.days_in_rally += 1
            
            # Check for distribution day overload
            recent_dist = len([d for d in self.distribution_days 
                              if d.get("date") and 
                              (datetime.now(timezone.utc) - datetime.fromisoformat(d["date"].replace("Z", "+00:00"))).days <= 25])
            
            if recent_dist >= self.DISTRIBUTION_MAX_COUNT:
                self.ftd_state = FTDState.CONFIRMED_DOWN
        
        elif self.ftd_state == FTDState.CONFIRMED_DOWN:
            # Look for signs of bottoming
            if daily_change_pct > 0:
                self.ftd_state = FTDState.RALLY_ATTEMPT
                self.rally_start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                self.days_in_rally = 1
    
    def _restore_state(self, stored_state: Dict):
        """Restore FTD state from MongoDB storage"""
        if "ftd_state" in stored_state:
            try:
                self.ftd_state = FTDState(stored_state["ftd_state"])
            except ValueError:
                self.ftd_state = FTDState.CORRECTION
        
        self.rally_start_date = stored_state.get("rally_start_date")
        self.ftd_date = stored_state.get("ftd_date")
        self.days_in_rally = stored_state.get("days_in_rally", 0)
        self.distribution_days = stored_state.get("distribution_days", [])
    
    def get_state_for_storage(self) -> Dict:
        """Get FTD state for MongoDB storage"""
        return {
            "ftd_state": self.ftd_state.value,
            "rally_start_date": self.rally_start_date,
            "ftd_date": self.ftd_date,
            "days_in_rally": self.days_in_rally,
            "distribution_days": self.distribution_days
        }


class VolumeVixSignalBlock(SignalBlock):
    """
    Volume/VIX Signal Block (Weight: 20%)
    Measures fear/greed through VIX levels and volume patterns.
    """
    
    def __init__(self):
        super().__init__("volume_vix", 0.20)
    
    async def calculate(self, vix_price: float = 0, 
                       vix_change: float = 0,
                       spy_bars: List[Dict] = None,
                       current_rvol: float = 1.0) -> float:
        """
        Calculate volume/VIX score.
        
        Indicators:
        - VIX level healthy (30 pts)
        - VIX trend favorable (20 pts)
        - Volume confirms trend (30 pts)
        - RVOL normal range (20 pts)
        """
        score = 0
        
        # VIX level (30 pts)
        # Lower VIX = more bullish (less fear)
        if vix_price <= 15:
            score += 30
            vix_level_status = "LOW_FEAR"
        elif vix_price <= 20:
            score += 25
            vix_level_status = "NORMAL"
        elif vix_price <= 25:
            score += 15
            vix_level_status = "ELEVATED"
        elif vix_price <= 30:
            score += 5
            vix_level_status = "HIGH_FEAR"
        else:
            score += 0
            vix_level_status = "EXTREME_FEAR"
        
        # VIX trend (20 pts)
        # Falling VIX = bullish, Rising VIX = bearish
        if vix_change < -5:
            score += 20
            vix_trend_status = "FALLING_FAST"
        elif vix_change < 0:
            score += 15
            vix_trend_status = "FALLING"
        elif vix_change < 5:
            score += 10
            vix_trend_status = "STABLE"
        elif vix_change < 10:
            score += 5
            vix_trend_status = "RISING"
        else:
            score += 0
            vix_trend_status = "RISING_FAST"
        
        # Volume confirms trend (30 pts)
        volume_confirmation = self._analyze_volume_pattern(spy_bars) if spy_bars else 50
        score += (volume_confirmation / 100) * 30
        
        if volume_confirmation >= 70:
            volume_status = "CONFIRMS_UPTREND"
        elif volume_confirmation >= 50:
            volume_status = "NEUTRAL"
        else:
            volume_status = "CONFIRMS_DOWNTREND"
        
        # RVOL range (20 pts)
        # Normal RVOL (1.0-1.5) is healthy, too high indicates panic
        if 0.8 <= current_rvol <= 1.5:
            score += 20
            rvol_status = "HEALTHY"
        elif 0.5 <= current_rvol <= 2.0:
            score += 15
            rvol_status = "ELEVATED"
        elif current_rvol > 2.0:
            score += 5  # High volume can mean panic selling
            rvol_status = "EXTREME"
        else:
            score += 10
            rvol_status = "LOW"
        
        self.score = round(score, 1)
        self.signals = {
            "vix_price": round(vix_price, 2),
            "vix_change": round(vix_change, 2),
            "vix_level_status": vix_level_status,
            "vix_trend_status": vix_trend_status,
            "volume_confirmation_score": round(volume_confirmation, 1),
            "volume_status": volume_status,
            "current_rvol": round(current_rvol, 2),
            "rvol_status": rvol_status
        }
        self.last_updated = datetime.now(timezone.utc)
        
        return self.score
    
    def _analyze_volume_pattern(self, bars: List[Dict]) -> float:
        """
        Analyze if volume confirms price trend.
        Up days should have higher volume in uptrend.
        Returns 0-100 score.
        """
        if not bars or len(bars) < 10:
            return 50
        
        recent_bars = bars[-20:]
        up_day_volume = []
        down_day_volume = []
        
        for i in range(1, len(recent_bars)):
            bar = recent_bars[i]
            prev_bar = recent_bars[i-1]
            
            close = bar.get("close", bar.get("c", 0))
            prev_close = prev_bar.get("close", prev_bar.get("c", 0))
            volume = bar.get("volume", bar.get("v", 0))
            
            if close > prev_close:
                up_day_volume.append(volume)
            elif close < prev_close:
                down_day_volume.append(volume)
        
        avg_up_volume = sum(up_day_volume) / len(up_day_volume) if up_day_volume else 0
        avg_down_volume = sum(down_day_volume) / len(down_day_volume) if down_day_volume else 0
        
        if avg_up_volume + avg_down_volume == 0:
            return 50
        
        # If up days have more volume, that's bullish
        if avg_up_volume > avg_down_volume:
            ratio = avg_up_volume / (avg_up_volume + avg_down_volume)
            return min(100, ratio * 100 + 10)
        else:
            ratio = avg_down_volume / (avg_up_volume + avg_down_volume)
            return max(0, 50 - (ratio - 0.5) * 100)


class MarketRegimeEngine:
    """
    Main Market Regime Engine that coordinates all signal blocks.
    """
    
    # Update frequency (30 minutes)
    UPDATE_INTERVAL_SECONDS = 30 * 60
    
    # Score thresholds for state determination.
    # v19.34.303 — FIX asymmetric neutral band. Composite score is centered on
    # 50 (neutral). CONFIRMED_UP requires +20 (>=70), so CONFIRMED_DOWN must be
    # symmetric at -20 (<30). Previously CONFIRMED_DOWN sat at 50, meaning ANY
    # sub-neutral read (e.g. a flat 48.4) was branded a confirmed bear regime,
    # which forced the confidence gate into DEFENSIVE mode (GO threshold 60 +
    # -10 long penalty) and skipped virtually every intraday setup. A genuine
    # confirmed downtrend should require broad, strong bearishness (<30), not a
    # hair below neutral. The 30-69 band is HOLD/neutral → CAUTIOUS trading.
    CONFIRMED_UP_THRESHOLD = 70
    CONFIRMED_DOWN_THRESHOLD = 30
    
    def __init__(self, alpaca_service=None, ib_service=None, db=None):
        self.alpaca_service = alpaca_service
        self.ib_service = ib_service
        self.db = db
        
        # Initialize signal blocks
        self.trend_block = TrendSignalBlock()
        self.breadth_block = BreadthSignalBlock()
        self.ftd_block = FTDSignalBlock()
        self.volume_vix_block = VolumeVixSignalBlock()
        
        # Cache
        self._cache: Dict = {}
        self._cache_time: datetime = None
        self._cache_ttl = self.UPDATE_INTERVAL_SECONDS
        
        # State tracking
        self.current_state = MarketState.HOLD
        self.previous_state = None
        self.state_change_time = None
    
    async def get_current_regime(self, force_refresh: bool = False) -> Dict:
        """
        Get the current market regime analysis.
        Uses cache unless force_refresh is True or cache is stale.
        """
        # Check cache
        if not force_refresh and self._cache and self._cache_time:
            cache_age = (datetime.now(timezone.utc) - self._cache_time).total_seconds()
            if cache_age < self._cache_ttl:
                return self._cache
        
        # Calculate fresh regime
        regime = await self._calculate_regime()
        
        # Update cache
        self._cache = regime
        self._cache_time = datetime.now(timezone.utc)
        
        # Store in MongoDB if available
        await self._store_regime(regime)
        
        return regime
    
    async def _calculate_regime(self) -> Dict:
        """Calculate the full market regime analysis."""
        
        # Fetch all required data
        spy_bars = await self._get_historical_bars("SPY", 200)
        # v19.34.176 — QQQ/IWM now feed the composite TREND block (not just
        # breadth), so they need the full 200-bar window for sma_200.
        qqq_bars = await self._get_historical_bars("QQQ", 200)
        iwm_bars = await self._get_historical_bars("IWM", 200)
        
        # Get current quotes for change calculations
        spy_quote = await self._get_quote("SPY")
        qqq_quote = await self._get_quote("QQQ")
        iwm_quote = await self._get_quote("IWM")
        vix_data = await self._get_vix_data()
        
        # Get sector data
        sector_data = await self._get_sector_data()
        
        # Get VOLD ratio from existing market indicators
        vold_ratio = await self._get_vold_ratio()
        
        # Load FTD state from storage
        ftd_stored_state = await self._load_ftd_state()
        
        # Calculate each signal block
        # v19.34.176 — composite SPY/QQQ/IWM trend (tolerance-aware).
        await self.trend_block.calculate(spy_bars, qqq_bars, iwm_bars)
        
        await self.breadth_block.calculate(
            sector_data,
            spy_quote.get("change_pct", 0),
            qqq_quote.get("change_pct", 0),
            iwm_quote.get("change_pct", 0),
            vold_ratio
        )
        
        await self.ftd_block.calculate(spy_bars, ftd_stored_state)
        
        await self.volume_vix_block.calculate(
            vix_data.get("price", 20),
            vix_data.get("change_pct", 0),
            spy_bars,
            spy_quote.get("rvol", 1.0)
        )
        
        # Calculate composite score
        composite_score = (
            self.trend_block.score * self.trend_block.weight +
            self.breadth_block.score * self.breadth_block.weight +
            self.ftd_block.score * self.ftd_block.weight +
            self.volume_vix_block.score * self.volume_vix_block.weight
        )
        
        # Determine market state
        if composite_score >= self.CONFIRMED_UP_THRESHOLD:
            new_state = MarketState.CONFIRMED_UP
        elif composite_score < self.CONFIRMED_DOWN_THRESHOLD:
            new_state = MarketState.CONFIRMED_DOWN
        else:
            new_state = MarketState.HOLD
        
        # Track state changes
        state_changed = new_state != self.current_state
        if state_changed:
            self.previous_state = self.current_state
            self.current_state = new_state
            self.state_change_time = datetime.now(timezone.utc)
        
        # Calculate confidence
        confidence = self._calculate_confidence()
        
        # Calculate risk level (inverse of composite)
        risk_level = 100 - composite_score
        
        # Generate recommendation
        recommendation = self._generate_recommendation(new_state, composite_score)

        # Multi-timeframe context (additive — preserves all existing fields).
        # Anchors on SPY across 1d/1h/5m/1m; degrades gracefully to anchor-only
        # when intraday bars are not yet backfilled.
        multi_tf = await self._calculate_multi_tf()

        return {
            "state": new_state.value,
            "previous_state": self.previous_state.value if self.previous_state else None,
            "state_changed": state_changed,
            "state_change_time": self.state_change_time.isoformat() if self.state_change_time else None,
            "composite_score": round(composite_score, 1),
            "risk_level": round(risk_level, 1),
            "confidence": round(confidence, 1),
            "signal_blocks": {
                "trend": self.trend_block.to_dict(),
                "breadth": self.breadth_block.to_dict(),
                "ftd": self.ftd_block.to_dict(),
                "volume_vix": self.volume_vix_block.to_dict()
            },
            "multi_tf": multi_tf,
            "recommendation": recommendation,
            "trading_implications": self._get_trading_implications(new_state),
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
    
    async def _calculate_multi_tf(self) -> Dict:
        """Multi-index (SPY/QQQ/IWM) multi-timeframe regime + TICK internals.

        A(a): each lane blends SPY/QQQ/IWM (0.5/0.3/0.2). B1(c): per-index TICK
        — NYSE ($TICK) covers SPY+IWM, Nasdaq ($TICKQ) covers QQQ — fetched live
        over the ib-direct socket (the only working historical path here). B2(c):
        internals confirm/contradict the intraday read + flag climaxes. Degrades
        gracefully (any missing lane/feed simply drops out of the blend)."""
        try:
            from services.multi_tf_regime import (
                score_long_lane, score_intraday_lane, blend_intraday,
                weighted_blend, score_internals, combine_internals,
                index_divergence, build_multi_tf, INDEX_WEIGHTS,
            )

            symbols = ["SPY", "QQQ", "IWM"]
            per = {}
            for sym in symbols:
                daily = await self._get_tf_bars(sym, "1 day", 220)
                h1 = await self._get_tf_bars(sym, "1 hour", 120)
                m5 = await self._get_tf_bars(sym, "5 mins", 120)
                m1 = await self._get_tf_bars(sym, "1 min", 120)
                L = score_long_lane(daily)
                M = score_intraday_lane(h1, fast=20, slow=50, use_vwap=False)
                S = score_intraday_lane(m5, fast=9, slow=21, use_vwap=True)
                Mi = score_intraday_lane(m1, fast=9, slow=21, use_vwap=True)
                per[sym] = {"long": L, "mid": M, "short": S, "micro": Mi,
                            "intraday": blend_intraday(M, S, Mi)}

            long_s = weighted_blend({s: per[s]["long"] for s in symbols}, INDEX_WEIGHTS)
            mid_s = weighted_blend({s: per[s]["mid"] for s in symbols}, INDEX_WEIGHTS)
            short_s = weighted_blend({s: per[s]["short"] for s in symbols}, INDEX_WEIGHTS)
            micro_s = weighted_blend({s: per[s]["micro"] for s in symbols}, INDEX_WEIGHTS)

            divergence = index_divergence(
                per["SPY"]["intraday"], per["QQQ"]["intraday"], per["IWM"]["intraday"])

            # Per-index TICK internals via the live ib-direct socket.
            internals = None
            try:
                from services.ib_direct_service import get_ib_direct_service
                ibd = get_ib_direct_service()
                if ibd and ibd.is_connected():
                    nyse_bars = await ibd.get_historical_data("TICK-NYSE", "1 D", "1 min")
                    nasd_bars = await ibd.get_historical_data("TICK-NASD", "1 D", "1 min")
                    internals = combine_internals(
                        score_internals(nyse_bars, "NYSE"),
                        score_internals(nasd_bars, "NASD"))
            except Exception as ie:
                print(f"multi-tf internals error: {ie}")

            per_index = {s: {"long": per[s]["long"], "intraday": per[s]["intraday"]}
                         for s in symbols}
            return build_multi_tf(long_s, mid_s, short_s, micro_s,
                                  internals=internals, divergence=divergence,
                                  per_index=per_index)
        except Exception as e:
            print(f"multi-tf calc error: {e}")
            return {"context": "UNKNOWN", "error": str(e)}

    async def _get_tf_bars(self, symbol: str, bar_size: str, limit: int = 120) -> List[Dict]:
        """Read cached intraday bars for a timeframe from ib_historical_data.

        Uses the injected self.db handle (the module-level get_database() returns
        None in the IB-only runtime — same fix as the breadth path). Returns
        chronological OHLCV; empty list when the timeframe isn't backfilled yet."""
        db = self.db
        if db is None:
            try:
                from database import get_database
                db = get_database()
            except Exception:
                db = None
        if db is None:
            return []
        try:
            def _q():
                return list(db["ib_historical_data"].find(
                    {"symbol": symbol, "bar_size": bar_size},
                    {"_id": 0, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "date": 1}
                ).sort("date", -1).limit(limit))
            rows = await asyncio.to_thread(_q)
            if rows:
                return [{
                    "open": r.get("open"), "high": r.get("high"),
                    "low": r.get("low"), "close": r.get("close"),
                    "volume": r.get("volume"),
                } for r in reversed(rows)]
        except Exception as e:
            print(f"tf-bars error {symbol} {bar_size}: {e}")
        return []

    async def _get_tf_bars_v322(self, symbol, bar_size, limit=120):
        """v322 self-contained timeframe bar reader (ib_historical_data).

        Private copy for the symbol-level regime path so the v322 patch has
        ZERO dependencies on other engine internals (DGX tree drift proof).
        Chronological OHLCV; [] when the timeframe isn't backfilled."""
        import asyncio as _aio
        db = getattr(self, "db", None)
        if db is None:
            try:
                from database import get_database
                db = get_database()
            except Exception:
                db = None
        if db is None:
            return []
        try:
            def _q():
                return list(db["ib_historical_data"].find(
                    {"symbol": symbol, "bar_size": bar_size},
                    {"_id": 0, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "date": 1}
                ).sort("date", -1).limit(limit))
            rows = await _aio.to_thread(_q)
            if rows:
                return [{
                    "open": r.get("open"), "high": r.get("high"),
                    "low": r.get("low"), "close": r.get("close"),
                    "volume": r.get("volume"),
                } for r in reversed(rows)]
        except Exception as e:
            print(f"v322 tf-bars error {symbol} {bar_size}: {e}")
        return []

    async def compute_symbol_multi_tf(self, symbol):
        """Per-stock multi-timeframe regime (#1 / c2 foundation).

        Runs the SAME lane scoring as the index regime, but on ONE symbol's
        own bars — no index blend, no TICK internals (those are market-wide).
        Returns the build_multi_tf shape (context / lanes / tf_alignment /
        modes / recommendation) so a per-ticker RegimeStrip can render a trend
        stack and the gate can read a candidate's OWN regime alignment.
        Degrades gracefully (cold/missing lanes → context UNKNOWN)."""
        try:
            from services.multi_tf_regime import (
                score_long_lane, score_intraday_lane, build_multi_tf)
            daily = await self._get_tf_bars_v322(symbol, "1 day", 220)
            h1 = await self._get_tf_bars_v322(symbol, "1 hour", 120)
            m5 = await self._get_tf_bars_v322(symbol, "5 mins", 120)
            m1 = await self._get_tf_bars_v322(symbol, "1 min", 120)
            mtf = build_multi_tf(
                score_long_lane(daily),
                score_intraday_lane(h1, fast=20, slow=50, use_vwap=False),
                score_intraday_lane(m5, fast=9, slow=21, use_vwap=True),
                score_intraday_lane(m1, fast=9, slow=21, use_vwap=True),
            )
            mtf["symbol"] = symbol
            return mtf
        except Exception as e:
            print(f"symbol multi-tf error {symbol}: {e}")
            return {"context": "UNKNOWN", "error": str(e), "symbol": symbol}

    async def compute_symbol_multi_tf_cached(self, symbol, ttl_s=300):
        """TTL-cached wrapper around compute_symbol_multi_tf (v322 / c2).

        The raw call does 4 Mongo bar queries per symbol — the cache makes it
        safe for the confidence gate to consult on every alert evaluation.
        Bounded (~600 symbols) with oldest-first eviction."""
        import time as _time
        sym = symbol.upper()
        if not hasattr(self, "_symbol_mtf_cache"):
            self._symbol_mtf_cache = {}
        now = _time.time()
        hit = self._symbol_mtf_cache.get(sym)
        if hit and (now - hit[0]) < ttl_s:
            return hit[1]
        res = await self.compute_symbol_multi_tf(sym)
        if len(self._symbol_mtf_cache) > 600:
            for old_key in sorted(self._symbol_mtf_cache,
                                  key=lambda k: self._symbol_mtf_cache[k][0])[:100]:
                self._symbol_mtf_cache.pop(old_key, None)
        self._symbol_mtf_cache[sym] = (now, res)
        return res



    def _calculate_confidence(self) -> float:
        """Calculate confidence based on signal block agreement."""
        scores = [
            self.trend_block.score,
            self.breadth_block.score,
            self.ftd_block.score,
            self.volume_vix_block.score
        ]
        
        # Count bullish vs bearish blocks
        bullish_count = sum(1 for s in scores if s >= 60)
        bearish_count = sum(1 for s in scores if s <= 40)
        
        # All agree
        if bullish_count == 4 or bearish_count == 4:
            variance = statistics.variance(scores) if len(scores) > 1 else 0
            return min(95, 90 + (10 - min(10, variance / 10)))
        
        # 3 of 4 agree
        if bullish_count == 3 or bearish_count == 3:
            return 75
        
        # Mixed signals
        avg_score = sum(scores) / len(scores)
        return max(40, 60 - abs(50 - avg_score))
    
    def _generate_recommendation(self, state: MarketState, score: float) -> str:
        """Generate trading recommendation based on regime."""
        if state == MarketState.CONFIRMED_UP:
            if score >= 85:
                return "Strong uptrend confirmed. Favor momentum longs, buy dips aggressively, let winners run."
            else:
                return "Uptrend in place. Favor long setups, buy pullbacks to support, maintain normal position sizes."
        
        elif state == MarketState.CONFIRMED_DOWN:
            if score <= 30:
                return "Strong downtrend confirmed. Favor shorts or cash, sell rallies, avoid catching falling knives."
            else:
                return "Correction mode. Reduce exposure, favor defensive sectors, wait for follow-through day."
        
        else:  # HOLD
            return "Mixed signals. Be selective with trades, reduce position sizes, take quick profits."
    
    def _get_trading_implications(self, state: MarketState) -> Dict:
        """Get specific trading implications for the regime."""
        implications = {
            MarketState.CONFIRMED_UP: {
                "position_sizing": "Normal to aggressive",
                "favored_strategies": ["Momentum breakouts", "Pullback entries", "Trend continuation"],
                "avoid_strategies": ["Counter-trend shorts", "Mean reversion fades"],
                "sector_focus": "Growth, Technology, Consumer Discretionary",
                "risk_tolerance": "Higher - let winners run"
            },
            MarketState.HOLD: {
                "position_sizing": "Reduced (50-75% normal)",
                "favored_strategies": ["Selective high-quality setups", "Quick scalps"],
                "avoid_strategies": ["Swing trades", "Overnight holds"],
                "sector_focus": "Defensive - Utilities, Healthcare, Consumer Staples",
                "risk_tolerance": "Lower - quick profits, tight stops"
            },
            MarketState.CONFIRMED_DOWN: {
                "position_sizing": "Minimal (25-50% normal) or cash",
                "favored_strategies": ["Short selling rallies", "Put options", "Inverse ETFs"],
                "avoid_strategies": ["Buying dips", "Averaging down"],
                "sector_focus": "Cash, Bonds, Inverse ETFs",
                "risk_tolerance": "Very low - preserve capital"
            }
        }
        return implications.get(state, implications[MarketState.HOLD])
    
    # === Data Fetching Methods ===
    
    async def _get_historical_bars(self, symbol: str, limit: int = 200) -> List[Dict]:
        """Get historical daily bars from unified ib_historical_data (primary), then Alpaca or IB."""
        # Try unified MongoDB collection first (fastest)
        try:
            from database import get_database
            db = get_database()
            if db is not None:
                def _query_bars():
                    return list(db["ib_historical_data"].find(
                        {"symbol": symbol, "bar_size": "1 day"},
                        {"_id": 0}
                    ).sort("date", -1).limit(limit))
                
                bars = await asyncio.to_thread(_query_bars)
                
                if bars and len(bars) >= 20:
                    # Convert to expected format and reverse to chronological order
                    return [{
                        "timestamp": bar.get("date"),
                        "open": bar.get("open"),
                        "high": bar.get("high"),
                        "low": bar.get("low"),
                        "close": bar.get("close"),
                        "volume": bar.get("volume")
                    } for bar in reversed(bars)]
        except Exception as e:
            print(f"MongoDB bars error for {symbol}: {e}")
        
        # Fallback to Alpaca
        try:
            if self.alpaca_service:
                bars = await self.alpaca_service.get_bars(symbol, "1Day", limit)
                if bars:
                    return bars
        except Exception as e:
            print(f"Alpaca bars error for {symbol}: {e}")
        
        # Fallback to IB if available
        try:
            if self.ib_service:
                bars = await self.ib_service.get_historical_data(symbol, "1D", limit)
                if bars:
                    return bars
        except Exception as e:
            print(f"IB bars error for {symbol}: {e}")
        
        return []
    
    async def _daily_change_from_bars(self, symbol: str) -> Dict:
        """Compute (price, change_pct) from the two most recent cached daily bars.

        IB-only fallback used when Alpaca is disabled. Uses `self.db` (the handle
        the engine is actually constructed with) first — the module-level
        get_database() returns None in this runtime, which is why breadth
        previously flatlined to zero — then get_database(), then the IB service.
        """
        # Prefer the injected handle (proven valid by FTD persistence).
        db = self.db
        if db is None:
            try:
                from database import get_database
                db = get_database()
            except Exception:
                db = None

        if db is not None:
            try:
                def _q():
                    return list(db["ib_historical_data"].find(
                        {"symbol": symbol, "bar_size": "1 day"},
                        {"_id": 0, "close": 1, "date": 1}
                    ).sort("date", -1).limit(2))
                rows = await asyncio.to_thread(_q)
                if len(rows) >= 2:
                    last_close = rows[0].get("close") or 0
                    prev_close = rows[1].get("close") or 0
                    if prev_close:
                        return {
                            "price": last_close,
                            "change_pct": round((last_close - prev_close) / prev_close * 100, 2),
                        }
            except Exception as e:
                print(f"daily-change-from-bars mongo error for {symbol}: {e}")

        # IB fallback (same source the trend block already uses successfully).
        try:
            if self.ib_service:
                bars = await self.ib_service.get_historical_data(symbol, "1D", 3)
                if bars and len(bars) >= 2:
                    last_close = bars[-1].get("close") or 0
                    prev_close = bars[-2].get("close") or 0
                    if prev_close:
                        return {
                            "price": last_close,
                            "change_pct": round((last_close - prev_close) / prev_close * 100, 2),
                        }
        except Exception as e:
            print(f"daily-change-from-bars IB error for {symbol}: {e}")

        return {}

    async def _get_quote(self, symbol: str) -> Dict:
        """Get current quote with change percentage.

        IB-only deployment: Alpaca is disabled, so when it's unavailable we derive
        change_pct from the cached daily bars instead of returning zeros (which
        silently flatlined the breadth block). A realtime overlay is layered in
        Step 2 so the current day's change goes live like the charts.
        """
        try:
            if self.alpaca_service:
                quote = await self.alpaca_service.get_quote(symbol)
                if quote:
                    return {
                        "price": quote.get("price", quote.get("last", 0)),
                        "change_pct": quote.get("change_pct", quote.get("changePercent", 0)),
                        "rvol": quote.get("rvol", 1.0)
                    }
        except Exception as e:
            print(f"Quote error for {symbol}: {e}")

        # IB-only fallback: derive daily change from cached bars.
        derived = await self._daily_change_from_bars(symbol)
        if derived:
            return {"price": derived["price"], "change_pct": derived["change_pct"], "rvol": 1.0}

        return {"price": 0, "change_pct": 0, "rvol": 1.0}
    
    async def _get_vix_data(self) -> Dict:
        """Get VIX data from IB (primary) or estimate from volatility."""
        try:
            if self.ib_service:
                vix = self.ib_service.get_vix()
                if vix:
                    return {
                        "price": vix.get("price", vix.get("last", 20)),
                        "change_pct": vix.get("change_pct", vix.get("changePercent", 0))
                    }
        except Exception as e:
            print(f"VIX data error: {e}")
        
        # Default to neutral VIX if unavailable
        return {"price": 20, "change_pct": 0}
    
    async def _get_sector_data(self) -> Dict[str, Dict]:
        """Get sector ETF data for breadth analysis.

        IB-only deployment: when Alpaca batch quotes are unavailable, derive each
        sector's daily change from cached bars so breadth reflects real sector
        rotation instead of all-zeros.
        """
        sector_etfs = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLC", "XLY", "XLP", "XLU", "XLRE", "XLB"]
        sector_data = {}

        try:
            if self.alpaca_service:
                quotes = await self.alpaca_service.get_quotes_batch(sector_etfs)
                if quotes:
                    for symbol, quote in quotes.items():
                        sector_data[symbol] = {
                            "price": quote.get("price", quote.get("last", 0)),
                            "change_pct": quote.get("change_pct", quote.get("changePercent", 0))
                        }
                    return sector_data
        except Exception as e:
            print(f"Sector data error: {e}")

        # IB-only fallback: derive each sector's daily change from cached bars.
        for etf in sector_etfs:
            derived = await self._daily_change_from_bars(etf)
            if derived:
                sector_data[etf] = {"price": derived["price"], "change_pct": derived["change_pct"]}

        return sector_data
    
    async def _get_vold_ratio(self) -> float:
        """Get VOLD ratio from existing market indicators service."""
        try:
            from services.market_indicators import get_market_indicators_service
            indicators = get_market_indicators_service(self.alpaca_service, self.ib_service)
            vold_data = await indicators.calculate_vold_ratio()
            return vold_data.get("overall", {}).get("is_trend_day", False) and 2.0 or 1.0
        except Exception as e:
            print(f"VOLD ratio error: {e}")
            return 1.0
    
    # === MongoDB Storage Methods ===
    
    async def _store_regime(self, regime: Dict):
        """Store regime data in MongoDB for history tracking."""
        if self.db is None:
            return
        
        try:
            collection = self.db["market_regime_state"]
            
            # Store current state
            doc = {
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "timestamp": datetime.now(timezone.utc),
                "state": regime.get("state"),
                "composite_score": regime.get("composite_score"),
                "risk_level": regime.get("risk_level"),
                "confidence": regime.get("confidence"),
                "signal_blocks": regime.get("signal_blocks"),
                "multi_tf": regime.get("multi_tf"),
                "state_changed": regime.get("state_changed"),
                "previous_state": regime.get("previous_state")
            }
            
            # Also store FTD state separately for persistence
            ftd_collection = self.db["market_regime_ftd"]
            ftd_doc = self.ftd_block.get_state_for_storage()
            ftd_doc["updated_at"] = datetime.now(timezone.utc)
            
            def _write_regime():
                collection.update_one(
                    {"date": doc["date"]},
                    {"$set": doc},
                    upsert=True
                )
                ftd_collection.update_one(
                    {"_id": "current_ftd_state"},
                    {"$set": ftd_doc},
                    upsert=True
                )
            
            await asyncio.to_thread(_write_regime)
            
        except Exception as e:
            print(f"Error storing regime: {e}")
    
    async def _load_ftd_state(self) -> Dict:
        """Load FTD state from MongoDB."""
        if self.db is None:
            return {}
        
        try:
            collection = self.db["market_regime_ftd"]
            def _query_ftd():
                return collection.find_one({"_id": "current_ftd_state"})
            doc = await asyncio.to_thread(_query_ftd)
            if doc:
                doc.pop("_id", None)
                doc.pop("updated_at", None)
                return doc
        except Exception as e:
            print(f"Error loading FTD state: {e}")
        
        return {}
    
    async def get_history(self, days: int = 30) -> List[Dict]:
        """Get regime history for the specified number of days."""
        if self.db is None:
            return []
        
        try:
            collection = self.db["market_regime_state"]
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            
            def _query_history():
                return list(collection.find(
                    {"timestamp": {"$gte": cutoff}},
                    {"_id": 0}
                ).sort("timestamp", -1))
            
            return await asyncio.to_thread(_query_history)
        except Exception as e:
            print(f"Error getting history: {e}")
            return []
    
    async def get_state_changes(self, days: int = 30) -> List[Dict]:
        """Get only the regime state changes for the specified period."""
        history = await self.get_history(days)
        return [h for h in history if h.get("state_changed")]


# Singleton instance
_market_regime_engine: Optional[MarketRegimeEngine] = None


def get_market_regime_engine(alpaca_service=None, ib_service=None, db=None) -> MarketRegimeEngine:
    """Get or create the market regime engine singleton."""
    global _market_regime_engine
    if _market_regime_engine is None:
        _market_regime_engine = MarketRegimeEngine(alpaca_service, ib_service, db)
    return _market_regime_engine
