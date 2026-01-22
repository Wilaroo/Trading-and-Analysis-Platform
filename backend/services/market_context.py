"""
Market Context Analysis Service
Classifies stocks into: Trending, Consolidation (Range), or Mean Reversion
Based on Volume, ATR, Price Action, and Technical Indicators
"""
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Tuple
import math

class MarketContextService:
    """
    Analyzes market context for stocks to determine:
    - TRENDING: Clear directional movement with high volume
    - CONSOLIDATION: Range-bound with low volume and declining ATR
    - MEAN_REVERSION: Overextended price returning to mean
    """
    
    CONTEXT_TRENDING = "TRENDING"
    CONTEXT_CONSOLIDATION = "CONSOLIDATION"
    CONTEXT_MEAN_REVERSION = "MEAN_REVERSION"
    
    # Sub-classifications
    TRENDING_AGGRESSIVE = "AGGRESSIVE"  # High volatility, rapid movement
    TRENDING_PASSIVE = "PASSIVE"        # Low volatility, gradual movement
    
    def __init__(self, stock_service=None):
        self.stock_service = stock_service
        self._context_cache: Dict[str, Tuple[Dict, datetime]] = {}
        self._cache_ttl = 300  # 5 minutes
    
    def _check_cache(self, symbol: str) -> Optional[Dict]:
        """Check if cached context is still valid"""
        if symbol in self._context_cache:
            data, cached_time = self._context_cache[symbol]
            if (datetime.now(timezone.utc) - cached_time).total_seconds() < self._cache_ttl:
                return data
        return None
    
    def _set_cache(self, symbol: str, data: Dict):
        """Store context in cache"""
        self._context_cache[symbol] = (data, datetime.now(timezone.utc))
    
    def calculate_atr(self, high_prices: List[float], low_prices: List[float], 
                      close_prices: List[float], period: int = 14) -> float:
        """
        Calculate Average True Range (ATR)
        ATR = Average of True Range over period
        True Range = max(High-Low, |High-PrevClose|, |Low-PrevClose|)
        """
        if len(high_prices) < period + 1:
            return 0.0
        
        true_ranges = []
        for i in range(1, len(high_prices)):
            high = high_prices[i]
            low = low_prices[i]
            prev_close = close_prices[i-1]
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        if len(true_ranges) < period:
            return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0
        
        # Use EMA-style ATR calculation
        atr = sum(true_ranges[:period]) / period
        for tr in true_ranges[period:]:
            atr = (atr * (period - 1) + tr) / period
        
        return round(atr, 4)
    
    def calculate_atr_trend(self, high_prices: List[float], low_prices: List[float],
                           close_prices: List[float], period: int = 14) -> Dict:
        """
        Calculate ATR and its trend (rising/falling/flat)
        Used for consolidation detection
        """
        if len(high_prices) < period * 2:
            current_atr = self.calculate_atr(high_prices, low_prices, close_prices, period)
            return {
                "current_atr": current_atr,
                "previous_atr": current_atr,
                "atr_change_percent": 0,
                "atr_trend": "FLAT"
            }
        
        # Calculate current ATR (last 'period' bars)
        current_atr = self.calculate_atr(
            high_prices[-period-1:], 
            low_prices[-period-1:], 
            close_prices[-period-1:], 
            period
        )
        
        # Calculate previous ATR (period before current)
        mid_point = len(high_prices) - period
        previous_atr = self.calculate_atr(
            high_prices[mid_point-period-1:mid_point], 
            low_prices[mid_point-period-1:mid_point], 
            close_prices[mid_point-period-1:mid_point], 
            period
        )
        
        if previous_atr > 0:
            atr_change = ((current_atr - previous_atr) / previous_atr) * 100
        else:
            atr_change = 0
        
        # Determine trend
        if atr_change < -10:
            atr_trend = "DECLINING"  # Consolidation signal
        elif atr_change > 10:
            atr_trend = "RISING"     # Trending/Breakout signal
        else:
            atr_trend = "FLAT"
        
        return {
            "current_atr": round(current_atr, 4),
            "previous_atr": round(previous_atr, 4),
            "atr_change_percent": round(atr_change, 2),
            "atr_trend": atr_trend
        }
    
    def calculate_relative_volume(self, current_volume: int, avg_volume: int) -> float:
        """Calculate Relative Volume (RVOL)"""
        if avg_volume <= 0:
            return 1.0
        return round(current_volume / avg_volume, 2)
    
    def detect_price_range(self, high_prices: List[float], low_prices: List[float],
                          close_prices: List[float], lookback: int = 20) -> Dict:
        """
        Detect if price is in a defined range
        Returns range boundaries and range tightness
        """
        if len(high_prices) < lookback:
            lookback = len(high_prices)
        
        recent_highs = high_prices[-lookback:]
        recent_lows = low_prices[-lookback:]
        recent_closes = close_prices[-lookback:]
        
        range_high = max(recent_highs)
        range_low = min(recent_lows)
        range_size = range_high - range_low
        current_price = recent_closes[-1] if recent_closes else 0
        
        # Calculate range tightness (lower = tighter consolidation)
        avg_price = sum(recent_closes) / len(recent_closes)
        range_percent = (range_size / avg_price * 100) if avg_price > 0 else 0
        
        # Position within range (0 = at low, 1 = at high)
        if range_size > 0:
            position_in_range = (current_price - range_low) / range_size
        else:
            position_in_range = 0.5
        
        return {
            "range_high": round(range_high, 2),
            "range_low": round(range_low, 2),
            "range_size": round(range_size, 2),
            "range_percent": round(range_percent, 2),
            "current_price": round(current_price, 2),
            "position_in_range": round(position_in_range, 2),
            "is_tight_range": range_percent < 5  # Less than 5% range = tight
        }
    
    def calculate_trend_strength(self, close_prices: List[float], period: int = 20) -> Dict:
        """
        Calculate trend strength using price momentum and direction
        """
        if len(close_prices) < period:
            return {
                "trend_direction": "NEUTRAL",
                "trend_strength": 0,
                "price_change_percent": 0,
                "higher_highs": 0,
                "lower_lows": 0
            }
        
        recent_closes = close_prices[-period:]
        start_price = recent_closes[0]
        end_price = recent_closes[-1]
        
        # Price change over period
        price_change_pct = ((end_price - start_price) / start_price * 100) if start_price > 0 else 0
        
        # Count higher highs and lower lows (trend confirmation)
        higher_highs = 0
        lower_lows = 0
        for i in range(1, len(recent_closes)):
            if recent_closes[i] > recent_closes[i-1]:
                higher_highs += 1
            elif recent_closes[i] < recent_closes[i-1]:
                lower_lows += 1
        
        # Determine trend direction
        if price_change_pct > 3 and higher_highs > lower_lows:
            trend_direction = "BULLISH"
        elif price_change_pct < -3 and lower_lows > higher_highs:
            trend_direction = "BEARISH"
        else:
            trend_direction = "NEUTRAL"
        
        # Trend strength (0-100)
        consistency = abs(higher_highs - lower_lows) / period * 100
        trend_strength = min(100, abs(price_change_pct) * 5 + consistency)
        
        return {
            "trend_direction": trend_direction,
            "trend_strength": round(trend_strength, 1),
            "price_change_percent": round(price_change_pct, 2),
            "higher_highs": higher_highs,
            "lower_lows": lower_lows
        }
    
    def detect_mean_reversion_setup(self, close_prices: List[float], 
                                    high_prices: List[float], low_prices: List[float],
                                    period: int = 20) -> Dict:
        """
        Detect mean reversion conditions:
        - Price overextended from moving average
        - Gap scenarios
        - RSI extremes
        """
        if len(close_prices) < period:
            return {
                "is_overextended": False,
                "extension_percent": 0,
                "extension_direction": "NEUTRAL",
                "sma": 0,
                "distance_from_sma": 0
            }
        
        recent_closes = close_prices[-period:]
        current_price = recent_closes[-1]
        
        # Calculate SMA
        sma = sum(recent_closes) / len(recent_closes)
        
        # Calculate standard deviation for Bollinger-style analysis
        variance = sum((x - sma) ** 2 for x in recent_closes) / len(recent_closes)
        std_dev = math.sqrt(variance)
        
        # Distance from SMA in standard deviations
        if std_dev > 0:
            z_score = (current_price - sma) / std_dev
        else:
            z_score = 0
        
        # Extension percentage
        extension_pct = ((current_price - sma) / sma * 100) if sma > 0 else 0
        
        # Determine if overextended (more than 2 std devs or >5% from SMA)
        is_overextended = abs(z_score) > 2 or abs(extension_pct) > 5
        
        if extension_pct > 0:
            extension_direction = "ABOVE_MEAN"
        elif extension_pct < 0:
            extension_direction = "BELOW_MEAN"
        else:
            extension_direction = "AT_MEAN"
        
        return {
            "is_overextended": is_overextended,
            "extension_percent": round(extension_pct, 2),
            "extension_direction": extension_direction,
            "sma": round(sma, 2),
            "distance_from_sma": round(current_price - sma, 2),
            "z_score": round(z_score, 2),
            "std_dev": round(std_dev, 2)
        }
    
    def classify_market_context(self, 
                                rvol: float, 
                                atr_data: Dict, 
                                range_data: Dict,
                                trend_data: Dict,
                                mean_reversion_data: Dict) -> Dict:
        """
        Main classification logic for market context
        Returns context type and confidence score
        """
        scores = {
            self.CONTEXT_TRENDING: 0,
            self.CONTEXT_CONSOLIDATION: 0,
            self.CONTEXT_MEAN_REVERSION: 0
        }
        
        # === TRENDING SIGNALS ===
        # High RVOL is #1 indicator for trending
        if rvol >= 2.0:
            scores[self.CONTEXT_TRENDING] += 40
        elif rvol >= 1.5:
            scores[self.CONTEXT_TRENDING] += 25
        elif rvol >= 1.2:
            scores[self.CONTEXT_TRENDING] += 10
        
        # Strong trend direction
        if trend_data["trend_strength"] >= 60:
            scores[self.CONTEXT_TRENDING] += 30
        elif trend_data["trend_strength"] >= 40:
            scores[self.CONTEXT_TRENDING] += 15
        
        # Rising ATR supports trending
        if atr_data["atr_trend"] == "RISING":
            scores[self.CONTEXT_TRENDING] += 20
        
        # === CONSOLIDATION SIGNALS ===
        # Low volume
        if rvol < 0.8:
            scores[self.CONTEXT_CONSOLIDATION] += 30
        elif rvol < 1.0:
            scores[self.CONTEXT_CONSOLIDATION] += 15
        
        # Declining ATR is key consolidation indicator
        if atr_data["atr_trend"] == "DECLINING":
            scores[self.CONTEXT_CONSOLIDATION] += 35
        
        # Tight range
        if range_data["is_tight_range"]:
            scores[self.CONTEXT_CONSOLIDATION] += 25
        elif range_data["range_percent"] < 8:
            scores[self.CONTEXT_CONSOLIDATION] += 10
        
        # Neutral trend
        if trend_data["trend_direction"] == "NEUTRAL":
            scores[self.CONTEXT_CONSOLIDATION] += 15
        
        # === MEAN REVERSION SIGNALS ===
        # Overextended price
        if mean_reversion_data["is_overextended"]:
            scores[self.CONTEXT_MEAN_REVERSION] += 40
        
        # High z-score (far from mean)
        z_score = abs(mean_reversion_data.get("z_score", 0))
        if z_score > 2.5:
            scores[self.CONTEXT_MEAN_REVERSION] += 30
        elif z_score > 2.0:
            scores[self.CONTEXT_MEAN_REVERSION] += 20
        elif z_score > 1.5:
            scores[self.CONTEXT_MEAN_REVERSION] += 10
        
        # High volume with overextension suggests mean reversion coming
        if rvol >= 1.5 and mean_reversion_data["is_overextended"]:
            scores[self.CONTEXT_MEAN_REVERSION] += 20
        
        # Determine winner
        max_score = max(scores.values())
        if max_score == 0:
            primary_context = self.CONTEXT_CONSOLIDATION  # Default
            confidence = 50
        else:
            primary_context = max(scores, key=scores.get)
            total_score = sum(scores.values())
            confidence = int((max_score / total_score * 100)) if total_score > 0 else 50
        
        # Determine sub-classification for trending
        sub_type = None
        if primary_context == self.CONTEXT_TRENDING:
            if rvol >= 2.0 and atr_data["atr_change_percent"] > 15:
                sub_type = self.TRENDING_AGGRESSIVE
            else:
                sub_type = self.TRENDING_PASSIVE
        
        return {
            "primary_context": primary_context,
            "sub_type": sub_type,
            "confidence": confidence,
            "scores": scores,
            "recommended_styles": self._get_recommended_styles(primary_context, sub_type)
        }
    
    def _get_recommended_styles(self, context: str, sub_type: str = None) -> List[Dict]:
        """Get recommended trading styles for the market context"""
        styles = {
            self.CONTEXT_TRENDING: [
                {"style": "Breakout Confirmation", "strategies": ["INT-02", "INT-03", "INT-15"]},
                {"style": "Pullback Continuation", "strategies": ["INT-01", "INT-05", "INT-06"]},
                {"style": "Momentum Trading", "strategies": ["INT-04", "INT-14", "INT-16"]}
            ],
            self.CONTEXT_CONSOLIDATION: [
                {"style": "Range Trading", "strategies": ["INT-13", "INT-12"]},
                {"style": "Scalping", "strategies": ["INT-09"]},
                {"style": "Rubber Band Setup", "strategies": ["INT-17"]},
                {"style": "Breakout Watch", "strategies": ["INT-02", "INT-03"]}
            ],
            self.CONTEXT_MEAN_REVERSION: [
                {"style": "VWAP Reversion", "strategies": ["INT-07", "INT-06"]},
                {"style": "Exhaustion Reversal", "strategies": ["INT-08", "INT-11"]},
                {"style": "Key Level Reversal", "strategies": ["INT-11", "INT-12"]}
            ]
        }
        return styles.get(context, [])
    
    async def analyze_symbol(self, symbol: str, historical_data: List[Dict] = None) -> Dict:
        """
        Full market context analysis for a symbol
        Uses Finnhub candle data or generates simulated data
        """
        symbol = symbol.upper()
        
        # Check cache
        cached = self._check_cache(symbol)
        if cached:
            return cached
        
        # Get historical data if not provided
        if not historical_data:
            historical_data = await self._fetch_historical_data(symbol)
        
        if not historical_data or len(historical_data) < 5:
            # Generate simulated data for analysis
            historical_data = self._generate_simulated_history(symbol)
        
        # Extract price arrays
        high_prices = [d['high'] for d in historical_data]
        low_prices = [d['low'] for d in historical_data]
        close_prices = [d['close'] for d in historical_data]
        volumes = [d['volume'] for d in historical_data]
        
        # Calculate metrics
        current_volume = volumes[-1] if volumes else 0
        avg_volume = sum(volumes[:-1]) / len(volumes[:-1]) if len(volumes) > 1 else current_volume
        rvol = self.calculate_relative_volume(current_volume, int(avg_volume))
        
        atr_data = self.calculate_atr_trend(high_prices, low_prices, close_prices)
        range_data = self.detect_price_range(high_prices, low_prices, close_prices)
        trend_data = self.calculate_trend_strength(close_prices)
        mean_reversion_data = self.detect_mean_reversion_setup(close_prices, high_prices, low_prices)
        
        # Classify context
        context = self.classify_market_context(
            rvol, atr_data, range_data, trend_data, mean_reversion_data
        )
        
        result = {
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market_context": context["primary_context"],
            "sub_type": context["sub_type"],
            "confidence": context["confidence"],
            "metrics": {
                "rvol": rvol,
                "atr": atr_data,
                "range": range_data,
                "trend": trend_data,
                "mean_reversion": mean_reversion_data
            },
            "scores": context["scores"],
            "recommended_styles": context["recommended_styles"],
            "current_price": close_prices[-1] if close_prices else 0,
            "data_points": len(historical_data)
        }
        
        self._set_cache(symbol, result)
        return result
    
    def _default_context(self, symbol: str, error: str) -> Dict:
        """Return default context when analysis fails"""
        return {
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market_context": self.CONTEXT_CONSOLIDATION,
            "sub_type": None,
            "confidence": 0,
            "error": error,
            "metrics": {},
            "scores": {},
            "recommended_styles": []
        }
    
    async def _fetch_historical_data(self, symbol: str) -> List[Dict]:
        """Fetch historical candle data from Finnhub"""
        try:
            import finnhub
            import os
            from datetime import datetime, timedelta
            
            finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
            if not finnhub_key or finnhub_key == "demo":
                return []
            
            client = finnhub.Client(api_key=finnhub_key)
            
            # Get last 30 days of daily candles
            end_time = int(datetime.now().timestamp())
            start_time = int((datetime.now() - timedelta(days=30)).timestamp())
            
            loop = asyncio.get_event_loop()
            candles = await loop.run_in_executor(
                None,
                lambda: client.stock_candles(symbol, 'D', start_time, end_time)
            )
            
            if candles and candles.get('s') == 'ok':
                historical_data = []
                for i in range(len(candles['c'])):
                    historical_data.append({
                        "date": datetime.fromtimestamp(candles['t'][i]).strftime("%Y-%m-%d"),
                        "open": candles['o'][i],
                        "high": candles['h'][i],
                        "low": candles['l'][i],
                        "close": candles['c'][i],
                        "volume": candles['v'][i]
                    })
                return historical_data
        except Exception as e:
            print(f"Finnhub historical data error for {symbol}: {e}")
        
        return []
    
    def _generate_simulated_history(self, symbol: str, days: int = 30) -> List[Dict]:
        """Generate simulated historical data for analysis when real data unavailable"""
        import random
        from datetime import datetime, timedelta
        
        base_prices = {
            "SPY": 475, "QQQ": 415, "DIA": 385, "IWM": 198, "VIX": 15,
            "AAPL": 186, "MSFT": 379, "GOOGL": 143, "AMZN": 178, "NVDA": 495,
            "TSLA": 249, "META": 358, "AMD": 146, "NFLX": 479, "CRM": 278,
            "BA": 178, "JPM": 195, "V": 280, "JNJ": 160, "WMT": 165,
        }
        
        base_price = base_prices.get(symbol.upper(), random.uniform(50, 300))
        
        # Generate different patterns for variety
        patterns = ['trending_up', 'trending_down', 'consolidation', 'mean_reversion']
        pattern = random.choice(patterns)
        
        historical_data = []
        current_price = base_price
        base_volume = random.randint(10000000, 50000000)
        
        for i in range(days):
            date = (datetime.now() - timedelta(days=days-i)).strftime("%Y-%m-%d")
            
            # Apply pattern
            if pattern == 'trending_up':
                daily_change = random.uniform(0, 0.02)  # Bias upward
                volume_mult = 1.2 if random.random() > 0.7 else 1.0
            elif pattern == 'trending_down':
                daily_change = random.uniform(-0.02, 0)  # Bias downward
                volume_mult = 1.2 if random.random() > 0.7 else 1.0
            elif pattern == 'consolidation':
                daily_change = random.uniform(-0.005, 0.005)  # Small moves
                volume_mult = 0.7 + random.random() * 0.3  # Lower volume
            else:  # mean_reversion
                # Oscillate around base
                deviation = (current_price - base_price) / base_price
                daily_change = -deviation * 0.1 + random.uniform(-0.01, 0.01)
                volume_mult = 1.0 + abs(deviation)
            
            current_price *= (1 + daily_change)
            daily_range = random.uniform(0.01, 0.03)
            
            high = current_price * (1 + daily_range/2)
            low = current_price * (1 - daily_range/2)
            open_price = current_price * (1 + random.uniform(-daily_range/3, daily_range/3))
            volume = int(base_volume * volume_mult * random.uniform(0.8, 1.2))
            
            historical_data.append({
                "date": date,
                "open": round(open_price, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(current_price, 2),
                "volume": volume
            })
        
        return historical_data
    
    async def analyze_batch(self, symbols: List[str]) -> Dict[str, Dict]:
        """Analyze market context for multiple symbols"""
        results = {}
        
        # Process with concurrency limit
        semaphore = asyncio.Semaphore(5)
        
        async def analyze_one(symbol: str):
            async with semaphore:
                results[symbol] = await self.analyze_symbol(symbol)
        
        await asyncio.gather(*[analyze_one(s) for s in symbols])
        return results
    
    def get_context_summary(self, contexts: Dict[str, Dict]) -> Dict:
        """Generate summary statistics for multiple contexts"""
        trending = []
        consolidation = []
        mean_reversion = []
        
        for symbol, ctx in contexts.items():
            market_ctx = ctx.get("market_context", "")
            if market_ctx == self.CONTEXT_TRENDING:
                trending.append(symbol)
            elif market_ctx == self.CONTEXT_CONSOLIDATION:
                consolidation.append(symbol)
            elif market_ctx == self.CONTEXT_MEAN_REVERSION:
                mean_reversion.append(symbol)
        
        total = len(contexts)
        return {
            "total_analyzed": total,
            "trending": {
                "count": len(trending),
                "percent": round(len(trending) / total * 100, 1) if total > 0 else 0,
                "symbols": trending
            },
            "consolidation": {
                "count": len(consolidation),
                "percent": round(len(consolidation) / total * 100, 1) if total > 0 else 0,
                "symbols": consolidation
            },
            "mean_reversion": {
                "count": len(mean_reversion),
                "percent": round(len(mean_reversion) / total * 100, 1) if total > 0 else 0,
                "symbols": mean_reversion
            }
        }


# Singleton instance
_market_context_service: Optional[MarketContextService] = None

def get_market_context_service() -> MarketContextService:
    """Get or create the market context service singleton"""
    global _market_context_service
    if _market_context_service is None:
        _market_context_service = MarketContextService()
    return _market_context_service
