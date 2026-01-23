"""
Feature Engineering Service
Comprehensive technical, fundamental, and derived features for trading analysis.
Optimized for IB Gateway API with focus on intraday high-conviction setups.

Data Sources:
- IB Gateway: Real-time bars (1m/5m), Historical bars (daily/weekly), Fundamentals
- Calculations: EMAs, RSI, MACD, ATR, VWAP, etc.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Tuple
from enum import Enum
import math


class Timeframe(str, Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    DAILY = "daily"
    WEEKLY = "weekly"


class FeatureEngineService:
    """
    Calculates all technical, fundamental, and derived features for stock analysis.
    Designed to work with IB Gateway API data.
    """
    
    def __init__(self):
        pass
    
    # ==================== BASIC PRICE & VOLUME ====================
    
    def calc_basic_price_volume(self, bars: List[Dict], current_bar: Dict = None) -> Dict:
        """
        Calculate basic price and volume features.
        bars: List of OHLCV bars (oldest first)
        """
        if not bars:
            return {}
        
        current = current_bar or bars[-1]
        
        features = {
            "open": current.get("open", 0),
            "high": current.get("high", 0),
            "low": current.get("low", 0),
            "close": current.get("close", 0),
            "volume": current.get("volume", 0),
        }
        
        # Returns
        if len(bars) >= 2:
            prev_close = bars[-2].get("close", current["close"])
            features["pct_return_1bar"] = ((current["close"] - prev_close) / prev_close) * 100 if prev_close else 0
        
        # Gap calculation (if we have prior session close)
        prior_close = current.get("prior_close", 0)
        if prior_close > 0:
            features["gap_pct_today"] = ((current["open"] - prior_close) / prior_close) * 100
        
        # Dollar volume
        features["dollar_volume"] = current["close"] * current["volume"]
        
        # Average volume (20-bar)
        if len(bars) >= 20:
            avg_vol_20 = sum(b.get("volume", 0) for b in bars[-20:]) / 20
            features["avg_volume_20"] = avg_vol_20
            features["rvol_20"] = current["volume"] / avg_vol_20 if avg_vol_20 > 0 else 1
        
        # Average volume (50-bar)
        if len(bars) >= 50:
            avg_vol_50 = sum(b.get("volume", 0) for b in bars[-50:]) / 50
            features["avg_volume_50"] = avg_vol_50
        
        return features
    
    # ==================== TREND & MOVING AVERAGES ====================
    
    def calc_sma(self, prices: List[float], period: int) -> float:
        """Calculate Simple Moving Average"""
        if len(prices) < period:
            return prices[-1] if prices else 0
        return sum(prices[-period:]) / period
    
    def calc_ema(self, prices: List[float], period: int) -> float:
        """Calculate Exponential Moving Average"""
        if not prices:
            return 0
        if len(prices) < period:
            return sum(prices) / len(prices)
        
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period  # Start with SMA
        
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        
        return ema
    
    def calc_moving_averages(self, bars: List[Dict]) -> Dict:
        """Calculate all moving average features"""
        if not bars:
            return {}
        
        closes = [b.get("close", 0) for b in bars]
        current_close = closes[-1] if closes else 0
        
        features = {}
        
        # SMAs
        for period in [10, 20, 50, 100, 200]:
            if len(closes) >= period:
                sma = self.calc_sma(closes, period)
                features[f"sma_{period}"] = sma
                features[f"close_over_sma_{period}_pct"] = ((current_close - sma) / sma) * 100 if sma else 0
        
        # EMAs
        for period in [9, 20, 50]:
            if len(closes) >= period:
                ema = self.calc_ema(closes, period)
                features[f"ema_{period}"] = ema
                features[f"close_over_ema_{period}_pct"] = ((current_close - ema) / ema) * 100 if ema else 0
        
        # Relationships
        if "sma_20" in features and "sma_50" in features:
            features["sma_20_over_50_pct"] = ((features["sma_20"] - features["sma_50"]) / features["sma_50"]) * 100 if features["sma_50"] else 0
        
        if "sma_50" in features and "sma_200" in features:
            features["sma_50_over_200_pct"] = ((features["sma_50"] - features["sma_200"]) / features["sma_200"]) * 100 if features["sma_200"] else 0
            features["golden_cross"] = features["sma_50"] > features["sma_200"]
            features["death_cross"] = features["sma_50"] < features["sma_200"]
        
        if "ema_20" in features and "ema_50" in features:
            features["ema_20_over_50_pct"] = ((features["ema_20"] - features["ema_50"]) / features["ema_50"]) * 100 if features["ema_50"] else 0
        
        # Slopes (change over last 5 bars)
        if len(closes) >= 25:
            sma_20_current = self.calc_sma(closes, 20)
            sma_20_5_ago = self.calc_sma(closes[:-5], 20)
            features["slope_sma_20"] = sma_20_current - sma_20_5_ago
        
        if len(closes) >= 55:
            sma_50_current = self.calc_sma(closes, 50)
            sma_50_5_ago = self.calc_sma(closes[:-5], 50)
            features["slope_sma_50"] = sma_50_current - sma_50_5_ago
        
        return features
    
    # ==================== VOLATILITY & RANGE ====================
    
    def calc_true_range(self, high: float, low: float, prev_close: float) -> float:
        """Calculate True Range"""
        return max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
    
    def calc_atr(self, bars: List[Dict], period: int = 14) -> float:
        """Calculate Average True Range"""
        if len(bars) < period + 1:
            return 0
        
        true_ranges = []
        for i in range(1, len(bars)):
            tr = self.calc_true_range(
                bars[i].get("high", 0),
                bars[i].get("low", 0),
                bars[i-1].get("close", 0)
            )
            true_ranges.append(tr)
        
        if len(true_ranges) < period:
            return sum(true_ranges) / len(true_ranges) if true_ranges else 0
        
        # Use Wilder's smoothing (EMA-like)
        atr = sum(true_ranges[:period]) / period
        for tr in true_ranges[period:]:
            atr = (atr * (period - 1) + tr) / period
        
        return atr
    
    def calc_volatility_features(self, bars: List[Dict]) -> Dict:
        """Calculate volatility and range features"""
        if not bars:
            return {}
        
        features = {}
        current = bars[-1]
        current_close = current.get("close", 0)
        
        # ATR
        atr_14 = self.calc_atr(bars, 14)
        features["atr_14"] = atr_14
        features["atr_14_pct"] = (atr_14 / current_close) * 100 if current_close else 0
        
        # True range percent (current bar)
        if len(bars) >= 2:
            tr = self.calc_true_range(
                current.get("high", 0),
                current.get("low", 0),
                bars[-2].get("close", 0)
            )
            features["tr_pct"] = (tr / current_close) * 100 if current_close else 0
        
        # Historical volatility (standard deviation of returns)
        if len(bars) >= 20:
            returns = []
            for i in range(1, min(21, len(bars))):
                prev_close = bars[-(i+1)].get("close", 0)
                curr_close = bars[-i].get("close", 0)
                if prev_close > 0:
                    returns.append((curr_close - prev_close) / prev_close)
            
            if returns:
                mean_ret = sum(returns) / len(returns)
                variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
                features["realized_vol_20d"] = math.sqrt(variance) * math.sqrt(252) * 100  # Annualized
        
        # Range compression/expansion
        if len(bars) >= 20:
            ranges = [b.get("high", 0) - b.get("low", 0) for b in bars[-20:]]
            avg_range = sum(ranges) / len(ranges)
            current_range = current.get("high", 0) - current.get("low", 0)
            features["range_vs_avg_20"] = current_range / avg_range if avg_range else 1
        
        return features
    
    # ==================== MOMENTUM & OSCILLATORS ====================
    
    def calc_rsi(self, bars: List[Dict], period: int = 14) -> float:
        """Calculate RSI (Relative Strength Index)"""
        if len(bars) < period + 1:
            return 50  # Neutral
        
        gains = []
        losses = []
        
        for i in range(1, len(bars)):
            change = bars[i].get("close", 0) - bars[i-1].get("close", 0)
            if change >= 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        if len(gains) < period:
            return 50
        
        # Wilder's smoothing
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def calc_stochastic(self, bars: List[Dict], k_period: int = 14, d_period: int = 3) -> Tuple[float, float]:
        """Calculate Stochastic %K and %D"""
        if len(bars) < k_period:
            return 50, 50
        
        recent_bars = bars[-k_period:]
        highest_high = max(b.get("high", 0) for b in recent_bars)
        lowest_low = min(b.get("low", 0) for b in recent_bars)
        current_close = bars[-1].get("close", 0)
        
        if highest_high == lowest_low:
            k = 50
        else:
            k = ((current_close - lowest_low) / (highest_high - lowest_low)) * 100
        
        # Calculate %D (SMA of %K over d_period)
        # For simplicity, return K as D if not enough data
        d = k
        
        return k, d
    
    def calc_macd(self, bars: List[Dict], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[float, float, float]:
        """Calculate MACD Line, Signal Line, and Histogram"""
        if len(bars) < slow:
            return 0, 0, 0
        
        closes = [b.get("close", 0) for b in bars]
        
        ema_fast = self.calc_ema(closes, fast)
        ema_slow = self.calc_ema(closes, slow)
        
        macd_line = ema_fast - ema_slow
        
        # Calculate signal line (EMA of MACD)
        # For full accuracy, we'd need historical MACD values
        # Simplified: use current MACD as approximation
        signal_line = macd_line * 0.9  # Approximation
        
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    def calc_williams_r(self, bars: List[Dict], period: int = 14) -> float:
        """Calculate Williams %R"""
        if len(bars) < period:
            return -50
        
        recent_bars = bars[-period:]
        highest_high = max(b.get("high", 0) for b in recent_bars)
        lowest_low = min(b.get("low", 0) for b in recent_bars)
        current_close = bars[-1].get("close", 0)
        
        if highest_high == lowest_low:
            return -50
        
        return ((highest_high - current_close) / (highest_high - lowest_low)) * -100
    
    def calc_momentum_features(self, bars: List[Dict]) -> Dict:
        """Calculate all momentum and oscillator features"""
        if not bars:
            return {}
        
        features = {}
        closes = [b.get("close", 0) for b in bars]
        
        # RSI
        features["rsi_14"] = self.calc_rsi(bars, 14)
        features["rsi_2"] = self.calc_rsi(bars, 2)  # Short-term mean reversion
        
        # RSI zones
        features["rsi_oversold"] = features["rsi_14"] < 30
        features["rsi_overbought"] = features["rsi_14"] > 70
        
        # Stochastics
        k, d = self.calc_stochastic(bars, 14, 3)
        features["stoch_k_14_3"] = k
        features["stoch_d_14_3"] = d
        
        # MACD
        macd_line, signal_line, histogram = self.calc_macd(bars, 12, 26, 9)
        features["macd_line"] = macd_line
        features["macd_signal"] = signal_line
        features["macd_hist"] = histogram
        features["macd_bullish"] = histogram > 0
        
        # Rate of Change
        if len(closes) >= 10:
            features["roc_10"] = ((closes[-1] - closes[-10]) / closes[-10]) * 100 if closes[-10] else 0
        if len(closes) >= 20:
            features["roc_20"] = ((closes[-1] - closes[-20]) / closes[-20]) * 100 if closes[-20] else 0
        
        # Williams %R
        features["williams_r_14"] = self.calc_williams_r(bars, 14)
        
        return features
    
    # ==================== VOLUME & VWAP FEATURES ====================
    
    def calc_vwap(self, bars: List[Dict]) -> float:
        """Calculate VWAP (Volume Weighted Average Price)"""
        if not bars:
            return 0
        
        cumulative_tp_vol = 0
        cumulative_vol = 0
        
        for bar in bars:
            typical_price = (bar.get("high", 0) + bar.get("low", 0) + bar.get("close", 0)) / 3
            volume = bar.get("volume", 0)
            cumulative_tp_vol += typical_price * volume
            cumulative_vol += volume
        
        return cumulative_tp_vol / cumulative_vol if cumulative_vol > 0 else 0
    
    def calc_vwap_features(self, bars: List[Dict], session_bars: List[Dict] = None) -> Dict:
        """Calculate VWAP and related features"""
        if not bars:
            return {}
        
        features = {}
        current_close = bars[-1].get("close", 0)
        
        # Use session bars for VWAP if provided, otherwise use all bars
        vwap_bars = session_bars if session_bars else bars
        vwap = self.calc_vwap(vwap_bars)
        
        features["vwap"] = vwap
        features["close_over_vwap"] = current_close > vwap
        features["close_over_vwap_pct"] = ((current_close - vwap) / vwap) * 100 if vwap else 0
        features["distance_from_vwap_pct"] = abs(features["close_over_vwap_pct"])
        
        # VWAP bands (1 and 2 ATR)
        atr = self.calc_atr(bars, 14)
        features["vwap_upper_1atr"] = vwap + atr
        features["vwap_lower_1atr"] = vwap - atr
        features["vwap_upper_2atr"] = vwap + (atr * 2)
        features["vwap_lower_2atr"] = vwap - (atr * 2)
        
        # Relative volume (RVOL)
        if len(bars) >= 20:
            current_vol = bars[-1].get("volume", 0)
            avg_vol = sum(b.get("volume", 0) for b in bars[-20:]) / 20
            features["rvol_intraday"] = current_vol / avg_vol if avg_vol > 0 else 1
        
        return features
    
    # ==================== STRUCTURE / LEVELS ====================
    
    def calc_structure_features(self, bars: List[Dict], daily_bars: List[Dict] = None) -> Dict:
        """Calculate support/resistance and structure features"""
        if not bars:
            return {}
        
        features = {}
        current = bars[-1]
        current_close = current.get("close", 0)
        
        # Intraday highs/lows
        if len(bars) >= 20:
            features["high_20"] = max(b.get("high", 0) for b in bars[-20:])
            features["low_20"] = min(b.get("low", 0) for b in bars[-20:])
            features["close_over_high20_pct"] = ((current_close - features["high_20"]) / features["high_20"]) * 100 if features["high_20"] else 0
            features["close_over_low20_pct"] = ((current_close - features["low_20"]) / features["low_20"]) * 100 if features["low_20"] else 0
        
        # Use daily bars for longer-term levels
        if daily_bars and len(daily_bars) >= 20:
            features["high_20d"] = max(b.get("high", 0) for b in daily_bars[-20:])
            features["low_20d"] = min(b.get("low", 0) for b in daily_bars[-20:])
            
            if len(daily_bars) >= 52:  # ~52 weeks
                features["high_52w"] = max(b.get("high", 0) for b in daily_bars[-260:]) if len(daily_bars) >= 260 else max(b.get("high", 0) for b in daily_bars)
                features["low_52w"] = min(b.get("low", 0) for b in daily_bars[-260:]) if len(daily_bars) >= 260 else min(b.get("low", 0) for b in daily_bars)
                features["close_over_52w_high_pct"] = ((current_close - features["high_52w"]) / features["high_52w"]) * 100 if features["high_52w"] else 0
                features["pct_off_52w_high"] = abs(features["close_over_52w_high_pct"])
        
        # Prior day levels (if available in current bar)
        prior_high = current.get("prior_high", 0)
        prior_low = current.get("prior_low", 0)
        prior_close = current.get("prior_close", 0)
        
        if prior_high > 0:
            features["prior_day_high"] = prior_high
            features["close_near_pdh_pct"] = abs((current_close - prior_high) / prior_high) * 100
        
        if prior_low > 0:
            features["prior_day_low"] = prior_low
            features["close_near_pdl_pct"] = abs((current_close - prior_low) / prior_low) * 100
        
        if prior_close > 0:
            features["prior_day_close"] = prior_close
        
        # Pivot points (using prior day data)
        if prior_high > 0 and prior_low > 0 and prior_close > 0:
            pivot = (prior_high + prior_low + prior_close) / 3
            features["pivot"] = pivot
            features["r1"] = (2 * pivot) - prior_low
            features["s1"] = (2 * pivot) - prior_high
            features["r2"] = pivot + (prior_high - prior_low)
            features["s2"] = pivot - (prior_high - prior_low)
        
        return features
    
    # ==================== OPENING RANGE (INTRADAY) ====================
    
    def calc_opening_range(self, session_bars: List[Dict], or_minutes: int = 15) -> Dict:
        """Calculate Opening Range features (first N minutes of session)"""
        if not session_bars:
            return {}
        
        features = {}
        
        # Assume bars are 1-minute; take first 'or_minutes' bars
        or_bars = session_bars[:or_minutes] if len(session_bars) >= or_minutes else session_bars
        
        if or_bars:
            features["opening_range_high"] = max(b.get("high", 0) for b in or_bars)
            features["opening_range_low"] = min(b.get("low", 0) for b in or_bars)
            features["opening_range_size"] = features["opening_range_high"] - features["opening_range_low"]
            
            current_close = session_bars[-1].get("close", 0) if session_bars else 0
            
            if features["opening_range_high"] > 0:
                features["break_above_orh"] = current_close > features["opening_range_high"]
                features["break_above_orh_pct"] = ((current_close - features["opening_range_high"]) / features["opening_range_high"]) * 100
            
            if features["opening_range_low"] > 0:
                features["break_below_orl"] = current_close < features["opening_range_low"]
                features["break_below_orl_pct"] = ((features["opening_range_low"] - current_close) / features["opening_range_low"]) * 100
        
        return features
    
    # ==================== MARKET / SECTOR CONTEXT ====================
    
    def calc_relative_strength(self, stock_returns: Dict, benchmark_returns: Dict) -> Dict:
        """Calculate relative strength vs SPY and sector"""
        features = {}
        
        # vs SPY
        spy_1d = benchmark_returns.get("spy_return_1d", 0)
        spy_5d = benchmark_returns.get("spy_return_5d", 0)
        spy_20d = benchmark_returns.get("spy_return_20d", 0)
        
        stock_1d = stock_returns.get("return_1d", 0)
        stock_5d = stock_returns.get("return_5d", 0)
        stock_20d = stock_returns.get("return_20d", 0)
        
        features["rs_vs_spy_1d"] = stock_1d - spy_1d
        features["rs_vs_spy_5d"] = stock_5d - spy_5d
        features["rs_vs_spy_20d"] = stock_20d - spy_20d
        
        # vs Sector
        sector_1d = benchmark_returns.get("sector_return_1d", 0)
        sector_20d = benchmark_returns.get("sector_return_20d", 0)
        
        features["rs_vs_sector_1d"] = stock_1d - sector_1d
        features["rs_vs_sector_20d"] = stock_20d - sector_20d
        
        # Relative strength ranking (0-100, higher = stronger)
        features["rs_rank_20d"] = 50 + (features["rs_vs_spy_20d"] * 2)  # Simplified
        features["rs_rank_20d"] = max(0, min(100, features["rs_rank_20d"]))
        
        return features
    
    # ==================== HIGH-CONVICTION INTRADAY FILTER ====================
    
    def calc_intraday_conviction_score(self, features: Dict) -> Dict:
        """
        Calculate high-conviction intraday setup score.
        Based on user's criteria:
        - RVOL >= threshold
        - Near VWAP
        - Above EMA20
        - RSI in sweet spot (45-75)
        - Breaking Opening Range or near PDH
        - Catalyst boost
        """
        score = 0
        max_score = 100
        signals = []
        
        # RVOL (25 points)
        rvol = features.get("rvol_intraday", 1)
        if rvol >= 5:
            score += 25
            signals.append(f"RVOL {rvol:.1f}x (Excellent)")
        elif rvol >= 3:
            score += 20
            signals.append(f"RVOL {rvol:.1f}x (Good)")
        elif rvol >= 2:
            score += 15
            signals.append(f"RVOL {rvol:.1f}x (Moderate)")
        elif rvol >= 1.5:
            score += 10
            signals.append(f"RVOL {rvol:.1f}x (Low)")
        
        # VWAP Position (20 points)
        vwap_dist = abs(features.get("distance_from_vwap_pct", 10))
        if vwap_dist <= 0.5:
            score += 20
            signals.append("At VWAP (High conviction zone)")
        elif vwap_dist <= 1.0:
            score += 15
            signals.append("Near VWAP")
        elif vwap_dist <= 2.0:
            score += 10
        
        # EMA Position (15 points)
        close_over_ema20 = features.get("close_over_ema_20_pct", 0)
        if close_over_ema20 > 0 and close_over_ema20 <= 2:
            score += 15
            signals.append("Above EMA20 (Trend aligned)")
        elif close_over_ema20 > 2:
            score += 10
        elif close_over_ema20 < -2:
            score += 5  # Potential mean reversion
            signals.append("Below EMA20 (Mean reversion candidate)")
        
        # RSI Sweet Spot (15 points)
        rsi = features.get("rsi_14", 50)
        if 45 <= rsi <= 75:
            score += 15
            signals.append(f"RSI {rsi:.0f} (Sweet spot)")
        elif 30 <= rsi < 45:
            score += 10
            signals.append(f"RSI {rsi:.0f} (Oversold bounce candidate)")
        elif 75 < rsi <= 85:
            score += 8
        
        # Opening Range Break (15 points)
        if features.get("break_above_orh", False):
            score += 15
            signals.append("Opening Range Breakout")
        elif features.get("break_below_orl", False):
            score += 15
            signals.append("Opening Range Breakdown")
        
        # Near Prior Day Levels (10 points)
        pdh_dist = features.get("close_near_pdh_pct", 100)
        pdl_dist = features.get("close_near_pdl_pct", 100)
        if pdh_dist < 0.5:
            score += 10
            signals.append("Testing Prior Day High")
        elif pdl_dist < 0.5:
            score += 10
            signals.append("Testing Prior Day Low")
        
        # Catalyst Boost (up to 10 bonus points)
        catalyst_score = features.get("earnings_catalyst_score", 5)
        if catalyst_score >= 8:
            score += 10
            signals.append("Strong catalyst")
        elif catalyst_score >= 6:
            score += 5
        
        # Normalize
        conviction = min(100, score)
        
        # Determine confidence level
        if conviction >= 80:
            confidence = "VERY HIGH"
        elif conviction >= 65:
            confidence = "HIGH"
        elif conviction >= 50:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"
        
        return {
            "intraday_conviction_score": conviction,
            "conviction_confidence": confidence,
            "conviction_signals": signals,
            "meets_high_conviction": conviction >= 65
        }
    
    # ==================== COMPOSITE SCORES ====================
    
    def calc_vst_scores(self, features: Dict, fundamentals: Dict) -> Dict:
        """
        Calculate VectorVest-style scores (0-10 scale)
        RV: Relative Value
        RS: Relative Safety
        RT: Relative Timing
        VST: Composite
        """
        scores = {}
        
        # RV Score (Value) - based on P/E, P/S, etc.
        pe = fundamentals.get("pe_ttm", 20)
        sector_pe = fundamentals.get("sector_pe", 20)
        if pe > 0 and sector_pe > 0:
            pe_ratio = pe / sector_pe
            if pe_ratio < 0.7:
                rv = 9
            elif pe_ratio < 0.9:
                rv = 7
            elif pe_ratio < 1.1:
                rv = 5
            elif pe_ratio < 1.3:
                rv = 3
            else:
                rv = 1
        else:
            rv = 5
        scores["rv_score"] = rv
        
        # RS Score (Safety) - based on debt, margins, consistency
        debt_equity = fundamentals.get("debt_to_equity", 1)
        net_margin = fundamentals.get("net_margin", 10)
        
        safety = 5
        if debt_equity < 0.5:
            safety += 2
        elif debt_equity > 2:
            safety -= 2
        
        if net_margin > 20:
            safety += 2
        elif net_margin < 5:
            safety -= 2
        
        scores["rs_score"] = max(1, min(10, safety))
        
        # RT Score (Timing) - based on technicals
        rsi = features.get("rsi_14", 50)
        close_over_sma50 = features.get("close_over_sma_50_pct", 0)
        
        timing = 5
        if close_over_sma50 > 5:
            timing += 2
        elif close_over_sma50 < -5:
            timing -= 2
        
        if 40 <= rsi <= 60:
            timing += 1
        elif rsi > 70 or rsi < 30:
            timing -= 1
        
        scores["rt_score"] = max(1, min(10, timing))
        
        # VST Composite
        scores["vst_score"] = round((scores["rv_score"] + scores["rs_score"] + scores["rt_score"]) / 3, 1)
        
        return scores
    
    # ==================== MASTER FEATURE CALCULATOR ====================
    
    def calculate_all_features(
        self,
        bars_5m: List[Dict],
        bars_daily: List[Dict] = None,
        session_bars_1m: List[Dict] = None,
        fundamentals: Dict = None,
        market_data: Dict = None
    ) -> Dict:
        """
        Calculate all features for a stock.
        
        Args:
            bars_5m: 5-minute bars (primary timeframe for intraday)
            bars_daily: Daily bars (for swing/long-term)
            session_bars_1m: 1-minute bars for current session (for opening range)
            fundamentals: Fundamental data from IB
            market_data: Market context (SPY, sector returns)
        
        Returns:
            Complete feature dictionary
        """
        all_features = {}
        
        # Use 5m bars as primary
        primary_bars = bars_5m if bars_5m else []
        
        # Basic price/volume
        all_features.update(self.calc_basic_price_volume(primary_bars))
        
        # Moving averages
        all_features.update(self.calc_moving_averages(primary_bars))
        
        # Volatility
        all_features.update(self.calc_volatility_features(primary_bars))
        
        # Momentum
        all_features.update(self.calc_momentum_features(primary_bars))
        
        # VWAP (use session bars if available)
        vwap_bars = session_bars_1m if session_bars_1m else primary_bars
        all_features.update(self.calc_vwap_features(primary_bars, vwap_bars))
        
        # Structure/levels
        all_features.update(self.calc_structure_features(primary_bars, bars_daily))
        
        # Opening range (if session bars available)
        if session_bars_1m:
            all_features.update(self.calc_opening_range(session_bars_1m, 15))
        
        # Relative strength (if market data available)
        if market_data:
            stock_returns = {
                "return_1d": all_features.get("pct_return_1bar", 0),
                "return_5d": all_features.get("roc_10", 0) / 2,  # Approximation
                "return_20d": all_features.get("roc_20", 0)
            }
            all_features.update(self.calc_relative_strength(stock_returns, market_data))
        
        # VectorVest scores (if fundamentals available)
        if fundamentals:
            all_features.update(fundamentals)
            all_features.update(self.calc_vst_scores(all_features, fundamentals))
        
        # Intraday conviction score
        all_features.update(self.calc_intraday_conviction_score(all_features))
        
        return all_features


# Singleton
_feature_engine: Optional[FeatureEngineService] = None

def get_feature_engine() -> FeatureEngineService:
    global _feature_engine
    if _feature_engine is None:
        _feature_engine = FeatureEngineService()
    return _feature_engine
