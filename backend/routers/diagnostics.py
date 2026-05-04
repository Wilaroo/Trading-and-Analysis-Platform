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


# ─── v19.31.9 — Day Tape ─────────────────────────────────────────────


@router.get("/day-tape")
async def get_day_tape(
    days: int = Query(1, ge=1, le=30),
    direction: Optional[str] = Query(None, pattern="^(long|short)$"),
    setup: Optional[str] = Query(None, max_length=64),
):
    """v19.31.9 — multi-day version of /api/sentcom/positions's
    closed_today array. Powers the new Day Tape tab in Diagnostics
    (5-day / 30-day toggle + CSV export).

    Returns:
      {
        success: True,
        days,
        from_iso, to_iso,
        rows: [...],
        summary: {
          count, wins, losses, scratches,
          gross_pnl, win_rate, avg_r,
          biggest_winner, biggest_loser,
          by_setup: { setup_name: { count, win_rate, gross_pnl } },
          by_direction: { long: {...}, short: {...} },
        },
      }
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="db not initialised")

    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    now_utc = _dt.now(_tz.utc)
    cutoff = (now_utc - _td(days=days)).isoformat()

    query: Dict[str, Any] = {
        "status": "closed",
        "$or": [
            {"closed_at": {"$gte": cutoff}},
            {"closed_at": None, "executed_at": {"$gte": cutoff}},
        ],
    }
    if direction:
        query["direction"] = direction
    if setup:
        query["setup_type"] = setup

    try:
        cursor = _db["bot_trades"].find(
            query,
            {"_id": 0},
            sort=[("closed_at", -1), ("executed_at", -1)],
            limit=2000,
        )
        rows = list(cursor)
    except Exception as e:
        logger.warning(f"day-tape lookup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # Summary aggregation
    realized_total = 0.0
    wins = losses = scratches = 0
    r_sum = 0.0
    biggest_winner = None
    biggest_loser = None
    by_setup: Dict[str, Dict[str, Any]] = {}
    by_direction = {
        "long": {"count": 0, "wins": 0, "gross_pnl": 0.0},
        "short": {"count": 0, "wins": 0, "gross_pnl": 0.0},
    }

    out_rows: List[Dict[str, Any]] = []
    for t in rows:
        realized = float(t.get("realized_pnl") or t.get("net_pnl") or t.get("pnl") or 0)
        realized_total += realized
        r = t.get("r_multiple")
        if r is not None:
            try:
                r_sum += float(r)
            except (TypeError, ValueError):
                pass
        if realized > 0:
            wins += 1
            if biggest_winner is None or realized > (biggest_winner.get("realized_pnl") or 0):
                biggest_winner = {"symbol": t.get("symbol"), "realized_pnl": round(realized, 2),
                                  "trade_id": t.get("id"), "closed_at": t.get("closed_at")}
        elif realized < 0:
            losses += 1
            if biggest_loser is None or realized < (biggest_loser.get("realized_pnl") or 0):
                biggest_loser = {"symbol": t.get("symbol"), "realized_pnl": round(realized, 2),
                                 "trade_id": t.get("id"), "closed_at": t.get("closed_at")}
        else:
            scratches += 1

        # by setup
        s = (t.get("setup_type") or "unknown")
        bs = by_setup.setdefault(s, {"count": 0, "wins": 0, "gross_pnl": 0.0})
        bs["count"] += 1
        bs["gross_pnl"] = round(bs["gross_pnl"] + realized, 2)
        if realized > 0:
            bs["wins"] += 1

        # by direction
        d = (t.get("direction") or "").lower()
        if d in by_direction:
            by_direction[d]["count"] += 1
            by_direction[d]["gross_pnl"] = round(by_direction[d]["gross_pnl"] + realized, 2)
            if realized > 0:
                by_direction[d]["wins"] += 1

        out_rows.append({
            "trade_id": t.get("id"),
            "symbol": t.get("symbol"),
            "direction": t.get("direction"),
            "shares": t.get("shares"),
            "entry_price": t.get("fill_price") or t.get("entry_price"),
            "exit_price": t.get("exit_price") or t.get("close_price"),
            "realized_pnl": round(realized, 2),
            "r_multiple": t.get("r_multiple"),
            "executed_at": t.get("executed_at"),
            "closed_at": t.get("closed_at"),
            "close_reason": t.get("close_reason") or t.get("exit_reason"),
            "setup_type": t.get("setup_type"),
            "setup_variant": t.get("setup_variant"),
            "trade_style": t.get("trade_style"),
        })

    # finalize win-rates
    for s, b in by_setup.items():
        b["win_rate"] = round(100.0 * b["wins"] / b["count"], 1) if b["count"] else None
    for d, b in by_direction.items():
        b["win_rate"] = round(100.0 * b["wins"] / b["count"], 1) if b["count"] else None

    total = wins + losses + scratches
    summary = {
        "count": total,
        "wins": wins,
        "losses": losses,
        "scratches": scratches,
        "gross_pnl": round(realized_total, 2),
        "win_rate": round(100.0 * wins / (wins + losses), 1) if (wins + losses) else None,
        "avg_r": round(r_sum / total, 3) if total else None,
        "biggest_winner": biggest_winner,
        "biggest_loser": biggest_loser,
        "by_setup": by_setup,
        "by_direction": by_direction,
    }

    return {
        "success": True,
        "days": days,
        "from_iso": cutoff,
        "to_iso": now_utc.isoformat(),
        "rows": out_rows,
        "summary": summary,
    }


@router.get("/day-tape.csv", response_class=PlainTextResponse)
async def get_day_tape_csv(
    days: int = Query(1, ge=1, le=30),
    direction: Optional[str] = Query(None, pattern="^(long|short)$"),
    setup: Optional[str] = Query(None, max_length=64),
) -> str:
    """v19.31.9 — CSV export of /day-tape rows. Pipe-delimited safe for
    journaling or pasting into a spreadsheet."""
    payload = await get_day_tape(days=days, direction=direction, setup=setup)
    rows = payload.get("rows", [])
    headers = [
        "closed_at", "symbol", "direction", "shares", "entry_price",
        "exit_price", "realized_pnl", "r_multiple", "close_reason",
        "setup_type", "setup_variant", "trade_style", "executed_at", "trade_id",
    ]

    def _q(v):
        if v is None:
            return ""
        s = str(v).replace('"', '""')
        if "," in s or '"' in s or "\n" in s:
            return f'"{s}"'
        return s

    lines = [",".join(headers)]
    for r in rows:
        lines.append(",".join(_q(r.get(h)) for h in headers))
    return "\n".join(lines) + "\n"
