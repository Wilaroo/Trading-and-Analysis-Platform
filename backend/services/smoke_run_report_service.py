"""
smoke_run_report_service.py — paper-mode smoke-run go/no-go report.

================================================================
Used to convert the operator's "did the bot work overnight?" gut-
check into a single mechanical report. Run it after a PAPER smoke
session; if every line is green, you flip LIVE with confidence.

CONTRACT:
  - Read-only — never mutates state, never triggers anything.
  - Pure aggregation over the last `hours_back` of operational data.
  - Returns a single dict with one entry per pipeline phase + overall
    `verdict` ∈ {"green", "amber", "red"}.

Used by:
  - `POST /api/trading-bot/smoke-run-report?hours_back=24`
  - Future: nightly scheduled run that posts to Slack/Telegram
================================================================
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ─── Tunables ───────────────────────────────────────────────────────────

# Phase-1 (SCAN) — how many sweeps we expect per hour during overnight
# (after-hours sweep cadence is 20 min ⇒ 3 per hour).
_EXPECTED_AFTER_HOURS_SWEEPS_PER_HOUR = 3

# Phase-3 (ORDER) — fill-rate floor. Below this is amber.
_FILL_RATE_AMBER = 0.85
_FILL_RATE_RED   = 0.60

# Phase-3 (ORDER) — RPC latency p99 floor (ms).
_RPC_P99_AMBER_MS = 2000
_RPC_P99_RED_MS   = 5000

# Coverage of `entry_context.multipliers` in bot_trades. < this → amber.
_MULTIPLIER_COVERAGE_AMBER = 0.85
_MULTIPLIER_COVERAGE_RED   = 0.50


# ─── Helpers ────────────────────────────────────────────────────────────

def _classify(value: Optional[float], red: float, amber: float,
              higher_is_better: bool = True) -> str:
    """Return 'green' | 'amber' | 'red' from a numeric metric."""
    if value is None:
        return "amber"   # missing data isn't fatal but is a yellow flag
    if higher_is_better:
        if value >= amber:
            return "green"
        if value >= red:
            return "amber"
        return "red"
    else:
        if value <= amber:
            return "green"
        if value <= red:
            return "amber"
        return "red"


def _safe_count(coll, query: Dict[str, Any]) -> int:
    try:
        return coll.count_documents(query)
    except Exception:
        return 0


# ─── Phase reporters ────────────────────────────────────────────────────

def _phase1_scan(db, cutoff_iso: str) -> Dict[str, Any]:
    """SCAN phase: how many sweeps fired, how many alerts produced, top
    setup types and TQS distribution."""
    out: Dict[str, Any] = {"phase": "SCAN"}

    # Most projects don't log every sweep firing to Mongo; we infer from
    # `live_alerts` row creation timestamps + scanner stats endpoint
    # data when available. Here we use the alert count as a proxy.
    alerts_coll = db["live_alerts"]
    alert_count = _safe_count(alerts_coll, {"created_at": {"$gte": cutoff_iso}})
    out["alerts_created"] = alert_count

    # Setup-type distribution (top 5)
    try:
        cursor = alerts_coll.aggregate([
            {"$match": {"created_at": {"$gte": cutoff_iso}}},
            {"$group": {"_id": "$setup_type", "n": {"$sum": 1}}},
            {"$sort":  {"n": -1}},
            {"$limit": 5},
        ])
        out["top_setups"] = [
            {"setup_type": d["_id"], "count": d["n"]} for d in cursor
        ]
    except Exception:
        out["top_setups"] = []

    # TQS distribution
    try:
        agg = list(alerts_coll.aggregate([
            {"$match": {"created_at": {"$gte": cutoff_iso}}},
            {"$group": {
                "_id": None,
                "mean_tqs": {"$avg": "$tqs_score"},
                "n": {"$sum": 1},
            }},
        ]))
        if agg:
            out["mean_tqs"] = round(agg[0].get("mean_tqs") or 0, 1)
    except Exception:
        pass

    out["status"] = "green" if alert_count >= 5 else "amber" if alert_count >= 1 else "red"
    return out


def _phase2_eval(db, cutoff_iso: str) -> Dict[str, Any]:
    """EVAL phase: how many bot_trades were sized, what % carry full
    multiplier provenance."""
    out: Dict[str, Any] = {"phase": "EVAL"}
    trades_coll = db["bot_trades"]
    total = _safe_count(trades_coll, {"created_at": {"$gte": cutoff_iso}})
    out["trades_created"] = total

    if total == 0:
        out["status"] = "amber"
        out["multiplier_coverage"] = None
        return out

    # Multiplier-meta coverage
    with_meta = _safe_count(trades_coll, {
        "created_at": {"$gte": cutoff_iso},
        "entry_context.multipliers": {"$exists": True},
    })
    coverage = with_meta / total
    out["multiplier_coverage"] = round(coverage, 3)
    out["with_multiplier_meta"] = with_meta

    out["status"] = _classify(coverage, _MULTIPLIER_COVERAGE_RED,
                              _MULTIPLIER_COVERAGE_AMBER)
    return out


def _phase3_order(db, cutoff_iso: str) -> Dict[str, Any]:
    """ORDER phase: order count, fill rate, mean RPC latency."""
    out: Dict[str, Any] = {"phase": "ORDER"}
    orders_coll = db["bot_orders"] if "bot_orders" in db.list_collection_names() else None
    if orders_coll is None:
        # Fallback: check `order_history` or `ib_order_log`
        for cand in ("order_history", "ib_order_log", "trade_orders"):
            try:
                if cand in db.list_collection_names():
                    orders_coll = db[cand]
                    break
            except Exception:
                continue

    if orders_coll is None:
        out["status"] = "amber"
        out["note"] = "no order log collection found"
        return out

    total = _safe_count(orders_coll, {"created_at": {"$gte": cutoff_iso}})
    filled = _safe_count(orders_coll, {
        "created_at": {"$gte": cutoff_iso},
        "status": {"$in": ["filled", "FILLED", "complete"]},
    })
    out["orders_placed"] = total
    out["orders_filled"] = filled
    out["fill_rate"] = round(filled / total, 3) if total else None

    # RPC latency from pusher_health collection if present
    try:
        if "pusher_health_history" in db.list_collection_names():
            health = list(db["pusher_health_history"].find(
                {"recorded_at": {"$gte": cutoff_iso}},
                {"_id": 0, "rpc_latency_p99_ms": 1},
            ).limit(500))
            p99s = [h.get("rpc_latency_p99_ms") for h in health
                    if h.get("rpc_latency_p99_ms") is not None]
            if p99s:
                out["rpc_p99_ms_max"] = max(p99s)
    except Exception:
        pass

    fill_status = _classify(out["fill_rate"], _FILL_RATE_RED, _FILL_RATE_AMBER)
    rpc_status  = _classify(out.get("rpc_p99_ms_max"),
                            _RPC_P99_RED_MS, _RPC_P99_AMBER_MS,
                            higher_is_better=False)
    out["status"] = "red" if "red" in {fill_status, rpc_status} \
                    else "amber" if "amber" in {fill_status, rpc_status} \
                    else "green"
    return out


def _phase4_manage(db, cutoff_iso: str) -> Dict[str, Any]:
    """MANAGE phase: stop-adjustment count, partial-exit count, current
    open positions."""
    out: Dict[str, Any] = {"phase": "MANAGE"}
    trades_coll = db["bot_trades"]
    open_count = _safe_count(trades_coll, {"status": "open"})
    out["currently_open"] = open_count

    # Trail / breakeven moves recorded in stop_adjustment_log if present
    try:
        if "stop_adjustment_log" in db.list_collection_names():
            adjusts = _safe_count(db["stop_adjustment_log"],
                                   {"adjusted_at": {"$gte": cutoff_iso}})
            out["stop_adjustments"] = adjusts
    except Exception:
        pass

    out["status"] = "green"
    return out


def _phase5_close(db, cutoff_iso: str) -> Dict[str, Any]:
    """CLOSE phase: closed trade count, % wins, mean realized R."""
    out: Dict[str, Any] = {"phase": "CLOSE"}
    trades_coll = db["bot_trades"]
    closed = list(trades_coll.find(
        {"status": "closed", "created_at": {"$gte": cutoff_iso}},
        {"_id": 0, "id": 1, "realized_pnl": 1, "realized_r_multiple": 1,
         "exit_reason": 1},
    ))
    out["trades_closed"] = len(closed)
    if not closed:
        out["status"] = "amber"
        return out

    rs   = [t.get("realized_r_multiple") for t in closed
            if t.get("realized_r_multiple") is not None]
    pnls = [t.get("realized_pnl") for t in closed
            if t.get("realized_pnl") is not None]
    if rs:
        wins = sum(1 for r in rs if r > 0)
        out["win_rate"] = round(wins / len(rs), 3)
        out["mean_r"] = round(sum(rs) / len(rs), 3)
    if pnls:
        out["total_pnl"] = round(sum(pnls), 2)

    # Exit-reason distribution (proxy for whether MANAGE was hitting
    # targets vs stops vs EOD-closing).
    reason_counts: Dict[str, int] = {}
    for t in closed:
        r = t.get("exit_reason") or "unknown"
        reason_counts[r] = reason_counts.get(r, 0) + 1
    out["exit_reasons"] = reason_counts

    out["status"] = "green"
    return out


def _phase_health(db, cutoff_iso: str) -> Dict[str, Any]:
    """Live health monitor + safety guardrail trips."""
    out: Dict[str, Any] = {"phase": "HEALTH"}
    try:
        if "kill_switch_history" in db.list_collection_names():
            trips = _safe_count(db["kill_switch_history"],
                                 {"triggered_at": {"$gte": cutoff_iso}})
            out["kill_switch_trips"] = trips
        else:
            out["kill_switch_trips"] = 0
    except Exception:
        out["kill_switch_trips"] = 0

    out["status"] = "green" if (out.get("kill_switch_trips") or 0) == 0 \
                    else "red"
    return out


# ─── Public API ────────────────────────────────────────────────────────

def compute_smoke_run_report(db, hours_back: int = 24) -> Dict[str, Any]:
    """Aggregate the last `hours_back` of activity into a single
    go/no-go report. Phase status colors roll up to a single `verdict`:
      - red   if ANY phase is red
      - amber if any phase is amber
      - green otherwise
    """
    if db is None:
        return {
            "verdict": "red",
            "reason": "db not available",
            "phases": [],
            "as_of": datetime.now(timezone.utc).isoformat(),
        }

    cutoff = datetime.now(timezone.utc) - timedelta(hours=int(hours_back))
    cutoff_iso = cutoff.isoformat()

    phases: List[Dict[str, Any]] = []
    try:
        phases.append(_phase1_scan(db,    cutoff_iso))
    except Exception as e:
        phases.append({"phase": "SCAN", "status": "amber", "error": str(e)})
    try:
        phases.append(_phase2_eval(db,    cutoff_iso))
    except Exception as e:
        phases.append({"phase": "EVAL", "status": "amber", "error": str(e)})
    try:
        phases.append(_phase3_order(db,   cutoff_iso))
    except Exception as e:
        phases.append({"phase": "ORDER", "status": "amber", "error": str(e)})
    try:
        phases.append(_phase4_manage(db,  cutoff_iso))
    except Exception as e:
        phases.append({"phase": "MANAGE", "status": "amber", "error": str(e)})
    try:
        phases.append(_phase5_close(db,   cutoff_iso))
    except Exception as e:
        phases.append({"phase": "CLOSE", "status": "amber", "error": str(e)})
    try:
        phases.append(_phase_health(db,   cutoff_iso))
    except Exception as e:
        phases.append({"phase": "HEALTH", "status": "amber", "error": str(e)})

    statuses = {p.get("status", "amber") for p in phases}
    verdict = "red" if "red" in statuses else "amber" if "amber" in statuses else "green"

    return {
        "verdict": verdict,
        "window_hours": hours_back,
        "phases": phases,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "summary": _human_summary(phases, verdict),
    }


def _human_summary(phases: List[Dict[str, Any]], verdict: str) -> str:
    """One-paragraph operator-readable summary, suitable for a
    Slack/Telegram post or a UI banner."""
    lines = [f"Smoke-run verdict: {verdict.upper()}"]
    for p in phases:
        name = p.get("phase", "?")
        s = p.get("status", "?")
        if name == "SCAN":
            lines.append(
                f"• SCAN [{s}] — {p.get('alerts_created', 0)} alerts, "
                f"mean TQS {p.get('mean_tqs')}"
            )
        elif name == "EVAL":
            lines.append(
                f"• EVAL [{s}] — {p.get('trades_created', 0)} trades sized, "
                f"multiplier coverage {p.get('multiplier_coverage')}"
            )
        elif name == "ORDER":
            lines.append(
                f"• ORDER [{s}] — {p.get('orders_placed', 0)} orders, "
                f"fill rate {p.get('fill_rate')}, RPC p99 max "
                f"{p.get('rpc_p99_ms_max')}ms"
            )
        elif name == "MANAGE":
            lines.append(
                f"• MANAGE [{s}] — {p.get('currently_open', 0)} open, "
                f"{p.get('stop_adjustments', 0)} stop adjustments"
            )
        elif name == "CLOSE":
            lines.append(
                f"• CLOSE [{s}] — {p.get('trades_closed', 0)} closed, "
                f"win rate {p.get('win_rate')}, mean R {p.get('mean_r')}"
            )
        elif name == "HEALTH":
            lines.append(
                f"• HEALTH [{s}] — {p.get('kill_switch_trips', 0)} kill-switch trips"
            )
    return "\n".join(lines)
