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
            # v19.31.13 — surface trade_type so the Day Tape rows can
            # render PAPER / LIVE / SHADOW / UNKNOWN chips and the
            # operator can never confuse modes when journaling.
            "trade_type": t.get("trade_type") or "unknown",
            "account_id_at_fill": t.get("account_id_at_fill"),
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
        "setup_type", "setup_variant", "trade_style", "trade_type",
        "account_id_at_fill", "executed_at", "trade_id",
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

        # v19.31.13 — surface dominant trade_type per symbol so the
        # forensics row can show a PAPER/LIVE/SHADOW/UNKNOWN chip.
        # When a symbol has rows of mixed types (paper-then-live across
        # an account flip), report "mixed" so the operator notices.
        type_set = {(r.get("trade_type") or "unknown") for r in rows}
        if not type_set:
            dominant_type = "unknown"
        elif len(type_set) == 1:
            dominant_type = next(iter(type_set))
        else:
            # Filter out unknown when other concrete types exist.
            non_unknown = type_set - {"unknown"}
            dominant_type = (
                "mixed" if len(non_unknown) > 1
                else (next(iter(non_unknown)) if non_unknown else "unknown")
            )

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
            "trade_type": dominant_type,
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


async def _recalc_realized_pnl_for_symbol(
    db, symbol: str, days: int = 7,
) -> Dict[str, Any]:
    """v19.31.13 — Internal helper extracted from /recalc-realized-pnl
    so the new auto-recalc background task can reuse the exact same
    apportion-by-shares logic.
    """
    symbol_u = (symbol or "").upper()
    if not symbol_u:
        return {"success": False, "error": "symbol required"}

    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    cutoff_iso = (_dt.now(_tz.utc) - _td(days=days)).isoformat()

    # 1. Pull IB realizedPNL.
    ib_realized = 0.0
    try:
        snap = db["ib_live_snapshot"].find_one({"_id": "current"}, {"_id": 0})
        if snap:
            for p in snap.get("positions", []) or []:
                if (p.get("symbol") or "").upper() == symbol_u:
                    ib_realized = float(
                        p.get("realizedPNL") or p.get("realized_pnl") or 0
                    )
                    break
    except Exception as e:
        logger.warning(f"recalc helper: ib snapshot read failed: {e}")

    if abs(ib_realized) < 0.005:
        return {
            "success": True, "symbol": symbol_u,
            "ib_realized_pnl": 0.0, "claimed": 0.0,
            "rows_updated": [], "rows_skipped": [],
            "note": "IB shows no realized PnL for this symbol — nothing to claim.",
        }

    try:
        rows = list(db["bot_trades"].find(
            {
                "symbol": symbol_u, "status": "closed",
                "$or": [
                    {"closed_at": {"$gte": cutoff_iso}},
                    {"closed_at": None, "executed_at": {"$gte": cutoff_iso}},
                ],
            },
            {"_id": 0},
        ))
    except Exception as e:
        return {"success": False, "error": f"bot_trades read failed: {e}"}

    candidates = [r for r in rows if not (r.get("realized_pnl") or 0)]
    if not candidates:
        return {
            "success": True, "symbol": symbol_u,
            "ib_realized_pnl": round(ib_realized, 2), "claimed": 0.0,
            "rows_updated": [], "rows_skipped": [
                {"trade_id": str(r.get("id") or r.get("trade_id")),
                 "reason": "already has realized_pnl"} for r in rows
            ],
            "note": "All closed rows already have realized_pnl populated.",
        }

    total_shares = sum(int(r.get("shares") or 0) for r in candidates) or 1
    rows_updated: List[Dict[str, Any]] = []
    rows_skipped: List[Dict[str, Any]] = []
    total_claimed = 0.0
    for r in candidates:
        tid = str(r.get("id") or r.get("trade_id") or "")
        if not tid:
            rows_skipped.append({"trade_id": "?", "reason": "no trade id"})
            continue
        share_fraction = (int(r.get("shares") or 0)) / total_shares
        claimed_pnl = round(ib_realized * share_fraction, 2)
        if claimed_pnl == 0:
            rows_skipped.append({"trade_id": tid, "reason": "apportioned to zero"})
            continue
        try:
            res = db["bot_trades"].update_one(
                {"id": tid, "status": "closed", "$or": [
                    {"realized_pnl": 0}, {"realized_pnl": None},
                    {"realized_pnl": {"$exists": False}},
                ]},
                {"$set": {
                    "realized_pnl": claimed_pnl,
                    "realized_pnl_recalc_source": "ib_snapshot_v19_31_12",
                    "realized_pnl_recalc_at": _dt.now(_tz.utc).isoformat(),
                }},
            )
            if res.matched_count > 0:
                rows_updated.append({"trade_id": tid, "claimed_pnl": claimed_pnl})
                total_claimed += claimed_pnl
            else:
                rows_skipped.append({"trade_id": tid, "reason": "row no longer matched"})
        except Exception as e:
            rows_skipped.append({"trade_id": tid, "reason": f"write failed: {e}"})

    return {
        "success": True, "symbol": symbol_u,
        "ib_realized_pnl": round(ib_realized, 2),
        "claimed": round(total_claimed, 2),
        "rows_updated": rows_updated, "rows_skipped": rows_skipped,
    }


@router.post("/recalc-realized-pnl/{symbol}")
async def recalc_realized_pnl(symbol: str, days: int = Query(7, ge=1, le=30)):
    """v19.31.12 — Retroactive backfill (now a thin wrapper around
    `_recalc_realized_pnl_for_symbol` so the auto-recalc background
    task in TradingBotService.start() can reuse the same logic)."""
    if _db is None:
        raise HTTPException(status_code=503, detail="db not initialised")
    if not (symbol or "").strip():
        raise HTTPException(status_code=400, detail="symbol required")
    return await _recalc_realized_pnl_for_symbol(_db, symbol, days=days)



# ─── v19.31.13 — Shadow Decisions tab ────────────────────────────────


@router.get("/shadow-decisions")
async def get_shadow_decisions(
    days: int = Query(1, ge=1, le=30),
    symbol: Optional[str] = Query(None, max_length=10),
    only_executed: bool = Query(False),
    only_passed: bool = Query(False),
    limit: int = Query(500, ge=1, le=2000),
):
    """v19.31.13 — Lists rows from the `shadow_decisions` Mongo
    collection with light per-row aggregation so the V5 Diagnostics →
    Shadow Decisions sub-tab can render a sortable table.

    A "shadow decision" is the AI council's verdict on an alert,
    logged regardless of whether the bot fired. When the bot DID fire,
    `was_executed=True` and `trade_id` references the corresponding
    `bot_trades` row. When it didn't, the shadow row is the only
    record of the decision — useful for the operator to see "what
    would have happened" and grade the AI council's calibration.

    Returns rows + a small summary (counts by combined_recommendation,
    win-rate among executed, would-have-pnl among non-executed).
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="db not initialised")

    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    now_utc = _dt.now(_tz.utc)
    cutoff_iso = (now_utc - _td(days=days)).isoformat()

    query: Dict[str, Any] = {"trigger_time": {"$gte": cutoff_iso}}
    if symbol and isinstance(symbol, str):
        query["symbol"] = symbol.upper()
    if only_executed is True:
        query["was_executed"] = True
    if only_passed is True:
        query["combined_recommendation"] = {"$in": ["proceed", "PROCEED", "Proceed"]}

    try:
        cursor = _db["shadow_decisions"].find(
            query,
            {"_id": 0},
            sort=[("trigger_time", -1)],
            limit=limit,
        )
        raw = list(cursor)
    except Exception as e:
        logger.warning(f"shadow-decisions read failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    out: List[Dict[str, Any]] = []
    by_rec: Dict[str, int] = {}
    executed_count = 0
    executed_wins = 0
    executed_pnl_sum = 0.0
    not_executed_count = 0
    would_pnl_sum = 0.0
    for d in raw:
        rec = (d.get("combined_recommendation") or "").lower() or "unknown"
        by_rec[rec] = by_rec.get(rec, 0) + 1

        debate = d.get("debate_result") or {}
        risk = d.get("risk_assessment") or {}
        ts = d.get("timeseries_forecast") or {}

        was_exec = bool(d.get("was_executed"))
        actual_outcome = d.get("actual_outcome") or ""
        would_pnl = float(d.get("would_have_pnl") or 0)
        would_r = float(d.get("would_have_r") or 0)

        if was_exec:
            executed_count += 1
            # Use real outcome when present; otherwise use would_have_pnl
            # which the executed branch also stamps post-fill.
            pnl_for_summary = would_pnl
            if pnl_for_summary > 0:
                executed_wins += 1
            executed_pnl_sum += pnl_for_summary
        else:
            not_executed_count += 1
            would_pnl_sum += would_pnl

        out.append({
            "id": d.get("id"),
            "symbol": d.get("symbol"),
            "trigger_type": d.get("trigger_type"),
            "trigger_time": d.get("trigger_time"),
            "price_at_decision": d.get("price_at_decision"),
            "market_regime": d.get("market_regime"),
            "combined_recommendation": d.get("combined_recommendation"),
            "confidence_score": d.get("confidence_score"),
            "reasoning": d.get("reasoning") or "",
            "was_executed": was_exec,
            "execution_reason": d.get("execution_reason"),
            "trade_id": d.get("trade_id"),
            "would_have_pnl": round(would_pnl, 2),
            "would_have_r": round(would_r, 3) if would_r else None,
            "actual_outcome": actual_outcome,
            "outcome_tracked": bool(d.get("outcome_tracked")),
            "modules_used": d.get("modules_used") or [],
            # Per-module compact summary so the operator can spot bias
            # without expanding the full debate_result / risk row.
            "debate_winner": debate.get("winner"),
            "debate_bull_score": debate.get("bull_score"),
            "debate_bear_score": debate.get("bear_score"),
            "risk_recommendation": risk.get("recommendation"),
            "risk_score": risk.get("risk_score"),
            "ts_direction": ts.get("direction"),
            "ts_probability": ts.get("probability"),
        })

    summary = {
        "total": len(out),
        "by_recommendation": by_rec,
        "executed_count": executed_count,
        "executed_wins": executed_wins,
        "executed_win_rate": (
            round(100.0 * executed_wins / executed_count, 1)
            if executed_count else None
        ),
        "executed_pnl_sum": round(executed_pnl_sum, 2),
        "not_executed_count": not_executed_count,
        "not_executed_would_pnl_sum": round(would_pnl_sum, 2),
        # Divergence sign — positive means "the trades you didn't take
        # would have been profitable in aggregate, you may be too
        # conservative". Negative means "the AI's pass calls were
        # correct in aggregate".
        "divergence_signal": (
            "ai_too_conservative" if would_pnl_sum > 250
            else "ai_too_aggressive" if would_pnl_sum < -250
            else "balanced"
        ),
    }

    return {
        "success": True,
        "days": days,
        "from_iso": cutoff_iso,
        "to_iso": now_utc.isoformat(),
        "rows": out,
        "summary": summary,
    }


@router.get("/shadow-decisions.csv", response_class=PlainTextResponse)
async def get_shadow_decisions_csv(
    days: int = Query(1, ge=1, le=30),
    symbol: Optional[str] = Query(None, max_length=10),
    only_executed: bool = Query(False),
    only_passed: bool = Query(False),
) -> str:
    """v19.31.13 — CSV mirror of /shadow-decisions for journaling."""
    payload = await get_shadow_decisions(
        days=days, symbol=symbol,
        only_executed=only_executed, only_passed=only_passed,
        limit=2000,
    )
    rows = payload.get("rows", [])
    headers = [
        "trigger_time", "symbol", "combined_recommendation",
        "confidence_score", "was_executed", "trade_id",
        "would_have_pnl", "would_have_r", "actual_outcome",
        "debate_winner", "risk_recommendation", "ts_direction",
        "price_at_decision", "market_regime", "execution_reason",
        "id",
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



# ─── v19.34.3 (2026-05-04) — Forensic Orphan Origin ──────────────────


@router.get("/orphan-origin/{symbol}")
async def get_orphan_origin(
    symbol: str,
    days: int = Query(7, ge=1, le=90),
):
    """v19.34.3 — Forensic backfill report for a reconciled IB orphan.

    Operator's "where did this position come from?" question. Walks
    every available history source for a single symbol over the last
    N days and assembles a single-page report:

    * `bot_trades` — every row this symbol has had (open, closed, swept,
      reconciled). Lets the operator spot a prior session's leftover.
    * `bot_trades_reset_log` — morning resets that touched this symbol.
    * `sentcom_thoughts` — last 50 events: rejections, evaluations,
      reconcile events, sweep events, manual fills.
    * `ib_live_snapshot.history` — when the position first appeared on
      the IB pusher snapshot (when persisted; falls back to "current
      only" when history isn't being saved).
    * `shadow_decisions` — AI council verdicts on this symbol so the
      operator can see what the bot WOULD HAVE DONE if asked.

    Output is shaped for the V5 Diagnostics → Orphan Origin tab and
    designed to answer "should I close this position manually?".
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="db not initialised")

    sym_u = (symbol or "").strip().upper()
    if not sym_u:
        raise HTTPException(status_code=400, detail="symbol required")

    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    now_utc = _dt.now(_tz.utc)
    cutoff = (now_utc - _td(days=days)).isoformat()

    out: Dict[str, Any] = {
        "success": True,
        "symbol": sym_u,
        "days": days,
        "from_iso": cutoff,
        "to_iso": now_utc.isoformat(),
    }

    # 1) bot_trades history
    try:
        bt_rows = list(_db["bot_trades"].find(
            {"symbol": sym_u, "executed_at": {"$gte": cutoff}},
            {"_id": 0},
            sort=[("executed_at", -1)],
            limit=50,
        ))
    except Exception as e:
        bt_rows = []
        logger.debug(f"orphan-origin bot_trades lookup failed: {e}")
    out["bot_trades"] = [
        {
            "id": r.get("id"),
            "executed_at": r.get("executed_at"),
            "closed_at": r.get("closed_at"),
            "status": r.get("status"),
            "direction": r.get("direction"),
            "shares": r.get("shares"),
            "remaining_shares": r.get("remaining_shares"),
            "fill_price": r.get("fill_price") or r.get("entry_price"),
            "stop_price": r.get("stop_price"),
            "target_prices": r.get("target_prices") or [],
            "realized_pnl": r.get("realized_pnl"),
            "close_reason": r.get("close_reason"),
            "setup_type": r.get("setup_type"),
            "trade_type": r.get("trade_type"),
            "entered_by": r.get("entered_by"),
            "synthetic_source": r.get("synthetic_source"),
            "prior_verdict_conflict": r.get("prior_verdict_conflict"),
            "notes": r.get("notes"),
        }
        for r in bt_rows
    ]
    out["bot_trades_count"] = len(bt_rows)

    # 2) bot_trades_reset_log — what reset events touched this symbol
    try:
        reset_rows = list(_db["bot_trades_reset_log"].find(
            {"as_of": {"$gte": cutoff}},
            {"_id": 0},
            sort=[("as_of", -1)],
            limit=10,
        ))
        # Filter to events that mention this symbol.
        reset_touched = []
        for r in reset_rows:
            affected = r.get("affected") or []
            survivors = r.get("survivors") or []
            for source, items in (("affected", affected), ("survivors", survivors)):
                for item in items:
                    if isinstance(item, dict) and (item.get("symbol") or "").upper() == sym_u:
                        reset_touched.append({
                            "as_of": r.get("as_of"),
                            "source": source,
                            "trade_id": item.get("trade_id"),
                            "direction": item.get("direction"),
                            "shares": item.get("shares"),
                            "force": r.get("force"),
                            "ib_snapshot_age_s": r.get("ib_snapshot_age_s"),
                        })
                    elif isinstance(item, str) and item.upper() == sym_u:
                        reset_touched.append({
                            "as_of": r.get("as_of"),
                            "source": source,
                            "force": r.get("force"),
                        })
    except Exception as e:
        reset_touched = []
        logger.debug(f"orphan-origin reset-log lookup failed: {e}")
    out["reset_log_touched"] = reset_touched

    # 3) sentcom_thoughts — full event timeline (rejections, fires,
    # reconciles, sweeps, evals, warnings)
    try:
        thoughts = list(_db["sentcom_thoughts"].find(
            {"symbol": sym_u, "timestamp": {"$gte": cutoff}},
            {"_id": 0},
            sort=[("timestamp", -1)],
            limit=80,
        ))
    except Exception as e:
        thoughts = []
        logger.debug(f"orphan-origin thoughts lookup failed: {e}")
    out["thoughts"] = [
        {
            "timestamp": t.get("timestamp"),
            "kind": t.get("kind"),
            "event": t.get("event"),
            "text": t.get("text"),
            "severity": t.get("severity"),
            "metadata": {
                k: v for k, v in (t.get("metadata") or {}).items()
                if k in (
                    "setup_type", "direction", "reason_code",
                    "rr_ratio", "min_required",
                    "entry_price", "stop_price", "primary_target",
                    "trade_id", "trade_type",
                )
            },
        }
        for t in thoughts
    ]

    # 4) shadow_decisions — what the AI council thought
    try:
        shadow_rows = list(_db["shadow_decisions"].find(
            {"symbol": sym_u, "trigger_time": {"$gte": cutoff}},
            {"_id": 0},
            sort=[("trigger_time", -1)],
            limit=20,
        ))
    except Exception as e:
        shadow_rows = []
        logger.debug(f"orphan-origin shadow lookup failed: {e}")
    out["shadow_decisions"] = [
        {
            "trigger_time": s.get("trigger_time"),
            "trigger_type": s.get("trigger_type"),
            "combined_recommendation": s.get("combined_recommendation"),
            "confidence_score": s.get("confidence_score"),
            "was_executed": s.get("was_executed"),
            "would_have_pnl": s.get("would_have_pnl"),
            "would_have_r": s.get("would_have_r"),
            "actual_outcome": s.get("actual_outcome"),
        }
        for s in shadow_rows
    ]

    # 5) Current IB position snapshot for context.
    try:
        from routers.ib import _pushed_ib_data
        for p in (_pushed_ib_data.get("positions") or []):
            if (p.get("symbol") or "").upper() == sym_u:
                out["ib_current_position"] = {
                    "symbol": sym_u,
                    "qty": float(p.get("position", p.get("qty", 0)) or 0),
                    "avg_cost": float(p.get("avgCost", p.get("avg_cost", 0)) or 0),
                    "market_price": float(p.get("marketPrice", p.get("market_price", 0)) or 0),
                }
                break
    except Exception:
        pass

    # 6) Verdict summary — count rejections vs evaluations vs fires
    # over the window. Helps the operator answer "was the bot agreeing
    # with this position?" at a glance.
    rej_count = sum(
        1 for t in thoughts if (t.get("kind") or "") == "rejection"
    )
    fire_count = sum(
        1 for t in thoughts
        if (t.get("event") or "").startswith("trade_executed")
    )
    eval_count = sum(
        1 for t in thoughts
        if (t.get("event") or "") == "evaluating_setup"
    )
    reconcile_count = sum(
        1 for t in thoughts
        if "reconcile" in (t.get("event") or "")
    )
    out["verdict_summary"] = {
        "rejections": rej_count,
        "evaluations": eval_count,
        "fires": fire_count,
        "reconciles": reconcile_count,
        # Heuristic verdict:
        #   "bot_disagreed"  — evaluations > 0 AND ≥80% were rejections
        #   "bot_agreed"     — fires > 0
        #   "no_signal"      — no evals, no fires (manual or carryover)
        "verdict": (
            "bot_disagreed" if eval_count > 0 and (rej_count / max(1, eval_count)) >= 0.8 and fire_count == 0
            else "bot_agreed" if fire_count > 0
            else "no_signal"
        ),
    }

    return out
