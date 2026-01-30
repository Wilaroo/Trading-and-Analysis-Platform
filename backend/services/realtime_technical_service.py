"""
Real-Time Technical Analysis Service
Calculates live technical indicators from Alpaca bar data:
- VWAP, EMA (9, 20, 50, 200), RSI, RVOL, ATR
- Support/Resistance levels
- Gap percentage, price momentum
- Pattern detection

Provides the actual data needed for accurate alert detection.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import math

logger = logging.getLogger(__name__)


@dataclass
class TechnicalSnapshot:
    """Complete technical analysis snapshot for a symbol"""
    symbol: str
    timestamp: str
    
    # Price data
    current_price: float
    open: float
    high: float
    low: float
    prev_close: float
    
    # Volume analysis
    volume: int
    avg_volume: float
    rvol: float  # Relative volume
    
    # Moving averages
    vwap: float
    ema_9: float
    ema_20: float
    ema_50: float
    sma_200: float
    
    # Distance from key levels (as percentage)
    dist_from_vwap: float
    dist_from_ema9: float
    dist_from_ema20: float
    
    # Momentum indicators
    rsi_14: float
    rsi_trend: str  # "oversold", "neutral", "overbought"
    
    # Volatility
    atr: float
    atr_percent: float
    daily_range_pct: float
    
    # Gap analysis
    gap_pct: float
    gap_direction: str  # "up", "down", "flat"
    holding_gap: bool
    
    # Key levels
    resistance: float
    support: float
    high_of_day: float
    low_of_day: float
    
    # Position analysis
    above_vwap: bool
    above_ema9: bool
    above_ema20: bool
    trend: str  # "uptrend", "downtrend", "sideways"
    
    # Setup indicators
    extended_from_ema9: bool
    extension_pct: float
    
    # Source tracking
    bars_used: int
    data_quality: str  # "real", "partial", "estimated"


class RealTimeTechnicalService:
    """
    Service for calculating real-time technical indicators
    using actual market data from Alpaca.
    """
    
    def __init__(self):
        self._alpaca_service = None
        self._cache: Dict[str, TechnicalSnapshot] = {}
        self._cache_ttl = 30  # 30 second cache for technical data
        
    @property
    def alpaca(self):
        if self._alpaca_service is None:
            from services.alpaca_service import get_alpaca_service
            self._alpaca_service = get_alpaca_service()
        return self._alpaca_service
    
    async def get_technical_snapshot(self, symbol: str, force_refresh: bool = False) -> Optional[TechnicalSnapshot]:
        """
        Get comprehensive technical snapshot for a symbol.
        Uses real bar data from Alpaca to calculate all indicators.
        """
        symbol = symbol.upper()
        
        # Check cache
        if not force_refresh and symbol in self._cache:
            cached = self._cache[symbol]
            cache_age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached.timestamp.replace('Z', '+00:00'))).total_seconds()
            if cache_age < self._cache_ttl:
                return cached
        
        try:
            # Get intraday bars (5-min) for VWAP, EMA, intraday levels
            intraday_bars = await self.alpaca.get_bars(symbol, "5Min", 78)  # ~6.5 hours of data
            
            # Get daily bars for ATR, average volume, daily levels
            daily_bars = await self.alpaca.get_bars(symbol, "1Day", 50)
            
            # Get current quote
            quote = await self.alpaca.get_quote(symbol)
            
            if not quote or not daily_bars:
                logger.warning(f"Insufficient data for {symbol}")
                return None
            
            current_price = quote.get("price", 0)
            if current_price <= 0:
                return None
            
            # Calculate all indicators
            snapshot = self._calculate_snapshot(
                symbol=symbol,
                current_price=current_price,
                intraday_bars=intraday_bars,
                daily_bars=daily_bars,
                quote=quote
            )
            
            # Cache the result
            self._cache[symbol] = snapshot
            
            return snapshot
            
        except Exception as e:
            logger.error(f"Error calculating technicals for {symbol}: {e}")
            return None
    
    def _calculate_snapshot(
        self,
        symbol: str,
        current_price: float,
        intraday_bars: List[Dict],
        daily_bars: List[Dict],
        quote: Dict
    ) -> TechnicalSnapshot:
        """Calculate all technical indicators from bar data"""
        
        # === DAILY DATA ANALYSIS ===
        if daily_bars:
            # Previous close
            prev_close = daily_bars[-2]["close"] if len(daily_bars) >= 2 else daily_bars[-1]["open"]
            
            # Today's OHLC
            today = daily_bars[-1]
            open_price = today["open"]
            high_of_day = today["high"]
            low_of_day = today["low"]
            daily_volume = today["volume"]
            
            # Calculate average volume (20-day)
            volumes = [bar["volume"] for bar in daily_bars[-21:-1]] if len(daily_bars) > 21 else [bar["volume"] for bar in daily_bars[:-1]]
            avg_volume = sum(volumes) / len(volumes) if volumes else daily_volume
            
            # RVOL (Relative Volume)
            rvol = daily_volume / avg_volume if avg_volume > 0 else 1.0
            
            # Calculate ATR (14-period)
            atr = self._calculate_atr(daily_bars, 14)
            atr_percent = (atr / current_price) * 100 if current_price > 0 else 0
            
            # Gap calculation
            gap_pct = ((open_price - prev_close) / prev_close) * 100 if prev_close > 0 else 0
            gap_direction = "up" if gap_pct > 0.5 else "down" if gap_pct < -0.5 else "flat"
            holding_gap = current_price > prev_close if gap_pct > 0 else current_price < prev_close if gap_pct < 0 else True
            
            # Calculate SMAs/EMAs from daily data
            ema_50 = self._calculate_ema([bar["close"] for bar in daily_bars], 50)
            sma_200 = self._calculate_sma([bar["close"] for bar in daily_bars], 200)
            
            # Support/Resistance from daily data
            resistance, support = self._calculate_sr_levels(daily_bars[-20:])
            
        else:
            # Fallback values
            prev_close = current_price * 0.99
            open_price = current_price
            high_of_day = current_price * 1.01
            low_of_day = current_price * 0.99
            daily_volume = 0
            avg_volume = 1000000
            rvol = 1.0
            atr = current_price * 0.02
            atr_percent = 2.0
            gap_pct = 0
            gap_direction = "flat"
            holding_gap = True
            ema_50 = current_price
            sma_200 = current_price
            resistance = current_price * 1.03
            support = current_price * 0.97
        
        # === INTRADAY DATA ANALYSIS ===
        if intraday_bars and len(intraday_bars) >= 5:
            # Calculate intraday VWAP
            vwap = self._calculate_vwap(intraday_bars)
            
            # Calculate short-term EMAs from intraday data
            closes = [bar["close"] for bar in intraday_bars]
            ema_9 = self._calculate_ema(closes, 9)
            ema_20 = self._calculate_ema(closes, 20)
            
            # Calculate RSI from intraday closes
            rsi_14 = self._calculate_rsi(closes, 14)
            
            # Update high/low of day if intraday data is more recent
            intraday_high = max(bar["high"] for bar in intraday_bars)
            intraday_low = min(bar["low"] for bar in intraday_bars)
            high_of_day = max(high_of_day, intraday_high)
            low_of_day = min(low_of_day, intraday_low)
            
            data_quality = "real"
            bars_used = len(intraday_bars)
            
        else:
            # Use estimates from daily data
            vwap = current_price * 0.998
            ema_9 = current_price * 0.99
            ema_20 = current_price * 0.985
            rsi_14 = 50
            data_quality = "partial" if daily_bars else "estimated"
            bars_used = len(daily_bars) if daily_bars else 0
        
        # === CALCULATED METRICS ===
        
        # Distance from key levels
        dist_from_vwap = ((current_price - vwap) / vwap) * 100 if vwap > 0 else 0
        dist_from_ema9 = ((current_price - ema_9) / ema_9) * 100 if ema_9 > 0 else 0
        dist_from_ema20 = ((current_price - ema_20) / ema_20) * 100 if ema_20 > 0 else 0
        
        # Position analysis
        above_vwap = current_price > vwap
        above_ema9 = current_price > ema_9
        above_ema20 = current_price > ema_20
        
        # Trend determination
        if above_ema9 and above_ema20 and ema_9 > ema_20:
            trend = "uptrend"
        elif not above_ema9 and not above_ema20 and ema_9 < ema_20:
            trend = "downtrend"
        else:
            trend = "sideways"
        
        # Extension analysis (for rubber band setups)
        extended_from_ema9 = abs(dist_from_ema9) > 2.0
        
        # RSI interpretation
        if rsi_14 < 30:
            rsi_trend = "oversold"
        elif rsi_14 > 70:
            rsi_trend = "overbought"
        else:
            rsi_trend = "neutral"
        
        # Daily range
        daily_range_pct = ((high_of_day - low_of_day) / low_of_day) * 100 if low_of_day > 0 else 0
        
        return TechnicalSnapshot(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc).isoformat(),
            current_price=round(current_price, 2),
            open=round(open_price, 2),
            high=round(high_of_day, 2),
            low=round(low_of_day, 2),
            prev_close=round(prev_close, 2),
            volume=daily_volume,
            avg_volume=round(avg_volume),
            rvol=round(rvol, 2),
            vwap=round(vwap, 2),
            ema_9=round(ema_9, 2),
            ema_20=round(ema_20, 2),
            ema_50=round(ema_50, 2),
            sma_200=round(sma_200, 2),
            dist_from_vwap=round(dist_from_vwap, 2),
            dist_from_ema9=round(dist_from_ema9, 2),
            dist_from_ema20=round(dist_from_ema20, 2),
            rsi_14=round(rsi_14, 1),
            rsi_trend=rsi_trend,
            atr=round(atr, 2),
            atr_percent=round(atr_percent, 2),
            daily_range_pct=round(daily_range_pct, 2),
            gap_pct=round(gap_pct, 2),
            gap_direction=gap_direction,
            holding_gap=holding_gap,
            resistance=round(resistance, 2),
            support=round(support, 2),
            high_of_day=round(high_of_day, 2),
            low_of_day=round(low_of_day, 2),
            above_vwap=above_vwap,
            above_ema9=above_ema9,
            above_ema20=above_ema20,
            trend=trend,
            extended_from_ema9=extended_from_ema9,
            extension_pct=round(dist_from_ema9, 2),
            bars_used=bars_used,
            data_quality=data_quality
        )
    
    def _calculate_vwap(self, bars: List[Dict]) -> float:
        """Calculate VWAP from bar data"""
        if not bars:
            return 0
        
        total_volume = 0
        total_vp = 0
        
        for bar in bars:
            typical_price = (bar["high"] + bar["low"] + bar["close"]) / 3
            volume = bar["volume"]
            total_vp += typical_price * volume
            total_volume += volume
        
        return total_vp / total_volume if total_volume > 0 else bars[-1]["close"]
    
    def _calculate_ema(self, prices: List[float], period: int) -> float:
        """Calculate EMA from price list"""
        if not prices or len(prices) < period:
            return prices[-1] if prices else 0
        
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period  # Start with SMA
        
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    def _calculate_sma(self, prices: List[float], period: int) -> float:
        """Calculate SMA from price list"""
        if not prices:
            return 0
        if len(prices) < period:
            return sum(prices) / len(prices)
        return sum(prices[-period:]) / period
    
    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Calculate RSI from price list"""
        if len(prices) < period + 1:
            return 50  # Neutral default
        
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        if len(gains) < period:
            return 50
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _calculate_atr(self, bars: List[Dict], period: int = 14) -> float:
        """Calculate ATR from daily bars"""
        if len(bars) < 2:
            return 0
        
        true_ranges = []
        for i in range(1, len(bars)):
            high = bars[i]["high"]
            low = bars[i]["low"]
            prev_close = bars[i-1]["close"]
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        if len(true_ranges) < period:
            return sum(true_ranges) / len(true_ranges) if true_ranges else 0
        
        return sum(true_ranges[-period:]) / period
    
    def _calculate_sr_levels(self, bars: List[Dict]) -> Tuple[float, float]:
        """Calculate support and resistance from recent bars"""
        if not bars:
            return (0, 0)
        
        highs = [bar["high"] for bar in bars]
        lows = [bar["low"] for bar in bars]
        
        # Simple approach: recent high/low as R/S
        resistance = max(highs)
        support = min(lows)
        
        return (resistance, support)
    
    async def get_batch_snapshots(self, symbols: List[str]) -> Dict[str, TechnicalSnapshot]:
        """Get technical snapshots for multiple symbols"""
        results = {}
        
        for symbol in symbols:
            snapshot = await self.get_technical_snapshot(symbol)
            if snapshot:
                results[symbol] = snapshot
        
        return results
    
    def snapshot_to_dict(self, snapshot: TechnicalSnapshot) -> Dict[str, Any]:
        """Convert snapshot to dictionary for API response"""
        return {
            "symbol": snapshot.symbol,
            "timestamp": snapshot.timestamp,
            "price": {
                "current": snapshot.current_price,
                "open": snapshot.open,
                "high": snapshot.high,
                "low": snapshot.low,
                "prev_close": snapshot.prev_close
            },
            "volume": {
                "current": snapshot.volume,
                "average": snapshot.avg_volume,
                "rvol": snapshot.rvol
            },
            "moving_averages": {
                "vwap": snapshot.vwap,
                "ema_9": snapshot.ema_9,
                "ema_20": snapshot.ema_20,
                "ema_50": snapshot.ema_50,
                "sma_200": snapshot.sma_200
            },
            "distances": {
                "from_vwap": snapshot.dist_from_vwap,
                "from_ema9": snapshot.dist_from_ema9,
                "from_ema20": snapshot.dist_from_ema20
            },
            "momentum": {
                "rsi": snapshot.rsi_14,
                "rsi_trend": snapshot.rsi_trend
            },
            "volatility": {
                "atr": snapshot.atr,
                "atr_percent": snapshot.atr_percent,
                "daily_range_pct": snapshot.daily_range_pct
            },
            "gap": {
                "percent": snapshot.gap_pct,
                "direction": snapshot.gap_direction,
                "holding": snapshot.holding_gap
            },
            "levels": {
                "resistance": snapshot.resistance,
                "support": snapshot.support,
                "high_of_day": snapshot.high_of_day,
                "low_of_day": snapshot.low_of_day
            },
            "position": {
                "above_vwap": snapshot.above_vwap,
                "above_ema9": snapshot.above_ema9,
                "above_ema20": snapshot.above_ema20,
                "trend": snapshot.trend
            },
            "setup_indicators": {
                "extended_from_ema9": snapshot.extended_from_ema9,
                "extension_pct": snapshot.extension_pct
            },
            "data_quality": snapshot.data_quality,
            "bars_used": snapshot.bars_used
        }
    
    def get_snapshot_for_ai(self, snapshot: TechnicalSnapshot) -> str:
        """Format snapshot as context for AI assistant"""
        return f"""
=== TECHNICAL SNAPSHOT: {snapshot.symbol} ===
Price: ${snapshot.current_price} (Open: ${snapshot.open}, H: ${snapshot.high}, L: ${snapshot.low})
Change from prev close: {((snapshot.current_price - snapshot.prev_close) / snapshot.prev_close * 100):.1f}%

VOLUME:
- Today: {snapshot.volume:,} | Avg: {snapshot.avg_volume:,.0f}
- RVOL: {snapshot.rvol:.1f}x {"🔥 HIGH" if snapshot.rvol >= 2 else "📊 Normal" if snapshot.rvol >= 1 else "⚠️ Low"}

KEY LEVELS:
- VWAP: ${snapshot.vwap} ({snapshot.dist_from_vwap:+.1f}% {"above" if snapshot.above_vwap else "below"})
- EMA 9: ${snapshot.ema_9} ({snapshot.dist_from_ema9:+.1f}%)
- EMA 20: ${snapshot.ema_20} ({snapshot.dist_from_ema20:+.1f}%)
- Resistance: ${snapshot.resistance} | Support: ${snapshot.support}

INDICATORS:
- RSI(14): {snapshot.rsi_14:.0f} ({snapshot.rsi_trend})
- ATR: ${snapshot.atr} ({snapshot.atr_percent:.1f}%)
- Trend: {snapshot.trend.upper()}

GAP: {snapshot.gap_pct:+.1f}% ({snapshot.gap_direction}) {"✓ Holding" if snapshot.holding_gap else "✗ Failed"}

SETUP STATUS:
- Extended from EMA9: {"YES" if snapshot.extended_from_ema9 else "No"} ({snapshot.extension_pct:+.1f}%)
- Position: {"Bullish (above key MAs)" if snapshot.above_vwap and snapshot.above_ema9 else "Bearish (below key MAs)" if not snapshot.above_vwap and not snapshot.above_ema9 else "Mixed"}
"""


# Global instance
_technical_service: Optional[RealTimeTechnicalService] = None


def get_technical_service() -> RealTimeTechnicalService:
    """Get or create the technical service"""
    global _technical_service
    if _technical_service is None:
        _technical_service = RealTimeTechnicalService()
    return _technical_service
