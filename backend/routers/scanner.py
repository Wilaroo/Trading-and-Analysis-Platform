"""
Predictive Scanner API Router
Endpoints for real-time trade setup scanning and alerts
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import logging
import asyncio

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scanner", tags=["Predictive Scanner"])

# Service instance
_scanner_service = None
_scan_task = None


def init_scanner_router(scanner_service):
    """Initialize the router with the scanner service"""
    global _scanner_service
    _scanner_service = scanner_service


# ===================== Pydantic Models =====================

class ScanRequest(BaseModel):
    symbols: Optional[List[str]] = Field(default=None, description="Symbols to scan (uses default watchlist if not provided)")
    setup_types: Optional[List[str]] = Field(default=None, description="Filter by setup types")
    min_probability: float = Field(default=0.30, description="Minimum trigger probability")


class WatchlistRequest(BaseModel):
    symbols: List[str] = Field(..., description="Symbols to watch")


class AlertConfigRequest(BaseModel):
    min_probability: float = Field(default=0.60, description="Minimum probability to trigger alert")
    alert_minutes_before: int = Field(default=5, description="Minutes before trigger to alert")
    setup_types: Optional[List[str]] = Field(default=None, description="Setup types to alert on")


# ===================== Endpoints =====================

@router.get("/status")
def get_scanner_status():
    """
    Get the current status of the predictive scanner.
    Returns running state, scan count, and active alerts.
    """
    if not _scanner_service:
        return {
            "success": True,
            "running": False,
            "scan_count": 0,
            "active_alerts": 0,
            "last_scan": None,
            "message": "Scanner service not initialized"
        }
    
    try:
        # Try to get status from scanner service
        if hasattr(_scanner_service, 'get_status'):
            status = _scanner_service.get_status()
            return {
                "success": True,
                **status
            }
        else:
            # Fallback basic status
            return {
                "success": True,
                "running": hasattr(_scanner_service, '_running') and _scanner_service._running,
                "scan_count": getattr(_scanner_service, '_scan_count', 0),
                "active_alerts": len(getattr(_scanner_service, '_live_alerts', {})),
                "last_scan": None,
                "watchlist_size": len(getattr(_scanner_service, '_watchlist', []))
            }
    except Exception as e:
        logger.error(f"Error getting scanner status: {e}")
        return {
            "success": False,
            "error": str(e),
            "running": False
        }



@router.post("/scan")
async def scan_for_setups(request: ScanRequest):
    """
    Scan for forming trade setups.
    
    Returns setups sorted by trigger probability with:
    - Current phase (early, developing, nearly ready, imminent)
    - Trigger probability
    - Predicted outcome (win rate, targets, R:R)
    - Time estimate until trigger
    """
    if not _scanner_service:
        raise HTTPException(status_code=500, detail="Scanner service not initialized")
    
    try:
        setups = await _scanner_service.scan_for_setups(request.symbols)
        
        # Filter by probability
        setups = [s for s in setups if s.trigger_probability >= request.min_probability]
        
        # Filter by setup type if specified
        if request.setup_types:
            type_set = set(request.setup_types)
            setups = [s for s in setups if s.setup_type.value in type_set]
        
        # Convert to response format
        results = []
        for setup in setups:
            results.append({
                "id": setup.id,
                "symbol": setup.symbol,
                "setup_type": setup.setup_type.value,
                "phase": setup.phase.value,
                "direction": setup.direction,
                "current_price": setup.current_price,
                "trigger_price": setup.trigger_price,
                "distance_to_trigger_pct": round(setup.distance_to_trigger_pct, 2),
                "trigger_probability": round(setup.trigger_probability, 3),
                "minutes_to_trigger": setup.minutes_to_trigger,
                "prediction": {
                    "win_probability": setup.prediction.win_probability,
                    "expected_gain_pct": setup.prediction.expected_gain_pct,
                    "expected_loss_pct": setup.prediction.expected_loss_pct,
                    "expected_value": setup.prediction.expected_value,
                    "realistic_target": setup.prediction.realistic_target,
                    "realistic_stop": setup.prediction.realistic_stop,
                    "risk_reward": setup.prediction.risk_reward_ratio,
                    "confidence": setup.prediction.confidence,
                    "factors": setup.prediction.factors
                },
                "scores": {
                    "overall": setup.setup_score,
                    "technical": setup.technical_score,
                    "fundamental": setup.fundamental_score,
                    "catalyst": setup.catalyst_score
                },
                "strategy_match": setup.strategy_match,
                "patterns_detected": setup.pattern_detected,
                "key_levels": setup.key_levels,
                "notes": setup.notes,
                "detected_at": setup.detected_at
            })
        
        return {
            "success": True,
            "count": len(results),
            "setups": results,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Scan error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/setups")
def get_forming_setups(
    min_probability: float = 0.30,
    setup_type: Optional[str] = None,
    symbol: Optional[str] = None
):
    """
    Get currently tracked forming setups.
    These are updated on each scan cycle.
    """
    if not _scanner_service:
        raise HTTPException(status_code=500, detail="Scanner service not initialized")
    
    setup_types = None
    if setup_type:
        from services.predictive_scanner import SetupType
        try:
            setup_types = [SetupType(setup_type)]
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid setup type: {setup_type}")
    
    symbols = [symbol] if symbol else None
    
    setups = _scanner_service.get_forming_setups(
        min_probability=min_probability,
        setup_types=setup_types,
        symbols=symbols
    )
    
    results = []
    for setup in setups:
        results.append({
            "id": setup.id,
            "symbol": setup.symbol,
            "setup_type": setup.setup_type.value,
            "phase": setup.phase.value,
            "direction": setup.direction,
            "trigger_probability": round(setup.trigger_probability, 3),
            "minutes_to_trigger": setup.minutes_to_trigger,
            "win_probability": setup.prediction.win_probability,
            "expected_value": setup.prediction.expected_value,
            "risk_reward": setup.prediction.risk_reward_ratio,
            "strategy": setup.strategy_match,
            "notes": setup.notes[:2] if setup.notes else []
        })
    
    return {
        "success": True,
        "count": len(results),
        "setups": results
    }


@router.get("/alerts")
def get_active_alerts():
    """
    Get active (pending) trade alerts.
    These are setups that are about to trigger.
    """
    if not _scanner_service:
        raise HTTPException(status_code=500, detail="Scanner service not initialized")
    
    alerts = _scanner_service.get_active_alerts()
    
    results = []
    for alert in alerts:
        results.append({
            "id": alert.id,
            "symbol": alert.symbol,
            "setup_type": alert.setup_type,
            "direction": alert.direction,
            "alert_time": alert.alert_time,
            "estimated_trigger_time": alert.estimated_trigger_time,
            "minutes_until_trigger": alert.minutes_until_trigger,
            "trigger_price": alert.trigger_price,
            "entry_zone": alert.entry_zone,
            "stop_loss": alert.stop_loss,
            "target_1": alert.target_1,
            "target_2": alert.target_2,
            "risk_reward": alert.risk_reward,
            "trigger_probability": alert.trigger_probability,
            "win_probability": alert.win_probability,
            "expected_value": alert.expected_value,
            "setup_score": alert.setup_score,
            "strategy": alert.strategy_match,
            "reasoning": alert.reasoning,
            "status": alert.status
        })
    
    return {
        "success": True,
        "count": len(results),
        "alerts": results
    }


@router.get("/alerts/history")
def get_alert_history(limit: int = 50):
    """Get historical alerts with outcomes"""
    if not _scanner_service:
        raise HTTPException(status_code=500, detail="Scanner service not initialized")
    
    history = _scanner_service.get_alert_history(limit)
    
    results = [{
        "id": a.id,
        "symbol": a.symbol,
        "setup_type": a.setup_type,
        "direction": a.direction,
        "alert_time": a.alert_time,
        "status": a.status,
        "outcome": a.outcome,
        "win_probability": a.win_probability,
        "trigger_price": a.trigger_price
    } for a in history]
    
    return {"success": True, "history": results}


@router.post("/watchlist")
def set_watchlist(request: WatchlistRequest):
    """Set the symbols to scan"""
    if not _scanner_service:
        raise HTTPException(status_code=500, detail="Scanner service not initialized")
    
    _scanner_service.set_watchlist(request.symbols)
    
    return {
        "success": True,
        "watchlist": [s.upper() for s in request.symbols],
        "message": f"Watchlist updated with {len(request.symbols)} symbols"
    }


@router.get("/watchlist")
def get_watchlist():
    """Get current watchlist"""
    if not _scanner_service:
        raise HTTPException(status_code=500, detail="Scanner service not initialized")
    
    watchlist = _scanner_service._watchlist or _scanner_service._get_default_watchlist()
    
    return {
        "success": True,
        "watchlist": watchlist,
        "count": len(watchlist)
    }


@router.get("/setup-types")
def get_available_setup_types():
    """Get list of available setup types for filtering"""
    from services.predictive_scanner import SetupType, PredictiveScannerService
    
    criteria = PredictiveScannerService.STRATEGY_CRITERIA
    
    types = []
    for setup_type in SetupType:
        info = criteria.get(setup_type, {})
        types.append({
            "id": setup_type.value,
            "name": setup_type.value.replace("_", " ").title(),
            "description": info.get("description", ""),
            "base_win_rate": info.get("base_win_rate"),
            "trigger_condition": info.get("trigger_condition", "")
        })
    
    return {"success": True, "setup_types": types}


@router.get("/strategy-mix")
def get_strategy_mix(n: int = 100):
    """Distribution of `setup_type` across the last N alerts.

    Surfaces silent biases in the scanner — e.g. "85% of last 100 alerts
    were `relative_strength_leader`" indicates the bot is overfit to one
    regime/strategy. Used by the V5 StrategyMixCard so the operator (and
    eventually the self-improving loop) can spot single-strategy
    domination at a glance.
    """
    n = max(10, min(500, int(n or 100)))
    if not _scanner_service:
        return {"success": True, "n": 0, "buckets": [], "total": 0}

    db = getattr(_scanner_service, "db", None)
    if db is None:
        return {"success": True, "n": 0, "buckets": [], "total": 0}

    try:
        cursor = db["live_alerts"].find(
            {},
            {"_id": 0, "setup_type": 1, "direction": 1, "created_at": 1, "ai_edge_label": 1},
        ).sort("created_at", -1).limit(n)
        rows = list(cursor)
    except Exception as e:
        logger.warning(f"strategy-mix aggregate failed: {e}")
        return {"success": True, "n": 0, "buckets": [], "total": 0, "error": str(e)[:120]}

    if not rows:
        return {"success": True, "n": 0, "buckets": [], "total": 0}

    # Count by `setup_type`. Strip _long / _short suffix so paired strategies
    # are aggregated together (e.g. orb_long + orb_short → orb).
    from collections import Counter
    def _base(setup: str) -> str:
        if not setup:
            return "unknown"
        s = str(setup)
        for suf in ("_long", "_short"):
            if s.endswith(suf):
                return s[: -len(suf)]
        return s

    counts = Counter(_base(r.get("setup_type", "")) for r in rows)
    total = sum(counts.values())
    # STRONG_EDGE counts per bucket — surfaces "this strategy fires often
    # AND has high AI edge" as a quality multiplier.
    strong_edge_counts: dict = {}
    for r in rows:
        if r.get("ai_edge_label") == "STRONG_EDGE":
            base = _base(r.get("setup_type", ""))
            strong_edge_counts[base] = strong_edge_counts.get(base, 0) + 1

    # ---- Per-strategy P&L attribution from `alert_outcomes` ---------------
    # Pull last-30-days realized outcomes grouped by setup_type so we can
    # surface "this strategy fires often, but is it actually making money?"
    # right next to the frequency bar. Same field shape as
    # `learning_connectors_service` for consistency.
    pnl_by_setup: dict = {}
    try:
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        cutoff_iso = cutoff.isoformat()
        pipeline = [
            {"$match": {"timestamp": {"$gte": cutoff_iso}, "r_multiple": {"$ne": None}}},
            {"$group": {
                "_id": "$setup_type",
                "total": {"$sum": 1},
                "wins": {"$sum": {"$cond": [{"$gt": ["$r_multiple", 0]}, 1, 0]}},
                "avg_r": {"$avg": "$r_multiple"},
                "total_r": {"$sum": "$r_multiple"},
            }},
        ]
        for row in db["alert_outcomes"].aggregate(pipeline):
            base = _base(row.get("_id", ""))
            t = int(row.get("total") or 0)
            if t == 0:
                continue
            existing = pnl_by_setup.get(base)
            if existing:
                # Merge long+short variants of same base setup.
                merged_total = existing["total"] + t
                merged_wins = existing["wins"] + int(row.get("wins") or 0)
                merged_total_r = existing["total_r"] + float(row.get("total_r") or 0)
                pnl_by_setup[base] = {
                    "total": merged_total,
                    "wins": merged_wins,
                    "total_r": merged_total_r,
                    "avg_r": merged_total_r / merged_total if merged_total else 0.0,
                    "win_rate": merged_wins / merged_total if merged_total else 0.0,
                }
            else:
                pnl_by_setup[base] = {
                    "total": t,
                    "wins": int(row.get("wins") or 0),
                    "total_r": float(row.get("total_r") or 0),
                    "avg_r": float(row.get("avg_r") or 0),
                    "win_rate": (int(row.get("wins") or 0) / t) if t else 0.0,
                }
    except Exception as e:
        logger.debug(f"strategy-mix P&L join failed: {e}")

    buckets = []
    for setup_type, c in counts.most_common():
        pnl = pnl_by_setup.get(setup_type) or {}
        buckets.append({
            "setup_type": setup_type,
            "label": setup_type.replace("_", " ").title(),
            "count": c,
            "pct": round((c / total) * 100, 1),
            "strong_edge_count": strong_edge_counts.get(setup_type, 0),
            # P&L fields — null when no outcomes recorded yet for this
            # setup_type. Front-end shows "—" in those cases.
            "outcomes_count": pnl.get("total"),
            "win_rate_pct": (
                round(pnl["win_rate"] * 100, 1)
                if pnl.get("total")
                else None
            ),
            "avg_r_multiple": (
                round(pnl["avg_r"], 2) if pnl.get("total") else None
            ),
            "total_r_30d": (
                round(pnl["total_r"], 2) if pnl.get("total") else None
            ),
        })

    # Concentration metric: % of total taken by the single most common
    # strategy. A red flag when ≥70%.
    top_pct = buckets[0]["pct"] if buckets else 0
    return {
        "success": True,
        "n": total,
        "window": "last_n_alerts",
        "buckets": buckets,
        "total": total,
        "top_strategy_pct": top_pct,
        "concentration_warning": top_pct >= 70.0,
    }


@router.get("/summary")
def get_scanner_summary():
    """
    Get a quick summary of current scanner state.
    Good for dashboard widgets and AI assistant.
    """
    if not _scanner_service:
        raise HTTPException(status_code=500, detail="Scanner service not initialized")
    
    setups = _scanner_service.get_forming_setups(min_probability=0.40)
    alerts = _scanner_service.get_active_alerts()
    
    # Categorize by phase
    imminent = [s for s in setups if s.phase.value == "trigger_imminent"]
    nearly_ready = [s for s in setups if s.phase.value == "nearly_ready"]
    developing = [s for s in setups if s.phase.value == "developing"]
    
    # Best opportunities
    best_setups = sorted(setups, key=lambda x: x.prediction.expected_value, reverse=True)[:3]
    
    return {
        "success": True,
        "summary": {
            "total_setups_forming": len(setups),
            "imminent_triggers": len(imminent),
            "nearly_ready": len(nearly_ready),
            "developing": len(developing),
            "active_alerts": len(alerts),
            "best_opportunities": [{
                "symbol": s.symbol,
                "setup": s.setup_type.value,
                "direction": s.direction,
                "trigger_prob": round(s.trigger_probability, 2),
                "win_prob": round(s.prediction.win_probability, 2),
                "ev": round(s.prediction.expected_value, 2),
                "minutes_to_trigger": s.minutes_to_trigger
            } for s in best_setups]
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/ai-context")
def get_ai_context():
    """
    Get formatted context for AI assistant integration.
    Returns human-readable summary of current setups.
    """
    if not _scanner_service:
        raise HTTPException(status_code=500, detail="Scanner service not initialized")
    
    context = _scanner_service.get_setup_summary_for_ai()
    
    return {
        "success": True,
        "context": context,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }



@router.get("/universe-stats")
def get_universe_stats():
    """
    Get statistics about the scanner symbol universe.
    Shows total symbols being scanned across all tiers.
    """
    from data.index_symbols import get_universe_stats as get_stats
    from services.user_viewed_tracker import get_view_stats, get_viewed_symbols
    
    try:
        universe_stats = get_stats()
        
        # Add viewed symbols stats
        viewed_stats = get_view_stats()
        viewed_symbols = get_viewed_symbols(max_count=100)
        
        return {
            "success": True,
            "universe": universe_stats,
            "user_viewed": {
                "count": len(viewed_symbols),
                "symbols": viewed_symbols[:20],  # Top 20 for display
                "stats": viewed_stats
            },
            "summary": {
                "tier1": f"~{universe_stats['tier1_count']} (SPY + QQQ + ETFs + Watchlist + Viewed)",
                "tier2": f"~{universe_stats['tier2_count']} (NASDAQ Extended)",
                "tier3": f"~{universe_stats['tier3_count']} (Russell 2000 + Sectors)",
                "total_unique": universe_stats['total_unique'],
                "sectors_included": list(universe_stats.get('sector_expansions', {}).keys())
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting universe stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
