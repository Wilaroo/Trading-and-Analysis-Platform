"""
Catalyst Scoring System
Evaluates earnings, news, geopolitical events, technical catalysts, and sentiment
Uses SMB-style -10 to +10 scoring system
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
from enum import Enum
import math

class CatalystType(str, Enum):
    EARNINGS = "EARNINGS"
    NEWS = "NEWS"
    GEOPOLITICAL = "GEOPOLITICAL"
    FUNDAMENTAL_CHANGE = "FUNDAMENTAL_CHANGE"
    TECHNICAL = "TECHNICAL"
    SOCIAL_SENTIMENT = "SOCIAL_SENTIMENT"


class CatalystScoringService:
    """
    SMB-style catalyst scoring system
    Outputs -10 to +10 score based on:
    - Earnings: Revenue, EPS, Margins, Guidance, Tape
    - News/Events: Impact, Surprise, Duration
    - Technical: Breakout confirmation, Volume
    - Sentiment: Social media, analyst ratings
    """
    
    def __init__(self, db=None):
        self.db = db
        if db:
            self.catalysts_col = db["catalysts"]
            self.templates_col = db["catalyst_templates"]
    
    # ==================== EARNINGS CATALYST SCORING ====================
    
    def score_revenue(self, actual: float, estimate: float, prior_year: float = None) -> Dict:
        """
        Score revenue performance (-2 to +2)
        RevSurprise = (actual - estimate) / estimate
        RevGrowth = (actual - prior_year) / prior_year
        """
        if estimate <= 0:
            return {"score": 0, "surprise_pct": 0, "growth_pct": 0, "analysis": "Invalid estimate"}
        
        surprise_pct = ((actual - estimate) / estimate) * 100
        growth_pct = ((actual - prior_year) / prior_year * 100) if prior_year and prior_year > 0 else 0
        
        # Scoring logic
        if surprise_pct >= 3 and growth_pct >= 10:
            score = 2
            analysis = "Strong beat with double-digit growth"
        elif surprise_pct >= 1 or growth_pct >= 5:
            score = 1
            analysis = "Solid beat or good growth"
        elif surprise_pct >= -1:
            score = 0
            analysis = "In-line revenue"
        elif surprise_pct >= -3:
            score = -1
            analysis = "Revenue miss"
        else:
            score = -2
            analysis = "Significant revenue miss"
        
        return {
            "score": score,
            "surprise_pct": round(surprise_pct, 2),
            "growth_pct": round(growth_pct, 2),
            "analysis": analysis
        }
    
    def score_eps(self, actual: float, estimate: float) -> Dict:
        """
        Score EPS performance (-2 to +2)
        EPSSurprise = (actual - estimate) / |estimate|
        """
        if estimate == 0:
            return {"score": 0, "surprise_pct": 0, "analysis": "No EPS estimate"}
        
        surprise_pct = ((actual - estimate) / abs(estimate)) * 100
        
        if surprise_pct >= 5:
            score = 2
            analysis = "Strong EPS beat (≥5%)"
        elif surprise_pct >= 1:
            score = 1
            analysis = "EPS beat"
        elif surprise_pct >= -1:
            score = 0
            analysis = "In-line EPS"
        elif surprise_pct >= -5:
            score = -1
            analysis = "EPS miss"
        else:
            score = -2
            analysis = "Significant EPS miss (≥5%)"
        
        return {
            "score": score,
            "surprise_pct": round(surprise_pct, 2),
            "analysis": analysis
        }
    
    def score_margins(self, current_margin: float, prior_year_margin: float) -> Dict:
        """
        Score margin expansion/compression (-2 to +2)
        MarginDelta = current - prior_year (percentage points)
        """
        margin_delta = current_margin - prior_year_margin
        
        if margin_delta >= 2:
            score = 2
            analysis = "Strong margin expansion (≥2pts)"
        elif margin_delta >= 0.5:
            score = 1
            analysis = "Margin expansion"
        elif margin_delta >= -0.5:
            score = 0
            analysis = "Stable margins"
        elif margin_delta >= -2:
            score = -1
            analysis = "Margin compression"
        else:
            score = -2
            analysis = "Significant margin compression (≥2pts)"
        
        return {
            "score": score,
            "margin_delta_pts": round(margin_delta, 2),
            "analysis": analysis
        }
    
    def score_guidance(
        self, 
        rev_guide_vs_consensus_pct: float = 0,
        eps_guide_vs_consensus_pct: float = 0
    ) -> Dict:
        """
        Score forward guidance (-2 to +2)
        Based on revenue and EPS guidance vs prior/consensus
        """
        # Take the stronger signal
        best_signal = max(rev_guide_vs_consensus_pct, eps_guide_vs_consensus_pct)
        worst_signal = min(rev_guide_vs_consensus_pct, eps_guide_vs_consensus_pct)
        
        if best_signal >= 5 or (rev_guide_vs_consensus_pct >= 3 and eps_guide_vs_consensus_pct >= 3):
            score = 2
            analysis = "Strong guidance raise"
        elif best_signal >= 1:
            score = 1
            analysis = "Guidance raised / good enough"
        elif worst_signal >= -1:
            score = 0
            analysis = "In-line guidance"
        elif worst_signal >= -5:
            score = -1
            analysis = "Guidance lowered"
        else:
            score = -2
            analysis = "Significant guidance cut"
        
        return {
            "score": score,
            "rev_guide_pct": round(rev_guide_vs_consensus_pct, 2),
            "eps_guide_pct": round(eps_guide_vs_consensus_pct, 2),
            "analysis": analysis
        }
    
    def score_tape_reaction(
        self,
        prior_close: float,
        open_price: float,
        high_price: float,
        low_price: float,
        close_price: float,
        volume: int,
        avg_volume_20d: int
    ) -> Dict:
        """
        Score market reaction / tape (-2 to +2)
        SMB cares about how market "votes" on the catalyst
        """
        if prior_close <= 0 or avg_volume_20d <= 0:
            return {"score": 0, "analysis": "Insufficient data"}
        
        gap_pct = ((open_price - prior_close) / prior_close) * 100
        close_pct = ((close_price - prior_close) / prior_close) * 100
        rvol = volume / avg_volume_20d
        
        # Intraday fade for gap-ups
        if gap_pct > 0 and high_price > open_price:
            intraday_range = high_price - low_price
            fade_from_high = high_price - close_price
            intraday_fade_pct = (fade_from_high / intraday_range * 100) if intraday_range > 0 else 0
        else:
            intraday_fade_pct = 0
        
        # Scoring logic
        if rvol >= 2 and close_pct >= 5 and intraday_fade_pct <= 30:
            score = 2
            analysis = "Bullish tape: High volume, strong close, held gains"
        elif rvol >= 1.5 and close_pct >= 2:
            score = 1
            analysis = "Positive tape: Good volume and close"
        elif abs(close_pct) < 2 or rvol < 1.5:
            score = 0
            analysis = "Neutral/noisy tape"
        elif close_pct <= -2 and close_pct > -5 and rvol >= 1.5:
            score = -1
            analysis = "Bearish tape: Selling on volume"
        else:
            score = -2
            analysis = "Very bearish tape: Heavy selling"
        
        return {
            "score": score,
            "gap_pct": round(gap_pct, 2),
            "close_pct": round(close_pct, 2),
            "rvol": round(rvol, 2),
            "intraday_fade_pct": round(intraday_fade_pct, 1),
            "analysis": analysis
        }
    
    def calculate_earnings_score(self, earnings_data: Dict) -> Dict:
        """
        Calculate comprehensive earnings catalyst score (-10 to +10)
        Sum of: Revenue + EPS + Margins + Guidance + Tape
        """
        # Score each component
        rev_score = self.score_revenue(
            earnings_data.get("revenue_actual", 0),
            earnings_data.get("revenue_estimate", 0),
            earnings_data.get("revenue_prior_year", 0)
        )
        
        eps_score = self.score_eps(
            earnings_data.get("eps_actual", 0),
            earnings_data.get("eps_estimate", 0)
        )
        
        margin_score = self.score_margins(
            earnings_data.get("margin_current", 0),
            earnings_data.get("margin_prior_year", 0)
        )
        
        guide_score = self.score_guidance(
            earnings_data.get("rev_guide_vs_consensus_pct", 0),
            earnings_data.get("eps_guide_vs_consensus_pct", 0)
        )
        
        tape_score = self.score_tape_reaction(
            earnings_data.get("prior_close", 0),
            earnings_data.get("open_price", 0),
            earnings_data.get("high_price", 0),
            earnings_data.get("low_price", 0),
            earnings_data.get("close_price", 0),
            earnings_data.get("volume", 0),
            earnings_data.get("avg_volume_20d", 0)
        )
        
        # Calculate raw score (-10 to +10)
        raw_score = (
            rev_score["score"] + 
            eps_score["score"] + 
            margin_score["score"] + 
            guide_score["score"] + 
            tape_score["score"]
        )
        
        # Also calculate 0-10 normalized score
        normalized_score = round((raw_score + 10) / 2, 2)
        
        # Interpretation
        if raw_score >= 8:
            rating = "A+"
            bias = "STRONG_LONG"
            interpretation = "Elite positive catalyst - SMB 'In Play' long bias"
        elif raw_score >= 4:
            rating = "B+"
            bias = "LONG"
            interpretation = "Tradable positive catalyst"
        elif raw_score >= -3:
            rating = "C"
            bias = "NEUTRAL"
            interpretation = "Mixed/neutral - probably not a focus name"
        elif raw_score >= -7:
            rating = "D"
            bias = "SHORT"
            interpretation = "Negative catalyst"
        else:
            rating = "F"
            bias = "STRONG_SHORT"
            interpretation = "A+ short catalyst"
        
        return {
            "symbol": earnings_data.get("symbol", ""),
            "catalyst_type": CatalystType.EARNINGS.value,
            "raw_score": raw_score,
            "normalized_score": normalized_score,
            "rating": rating,
            "bias": bias,
            "interpretation": interpretation,
            "components": {
                "revenue": rev_score,
                "eps": eps_score,
                "margins": margin_score,
                "guidance": guide_score,
                "tape": tape_score
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    # ==================== NEWS/EVENT CATALYST SCORING ====================
    
    def score_news_catalyst(
        self,
        impact_level: str,  # "high", "medium", "low"
        surprise_factor: str,  # "major_positive", "positive", "neutral", "negative", "major_negative"
        duration: str,  # "one_time", "short_term", "long_term"
        sentiment: str,  # "very_bullish", "bullish", "neutral", "bearish", "very_bearish"
        volume_reaction: float = 1.0  # RVOL
    ) -> Dict:
        """
        Score news/event catalysts (-10 to +10)
        """
        # Impact score (-2 to +2)
        impact_scores = {"high": 2, "medium": 1, "low": 0}
        impact_score = impact_scores.get(impact_level.lower(), 0)
        
        # Surprise score (-3 to +3)
        surprise_scores = {
            "major_positive": 3,
            "positive": 1,
            "neutral": 0,
            "negative": -1,
            "major_negative": -3
        }
        surprise_score = surprise_scores.get(surprise_factor.lower(), 0)
        
        # Duration multiplier (0.5 to 1.5)
        duration_mult = {"one_time": 0.5, "short_term": 1.0, "long_term": 1.5}
        duration_multiplier = duration_mult.get(duration.lower(), 1.0)
        
        # Sentiment score (-3 to +3)
        sentiment_scores = {
            "very_bullish": 3,
            "bullish": 1,
            "neutral": 0,
            "bearish": -1,
            "very_bearish": -3
        }
        sentiment_score = sentiment_scores.get(sentiment.lower(), 0)
        
        # Volume confirmation (-1 to +1)
        if volume_reaction >= 2.0:
            volume_score = 1
        elif volume_reaction <= 0.5:
            volume_score = -1
        else:
            volume_score = 0
        
        # Calculate raw score
        base_score = impact_score + surprise_score + sentiment_score + volume_score
        raw_score = int(base_score * duration_multiplier)
        raw_score = max(-10, min(10, raw_score))  # Clamp to -10 to +10
        
        normalized_score = round((raw_score + 10) / 2, 2)
        
        # Rating
        if raw_score >= 6:
            rating, bias = "A", "STRONG_LONG"
        elif raw_score >= 3:
            rating, bias = "B", "LONG"
        elif raw_score >= -2:
            rating, bias = "C", "NEUTRAL"
        elif raw_score >= -5:
            rating, bias = "D", "SHORT"
        else:
            rating, bias = "F", "STRONG_SHORT"
        
        return {
            "catalyst_type": CatalystType.NEWS.value,
            "raw_score": raw_score,
            "normalized_score": normalized_score,
            "rating": rating,
            "bias": bias,
            "components": {
                "impact": {"score": impact_score, "level": impact_level},
                "surprise": {"score": surprise_score, "factor": surprise_factor},
                "duration": {"multiplier": duration_multiplier, "type": duration},
                "sentiment": {"score": sentiment_score, "level": sentiment},
                "volume": {"score": volume_score, "rvol": volume_reaction}
            }
        }
    
    # ==================== TECHNICAL CATALYST SCORING ====================
    
    def score_technical_catalyst(
        self,
        breakout_type: str,  # "resistance", "support", "channel", "pattern", "none"
        confirmation_volume: float,  # RVOL
        trend_alignment: str,  # "with_trend", "neutral", "against_trend"
        key_level_distance_pct: float,  # Distance from key S/R level
        rsi: float = 50
    ) -> Dict:
        """
        Score technical catalysts (-10 to +10)
        """
        # Breakout score (-2 to +3)
        breakout_scores = {
            "resistance": 3,
            "pattern": 2,
            "channel": 2,
            "support": -2,
            "none": 0
        }
        breakout_score = breakout_scores.get(breakout_type.lower(), 0)
        
        # Volume confirmation (-2 to +3)
        if confirmation_volume >= 3.0:
            volume_score = 3
        elif confirmation_volume >= 2.0:
            volume_score = 2
        elif confirmation_volume >= 1.5:
            volume_score = 1
        elif confirmation_volume < 0.8:
            volume_score = -2
        else:
            volume_score = 0
        
        # Trend alignment (-2 to +2)
        trend_scores = {"with_trend": 2, "neutral": 0, "against_trend": -2}
        trend_score = trend_scores.get(trend_alignment.lower(), 0)
        
        # Key level proximity (-1 to +2)
        if key_level_distance_pct <= 1:
            level_score = 2  # Very close to key level
        elif key_level_distance_pct <= 3:
            level_score = 1
        elif key_level_distance_pct > 10:
            level_score = -1
        else:
            level_score = 0
        
        # RSI context (overbought/oversold warning)
        if rsi > 80:
            rsi_adj = -1  # Overbought warning
        elif rsi < 20:
            rsi_adj = -1  # Could bounce, risky for shorts
        else:
            rsi_adj = 0
        
        raw_score = breakout_score + volume_score + trend_score + level_score + rsi_adj
        raw_score = max(-10, min(10, raw_score))
        normalized_score = round((raw_score + 10) / 2, 2)
        
        if raw_score >= 6:
            rating, bias = "A", "STRONG_LONG"
        elif raw_score >= 3:
            rating, bias = "B", "LONG"
        elif raw_score >= -2:
            rating, bias = "C", "NEUTRAL"
        else:
            rating, bias = "D", "SHORT"
        
        return {
            "catalyst_type": CatalystType.TECHNICAL.value,
            "raw_score": raw_score,
            "normalized_score": normalized_score,
            "rating": rating,
            "bias": bias,
            "components": {
                "breakout": {"score": breakout_score, "type": breakout_type},
                "volume": {"score": volume_score, "rvol": confirmation_volume},
                "trend": {"score": trend_score, "alignment": trend_alignment},
                "level": {"score": level_score, "distance_pct": key_level_distance_pct},
                "rsi": {"adjustment": rsi_adj, "value": rsi}
            }
        }
    
    # ==================== SENTIMENT CATALYST SCORING ====================
    
    def score_sentiment_catalyst(
        self,
        social_sentiment: str,  # "very_bullish" to "very_bearish"
        analyst_rating_change: str,  # "upgrade", "none", "downgrade"
        institutional_activity: str,  # "accumulation", "none", "distribution"
        short_interest_change_pct: float = 0,
        news_volume_spike: bool = False
    ) -> Dict:
        """
        Score social/analyst sentiment catalysts (-10 to +10)
        """
        # Social sentiment (-3 to +3)
        sentiment_scores = {
            "very_bullish": 3,
            "bullish": 1,
            "neutral": 0,
            "bearish": -1,
            "very_bearish": -3
        }
        social_score = sentiment_scores.get(social_sentiment.lower(), 0)
        
        # Analyst rating (-2 to +2)
        analyst_scores = {"upgrade": 2, "none": 0, "downgrade": -2}
        analyst_score = analyst_scores.get(analyst_rating_change.lower(), 0)
        
        # Institutional activity (-2 to +2)
        inst_scores = {"accumulation": 2, "none": 0, "distribution": -2}
        inst_score = inst_scores.get(institutional_activity.lower(), 0)
        
        # Short interest (-2 to +2)
        if short_interest_change_pct <= -10:
            short_score = 2  # Short covering = bullish
        elif short_interest_change_pct <= -5:
            short_score = 1
        elif short_interest_change_pct >= 10:
            short_score = -2  # Rising shorts = bearish
        elif short_interest_change_pct >= 5:
            short_score = -1
        else:
            short_score = 0
        
        # News volume spike (+1 if true, magnifies move)
        news_spike_score = 1 if news_volume_spike else 0
        
        raw_score = social_score + analyst_score + inst_score + short_score + news_spike_score
        raw_score = max(-10, min(10, raw_score))
        normalized_score = round((raw_score + 10) / 2, 2)
        
        if raw_score >= 5:
            rating, bias = "A", "STRONG_LONG"
        elif raw_score >= 2:
            rating, bias = "B", "LONG"
        elif raw_score >= -1:
            rating, bias = "C", "NEUTRAL"
        else:
            rating, bias = "D", "SHORT"
        
        return {
            "catalyst_type": CatalystType.SOCIAL_SENTIMENT.value,
            "raw_score": raw_score,
            "normalized_score": normalized_score,
            "rating": rating,
            "bias": bias,
            "components": {
                "social": {"score": social_score, "sentiment": social_sentiment},
                "analyst": {"score": analyst_score, "change": analyst_rating_change},
                "institutional": {"score": inst_score, "activity": institutional_activity},
                "short_interest": {"score": short_score, "change_pct": short_interest_change_pct},
                "news_spike": {"score": news_spike_score, "detected": news_volume_spike}
            }
        }
    
    # ==================== COMBINED/AGGREGATE SCORING ====================
    
    def calculate_combined_score(self, catalyst_scores: List[Dict]) -> Dict:
        """
        Combine multiple catalyst scores into aggregate score
        Weighted by catalyst type importance
        """
        if not catalyst_scores:
            return {"combined_score": 0, "rating": "C", "bias": "NEUTRAL"}
        
        weights = {
            CatalystType.EARNINGS.value: 1.5,
            CatalystType.NEWS.value: 1.2,
            CatalystType.GEOPOLITICAL.value: 1.0,
            CatalystType.FUNDAMENTAL_CHANGE.value: 1.3,
            CatalystType.TECHNICAL.value: 1.0,
            CatalystType.SOCIAL_SENTIMENT.value: 0.8
        }
        
        weighted_sum = 0
        total_weight = 0
        
        for score_data in catalyst_scores:
            catalyst_type = score_data.get("catalyst_type", "")
            raw_score = score_data.get("raw_score", 0)
            weight = weights.get(catalyst_type, 1.0)
            
            weighted_sum += raw_score * weight
            total_weight += weight
        
        combined_score = round(weighted_sum / total_weight, 1) if total_weight > 0 else 0
        
        if combined_score >= 6:
            rating, bias = "A", "STRONG_LONG"
        elif combined_score >= 3:
            rating, bias = "B", "LONG"
        elif combined_score >= -2:
            rating, bias = "C", "NEUTRAL"
        elif combined_score >= -5:
            rating, bias = "D", "SHORT"
        else:
            rating, bias = "F", "STRONG_SHORT"
        
        return {
            "combined_score": combined_score,
            "rating": rating,
            "bias": bias,
            "catalyst_count": len(catalyst_scores),
            "components": catalyst_scores
        }
    
    # ==================== PERSISTENCE ====================
    
    async def save_catalyst(self, symbol: str, catalyst_data: Dict) -> Dict:
        """Save catalyst score to database"""
        if not self.db:
            return catalyst_data
        
        doc = {
            "symbol": symbol.upper(),
            **catalyst_data,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        result = self.catalysts_col.insert_one(doc)
        doc["id"] = str(result.inserted_id)
        return {k: v for k, v in doc.items() if k != "_id"}
    
    async def get_catalysts(
        self, 
        symbol: str = None, 
        catalyst_type: str = None,
        min_score: int = None,
        limit: int = 50
    ) -> List[Dict]:
        """Get catalysts with optional filters"""
        if not self.db:
            return []
        
        query = {}
        if symbol:
            query["symbol"] = symbol.upper()
        if catalyst_type:
            query["catalyst_type"] = catalyst_type
        if min_score is not None:
            query["raw_score"] = {"$gte": min_score}
        
        catalysts = list(self.catalysts_col.find(
            query,
            {"_id": 0}
        ).sort("created_at", -1).limit(limit))
        
        return catalysts


# Singleton
_catalyst_service: Optional[CatalystScoringService] = None

def get_catalyst_scoring_service(db=None) -> CatalystScoringService:
    global _catalyst_service
    if _catalyst_service is None:
        _catalyst_service = CatalystScoringService(db)
    return _catalyst_service
