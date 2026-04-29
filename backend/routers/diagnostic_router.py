"""
diagnostic_router — "where did the trades die today?" forensics.
=================================================================

Single endpoint that walks the full alert-to-execution chain for any
calendar day and returns the per-gate pass/fail counts so the operator
can pinpoint *which* gate killed flow without grepping logs.

Endpoint:
    GET /api/diagnostic/trade-funnel?date=YYYY-MM-DD

Funnel stages (in order):

    SCANNER STAGE
        ↓ Total alerts in `live_alerts` for the day
    PRIORITY GATE
        ↓ HIGH + CRITICAL only
    TAPE-CONFIRMATION GATE
        ↓ alert.tape_confirmation == True
    AUTO-EXECUTE-ELIGIBLE GATE
        ↓ alert.auto_execute_eligible == True
    BOT MASTER SWITCH
        ↓ bot_state.auto_execute_enabled == True
    BOT MODE
        ↓ AUTONOMOUS (else trades go to pending, never to broker)
    BOT EVALUATION
        ↓ `_evaluate_opportunity` returned a BotTrade (not None)
    PRE-EXECUTION FILTERS
        ↓ Trade status != PAPER / SIMULATED / VETOED
    EXECUTION ATTEMPT
        ↓ `_execute_trade` succeeded (status != REJECTED)
    BROKER FILL
        ↓ status == OPEN/PARTIAL/CLOSED (vs. CANCELLED)

Returns a structured ``stages`` array + a top-level ``diagnosis`` string
that names the FIRST stage where flow dropped to zero so the operator
sees the answer at a glance.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/diagnostic", tags=["diagnostic"])


def _get_db():
    """Pull the same Mongo handle server.py exposes via `database.get_database`.

    Falls back to a local MongoClient only if the global hasn't been set
    yet (cold-start before lifespan finishes).
    """
    try:
        from database import get_database
        db = get_database()
        if db is not None:
            return db
    except Exception:
        pass
    import os
    from pymongo import MongoClient
    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        raise HTTPException(status_code=500, detail="MONGO_URL not configured")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    return MongoClient(mongo_url)[db_name]


def _trading_day_iso(date_str: Optional[str]) -> str:
    """Validate / default the trading-day argument to today (UTC)."""
    if date_str is None or not date_str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")


def _date_range_filter(field: str, day_iso: str) -> Dict:
    """ISO-prefix scan — works whether the field stores str or datetime."""
    next_day = (datetime.strptime(day_iso, "%Y-%m-%d") + timedelta(days=1)
                ).strftime("%Y-%m-%d")
    return {
        "$or": [
            {field: {"$gte": day_iso, "$lt": next_day}},   # string sort
            {field: {"$regex": f"^{day_iso}"}},             # ISO prefix
        ]
    }


@router.get("/trade-funnel")
def trade_funnel(date: Optional[str] = None) -> Dict[str, Any]:
    """Walk the alert → bot → execution chain and report per-gate counts."""
    day = _trading_day_iso(date)
    db = _get_db()

    stages: List[Dict[str, Any]] = []

    # ───────── 1. Scanner output ─────────
    total_alerts = db["live_alerts"].count_documents(
        _date_range_filter("created_at", day)
    )
    stages.append({
        "stage": "scanner_alerts",
        "label": "Total alerts generated",
        "count": total_alerts,
        "kill_check": total_alerts == 0,
        "kill_reason": "Scanner produced zero alerts today (universe / time / RVOL / ADV gates)",
    })

    # ───────── 2. Priority breakdown ─────────
    priority_breakdown: Dict[str, int] = {}
    for d in db["live_alerts"].aggregate([
        {"$match": _date_range_filter("created_at", day)},
        {"$group": {"_id": "$priority", "count": {"$sum": 1}}},
    ]):
        priority_breakdown[str(d["_id"]).lower()] = d["count"]
    high_critical = priority_breakdown.get("high", 0) + priority_breakdown.get("critical", 0)
    stages.append({
        "stage": "priority_high_or_critical",
        "label": "Alerts with HIGH or CRITICAL priority (auto-execute candidates)",
        "count": high_critical,
        "breakdown": priority_breakdown,
        "kill_check": total_alerts > 0 and high_critical == 0,
        "kill_reason": "Alerts fired but none were HIGH/CRITICAL — only those auto-execute",
    })

    # ───────── 3. Tape confirmation ─────────
    tape_confirmed = db["live_alerts"].count_documents({
        **_date_range_filter("created_at", day),
        "priority": {"$in": ["high", "critical", "HIGH", "CRITICAL"]},
        "tape_confirmation": True,
    })
    stages.append({
        "stage": "tape_confirmed",
        "label": "HIGH/CRITICAL alerts that ALSO had tape confirmation",
        "count": tape_confirmed,
        "kill_check": high_critical > 0 and tape_confirmed == 0,
        "kill_reason": "Priority alerts fired but tape didn't confirm — bid/ask, momentum, imbalance signals were neutral",
    })

    # ───────── 4. auto_execute_eligible ─────────
    auto_eligible = db["live_alerts"].count_documents({
        **_date_range_filter("created_at", day),
        "auto_execute_eligible": True,
    })
    stages.append({
        "stage": "auto_execute_eligible",
        "label": "Alerts flagged auto_execute_eligible by the scanner",
        "count": auto_eligible,
        "kill_check": tape_confirmed > 0 and auto_eligible == 0,
        "kill_reason": "Tape-confirmed alerts didn't earn auto-execute flag — strategy win-rate floor or master switch off",
    })

    # ───────── 5. Bot master switch + mode ─────────
    bot_state = db["bot_state"].find_one({}) or {}
    auto_execute_enabled = bool(bot_state.get("auto_execute_enabled", False))
    bot_mode = str(bot_state.get("bot_mode") or bot_state.get("mode") or "unknown")
    stages.append({
        "stage": "bot_master_switch",
        "label": "Bot auto_execute_enabled flag",
        "count": int(auto_execute_enabled),
        "value": auto_execute_enabled,
        "kill_check": auto_eligible > 0 and not auto_execute_enabled,
        "kill_reason": "Eligible alerts existed but the bot's auto_execute master switch is OFF",
    })
    stages.append({
        "stage": "bot_mode",
        "label": "Bot mode",
        "value": bot_mode,
        "count": 1 if bot_mode.lower() == "autonomous" else 0,
        "kill_check": (auto_eligible > 0 and auto_execute_enabled
                        and bot_mode.lower() != "autonomous"),
        "kill_reason": (
            f"Bot mode is {bot_mode!r}, not AUTONOMOUS — eligible trades are queued "
            "in `_pending_trades` waiting for human confirmation"
        ),
    })

    # ───────── 6. Bot trades created ─────────
    total_bot_trades = db["bot_trades"].count_documents(
        _date_range_filter("entered_at", day)
    )
    if total_bot_trades == 0:
        # Some installs use `created_at` instead of `entered_at`
        total_bot_trades = db["bot_trades"].count_documents(
            _date_range_filter("created_at", day)
        )
    stages.append({
        "stage": "bot_trades_created",
        "label": "BotTrade records the bot actually wrote",
        "count": total_bot_trades,
        "kill_check": auto_eligible > 0 and auto_execute_enabled and total_bot_trades == 0,
        "kill_reason": (
            "auto_execute_eligible alerts existed and the master switch is ON, "
            "but `_evaluate_opportunity` rejected every one — check daily-loss "
            "guardrail, stale-quote guard, exposure caps, max concurrent positions"
        ),
    })

    # ───────── 7. Bot trade status breakdown ─────────
    status_breakdown: Dict[str, int] = {}
    for d in db["bot_trades"].aggregate([
        {"$match": _date_range_filter("entered_at", day)},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]):
        status_breakdown[str(d["_id"]).lower()] = d["count"]
    if not status_breakdown:
        for d in db["bot_trades"].aggregate([
            {"$match": _date_range_filter("created_at", day)},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]):
            status_breakdown[str(d["_id"]).lower()] = d["count"]
    pre_filtered = (status_breakdown.get("paper", 0)
                    + status_breakdown.get("simulated", 0)
                    + status_breakdown.get("vetoed", 0))
    stages.append({
        "stage": "pre_execution_filters",
        "label": "Trades killed by PAPER/SIMULATED/VETOED gates (never reach broker)",
        "count": pre_filtered,
        "breakdown": {k: status_breakdown.get(k, 0)
                      for k in ("paper", "simulated", "vetoed")},
        "kill_check": total_bot_trades > 0 and pre_filtered == total_bot_trades,
        "kill_reason": (
            "Every bot-created trade was diverted to PAPER / SIMULATED / VETOED — "
            "strategies are in pre-execution phases (paper-trade phase, sim phase) "
            "or hit a guardrail (tight stop, oversized notional)"
        ),
    })
    submitted = (status_breakdown.get("open", 0)
                 + status_breakdown.get("partial", 0)
                 + status_breakdown.get("closed", 0)
                 + status_breakdown.get("cancelled", 0)
                 + status_breakdown.get("rejected", 0))
    stages.append({
        "stage": "broker_submitted",
        "label": "Trades that actually reached the broker (any final status)",
        "count": submitted,
        "breakdown": {k: status_breakdown.get(k, 0)
                      for k in ("open", "partial", "closed", "cancelled",
                                "rejected", "pending")},
        "kill_check": total_bot_trades > 0 and submitted == 0,
        "kill_reason": (
            "Trades were created but never submitted to the broker — likely the "
            "execution attempt itself failed (IB Gateway down? order_queue stuck?)"
        ),
    })

    # ───────── 8. Order queue activity (IB pusher view) ─────────
    queue_breakdown: Dict[str, int] = {}
    for d in db["order_queue"].aggregate([
        {"$match": _date_range_filter("created_at", day)},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]):
        queue_breakdown[str(d["_id"]).lower()] = d["count"]
    queue_total = sum(queue_breakdown.values())
    queue_completed = queue_breakdown.get("completed", 0) + queue_breakdown.get("done", 0)
    stages.append({
        "stage": "ib_order_queue",
        "label": "Orders placed in the IB pusher queue today",
        "count": queue_total,
        "breakdown": queue_breakdown,
        "kill_check": submitted > 0 and queue_total == 0,
        "kill_reason": (
            "Bot tried to submit orders but none reached the order_queue "
            "collection — `order_queue_service.enqueue_order` never wrote a row"
        ),
    })
    stages.append({
        "stage": "ib_pusher_consumed",
        "label": "Orders the IB pusher actually claimed + completed",
        "count": queue_completed,
        "kill_check": queue_total > 0 and queue_completed == 0,
        "kill_reason": (
            "Orders were queued but the IB pusher never claimed any — "
            "Windows pusher offline, IB Gateway disconnected, or auth lapsed"
        ),
    })

    # ───────── 9. In-play config (could be quietly killing flow) ─────────
    in_play_cfg = bot_state.get("in_play_config") if isinstance(bot_state, dict) else None
    if not in_play_cfg:
        ipc_doc = db["bot_state"].find_one({"_id": "in_play_config"})
        in_play_cfg = ipc_doc if ipc_doc else None

    # ───────── Diagnosis: name the FIRST stage that killed flow ─────────
    diagnosis = "Trade flow looks healthy — no obvious dead stage."
    first_killed_stage = None
    for s in stages:
        if s.get("kill_check"):
            first_killed_stage = s
            diagnosis = f"🔴 First dead stage: **{s['stage']}** — {s['kill_reason']}"
            break
    if not first_killed_stage and queue_completed > 0:
        diagnosis = (
            f"✅ Flow reached the broker — {queue_completed} order(s) completed via "
            f"the IB pusher today."
        )

    # Read scanner hot counters (cumulative per cycle, not per-day) so the
    # operator can see what the live scanner *just* skipped.
    try:
        from services.enhanced_scanner import get_enhanced_scanner
        scanner = get_enhanced_scanner()
        scanner_hot = {
            "auto_execute_enabled": getattr(scanner, "_auto_execute_enabled", None),
            "auto_execute_min_win_rate": getattr(scanner, "_auto_execute_min_win_rate", None),
            "min_rvol_filter": getattr(scanner, "_min_rvol_filter", None),
            "symbols_skipped_adv": getattr(scanner, "_symbols_skipped_adv", None),
            "symbols_skipped_rvol": getattr(scanner, "_symbols_skipped_rvol", None),
            "symbols_skipped_in_play": getattr(scanner, "_symbols_skipped_in_play", None),
        }
    except Exception:
        scanner_hot = {}

    return {
        "success": True,
        "trading_day": day,
        "diagnosis": diagnosis,
        "first_dead_stage": first_killed_stage["stage"] if first_killed_stage else None,
        "stages": stages,
        "scanner_hot_counters": scanner_hot,
        "in_play_config": in_play_cfg,
        "bot_state_keys": sorted(list(bot_state.keys()))[:30] if bot_state else [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
