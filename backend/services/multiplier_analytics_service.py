"""
multiplier_analytics_service.py — A/B-style analytics for the
liquidity-aware execution layers shipped 2026-04-28e.

Slices `bot_trades` into "snap fired" vs "snap didn't fire" cohorts
across the three sizing dials (volatility, regime, vp_path), the
stop-guard, and the target-snap. Returns mean realized R-multiple,
win rate, and sample size per cohort so the operator can tell at a
glance whether the snap layers actually move live P&L.

Pure logic, no FastAPI / no Mongo writes — the HTTP wrapper lives in
`routers/trading_bot.py`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ─── Helpers ────────────────────────────────────────────────────────────

def _safe_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:   # NaN
        return None
    return f


def _bucket_summary(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return summary stats for a cohort of trades."""
    if not trades:
        return {"count": 0, "mean_r": None, "median_r": None,
                "win_rate": None, "total_pnl": None}
    rs: List[float] = []
    pnls: List[float] = []
    wins = 0
    for t in trades:
        r = _safe_float(t.get("realized_r_multiple") or t.get("r_multiple"))
        if r is not None:
            rs.append(r)
            if r > 0:
                wins += 1
        p = _safe_float(t.get("realized_pnl") or t.get("pnl"))
        if p is not None:
            pnls.append(p)
    rs_sorted = sorted(rs)
    median_r = rs_sorted[len(rs_sorted) // 2] if rs_sorted else None
    return {
        "count": len(trades),
        "mean_r":   round(sum(rs) / len(rs), 3) if rs else None,
        "median_r": round(median_r, 3) if median_r is not None else None,
        "win_rate": round(wins / len(rs), 3) if rs else None,
        "total_pnl": round(sum(pnls), 2) if pnls else None,
    }


def _has_snapped_target(entry_ctx: Dict[str, Any]) -> bool:
    snaps = (entry_ctx.get("multipliers") or {}).get("target_snap") or []
    return any(bool(s.get("snapped")) for s in snaps if isinstance(s, dict))


def _has_widened_stop(entry_ctx: Dict[str, Any]) -> bool:
    sg = (entry_ctx.get("multipliers") or {}).get("stop_guard") or {}
    return bool(sg.get("snapped"))


def _vp_path_active(entry_ctx: Dict[str, Any]) -> bool:
    vp = (entry_ctx.get("multipliers") or {}).get("vp_path")
    f = _safe_float(vp)
    return f is not None and f < 1.0


# ─── Public API ─────────────────────────────────────────────────────────

def compute_multiplier_analytics(
    db,
    days_back: int = 30,
    only_closed: bool = True,
) -> Dict[str, Any]:
    """Walk `bot_trades` over the last `days_back` days and bucket
    each closed trade by which liquidity-aware layer fired. Returns:

        {
          "window_days": int,
          "total_trades": int,
          "stop_guard": {
            "fired":     {count, mean_r, median_r, win_rate, total_pnl},
            "not_fired": {...},
          },
          "target_snap": {fired, not_fired},
          "vp_path":     {downsized, full_size},
          "as_of":       <iso ts>,
        }

    Skipped fields default to `None` if the cohort is empty. The
    intended UI is a single tab showing both cohorts side-by-side per
    layer so the operator can eyeball lift / regression at a glance.
    """
    if db is None:
        return {
            "window_days": days_back,
            "total_trades": 0,
            "stop_guard":  {"fired": _bucket_summary([]), "not_fired": _bucket_summary([])},
            "target_snap": {"fired": _bucket_summary([]), "not_fired": _bucket_summary([])},
            "vp_path":     {"downsized": _bucket_summary([]), "full_size": _bucket_summary([])},
            "as_of": datetime.now(timezone.utc).isoformat(),
            "error": "db not available",
        }

    cutoff = datetime.now(timezone.utc) - timedelta(days=int(days_back))
    cutoff_iso = cutoff.isoformat()

    query: Dict[str, Any] = {
        "$or": [
            {"created_at": {"$gte": cutoff_iso}},
            {"entered_at": {"$gte": cutoff_iso}},
            {"opened_at":  {"$gte": cutoff_iso}},
        ],
    }
    if only_closed:
        query["status"] = "closed"

    sg_fired: List[Dict[str, Any]] = []
    sg_not:   List[Dict[str, Any]] = []
    ts_fired: List[Dict[str, Any]] = []
    ts_not:   List[Dict[str, Any]] = []
    vp_down:  List[Dict[str, Any]] = []
    vp_full:  List[Dict[str, Any]] = []
    total = 0

    try:
        cursor = db["bot_trades"].find(
            query,
            {
                "_id": 0,
                "id": 1, "symbol": 1, "status": 1,
                "realized_r_multiple": 1, "r_multiple": 1,
                "realized_pnl": 1, "pnl": 1,
                "entry_context": 1,
                "created_at": 1,
            },
        )
        for trade in cursor:
            total += 1
            ec = trade.get("entry_context") or {}
            if _has_widened_stop(ec):
                sg_fired.append(trade)
            else:
                sg_not.append(trade)
            if _has_snapped_target(ec):
                ts_fired.append(trade)
            else:
                ts_not.append(trade)
            if _vp_path_active(ec):
                vp_down.append(trade)
            else:
                vp_full.append(trade)
    except Exception as exc:
        return {
            "window_days": days_back,
            "total_trades": 0,
            "stop_guard":  {"fired": _bucket_summary([]), "not_fired": _bucket_summary([])},
            "target_snap": {"fired": _bucket_summary([]), "not_fired": _bucket_summary([])},
            "vp_path":     {"downsized": _bucket_summary([]), "full_size": _bucket_summary([])},
            "as_of": datetime.now(timezone.utc).isoformat(),
            "error": str(exc),
        }

    return {
        "window_days": days_back,
        "total_trades": total,
        "stop_guard": {
            "fired":     _bucket_summary(sg_fired),
            "not_fired": _bucket_summary(sg_not),
        },
        "target_snap": {
            "fired":     _bucket_summary(ts_fired),
            "not_fired": _bucket_summary(ts_not),
        },
        "vp_path": {
            "downsized": _bucket_summary(vp_down),
            "full_size": _bucket_summary(vp_full),
        },
        "as_of": datetime.now(timezone.utc).isoformat(),
    }
