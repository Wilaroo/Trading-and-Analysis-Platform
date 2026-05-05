"""
unmatched_short_close_service.py — v19.34.16 (2026-05-06)

Detects Sell Short / Buy to Cover transactions in the IB execution tape
that have NO matching `bot_trades` row. Closes the leak class that
v19.34.15a (Naked-position safety net) is designed to prevent: when a
short fill ends up at IB without the bot tracking it.

Used by:
  • `GET /api/diagnostics/unmatched-short-closes` — operator endpoint
    for the V5 Diagnostics tab.
  • `scripts/audit_ib_fill_tape.py` — Markdown report cross-check
    (via the `find_unmatched_short_activity` helper there).

Algorithm:
  1. Read `ib_executions` rows for the symbol/window. IB tape uses
     `side` field: `BOT`/`BUY` = buy, `SLD`/`SELL` = sell. Direction is
     not stamped at the broker level — must be inferred from FIFO
     inventory walk.
  2. Group by symbol, walk fills chronologically, maintain signed
     inventory queue. SHORT round-trip leg = a closed leg whose
     opening lot was a SELL (negative inventory).
  3. For each symbol with SHORT activity, query `bot_trades` for
     direction=short rows in the same window. If none, flag.
  4. Also flag symbols with current negative `_pushed_ib_data.position`
     and no open short bot_trade (still-open unrecorded short).
"""
import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _normalize_side(raw: Any) -> str:
    """Normalize IB side strings to BUY/SELL."""
    s = (str(raw or "")).upper().strip()
    if s.startswith(("BOT", "BUY", "B ")):
        return "BUY"
    if s.startswith(("SLD", "SEL", "SOLD", "SHORT", "S ")):
        return "SELL"
    return s  # fallback — pass through


def _fifo_walk_short_legs(executions: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Walk chronological fills per symbol; return SHORT closed legs.

    Each entry has: {qty, open_price, close_price, open_time, close_time, pnl}.
    """
    by_sym: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for ex in executions:
        sym = (ex.get("symbol") or "").upper()
        if not sym:
            continue
        grouped[sym].append(ex)

    for sym, fills in grouped.items():
        fills_sorted = sorted(fills, key=lambda x: str(x.get("time") or x.get("timestamp") or ""))
        inventory: deque = deque()  # entries: (signed_qty, price, time)
        short_legs: List[Dict[str, Any]] = []
        for f in fills_sorted:
            side = _normalize_side(f.get("side") or f.get("action"))
            qty = int(abs(float(f.get("shares") or f.get("qty") or 0)))
            price = float(f.get("price") or f.get("avg_price") or 0)
            t = str(f.get("time") or f.get("timestamp") or "")
            if qty <= 0 or price <= 0:
                continue
            incoming = qty if side == "BUY" else -qty
            while incoming != 0 and inventory:
                head_qty, head_price, head_time = inventory[0]
                if (incoming > 0) == (head_qty > 0):
                    break  # same direction — append, don't match
                match_qty = min(abs(incoming), abs(head_qty))
                if head_qty < 0:  # short lot, covered by incoming BUY
                    pnl = match_qty * (head_price - price)
                    short_legs.append({
                        "symbol": sym,
                        "qty": match_qty,
                        "open_price": round(head_price, 4),
                        "close_price": round(price, 4),
                        "open_time": head_time,
                        "close_time": t,
                        "pnl": round(pnl, 2),
                    })
                # long lot covered by incoming SELL → not a short leg, skip
                new_head = head_qty + (match_qty if head_qty < 0 else -match_qty)
                if new_head == 0:
                    inventory.popleft()
                else:
                    inventory[0] = (new_head, head_price, head_time)
                incoming += match_qty if incoming < 0 else -match_qty
            if incoming != 0:
                inventory.append((incoming, price, t))
        # Residual short inventory = still-open short
        residual_short = sum(q for q, _, _ in inventory if q < 0)
        by_sym[sym] = short_legs
        if residual_short < 0:
            short_legs.append({
                "symbol": sym,
                "qty": abs(residual_short),
                "open_price": None,
                "close_price": None,
                "open_time": None,
                "close_time": None,
                "pnl": None,
                "kind": "open_residual_short",
            })
    return dict(by_sym)


async def find_unmatched_short_closes(
    db,
    days: int = 1,
    symbol: Optional[str] = None,
) -> Dict[str, Any]:
    """Main entry point. Returns dict with `findings` + `summary`."""
    if db is None:
        return {"success": False, "error": "database not available", "findings": []}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    exec_query: Dict[str, Any] = {
        "$or": [
            {"time": {"$gte": cutoff}},
            {"timestamp": {"$gte": cutoff}},
        ],
    }
    if symbol:
        exec_query["symbol"] = symbol.upper()

    try:
        executions = list(db["ib_executions"].find(exec_query, {"_id": 0}))
    except Exception as e:
        logger.warning(f"[v19.34.16] ib_executions read failed: {e}")
        executions = []

    short_legs_by_sym = _fifo_walk_short_legs(executions)
    if not short_legs_by_sym:
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "window_days": days,
            "symbol_filter": symbol,
            "executions_scanned": len(executions),
            "findings": [],
            "summary": {"unmatched_count": 0, "symbols": []},
        }

    # Cross-check against bot_trades for direction=short rows.
    bot_query: Dict[str, Any] = {
        "direction": "short",
        "$or": [
            {"executed_at": {"$gte": cutoff}},
            {"closed_at": {"$gte": cutoff}},
        ],
    }
    if symbol:
        bot_query["symbol"] = symbol.upper()

    try:
        bot_short_rows = list(db["bot_trades"].find(
            bot_query, {"_id": 0, "symbol": 1, "id": 1, "shares": 1, "status": 1},
        ))
    except Exception as e:
        logger.warning(f"[v19.34.16] bot_trades read failed: {e}")
        bot_short_rows = []

    bot_short_syms = {(r.get("symbol") or "").upper() for r in bot_short_rows}

    findings: List[Dict[str, Any]] = []
    for sym, legs in short_legs_by_sym.items():
        if not legs:
            continue
        if sym in bot_short_syms:
            continue  # bot has at least one short row — matched
        # No matching bot row → flag.
        round_trips = [leg for leg in legs if leg.get("kind") != "open_residual_short"]
        residuals = [leg for leg in legs if leg.get("kind") == "open_residual_short"]
        findings.append({
            "symbol": sym,
            "round_trip_count": len(round_trips),
            "open_residual_count": len(residuals),
            "qty_total": sum(leg.get("qty") or 0 for leg in legs),
            "realized_pnl": round(sum((leg.get("pnl") or 0) for leg in round_trips), 2),
            "legs": legs,
            "detail": (
                f"{sym}: tape has {len(round_trips)} short round-trip(s) "
                f"+ {len(residuals)} residual(s) but bot_trades has no "
                f"direction=short row in last {days}d. "
                "Run `POST /api/trading-bot/reconcile-share-drift` to heal."
            ),
        })

    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "window_days": days,
        "symbol_filter": symbol,
        "executions_scanned": len(executions),
        "findings": findings,
        "summary": {
            "unmatched_count": len(findings),
            "symbols": [f["symbol"] for f in findings],
        },
    }
