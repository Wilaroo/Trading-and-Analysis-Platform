"""
integrity_router — v333 System Integrity briefing + feed
=========================================================
Operator-approved (2026-06-12): "morning report" infrastructure inside the
briefings panel + regime demotions auditable with before/after stops.

GET /api/integrity/morning-report
    Session scorecard with PASS/WARN/FAIL checks proving this week's
    fixes are holding:
      • scalps fired today (v328 unblocked the blackout that zeroed them)
      • data uptime — % of RTH minutes with ≥1 ingest write (pusher
        liveness; the 2026-06-12 blackout would read ~0%)
      • snapshot freshness — age of the newest ingest write
      • daily-bar leak — in-progress daily bars for today (v328: must be 0
        before the close)
      • RTH backfill gate — deep requests currently held (v328)
      • M0 ladder — trades carrying multi-leg OCA ladders + legs filled
      • regime — current regime + demotions today (v332)
      • integrity events today by severity

GET /api/integrity/feed?limit=30
    Recent state_integrity_events (newest first) PLUS per-trade regime
    demotion stop moves (old → new stop) pulled from
    bot_trades.trailing_stop_config.stop_adjustments, merged into one
    auditable timeline.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrity", tags=["integrity"])

_db = None
ET = ZoneInfo("America/New_York")


def init_integrity_router(db) -> None:
    global _db
    _db = db


def _today_bounds():
    now_et = datetime.now(ET)
    open_et = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    close_et = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    midnight_et = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
    return now_et, open_et, close_et, midnight_et


def _parse_ts(v) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _check(name: str, status: str, value: str, detail: str = "") -> Dict[str, Any]:
    return {"name": name, "status": status, "value": value, "detail": detail}


def _sync_morning_report() -> Dict[str, Any]:
    now_et, open_et, close_et, midnight_et = _today_bounds()
    today_str = now_et.strftime("%Y-%m-%d")
    midnight_utc_iso = midnight_et.astimezone(timezone.utc).isoformat()
    open_utc_iso = open_et.astimezone(timezone.utc).isoformat()
    checks: List[Dict[str, Any]] = []

    # ── 1. trades fired today by style ───────────────────────────────────
    style_counts: Dict[str, int] = {}
    for doc in _db["bot_trades"].find(
        {"created_at": {"$gte": midnight_utc_iso}},
        {"_id": 0, "trade_style": 1},
    ):
        s = doc.get("trade_style") or "?"
        style_counts[s] = style_counts.get(s, 0) + 1
    scalps = style_counts.get("scalp", 0)
    total_trades = sum(style_counts.values())
    in_session = open_et <= now_et <= close_et and now_et.weekday() < 5
    if not in_session and total_trades == 0:
        checks.append(_check("scalps_fired", "info", "market closed",
                             "no session today / pre-open"))
    else:
        checks.append(_check(
            "scalps_fired",
            "pass" if scalps > 0 else ("warn" if in_session and now_et > open_et + timedelta(hours=1) else "info"),
            f"{scalps} scalps / {total_trades} total",
            " · ".join(f"{k}:{v}" for k, v in sorted(style_counts.items())) or "no entries yet",
        ))

    # ── 2. data uptime (distinct ingest minutes vs RTH minutes elapsed) ──
    minutes_seen = set()
    newest_ingest: Optional[datetime] = None
    for doc in _db["ib_historical_data"].find(
        {"collected_at": {"$gte": open_utc_iso}},
        {"_id": 0, "collected_at": 1},
    ):
        ts = _parse_ts(doc.get("collected_at"))
        if not ts:
            continue
        if newest_ingest is None or ts > newest_ingest:
            newest_ingest = ts
        ts_et = ts.astimezone(ET)
        mins = ts_et.hour * 60 + ts_et.minute
        if 9 * 60 + 30 <= mins <= 16 * 60:
            minutes_seen.add(ts_et.strftime("%H:%M"))
    elapsed_min = max(0, int((min(now_et, close_et) - open_et).total_seconds() // 60))
    if elapsed_min <= 0 or now_et.weekday() >= 5:
        checks.append(_check("data_uptime", "info", "—", "outside RTH"))
        uptime_pct = None
    else:
        uptime_pct = round(100.0 * len(minutes_seen) / max(1, elapsed_min), 1)
        checks.append(_check(
            "data_uptime",
            "pass" if uptime_pct >= 80 else ("warn" if uptime_pct >= 40 else "fail"),
            f"{uptime_pct}%",
            f"{len(minutes_seen)}/{elapsed_min} RTH minutes with ingest",
        ))

    # ── 3. snapshot freshness ─────────────────────────────────────────────
    if newest_ingest is None:
        newest_doc = _db["ib_historical_data"].find_one(
            {}, {"_id": 0, "collected_at": 1}, sort=[("collected_at", -1)])
        newest_ingest = _parse_ts((newest_doc or {}).get("collected_at"))
    if newest_ingest:
        age_s = int((datetime.now(timezone.utc) - newest_ingest).total_seconds())
        if in_session:
            status = "pass" if age_s <= 120 else ("warn" if age_s <= 600 else "fail")
        else:
            status = "info"
        checks.append(_check("ingest_freshness", status,
                             f"{age_s}s ago" if age_s < 3600 else f"{age_s // 3600}h ago",
                             "newest ib_historical_data write"))
    else:
        checks.append(_check("ingest_freshness", "fail", "none", "no ingest rows found"))

    # ── 4. daily-bar leak (v328 must hold) ────────────────────────────────
    leak_n = _db["ib_historical_data"].count_documents(
        {"bar_size": "1 day", "date": {"$regex": f"^{today_str}"}})
    if now_et >= close_et.replace(minute=15):
        checks.append(_check("daily_bar_leak", "info", f"{leak_n} today",
                             "post-close — today's daily bar is legitimately final"))
    else:
        checks.append(_check("daily_bar_leak", "pass" if leak_n == 0 else "fail",
                             f"{leak_n} leaked",
                             "in-progress daily bars for today (v328 guard: must be 0)"))

    # ── 5. RTH backfill gate ──────────────────────────────────────────────
    try:
        from services.historical_data_queue_service import (
            _rth_backfill_gate_active, _deep_request_exclusion)
        gate_on = _rth_backfill_gate_active()
        deep_held = _db["historical_data_requests"].count_documents(
            {"status": "pending", "$nor": [{"$and": _deep_request_exclusion()}]})
        checks.append(_check(
            "backfill_gate", "pass" if (gate_on or not in_session) else "warn",
            "ACTIVE" if gate_on else "off",
            f"{deep_held} deep request(s) held until after close" if gate_on
            else f"{deep_held} deep request(s) pending (gate off)",
        ))
    except Exception as e:
        checks.append(_check("backfill_gate", "warn", "unknown", str(e)[:80]))

    # ── 6. M0 ladder activity today ───────────────────────────────────────
    ladder_trades = 0
    legs_filled = 0
    for doc in _db["bot_trades"].find(
        {"created_at": {"$gte": midnight_utc_iso},
         "scale_out_config.m0_legs": {"$exists": True, "$ne": []}},
        {"_id": 0, "scale_out_config.m0_legs.status": 1},
    ):
        ladder_trades += 1
        for leg in (doc.get("scale_out_config") or {}).get("m0_legs", []):
            if str(leg.get("status")) == "filled":
                legs_filled += 1
    checks.append(_check(
        "m0_ladder", "pass" if legs_filled > 0 else "info",
        f"{ladder_trades} laddered · {legs_filled} legs filled",
        "multi-leg OCA scale-out validation (M0a-d)",
    ))

    # ── 7. regime + demotions today (v332) ───────────────────────────────
    demotions_today = list(_db["state_integrity_events"].find(
        {"event": "regime_demotion", "ts": {"$gte": midnight_utc_iso}},
        {"_id": 0}))
    regime_doc = _db["regime_snapshots"].find_one({}, sort=[("timestamp", -1)]) or {}
    regime = regime_doc.get("state") or regime_doc.get("regime") or "?"
    demo_summary = ""
    if demotions_today:
        last = demotions_today[-1]
        demo_summary = (f"{last.get('from_regime')}→{last.get('to_regime')} "
                        f"stats={last.get('stats')}")
    checks.append(_check(
        "regime", "info", f"{regime} · {len(demotions_today)} demotion(s) today",
        demo_summary or "no demotion passes today"))

    # ── 8. integrity events today by severity ────────────────────────────
    sev: Dict[str, int] = {}
    for doc in _db["state_integrity_events"].find(
        {"ts": {"$gte": midnight_utc_iso}}, {"_id": 0, "severity": 1}):
        s = doc.get("severity") or "?"
        sev[s] = sev.get(s, 0) + 1
    n_events = sum(sev.values())
    checks.append(_check(
        "integrity_events",
        "pass" if sev.get("high", 0) == 0 else "warn",
        f"{n_events} today",
        " · ".join(f"{k}:{v}" for k, v in sorted(sev.items())) or "clean",
    ))

    n_pass = sum(1 for c in checks if c["status"] == "pass")
    n_fail = sum(1 for c in checks if c["status"] == "fail")
    n_warn = sum(1 for c in checks if c["status"] == "warn")
    scored = sum(1 for c in checks if c["status"] in ("pass", "warn", "fail"))
    verdict = "FAIL" if n_fail else ("WARN" if n_warn else "PASS")

    return {
        "success": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session_date": today_str,
        "in_session": in_session,
        "verdict": verdict,
        "score": f"{n_pass}/{scored}",
        "checks": checks,
        "uptime_pct": uptime_pct,
        "scalps_today": scalps,
        "trades_today": total_trades,
        "leaked_daily_bars": leak_n,
        "demotions_today": len(demotions_today),
    }


def _sync_feed(limit: int) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []

    for doc in _db["state_integrity_events"].find(
        {}, {"_id": 0}).sort("ts", -1).limit(limit):
        ev = doc.get("event") or "?"
        if ev == "regime_demotion":
            stats = doc.get("stats") or {}
            text = (f"Regime {doc.get('from_regime')} → {doc.get('to_regime')} "
                    f"confirmed — {stats.get('be', 0)} to BE, "
                    f"{stats.get('tightened', 0)} tightened"
                    + (f" [{', '.join(doc.get('details') or [])}]"
                       if doc.get("details") else ""))
        else:
            text = doc.get("text") or doc.get("detail") or ev
        items.append({"ts": doc.get("ts"), "event": ev,
                      "severity": doc.get("severity") or "info",
                      "symbol": doc.get("symbol"), "text": text})

    # merge per-trade regime-demotion stop moves (old → new, auditable)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    for doc in _db["bot_trades"].find(
        {"trailing_stop_config.stop_adjustments.reason":
            {"$regex": "^regime_demotion"},
         "created_at": {"$gte": cutoff}},
        {"_id": 0, "symbol": 1, "trailing_stop_config.stop_adjustments": 1},
    ).limit(50):
        for adj in (doc.get("trailing_stop_config") or {}).get("stop_adjustments", []):
            if not str(adj.get("reason", "")).startswith("regime_demotion"):
                continue
            items.append({
                "ts": adj.get("timestamp"),
                "event": "regime_demotion_stop_move",
                "severity": "medium",
                "symbol": doc.get("symbol"),
                "text": (f"{doc.get('symbol')} stop ${adj.get('old_stop'):.2f} → "
                         f"${adj.get('new_stop'):.2f} ({adj.get('reason')}) "
                         f"@ px ${adj.get('price_at_adjustment') or 0:.2f}"),
            })

    items.sort(key=lambda x: str(x.get("ts") or ""), reverse=True)
    return {"success": True, "count": len(items[:limit]), "items": items[:limit]}


@router.get("/morning-report")
async def get_morning_report():
    if _db is None:
        return {"success": False, "error": "db not initialised"}
    try:
        return await asyncio.to_thread(_sync_morning_report)
    except Exception as e:
        logger.error(f"morning-report failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)[:200]}


@router.get("/feed")
async def get_integrity_feed(limit: int = Query(30, ge=1, le=200)):
    if _db is None:
        return {"success": False, "error": "db not initialised"}
    try:
        return await asyncio.to_thread(_sync_feed, limit)
    except Exception as e:
        logger.error(f"integrity feed failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)[:200]}
