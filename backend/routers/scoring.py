"""
Scoring Engine API Router
Endpoints for Universal Scoring System and Top Picks
"""
from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from services.scoring_engine import get_scoring_engine, TimeframeType

router = APIRouter(prefix="/api/scoring", tags=["scoring"])


class StockDataInput(BaseModel):
    """Input model for stock scoring"""
    symbol: str
    current_price: float
    vwap: float = 0
    rvol: float = 1.0
    gap_percent: float = 0
    market_cap: float = 10000000000
    ema_9: float = 0
    sma_20: float = 0
    sma_50: float = 0
    high: float = 0
    low: float = 0
    prev_close: float = 0
    prev_high: float = 0
    prev_low: float = 0
    volume: int = 0
    avg_volume: int = 0
    float_shares: int = 50000000
    short_interest_pct: float = 0
    shares_available_to_short: int = 0
    pe_ratio: float = 0
    sector_pe: float = 20
    debt_to_equity: float = 1
    profit_margin: float = 0
    revenue_growth: float = 0
    eps_growth: float = 0
    price_vs_52w_high: float = 80
    trend_strength: float = 50
    earnings_surprise_pct: float = 0
    revenue_surprise_pct: float = 0
    guidance_change: str = "none"
    news_impact: int = 0
    news_type: str = ""
    analyst_action: str = "none"
    price_target_change_pct: float = 0
    sector_momentum: float = 0
    market_sentiment: float = 0
    sector_rank: int = 50
    patterns: List[str] = []
    matched_strategies: List[str] = []
    atr: float = 0
    support_distance: float = 0
    resistance_distance: float = 0
    bid_ask_spread_pct: float = 0.1
    bias: str = "neutral"


class MarketDataInput(BaseModel):
    """Input model for market context"""
    regime: str = "neutral"  # bullish, bearish, neutral
    spy_change_pct: float = 0
    vix_level: float = 15


class BatchScoreRequest(BaseModel):
    """Request for batch scoring"""
    stocks: List[StockDataInput]
    market_data: Optional[MarketDataInput] = None


@router.post("/analyze")
async def analyze_single_stock(stock: StockDataInput, market_data: Optional[MarketDataInput] = None):
    """
    Analyze a single stock and return comprehensive score
    """
    engine = get_scoring_engine()
    
    stock_dict = stock.dict()
    # Rename float_shares to float for scoring engine
    stock_dict["float"] = stock_dict.pop("float_shares", 50000000)
    market_dict = market_data.dict() if market_data else {"regime": "neutral"}
    
    result = engine.calculate_composite_score(stock_dict, market_dict)
    return result


@router.post("/batch")
async def analyze_batch(request: BatchScoreRequest):
    """
    Analyze multiple stocks and return sorted by score
    """
    engine = get_scoring_engine()
    
    stocks = [s.dict() for s in request.stocks]
    # Rename float_shares to float for scoring engine
    for s in stocks:
        s["float"] = s.pop("float_shares", 50000000)
    market_dict = request.market_data.dict() if request.market_data else {"regime": "neutral"}
    
    results = await engine.score_batch(stocks, market_dict)
    return {
        "count": len(results),
        "timestamp": datetime.utcnow().isoformat(),
        "scores": results
    }


@router.post("/top-picks")
async def get_top_picks(
    request: BatchScoreRequest,
    timeframe: Optional[str] = Query(None, description="Filter by timeframe: intraday, swing, longterm"),
    direction: Optional[str] = Query(None, description="Filter by direction: long, short"),
    limit: int = Query(10, description="Maximum results to return")
):
    """
    Get top-scored picks filtered by timeframe and direction
    """
    engine = get_scoring_engine()
    
    stocks = [s.dict() for s in request.stocks]
    # Rename float_shares to float for scoring engine
    for s in stocks:
        s["float"] = s.pop("float_shares", 50000000)
    market_dict = request.market_data.dict() if request.market_data else {"regime": "neutral"}
    
    # Score all stocks
    all_scores = await engine.score_batch(stocks, market_dict)
    
    # Filter for top picks
    top = engine.get_top_picks(all_scores, timeframe, direction, limit)
    
    return {
        "timeframe_filter": timeframe,
        "direction_filter": direction,
        "count": len(top),
        "timestamp": datetime.utcnow().isoformat(),
        "picks": top
    }


@router.get("/criteria")
async def get_scoring_criteria():
    """
    Get the scoring criteria and weights used by the engine
    """
    engine = get_scoring_engine()
    
    return {
        "category_weights": engine.CATEGORY_WEIGHTS,
        "rvol_thresholds": {
            "small_cap": engine.RVOL_THRESHOLDS[engine.classify_market_cap(1_000_000_000)],
            "mid_cap": engine.RVOL_THRESHOLDS[engine.classify_market_cap(5_000_000_000)],
            "large_cap": engine.RVOL_THRESHOLDS[engine.classify_market_cap(50_000_000_000)]
        },
        "min_float": engine.MIN_FLOAT,
        "gap_threshold": engine.GAP_THRESHOLD,
        "scoring_components": {
            "technical": {
                "weight": "35%",
                "components": ["VWAP Position", "RVOL", "Gap %", "MA Distance", "Patterns"]
            },
            "fundamental": {
                "weight": "20%",
                "components": ["Value (P/E)", "Safety (Debt/Margin)", "Growth (Rev/EPS)", "Timing"]
            },
            "catalyst": {
                "weight": "20%",
                "components": ["Earnings Surprise", "Fundamental News", "Analyst Actions", "Sector/Market"]
            },
            "risk": {
                "weight": "10%",
                "components": ["Float", "Short Interest", "Risk/Reward", "Liquidity"]
            },
            "context": {
                "weight": "15%",
                "components": ["Market Regime", "Sector Strength", "Strategy Match"]
            }
        },
        "direction_rules": {
            "above_vwap": "Prioritize LONG",
            "below_vwap": "Prioritize SHORT",
            "extended_above_ma": "Mean Reversion SHORT",
            "extended_below_ma": "Rubber Band LONG"
        },
        "success_factors": [
            "Composite score >= 60",
            "RVOL meets threshold",
            "Market regime alignment",
            "Strong catalyst (>=50)"
        ]
    }


@router.get("/timeframes")
async def get_timeframe_criteria():
    """
    Get criteria for each trading timeframe
    """
    return {
        "intraday": {
            "description": "Day trades, scalps, momentum plays",
            "ideal_conditions": [
                "RVOL meets threshold (5x small cap, 3x mid, 2x large)",
                "Gap >= 4%",
                "Strong catalyst (earnings, news)",
                "High volume confirmation"
            ],
            "strategies": ["Rubber Band Scalp", "VWAP Bounce", "Gap & Go", "Momentum Continuation"],
            "hold_time": "Minutes to hours"
        },
        "swing": {
            "description": "Multi-day to multi-week holds",
            "ideal_conditions": [
                "Strong technical setup",
                "Breakout from consolidation",
                "Positive catalyst or sector momentum",
                "Good risk/reward (>2:1)"
            ],
            "strategies": ["Breakout Continuation", "Pullback Entry", "Range Break"],
            "hold_time": "Days to weeks"
        },
        "longterm": {
            "description": "Position trades, investments",
            "ideal_conditions": [
                "Strong fundamentals (VectorVest score)",
                "Positive growth trajectory",
                "Undervalued vs sector",
                "Long-term trend intact"
            ],
            "strategies": ["Trend Following", "Dip Buying", "Value Investing"],
            "hold_time": "Weeks to months"
        }
    }
