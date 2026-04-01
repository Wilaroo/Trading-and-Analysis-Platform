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
from typing import Optional, Dict, List, Tuple, Any
from enum import Enum
import statistics
import math


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
    """
    
    def __init__(self):
        super().__init__("trend", 0.35)
    
    async def calculate(self, spy_bars: List[Dict], qqq_bars: List[Dict] = None) -> float:
        """
        Calculate trend score from SPY price data.
        
        Indicators:
        - SPY vs 21 EMA (20 pts)
        - SPY vs 50 SMA (20 pts)
        - SPY vs 200 SMA (15 pts)
        - 21 EMA vs 50 SMA alignment (15 pts)
        - Higher highs/lows pattern (30 pts)
        """
        if not spy_bars or len(spy_bars) < 200:
            self.score = 50  # Neutral if insufficient data
            self.signals = {"error": "Insufficient data for trend analysis"}
            return self.score
        
        closes = [bar.get("close", bar.get("c", 0)) for bar in spy_bars]
        highs = [bar.get("high", bar.get("h", 0)) for bar in spy_bars]
        lows = [bar.get("low", bar.get("l", 0)) for bar in spy_bars]
        
        current_price = closes[-1]
        
        # Calculate EMAs and SMAs
        ema_21 = self._calculate_ema(closes, 21)
        sma_50 = self._calculate_sma(closes, 50)
        sma_200 = self._calculate_sma(closes, 200)
        
        # Signal calculations
        above_21_ema = current_price > ema_21
        above_50_sma = current_price > sma_50
        above_200_sma = current_price > sma_200
        ema_above_sma = ema_21 > sma_50
        
        # Higher highs / higher lows analysis (last 20 bars)
        hh_hl_score = self._analyze_price_structure(highs[-20:], lows[-20:])
        
        # Calculate score
        score = 0
        score += 20 if above_21_ema else 0
        score += 20 if above_50_sma else 0
        score += 15 if above_200_sma else 0
        score += 15 if ema_above_sma else 0
        score += hh_hl_score * 30 / 100  # Normalize to 30 pts max
        
        self.score = round(score, 1)
        self.signals = {
            "current_price": round(current_price, 2),
            "ema_21": round(ema_21, 2),
            "sma_50": round(sma_50, 2),
            "sma_200": round(sma_200, 2),
            "above_21_ema": above_21_ema,
            "above_50_sma": above_50_sma,
            "above_200_sma": above_200_sma,
            "ema_above_sma": ema_above_sma,
            "price_structure_score": round(hh_hl_score, 1),
            "trend_direction": "BULLISH" if score >= 60 else "BEARISH" if score <= 40 else "NEUTRAL"
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
        
        # Check for distribution day
        if daily_change_pct <= -self.DISTRIBUTION_MIN_LOSS and volume_increased:
            self.distribution_days.append({
                "date": datetime.now(timezone.utc).isoformat(),
                "change_pct": round(daily_change_pct, 2),
                "volume_ratio": round(today_volume / yesterday_volume, 2) if yesterday_volume > 0 else 1
            })
            # Keep only last 25 trading days
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
    
    # Score thresholds for state determination
    CONFIRMED_UP_THRESHOLD = 70
    CONFIRMED_DOWN_THRESHOLD = 50
    
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
        qqq_bars = await self._get_historical_bars("QQQ", 50)
        # IWM bars fetched via quote for change calculation
        
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
        await self.trend_block.calculate(spy_bars, qqq_bars)
        
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
            "recommendation": recommendation,
            "trading_implications": self._get_trading_implications(new_state),
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
    
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
    
    async def _get_quote(self, symbol: str) -> Dict:
        """Get current quote with change percentage."""
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
        """Get sector ETF data for breadth analysis."""
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
        except Exception as e:
            print(f"Sector data error: {e}")
        
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
