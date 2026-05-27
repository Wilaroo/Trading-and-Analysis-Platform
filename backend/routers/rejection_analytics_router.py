"""v19.34.41 -- Rejection Analytics + Scanner Quality Score.

GET /api/system/rejection-analytics?date=YYYY-MM-DD

Aggregates bot_trades (rejected_* statuses) + trade_drops (silent gate
drops) for the ET trading day. Returns a "Scanner Quality Score"
(accepted / (accepted + scanner-quality rejections)) plus breakdowns by
reason / category / setup.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system", "rejection-analytics"])


CAT_SCANNER_QUALITY = "scanner_quality"
CAT_BROKER = "broker"
CAT_POLICY = "policy"
CAT_OTHER = "other"


REASON_MAP: Dict[str, Dict[str, str]] = {
    "stale_alert":        {"label": "Stale alert (TTL expired)",            "category": CAT_SCANNER_QUALITY},
    "stale_alert_ttl":    {"label": "Stale alert (pipeline-lag TTL)",        "category": CAT_SCANNER_QUALITY},
    "live_price_gate":    {"label": "Live-price gate (>2.5% from alert)",   "category": CAT_SCANNER_QUALITY},
    "cooldown":           {"label": "Recent-rejection cooldown",            "category": CAT_SCANNER_QUALITY},
    "rejection_cooldown": {"label": "Recent-rejection cooldown",            "category": CAT_SCANNER_QUALITY},
    "post_stop_cooldown": {"label": "Post-stop cooldown (same symbol+setup)", "category": CAT_POLICY},
    "ttl_expired":        {"label": "Setup TTL expired",                    "category": CAT_SCANNER_QUALITY},
    "broker_rejected":    {"label": "Broker rejected (uncategorised)",      "category": CAT_BROKER},
    "execution_exception": {"label": "Execution exception",                 "category": CAT_BROKER},
    # v19.34.55 — broker_rejected sub-triage (per-cause breakdown).
    "parent_cancelled":   {"label": "Parent leg cancelled (bracket OCA)",   "category": CAT_BROKER},
    "margin_insufficient": {"label": "Insufficient margin/buying power",    "category": CAT_BROKER},
    "pacing_violation":   {"label": "Pacing violation (Error 162)",         "category": CAT_BROKER},
    "no_security_def":    {"label": "No security definition (Error 200)",   "category": CAT_BROKER},
    "connection_lost":    {"label": "IB connection lost (Error 1100/1101)", "category": CAT_BROKER},
    "duplicate_order":    {"label": "Duplicate order ID (Error 322)",       "category": CAT_BROKER},
    "min_tick":           {"label": "Min price variation (Error 110)",      "category": CAT_BROKER},
    "error_202":          {"label": "Order cancelled by IB (Error 202)",    "category": CAT_BROKER},
    "bracket_submission_timeout": {"label": "Bracket submission timeout",   "category": CAT_BROKER},
    "pusher_offline_cannot_close_in_live_mode": {"label": "Pusher offline (close)", "category": CAT_BROKER},
    "account_guard":      {"label": "Account guard",                        "category": CAT_POLICY},
    "safety_guardrail":   {"label": "Safety guardrail",                     "category": CAT_POLICY},
    "safety_guardrail_crash": {"label": "Safety guardrail crash",           "category": CAT_POLICY},
    "no_trade_executor":  {"label": "Trade executor missing",               "category": CAT_POLICY},
    "pre_exec_guardrail_veto": {"label": "Pre-exec guardrail veto",         "category": CAT_POLICY},
    "strategy_paper_phase":     {"label": "Strategy in PAPER phase",        "category": CAT_POLICY},
    "strategy_simulation_phase": {"label": "Strategy in SIMULATION phase",  "category": CAT_POLICY},
    "kill_switch":        {"label": "Kill-switch active",                   "category": CAT_POLICY},
    "eod_blackout":       {"label": "EOD blackout window",                  "category": CAT_POLICY},
    # v19.34.164 — gates surfaced by `record_rejection` once it began
    # persisting every rejection to `trade_drops` (May 2026). Order
    # mirrors the bot's evaluation pipeline so the UI groups them in
    # logical sections.
    "symbol_direction_open_cap_v123": {"label": "Already open (symbol+direction cap)", "category": CAT_POLICY},
    "eod_no_new_entries": {"label": "EOD no-new-entries (≥3:55pm ET)",      "category": CAT_POLICY},
    "no_price":           {"label": "No live price available",              "category": CAT_SCANNER_QUALITY},
    "smart_filter_skip":  {"label": "Smart filter SKIP (historical win-rate)", "category": CAT_SCANNER_QUALITY},
    "gate_skip":          {"label": "Confidence gate SKIP",                  "category": CAT_SCANNER_QUALITY},
    "symbol_exposure_saturated": {"label": "Per-symbol exposure cap reached", "category": CAT_POLICY},
    "position_size_zero": {"label": "Position size = 0 shares",              "category": CAT_SCANNER_QUALITY},
    "rr_below_min":       {"label": "R:R below setup minimum",               "category": CAT_SCANNER_QUALITY},
    "ai_consultation_block": {"label": "AI consultation BLOCKED",            "category": CAT_SCANNER_QUALITY},
    "ai_verdict_reject":  {"label": "Legacy AI verdict REJECT",              "category": CAT_SCANNER_QUALITY},
    "evaluator_exception": {"label": "Evaluator exception",                  "category": CAT_OTHER},
    "evaluator_veto_unknown": {"label": "Evaluator veto (unspecified)",      "category": CAT_OTHER},
    "max_open_positions": {"label": "Max open positions reached",            "category": CAT_POLICY},
    "dedup_cooldown":     {"label": "Alert dedup cooldown (~5min)",          "category": CAT_SCANNER_QUALITY},
    "dedup_open_position": {"label": "Alert dedup — position open",          "category": CAT_POLICY},
    "position_exists":    {"label": "Position already exists (safety net)",  "category": CAT_POLICY},
    "pending_trade_exists": {"label": "Pending trade exists (safety net)",   "category": CAT_POLICY},
    "setup_disabled":     {"label": "Setup disabled",                        "category": CAT_POLICY},
    "watchlist_only_skip": {"label": "Watchlist-only setup (silent)",        "category": CAT_OTHER},
    "scanner_paused":     {"label": "Scanner paused (guardrail)",            "category": CAT_POLICY},
}


def _normalise_reason(raw: Optional[str]) -> str:
    """Normalise a status/gate/error string to a key in REASON_MAP."""
    if not raw:
        return "other"
    s = str(raw).lower().strip()
    if s.startswith("rejected_"):
        s = s[len("rejected_"):]
    if "stale" in s:
        return "stale_alert"
    if "live_price" in s or "live-price" in s or "price_gate" in s:
        return "live_price_gate"
    if "cooldown" in s:
        return "rejection_cooldown"
    if "ttl" in s and "expir" in s:
        return "ttl_expired"
    if "error 1100" in s or "error 1101" in s or "connectivity" in s or "connection_lost" in s:
        return "connection_lost"
    if "error 110" in s or "min_tick" in s or "min price variation" in s:
        return "min_tick"
    if "error 202" in s or "cancelled by ib" in s:
        return "error_202"
    # v19.34.55 — broker_rejected sub-triage. Order matters.
    if "error 201" in s or "insufficient" in s or "margin" in s or "buying power" in s:
        return "margin_insufficient"
    if "error 162" in s or "pacing" in s:
        return "pacing_violation"
    if "error 200" in s or "no security definition" in s or "security_def" in s:
        return "no_security_def"
    if "error 322" in s or "duplicate order" in s or "duplicate_order" in s:
        return "duplicate_order"
    if "parent" in s and ("cancel" in s or "cancelled" in s):
        return "parent_cancelled"
    if "bracket" in s and ("timeout" in s or "submission" in s):
        return "bracket_submission_timeout"
    if "kill_switch" in s or "kill-switch" in s:
        return "kill_switch"
    if "eod_blackout" in s or "eod blackout" in s:
        return "eod_blackout"
    return s if s in REASON_MAP else "other"


def _reason_meta(reason_key: str) -> Dict[str, str]:
    meta = REASON_MAP.get(reason_key)
    if meta:
        return {"label": meta["label"], "category": meta["category"]}
    return {"label": reason_key.replace("_", " ").title(), "category": CAT_OTHER}


def _score_bucket(score: float) -> str:
    if score >= 0.90:
        return "excellent"
    if score >= 0.75:
        return "good"
    if score >= 0.50:
        return "fair"
    return "poor"


def _et_day_window(date_str: Optional[str]) -> tuple:
    """Return (YYYY-MM-DD, start_utc, end_utc) for an ET trading day."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo  # type: ignore
    et = ZoneInfo("America/New_York")
    if date_str:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "date must be YYYY-MM-DD")
    else:
        d = datetime.now(et).date()
    start_et = datetime.combine(d, time.min, tzinfo=et)
    end_et = start_et + timedelta(days=1)
    return (
        d.strftime("%Y-%m-%d"),
        start_et.astimezone(timezone.utc),
        end_et.astimezone(timezone.utc),
    )


def _get_db():
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
        return None
    db_name = os.environ.get("DB_NAME") or "test_database"
    return MongoClient(mongo_url)[db_name]


ACCEPTED_STATUSES = {
    "filled", "partial_fill", "partial", "working", "open",
    "closed", "scaled_out", "paper",
}


def _aggregate_bot_trades(db, start_utc, end_utc):
    accepted = 0
    rejected_by_reason: Counter = Counter()
    by_setup: Dict[str, Dict[str, int]] = defaultdict(lambda: {"accepted": 0, "rejected": 0})
    recent: List[Dict[str, Any]] = []
    try:
        cursor = db["bot_trades"].find(
            {"entered_at": {"$gte": start_utc.isoformat(), "$lt": end_utc.isoformat()}},
            {"_id": 0, "id": 1, "symbol": 1, "setup_type": 1, "setup_variant": 1,
             "direction": 1, "status": 1, "entered_at": 1,
             "rejection_reason": 1, "drop_reason": 1, "close_reason": 1, "error_text": 1},
        )
        for row in cursor:
            status = (row.get("status") or "").lower().strip()
            setup = row.get("setup_variant") or row.get("setup_type") or "unknown"
            if status in ACCEPTED_STATUSES:
                accepted += 1
                by_setup[setup]["accepted"] += 1
                continue
            if status.startswith("rejected") or status == "dropped":
                raw_reason = (row.get("rejection_reason") or row.get("drop_reason")
                              or row.get("error_text") or status)
                key = _normalise_reason(raw_reason)
                rejected_by_reason[key] += 1
                by_setup[setup]["rejected"] += 1
                if len(recent) < 20:
                    recent.append({
                        "ts": row.get("entered_at"),
                        "symbol": row.get("symbol"),
                        "setup": setup,
                        "direction": row.get("direction"),
                        "reason_key": key,
                        "reason_label": _reason_meta(key)["label"],
                        "raw_reason": str(raw_reason)[:200],
                        "source": "bot_trades",
                    })
    except Exception as exc:
        logger.warning("[rejection-analytics] bot_trades read failed: %s", exc)
    return {"accepted": accepted, "rejected_by_reason": rejected_by_reason,
            "by_setup": dict(by_setup), "recent_rejections": recent}


def _aggregate_trade_drops(db, start_utc, end_utc):
    rejected_by_reason: Counter = Counter()
    by_setup: Dict[str, Dict[str, int]] = defaultdict(lambda: {"accepted": 0, "rejected": 0})
    recent: List[Dict[str, Any]] = []
    start_ms = int(start_utc.timestamp() * 1000)
    end_ms = int(end_utc.timestamp() * 1000)
    try:
        cursor = db["trade_drops"].find(
            {"ts_epoch_ms": {"$gte": start_ms, "$lt": end_ms}},
            {"_id": 0, "ts_dt": 0},
        ).sort("ts_epoch_ms", -1)
        for row in cursor:
            gate = (row.get("gate") or "").lower()
            reason_text = row.get("reason") or gate
            key = _normalise_reason(reason_text) if reason_text else _normalise_reason(gate)
            if key == "other":
                key = _normalise_reason(gate) if gate else "other"
            rejected_by_reason[key] += 1
            setup = row.get("setup_type") or "unknown"
            by_setup[setup]["rejected"] += 1
            if len(recent) < 20:
                recent.append({
                    "ts": row.get("ts"),
                    "symbol": row.get("symbol"),
                    "setup": setup,
                    "direction": row.get("direction"),
                    "reason_key": key,
                    "reason_label": _reason_meta(key)["label"],
                    "raw_reason": str(reason_text)[:200],
                    "source": "trade_drops",
                    "gate": gate,
                })
    except Exception as exc:
        logger.warning("[rejection-analytics] trade_drops read failed: %s", exc)
    return {"rejected_by_reason": rejected_by_reason,
            "by_setup": dict(by_setup), "recent_rejections": recent}


def _compose_response(trading_date_et, bot_agg, drops_agg):
    accepted = int(bot_agg["accepted"])
    merged: Counter = Counter()
    merged.update(bot_agg["rejected_by_reason"])
    merged.update(drops_agg["rejected_by_reason"])
    by_category = {CAT_SCANNER_QUALITY: 0, CAT_BROKER: 0, CAT_POLICY: 0, CAT_OTHER: 0}
    by_reason: List[Dict[str, Any]] = []
    for key, count in merged.most_common():
        meta = _reason_meta(key)
        by_category[meta["category"]] += count
        by_reason.append({
            "reason_key": key,
            "label": meta["label"],
            "category": meta["category"],
            "count": count,
        })
    scanner_rejections = by_category[CAT_SCANNER_QUALITY]
    denom = accepted + scanner_rejections
    score = (accepted / denom) if denom > 0 else 1.0
    score = max(0.0, min(1.0, score))
    rejected_total = sum(merged.values())
    scanner_signals = accepted + rejected_total
    by_setup: Dict[str, Dict[str, int]] = {}
    for src in (bot_agg["by_setup"], drops_agg["by_setup"]):
        for setup, counts in src.items():
            slot = by_setup.setdefault(setup, {"accepted": 0, "rejected": 0})
            slot["accepted"] += counts.get("accepted", 0)
            slot["rejected"] += counts.get("rejected", 0)
    all_recent = list(bot_agg["recent_rejections"]) + list(drops_agg["recent_rejections"])
    all_recent.sort(key=lambda r: r.get("ts") or "", reverse=True)
    return {
        "success": True,
        "trading_date_et": trading_date_et,
        "scanner_quality_score": round(score, 4),
        "scanner_quality_score_pct": round(score * 100, 1),
        "score_bucket": _score_bucket(score),
        "totals": {
            "accepted": accepted,
            "rejected": rejected_total,
            "scanner_signals": scanner_signals,
        },
        "by_category": by_category,
        "by_reason": by_reason,
        "by_setup": by_setup,
        "recent_rejections": all_recent[:25],
    }


@router.get("/rejection-analytics")
def rejection_analytics(date: Optional[str] = None) -> Dict[str, Any]:
    """Daily rejection breakdown + Scanner Quality Score."""
    trading_date, start_utc, end_utc = _et_day_window(date)
    db = _get_db()
    if db is None:
        return {
            "success": False,
            "error": "db_unavailable",
            "trading_date_et": trading_date,
            "scanner_quality_score": 1.0,
            "scanner_quality_score_pct": 100.0,
            "score_bucket": "excellent",
            "totals": {"accepted": 0, "rejected": 0, "scanner_signals": 0},
            "by_category": {CAT_SCANNER_QUALITY: 0, CAT_BROKER: 0,
                            CAT_POLICY: 0, CAT_OTHER: 0},
            "by_reason": [],
            "by_setup": {},
            "recent_rejections": [],
        }
    bot_agg = _aggregate_bot_trades(db, start_utc, end_utc)
    drops_agg = _aggregate_trade_drops(db, start_utc, end_utc)
    return _compose_response(trading_date, bot_agg, drops_agg)
