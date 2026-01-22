"""
Catalyst Scoring Router - API endpoints for catalyst scoring system
Scores earnings, news, technical, and sentiment catalysts on a -10 to +10 scale
"""
from fastapi import APIRouter, HTTPException
from typing import Optional, List, Dict
from pydantic import BaseModel

router = APIRouter(prefix="/api/catalyst", tags=["catalyst"])

# Will be initialized from main server
catalyst_scoring_service = None
stock_service = None

def init_catalyst_service(catalyst_svc, stock_svc=None):
    global catalyst_scoring_service, stock_service
    catalyst_scoring_service = catalyst_svc
    stock_service = stock_svc


# ===================== PYDANTIC MODELS =====================

class EarningsScoreRequest(BaseModel):
    symbol: str
    revenue_actual: Optional[float] = 0
    revenue_estimate: Optional[float] = 0
    revenue_prior_year: Optional[float] = 0
    eps_actual: Optional[float] = 0
    eps_estimate: Optional[float] = 0
    margin_current: Optional[float] = 0
    margin_prior_year: Optional[float] = 0
    rev_guide_vs_consensus_pct: Optional[float] = 0
    eps_guide_vs_consensus_pct: Optional[float] = 0
    prior_close: Optional[float] = 0
    open_price: Optional[float] = 0
    high_price: Optional[float] = 0
    low_price: Optional[float] = 0
    close_price: Optional[float] = 0
    volume: Optional[int] = 0
    avg_volume_20d: Optional[int] = 0


class NewsScoreRequest(BaseModel):
    symbol: str
    impact_level: str = "medium"  # high, medium, low
    surprise_factor: str = "neutral"  # major_positive, positive, neutral, negative, major_negative
    duration: str = "short_term"  # one_time, short_term, long_term
    sentiment: str = "neutral"  # very_bullish, bullish, neutral, bearish, very_bearish
    volume_reaction: Optional[float] = 1.0
    headline: Optional[str] = ""


class TechnicalScoreRequest(BaseModel):
    symbol: str
    breakout_type: str = "none"  # resistance, support, channel, pattern, none
    confirmation_volume: Optional[float] = 1.0
    trend_alignment: str = "neutral"  # with_trend, neutral, against_trend
    key_level_distance_pct: Optional[float] = 5.0
    rsi: Optional[float] = 50


class SentimentScoreRequest(BaseModel):
    symbol: str
    social_sentiment: str = "neutral"  # very_bullish, bullish, neutral, bearish, very_bearish
    analyst_rating_change: str = "none"  # upgrade, none, downgrade
    institutional_activity: str = "none"  # accumulation, none, distribution
    short_interest_change_pct: Optional[float] = 0
    news_volume_spike: Optional[bool] = False


class QuickScoreRequest(BaseModel):
    symbol: str
    # Simplified inputs for quick scoring
    eps_beat_pct: Optional[float] = 0  # % EPS beat/miss
    revenue_beat_pct: Optional[float] = 0  # % revenue beat/miss
    guidance: str = "inline"  # raised, inline, lowered, cut
    price_reaction_pct: Optional[float] = 0  # Stock move %
    volume_multiple: Optional[float] = 1.0  # Volume vs average


# ===================== ENDPOINTS =====================

@router.post("/score/earnings")
async def score_earnings(request: EarningsScoreRequest):
    """
    Calculate comprehensive earnings catalyst score (-10 to +10)
    Components: Revenue, EPS, Margins, Guidance, Tape Reaction
    """
    if not catalyst_scoring_service:
        raise HTTPException(500, "Catalyst scoring service not initialized")
    
    earnings_data = {
        "symbol": request.symbol.upper(),
        "revenue_actual": request.revenue_actual,
        "revenue_estimate": request.revenue_estimate,
        "revenue_prior_year": request.revenue_prior_year,
        "eps_actual": request.eps_actual,
        "eps_estimate": request.eps_estimate,
        "margin_current": request.margin_current,
        "margin_prior_year": request.margin_prior_year,
        "rev_guide_vs_consensus_pct": request.rev_guide_vs_consensus_pct,
        "eps_guide_vs_consensus_pct": request.eps_guide_vs_consensus_pct,
        "prior_close": request.prior_close,
        "open_price": request.open_price,
        "high_price": request.high_price,
        "low_price": request.low_price,
        "close_price": request.close_price,
        "volume": request.volume,
        "avg_volume_20d": request.avg_volume_20d
    }
    
    score = catalyst_scoring_service.calculate_earnings_score(earnings_data)
    
    # Save to database
    await catalyst_scoring_service.save_catalyst(request.symbol, score)
    
    return score


@router.post("/score/quick")
async def score_quick(request: QuickScoreRequest):
    """
    Quick earnings score with simplified inputs
    Ideal for rapid scoring when full data isn't available
    """
    if not catalyst_scoring_service:
        raise HTTPException(500, "Catalyst scoring service not initialized")
    
    # Map simplified inputs to full scoring inputs
    guidance_map = {
        "raised": 3,
        "inline": 0,
        "lowered": -3,
        "cut": -5
    }
    
    # Calculate quick score components
    eps_score = min(2, max(-2, request.eps_beat_pct / 2.5))
    rev_score = min(2, max(-2, request.revenue_beat_pct / 3))
    guide_score = guidance_map.get(request.guidance, 0) / 2.5  # Scale to -2 to +2
    
    # Tape reaction score
    if request.volume_multiple >= 2 and request.price_reaction_pct >= 5:
        tape_score = 2
    elif request.volume_multiple >= 1.5 and request.price_reaction_pct >= 2:
        tape_score = 1
    elif abs(request.price_reaction_pct) < 2:
        tape_score = 0
    elif request.price_reaction_pct <= -2:
        tape_score = -1 if request.price_reaction_pct > -5 else -2
    else:
        tape_score = 0
    
    raw_score = round(eps_score + rev_score + guide_score + tape_score, 1)
    raw_score = max(-10, min(10, raw_score * 2))  # Scale to -10 to +10
    
    # Determine rating
    if raw_score >= 8:
        rating, bias = "A+", "STRONG_LONG"
        interpretation = "Elite positive catalyst"
    elif raw_score >= 4:
        rating, bias = "B+", "LONG"
        interpretation = "Tradable positive catalyst"
    elif raw_score >= -3:
        rating, bias = "C", "NEUTRAL"
        interpretation = "Mixed/neutral catalyst"
    elif raw_score >= -7:
        rating, bias = "D", "SHORT"
        interpretation = "Negative catalyst"
    else:
        rating, bias = "F", "STRONG_SHORT"
        interpretation = "Strong negative catalyst"
    
    return {
        "symbol": request.symbol.upper(),
        "catalyst_type": "EARNINGS",
        "raw_score": raw_score,
        "normalized_score": round((raw_score + 10) / 2, 2),
        "rating": rating,
        "bias": bias,
        "interpretation": interpretation,
        "components": {
            "eps_beat": {"score": round(eps_score, 2), "input_pct": request.eps_beat_pct},
            "revenue_beat": {"score": round(rev_score, 2), "input_pct": request.revenue_beat_pct},
            "guidance": {"score": round(guide_score, 2), "direction": request.guidance},
            "tape_reaction": {"score": tape_score, "price_pct": request.price_reaction_pct, "rvol": request.volume_multiple}
        }
    }


@router.post("/score/news")
async def score_news(request: NewsScoreRequest):
    """
    Score news/event catalyst (-10 to +10)
    Components: Impact, Surprise, Duration, Sentiment, Volume
    """
    if not catalyst_scoring_service:
        raise HTTPException(500, "Catalyst scoring service not initialized")
    
    score = catalyst_scoring_service.score_news_catalyst(
        impact_level=request.impact_level,
        surprise_factor=request.surprise_factor,
        duration=request.duration,
        sentiment=request.sentiment,
        volume_reaction=request.volume_reaction
    )
    
    score["symbol"] = request.symbol.upper()
    score["headline"] = request.headline
    
    # Save to database
    await catalyst_scoring_service.save_catalyst(request.symbol, score)
    
    return score


@router.post("/score/technical")
async def score_technical(request: TechnicalScoreRequest):
    """
    Score technical catalyst (-10 to +10)
    Components: Breakout type, Volume confirmation, Trend alignment, Key levels, RSI
    """
    if not catalyst_scoring_service:
        raise HTTPException(500, "Catalyst scoring service not initialized")
    
    score = catalyst_scoring_service.score_technical_catalyst(
        breakout_type=request.breakout_type,
        confirmation_volume=request.confirmation_volume,
        trend_alignment=request.trend_alignment,
        key_level_distance_pct=request.key_level_distance_pct,
        rsi=request.rsi
    )
    
    score["symbol"] = request.symbol.upper()
    
    # Save to database
    await catalyst_scoring_service.save_catalyst(request.symbol, score)
    
    return score


@router.post("/score/sentiment")
async def score_sentiment(request: SentimentScoreRequest):
    """
    Score sentiment catalyst (-10 to +10)
    Components: Social sentiment, Analyst ratings, Institutional activity, Short interest
    """
    if not catalyst_scoring_service:
        raise HTTPException(500, "Catalyst scoring service not initialized")
    
    score = catalyst_scoring_service.score_sentiment_catalyst(
        social_sentiment=request.social_sentiment,
        analyst_rating_change=request.analyst_rating_change,
        institutional_activity=request.institutional_activity,
        short_interest_change_pct=request.short_interest_change_pct,
        news_volume_spike=request.news_volume_spike
    )
    
    score["symbol"] = request.symbol.upper()
    
    # Save to database
    await catalyst_scoring_service.save_catalyst(request.symbol, score)
    
    return score


@router.post("/score/combined")
async def score_combined(catalysts: List[Dict]):
    """
    Combine multiple catalyst scores into aggregate score
    Weighted by catalyst type importance
    """
    if not catalyst_scoring_service:
        raise HTTPException(500, "Catalyst scoring service not initialized")
    
    combined = catalyst_scoring_service.calculate_combined_score(catalysts)
    return combined


@router.get("/history/{symbol}")
async def get_catalyst_history(
    symbol: str,
    catalyst_type: Optional[str] = None,
    min_score: Optional[int] = None,
    limit: int = 20
):
    """Get catalyst scoring history for a symbol"""
    if not catalyst_scoring_service:
        raise HTTPException(500, "Catalyst scoring service not initialized")
    
    catalysts = await catalyst_scoring_service.get_catalysts(
        symbol=symbol,
        catalyst_type=catalyst_type,
        min_score=min_score,
        limit=limit
    )
    
    return {
        "symbol": symbol.upper(),
        "catalysts": catalysts,
        "count": len(catalysts)
    }


@router.get("/recent")
async def get_recent_catalysts(
    min_score: Optional[int] = None,
    catalyst_type: Optional[str] = None,
    limit: int = 50
):
    """Get recent catalyst scores across all symbols"""
    if not catalyst_scoring_service:
        raise HTTPException(500, "Catalyst scoring service not initialized")
    
    catalysts = await catalyst_scoring_service.get_catalysts(
        catalyst_type=catalyst_type,
        min_score=min_score,
        limit=limit
    )
    
    return {
        "catalysts": catalysts,
        "count": len(catalysts)
    }


@router.get("/score-guide")
async def get_score_guide():
    """Get the scoring guide and rubric explanation"""
    return {
        "scale": {
            "description": "Scores range from -10 to +10",
            "ratings": {
                "A+": {"range": [8, 10], "bias": "STRONG_LONG", "action": "Elite long opportunity"},
                "B+": {"range": [4, 7], "bias": "LONG", "action": "Tradable long"},
                "C": {"range": [-3, 3], "bias": "NEUTRAL", "action": "Mixed/wait for clarity"},
                "D": {"range": [-7, -4], "bias": "SHORT", "action": "Negative catalyst, short opportunity"},
                "F": {"range": [-10, -8], "bias": "STRONG_SHORT", "action": "Elite short opportunity"}
            }
        },
        "earnings_components": {
            "revenue": {"range": [-2, 2], "description": "Beat/miss vs estimate and YoY growth"},
            "eps": {"range": [-2, 2], "description": "EPS surprise magnitude"},
            "margins": {"range": [-2, 2], "description": "Margin expansion/compression"},
            "guidance": {"range": [-2, 2], "description": "Forward guidance vs consensus"},
            "tape": {"range": [-2, 2], "description": "Market reaction quality (volume, price action)"}
        },
        "news_components": {
            "impact": {"range": [0, 2], "options": ["low", "medium", "high"]},
            "surprise": {"range": [-3, 3], "options": ["major_negative", "negative", "neutral", "positive", "major_positive"]},
            "duration": {"multiplier": [0.5, 1.5], "options": ["one_time", "short_term", "long_term"]},
            "sentiment": {"range": [-3, 3], "options": ["very_bearish", "bearish", "neutral", "bullish", "very_bullish"]},
            "volume": {"range": [-1, 1], "description": "Volume confirmation"}
        },
        "technical_components": {
            "breakout": {"range": [-2, 3], "options": ["support", "none", "channel", "pattern", "resistance"]},
            "volume": {"range": [-2, 3], "description": "Volume confirmation RVOL"},
            "trend": {"range": [-2, 2], "options": ["against_trend", "neutral", "with_trend"]},
            "level": {"range": [-1, 2], "description": "Proximity to key S/R level"},
            "rsi": {"range": [-1, 0], "description": "Overbought/oversold adjustment"}
        }
    }
