"""
Predictive Scanner API Router
Endpoints for real-time trade setup scanning and alerts
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
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

    rows: list = []
    try:
        cursor = db["live_alerts"].find(
            {},
            {"_id": 0, "setup_type": 1, "direction": 1, "created_at": 1, "ai_edge_label": 1},
        ).sort("created_at", -1).limit(n)
        rows = list(cursor)
    except Exception as e:
        logger.warning(f"strategy-mix aggregate failed: {e}")
        rows = []

    # Fallback to in-memory alerts when Mongo persistence is empty or
    # behind. Checks BOTH the predictive_scanner (which is `_scanner_service`)
    # AND the enhanced_scanner (which is what fires the live setup alerts the
    # operator actually sees on the V5 dashboard). Without the
    # enhanced_scanner branch, strategy-mix would render
    # "waiting for first alerts" even when the V5 panel shows 6 hits
    # (operator's 2026-04-29 afternoon-5 screenshot bug).
    if not rows:
        in_mem_alerts = []
        try:
            in_mem_alerts.extend(
                (getattr(_scanner_service, "_live_alerts", {}) or {}).values()
            )
        except Exception:
            pass
        try:
            from services.enhanced_scanner import get_enhanced_scanner
            es = get_enhanced_scanner()
            if es is not None:
                in_mem_alerts.extend(
                    (getattr(es, "_live_alerts", {}) or {}).values()
                )
        except Exception as e:
            logger.debug(f"strategy-mix enhanced_scanner fallback failed: {e}")
        try:
            in_mem_alerts.sort(
                key=lambda a: getattr(a, "created_at", "") or "", reverse=True
            )
            seen_ids = set()
            for a in in_mem_alerts[:n * 2]:
                aid = getattr(a, "id", None) or id(a)
                if aid in seen_ids:
                    continue
                seen_ids.add(aid)
                rows.append({
                    "setup_type": getattr(a, "setup_type", None),
                    "direction": getattr(a, "direction", None),
                    "created_at": getattr(a, "created_at", None),
                    "ai_edge_label": getattr(a, "ai_edge_label", None),
                })
                if len(rows) >= n:
                    break
        except Exception as e:
            logger.debug(f"strategy-mix in-memory fallback failed: {e}")

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


@router.get("/detector-stats")
def get_detector_stats():
    """Per-setup-detector evaluation/hit telemetry — diagnoses why the
    scanner is quiet or biased toward a single setup type.

    Operator question this answers (Round 2 of the 2026-04-29 audit):
      "Why is the scanner only emitting `relative_strength_laggard` hits
      after 20 minutes of market open?"

    Returns two views:
      - `last_cycle`: counters since the last `_run_optimized_scan` reset.
        Most actionable for "what just happened?" debugging.
      - `cumulative`: counters since process startup. Better baseline.

    For each detector:
      - `evaluations`: how many times the checker was invoked
      - `hits`: how many times it returned a non-None LiveAlert
      - `hit_rate_pct`: hits / evaluations × 100

    2026-04-29 (afternoon-15): the `_scanner_service` singleton injected
    by `init_scanner_router` is the *predictive* scanner — a different
    instance than the live `enhanced_scanner` which actually owns the
    `_detector_evals` counters. Read from `get_enhanced_scanner()`
    directly so this endpoint reflects the live scanner that's
    generating today's alerts.
    """
    try:
        from services.enhanced_scanner import get_enhanced_scanner
        live_scanner = get_enhanced_scanner()
    except Exception:
        live_scanner = None

    if not live_scanner:
        return {
            "success": True,
            "running": False,
            "scan_count": 0,
            "last_cycle": {"detectors": [], "total_evals": 0, "total_hits": 0},
            "cumulative": {"detectors": [], "total_evals": 0, "total_hits": 0},
        }

    last_evals = getattr(live_scanner, "_detector_evals", {}) or {}
    last_hits = getattr(live_scanner, "_detector_hits", {}) or {}
    cum_evals = getattr(live_scanner, "_detector_evals_total", {}) or {}
    cum_hits = getattr(live_scanner, "_detector_hits_total", {}) or {}

    def _build(evals: dict, hits: dict) -> dict:
        rows = []
        for setup_type, e in evals.items():
            h = hits.get(setup_type, 0)
            rate = round((h / e) * 100, 1) if e else 0.0
            rows.append({
                "setup_type": setup_type,
                "label": setup_type.replace("_", " ").title(),
                "evaluations": int(e),
                "hits": int(h),
                "hit_rate_pct": rate,
            })
        rows.sort(key=lambda r: (-r["hits"], -r["evaluations"], r["setup_type"]))
        return {
            "detectors": rows,
            "total_evals": int(sum(evals.values())),
            "total_hits": int(sum(hits.values())),
        }

    return {
        "success": True,
        "running": bool(getattr(live_scanner, "_running", False)),
        "scan_count": int(getattr(live_scanner, "_scan_count", 0)),
        "symbols_scanned_last": int(getattr(live_scanner, "_symbols_scanned_last", 0)),
        "symbols_skipped_adv": int(getattr(live_scanner, "_symbols_skipped_adv", 0)),
        "symbols_skipped_rvol": int(getattr(live_scanner, "_symbols_skipped_rvol", 0)),
        "last_cycle": _build(last_evals, last_hits),
        "cumulative": _build(cum_evals, cum_hits),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/setup-coverage")
def get_setup_coverage():
    """Cross-reference the live scanner's enabled_setups against the
    registered detector functions. Surfaces three classes of problem:

      - `orphan_enabled_setups`: in `_enabled_setups` but no checker
        function in `_check_setup`'s `checkers` dict. These are silent
        no-ops — the scanner wastes a loop iteration per scan cycle on
        them but emits nothing.

      - `silent_detectors`: enabled AND has a checker, but cumulative
        hit count is 0 across all evaluations. Either thresholds are
        too tight or upstream data is missing. Operator can use this
        list to prioritize threshold-tuning audits.

      - `active_detectors`: enabled, has a checker, AND has emitted at
        least one alert. Sorted by hit count.

    Also includes `unenabled_with_checkers` — registered but not in
    `_enabled_setups` (the inverse orphan: the code exists but the bot
    won't ever ask for it).

    2026-04-29 (afternoon-15): added so the operator doesn't have to
    grep `enhanced_scanner.py` to identify dead enabled_setups names.
    """
    try:
        from services.enhanced_scanner import get_enhanced_scanner
        scanner = get_enhanced_scanner()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scanner unavailable: {e}")

    if not scanner:
        raise HTTPException(status_code=503, detail="Scanner not initialized")

    # Read the registered-checker keys from the source of truth: build
    # a dummy snapshot/tape, hit `_check_setup` with a known-bad
    # setup_type to introspect the dict — but that's brittle. Easier:
    # scan the source of `_check_setup` for keys. Since this is a
    # diagnostic endpoint, hit the scanner instance's evaluation
    # totals: every key that has ever been called lives in
    # `_detector_evals_total`. That's a sufficient proxy for "has a
    # registered checker" because the counter only increments inside
    # the `if checker:` branch.
    cum_evals: Dict[str, int] = getattr(scanner, "_detector_evals_total", {}) or {}
    cum_hits: Dict[str, int] = getattr(scanner, "_detector_hits_total", {}) or {}
    enabled: set = set(getattr(scanner, "_enabled_setups", set()) or set())

    # `REGISTERED_SETUP_TYPES` is a class-level frozenset that lists
    # every setup_type with a checker function in `_check_setup`.
    # Distinguishes TRUE orphans (no code at all) from time-window-
    # filtered setups (have code, blocked by `_is_setup_valid_now`).
    registered: set = set(getattr(
        type(scanner), "REGISTERED_SETUP_TYPES", frozenset()
    ))
    # `evaluated`: subset of registered that has actually been called
    # at least once since startup. Setups in registered-but-not-
    # evaluated are time-window/regime-filtered.
    evaluated: set = set(cum_evals.keys())

    orphan_enabled = sorted(enabled - registered)
    time_filtered = sorted((enabled & registered) - evaluated)
    silent = sorted(
        [s for s in (enabled & evaluated) if cum_hits.get(s, 0) == 0],
        key=lambda s: -cum_evals.get(s, 0),
    )
    active = sorted(
        [s for s in (enabled & evaluated) if cum_hits.get(s, 0) > 0],
        key=lambda s: -cum_hits.get(s, 0),
    )
    unenabled_with_checkers = sorted(registered - enabled)

    def _row(s: str) -> Dict[str, Any]:
        e = int(cum_evals.get(s, 0))
        h = int(cum_hits.get(s, 0))
        proximity = None
        try:
            # Only silent detectors carry proximity data — keeps the
            # response payload focused.
            if h == 0 and hasattr(scanner, "get_proximity_audit"):
                proximity = scanner.get_proximity_audit(s)
        except Exception:
            proximity = None
        row = {
            "setup_type": s,
            "evaluations": e,
            "hits": h,
            "hit_rate_pct": round((h / e) * 100, 1) if e else 0.0,
        }
        if proximity:
            row["threshold_proximity"] = proximity
        return row

    return {
        "success": True,
        "running": bool(getattr(scanner, "_running", False)),
        "scan_count": int(getattr(scanner, "_scan_count", 0)),
        "totals": {
            "enabled_setups": len(enabled),
            "registered_checkers": len(registered),
            "evaluated_at_least_once": len(evaluated),
            "orphan_count": len(orphan_enabled),
            "time_filtered_count": len(time_filtered),
            "silent_count": len(silent),
            "active_count": len(active),
            "unenabled_count": len(unenabled_with_checkers),
        },
        "orphan_enabled_setups": [
            {
                "setup_type": s,
                "issue": "in _enabled_setups but no registered checker function — silent no-op every scan",
            }
            for s in orphan_enabled
        ],
        "time_filtered_setups": [
            {
                "setup_type": s,
                "issue": "checker exists but _is_setup_valid_now blocks it in current time-window/regime — expected for opening/morning-only setups during afternoon",
            }
            for s in time_filtered
        ],
        "silent_detectors": [_row(s) for s in silent],
        "active_detectors": [_row(s) for s in active],
        "unenabled_with_checkers": [
            {"setup_type": s, "issue": "checker exists but not in _enabled_setups — code is unused"}
            for s in unenabled_with_checkers
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/setup-trade-matrix")
async def get_setup_trade_matrix():
    """
    Bellafiore Setup × Trade matrix.

    Returns the canonical operator-defined matrix mapping each Trade
    (`setup_type`) to its valid daily Setups, plus a real-time
    breakdown of which Setup each currently-classified symbol is in
    (so the UI can render the matrix as a heat-grid with live counts).

    Response shape:
        {
            "setups":          [list of MarketSetup values],
            "trades":          [list of trade `setup_type` keys],
            "matrix":          { trade: { setup: "with_trend"|"countertrend" } },
            "experimental":    [trades not gated by the matrix],
            "aliases":         { deprecated_name: canonical_name },
            "classifier_stats": {...},
        }
    """
    try:
        from services.market_setup_classifier import (
            get_market_setup_classifier, TRADE_SETUP_MATRIX,
            EXPERIMENTAL_TRADES, TRADE_ALIASES, MarketSetup,
        )
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Classifier import failed: {e}")
    classifier = get_market_setup_classifier()
    matrix_serialized = {
        trade: {setup.value: ctx.value for setup, ctx in cells.items()}
        for trade, cells in TRADE_SETUP_MATRIX.items()
    }
    return {
        "setups": [s.value for s in MarketSetup],
        "trades": sorted(TRADE_SETUP_MATRIX.keys()),
        "matrix": matrix_serialized,
        "experimental": sorted(EXPERIMENTAL_TRADES),
        "aliases": dict(TRADE_ALIASES),
        "classifier_stats": classifier.stats(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
