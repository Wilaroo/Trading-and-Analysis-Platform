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


# ─── v19.31.11 — Trade Forensics ─────────────────────────────────────


def _classify_symbol_verdict(*, bot_rows, ib_pos, ib_realized, sweep_events,
                             reconcile_events, reset_touched):
    """v19.31.11 — Verdict classifier for the trade-forensics endpoint.

    Returns (verdict, explanation). Order is intentional — first match
    wins, so the most specific verdict surfaces first.

    Inputs
    ------
    bot_rows         list of bot_trades docs for this symbol in window
    ib_pos           float — current IB position (0 if flat)
    ib_realized      float — IB realizedPNL today (0 if no closes)
    sweep_events     list of sentcom_thought dicts where event matches
                     phantom_v19_27_leftover_swept or
                     phantom_v19_31_oca_closed_swept
    reconcile_events list of sentcom_thought dicts where event matches
                     auto_reconcile_at_boot (metadata.symbols includes
                     this symbol) or manual reconcile event
    reset_touched    bool — `bot_trades_reset_log.affected_ids`
                     references this symbol's trade_ids
    """
    # 1. Phantom-v31 OCA-closed-externally — most specific.
    if any(e.get("event") == "phantom_v19_31_oca_closed_swept" for e in sweep_events):
        return ("phantom_v31",
                "OCA bracket closed the position on IB; bot still tracked it "
                "until v19.31 sweep marked it closed.")

    # 2. Phantom-v27 0sh leftover.
    if any(e.get("event") == "phantom_v19_27_leftover_swept" for e in sweep_events):
        return ("phantom_v27",
                "Bot scaled to 0sh leftover, IB held nothing, v19.27 sweep "
                "cleaned the in-memory ghost.")

    # 3. Reset-orphaned — reset wiped a row but IB still held shares.
    #    (Pre-v19.31 survival guard could do this.)
    if reset_touched and abs(ib_pos) > 0.01:
        return ("reset_orphaned",
                "Morning reset script wiped this trade's row, but IB still "
                "held the position. Survival guard (v19.31.1) prevents this.")

    # 4. Auto-reconciled / operator-reconciled.
    if reconcile_events:
        return ("auto_reconciled",
                "Bot had no record of this position at boot; auto-reconcile "
                "(or operator's RECONCILE click) claimed it from IB.")

    # 5. Manual-or-external — IB has it but no bot row anywhere.
    if not bot_rows and abs(ib_pos) > 0.01:
        return ("manual_or_external",
                "IB position with no bot record and no reconcile event — "
                "external trade (TWS / upstream) the bot never owned.")

    # 6. Unexplained drift — both ledgers exist but PnL differs > $5.
    bot_total_realized = sum(
        float(r.get("realized_pnl") or r.get("net_pnl") or r.get("pnl") or 0)
        for r in bot_rows
        if (r.get("status") or "").lower() == "closed"
    )
    if bot_rows and abs(bot_total_realized - ib_realized) > 5.0:
        return ("unexplained_drift",
                f"Bot realized ${bot_total_realized:+.2f}, IB realized "
                f"${ib_realized:+.2f} (Δ ${bot_total_realized - ib_realized:+.2f}). "
                f"Investigate fill prices / commissions / partial closes.")

    # 7. Clean.
    if bot_rows:
        return ("clean",
                "Bot opened + closed; ledgers match within tolerance.")

    # 8. Fallback — no bot rows and no IB activity → ignore.
    return ("inactive",
            "No bot record and no IB activity for this symbol in window.")


@router.get("/trade-forensics")
async def get_trade_forensics(days: int = Query(1, ge=1, le=7)):
    """v19.31.11 — Joins bot_trades + ib_live_snapshot.current + recent
    sentcom_thoughts (sweep + reconcile events) + bot_trades_reset_log
    to produce a per-symbol forensic verdict for "what was real vs
    phantom" today.

    Verdicts:
      - clean: bot opened + closed; ledgers match.
      - phantom_v27: 0sh-leftover swept by v19.27 path.
      - phantom_v31: OCA-closed-externally swept by v19.31 path.
      - reset_orphaned: morning reset wiped row but IB still held.
      - auto_reconciled: bot had nothing, claimed via reconcile.
      - manual_or_external: IB has it, no bot trace at all.
      - unexplained_drift: both ledgers, PnL gap > $5.
      - inactive: no activity (filtered out of `symbols` list by default).
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="db not initialised")

    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    now_utc = _dt.now(_tz.utc)
    cutoff_iso = (now_utc - _td(days=days)).isoformat()

    # ── 1. bot_trades rows in window ────────────────────────────────
    try:
        bot_rows = list(_db["bot_trades"].find(
            {
                "$or": [
                    {"executed_at": {"$gte": cutoff_iso}},
                    {"created_at": {"$gte": cutoff_iso}},
                    {"closed_at": {"$gte": cutoff_iso}},
                ],
            },
            {"_id": 0},
        ))
    except Exception as e:
        logger.warning(f"forensics: bot_trades read failed: {e}")
        bot_rows = []

    # ── 2. ib_live_snapshot.current ─────────────────────────────────
    ib_by_symbol: Dict[str, Dict[str, Any]] = {}
    try:
        snap = _db["ib_live_snapshot"].find_one({"_id": "current"}, {"_id": 0})
        if snap:
            for p in snap.get("positions", []) or []:
                sym = (p.get("symbol") or "").upper()
                if not sym:
                    continue
                qty = float(p.get("position", p.get("qty", 0)) or 0)
                ib_by_symbol[sym] = {
                    "position": qty,
                    "realized_pnl": float(p.get("realizedPNL") or p.get("realized_pnl") or 0),
                    "unrealized_pnl": float(p.get("unrealizedPNL") or p.get("unrealized_pnl") or 0),
                    "avg_cost": float(p.get("avgCost") or p.get("avg_cost") or 0),
                    "market_price": float(p.get("marketPrice") or p.get("market_price") or 0),
                    "market_value": float(p.get("marketValue") or p.get("market_value") or 0),
                }
    except Exception as e:
        logger.warning(f"forensics: ib snapshot read failed: {e}")

    # ── 3. sentcom_thoughts — sweep + reconcile events in window ────
    sweep_events_by_symbol: Dict[str, list] = {}
    reconcile_events_by_symbol: Dict[str, list] = {}
    try:
        cur = _db["sentcom_thoughts"].find(
            {
                "timestamp": {"$gte": cutoff_iso},
                "$or": [
                    {"metadata.reason": {"$regex": "phantom|reconcile|oca_closed", "$options": "i"}},
                    {"metadata.event": {"$regex": "phantom|reconcile", "$options": "i"}},
                ],
            },
            {"_id": 0},
            sort=[("timestamp", 1)],
            limit=2000,
        )
        for e in cur:
            md = e.get("metadata") or {}
            evt = md.get("event") or e.get("kind") or ""
            sym = (e.get("symbol") or md.get("symbol") or "").upper()
            if not sym and "auto_reconcile" in evt.lower():
                # Boot-time auto-reconcile carries an array of symbols.
                for s in (md.get("symbols") or []):
                    s_up = (s or "").upper()
                    if s_up:
                        reconcile_events_by_symbol.setdefault(s_up, []).append({
                            "event": evt, "timestamp": e.get("timestamp"),
                            "metadata": md,
                        })
                continue
            if not sym:
                continue
            payload = {"event": evt, "timestamp": e.get("timestamp"),
                       "metadata": md, "content": e.get("content")}
            if "phantom" in evt.lower() or "phantom" in str(md.get("reason", "")).lower():
                sweep_events_by_symbol.setdefault(sym, []).append(payload)
            if "reconcile" in evt.lower() or "reconcile" in str(md.get("reason", "")).lower():
                reconcile_events_by_symbol.setdefault(sym, []).append(payload)
    except Exception as e:
        logger.warning(f"forensics: sweep/reconcile lookup failed: {e}")

    # ── 4. bot_trades_reset_log — which trade_ids were closed? ──────
    reset_trade_ids: set = set()
    try:
        cur = _db["bot_trades_reset_log"].find(
            {"timestamp": {"$gte": cutoff_iso}},
            {"_id": 0, "affected_ids": 1, "symbols": 1},
        )
        for r in cur:
            for tid in r.get("affected_ids") or []:
                reset_trade_ids.add(str(tid))
    except Exception as e:
        logger.debug(f"forensics: reset log read skipped: {e}")

    # ── 5. Merge per symbol ─────────────────────────────────────────
    symbols_seen = set()
    bot_by_symbol: Dict[str, list] = {}
    for r in bot_rows:
        sym = (r.get("symbol") or "").upper()
        if not sym:
            continue
        bot_by_symbol.setdefault(sym, []).append(r)
        symbols_seen.add(sym)
    for sym in ib_by_symbol:
        symbols_seen.add(sym)
    for sym in sweep_events_by_symbol:
        symbols_seen.add(sym)
    for sym in reconcile_events_by_symbol:
        symbols_seen.add(sym)

    out_symbols: List[Dict[str, Any]] = []
    by_verdict: Dict[str, int] = {}
    for sym in sorted(symbols_seen):
        rows = bot_by_symbol.get(sym) or []
        ib = ib_by_symbol.get(sym) or {"position": 0, "realized_pnl": 0,
                                        "unrealized_pnl": 0, "avg_cost": 0,
                                        "market_price": 0, "market_value": 0}
        sweeps = sweep_events_by_symbol.get(sym) or []
        recons = reconcile_events_by_symbol.get(sym) or []
        reset_touched = any(str(r.get("id") or r.get("trade_id")) in reset_trade_ids for r in rows)

        verdict, explanation = _classify_symbol_verdict(
            bot_rows=rows, ib_pos=ib["position"], ib_realized=ib["realized_pnl"],
            sweep_events=sweeps, reconcile_events=recons, reset_touched=reset_touched,
        )

        # Build event timeline merging bot_trades + sweeps + reconciles.
        timeline = []
        for r in rows:
            if r.get("executed_at"):
                timeline.append({
                    "time": r["executed_at"], "kind": "bot_executed",
                    "detail": f"{r.get('direction', '?')} {r.get('shares', '?')}sh @ {r.get('fill_price', r.get('entry_price', '?'))}",
                    "trade_id": r.get("id"),
                })
            if r.get("closed_at") and (r.get("status") or "").lower() == "closed":
                timeline.append({
                    "time": r["closed_at"], "kind": "bot_closed",
                    "detail": f"realized ${float(r.get('realized_pnl') or r.get('pnl') or 0):+.2f} reason={r.get('close_reason') or '?'}",
                    "trade_id": r.get("id"),
                })
        for e in sweeps:
            timeline.append({
                "time": e.get("timestamp"), "kind": e.get("event"),
                "detail": e.get("content") or e.get("metadata", {}).get("reason") or "?",
            })
        for e in recons:
            timeline.append({
                "time": e.get("timestamp"), "kind": e.get("event") or "reconcile",
                "detail": e.get("content") or e.get("metadata", {}).get("reason") or "?",
            })
        timeline.sort(key=lambda x: x.get("time") or "")

        bot_total_realized = sum(
            float(r.get("realized_pnl") or r.get("net_pnl") or r.get("pnl") or 0)
            for r in rows if (r.get("status") or "").lower() == "closed"
        )
        bot_open = [r for r in rows if (r.get("status") or "").lower() == "open"]
        bot_closed = [r for r in rows if (r.get("status") or "").lower() == "closed"]

        by_verdict[verdict] = by_verdict.get(verdict, 0) + 1

        # Skip 'inactive' rows from the response by default — operator's
        # forensic UI doesn't need empty rows for symbols just appearing
        # in a yesterday-ish IB snapshot with no activity today.
        if verdict == "inactive":
            continue

        out_symbols.append({
            "symbol": sym,
            "verdict": verdict,
            "explanation": explanation,
            "bot": {
                "trade_count": len(rows),
                "open_count": len(bot_open),
                "closed_count": len(bot_closed),
                "total_realized_pnl": round(bot_total_realized, 2),
                "first_executed_at": min(
                    [r.get("executed_at") for r in rows if r.get("executed_at")],
                    default=None,
                ),
                "last_closed_at": max(
                    [r.get("closed_at") for r in rows if r.get("closed_at")],
                    default=None,
                ),
            },
            "ib": {
                "current_position": ib["position"],
                "realized_pnl_today": round(ib["realized_pnl"], 2),
                "unrealized_pnl": round(ib["unrealized_pnl"], 2),
                "avg_cost": round(ib["avg_cost"], 2),
                "market_value": round(ib["market_value"], 2),
            },
            "drift_usd": round(bot_total_realized - ib["realized_pnl"], 2),
            "sweep_count": len(sweeps),
            "reconcile_count": len(recons),
            "reset_touched": reset_touched,
            "timeline": timeline,
        })

    return {
        "success": True,
        "days": days,
        "from_iso": cutoff_iso,
        "to_iso": now_utc.isoformat(),
        "symbols": out_symbols,
        "summary": {
            "total_symbols": len(out_symbols),
            "by_verdict": by_verdict,
        },
    }
