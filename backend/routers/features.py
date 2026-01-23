"""
Feature Engine API Router
Endpoints for calculating technical indicators and features
"""
from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict
from pydantic import BaseModel

from services.feature_engine import get_feature_engine

router = APIRouter(prefix="/api/features", tags=["features"])


class BarData(BaseModel):
    """Single OHLCV bar"""
    open: float
    high: float
    low: float
    close: float
    volume: int
    timestamp: Optional[str] = None
    prior_close: Optional[float] = None
    prior_high: Optional[float] = None
    prior_low: Optional[float] = None


class FundamentalData(BaseModel):
    """Fundamental data inputs"""
    market_cap: float = 0
    pe_ttm: float = 0
    pe_forward: float = 0
    ps_ttm: float = 0
    pb_ratio: float = 0
    sector_pe: float = 20
    eps_growth_1y: float = 0
    revenue_growth_1y: float = 0
    roe: float = 0
    roa: float = 0
    gross_margin: float = 0
    operating_margin: float = 0
    net_margin: float = 0
    debt_to_equity: float = 1
    current_ratio: float = 1
    dividend_yield: float = 0


class MarketContextData(BaseModel):
    """Market context data"""
    spy_return_1d: float = 0
    spy_return_5d: float = 0
    spy_return_20d: float = 0
    sector_return_1d: float = 0
    sector_return_20d: float = 0


class FeatureRequest(BaseModel):
    """Request for feature calculation"""
    symbol: str
    bars_5m: List[BarData]
    bars_daily: Optional[List[BarData]] = None
    session_bars_1m: Optional[List[BarData]] = None
    fundamentals: Optional[FundamentalData] = None
    market_data: Optional[MarketContextData] = None


class QuickFeatureRequest(BaseModel):
    """Simplified request with just price data"""
    symbol: str
    current_price: float
    open_price: float
    high: float
    low: float
    volume: int
    prior_close: float
    prior_high: float = 0
    prior_low: float = 0
    vwap: float = 0
    rvol: float = 1.0


@router.post("/calculate")
async def calculate_features(request: FeatureRequest):
    """
    Calculate all technical features for a stock.
    
    Requires OHLCV bar data (at least 5-minute bars).
    Optionally include daily bars, session bars, fundamentals, and market context.
    """
    engine = get_feature_engine()
    
    # Convert Pydantic models to dicts
    bars_5m = [b.dict() for b in request.bars_5m]
    bars_daily = [b.dict() for b in request.bars_daily] if request.bars_daily else None
    session_bars = [b.dict() for b in request.session_bars_1m] if request.session_bars_1m else None
    fundamentals = request.fundamentals.dict() if request.fundamentals else None
    market_data = request.market_data.dict() if request.market_data else None
    
    # Calculate all features
    features = engine.calculate_all_features(
        bars_5m=bars_5m,
        bars_daily=bars_daily,
        session_bars_1m=session_bars,
        fundamentals=fundamentals,
        market_data=market_data
    )
    
    return {
        "symbol": request.symbol,
        "features": features,
        "intraday_conviction": {
            "score": features.get("intraday_conviction_score", 0),
            "confidence": features.get("conviction_confidence", "LOW"),
            "signals": features.get("conviction_signals", []),
            "high_conviction": features.get("meets_high_conviction", False)
        }
    }


@router.post("/quick-analysis")
async def quick_analysis(request: QuickFeatureRequest):
    """
    Quick feature analysis with minimal data.
    Good for real-time scanning where you just have current bar info.
    """
    features = {}
    
    # Basic calculations
    features["symbol"] = request.symbol
    features["current_price"] = request.current_price
    features["volume"] = request.volume
    features["rvol"] = request.rvol
    
    # Gap
    if request.prior_close > 0:
        features["gap_pct"] = ((request.open_price - request.prior_close) / request.prior_close) * 100
    
    # VWAP
    if request.vwap > 0:
        features["vwap"] = request.vwap
        features["close_over_vwap"] = request.current_price > request.vwap
        features["close_over_vwap_pct"] = ((request.current_price - request.vwap) / request.vwap) * 100
        features["distance_from_vwap_pct"] = abs(features["close_over_vwap_pct"])
    
    # Intraday range
    features["intraday_range_pct"] = ((request.high - request.low) / request.current_price) * 100 if request.current_price else 0
    
    # Position in day's range
    day_range = request.high - request.low
    if day_range > 0:
        features["position_in_range"] = ((request.current_price - request.low) / day_range) * 100
    
    # Prior day levels
    if request.prior_high > 0:
        features["close_vs_prior_high_pct"] = ((request.current_price - request.prior_high) / request.prior_high) * 100
        features["above_prior_high"] = request.current_price > request.prior_high
    
    if request.prior_low > 0:
        features["close_vs_prior_low_pct"] = ((request.current_price - request.prior_low) / request.prior_low) * 100
        features["below_prior_low"] = request.current_price < request.prior_low
    
    # Quick conviction estimate
    conviction = 50
    signals = []
    
    if request.rvol >= 3:
        conviction += 15
        signals.append(f"High RVOL ({request.rvol:.1f}x)")
    elif request.rvol >= 2:
        conviction += 10
        signals.append(f"Good RVOL ({request.rvol:.1f}x)")
    
    if features.get("distance_from_vwap_pct", 10) <= 1:
        conviction += 15
        signals.append("Near VWAP")
    
    if abs(features.get("gap_pct", 0)) >= 4:
        conviction += 10
        signals.append(f"Gap {features.get('gap_pct', 0):.1f}%")
    
    if features.get("above_prior_high", False):
        conviction += 10
        signals.append("Above prior day high")
    
    features["quick_conviction_score"] = min(100, conviction)
    features["conviction_signals"] = signals
    
    return features


@router.get("/indicators")
async def list_available_indicators():
    """
    List all available technical indicators and features
    """
    return {
        "price_volume": [
            "open", "high", "low", "close", "volume",
            "pct_return_1bar", "gap_pct_today", "dollar_volume",
            "avg_volume_20", "avg_volume_50", "rvol_20"
        ],
        "moving_averages": [
            "sma_10", "sma_20", "sma_50", "sma_100", "sma_200",
            "ema_9", "ema_20", "ema_50",
            "close_over_sma_X_pct", "sma_20_over_50_pct",
            "golden_cross", "death_cross", "slope_sma_20", "slope_sma_50"
        ],
        "volatility": [
            "atr_14", "atr_14_pct", "tr_pct",
            "realized_vol_20d", "range_vs_avg_20"
        ],
        "momentum": [
            "rsi_14", "rsi_2", "rsi_oversold", "rsi_overbought",
            "stoch_k_14_3", "stoch_d_14_3",
            "macd_line", "macd_signal", "macd_hist", "macd_bullish",
            "roc_10", "roc_20", "williams_r_14"
        ],
        "vwap": [
            "vwap", "close_over_vwap", "close_over_vwap_pct",
            "distance_from_vwap_pct", "rvol_intraday",
            "vwap_upper_1atr", "vwap_lower_1atr"
        ],
        "structure": [
            "high_20", "low_20", "high_20d", "low_20d",
            "high_52w", "low_52w", "pct_off_52w_high",
            "prior_day_high", "prior_day_low", "prior_day_close",
            "pivot", "r1", "s1", "r2", "s2"
        ],
        "opening_range": [
            "opening_range_high", "opening_range_low", "opening_range_size",
            "break_above_orh", "break_above_orh_pct",
            "break_below_orl", "break_below_orl_pct"
        ],
        "relative_strength": [
            "rs_vs_spy_1d", "rs_vs_spy_5d", "rs_vs_spy_20d",
            "rs_vs_sector_1d", "rs_vs_sector_20d", "rs_rank_20d"
        ],
        "composite_scores": [
            "rv_score", "rs_score", "rt_score", "vst_score",
            "intraday_conviction_score", "conviction_confidence"
        ]
    }


@router.get("/high-conviction-criteria")
async def get_high_conviction_criteria():
    """
    Get the criteria for high-conviction intraday setups
    """
    return {
        "description": "High-conviction intraday setup requirements",
        "primary_criteria": {
            "rvol": {
                "threshold": ">= 2 (ideally >= 3)",
                "weight": "25 points"
            },
            "vwap_distance": {
                "threshold": "<= 0.5% from VWAP",
                "weight": "20 points",
                "note": "Being near VWAP provides clear risk/reward"
            },
            "ema_position": {
                "threshold": "Above EMA20",
                "weight": "15 points",
                "note": "Confirms trend alignment"
            },
            "rsi_sweet_spot": {
                "threshold": "45-75",
                "weight": "15 points",
                "note": "Not overbought, not oversold"
            },
            "opening_range": {
                "threshold": "Break above ORH or below ORL",
                "weight": "15 points",
                "note": "Confirms directional commitment"
            }
        },
        "bonus_criteria": {
            "prior_day_levels": {
                "threshold": "Within 0.5% of PDH or PDL",
                "weight": "10 points"
            },
            "catalyst": {
                "threshold": "Catalyst score >= 6",
                "weight": "10 bonus points"
            }
        },
        "conviction_levels": {
            "VERY HIGH": ">= 80",
            "HIGH": ">= 65",
            "MEDIUM": ">= 50",
            "LOW": "< 50"
        },
        "minimum_for_trade": 65
    }
