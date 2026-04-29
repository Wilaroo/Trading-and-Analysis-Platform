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
