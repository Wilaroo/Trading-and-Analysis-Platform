"""
Market Indicators Service
Advanced market-wide and stock-specific indicators based on SMB/ThinkOrSwim studies.

Includes:
1. VOLD Ratio - Market breadth indicator for trend day detection
2. 5 ATR Over-Extension Bands - Identify over-extended price territory
3. Volume Threshold Study - Standard deviation-based significant volume detection
4. Market Regime Classification - 4 regime model based on strength/weakness

These indicators apply to ALL timeframes (Scalp, Intraday, Swing, Position)
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Tuple
import math
import statistics


class MarketIndicatorsService:
    """
    Advanced market indicators for trading analysis.
    Based on SMB Trading and ThinkOrSwim studies.
    """
    
    # VOLD threshold for trend day detection (from user's ToS study)
    VOLD_TREND_THRESHOLD = 2.618
    
    # ATR multiplier for over-extension bands
    ATR_EXTENSION_FACTOR = 5
    ATR_PERIOD = 20
    
    # Volume threshold standard deviations
    VOLUME_STDEV_THRESHOLD = 2.0
    
    def __init__(self, alpaca_service=None, ib_service=None):
        self.alpaca_service = alpaca_service
        self.ib_service = ib_service
        self._cache = {}
        self._cache_ttl = 60  # 1 minute cache for market-wide indicators
    
    # ==================== VOLD RATIO (Market Breadth) ====================
    
    async def calculate_vold_ratio(self) -> Dict:
        """
        Calculate VOLD Ratio for NYSE and NASDAQ
        
        VOLD Ratio compares total volume of advancing stocks vs declining stocks.
        - If VOLD > 2.618 in first 30-60 min = Strong trend day (bullish)
        - If VOLD < -2.618 = Strong trend day (bearish)
        - Between -2.618 and 2.618 = Range/chop day
        
        This is critical for determining if it's a "trend day" where momentum
        strategies work vs a "range day" where mean reversion works better.
        
        Note: We use market index proxies since direct $UVOL/$DVOL requires
        specific data feeds. SPY/QQQ volume and direction can approximate this.
        """
        try:
            # Get market ETF data to approximate breadth
            spy_data = await self._get_market_proxy_data("SPY")
            qqq_data = await self._get_market_proxy_data("QQQ")
            iwm_data = await self._get_market_proxy_data("IWM")  # Russell 2000
            
            # Calculate directional volume proxy
            nyse_ratio = self._calc_directional_volume_ratio(spy_data, iwm_data)
            nasdaq_ratio = self._calc_directional_volume_ratio(qqq_data)
            
            # Determine trend day status
            is_nyse_trend_day = abs(nyse_ratio) >= self.VOLD_TREND_THRESHOLD
            is_nasdaq_trend_day = abs(nasdaq_ratio) >= self.VOLD_TREND_THRESHOLD
            is_trend_day = is_nyse_trend_day or is_nasdaq_trend_day
            
            # Overall market direction
            if nyse_ratio >= self.VOLD_TREND_THRESHOLD and nasdaq_ratio >= self.VOLD_TREND_THRESHOLD:
                market_direction = "STRONG_BULLISH"
                market_bias = "LONG"
            elif nyse_ratio <= -self.VOLD_TREND_THRESHOLD and nasdaq_ratio <= -self.VOLD_TREND_THRESHOLD:
                market_direction = "STRONG_BEARISH"
                market_bias = "SHORT"
            elif nyse_ratio > 0 and nasdaq_ratio > 0:
                market_direction = "BULLISH"
                market_bias = "LONG"
            elif nyse_ratio < 0 and nasdaq_ratio < 0:
                market_direction = "BEARISH"
                market_bias = "SHORT"
            else:
                market_direction = "MIXED"
                market_bias = "NEUTRAL"
            
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "nyse": {
                    "vold_ratio": round(nyse_ratio, 2),
                    "is_trend_day": is_nyse_trend_day,
                    "direction": "BULLISH" if nyse_ratio > 0 else "BEARISH" if nyse_ratio < 0 else "NEUTRAL"
                },
                "nasdaq": {
                    "vold_ratio": round(nasdaq_ratio, 2),
                    "is_trend_day": is_nasdaq_trend_day,
                    "direction": "BULLISH" if nasdaq_ratio > 0 else "BEARISH" if nasdaq_ratio < 0 else "NEUTRAL"
                },
                "overall": {
                    "is_trend_day": is_trend_day,
                    "market_direction": market_direction,
                    "market_bias": market_bias,
                    "threshold": self.VOLD_TREND_THRESHOLD,
                    "recommendation": self._get_vold_recommendation(is_trend_day, market_direction)
                }
            }
        except Exception as e:
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
                "nyse": {"vold_ratio": 0, "is_trend_day": False},
                "nasdaq": {"vold_ratio": 0, "is_trend_day": False},
                "overall": {"is_trend_day": False, "market_direction": "UNKNOWN", "market_bias": "NEUTRAL"}
            }
    
    async def _get_market_proxy_data(self, symbol: str) -> Dict:
        """Get intraday data for market proxy ETF"""
        try:
            if self.alpaca_service:
                bars = await self.alpaca_service.get_bars(symbol, "5Min", 78)  # ~6.5 hours of 5-min bars
                if bars:
                    return {
                        "symbol": symbol,
                        "bars": bars,
                        "current_price": bars[-1].get("close", 0) if bars else 0,
                        "open_price": bars[0].get("open", 0) if bars else 0,
                        "volume": sum(b.get("volume", 0) for b in bars),
                        "change_pct": ((bars[-1].get("close", 0) - bars[0].get("open", 0)) / bars[0].get("open", 1)) * 100 if bars else 0
                    }
        except Exception as e:
            pass
        return {"symbol": symbol, "bars": [], "current_price": 0, "volume": 0, "change_pct": 0}
    
    def _calc_directional_volume_ratio(self, primary_data: Dict, secondary_data: Dict = None) -> float:
        """
        Calculate directional volume ratio from ETF data
        Approximates VOLD by looking at volume weighted by price direction
        """
        if not primary_data.get("bars"):
            return 0.0
        
        bars = primary_data["bars"]
        up_volume = 0
        down_volume = 0
        
        for bar in bars:
            vol = bar.get("volume", 0)
            open_price = bar.get("open", 0)
            close_price = bar.get("close", 0)
            
            if close_price > open_price:
                up_volume += vol
            elif close_price < open_price:
                down_volume += vol
            else:
                # Split evenly for doji bars
                up_volume += vol / 2
                down_volume += vol / 2
        
        # Blend with secondary data if available
        if secondary_data and secondary_data.get("bars"):
            sec_bars = secondary_data["bars"]
            for bar in sec_bars:
                vol = bar.get("volume", 0) * 0.3  # Weight secondary at 30%
                if bar.get("close", 0) > bar.get("open", 0):
                    up_volume += vol
                else:
                    down_volume += vol
        
        # Calculate ratio similar to ToS VOLD study
        if up_volume >= down_volume and down_volume > 0:
            return up_volume / down_volume
        elif down_volume > up_volume and up_volume > 0:
            return -(down_volume / up_volume)
        elif up_volume > 0:
            return up_volume / 1000000  # Large positive
        elif down_volume > 0:
            return -(down_volume / 1000000)  # Large negative
        return 0.0
    
    def _get_vold_recommendation(self, is_trend_day: bool, direction: str) -> str:
        """Get trading recommendation based on VOLD analysis"""
        if is_trend_day:
            if "BULLISH" in direction:
                return "TREND DAY - Favor momentum longs, buy dips, avoid shorting strength"
            elif "BEARISH" in direction:
                return "TREND DAY - Favor momentum shorts, sell rallies, avoid buying weakness"
            else:
                return "TREND DAY - Follow the dominant direction, let winners run"
        else:
            return "RANGE DAY - Favor mean reversion, fade extremes, take profits quickly"
    
    # ==================== 5 ATR OVER-EXTENSION BANDS ====================
    
    def calculate_atr_extension_bands(self, daily_bars: List[Dict], 
                                       atr_factor: int = 5, 
                                       atr_length: int = 20) -> Dict:
        """
        Calculate 5 ATR Over-Extension Bands
        
        Based on ToS Study: Bands plotted from 5-day high/low extended by 5 ATRs.
        Identifies when a stock is in over-extended territory.
        
        - Price above high_band = Over-extended to upside (caution on longs)
        - Price below low_band = Over-extended to downside (caution on shorts)
        - Price between bands = Normal trading range
        
        Args:
            daily_bars: List of daily OHLCV bars (oldest first)
            atr_factor: Number of ATRs for extension (default 5)
            atr_length: Period for ATR calculation (default 20)
        
        Returns:
            Dict with bands, ATR, and extension status
        """
        if len(daily_bars) < max(5, atr_length):
            return {
                "atr": 0,
                "high_band": 0,
                "low_band": 0,
                "is_over_extended": False,
                "extension_direction": "NONE",
                "error": "Insufficient data"
            }
        
        # Get last 5 days for high/low
        last_5_bars = daily_bars[-5:]
        five_day_high = max(bar.get("high", 0) for bar in last_5_bars)
        five_day_low = min(bar.get("low", float('inf')) for bar in last_5_bars)
        
        # Calculate ATR
        atr = self._calculate_atr(daily_bars, atr_length)
        atr_shift = atr_factor * atr
        
        # Calculate bands (from ToS formula)
        # low_band = 5-day high - (factor * ATR) -- support if coming down
        # high_band = 5-day low + (factor * ATR) -- resistance if going up
        low_band = five_day_high - atr_shift
        high_band = five_day_low + atr_shift
        
        # Current price
        current_price = daily_bars[-1].get("close", 0)
        
        # Determine extension status
        is_over_extended_high = current_price > high_band
        is_over_extended_low = current_price < low_band
        is_over_extended = is_over_extended_high or is_over_extended_low
        
        if is_over_extended_high:
            extension_direction = "OVER_EXTENDED_UP"
            extension_pct = ((current_price - high_band) / high_band) * 100 if high_band > 0 else 0
            recommendation = "CAUTION: Over-extended to upside. Consider taking profits on longs, avoid chasing."
        elif is_over_extended_low:
            extension_direction = "OVER_EXTENDED_DOWN"
            extension_pct = ((low_band - current_price) / low_band) * 100 if low_band > 0 else 0
            recommendation = "CAUTION: Over-extended to downside. Consider taking profits on shorts, avoid panic selling."
        else:
            extension_direction = "NORMAL"
            # Calculate how close to bands
            dist_to_high = high_band - current_price
            dist_to_low = current_price - low_band
            if dist_to_high < dist_to_low:
                extension_pct = (dist_to_high / atr_shift) * 100 if atr_shift > 0 else 0
                recommendation = f"Approaching upper extension band. {extension_pct:.1f}% room before over-extended."
            else:
                extension_pct = (dist_to_low / atr_shift) * 100 if atr_shift > 0 else 0
                recommendation = f"Approaching lower extension band. {extension_pct:.1f}% room before over-extended."
        
        return {
            "atr": round(atr, 2),
            "atr_factor": atr_factor,
            "atr_length": atr_length,
            "five_day_high": round(five_day_high, 2),
            "five_day_low": round(five_day_low, 2),
            "high_band": round(high_band, 2),
            "low_band": round(low_band, 2),
            "current_price": round(current_price, 2),
            "is_over_extended": is_over_extended,
            "extension_direction": extension_direction,
            "extension_pct": round(abs(extension_pct), 2) if is_over_extended else 0,
            "recommendation": recommendation
        }
    
    def _calculate_atr(self, bars: List[Dict], period: int = 14) -> float:
        """Calculate Average True Range"""
        if len(bars) < period + 1:
            return 0.0
        
        true_ranges = []
        for i in range(1, len(bars)):
            high = bars[i].get("high", 0)
            low = bars[i].get("low", 0)
            prev_close = bars[i-1].get("close", 0)
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        if len(true_ranges) < period:
            return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0
        
        # Wilder's smoothing (EMA-style)
        atr = sum(true_ranges[:period]) / period
        for tr in true_ranges[period:]:
            atr = (atr * (period - 1) + tr) / period
        
        return atr
    
    # ==================== VOLUME THRESHOLD STUDY ====================
    
    def calculate_volume_threshold(self, volume_bars: List[int], 
                                    current_volume: int,
                                    length: int = 20,
                                    std_dev_multiplier: float = 2.0) -> Dict:
        """
        Volume Threshold Study using Standard Deviation
        
        Based on ToS Study: Uses stdev to determine if current volume is significant.
        
        Formula:
            Average = SMA of volume over length
            Deviation = Average + (std_dev_multiplier * stdev)
            
        Interpretation:
            - Volume >= Deviation = SIGNIFICANT (magenta in ToS)
            - Volume < Average = LOW (gray in ToS)
            - Volume between = NORMAL (pink in ToS)
        
        Args:
            volume_bars: List of volume values (oldest first)
            current_volume: Current bar's volume
            length: Period for average/stdev (default 20)
            std_dev_multiplier: Number of standard deviations (default 2)
        
        Returns:
            Dict with threshold analysis
        """
        if len(volume_bars) < length:
            return {
                "average_volume": 0,
                "threshold": 0,
                "current_volume": current_volume,
                "volume_status": "INSUFFICIENT_DATA",
                "is_significant": False
            }
        
        # Calculate average and standard deviation
        recent_volume = volume_bars[-length:]
        avg_volume = sum(recent_volume) / length
        std_dev = statistics.stdev(recent_volume) if len(recent_volume) > 1 else 0
        
        # Calculate threshold (deviation)
        threshold = avg_volume + (std_dev_multiplier * std_dev)
        
        # Determine volume status
        if current_volume >= threshold:
            volume_status = "SIGNIFICANT"
            significance_level = "HIGH"
            color = "MAGENTA"
            interpretation = "Volume spike detected - potential catalyst or institutional activity"
        elif current_volume < avg_volume:
            volume_status = "LOW"
            significance_level = "LOW"
            color = "GRAY"
            interpretation = "Below average volume - potential consolidation or low interest"
        else:
            volume_status = "NORMAL"
            significance_level = "MEDIUM"
            color = "PINK"
            interpretation = "Normal volume - no significant deviation"
        
        # Calculate RVOL (relative volume)
        rvol = current_volume / avg_volume if avg_volume > 0 else 1.0
        
        # Calculate how many standard deviations above/below average
        z_score = (current_volume - avg_volume) / std_dev if std_dev > 0 else 0
        
        return {
            "average_volume": round(avg_volume, 0),
            "std_dev": round(std_dev, 0),
            "threshold": round(threshold, 0),
            "threshold_millions": round(threshold / 1000000, 2),
            "current_volume": current_volume,
            "volume_status": volume_status,
            "significance_level": significance_level,
            "color": color,
            "is_significant": volume_status == "SIGNIFICANT",
            "rvol": round(rvol, 2),
            "z_score": round(z_score, 2),
            "interpretation": interpretation
        }
    
    # ==================== MARKET REGIME CLASSIFICATION ====================
    
    def classify_market_regime(self, vold_data: Dict, 
                                spy_change: float = 0,
                                vix_level: float = 0) -> Dict:
        """
        Classify market into one of 4 regimes based on strength/weakness.
        
        From your Market Context Best Practices document:
        - High Strength + High Momentum = AGGRESSIVE TRENDING
        - High Strength + Low Momentum = PASSIVE TRENDING
        - Low Strength + High Volatility = VOLATILE RANGE
        - Low Strength + Low Volatility = QUIET CONSOLIDATION
        
        This determines which setups to favor:
        - AGGRESSIVE TRENDING: Momentum breakouts, trend following
        - PASSIVE TRENDING: Pullback entries, gradual position building
        - VOLATILE RANGE: Mean reversion, fade extremes
        - QUIET CONSOLIDATION: Wait for breakout, reduce position size
        """
        is_trend_day = vold_data.get("overall", {}).get("is_trend_day", False)
        market_direction = vold_data.get("overall", {}).get("market_direction", "MIXED")
        vold_nyse = abs(vold_data.get("nyse", {}).get("vold_ratio", 0))
        vold_nasdaq = abs(vold_data.get("nasdaq", {}).get("vold_ratio", 0))
        
        # Determine strength (based on VOLD magnitude)
        avg_vold = (vold_nyse + vold_nasdaq) / 2
        is_high_strength = avg_vold >= self.VOLD_TREND_THRESHOLD
        
        # Determine momentum (based on price change and VIX)
        is_high_momentum = abs(spy_change) >= 0.5 or (vix_level > 0 and vix_level > 20)
        
        # Classify regime
        if is_high_strength and is_high_momentum:
            regime = "AGGRESSIVE_TRENDING"
            regime_description = "Strong directional movement with high volatility"
            favored_setups = ["Momentum breakouts", "Trend continuation", "ABCD patterns", "Flag breakouts"]
            avoid_setups = ["Mean reversion", "Counter-trend fades", "Range plays"]
            position_sizing = "Normal to aggressive sizing, let winners run"
        elif is_high_strength and not is_high_momentum:
            regime = "PASSIVE_TRENDING"
            regime_description = "Strong direction but gradual movement"
            favored_setups = ["Pullback entries", "EMA bounces", "Consolidation breakouts", "Gradual scaling"]
            avoid_setups = ["Aggressive momentum chasing", "Extended entries"]
            position_sizing = "Normal sizing, scale in on pullbacks"
        elif not is_high_strength and is_high_momentum:
            regime = "VOLATILE_RANGE"
            regime_description = "Choppy action with high volatility swings"
            favored_setups = ["Mean reversion", "Fade extremes", "VWAP reversion", "RSI extremes"]
            avoid_setups = ["Breakout chasing", "Trend following", "Holding through swings"]
            position_sizing = "Reduced sizing, quick profits"
        else:
            regime = "QUIET_CONSOLIDATION"
            regime_description = "Low volume, tight range consolidation"
            favored_setups = ["Wait for breakout", "Reduce activity", "Build watchlist"]
            avoid_setups = ["Forcing trades", "Overtrading", "Large positions"]
            position_sizing = "Minimal sizing, preserve capital"
        
        return {
            "regime": regime,
            "regime_description": regime_description,
            "is_high_strength": is_high_strength,
            "is_high_momentum": is_high_momentum,
            "favored_setups": favored_setups,
            "avoid_setups": avoid_setups,
            "position_sizing": position_sizing,
            "market_direction": market_direction,
            "is_trend_day": is_trend_day,
            "inputs": {
                "avg_vold": round(avg_vold, 2),
                "spy_change": spy_change,
                "vix_level": vix_level
            }
        }
    
    # ==================== COMBINED ANALYSIS ====================
    
    async def get_full_market_analysis(self) -> Dict:
        """
        Get comprehensive market analysis including all indicators.
        Call this at market open and update throughout the day.
        """
        # Get VOLD analysis
        vold = await self.calculate_vold_ratio()
        
        # Get SPY data for regime classification
        spy_data = await self._get_market_proxy_data("SPY")
        spy_change = spy_data.get("change_pct", 0)
        
        # TODO: Add VIX data if available
        vix_level = 0
        
        # Classify regime
        regime = self.classify_market_regime(vold, spy_change, vix_level)
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "vold": vold,
            "regime": regime,
            "spy": {
                "change_pct": round(spy_change, 2),
                "direction": "UP" if spy_change > 0 else "DOWN" if spy_change < 0 else "FLAT"
            },
            "trading_guidance": {
                "is_trend_day": vold.get("overall", {}).get("is_trend_day", False),
                "market_bias": vold.get("overall", {}).get("market_bias", "NEUTRAL"),
                "regime": regime.get("regime", "UNKNOWN"),
                "recommendation": vold.get("overall", {}).get("recommendation", ""),
                "favored_setups": regime.get("favored_setups", []),
                "avoid_setups": regime.get("avoid_setups", [])
            }
        }
    
    def analyze_stock_extension(self, symbol: str, daily_bars: List[Dict], 
                                 intraday_volume: List[int] = None,
                                 current_volume: int = 0) -> Dict:
        """
        Analyze a specific stock for over-extension and volume significance.
        
        Args:
            symbol: Stock symbol
            daily_bars: Daily OHLCV bars
            intraday_volume: Optional list of intraday volume bars
            current_volume: Current bar's volume
        
        Returns:
            Dict with ATR extension and volume analysis
        """
        result = {
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # ATR Extension analysis
        if daily_bars:
            result["atr_extension"] = self.calculate_atr_extension_bands(daily_bars)
        else:
            result["atr_extension"] = {"error": "No daily bars provided"}
        
        # Volume threshold analysis
        if intraday_volume and current_volume > 0:
            result["volume_threshold"] = self.calculate_volume_threshold(
                intraday_volume, current_volume
            )
        elif daily_bars:
            # Use daily volume if intraday not available
            volume_history = [bar.get("volume", 0) for bar in daily_bars]
            current_vol = volume_history[-1] if volume_history else 0
            result["volume_threshold"] = self.calculate_volume_threshold(
                volume_history[:-1], current_vol
            )
        else:
            result["volume_threshold"] = {"error": "No volume data provided"}
        
        return result


# Singleton instance
_market_indicators_service = None

def get_market_indicators_service(alpaca_service=None, ib_service=None) -> MarketIndicatorsService:
    """Get or create the market indicators service singleton"""
    global _market_indicators_service
    if _market_indicators_service is None:
        _market_indicators_service = MarketIndicatorsService(alpaca_service, ib_service)
    return _market_indicators_service
