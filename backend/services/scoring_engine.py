"""
Universal Scoring Engine
Comprehensive stock scoring system combining:
- Technical Analysis (VWAP, RVOL, Gap%, MA Distance, Patterns)
- Fundamental Analysis (VectorVest-style scoring)
- Catalyst Scoring (SMB system + major events)
- Risk Assessment (R:R, Float, Short Interest)
- Market Context Alignment
- Historical Success Probability
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Tuple
from enum import Enum
import math


class TimeframeType(str, Enum):
    INTRADAY = "intraday"
    SWING = "swing"
    LONGTERM = "longterm"


class DirectionBias(str, Enum):
    STRONG_LONG = "STRONG_LONG"
    LONG = "LONG"
    NEUTRAL = "NEUTRAL"
    SHORT = "SHORT"
    STRONG_SHORT = "STRONG_SHORT"


class MarketCapCategory(str, Enum):
    SMALL_CAP = "small_cap"      # < 2B
    MID_CAP = "mid_cap"          # 2B - 10B
    LARGE_CAP = "large_cap"      # > 10B


class UniversalScoringEngine:
    """
    Universal scoring system that evaluates stocks across multiple dimensions
    and provides actionable trade recommendations with success probability.
    """
    
    # Weights for each scoring category
    CATEGORY_WEIGHTS = {
        "technical": 0.35,
        "fundamental": 0.20,
        "catalyst": 0.20,
        "risk": 0.10,
        "context": 0.15
    }
    
    # RVOL thresholds by market cap (user's rules)
    RVOL_THRESHOLDS = {
        MarketCapCategory.SMALL_CAP: 5.0,
        MarketCapCategory.MID_CAP: 3.0,
        MarketCapCategory.LARGE_CAP: 2.0
    }
    
    # Minimum float requirement
    MIN_FLOAT = 50_000_000  # 50M shares
    
    # Gap threshold
    GAP_THRESHOLD = 4.0  # +/-4%
    
    def __init__(self, db=None):
        self.db = db
        if db:
            self.scores_collection = db["ticker_scores"]
            self.historical_collection = db["score_history"]
    
    # ==================== MARKET CAP CLASSIFICATION ====================
    
    def classify_market_cap(self, market_cap: float) -> MarketCapCategory:
        """Classify stock by market cap"""
        if market_cap < 2_000_000_000:  # < 2B
            return MarketCapCategory.SMALL_CAP
        elif market_cap < 10_000_000_000:  # < 10B
            return MarketCapCategory.MID_CAP
        else:
            return MarketCapCategory.LARGE_CAP
    
    # ==================== TECHNICAL SCORING (35%) ====================
    
    def score_technical(self, data: Dict) -> Dict:
        """
        Score technical factors (0-100)
        - VWAP Position & Bias
        - RVOL vs threshold by market cap
        - Gap percentage
        - Distance from key MAs (mean reversion)
        - Pattern recognition
        """
        scores = {}
        total_score = 0
        direction_points = 0  # Positive = long bias, Negative = short bias
        
        # 1. VWAP Position (20 points max)
        vwap = data.get("vwap", 0)
        current_price = data.get("current_price", 0)
        if vwap > 0 and current_price > 0:
            vwap_distance_pct = ((current_price - vwap) / vwap) * 100
            if current_price > vwap:
                scores["vwap"] = {"score": 15, "position": "ABOVE", "distance_pct": round(vwap_distance_pct, 2)}
                direction_points += 10  # Long bias
                total_score += 15
            else:
                scores["vwap"] = {"score": 15, "position": "BELOW", "distance_pct": round(vwap_distance_pct, 2)}
                direction_points -= 10  # Short bias
                total_score += 15
        else:
            scores["vwap"] = {"score": 0, "position": "UNKNOWN", "distance_pct": 0}
        
        # 2. RVOL Score (25 points max)
        rvol = data.get("rvol", 1.0)
        market_cap = data.get("market_cap", 10_000_000_000)
        cap_category = self.classify_market_cap(market_cap)
        rvol_threshold = self.RVOL_THRESHOLDS[cap_category]
        
        if rvol >= rvol_threshold:
            rvol_score = 25
        elif rvol >= rvol_threshold * 0.75:
            rvol_score = 20
        elif rvol >= rvol_threshold * 0.5:
            rvol_score = 15
        elif rvol >= 1.5:
            rvol_score = 10
        else:
            rvol_score = 5
        
        scores["rvol"] = {
            "score": rvol_score,
            "value": rvol,
            "threshold": rvol_threshold,
            "cap_category": cap_category.value,
            "meets_threshold": rvol >= rvol_threshold
        }
        total_score += rvol_score
        
        # 3. Gap Score (20 points max)
        gap_pct = data.get("gap_percent", 0)
        if abs(gap_pct) >= self.GAP_THRESHOLD:
            gap_score = 20
            if gap_pct > 0:
                direction_points += 5  # Gap up = long bias
            else:
                direction_points -= 5  # Gap down = short bias
        elif abs(gap_pct) >= 2:
            gap_score = 12
        else:
            gap_score = 5
        
        scores["gap"] = {
            "score": gap_score,
            "percent": gap_pct,
            "meets_threshold": abs(gap_pct) >= self.GAP_THRESHOLD
        }
        total_score += gap_score
        
        # 4. MA Distance / Mean Reversion (20 points max)
        ma_9 = data.get("ema_9", 0)
        ma_20 = data.get("sma_20", 0)
        ma_50 = data.get("sma_50", 0)
        
        ma_distances = {}
        mean_reversion_signal = None
        
        if ma_9 > 0 and current_price > 0:
            dist_9 = ((current_price - ma_9) / ma_9) * 100
            ma_distances["ema_9"] = round(dist_9, 2)
            
            # Mean reversion logic per user rules
            if dist_9 > 5:  # Extended above = short bias (mean reversion)
                mean_reversion_signal = "SHORT"
                direction_points -= 8
            elif dist_9 < -5:  # Extended below = long bias (rubber band)
                mean_reversion_signal = "LONG"
                direction_points += 8
        
        if ma_20 > 0 and current_price > 0:
            dist_20 = ((current_price - ma_20) / ma_20) * 100
            ma_distances["sma_20"] = round(dist_20, 2)
        
        if ma_50 > 0 and current_price > 0:
            dist_50 = ((current_price - ma_50) / ma_50) * 100
            ma_distances["sma_50"] = round(dist_50, 2)
        
        # Score based on mean reversion opportunity
        if mean_reversion_signal:
            ma_score = 20
        elif ma_distances:
            avg_dist = sum(abs(v) for v in ma_distances.values()) / len(ma_distances)
            if avg_dist > 3:
                ma_score = 15
            else:
                ma_score = 10
        else:
            ma_score = 5
        
        scores["ma_distance"] = {
            "score": ma_score,
            "distances": ma_distances,
            "mean_reversion_signal": mean_reversion_signal
        }
        total_score += ma_score
        
        # 5. Pattern Recognition (15 points max)
        patterns = data.get("patterns", [])
        high_value_patterns = ["double_bottom", "cup_handle", "bull_flag", "ascending_triangle",
                              "breakout", "vwap_bounce", "higher_lows"]
        
        pattern_score = 0
        matched_patterns = []
        for pattern in patterns:
            if pattern.lower() in high_value_patterns:
                pattern_score += 5
                matched_patterns.append(pattern)
        pattern_score = min(pattern_score, 15)
        
        scores["patterns"] = {
            "score": pattern_score,
            "detected": matched_patterns
        }
        total_score += pattern_score
        
        # Normalize to 0-100
        max_possible = 100
        normalized_score = round((total_score / max_possible) * 100, 1)
        
        return {
            "category": "technical",
            "score": normalized_score,
            "direction_points": direction_points,
            "components": scores
        }
    
    # ==================== FUNDAMENTAL SCORING (20%) - VectorVest Style ====================
    
    def score_fundamental(self, data: Dict) -> Dict:
        """
        VectorVest-style fundamental scoring (0-100)
        Components:
        - Value (VS): Relative Value compared to AAA bonds
        - Safety (RS): Risk assessment based on consistency
        - Timing (RT): Technical timing indicator
        - Growth (GRT): Earnings & Revenue growth
        """
        scores = {}
        total_score = 0
        
        # 1. Value Score (VS) - 25 points max
        pe_ratio = data.get("pe_ratio", 0)
        sector_avg_pe = data.get("sector_pe", 20)
        
        if pe_ratio > 0:
            # Lower P/E relative to sector = better value
            pe_relative = pe_ratio / sector_avg_pe if sector_avg_pe > 0 else 1
            if pe_relative < 0.7:
                vs_score = 25
            elif pe_relative < 0.9:
                vs_score = 20
            elif pe_relative < 1.1:
                vs_score = 15
            elif pe_relative < 1.3:
                vs_score = 10
            else:
                vs_score = 5
        else:
            vs_score = 10  # Neutral if no P/E
        
        scores["value"] = {
            "score": vs_score,
            "pe_ratio": pe_ratio,
            "sector_pe": sector_avg_pe
        }
        total_score += vs_score
        
        # 2. Safety Score (RS) - 25 points max
        debt_to_equity = data.get("debt_to_equity", 1)
        profit_margin = data.get("profit_margin", 0)
        
        # Lower debt = safer
        if debt_to_equity < 0.5:
            debt_score = 15
        elif debt_to_equity < 1.0:
            debt_score = 12
        elif debt_to_equity < 2.0:
            debt_score = 8
        else:
            debt_score = 4
        
        # Higher margin = safer
        if profit_margin > 20:
            margin_score = 10
        elif profit_margin > 10:
            margin_score = 7
        elif profit_margin > 0:
            margin_score = 4
        else:
            margin_score = 2
        
        rs_score = debt_score + margin_score
        scores["safety"] = {
            "score": rs_score,
            "debt_to_equity": debt_to_equity,
            "profit_margin": profit_margin
        }
        total_score += rs_score
        
        # 3. Growth Score (GRT) - 25 points max
        revenue_growth = data.get("revenue_growth", 0)
        eps_growth = data.get("eps_growth", 0)
        
        # Revenue growth scoring
        if revenue_growth > 25:
            rev_score = 12
        elif revenue_growth > 15:
            rev_score = 10
        elif revenue_growth > 5:
            rev_score = 7
        elif revenue_growth > 0:
            rev_score = 4
        else:
            rev_score = 2
        
        # EPS growth scoring
        if eps_growth > 30:
            eps_score = 13
        elif eps_growth > 20:
            eps_score = 10
        elif eps_growth > 10:
            eps_score = 7
        elif eps_growth > 0:
            eps_score = 4
        else:
            eps_score = 2
        
        grt_score = rev_score + eps_score
        scores["growth"] = {
            "score": grt_score,
            "revenue_growth": revenue_growth,
            "eps_growth": eps_growth
        }
        total_score += grt_score
        
        # 4. Timing Score (RT) - 25 points max (technical within fundamentals)
        price_vs_52w_high = data.get("price_vs_52w_high", 100)  # % of 52w high
        trend_strength = data.get("trend_strength", 50)
        
        # Near highs with strong trend = good timing
        if price_vs_52w_high > 95 and trend_strength > 60:
            rt_score = 25
        elif price_vs_52w_high > 85:
            rt_score = 20
        elif price_vs_52w_high > 70:
            rt_score = 15
        elif price_vs_52w_high > 50:
            rt_score = 10
        else:
            rt_score = 5
        
        scores["timing"] = {
            "score": rt_score,
            "price_vs_52w_high": price_vs_52w_high,
            "trend_strength": trend_strength
        }
        total_score += rt_score
        
        # Calculate VST Rating (composite)
        normalized_score = round(total_score, 1)
        
        if normalized_score >= 85:
            vst_rating = "A+"
        elif normalized_score >= 75:
            vst_rating = "A"
        elif normalized_score >= 65:
            vst_rating = "B+"
        elif normalized_score >= 55:
            vst_rating = "B"
        elif normalized_score >= 45:
            vst_rating = "C"
        else:
            vst_rating = "D"
        
        return {
            "category": "fundamental",
            "score": normalized_score,
            "vst_rating": vst_rating,
            "components": scores
        }
    
    # ==================== CATALYST SCORING (20%) ====================
    
    def score_catalyst(self, data: Dict) -> Dict:
        """
        Enhanced SMB-style catalyst scoring (0-100)
        Major weight on fundamental-changing events
        """
        scores = {}
        total_score = 50  # Start neutral
        direction_points = 0
        
        # 1. Earnings Impact (40 points swing)
        earnings_surprise_pct = data.get("earnings_surprise_pct", 0)
        
        # Large earnings surprises per user's rules
        if abs(earnings_surprise_pct) > 20:
            earnings_score = 40 if earnings_surprise_pct > 0 else -40
            direction_points += 15 if earnings_surprise_pct > 0 else -15
        elif abs(earnings_surprise_pct) > 10:
            earnings_score = 25 if earnings_surprise_pct > 0 else -25
            direction_points += 10 if earnings_surprise_pct > 0 else -10
        elif abs(earnings_surprise_pct) > 5:
            earnings_score = 15 if earnings_surprise_pct > 0 else -15
        else:
            earnings_score = 0
        
        scores["earnings"] = {
            "surprise_pct": earnings_surprise_pct,
            "score_adjustment": earnings_score
        }
        total_score += earnings_score
        
        # 2. Fundamental News (30 points swing)
        news_impact = data.get("news_impact", 0)  # -10 to +10 SMB scale
        news_type = data.get("news_type", "")
        
        fundamental_changing = ["acquisition", "merger", "fda_approval", "major_contract",
                               "bankruptcy", "fraud", "delisting", "ceo_change"]
        
        if news_type.lower() in fundamental_changing:
            news_score = news_impact * 3  # Amplify fundamental changes
            direction_points += news_impact
        else:
            news_score = news_impact * 1.5
        
        scores["news"] = {
            "impact": news_impact,
            "type": news_type,
            "score_adjustment": news_score
        }
        total_score += news_score
        
        # 3. Analyst Actions (15 points swing)
        analyst_action = data.get("analyst_action", "none")  # upgrade, downgrade, initiate, none
        price_target_change_pct = data.get("price_target_change_pct", 0)
        
        if analyst_action == "upgrade":
            analyst_score = 10 + min(price_target_change_pct / 2, 5)
            direction_points += 3
        elif analyst_action == "downgrade":
            analyst_score = -10 - min(abs(price_target_change_pct) / 2, 5)
            direction_points -= 3
        else:
            analyst_score = 0
        
        scores["analyst"] = {
            "action": analyst_action,
            "pt_change_pct": price_target_change_pct,
            "score_adjustment": analyst_score
        }
        total_score += analyst_score
        
        # 4. Sector/Market Catalyst (15 points swing)
        sector_momentum = data.get("sector_momentum", 0)  # -5 to +5
        market_sentiment = data.get("market_sentiment", 0)  # -5 to +5
        
        context_score = (sector_momentum + market_sentiment) * 1.5
        scores["context"] = {
            "sector_momentum": sector_momentum,
            "market_sentiment": market_sentiment,
            "score_adjustment": context_score
        }
        total_score += context_score
        
        # Clamp to 0-100
        total_score = max(0, min(100, total_score))
        
        return {
            "category": "catalyst",
            "score": round(total_score, 1),
            "direction_points": direction_points,
            "components": scores
        }
    
    # ==================== RISK SCORING (10%) ====================
    
    def score_risk(self, data: Dict) -> Dict:
        """
        Risk assessment scoring (0-100, higher = better risk profile)
        """
        scores = {}
        total_score = 0
        
        # 1. Float Check (25 points)
        float_shares = data.get("float", 0)
        if float_shares >= self.MIN_FLOAT:
            float_score = 25
            meets_float = True
        elif float_shares >= self.MIN_FLOAT * 0.5:
            float_score = 15
            meets_float = False
        else:
            float_score = 5
            meets_float = False
        
        scores["float"] = {
            "score": float_score,
            "shares": float_shares,
            "minimum": self.MIN_FLOAT,
            "meets_requirement": meets_float
        }
        total_score += float_score
        
        # 2. Short Interest (25 points)
        short_interest_pct = data.get("short_interest_pct", 0)
        shares_to_short = data.get("shares_available_to_short", 0)
        
        # High short interest with shares available = squeeze potential
        if short_interest_pct > 20 and shares_to_short >= 250000:
            short_score = 25  # Squeeze watchlist candidate
            squeeze_potential = True
        elif short_interest_pct > 15:
            short_score = 20
            squeeze_potential = True
        elif short_interest_pct > 10:
            short_score = 15
            squeeze_potential = False
        else:
            short_score = 10
            squeeze_potential = False
        
        scores["short_interest"] = {
            "score": short_score,
            "percent": short_interest_pct,
            "shares_available": shares_to_short,
            "squeeze_potential": squeeze_potential
        }
        total_score += short_score
        
        # 3. Risk/Reward Assessment (25 points)
        atr = data.get("atr", 0)
        current_price = data.get("current_price", 0)
        support_distance = data.get("support_distance", 0)
        resistance_distance = data.get("resistance_distance", 0)
        
        if support_distance > 0 and resistance_distance > 0:
            rr_ratio = resistance_distance / support_distance
            if rr_ratio >= 3:
                rr_score = 25
            elif rr_ratio >= 2:
                rr_score = 20
            elif rr_ratio >= 1.5:
                rr_score = 15
            else:
                rr_score = 10
        else:
            rr_score = 12  # Neutral
            rr_ratio = 0
        
        scores["risk_reward"] = {
            "score": rr_score,
            "ratio": round(rr_ratio, 2) if rr_ratio else 0,
            "atr": atr
        }
        total_score += rr_score
        
        # 4. Liquidity (25 points)
        avg_volume = data.get("avg_volume", 0)
        spread_pct = data.get("bid_ask_spread_pct", 0)
        
        if avg_volume > 5_000_000 and spread_pct < 0.1:
            liquidity_score = 25
        elif avg_volume > 1_000_000:
            liquidity_score = 20
        elif avg_volume > 500_000:
            liquidity_score = 15
        else:
            liquidity_score = 10
        
        scores["liquidity"] = {
            "score": liquidity_score,
            "avg_volume": avg_volume,
            "spread_pct": spread_pct
        }
        total_score += liquidity_score
        
        return {
            "category": "risk",
            "score": round(total_score, 1),
            "components": scores
        }
    
    # ==================== CONTEXT SCORING (15%) ====================
    
    def score_context(self, data: Dict, market_data: Dict) -> Dict:
        """
        Market context alignment scoring (0-100)
        """
        scores = {}
        total_score = 0
        direction_points = 0
        
        # 1. Market Regime Alignment (35 points)
        market_regime = market_data.get("regime", "neutral")
        stock_bias = data.get("bias", "neutral")
        
        alignment_matrix = {
            ("bullish", "long"): 35,
            ("bullish", "neutral"): 20,
            ("bullish", "short"): 5,
            ("bearish", "short"): 35,
            ("bearish", "neutral"): 20,
            ("bearish", "long"): 5,
            ("neutral", "neutral"): 25,
            ("neutral", "long"): 20,
            ("neutral", "short"): 20,
        }
        
        regime_score = alignment_matrix.get((market_regime, stock_bias), 15)
        scores["regime_alignment"] = {
            "score": regime_score,
            "market_regime": market_regime,
            "stock_bias": stock_bias
        }
        total_score += regime_score
        
        # 2. Sector Relative Strength (35 points)
        sector_rank = data.get("sector_rank", 50)  # 1-100, 1 is best
        
        if sector_rank <= 10:
            sector_score = 35
            direction_points += 5
        elif sector_rank <= 25:
            sector_score = 28
            direction_points += 3
        elif sector_rank <= 50:
            sector_score = 20
        elif sector_rank <= 75:
            sector_score = 12
            direction_points -= 3
        else:
            sector_score = 5
            direction_points -= 5
        
        scores["sector_strength"] = {
            "score": sector_score,
            "rank": sector_rank
        }
        total_score += sector_score
        
        # 3. Strategy Match (30 points)
        matched_strategies = data.get("matched_strategies", [])
        high_prob_strategies = ["rubber_band", "vwap_bounce", "breakout_confirmation",
                               "trend_continuation", "mean_reversion"]
        
        strategy_score = 0
        for strat in matched_strategies:
            if strat.lower() in high_prob_strategies:
                strategy_score += 10
            else:
                strategy_score += 5
        strategy_score = min(strategy_score, 30)
        
        scores["strategy_match"] = {
            "score": strategy_score,
            "matched": matched_strategies
        }
        total_score += strategy_score
        
        return {
            "category": "context",
            "score": round(total_score, 1),
            "direction_points": direction_points,
            "components": scores
        }
    
    # ==================== SUPPORT/RESISTANCE LEVELS ====================
    
    def calculate_key_levels(self, data: Dict) -> Dict:
        """
        Calculate 3 key support and 3 key resistance levels
        """
        current_price = data.get("current_price", 0)
        high_of_day = data.get("high", current_price)
        low_of_day = data.get("low", current_price)
        vwap = data.get("vwap", current_price)
        prev_close = data.get("prev_close", current_price)
        prev_high = data.get("prev_high", current_price)
        prev_low = data.get("prev_low", current_price)
        sma_20 = data.get("sma_20", current_price)
        sma_50 = data.get("sma_50", current_price)
        
        # Collect all potential levels
        all_levels = [
            {"level": high_of_day, "type": "HOD", "strength": 3},
            {"level": low_of_day, "type": "LOD", "strength": 3},
            {"level": vwap, "type": "VWAP", "strength": 4},
            {"level": prev_close, "type": "Prev Close", "strength": 2},
            {"level": prev_high, "type": "Prev High", "strength": 3},
            {"level": prev_low, "type": "Prev Low", "strength": 3},
            {"level": sma_20, "type": "20 SMA", "strength": 2},
            {"level": sma_50, "type": "50 SMA", "strength": 2},
        ]
        
        # Round numbers
        if current_price > 10:
            round_above = math.ceil(current_price / 5) * 5
            round_below = math.floor(current_price / 5) * 5
            all_levels.append({"level": round_above, "type": "Round Number", "strength": 1})
            all_levels.append({"level": round_below, "type": "Round Number", "strength": 1})
        
        # Filter and sort for support (below current price)
        supports = sorted(
            [l for l in all_levels if l["level"] < current_price and l["level"] > 0],
            key=lambda x: x["level"],
            reverse=True
        )[:3]
        
        # Filter and sort for resistance (above current price)
        resistances = sorted(
            [l for l in all_levels if l["level"] > current_price],
            key=lambda x: x["level"]
        )[:3]
        
        return {
            "support_levels": [
                {
                    "price": round(s["level"], 2),
                    "type": s["type"],
                    "distance_pct": round(((current_price - s["level"]) / current_price) * 100, 2)
                } for s in supports
            ],
            "resistance_levels": [
                {
                    "price": round(r["level"], 2),
                    "type": r["type"],
                    "distance_pct": round(((r["level"] - current_price) / current_price) * 100, 2)
                } for r in resistances
            ]
        }
    
    # ==================== SUCCESS PROBABILITY ====================
    
    def calculate_success_probability(self, composite_score: float, direction: str,
                                      market_regime: str, rvol_meets: bool,
                                      catalyst_score: float) -> Dict:
        """
        Calculate probability of success based on historical patterns
        and rule compliance
        """
        base_probability = 45  # Start at 45%
        
        # Score impact (+/- 20%)
        if composite_score >= 80:
            base_probability += 20
        elif composite_score >= 70:
            base_probability += 15
        elif composite_score >= 60:
            base_probability += 10
        elif composite_score >= 50:
            base_probability += 5
        elif composite_score < 40:
            base_probability -= 10
        
        # RVOL compliance (+/- 10%)
        if rvol_meets:
            base_probability += 10
        else:
            base_probability -= 5
        
        # Market regime alignment (+/- 10%)
        if (direction == "LONG" and market_regime == "bullish") or \
           (direction == "SHORT" and market_regime == "bearish"):
            base_probability += 10
        elif (direction == "LONG" and market_regime == "bearish") or \
             (direction == "SHORT" and market_regime == "bullish"):
            base_probability -= 10
        
        # Catalyst strength (+/- 10%)
        if catalyst_score >= 70:
            base_probability += 10
        elif catalyst_score >= 50:
            base_probability += 5
        elif catalyst_score < 30:
            base_probability -= 5
        
        # Clamp to 20-90%
        probability = max(20, min(90, base_probability))
        
        confidence = "HIGH" if probability >= 70 else "MEDIUM" if probability >= 50 else "LOW"
        
        return {
            "probability": probability,
            "confidence": confidence,
            "factors": {
                "score_impact": composite_score >= 60,
                "rvol_compliant": rvol_meets,
                "regime_aligned": market_regime in ["bullish", "bearish"],
                "catalyst_strong": catalyst_score >= 50
            }
        }
    
    # ==================== COMPOSITE SCORING ====================
    
    def calculate_composite_score(self, stock_data: Dict, market_data: Dict = None) -> Dict:
        """
        Calculate comprehensive composite score for a stock
        Returns full analysis with direction, timeframe recommendations, and key levels
        """
        if market_data is None:
            market_data = {"regime": "neutral"}
        
        # Calculate all category scores
        technical = self.score_technical(stock_data)
        fundamental = self.score_fundamental(stock_data)
        catalyst = self.score_catalyst(stock_data)
        risk = self.score_risk(stock_data)
        context = self.score_context(stock_data, market_data)
        
        # Weighted composite score
        composite = (
            technical["score"] * self.CATEGORY_WEIGHTS["technical"] +
            fundamental["score"] * self.CATEGORY_WEIGHTS["fundamental"] +
            catalyst["score"] * self.CATEGORY_WEIGHTS["catalyst"] +
            risk["score"] * self.CATEGORY_WEIGHTS["risk"] +
            context["score"] * self.CATEGORY_WEIGHTS["context"]
        )
        
        # Calculate direction bias from all signals
        total_direction = (
            technical.get("direction_points", 0) +
            catalyst.get("direction_points", 0) +
            context.get("direction_points", 0)
        )
        
        if total_direction >= 15:
            direction = DirectionBias.STRONG_LONG
        elif total_direction >= 5:
            direction = DirectionBias.LONG
        elif total_direction <= -15:
            direction = DirectionBias.STRONG_SHORT
        elif total_direction <= -5:
            direction = DirectionBias.SHORT
        else:
            direction = DirectionBias.NEUTRAL
        
        # Letter grade
        if composite >= 85:
            grade = "A+"
        elif composite >= 80:
            grade = "A"
        elif composite >= 75:
            grade = "A-"
        elif composite >= 70:
            grade = "B+"
        elif composite >= 65:
            grade = "B"
        elif composite >= 60:
            grade = "B-"
        elif composite >= 55:
            grade = "C+"
        elif composite >= 50:
            grade = "C"
        else:
            grade = "D"
        
        # Determine best timeframe
        rvol_meets = technical["components"]["rvol"]["meets_threshold"]
        gap_meets = technical["components"]["gap"]["meets_threshold"]
        
        if rvol_meets and gap_meets:
            primary_timeframe = TimeframeType.INTRADAY
        elif fundamental["score"] >= 70:
            primary_timeframe = TimeframeType.LONGTERM
        else:
            primary_timeframe = TimeframeType.SWING
        
        # Key levels
        key_levels = self.calculate_key_levels(stock_data)
        
        # Success probability
        success_prob = self.calculate_success_probability(
            composite,
            direction.value.replace("STRONG_", ""),
            market_data.get("regime", "neutral"),
            rvol_meets,
            catalyst["score"]
        )
        
        return {
            "symbol": stock_data.get("symbol", "UNKNOWN"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "composite_score": round(composite, 1),
            "grade": grade,
            "direction": direction.value,
            "direction_strength": abs(total_direction),
            "primary_timeframe": primary_timeframe.value,
            "success_probability": success_prob,
            "key_levels": key_levels,
            "category_scores": {
                "technical": technical,
                "fundamental": fundamental,
                "catalyst": catalyst,
                "risk": risk,
                "context": context
            },
            "quick_stats": {
                "rvol": stock_data.get("rvol", 0),
                "gap_pct": stock_data.get("gap_percent", 0),
                "vwap_position": technical["components"]["vwap"]["position"],
                "float_ok": risk["components"]["float"]["meets_requirement"],
                "squeeze_watch": risk["components"]["short_interest"]["squeeze_potential"]
            }
        }
    
    # ==================== BATCH SCORING ====================
    
    async def score_batch(self, stocks: List[Dict], market_data: Dict = None) -> List[Dict]:
        """Score multiple stocks and return sorted by composite score"""
        scores = []
        for stock in stocks:
            score = self.calculate_composite_score(stock, market_data)
            scores.append(score)
        
        # Sort by composite score descending
        scores.sort(key=lambda x: x["composite_score"], reverse=True)
        return scores
    
    def get_top_picks(self, scores: List[Dict], timeframe: str = None, 
                      direction: str = None, limit: int = 10) -> List[Dict]:
        """Filter and return top picks based on criteria"""
        filtered = scores
        
        if timeframe:
            filtered = [s for s in filtered if s["primary_timeframe"] == timeframe]
        
        if direction:
            if direction.upper() == "LONG":
                filtered = [s for s in filtered if "LONG" in s["direction"]]
            elif direction.upper() == "SHORT":
                filtered = [s for s in filtered if "SHORT" in s["direction"]]
        
        return filtered[:limit]


# Singleton
_scoring_engine: Optional[UniversalScoringEngine] = None

def get_scoring_engine(db=None) -> UniversalScoringEngine:
    global _scoring_engine
    if _scoring_engine is None:
        _scoring_engine = UniversalScoringEngine(db)
    return _scoring_engine
