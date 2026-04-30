"""
diagnostics.py — v19.28 Diagnostics endpoints powering the new
"Diagnostics" tab in the V5 side nav.

All endpoints read-only. Heavy lifting in `services/decision_trail.py`.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])

# Lazy-bound at startup. Server.py calls `set_db(...)`.
_db: Any = None


def set_db(db) -> None:
    global _db
    _db = db


@router.get("/recent-decisions")
async def get_recent_decisions(
    limit: int = Query(50, ge=1, le=200),
    symbol: Optional[str] = Query(None, max_length=10),
    setup: Optional[str] = Query(None, max_length=64),
    outcome: Optional[str] = Query(
        None,
        pattern="^(win|loss|scratch|open|shadow_win|shadow_loss|shadow_scratch|shadow_pending)$",
    ),
    only_disagreements: bool = Query(False),
) -> Dict[str, Any]:
    """Paginated list for the Trail Explorer's left rail. See
    `services/decision_trail.list_recent_decisions` for filter semantics."""
    if _db is None:
        raise HTTPException(status_code=503, detail="db not initialised")
    from services.decision_trail import list_recent_decisions
    rows = list_recent_decisions(
        _db,
        limit=limit,
        symbol=symbol,
        setup=setup,
        outcome=outcome,
        only_disagreements=only_disagreements,
    )
    return {"success": True, "rows": rows, "count": len(rows)}


@router.get("/decision-trail/{identifier}")
async def get_decision_trail(identifier: str) -> Dict[str, Any]:
    """Build a full decision trail for one alert/trade/shadow ID. See
    `services/decision_trail.build_decision_trail` for the join logic."""
    if _db is None:
        raise HTTPException(status_code=503, detail="db not initialised")
    if not identifier or len(identifier) > 64:
        raise HTTPException(status_code=400, detail="bad identifier")
    from services.decision_trail import build_decision_trail
    trail = build_decision_trail(_db, identifier)
    if trail is None:
        raise HTTPException(status_code=404, detail=f"no decision found for {identifier}")
    return {"success": True, "trail": trail}


@router.get("/module-scorecard")
async def get_module_scorecard(days: int = Query(7, ge=1, le=90)) -> Dict[str, Any]:
    """Per-AI-module performance over the last `days` — see
    `services/decision_trail.build_module_scorecard`."""
    if _db is None:
        raise HTTPException(status_code=503, detail="db not initialised")
    from services.decision_trail import build_module_scorecard
    return {"success": True, **build_module_scorecard(_db, days=days)}


@router.get("/funnel")
async def get_pipeline_funnel(days: int = Query(1, ge=1, le=30)) -> Dict[str, Any]:
    """Scanner-emit → AI-passed → risk-passed → fired → winners
    funnel for the Diagnostics > Funnel sub-tab (V19.29)."""
    if _db is None:
        raise HTTPException(status_code=503, detail="db not initialised")
    from services.decision_trail import build_pipeline_funnel
    return {"success": True, **build_pipeline_funnel(_db, days=days)}


@router.get("/export-report", response_class=PlainTextResponse)
async def export_report(
    days: int = Query(1, ge=1, le=30),
    fmt: str = Query("markdown", pattern="^(markdown|md)$"),
) -> str:
    """One-click markdown dump combining funnel + scorecard + recent
    decisions + disagreements. Operator pastes this into chat with
    Emergent for tuning suggestions."""
    if _db is None:
        raise HTTPException(status_code=503, detail="db not initialised")
    from services.decision_trail import export_report_markdown
    return export_report_markdown(_db, days=days)
