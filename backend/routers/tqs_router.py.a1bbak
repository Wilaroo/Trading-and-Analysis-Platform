"""
TQS API Router - Trade Quality Score Endpoints

Provides API access to the TQS engine for:
- Single symbol scoring
- Batch scoring
- Detailed breakdowns
- Threshold guidance
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from services.tqs import get_tqs_engine

router = APIRouter(prefix="/api/tqs", tags=["tqs"])


class BatchScoreRequest(BaseModel):
    """Request model for batch scoring"""
    opportunities: List[Dict[str, Any]]


class ScoreRequest(BaseModel):
    """Request model for single score calculation"""
    symbol: str
    setup_type: str
    direction: str = "long"
    trade_style: Optional[str] = None  # NEW: move_2_move, trade_2_hold, a_plus, swing, investment
    tape_score: float = 0.0
    tape_confirmation: bool = False
    smb_grade: str = "B"
    smb_5var_score: int = 25
    risk_reward: float = 2.0
    alert_priority: str = "medium"
    market_regime: Optional[str] = None
    time_of_day: Optional[str] = None
    planned_position_size: int = 100
    account_value: float = 100000.0


@router.get("/score/{symbol}")
async def get_tqs_score(
    symbol: str,
    setup_type: str = Query(default="unknown", description="Type of setup (e.g., bull_flag, vwap_bounce)"),
    direction: str = Query(default="long", description="Trade direction: long or short")
):
    """
    Get TQS score for a symbol with basic parameters.
    
    Returns:
    - Overall score (0-100)
    - Grade (A/B+/B/C+/C/D/F)
    - Action recommendation (STRONG_BUY/BUY/HOLD/AVOID/STRONG_AVOID)
    - Pillar scores breakdown
    """
    tqs = get_tqs_engine()
    
    result = await tqs.calculate_tqs(
        symbol=symbol.upper(),
        setup_type=setup_type,
        direction=direction
    )
    
    return {
        "success": True,
        "tqs": result.to_summary()
    }


@router.post("/score")
async def calculate_tqs_score(request: ScoreRequest):
    """
    Calculate detailed TQS score with full parameters.
    
    Use this endpoint when you have additional context like:
    - Tape reading data
    - SMB grades
    - Position sizing info
    - Trade style (move_2_move, trade_2_hold, a_plus, swing, investment)
    """
    tqs = get_tqs_engine()
    
    result = await tqs.calculate_tqs(
        symbol=request.symbol.upper(),
        setup_type=request.setup_type,
        direction=request.direction,
        trade_style=request.trade_style,  # NEW: Pass trade style for timeframe-aware weighting
        tape_score=request.tape_score,
        tape_confirmation=request.tape_confirmation,
        smb_grade=request.smb_grade,
        smb_5var_score=request.smb_5var_score,
        risk_reward=request.risk_reward,
        alert_priority=request.alert_priority,
        market_regime=request.market_regime,
        time_of_day=request.time_of_day,
        planned_position_size=request.planned_position_size,
        account_value=request.account_value
    )
    
    return {
        "success": True,
        "tqs": result.to_dict()
    }


@router.get("/breakdown/{symbol}")
async def get_tqs_breakdown(
    symbol: str,
    setup_type: str = Query(default="unknown"),
    direction: str = Query(default="long")
):
    """
    Get detailed TQS breakdown with all pillar components.
    
    Returns full analysis including:
    - Each pillar's score and grade
    - Component breakdowns within each pillar
    - All factors (positive and negative)
    - Warnings if applicable
    """
    tqs = get_tqs_engine()
    
    result = await tqs.calculate_tqs(
        symbol=symbol.upper(),
        setup_type=setup_type,
        direction=direction
    )
    
    return {
        "success": True,
        "breakdown": result.to_dict()
    }


@router.get("/card-detail/{symbol}")
async def get_tqs_card_detail(
    symbol: str,
    source: str = Query(default="alert", description="alert | position"),
):
    """
    v19.34.256 (Part B) — the TQS drill-down data contract.

    Returns the PERSISTED TQS breakdown that actually drove the card (NOT a
    fresh recompute with default inputs, which `/breakdown` does and which
    would not match what the operator saw). Folds in the context that used to
    live in separate badges: rolling 30d setup performance, catalyst+gap, and —
    for open positions — entry/current/SL/TP + unrealized P&L.
    """
    sym = symbol.upper().strip()
    db = getattr(get_tqs_engine(), "_db", None)
    if db is None:
        return {"success": False, "error": "db_unavailable"}

    detail = {"success": True, "symbol": sym, "source": source}

    # ── pull the persisted record (position entry_context.tqs, else alert) ──
    rec, breakdown = None, None
    if source == "position":
        rec = db["bot_trades"].find_one(
            {"symbol": sym, "status": {"$in": ["open", "OPEN", "pending", "PENDING", "filled", "FILLED"]}},
            sort=[("created_at", -1)])
        if rec:
            breakdown = (rec.get("entry_context") or {}).get("tqs")
            detail["position"] = {
                "direction": rec.get("direction"),
                "entry_price": rec.get("fill_price") or rec.get("entry_price"),
                "current_price": rec.get("current_price") or rec.get("last_price"),
                "stop_price": rec.get("stop_price") or rec.get("stop_loss"),
                "target_price": rec.get("target_price"),
                "shares": rec.get("shares"),
                "unrealized_pnl": rec.get("unrealized_pnl"),
                "unrealized_r": rec.get("pnl_r") or rec.get("unrealized_r"),
                "entry_time": rec.get("executed_at") or rec.get("created_at"),
            }
    if breakdown is None:
        rec = db["live_alerts"].find_one(
            {"symbol": sym, "tqs_breakdown": {"$exists": True}},
            sort=[("created_at", -1)])
        if rec:
            breakdown = rec.get("tqs_breakdown")

    if not rec or not breakdown:
        return {"success": False, "error": "no_persisted_tqs", "symbol": sym}

    tqs = get_tqs_engine()
    score = float(rec.get("tqs_score") or 0)
    detail.update({
        "tqs_score": round(score, 1),
        "tqs_grade": rec.get("tqs_grade") or "",
        "tqs_action": tqs.get_threshold_guidance(score).get("action", "") if score else "",
        "setup_type": rec.get("setup_type") or "",
        "direction": rec.get("direction") or (detail.get("position") or {}).get("direction") or "long",
        "trade_style": rec.get("trade_style") or "",
        "breakdown": breakdown,
        # v19.34.305 — when the persisted alert predates weight-capture (or it
        # was stored empty), reconstruct the ACTUAL style-aware weights for this
        # trade_style instead of falling back to the generic 25/25/15/20/15
        # default (which mislabelled e.g. scalp setups that really used
        # 30/35/5/20/10). Only the true weights are ever shown.
        "weights": rec.get("tqs_weights")
        or tqs._get_weights_for_style(rec.get("trade_style") or "intraday"),
        # folded-in context (previously separate badges)
        "catalyst_tag": rec.get("catalyst_tag") or "",
        "catalyst_summary": rec.get("catalyst_summary") or "",
        "gap_pct": rec.get("gap_pct"),
        "scored_at": rec.get("created_at"),
    })

    # rolling 30d setup performance (the SetupGradeChip data, folded in)
    setup_type = detail["setup_type"]
    if setup_type:
        ss = db["strategy_stats"].find_one({"strategy": setup_type}) \
            or db["strategy_stats"].find_one({"setup_type": setup_type})
        if ss:
            # v19.34.305 — unify the displayed EV onto the single realized-mean
            # source (avg_r) so the card can never show a contradictory pair like
            # "avg +0.01R" next to "Expected Value -0.13R". Prefer avg_r; fall
            # back to the legacy decomposed fields only for not-yet-recomputed
            # legacy docs.
            _avg_r = ss.get("avg_r")
            _ev = _avg_r if _avg_r is not None else (
                ss.get("expected_value_r") or ss.get("genuine_ev_r"))
            detail["setup_perf"] = {
                "win_rate": ss.get("win_rate"),
                "expected_value_r": _ev,
                "avg_r": _avg_r if _avg_r is not None else ss.get("avg_rr_achieved"),
                "sample_size": ss.get("sample_size") or ss.get("total_trades"),
            }

    return detail



@router.post("/batch")
async def batch_score(request: BatchScoreRequest):
    """
    Score multiple opportunities at once.
    
    Request body should contain a list of opportunities, each with:
    - symbol (required)
    - setup_type (required)
    - direction (optional, default "long")
    - Other optional parameters
    
    Returns sorted list (highest score first).
    """
    if not request.opportunities:
        return {"success": True, "results": []}
        
    if len(request.opportunities) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 opportunities per batch")
        
    tqs = get_tqs_engine()
    
    results = await tqs.batch_calculate(request.opportunities)
    
    return {
        "success": True,
        "count": len(results),
        "results": [r.to_summary() for r in results]
    }


@router.get("/guidance")
def get_score_guidance(score: float = Query(ge=0, le=100)):
    """
    Get trading guidance for a particular TQS score.
    
    Returns:
    - Recommended action
    - Confidence level
    - Position sizing recommendation
    - General guidance text
    """
    tqs = get_tqs_engine()
    guidance = tqs.get_threshold_guidance(score)
    
    return {
        "success": True,
        "score": score,
        "guidance": guidance
    }


@router.get("/thresholds")
def get_tqs_thresholds():
    """
    Get the current TQS threshold configuration.
    
    Returns the score ranges for each action category.
    """
    tqs = get_tqs_engine()
    
    return {
        "success": True,
        "thresholds": tqs.ACTION_THRESHOLDS,
        "weights": tqs.WEIGHTS,
        "grade_ranges": {
            "A": "85-100",
            "B+": "75-84",
            "B": "65-74",
            "C+": "55-64",
            "C": "45-54",
            "D": "35-44",
            "F": "0-34"
        }
    }


@router.get("/pillars")
def get_pillar_info():
    """
    Get information about the 5 TQS pillars.
    
    Explains what each pillar measures and its weight.
    """
    return {
        "success": True,
        "pillars": {
            "setup": {
                "name": "Setup Quality",
                "weight": "25%",
                "description": "Pattern clarity, historical win rate, expected value, tape confirmation",
                "components": ["pattern_score", "win_rate_score", "ev_score", "tape_score", "smb_score"]
            },
            "technical": {
                "name": "Technical Quality",
                "weight": "25%",
                "description": "Trend alignment, RSI, support/resistance, volatility, volume",
                "components": ["trend_score", "rsi_score", "levels_score", "volatility_score", "volume_score"]
            },
            "fundamental": {
                "name": "Fundamental Quality",
                "weight": "15%",
                "description": "Catalyst presence, short interest, float, institutional ownership, earnings",
                "components": ["catalyst_score", "short_interest_score", "float_score", "institutional_score", "earnings_score"]
            },
            "context": {
                "name": "Context Quality",
                "weight": "20%",
                "description": "Market regime, time of day, sector strength, VIX regime, day of week",
                "components": ["regime_score", "time_score", "sector_score", "vix_score", "day_score"]
            },
            "execution": {
                "name": "Execution Quality",
                "weight": "15%",
                "description": "Your execution history, tilt state, entry/exit tendencies, recent streak",
                "components": ["history_score", "tilt_score", "entry_tendency_score", "exit_tendency_score", "streak_score"]
            }
        }
    }
