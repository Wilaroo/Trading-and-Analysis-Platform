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

import asyncio
import logging
from datetime import datetime, timezone
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
    """Validate / default the trading-day argument to today *in ET*.

    Defaulting to UTC's "today" produces the wrong answer between
    20:00-23:59 ET when UTC has already rolled over but the trading
    day hasn't. Using America/New_York gives the operator the answer
    they expect at all hours.
    """
    if date_str is None or not date_str:
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        except Exception:
            return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")


def _date_range_filter(field: str, day_iso: str) -> Dict:
    """Day-prefix match against a string-stored ISO timestamp.

    Uses a regex anchored to the YYYY-MM-DD prefix because that's the
    pattern the rest of the codebase stores `created_at` / `entered_at`
    in (proven via the live_alerts schema dump 2026-04-30). A previous
    version used `$or` between $gte/$lt and $regex which silently
    returned 0 on real data — switched to the simpler proven shape.
    """
    return {field: {"$regex": f"^{day_iso}"}}


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
    # Pull from the actual `bot_state` document (singleton; uses key
    # `mode` not `bot_mode`). Also reads the live scanner's in-memory
    # `_auto_execute_enabled` because that's what actually gates flow
    # — the bot_state collection doesn't persist that flag separately.
    bot_state = db["bot_state"].find_one({}) or {}
    bot_mode = str(bot_state.get("mode") or bot_state.get("bot_mode") or "unknown")
    auto_execute_enabled = False
    try:
        from services.enhanced_scanner import get_enhanced_scanner
        scanner = get_enhanced_scanner()
        auto_execute_enabled = bool(getattr(scanner, "_auto_execute_enabled", False))
    except Exception:
        pass
    stages.append({
        "stage": "bot_master_switch",
        "label": "Scanner _auto_execute_enabled (synced from bot mode on start/set)",
        "count": int(auto_execute_enabled),
        "value": auto_execute_enabled,
        "kill_check": auto_eligible > 0 and not auto_execute_enabled,
        "kill_reason": "Eligible alerts existed but the scanner's auto_execute flag is OFF (was the bot started with mode=AUTONOMOUS?)",
    })
    stages.append({
        "stage": "bot_mode",
        "label": "Bot mode (persisted in bot_state.mode)",
        "value": bot_mode,
        "count": 1 if bot_mode.lower() == "autonomous" else 0,
        "kill_check": (auto_eligible > 0 and auto_execute_enabled
                        and bot_mode.lower() != "autonomous"),
        "kill_reason": (
            f"Bot mode is {bot_mode!r}, not AUTONOMOUS — eligible trades are queued "
            "in `_pending_trades` waiting for human confirmation"
        ),
    })

    # Cross-check: bot_state says one mode but scanner has the opposite
    # auto-execute state — the symptom of the 2026-04-30 startup-sync bug
    # (now fixed but worth flagging on historical days).
    sync_mismatch = (bot_mode.lower() == "autonomous") != auto_execute_enabled
    stages.append({
        "stage": "bot_scanner_sync",
        "label": "Bot mode ↔ scanner auto-execute consistency check",
        "value": "MISMATCH" if sync_mismatch else "OK",
        "count": 0 if sync_mismatch else 1,
        "kill_check": sync_mismatch,
        "kill_reason": (
            f"Sync drift: bot_state.mode={bot_mode!r} but scanner "
            f"_auto_execute_enabled={auto_execute_enabled}. After 2026-04-30 fix, "
            "bot.start() and set_mode() both keep these aligned. If you see this on "
            "a *current* day, check that the trading_bot service actually started "
            "(supervisor logs)."
        ),
    })

    # Collection-mode is the silent killer: when the data-fill job is
    # running, the bot scan loop fully skips every cycle. Surface it.
    try:
        from services.collection_mode import is_active as _coll_active, state as _coll_state
        coll_now = bool(_coll_active())
    except Exception:
        coll_now = False
        _coll_state = {}
    stages.append({
        "stage": "collection_mode_pause",
        "label": "Collection-mode flag (when ACTIVE, pauses ALERT INTAKE only — open positions still managed)",
        "value": "ACTIVE" if coll_now else "INACTIVE",
        "count": 0 if coll_now else 1,
        "kill_check": coll_now and total_alerts == 0,
        "kill_reason": (
            "Collection mode is currently ACTIVE — the IB historical data-fill job "
            "is running, which pauses NEW alert intake (so no fresh trades are created). "
            "Open positions continue to be managed (stops / targets / trailing all run). "
            "After 2026-04-30 fix this is safe; pre-fix the bot fully paused which "
            "left open positions unattended. Stop the data-fill via "
            "POST /api/ib/collection-mode/stop if you need fresh alerts now."
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
    scanner_hot: Dict[str, Any] = {}
    scan_phase = "unknown"
    et_clock = ""
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
            "scan_count": getattr(scanner, "_scan_count", None),
            "running": getattr(scanner, "_running", None),
        }
        # Resolve the scanner's current time-window so the 0-counters
        # don't look like a bug when the scanner is intentionally idling.
        try:
            window = scanner._get_current_time_window()  # type: ignore
            scan_phase = getattr(window, "value", str(window)).lower()
        except Exception:
            scan_phase = "unknown"
        try:
            from zoneinfo import ZoneInfo
            et_clock = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception:
            pass
    except Exception:
        scanner_hot = {}

    # Surface the scanner's "phase" prominently — it's the most common
    # source of "0 alerts and I don't know why".
    phase_explanation = {
        "closed":       "After-hours mode: scanner runs daily-chart scans every ~20min; intraday RVOL/ADV gates aren't touched, so 0 skip counters are NORMAL.",
        "premarket":    "Pre-market mode: scanner builds the morning watchlist every ~2min; intraday gates not active yet.",
        "opening":      "Market open. Intraday gates active. ADV/RVOL skip counters should be climbing.",
        "intraday":     "Regular intraday. ADV/RVOL skip counters should be climbing.",
        "morning":      "Morning session. Intraday gates active.",
        "afternoon":    "Afternoon session. Intraday gates active.",
        "lunch":        "Lunch lull. Intraday gates active but most setups are time-windowed off.",
        "power_hour":   "Power hour. Intraday gates active.",
        "unknown":      "Scanner phase couldn't be resolved — supervisor may not have started the scanner.",
    }.get(scan_phase, f"Scanner phase: {scan_phase}")

    stages.append({
        "stage": "scanner_phase",
        "label": "Current scanner time-window",
        "value": scan_phase.upper(),
        "et_clock": et_clock,
        "count": 1,
        "kill_check": False,
        "kill_reason": phase_explanation,
    })

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



# ────────────────────────────────────────────────────────────────────
#  RTH READINESS — single curl, full pre-flight checklist.
#
#  Operator workflow: run this at 23:00 ET the night before, and again
#  at 09:25 ET the morning of, to confirm every precondition for clean
#  autonomous trading is in place. If any check is RED the trade-funnel
#  validation tomorrow will be muddied by a plumbing issue, not the
#  scanner / gate logic we actually want to validate.
#
#  Read-only by design — this endpoint never mutates state. Operator
#  decides if/when to fix.
#
#  2026-04-30 v11 — operator-flagged P0 pre-flight tool.
# ────────────────────────────────────────────────────────────────────


def _check_status(passed: bool, warning: bool = False) -> str:
    """Tri-state status: GREEN (passed) | YELLOW (warn-only) | RED (failed).

    Semantics:
      passed=True,  warning=False → GREEN (clean pass)
      passed=True,  warning=True  → YELLOW (passed but degraded)
      passed=False, warning=True  → YELLOW (failed but non-blocker)
      passed=False, warning=False → RED (failed blocker)
    """
    if passed and not warning:
        return "GREEN"
    if warning:
        return "YELLOW"
    return "RED"


def _check_bot_state(db) -> Dict[str, Any]:
    """Bot persisted state: mode + running + risk_params present."""
    bs = db["bot_state"].find_one({}) or {}
    mode = str(bs.get("mode") or bs.get("bot_mode") or "").lower()
    running = bool(bs.get("running"))
    risk_present = bool(bs.get("risk_params"))
    autonomous = mode == "autonomous"
    passed = autonomous and running and risk_present
    msg = (
        "GREEN" if passed
        else f"mode={mode!r}, running={running}, risk_params_present={risk_present} — "
             "expected mode=autonomous, running=true, risk_params populated"
    )
    return {
        "name": "bot_state",
        "label": "Bot persisted state (bot_state collection)",
        "status": _check_status(passed),
        "message": msg,
        "details": {
            "mode": mode,
            "running": running,
            "risk_params_present": risk_present,
        },
    }


def _check_bot_runtime(db) -> Dict[str, Any]:
    """In-process bot service: _running flag matches persisted state."""
    try:
        from services.trading_bot_service import get_trading_bot_service
        bot = get_trading_bot_service()
        runtime_running = bool(getattr(bot, "_running", False))
        runtime_mode = getattr(getattr(bot, "_mode", None), "value", "unknown")
    except Exception as e:
        return {
            "name": "bot_runtime",
            "label": "Bot service runtime state (in-process)",
            "status": "RED",
            "message": f"could not read bot service: {e}",
            "details": {},
        }

    bs = db["bot_state"].find_one({}) or {}
    persisted_running = bool(bs.get("running"))
    persisted_mode = str(bs.get("mode") or "").lower()

    in_sync = (
        runtime_running == persisted_running
        and str(runtime_mode).lower() == persisted_mode
    )
    autonomous_and_running = runtime_running and str(runtime_mode).lower() == "autonomous"
    passed = in_sync and autonomous_and_running
    msg = (
        "GREEN" if passed
        else f"runtime: running={runtime_running} mode={runtime_mode} | "
             f"persisted: running={persisted_running} mode={persisted_mode}"
    )
    return {
        "name": "bot_runtime",
        "label": "Bot service runtime state (in-process)",
        "status": _check_status(passed),
        "message": msg,
        "details": {
            "runtime_running": runtime_running,
            "runtime_mode": runtime_mode,
            "persisted_running": persisted_running,
            "persisted_mode": persisted_mode,
            "in_sync": in_sync,
        },
    }


def _check_scanner_runtime(db) -> Dict[str, Any]:
    """Scanner: running + auto_execute_enabled synced with bot mode."""
    try:
        from services.enhanced_scanner import get_enhanced_scanner
        scanner = get_enhanced_scanner()
        running = bool(getattr(scanner, "_running", False))
        auto_execute = bool(getattr(scanner, "_auto_execute_enabled", False))
        scan_count = int(getattr(scanner, "_scan_count", 0))
    except Exception as e:
        return {
            "name": "scanner_runtime",
            "label": "Enhanced scanner runtime state",
            "status": "RED",
            "message": f"could not read scanner service: {e}",
            "details": {},
        }

    bs = db["bot_state"].find_one({}) or {}
    bot_mode = str(bs.get("mode") or "").lower()
    expected_auto = bot_mode == "autonomous"
    sync_drift = expected_auto != auto_execute
    passed = running and auto_execute and not sync_drift
    msg = (
        "GREEN" if passed
        else f"running={running} auto_execute={auto_execute} expected_auto={expected_auto} "
             f"sync_drift={sync_drift}"
    )
    return {
        "name": "scanner_runtime",
        "label": "Enhanced scanner runtime state",
        "status": _check_status(passed),
        "message": msg,
        "details": {
            "running": running,
            "auto_execute_enabled": auto_execute,
            "scan_count": scan_count,
            "bot_mode_persisted": bot_mode,
            "sync_drift": sync_drift,
        },
    }


def _check_collection_mode() -> Dict[str, Any]:
    """Collection mode should be INACTIVE before market open. If active,
    NEW alert intake is paused (positions still managed)."""
    try:
        from services.collection_mode import is_active, state
        active = bool(is_active())
        started_at = state.get("started_at")
        instances = int(state.get("instances", 0))
    except Exception as e:
        return {
            "name": "collection_mode",
            "label": "IB historical-data fill mode (alert-intake pause)",
            "status": "RED",
            "message": f"could not read collection_mode: {e}",
            "details": {},
        }
    passed = not active
    msg = "INACTIVE — fresh alert intake is enabled" if passed else (
        f"ACTIVE since {started_at} ({instances} instances) — NEW alerts paused. "
        "Stop with POST /api/ib/collection-mode/stop"
    )
    return {
        "name": "collection_mode",
        "label": "IB historical-data fill mode (alert-intake pause)",
        "status": _check_status(passed),
        "message": msg,
        "details": {
            "active": active,
            "started_at": started_at,
            "instances": instances,
        },
    }


def _check_pusher_health() -> Dict[str, Any]:
    """IB pusher (Windows-side) reachable + reporting IB Gateway connected."""
    try:
        from services.ib_pusher_rpc import get_pusher_rpc_client
        rpc = get_pusher_rpc_client()
        health = rpc.health()
    except Exception as e:
        return {
            "name": "pusher_health",
            "label": "IB pusher reachable + IB Gateway connected",
            "status": "RED",
            "message": f"pusher RPC import failed: {e}",
            "details": {},
        }
    if health is None:
        return {
            "name": "pusher_health",
            "label": "IB pusher reachable + IB Gateway connected",
            "status": "RED",
            "message": "pusher unreachable — Windows PC offline or IB_PUSHER_RPC_URL wrong",
            "details": {},
        }
    ib_connected = bool(
        health.get("ib_connected")
        or health.get("connected")
        or health.get("ib_gateway_connected")
    )
    passed = ib_connected
    msg = (
        "GREEN — pusher reachable, IB Gateway connected" if passed
        else f"pusher reachable but IB Gateway NOT connected: {health}"
    )
    return {
        "name": "pusher_health",
        "label": "IB pusher reachable + IB Gateway connected",
        "status": _check_status(passed),
        "message": msg,
        "details": health,
    }


def _check_universe_freshness(db) -> Dict[str, Any]:
    """`symbol_adv_cache` populated and refreshed within 48h."""
    cache_count = db["symbol_adv_cache"].count_documents({})
    if cache_count == 0:
        return {
            "name": "universe_freshness",
            "label": "Symbol universe (symbol_adv_cache) freshness",
            "status": "RED",
            "message": "symbol_adv_cache is empty — RVOL / ADV gates can't fire",
            "details": {"count": 0},
        }
    # Try multiple known timestamp fields used by different writers.
    latest = None
    for field in ("updated_at", "last_refresh_at", "cached_at"):
        doc = db["symbol_adv_cache"].find_one(
            {field: {"$exists": True}},
            {"_id": 0, field: 1},
            sort=[(field, -1)],
        )
        if doc and doc.get(field):
            latest = doc[field]
            break
    age_hours = None
    if latest:
        try:
            from datetime import datetime as _dt
            ts = (
                latest if isinstance(latest, datetime)
                else _dt.fromisoformat(str(latest).replace("Z", "+00:00"))
            )
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - ts
            age_hours = round(age.total_seconds() / 3600, 1)
        except Exception:
            pass
    fresh = age_hours is not None and age_hours <= 48
    stale_warn = age_hours is not None and 24 < age_hours <= 48
    if fresh and stale_warn:
        return {
            "name": "universe_freshness",
            "label": "Symbol universe (symbol_adv_cache) freshness",
            "status": "YELLOW",
            "message": f"YELLOW — last refresh {age_hours}h ago (24-48h window, refresh recommended)",
            "details": {"count": cache_count, "age_hours": age_hours},
        }
    passed = fresh
    msg = (
        f"GREEN — {cache_count} symbols, last refresh {age_hours}h ago" if passed
        else f"stale — {cache_count} symbols, last refresh "
             f"{'unknown' if age_hours is None else f'{age_hours}h'} ago "
             "(>48h or no timestamp)"
    )
    return {
        "name": "universe_freshness",
        "label": "Symbol universe (symbol_adv_cache) freshness",
        "status": _check_status(passed),
        "message": msg,
        "details": {"count": cache_count, "age_hours": age_hours},
    }


def _check_data_request_queue(db) -> Dict[str, Any]:
    """historical_data_requests queue depth — high backlog = data fill
    will likely be running into market open."""
    try:
        col = db["historical_data_requests"]
        pending = col.count_documents({"status": {"$in": ["pending", "queued"]}})
        in_flight = col.count_documents({"status": {"$in": ["in_progress", "running"]}})
    except Exception as e:
        return {
            "name": "data_request_queue",
            "label": "IB historical-data backfill queue depth",
            "status": "YELLOW",
            "message": f"could not read queue: {e}",
            "details": {},
        }
    total = pending + in_flight
    passed = total < 200
    warn = 50 <= total < 200
    msg = (
        f"GREEN — {pending} pending + {in_flight} in-flight" if passed and not warn
        else f"YELLOW — {total} jobs in queue (will keep collection_mode active)" if warn
        else f"RED — {total} jobs in queue, risks running into market open"
    )
    return {
        "name": "data_request_queue",
        "label": "IB historical-data backfill queue depth",
        "status": _check_status(passed, warning=warn),
        "message": msg,
        "details": {"pending": pending, "in_flight": in_flight, "total": total},
    }


def _check_landscape_prewarm() -> Dict[str, Any]:
    """SetupLandscapeService cache is hot — confirms the after-hours
    pre-warm fired AND the morning briefing won't pay full classify
    latency."""
    try:
        from services.setup_landscape_service import get_setup_landscape_service
        svc = get_setup_landscape_service()
        snap = getattr(svc, "_snapshot", None)
        snap_at = getattr(svc, "_snapshot_at", None)
    except Exception as e:
        return {
            "name": "landscape_prewarm",
            "label": "Setup landscape pre-warm (morning briefing latency hedge)",
            "status": "YELLOW",
            "message": f"could not read landscape service: {e}",
            "details": {},
        }
    if snap is None or snap_at is None:
        return {
            "name": "landscape_prewarm",
            "label": "Setup landscape pre-warm (morning briefing latency hedge)",
            "status": "YELLOW",
            "message": "no snapshot cached yet — first briefing will pay 200×classify latency",
            "details": {"cached": False},
        }
    age_seconds = (datetime.now(timezone.utc) - snap_at).total_seconds()
    fresh = age_seconds <= 30 * 60
    passed = fresh
    msg = (
        f"GREEN — snapshot cached, {int(age_seconds)}s old" if passed
        else f"YELLOW — snapshot is {int(age_seconds // 60)}min old, "
             "next sweep should refresh it"
    )
    classified = getattr(snap, "classified", None)
    sample_size = getattr(snap, "sample_size", None)
    return {
        "name": "landscape_prewarm",
        "label": "Setup landscape pre-warm (morning briefing latency hedge)",
        "status": _check_status(passed, warning=not fresh),
        "message": msg,
        "details": {
            "cached": True,
            "age_seconds": int(age_seconds),
            "classified": classified,
            "sample_size": sample_size,
        },
    }


def _check_briefing_predictions(db) -> Dict[str, Any]:
    """`landscape_predictions` collection should have today's morning
    prediction for EOD grading. YELLOW if today's row hasn't been
    written yet — the briefing endpoint will write it on first call."""
    from datetime import datetime as _dt
    try:
        from zoneinfo import ZoneInfo
        today_et = _dt.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    except Exception:
        today_et = _dt.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        count_today = db["landscape_predictions"].count_documents({
            "trading_day": today_et,
            "context": "morning",
        })
    except Exception as e:
        return {
            "name": "briefing_predictions",
            "label": "Today's morning briefing prediction (EOD grading)",
            "status": "YELLOW",
            "message": f"could not read landscape_predictions: {e}",
            "details": {"trading_day_et": today_et},
        }
    passed = count_today >= 1
    msg = (
        f"GREEN — today's morning prediction recorded ({count_today} rows)" if passed
        else "YELLOW — no morning prediction for today yet. Will be written when "
             "/api/assistant/coach/morning-briefing is first called."
    )
    return {
        "name": "briefing_predictions",
        "label": "Today's morning briefing prediction (EOD grading)",
        "status": _check_status(passed, warning=not passed),
        "message": msg,
        "details": {"trading_day_et": today_et, "count": count_today},
    }


@router.get("/rth-readiness")
def rth_readiness() -> Dict[str, Any]:
    """Pre-flight checklist — single curl returns every precondition
    for clean autonomous trading. Read-only.

    Status semantics:
      • GREEN  — check passed, no action needed.
      • YELLOW — non-blocker; trades will still flow but something is
                 sub-optimal (stale data, cache cold, etc).
      • RED    — blocker; trades won't execute or won't be diagnosable
                 until this is fixed.

    Top-level ``ready_for_rth`` is True only when EVERY check is
    GREEN or YELLOW — any RED forces False.
    """
    db = _get_db()
    checks: List[Dict[str, Any]] = []

    # Order matters — most fundamental first so a RED at the top tells
    # the operator the simplest fix.
    for fn, args in (
        (_check_bot_state,            (db,)),
        (_check_bot_runtime,          (db,)),
        (_check_scanner_runtime,      (db,)),
        (_check_collection_mode,      ()),
        (_check_pusher_health,        ()),
        (_check_universe_freshness,   (db,)),
        (_check_data_request_queue,   (db,)),
        (_check_landscape_prewarm,    ()),
        (_check_briefing_predictions, (db,)),
    ):
        try:
            checks.append(fn(*args))
        except Exception as e:
            # Belt-and-braces — a single check raising shouldn't kill the endpoint.
            checks.append({
                "name": getattr(fn, "__name__", "check").replace("_check_", ""),
                "label": "Check raised",
                "status": "RED",
                "message": f"check raised {type(e).__name__}: {e}",
                "details": {},
            })

    green = sum(1 for c in checks if c["status"] == "GREEN")
    yellow = sum(1 for c in checks if c["status"] == "YELLOW")
    red = sum(1 for c in checks if c["status"] == "RED")
    overall = "GREEN" if red == 0 and yellow == 0 else "YELLOW" if red == 0 else "RED"
    ready = red == 0
    first_red = next((c for c in checks if c["status"] == "RED"), None)

    # ET clock so the operator knows what trading day this represents.
    try:
        from zoneinfo import ZoneInfo
        et_now = datetime.now(ZoneInfo("America/New_York"))
        et_clock = et_now.strftime("%Y-%m-%d %H:%M:%S %Z")
        trading_day_et = et_now.strftime("%Y-%m-%d")
    except Exception:
        et_clock = datetime.now(timezone.utc).isoformat()
        trading_day_et = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    return {
        "success": True,
        "overall_status": overall,
        "ready_for_rth": ready,
        "summary": {
            "green":  green,
            "yellow": yellow,
            "red":    red,
            "total":  len(checks),
        },
        "first_red_check": first_red["name"] if first_red else None,
        "first_red_message": first_red["message"] if first_red else None,
        "checks": checks,
        "trading_day_et": trading_day_et,
        "et_clock": et_clock,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }



# ===========================================================================
# /api/diagnostic/trade-drops — silent execution-drop forensics
# ===========================================================================
#
# Companion to `/trade-funnel`. The funnel walks the alert→bot→broker chain
# top-down to pinpoint *which stage* dropped flow. This endpoint walks the
# tail-end of that chain (the post-AI-gate execution path) bottom-up: every
# `return None` / `return` between the AI gate and `bot_trades.insert_one()`
# now records a row via `services.trade_drop_recorder`. Hitting this endpoint
# tells the operator which gate is killing trades in real time without
# grepping logs.
#
# Gates currently instrumented (from KNOWN_GATES in trade_drop_recorder.py):
#   account_guard           — IB_ACCOUNT_ACTIVE vs pusher account drift
#   safety_guardrail        — SafetyGuardrails.check_can_enter rejected
#   safety_guardrail_crash  — exception in the guardrail check itself
#   no_trade_executor       — bot._trade_executor is None
#   pre_exec_guardrail_veto — execution_guardrails.run_all_guardrails veto
#   strategy_paper_phase    — strategy still in PAPER (does save to bot_trades)
#   strategy_simulation_phase — strategy in SIMULATION (does save)
#   broker_rejected         — place_bracket_order/execute_entry returned error
#   execution_exception     — raised exception inside execute_trade
# ===========================================================================
@router.get("/trade-drops")
def trade_drops(
    minutes: int = 60,
    gate: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """Aggregate recent silent execution drops by gate.

    Args:
        minutes: lookback window (1 ≤ minutes ≤ 1440). Defaults to 60.
        gate: optional gate filter (e.g. ``account_guard``).
        limit: max rows returned in the ``recent`` list (1-500).

    Returns shape::

        {
          "success": True,
          "minutes": 60,
          "total": 47,
          "by_gate": {"account_guard": 32, "safety_guardrail": 15},
          "first_killing_gate": "account_guard",
          "recent": [
              {
                "ts": "2026-04-30T18:42:01.123456+00:00",
                "ts_epoch_ms": 1730351321123,
                "gate": "account_guard",
                "symbol": "AAPL",
                "setup_type": "9_ema_scalp",
                "direction": "long",
                "reason": "account drift: expected … got DUM61566S",
                "context": {...}
              },
              ...
          ]
        }
    """
    from services.trade_drop_recorder import (
        get_recent_drops,
        summarize_recent_drops,
        KNOWN_GATES,
    )

    try:
        minutes_clamped = max(1, min(int(minutes), 24 * 60))
    except Exception:
        raise HTTPException(status_code=400, detail="minutes must be an int")
    try:
        limit_clamped = max(1, min(int(limit), 500))
    except Exception:
        raise HTTPException(status_code=400, detail="limit must be an int")

    if gate and gate not in KNOWN_GATES:
        # Soft warning, not a 400 — the recorder accepts unknown gates
        # for forward-compat, so the endpoint should surface them too.
        logger.debug(f"[trade-drops] unknown gate filter '{gate}' — returning anyway")

    db = _get_db()
    summary = summarize_recent_drops(db, minutes=minutes_clamped)
    if gate:
        # Re-read with the filter so `recent` matches the gate the caller asked for.
        summary["recent"] = get_recent_drops(
            db, minutes=minutes_clamped, gate=gate, limit=limit_clamped,
        )
        summary["total"] = len(summary["recent"])
        summary["by_gate"] = {gate: summary["total"]} if summary["total"] else {}
        summary["first_killing_gate"] = gate if summary["total"] else None
    else:
        summary["recent"] = summary["recent"][:limit_clamped]

    return {
        "success": True,
        "known_gates": sorted(KNOWN_GATES),
        **summary,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }



# ===========================================================================
# /api/diagnostic/account-snapshot — why is EQUITY showing $-?
# ===========================================================================
@router.get("/account-snapshot")
async def account_snapshot() -> Dict[str, Any]:
    """Walk the equity-resolution chain and return what each layer sees.

    Operator flagged 2026-04-30 v15: V5 HUD shows EQUITY=$- despite the
    pusher being LIVE. This endpoint dumps every input to the equity
    resolution chain so the operator can pinpoint which layer is empty
    without log-grepping. Layers walked (same order as
    /api/trading-bot/status):
      1. _trade_executor.get_account_info()  (Alpaca / simulated only)
      2. _pushed_ib_data["account"]           (IB pusher push-loop)
      3. get_account_snapshot()               (IB pusher RPC fallback)
      4. _extract_account_value() per key
      5. Resolved account dict (same shape `/status` would surface)
    """
    layers: Dict[str, Any] = {
        "executor_info": None,
        "pushed_ib_data_account": None,
        "rpc_account_snapshot": None,
        "extracted_values": None,
        "is_pusher_connected": None,
        "resolved_account": None,
    }
    errors: Dict[str, str] = {}

    # 1. executor info (Alpaca / simulated only)
    try:
        from routers.trading_bot import _trade_executor
        if _trade_executor is not None:
            try:
                info = await _trade_executor.get_account_info()
                layers["executor_info"] = info if isinstance(info, dict) else None
            except Exception as e:
                errors["executor_info"] = f"{type(e).__name__}: {e}"
    except Exception as e:
        errors["executor_info_import"] = f"{type(e).__name__}: {e}"

    # 2. pushed_ib_data
    try:
        from routers.ib import _pushed_ib_data, _extract_account_value, is_pusher_connected
        layers["is_pusher_connected"] = bool(is_pusher_connected())
        ib_account = (_pushed_ib_data or {}).get("account") or {}
        layers["pushed_ib_data_account"] = {
            "keys": sorted(ib_account.keys()) if isinstance(ib_account, dict) else "<not dict>",
            "value_count": len(ib_account) if isinstance(ib_account, dict) else 0,
            "sample": {
                k: (str(v)[:80] if not isinstance(v, (int, float, bool, type(None))) else v)
                for k, v in list(ib_account.items())[:30]
            } if isinstance(ib_account, dict) else None,
        }

        # 3. RPC fallback
        try:
            from services.ib_pusher_rpc import get_account_snapshot
            # v19.30.8 (2026-05-02 evening): wrap in asyncio.to_thread.
            # Diagnostic endpoint is rarely called but must not wedge
            # the loop when an operator hits the diagnostic page during
            # a busy moment.
            snap = await asyncio.to_thread(get_account_snapshot) or {}
            layers["rpc_account_snapshot"] = {
                "success": bool(snap.get("success")),
                "has_account": bool(snap.get("account")),
                "account_keys": sorted((snap.get("account") or {}).keys()),
                "error": snap.get("error"),
            }
            if not ib_account and snap.get("account"):
                ib_account = snap["account"]
        except Exception as e:
            errors["rpc_snapshot"] = f"{type(e).__name__}: {e}"

        # 4. _extract_account_value for standard keys
        if isinstance(ib_account, dict) and ib_account:
            extracted: Dict[str, Any] = {}
            for key in ("NetLiquidation", "BuyingPower", "TotalCashBalance",
                        "AvailableFunds", "UnrealizedPnL", "RealizedPnL",
                        "GrossPositionValue", "EquityWithLoanValue"):
                try:
                    extracted[key] = _extract_account_value(ib_account, key, None)
                except Exception as e:
                    extracted[key] = f"<error: {type(e).__name__}>"
            layers["extracted_values"] = extracted

            # 5. Resolved account (mirror what /status would set)
            net_liq = _extract_account_value(ib_account, "NetLiquidation", 0)
            buying_power = _extract_account_value(ib_account, "BuyingPower", 0)
            cash = _extract_account_value(ib_account, "TotalCashBalance", 0)
            available_funds = _extract_account_value(
                ib_account, "AvailableFunds", buying_power
            )
            if net_liq and net_liq > 0:
                layers["resolved_account"] = {
                    "equity": float(net_liq),
                    "buying_power": float(buying_power),
                    "cash": float(cash),
                    "available_funds": float(available_funds),
                    "source": "ib_pushed",
                }
            else:
                layers["resolved_account"] = {
                    "equity": None,
                    "reason": "NetLiquidation is 0 or missing — paper account "
                              "may be fresh, or pusher hasn't received the "
                              "first accountSummary tick yet.",
                }
    except Exception as e:
        errors["pushed_ib_data"] = f"{type(e).__name__}: {e}"

    # Operator-friendly verdict
    verdict = "unknown"
    hint = None
    resolved = layers.get("resolved_account") or {}
    if resolved.get("equity"):
        verdict = "ok"
        hint = "Equity should render correctly on the V5 HUD."
    elif not layers.get("is_pusher_connected"):
        verdict = "pusher_disconnected"
        hint = "IB pusher is not connected — start IB Gateway + the pusher process on the Windows PC."
    elif layers.get("pushed_ib_data_account") and \
            layers["pushed_ib_data_account"].get("value_count", 0) == 0:
        verdict = "pushed_account_empty"
        hint = ("Pusher is connected but the push-loop has not received an "
                "accountSummary tick yet. Wait 5-10s and retry, or hit "
                "POST /api/trading-bot/refresh-account.")
    elif resolved.get("reason"):
        verdict = "net_liq_zero"
        hint = resolved["reason"]

    return {
        "success": True,
        "verdict": verdict,
        "hint": hint,
        "layers": layers,
        "errors": errors,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ===========================================================================
# /api/diagnostic/scanner-coverage — why is RS-laggard dominating scans?
# ===========================================================================
@router.get("/scan-cycle-stats")
def scan_cycle_stats() -> Dict[str, Any]:
    """Per-cycle scan coverage health — answers "are we really scanning
    the full universe or stuck on the same 325 symbols every cycle?"

    Returns:
      • Wave-rotation state: current wave, total waves, wave_size, ETA to
        full-universe coverage
      • Last-cycle count (`symbols_scanned_last`)
      • Lifetime-unique-symbols-since-restart (proves rotation is visiting
        new symbols, not looping the same set)
      • Tier breakdown of the canonical universe
      • Per-tier minimum ADV thresholds (so operator can debug why a
        symbol they expect is "tier:investment" not "tier:intraday")

    v19.34.131: shipped after operator reported HUD showing only 325
    symbols scanned. Hypothesis: working as designed (T1+T2+T3 wave =
    ~325/cycle, universe rotated over 12-15 cycles), but no way to
    prove rotation health pre-v131.
    """
    out: Dict[str, Any] = {"success": True, "ts": datetime.now(timezone.utc).isoformat()}

    # 1) Enhanced scanner live state
    try:
        from services.enhanced_scanner import get_enhanced_scanner
        sc = get_enhanced_scanner()
        lifetime = getattr(sc, "_scanned_symbols_lifetime", set()) or set()
        started_at = getattr(sc, "_scanned_symbols_session_started", None)
        out["enhanced_scanner"] = {
            "scan_count": int(getattr(sc, "_scan_count", 0) or 0),
            "running": bool(getattr(sc, "_running", False)),
            "symbols_scanned_last_cycle": int(getattr(sc, "_symbols_scanned_last", 0) or 0),
            "symbols_skipped_adv": int(getattr(sc, "_symbols_skipped_adv", 0) or 0),
            "symbols_skipped_rvol": int(getattr(sc, "_symbols_skipped_rvol", 0) or 0),
            "lifetime_unique_symbols_scanned": len(lifetime),
            "lifetime_tracking_started_at": (
                started_at.isoformat() if started_at else None
            ),
            "scan_interval_seconds": float(getattr(sc, "_scan_interval", 0) or 0),
            "swing_scan_frequency": int(getattr(sc, "_swing_scan_frequency", 0) or 0),
            "tier_thresholds": {
                "intraday_min_adv":   int(getattr(sc, "_min_adv_intraday", 0) or 0),
                "swing_min_adv":      int(getattr(sc, "_min_adv_general", 0) or 0),
                "investment_min_adv": int(getattr(sc, "_min_adv_investment", 0) or 0),
            },
            "adv_cache_size": len(getattr(sc, "_adv_cache", {}) or {}),
            "known_liquid_symbols_count": len(getattr(sc, "_known_liquid_symbols", set()) or set()),
            "tier_cache_counts": _count_tier_cache(getattr(sc, "_tier_cache", {})),
        }
    except Exception as e:
        out["enhanced_scanner_error"] = f"{type(e).__name__}: {e}"

    # 2) Wave scanner state (rotation health)
    try:
        from services.wave_scanner import get_wave_scanner
        ws = get_wave_scanner()
        stats = ws.get_stats()
        config = ws.get_scan_config()
        tier3_total = stats.get("tier3_roster_size", 0) or 0
        wave_size = config.get("wave_size", 200) or 200
        current_wave = stats.get("current_wave", 0) or 0
        total_waves = max(1, (tier3_total + wave_size - 1) // wave_size)
        scan_interval = float(
            (out.get("enhanced_scanner") or {}).get("scan_interval_seconds")
            or 15.0
        )
        # ETA to next-completion (waves remaining × scan_interval).
        waves_remaining = (total_waves - current_wave) % total_waves
        if waves_remaining == 0 and current_wave != 0:
            eta_seconds = total_waves * scan_interval
        else:
            eta_seconds = max(0, waves_remaining) * scan_interval
        out["wave_scanner"] = {
            "wave_size": wave_size,
            "tier2_pool_size": stats.get("tier2_pool_size", 0),
            "tier3_roster_size": tier3_total,
            "current_wave": current_wave,
            "total_waves": total_waves,
            "wave_progress_pct": round(current_wave / total_waves * 100, 1) if total_waves else 0,
            "tier3_scanned_so_far": min((current_wave + 1) * wave_size, tier3_total),
            "scan_interval_seconds": scan_interval,
            "full_coverage_eta_seconds": eta_seconds,
            "last_full_scan_complete_at": stats.get("last_full_scan"),
            "watchlist_count": stats.get("watchlist_count", 0),
        }
    except Exception as e:
        out["wave_scanner_error"] = f"{type(e).__name__}: {e}"

    # 3) Universe size from DB (ground truth)
    try:
        db = _get_db()
        if db is not None:
            t = out.get("enhanced_scanner", {}).get("tier_thresholds", {})
            intraday_min = t.get("intraday_min_adv", 50_000_000)
            swing_min    = t.get("swing_min_adv",    10_000_000)
            invest_min   = t.get("investment_min_adv", 2_000_000)
            cnt_intraday = db["symbol_adv_cache"].count_documents({
                "avg_dollar_volume": {"$gte": intraday_min},
                "unqualifiable": {"$ne": True},
            })
            cnt_swing = db["symbol_adv_cache"].count_documents({
                "avg_dollar_volume": {"$gte": swing_min},
                "unqualifiable": {"$ne": True},
            })
            cnt_invest = db["symbol_adv_cache"].count_documents({
                "avg_dollar_volume": {"$gte": invest_min},
                "unqualifiable": {"$ne": True},
            })
            cnt_total = db["symbol_adv_cache"].count_documents({})
            out["universe"] = {
                "intraday_tier_count":   cnt_intraday,
                "swing_tier_count":      cnt_swing - cnt_intraday,
                "investment_tier_count": cnt_invest - cnt_swing,
                "qualified_total":       cnt_invest,
                "all_in_cache_total":    cnt_total,
                "below_min_count":       cnt_total - cnt_invest,
            }
    except Exception as e:
        out["universe_error"] = f"{type(e).__name__}: {e}"

    # 4) Health verdict
    enh = out.get("enhanced_scanner", {}) or {}
    ws = out.get("wave_scanner", {}) or {}
    uni = out.get("universe", {}) or {}
    last = enh.get("symbols_scanned_last_cycle", 0) or 0
    lifetime = enh.get("lifetime_unique_symbols_scanned", 0) or 0
    qualified = uni.get("qualified_total", 0) or 0
    current_wave = ws.get("current_wave", 0) or 0
    total_waves = ws.get("total_waves", 1) or 1

    verdict = "unknown"
    hint = None
    if last <= 0:
        verdict = "scanner_idle_or_stale"
        hint = "Scanner reported 0 in its last cycle. Bot may be paused or pre-RTH."
    elif total_waves > 1 and current_wave == 0 and enh.get("scan_count", 0) > total_waves:
        verdict = "wave_rotation_stuck"
        hint = (
            f"Scan count is {enh.get('scan_count')} but wave is still at 0/{total_waves}. "
            f"Tier 3 isn't advancing — rotation broken."
        )
    elif qualified > 0 and lifetime < qualified * 0.5 and enh.get("scan_count", 0) > total_waves * 1.5:
        verdict = "coverage_lag"
        hint = (
            f"Scanned {lifetime} unique symbols since restart but universe has "
            f"{qualified} qualified. Expected ~{qualified} after "
            f"{total_waves * ws.get('scan_interval_seconds', 15):.0f}s. "
            f"Possible cause: ADV cache misses (fail-closed)."
        )
    elif qualified > 0 and lifetime >= qualified * 0.9:
        verdict = "healthy"
        hint = (
            f"Rotation healthy — {lifetime}/{qualified} unique symbols visited. "
            f"Per-cycle count of {last} is the wave_size + tier1/2 (working as designed)."
        )
    else:
        verdict = "warming_up"
        hint = (
            f"Scanner is in mid-rotation: {lifetime}/{qualified} unique symbols visited, "
            f"wave {current_wave}/{total_waves}. Re-run in "
            f"{ws.get('full_coverage_eta_seconds', 0):.0f}s for full picture."
        )
    out["verdict"] = verdict
    out["hint"] = hint
    return out


def _count_tier_cache(tier_cache: Dict[str, str]) -> Dict[str, int]:
    """Bucket _tier_cache by classification for the diagnostic response."""
    counts = {"intraday": 0, "swing": 0, "investment": 0}
    for tier in (tier_cache or {}).values():
        if tier in counts:
            counts[tier] += 1
    return counts


@router.get("/realized-pnl-audit")
def realized_pnl_audit(
    date: Optional[str] = None,
    paper_filter: bool = True,
):
    """Forensic audit of today's realized PnL — explains discrepancies
    between our app's "Realized" number and IB TWS's actual realized.

    Returns:
      • Per-trade row dump (every closed trade today)
      • Breakdown by `exit_reason` / `close_reason` path → see which
        path is contributing how much
      • Duplicate-close detection (same symbol + same fill cluster
        appearing twice — the #1 cause of inflated realized losses)
      • Paper-mode contamination check
      • Total summed (gross) vs total summed (excluding suspect rows)

    v19.34.133: shipped after operator reported TWS realized=$-674
    but our app shows $-4,250. Difference of $3,576 = the bleed.
    """
    from datetime import datetime as _dt, timedelta as _td
    from collections import defaultdict

    db = _get_db()
    if not date:
        date = _dt.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        day_start = _dt.fromisoformat(f"{date}T00:00:00").replace(tzinfo=timezone.utc)
    except ValueError:
        return {"success": False, "error": f"invalid date: {date}"}
    day_end = day_start + _td(days=1)
    # Mongo stores closed_at as ISO string most of the time. Match both
    # string and datetime ranges to be safe.
    day_start_iso = day_start.isoformat()
    day_end_iso = day_end.isoformat()

    # 1) Pull every closed trade in window
    q = {
        "$and": [
            {"status": {"$in": ["closed", "CLOSED"]}},
            {"$or": [
                {"closed_at": {"$gte": day_start, "$lt": day_end}},
                {"closed_at": {"$gte": day_start_iso, "$lt": day_end_iso}},
                {"exit_time": {"$gte": day_start, "$lt": day_end}},
                {"exit_time": {"$gte": day_start_iso, "$lt": day_end_iso}},
            ]},
        ],
    }
    rows = list(db["bot_trades"].find(q, {"_id": 0}).limit(2000))

    # 2) Helper to read either ISO string or datetime as ISO string
    def _iso(v):
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v) if v else ""

    # 3) Per-trade summary projection
    def _row(r):
        return {
            "trade_id": r.get("id") or r.get("trade_id"),
            "symbol": r.get("symbol"),
            "direction": r.get("direction"),
            "shares": r.get("shares"),
            "fill_price": r.get("fill_price"),
            "exit_price": r.get("exit_price"),
            "realized_pnl": r.get("realized_pnl"),
            "net_pnl": r.get("net_pnl"),
            "total_commissions": r.get("total_commissions"),
            "exit_reason": r.get("exit_reason") or r.get("close_reason") or "",
            "close_reason": r.get("close_reason") or "",
            "entered_by": r.get("entered_by") or "",
            "setup_type": r.get("setup_type") or "",
            "executor_mode": r.get("executor_mode")
                or r.get("execution_mode")
                or r.get("mode"),
            "is_paper": bool(
                r.get("is_paper")
                or "PAPER" in str(r.get("executor_mode", "")).upper()
                or "SIM" in str(r.get("execution_mode", "")).upper()
            ),
            "fill_time": _iso(r.get("fill_time") or r.get("entry_time")),
            "closed_at": _iso(r.get("closed_at") or r.get("exit_time")),
            "exit_price_source": r.get("exit_price_source"),
        }
    projected = [_row(r) for r in rows]

    # 4) Filter paper-mode rows (TWS doesn't count paper trades)
    live_only = [r for r in projected if not r["is_paper"]] if paper_filter else projected
    paper_dropped = len(projected) - len(live_only)

    # 5) Breakdown by exit_reason
    by_reason: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "realized_sum": 0.0, "net_sum": 0.0, "symbols": []}
    )
    for r in live_only:
        key = r["exit_reason"] or r["close_reason"] or "<no_reason>"
        b = by_reason[key]
        b["count"] += 1
        b["realized_sum"] += float(r["realized_pnl"] or 0)
        b["net_sum"] += float(r["net_pnl"] or 0)
        if len(b["symbols"]) < 8:
            b["symbols"].append(r["symbol"])

    breakdown_sorted = sorted(
        [{"exit_reason": k, **v} for k, v in by_reason.items()],
        key=lambda x: x["realized_sum"],
    )

    # 6) Duplicate-close detection — group by symbol + fill_time
    by_fill: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for r in live_only:
        if r["symbol"] and r["fill_time"]:
            by_fill[(r["symbol"], r["fill_time"])].append(r)
    duplicate_groups = []
    duplicate_pnl_impact = 0.0
    for (sym, ft), group in by_fill.items():
        if len(group) > 1:
            # Keep first row as canonical, others are suspected dupes
            dupe_realized_sum = sum(float(r["realized_pnl"] or 0) for r in group[1:])
            dupe_net_sum = sum(float(r["net_pnl"] or 0) for r in group[1:])
            duplicate_pnl_impact += dupe_net_sum or dupe_realized_sum
            duplicate_groups.append({
                "symbol": sym,
                "fill_time": ft,
                "row_count": len(group),
                "trade_ids": [r["trade_id"] for r in group],
                "realized_pnls": [r["realized_pnl"] for r in group],
                "net_pnls": [r["net_pnl"] for r in group],
                "exit_reasons": [r["exit_reason"] for r in group],
                "suspected_dupe_pnl": dupe_net_sum or dupe_realized_sum,
            })

    # 7) Suspicious close reasons that look like fake-PnL writers
    SUSPICIOUS = {
        "consolidated_v19_34_42", "consolidated", "reconciled_excess",
        "reconciled_excess_v19_34_15b", "phantom_close",
        "naked_sweep_reissue", "bracket_reissue",
        # cancellation / boot-time sweeps that should NEVER carry PnL
        "boot_zombie_sweep", "boot_zombie_sweep_summary",
    }
    suspicious_rows = []
    suspicious_realized_sum = 0.0
    for r in live_only:
        reason = (r["exit_reason"] or "") + "|" + (r["close_reason"] or "")
        if any(s in reason for s in SUSPICIOUS):
            pnl = float(r["net_pnl"] or r["realized_pnl"] or 0)
            if abs(pnl) > 0.01:
                suspicious_rows.append({**r, "_suspect_amount": pnl})
                suspicious_realized_sum += pnl

    # 8) Totals
    gross_realized = sum(float(r["realized_pnl"] or 0) for r in live_only)
    gross_net = sum(float(r["net_pnl"] or 0) for r in live_only)
    clean_net = gross_net - duplicate_pnl_impact - suspicious_realized_sum

    # 9) Verdict
    verdict = "clean"
    hints = []
    if duplicate_groups:
        verdict = "duplicate_closes"
        hints.append(
            f"{len(duplicate_groups)} symbol+fill-time pair(s) closed >1 times. "
            f"Suspected duplicate PnL impact: ${duplicate_pnl_impact:.2f}"
        )
    if suspicious_rows:
        if verdict == "clean":
            verdict = "suspicious_close_paths"
        hints.append(
            f"{len(suspicious_rows)} row(s) with PnL written from suspicious close "
            f"reasons (consolidator/phantom/reconciler/boot-sweep). "
            f"Suspect PnL: ${suspicious_realized_sum:.2f}"
        )
    if paper_dropped > 0:
        hints.append(
            f"{paper_dropped} paper-mode row(s) excluded (set paper_filter=false "
            f"to include them)."
        )

    return {
        "success": True,
        "date": date,
        "rows_total": len(rows),
        "rows_live_only": len(live_only),
        "paper_dropped": paper_dropped,
        "gross_realized_pnl_sum": round(gross_realized, 2),
        "gross_net_pnl_sum": round(gross_net, 2),
        "clean_net_pnl_estimate": round(clean_net, 2),
        "duplicate_close_groups": duplicate_groups,
        "duplicate_pnl_impact": round(duplicate_pnl_impact, 2),
        "suspicious_rows_count": len(suspicious_rows),
        "suspicious_pnl_sum": round(suspicious_realized_sum, 2),
        "suspicious_rows_sample": suspicious_rows[:20],
        "by_exit_reason": breakdown_sorted,
        "verdict": verdict,
        "hints": hints,
        "rows": live_only[:100],  # cap for response size
    }


@router.get("/scanner-coverage")
def scanner_coverage(hours: int = 6) -> Dict[str, Any]:
    """Surface the IB-subscription vs. universe-size gap for the operator.

    Hypothesis (operator's perpetual complaint 2026-04-29 + v15): every
    surfacing alert is `relative_strength_laggard` / `_leader`. Other
    detectors (`9_ema_scalp`, `vwap_continuation`, `opening_range_break`)
    almost never fire. The pusher subscription is small (~14 symbols
    per SPARK_ACCESS) so live-tick-driven detectors are starved on
    every other symbol, while RS detectors compute against SPY which
    IS always pushed — RS fires for every universe symbol.

    This endpoint exposes the raw inputs so the operator can prove or
    disprove without a 10-min log dive.
    """
    from datetime import timedelta as _timedelta

    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="DB not initialized")

    cutoff = (datetime.now(timezone.utc) - _timedelta(hours=max(1, int(hours)))).isoformat()
    by_setup: Dict[str, int] = {}
    by_direction: Dict[str, int] = {"long": 0, "short": 0, "unknown": 0}
    total_alerts = 0
    try:
        for row in db["live_alerts"].aggregate([
            {"$match": {"timestamp": {"$gte": cutoff}}},
            {"$group": {
                "_id": "$setup_type",
                "n": {"$sum": 1},
                "long_n": {"$sum": {"$cond": [{"$eq": ["$direction", "long"]}, 1, 0]}},
                "short_n": {"$sum": {"$cond": [{"$eq": ["$direction", "short"]}, 1, 0]}},
            }},
            {"$sort": {"n": -1}},
        ]):
            n = int(row.get("n") or 0)
            by_setup[row.get("_id") or "unknown"] = n
            total_alerts += n
            by_direction["long"] += int(row.get("long_n") or 0)
            by_direction["short"] += int(row.get("short_n") or 0)
        by_direction["unknown"] = total_alerts - by_direction["long"] - by_direction["short"]
    except Exception as e:
        logger.warning(f"[scanner-coverage] live_alerts agg failed: {type(e).__name__}: {e}")

    # Pusher subscription
    pusher_subs: List[str] = []
    pusher_sub_count = 0
    try:
        from routers.ib import _pushed_ib_data
        subs_raw = (_pushed_ib_data or {}).get("subscriptions")
        if subs_raw and isinstance(subs_raw, (list, set, tuple)):
            pusher_subs = sorted(str(s).upper() for s in subs_raw)
        else:
            quotes = (_pushed_ib_data or {}).get("quotes") or {}
            if isinstance(quotes, dict):
                pusher_subs = sorted(str(s).upper() for s in quotes.keys())
        pusher_sub_count = len(pusher_subs)
    except Exception as e:
        logger.debug(f"[scanner-coverage] pusher subs read failed: {e}")

    # Canonical universe size
    universe_size = 0
    try:
        universe_size = db["symbol_adv_cache"].count_documents({})
    except Exception as e:
        logger.debug(f"[scanner-coverage] symbol_adv_cache count failed: {e}")

    # "Starved" detectors
    starved_threshold = 1
    starved = []
    if universe_size >= 20:
        expected_setups: List[str] = []
        try:
            from services.enhanced_scanner import get_enhanced_scanner
            sc = get_enhanced_scanner()
            expected_setups = sorted(getattr(sc, "_enabled_setups", set()) or [])
        except Exception:
            expected_setups = sorted(by_setup.keys())
        for st in expected_setups:
            if by_setup.get(st, 0) <= starved_threshold:
                starved.append({"setup_type": st, "alerts_in_window": by_setup.get(st, 0)})

    # Operator-facing verdict
    verdict = "unknown"
    hint = None
    rs_share = 0.0
    if total_alerts > 0:
        rs_count = (
            by_setup.get("relative_strength_laggard", 0)
            + by_setup.get("relative_strength_leader", 0)
        )
        rs_share = rs_count / total_alerts
        if rs_share >= 0.7:
            verdict = "rs_dominated"
            hint = (
                f"RS-only setups account for {rs_share:.0%} of {total_alerts} "
                f"alerts in the last {hours}h. Pusher subscription is "
                f"{pusher_sub_count} symbols vs. {universe_size} canonical "
                f"universe. Live-tick-driven detectors (RVOL, EMA9, OR break) "
                f"are starved on the {max(0, universe_size - pusher_sub_count)} "
                f"unsubscribed symbols. Action: expand pusher subscription "
                f"on the Windows PC or accept RS-dominated breadth as a "
                f"known constraint of the small subscription footprint."
            )
        elif rs_share >= 0.4:
            verdict = "rs_skewed"
            hint = f"RS setups are {rs_share:.0%} of breadth — borderline."
        else:
            verdict = "diverse"
            hint = "Setup breadth looks healthy."
    else:
        verdict = "no_alerts"
        hint = f"Zero alerts in the last {hours}h. Scanner may be off or pre-RTH."

    return {
        "success": True,
        "verdict": verdict,
        "hint": hint,
        "hours": hours,
        "total_alerts": total_alerts,
        "by_setup": by_setup,
        "by_direction": by_direction,
        "rs_share": round(rs_share, 3),
        "pusher_sub_count": pusher_sub_count,
        "pusher_subs_sample": pusher_subs[:30],
        "universe_size": universe_size,
        "starved_setups": starved,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }



# ===========================================================================
# /api/diagnostic/pusher-rotation-status — 500-line budget allocation
# ===========================================================================
@router.get("/pusher-rotation-status")
def pusher_rotation_status(
    dry_run_preview: bool = False,
) -> Dict[str, Any]:
    """Surface the rotation service state.

    Args:
        dry_run_preview: if True, also computes what the next rotation
            would do (without applying it). Useful before a manual rotation.

    Returns:
        - running: bool — is the rotation loop alive?
        - active_profile: str — current time-of-day profile
        - budget: max/usable/safety-buffer
        - current_pusher_subscriptions: int — what's actually subscribed
        - last_rotation: dict — most recent applied rotation
        - dry_run_diff: dict — what would change if we rotated now (optional)
    """
    from services.pusher_rotation_service import (
        get_rotation_service, MAX_LINES, USABLE_LINES, SAFETY_BUFFER,
    )
    svc = get_rotation_service(db=_get_db())
    out: Dict[str, Any] = svc.status()
    out["budget"] = {
        "max_lines": MAX_LINES,
        "usable_lines": USABLE_LINES,
        "safety_buffer": SAFETY_BUFFER,
    }
    out["timestamp"] = datetime.now(timezone.utc).isoformat()

    if dry_run_preview:
        try:
            preview = svc.rotate_once(dry_run=True)
            out["dry_run_preview"] = {
                "profile": preview.get("profile"),
                "budget_used": preview.get("budget_used"),
                "by_cohort": {
                    k: len(v) for k, v in (preview.get("by_cohort") or {}).items()
                },
                "diff": preview.get("diff"),
                "warnings": preview.get("warnings"),
                "safety_pinned_count": preview.get("safety_pinned_count"),
            }
        except Exception as e:
            out["dry_run_preview"] = {
                "error": f"{type(e).__name__}: {e}",
            }

    return out


@router.post("/pusher-rotation-rotate-now")
def pusher_rotation_rotate_now() -> Dict[str, Any]:
    """Operator escape hatch — force a rotation cycle right now.
    Useful after manually opening a position before the next scheduled
    refresh (the loop pins new positions on its own each minute, but
    this is faster). Audit-logged in `pusher_rotation_log`."""
    from services.pusher_rotation_service import get_rotation_service
    svc = get_rotation_service(db=_get_db())
    try:
        result = svc.rotate_once(dry_run=False)
        return {
            "success": True,
            "rotated_at": result.get("ts"),
            "profile": result.get("profile"),
            "budget_used": result.get("budget_used"),
            "added_count": len(result.get("diff", {}).get("to_add", [])),
            "removed_count": len(result.get("diff", {}).get("to_remove", [])),
            "would_remove_held": result.get("diff", {}).get("would_remove_held", []),
            "warnings": result.get("warnings", []),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Rotation failed: {type(e).__name__}: {e}",
        )



# ===========================================================================
# /api/diagnostic/bar-poll-status — universe-coverage gap-filler (v18)
# ===========================================================================
@router.get("/bar-poll-status")
def bar_poll_status() -> Dict[str, Any]:
    """Surface bar-poll service state.

    Companion to `/pusher-rotation-status`. The bar poll service runs
    bar-based detectors on the universe-minus-pusher pool, reading
    from `ib_historical_data` Mongo (no IB calls, no rate limits).

    Returns:
        - running: bool
        - pools: list of {name, interval_s, last_run_ts, cursor}
        - lifetime_alerts_emitted: int
        - last_cycle_summary: dict (most recent poll batch)
    """
    from services.bar_poll_service import get_bar_poll_service
    svc = get_bar_poll_service(db=_get_db())
    out = svc.status()
    out["timestamp"] = datetime.now(timezone.utc).isoformat()
    return out


@router.post("/bar-poll-trigger")
async def bar_poll_trigger(pool: str = "intraday_noncore") -> Dict[str, Any]:
    """Operator escape hatch — trigger a single bar-poll cycle on the
    requested pool right now. Useful for ad-hoc testing or after a
    market-hours fresh-bar update without waiting for the cadence."""
    from services.bar_poll_service import get_bar_poll_service
    svc = get_bar_poll_service(db=_get_db())
    if pool not in {"intraday_noncore", "swing", "investment"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown pool '{pool}' — must be one of "
                   "intraday_noncore, swing, investment",
        )
    try:
        return await svc.poll_pool_once(pool)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Bar poll failed: {type(e).__name__}: {e}",
        )



# ===========================================================================
# /api/diagnostic/dlq-purge — clean up the historical-data dead-letter queue
# ===========================================================================
#
# The V5 HUD shows a `N DLQ` badge for failed historical-data collection
# requests (per `DeadLetterBadge.jsx`). It reads
# `/api/ib-collector/queue-progress-detailed` and surfaces the `failed`
# count.
#
# Two complementary endpoints already exist for this collection:
#   • POST /api/ib-collector/retry-failed — re-queues failed items
#   • GET  /api/ib-collector/failed-items — lists them
#
# What was missing: **purge**. Some failures are TERMINALLY bad and will
# never succeed on retry:
#   • `no security definition` (e.g., delisted symbols like "SLY")
#   • `contract_not_found`
#   • `no_data` for symbols that genuinely have no IB data
#   • items older than N days (operator gave up on them)
#
# Retrying these wastes IB pacing budget and pollutes the DLQ count, so
# the operator can't distinguish "5 transient failures we should retry"
# from "47 permanent failures we should drop".
#
# This endpoint deletes them. Safe by default — only deletes items
# matching a strict allowlist of known-permanent error patterns. Operator
# can override with `force=true` to purge ALL failed items.
# ===========================================================================
@router.post("/dlq-purge")
def dlq_purge(
    permanent_only: bool = True,
    older_than_hours: Optional[int] = None,
    bar_size: Optional[str] = None,
    force: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Purge permanently-failed historical-data requests.

    Args:
        permanent_only: when True (default), only purge items whose error
            matches a strict allowlist of "will-never-succeed" patterns
            (no security definition, contract not found, etc.). When
            False AND `force=True`, purge ALL failed items.
        older_than_hours: additional filter — only purge items at least
            this old. Useful for "drop all DLQ items older than 7 days".
        bar_size: scope to a single bar_size (e.g., "1 min").
        force: required when permanent_only=False, to prevent accidental
            mass-deletion of retryable transient failures.
        dry_run: when True, return what WOULD be purged without deleting.

    Returns:
        {
          "success": True,
          "purged_count": int,
          "by_error_type": {"no_security_definition": 3, "no_data": 2},
          "by_bar_size": {"1 min": 4, "5 mins": 1},
          "dry_run": bool,
        }
    """
    if not permanent_only and not force:
        raise HTTPException(
            status_code=400,
            detail=("permanent_only=False requires force=true to prevent "
                    "accidental mass-deletion of retryable failures. Use "
                    "the /retry-failed endpoint instead unless you really "
                    "want to drop transient errors."),
        )

    try:
        from services.historical_data_queue_service import (
            get_historical_data_queue_service,
        )
        from datetime import timedelta
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"queue service unavailable: {type(e).__name__}: {e}",
        )

    service = get_historical_data_queue_service()
    if not getattr(service, "_initialized", False):
        try:
            service.initialize()
        except Exception:
            pass
    coll = service.collection

    # Build the query
    query: Dict[str, Any] = {"status": "failed"}

    if permanent_only:
        # Strict allowlist of patterns that indicate a "will-never-succeed"
        # error. Anything outside this list is considered retryable and
        # left alone.
        permanent_patterns = [
            "no security definition",       # IB error 200 — delisted/unknown
            "contract not found",            # similar
            "contract_not_found",
            "no_data",                       # IB returned empty for valid contract
            "Contract: Stock",               # generic IB contract error
            "ambiguous contract",
            "expired contract",
        ]
        regex = "|".join(permanent_patterns)
        query["$or"] = [
            {"failure_reason": {"$regex": regex, "$options": "i"}},
            {"result_status": {"$regex": regex, "$options": "i"}},
            {"error": {"$regex": regex, "$options": "i"}},
        ]

    if bar_size:
        query["bar_size"] = bar_size

    if older_than_hours:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=int(older_than_hours))
        ).isoformat()
        # Most failed records have either `completed_at` or `created_at`.
        existing = query.get("$or", [])
        timestamp_filter = [
            {"completed_at": {"$lt": cutoff}},
            {"created_at": {"$lt": cutoff}},
        ]
        # If we already had an $or for the regex, $and the two filters together.
        if existing:
            query.pop("$or", None)
            query["$and"] = [
                {"$or": existing},
                {"$or": timestamp_filter},
            ]
        else:
            query["$or"] = timestamp_filter

    # Aggregate stats BEFORE delete (or in dry-run, just for reporting)
    by_error_type: Dict[str, int] = {}
    by_bar_size: Dict[str, int] = {}
    sample: List[Dict[str, Any]] = []
    try:
        for doc in coll.find(query, {
            "_id": 0, "symbol": 1, "bar_size": 1, "failure_reason": 1,
            "result_status": 1, "error": 1, "completed_at": 1,
        }).limit(2000):
            err = (doc.get("failure_reason") or doc.get("result_status")
                   or doc.get("error") or "unknown")[:80]
            by_error_type[err] = by_error_type.get(err, 0) + 1
            bs = doc.get("bar_size") or "unknown"
            by_bar_size[bs] = by_bar_size.get(bs, 0) + 1
            if len(sample) < 10:
                sample.append({
                    "symbol": doc.get("symbol"),
                    "bar_size": doc.get("bar_size"),
                    "error": err,
                    "completed_at": doc.get("completed_at"),
                })
    except Exception as e:
        logger.warning(
            "[dlq-purge] aggregate-before-delete failed (%s): %s",
            type(e).__name__, e, exc_info=True,
        )

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "would_purge_count": sum(by_error_type.values()),
            "by_error_type": by_error_type,
            "by_bar_size": by_bar_size,
            "sample": sample,
            "permanent_only": permanent_only,
            "older_than_hours": older_than_hours,
            "bar_size": bar_size,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # Actually delete
    try:
        result = coll.delete_many(query)
        purged_count = int(getattr(result, "deleted_count", 0))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"DLQ purge delete failed: {type(e).__name__}: {e}",
        )

    # Audit log
    try:
        db = _get_db()
        if db is not None:
            db["dlq_purge_log"].insert_one({
                "ts": datetime.now(timezone.utc).isoformat(),
                "ts_dt": datetime.now(timezone.utc),
                "purged_count": purged_count,
                "by_error_type": by_error_type,
                "by_bar_size": by_bar_size,
                "permanent_only": permanent_only,
                "older_than_hours": older_than_hours,
                "bar_size": bar_size,
                "force": force,
            })
            try:
                db["dlq_purge_log"].create_index(
                    "ts_dt", expireAfterSeconds=30 * 24 * 3600,  # 30d audit retention
                )
            except Exception:
                pass
    except Exception:
        pass

    return {
        "success": True,
        "dry_run": False,
        "purged_count": purged_count,
        "by_error_type": by_error_type,
        "by_bar_size": by_bar_size,
        "sample": sample,
        "permanent_only": permanent_only,
        "older_than_hours": older_than_hours,
        "bar_size": bar_size,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── v19.34.122 (Feb 2026) — Setup win-rate breakdown ─────────────────────
#
# Companion to scripts/setup_winrate_breakdown_v19_34_121.py — exposes the
# same aggregation via HTTP so the operator can curl it from any shell
# without worrying about Python interpreter / venv / pymongo install state
# on the DGX. Also feeds the next-iteration UI panel.
#
# Direction-suffixes are normalized (`mean_reversion_long` and
# `mean_reversion_short` aggregate into `mean_reversion`) because the
# operator's decision lever is per-SETUP (enable/disable in
# `_enabled_setups`), not per-direction-cell.

@router.get("/setup-winrate-breakdown")
def setup_winrate_breakdown(
    days: int = 30,
    min_samples: int = 3,
):
    """Aggregate `alert_outcomes` by setup_type and surface the bleeders.

    Query:
      • days        — lookback window (default 30)
      • min_samples — hide setups with fewer than N closed alerts (default 3)

    Returns rows sorted by net_pnl ascending (worst first) with a verdict:
        🔴 KILL   — WR < 25% with n ≥ 5
        🟡 review — WR < 35% AND net < 0
        🟢 keep   — WR ≥ 55% AND net > 0
        ⚪ neutral — anything else
    """
    from collections import defaultdict
    from datetime import timedelta

    db = _get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cursor = db["alert_outcomes"].find(
        {"closed_at": {"$gte": cutoff}},
        {
            "_id": 0, "setup_type": 1, "direction": 1, "outcome": 1,
            "pnl": 1, "r_multiple": 1, "trade_grade": 1, "closed_at": 1,
        },
    )

    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    total_rows = 0
    for row in cursor:
        st = (row.get("setup_type") or "<missing>").lower()
        for suffix in ("_long", "_short", "_confirmed"):
            if st.endswith(suffix):
                st = st[: -len(suffix)]
                break
        buckets[st].append(row)
        total_rows += 1

    rows: List[Dict[str, Any]] = []
    for setup, items in buckets.items():
        n = len(items)
        if n < min_samples:
            continue
        wins   = sum(1 for r in items if (r.get("pnl") or 0) > 0)
        losses = sum(1 for r in items if (r.get("pnl") or 0) < 0)
        wr     = wins / n if n else 0.0
        net    = sum(float(r.get("pnl") or 0) for r in items)
        r_mults = [float(r.get("r_multiple") or 0) for r in items if r.get("r_multiple") is not None]
        avg_r  = (sum(r_mults) / len(r_mults)) if r_mults else 0.0
        if wr < 0.25 and n >= 5:
            verdict = "kill"
        elif wr < 0.35 and net < 0:
            verdict = "review"
        elif wr >= 0.55 and net > 0:
            verdict = "keep"
        else:
            verdict = "neutral"
        rows.append({
            "setup_type": setup, "n": n, "wins": wins, "losses": losses,
            "win_rate": round(wr, 3),
            "avg_r_multiple": round(avg_r, 3),
            "net_pnl": round(net, 2),
            "verdict": verdict,
        })

    rows.sort(key=lambda r: r["net_pnl"])

    kill_list = [r["setup_type"] for r in rows if r["verdict"] == "kill"]
    review_list = [r["setup_type"] for r in rows if r["verdict"] == "review"]

    return {
        "success": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "window_days": days,
        "min_samples": min_samples,
        "total_alerts": total_rows,
        "rows": rows,
        "kill_candidates": kill_list,
        "review_candidates": review_list,
        "summary": (
            f"{len(kill_list)} setup(s) to KILL · "
            f"{len(review_list)} to REVIEW · "
            f"{len(rows)} setups with ≥{min_samples} samples over {days}d"
        ),
    }



# ── v19.34.124 — Bracket lifecycle audit endpoint ────────────────────
#
# Today's incident: 100+ bot-placed stop loss legs cancelled in two
# mass waves (11:21 and 15:29). Zero bot stops actually fired. Need a
# way to walk `bracket_lifecycle_events` and find the cause without
# pulling the whole collection.
#
# This endpoint takes (symbol, date) and returns every attach / cancel
# / reissue event grouped by trade_id, so the operator can spot:
#   • Stops cancelled without a replacement → orphaned canonical
#   • Multiple OCA groups on one canonical → IB OCA conflict
#   • Cancel-cluster (5+ cancels in <60s) → mass-cancel root cause

@router.get("/bracket-lifecycle")
def bracket_lifecycle_audit(
    symbol: Optional[str] = None,
    date: Optional[str] = None,  # ISO date, default = today UTC
    trade_id: Optional[str] = None,
    limit: int = 200,
):
    """Walk `bracket_lifecycle_events` for a symbol or trade_id.

    v19.34.125 — schema-fix:
      • Filters on `created_at` (BSON datetime), NOT a non-existent `ts`
        string. The persistence layer in `bracket_reissue_service.py`
        stamps `created_at = datetime.now(timezone.utc)`; the prior
        version of this endpoint queried `ts` and silently returned 0
        events even when the collection was healthy.
      • Maps the actual `phase` values written by the persistence layer
        (`done`/`cancel`/`submit`/`throttle`/`boot_zombie_sweep`) into
        operator-readable categories.

    Returns events grouped by trade_id with derived metrics:
      • `attaches`, `cancels`, `reissues`, `failures` per trade
      • `mass_cancel_clusters`: timestamp windows with 5+ cancels in 60s
      • `orphaned_stops`: trades whose last event was a cancel/failure
        with no subsequent successful re-issue
      • `naked_positions`: trades where cancel succeeded but submit failed
        (the catastrophic case from the -$25k incident)
    """
    from datetime import datetime as _dt, timedelta as _td

    db = _get_db()

    if not date:
        date = _dt.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        day_start = _dt.fromisoformat(f"{date}T00:00:00").replace(tzinfo=timezone.utc)
    except ValueError:
        return {"success": False, "error": f"invalid date format: {date} (expected YYYY-MM-DD)"}
    day_end = day_start + _td(days=1)

    q: Dict[str, Any] = {
        "created_at": {"$gte": day_start, "$lt": day_end},
    }
    if symbol:
        q["symbol"] = symbol.upper()
    if trade_id:
        q["trade_id"] = trade_id

    events = list(
        db["bracket_lifecycle_events"]
          .find(q, {"_id": 0})
          .sort("created_at", 1)
          .limit(limit)
    )

    # Normalize created_at → ISO string for JSON responses, preserve
    # the datetime for cluster math below.
    def _iso(v):
        return v.isoformat() if hasattr(v, "isoformat") else (v or "")
    for ev in events:
        ev["created_at_iso"] = _iso(ev.get("created_at"))

    # Phase → category map. Mirrors the writer in `bracket_reissue_service.py`
    #   phase="done"     + success=True   → reissue (cancel-old + submit-new OK)
    #   phase="cancel"   + success=False  → cancel_failed (old bracket survived)
    #   phase="submit"   + success=False  → naked  (cancel OK but submit FAIL)
    #   phase="throttle" + success=False  → throttled (refused, no IB action)
    #   phase="boot_zombie_sweep*"        → boot_observation
    def _classify(ev: Dict[str, Any]) -> str:
        phase = (ev.get("phase") or "").lower()
        ok = bool(ev.get("success"))
        if phase == "done" and ok:
            return "reissue"
        if phase == "cancel" and not ok:
            return "cancel_failed"
        if phase == "submit" and not ok:
            return "naked"
        if phase == "throttle":
            return "throttled"
        if phase.startswith("boot_zombie_sweep"):
            return "boot_observation"
        return f"unknown:{phase or 'none'}"

    from collections import defaultdict
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for ev in events:
        ev["_category"] = _classify(ev)
        grouped[ev.get("trade_id") or "<no_trade_id>"].append(ev)

    per_trade: List[Dict[str, Any]] = []
    naked_trades: List[Dict[str, Any]] = []
    orphaned: List[Dict[str, Any]] = []
    for tid, evts in grouped.items():
        cats = [e["_category"] for e in evts]
        reissues = sum(1 for c in cats if c == "reissue")
        cancels  = sum(1 for c in cats if c in ("cancel_failed", "naked"))
        naked    = sum(1 for c in cats if c == "naked")
        last_cat = cats[-1] if cats else ""
        is_orphaned = last_cat in ("cancel_failed", "naked")
        row = {
            "trade_id": tid,
            "symbol": (evts[0].get("symbol") if evts else None),
            "event_count": len(evts),
            "reissues": reissues,
            "cancels": cancels,
            "naked_events": naked,
            "throttled": sum(1 for c in cats if c == "throttled"),
            "last_category": last_cat,
            "orphaned_stop": is_orphaned,
            "first_event_at": evts[0].get("created_at_iso") if evts else None,
            "last_event_at":  evts[-1].get("created_at_iso") if evts else None,
            "events": evts,
        }
        per_trade.append(row)
        if naked > 0:
            naked_trades.append({
                "trade_id": tid,
                "symbol": row["symbol"],
                "last_event_at": row["last_event_at"],
                "naked_events": naked,
            })
        if is_orphaned:
            orphaned.append({
                "trade_id": tid,
                "symbol": row["symbol"],
                "last_event_at": row["last_event_at"],
                "last_category": last_cat,
            })

    # Mass-cancel cluster detection (5+ cancels within 60s window).
    # Uses the raw `created_at` datetime for accuracy.
    cancel_events = sorted(
        [e for e in events if e["_category"] in ("cancel_failed", "naked")],
        key=lambda x: x.get("created_at") or _dt.min.replace(tzinfo=timezone.utc),
    )
    clusters: List[Dict[str, Any]] = []
    i = 0
    while i < len(cancel_events):
        anchor = cancel_events[i]
        anchor_t = anchor.get("created_at")
        if not hasattr(anchor_t, "timestamp"):
            i += 1
            continue
        window_evts = [anchor]
        j = i + 1
        while j < len(cancel_events):
            t_j = cancel_events[j].get("created_at")
            if not hasattr(t_j, "timestamp"):
                j += 1
                continue
            if (t_j - anchor_t).total_seconds() <= 60:
                window_evts.append(cancel_events[j])
                j += 1
            else:
                break
        if len(window_evts) >= 5:
            clusters.append({
                "started_at": _iso(anchor.get("created_at")),
                "window_seconds": 60,
                "cancel_count": len(window_evts),
                "symbols": sorted({e.get("symbol") for e in window_evts if e.get("symbol")}),
            })
            i = j
        else:
            i += 1

    # Collection-health context — operator visibility into whether the
    # writer is actually running. Total docs + most recent timestamp.
    try:
        total_in_collection = db["bracket_lifecycle_events"].estimated_document_count()
    except Exception:
        total_in_collection = None
    latest_doc = None
    try:
        latest = list(
            db["bracket_lifecycle_events"]
              .find({}, {"_id": 0, "created_at": 1, "symbol": 1, "phase": 1})
              .sort("created_at", -1).limit(1)
        )
        if latest:
            latest_doc = {
                "symbol": latest[0].get("symbol"),
                "phase":  latest[0].get("phase"),
                "created_at": _iso(latest[0].get("created_at")),
            }
    except Exception:
        pass

    return {
        "success": True,
        "query": {"symbol": symbol, "date": date, "trade_id": trade_id, "limit": limit},
        "schema_version": "v19.34.125",
        "total_events": len(events),
        "unique_trades": len(grouped),
        "collection_total_docs": total_in_collection,
        "collection_latest_event": latest_doc,
        "per_trade": sorted(per_trade, key=lambda r: -r["event_count"]),
        "mass_cancel_clusters": clusters,
        "naked_positions": naked_trades,
        "orphaned_stops": orphaned,
        "summary": (
            f"{len(events)} events across {len(grouped)} trades for {date}. "
            f"{len(clusters)} mass-cancel cluster(s). "
            f"{len(naked_trades)} naked-position event(s). "
            f"{len(orphaned)} trade(s) with orphaned stops. "
            f"Collection holds {total_in_collection} total docs (7d TTL)."
        ),
    }

