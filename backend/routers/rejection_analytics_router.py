"""
v19.34.41 — Rejection Analytics + Scanner Quality Score
========================================================

Operator-facing visibility into WHY the scanner-to-broker funnel is dropping
trades during a session. Surfaces a single, color-codable "Scanner Quality
Score" (0-100) plus a per-reason breakdown so the operator can tell at a
glance whether today's drop rate is driven by:

  • SCANNER QUALITY  — stale alerts, price-gate rejects, cooldowns, TTL
    expiries. The scanner produced a signal that wasn't actionable by the
    time it reached the executor.
  • BROKER           — IB rejections (Error 110 minTick, Error 202, etc.),
    bracket failures, execution exceptions. The scanner was right but the
    broker said no.
  • POLICY           — safety guardrails, kill-switch, account guards, EOD
    blackout. Internal policy declined the trade (NOT a scanner problem).

Data sources unified by this endpoint:
  1. `bot_trades` Mongo collection — canonical entry rows including
     `status="rejected_*"` rows the executor writes when IB refuses an entry
     (e.g. `rejected_stale_alert`, `rejected_live_price_gate`).
  2. `trade_drops` Mongo collection (TTL 7d, via `trade_drop_recorder`) —
     every silent gate drop between the AI gate and the broker write.

Scanner Quality Score
---------------------
    score = accepted / (accepted + scanner_quality_rejections)

Where `scanner_quality_rejections` is the subset of rejections in the
SCANNER_QUALITY category (stale alerts, live-price-gate, TTL, cooldown).
Broker- and policy-category rejections are surfaced separately but are NOT
penalised against the scanner (those are downstream concerns).

Bucketing:
    score ≥ 0.90 → "excellent" (green)
    score ≥ 0.75 → "good"      (blue)
    score ≥ 0.50 → "fair"      (amber)
    score <  0.50 → "poor"     (red)

Endpoint
--------
    GET /api/system/rejection-analytics?date=YYYY-MM-DD

`date` defaults to today (ET). Pass an explicit ET date to backfill.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system", "rejection-analytics"])


# ── Reason normalisation ────────────────────────────────────────────────
# `bot_trades.status` rejection codes + `trade_drops.gate` values → a small
# enum the UI can group/color. Anything unrecognised goes to "other".

# Categories the UI uses to color-bucket reasons:
CAT_SCANNER_QUALITY = "scanner_quality"  # alert was stale/bad by execute-time
CAT_BROKER = "broker"                    # IB rejected a valid alert
CAT_POLICY = "policy"                    # internal policy declined
CAT_OTHER = "other"

# Map of normalised reason → (display label, category).
REASON_MAP: Dict[str, Dict[str, str]] = {
    # ── scanner-quality (count against the score) ──
    "stale_alert":        {"label": "Stale alert (TTL expired)",            "category": CAT_SCANNER_QUALITY},
    "stale_alert_ttl":    {"label": "Stale alert (pipeline-lag TTL)",        "category": CAT_SCANNER_QUALITY},
    "live_price_gate":    {"label": "Live-price gate (>2.5% from alert)",   "category": CAT_SCANNER_QUALITY},
    "cooldown":           {"label": "Recent-rejection cooldown",            "category": CAT_SCANNER_QUALITY},
    "rejection_cooldown": {"label": "Recent-rejection cooldown",            "category": CAT_SCANNER_QUALITY},
    "ttl_expired":        {"label": "Setup TTL expired",                    "category": CAT_SCANNER_QUALITY},
    # ── broker (informational; doesn't count against scanner score) ──
    "broker_rejected":    {"label": "Broker rejected (uncategorised)",      "category": CAT_BROKER},
    "execution_exception": {"label": "Execution exception",                 "category": CAT_BROKER},
    "min_tick":           {"label": "Min price variation (Error 110)",      "category": CAT_BROKER},
    "error_202":          {"label": "Order cancelled by IB (Error 202)",    "category": CAT_BROKER},
    "bracket_submission_timeout": {"label": "Bracket submission timeout",   "category": CAT_BROKER},
    "pusher_offline_cannot_close_in_live_mode": {"label": "Pusher offline (close)", "category": CAT_BROKER},
    # v19.34.55 — broker_rejected sub-triage (per-cause breakdown so the
    # UI shows WHY a broker rejection happened instead of the umbrella
    # "Broker rejected" label that hid every cause behind one bucket).
    "parent_cancelled":   {"label": "Parent leg cancelled (bracket OCA)",   "category": CAT_BROKER},
    "margin_insufficient": {"label": "Insufficient margin/buying power",    "category": CAT_BROKER},
    "pacing_violation":   {"label": "Pacing violation (Error 162)",         "category": CAT_BROKER},
    "no_security_def":    {"label": "No security definition (Error 200)",   "category": CAT_BROKER},
    "connection_lost":    {"label": "IB connection lost (Error 1100/1101)", "category": CAT_BROKER},
    "duplicate_order":    {"label": "Duplicate order ID (Error 322)",       "category": CAT_BROKER},
    # ── policy (informational; doesn't count against scanner score) ──
    "account_guard":      {"label": "Account guard",                        "category": CAT_POLICY},
    "safety_guardrail":   {"label": "Safety guardrail",                     "category": CAT_POLICY},
    "safety_guardrail_crash": {"label": "Safety guardrail crash",           "category": CAT_POLICY},
    "no_trade_executor":  {"label": "Trade executor missing",               "category": CAT_POLICY},
    "pre_exec_guardrail_veto": {"label": "Pre-exec guardrail veto",         "category": CAT_POLICY},
    "strategy_paper_phase":     {"label": "Strategy in PAPER phase",        "category": CAT_POLICY},
    "strategy_simulation_phase": {"label": "Strategy in SIMULATION phase",  "category": CAT_POLICY},
    "kill_switch":        {"label": "Kill-switch active",                   "category": CAT_POLICY},
    "eod_blackout":       {"label": "EOD blackout window",                  "category": CAT_POLICY},
}


def _normalise_reason(raw: Optional[str]) -> str:
    """Normalise a status/gate/error string to a key in REASON_MAP."""
    if not raw:
        return "other"
    s = str(raw).lower().strip()
    s = s.removeprefix("rejected_")
    # Map common IB error codes / phrases to canonical reasons.
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
    # v19.34.55 — broker_rejected sub-triage. Order matters: more
    # specific patterns first so e.g. "Error 201" doesn't slip into
    # the broader "rejected" bucket. connection_lost handled above
    # because "Error 110" is a substring of "Error 1100"/"1101".
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
    # Fall through to REASON_MAP key match.
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


def _et_day_window(date_str: Optional[str]) -> tuple[str, datetime, datetime]:
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
    """Same lazy Mongo handle pattern used by diagnostic_router."""
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


# ── Aggregation ──────────────────────────────────────────────────────────


def _aggregate_bot_trades(
    db, start_utc: datetime, end_utc: datetime,
) -> Dict[str, Any]:
    """Walk `bot_trades` for the date window.

    Returns:
        accepted: count of rows with status in {filled, partial_fill, working,
                  open, closed, scaled_out}.
        rejected_by_reason: Counter of reason_key → count.
        by_setup: {setup_type: {"accepted": N, "rejected": N}}
        recent_rejections: up to 20 recent rejected rows.
    """
    accepted = 0
    rejected_by_reason: Counter = Counter()
    by_setup: Dict[str, Dict[str, int]] = defaultdict(lambda: {"accepted": 0, "rejected": 0})
    recent: List[Dict[str, Any]] = []

    ACCEPTED_STATUSES = {
        "filled", "partial_fill", "partial", "working", "open",
        "closed", "scaled_out", "paper",
    }

    try:
        # Query — pull only what we need.
        cursor = db["bot_trades"].find(
            {
                "entered_at": {
                    "$gte": start_utc.isoformat(),
                    "$lt": end_utc.isoformat(),
                }
            },
            {
                "_id": 0,
                "id": 1,
                "symbol": 1,
                "setup_type": 1,
                "setup_variant": 1,
                "direction": 1,
                "status": 1,
                "entered_at": 1,
                "rejection_reason": 1,
                "drop_reason": 1,
                "close_reason": 1,
                "error_text": 1,
            },
        )
        for row in cursor:
            status = (row.get("status") or "").lower().strip()
            setup = row.get("setup_variant") or row.get("setup_type") or "unknown"
            if status in ACCEPTED_STATUSES:
                accepted += 1
                by_setup[setup]["accepted"] += 1
                continue
            if status.startswith("rejected") or status == "dropped":
                # Pull the reason from the most specific field available.
                raw_reason = (
                    row.get("rejection_reason")
                    or row.get("drop_reason")
                    or row.get("error_text")
                    or status
                )
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
        logger.warning(f"[rejection-analytics] bot_trades read failed: {exc}")

    return {
        "accepted": accepted,
        "rejected_by_reason": rejected_by_reason,
        "by_setup": dict(by_setup),
        "recent_rejections": recent,
    }


def _aggregate_trade_drops(
    db, start_utc: datetime, end_utc: datetime,
) -> Dict[str, Any]:
    """Walk `trade_drops` (silent gate drops) for the day."""
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
                # Fall back to gate name as the reason if it normalises.
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
        logger.warning(f"[rejection-analytics] trade_drops read failed: {exc}")

    return {
        "rejected_by_reason": rejected_by_reason,
        "by_setup": dict(by_setup),
        "recent_rejections": recent,
    }


def _compose_response(
    trading_date_et: str,
    bot_agg: Dict[str, Any],
    drops_agg: Dict[str, Any],
) -> Dict[str, Any]:
    accepted = int(bot_agg["accepted"])
    # Merge counters
    merged: Counter = Counter()
    merged.update(bot_agg["rejected_by_reason"])
    merged.update(drops_agg["rejected_by_reason"])

    # Split into category buckets.
    by_category: Dict[str, int] = {
        CAT_SCANNER_QUALITY: 0,
        CAT_BROKER: 0,
        CAT_POLICY: 0,
        CAT_OTHER: 0,
    }
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

    # Merge by-setup
    by_setup: Dict[str, Dict[str, int]] = {}
    for src in (bot_agg["by_setup"], drops_agg["by_setup"]):
        for setup, counts in src.items():
            slot = by_setup.setdefault(setup, {"accepted": 0, "rejected": 0})
            slot["accepted"] += counts.get("accepted", 0)
            slot["rejected"] += counts.get("rejected", 0)

    # Merge + cap recent rejections (sorted by ts descending if available)
    all_recent = list(bot_agg["recent_rejections"]) + list(drops_agg["recent_rejections"])
    def _ts_key(r):
        return r.get("ts") or ""
    all_recent.sort(key=_ts_key, reverse=True)
    recent_rejections = all_recent[:25]

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
        "recent_rejections": recent_rejections,
    }


# ── HTTP route ──────────────────────────────────────────────────────────


@router.get("/rejection-analytics")
def rejection_analytics(date: Optional[str] = None) -> Dict[str, Any]:
    """Daily rejection breakdown + Scanner Quality Score.

    Args:
        date: ET trading date in `YYYY-MM-DD`. Defaults to today (ET).

    See module docstring for the full response shape.
    """
    trading_date, start_utc, end_utc = _et_day_window(date)
    db = _get_db()
    if db is None:
        # Empty (degraded) response — still 200 so the UI can render a
        # "no data yet" state instead of erroring out.
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
