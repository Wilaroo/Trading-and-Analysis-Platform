"""Trade Autopsy — post-trade forensic view (2026-04-21).

Given a closed trade_id, assemble the full picture:
  - Entry/exit prices, realized R, stop-honor status
  - Setup/symbol/direction/timestamps
  - Gate decision at entry: confidence_score, layer-by-layer reasoning
  - Ensemble meta-labeler P(win) at entry
  - Model signals that voted (sub-models, CNN-LSTM, TFT, VAE regime)
  - Linked live_alerts showing what the scanner saw

Every losing trade becomes an actionable debugging session.

Data sources
------------
- `bot_trades`                  : trade facts (entry/exit/stop/r_multiple/stop_honored)
- `gate_decisions`              : per-trade gate evaluation snapshot (if stored)
- `live_alerts`                 : scanner context at entry (symbol/setup joined by time)
- `confidence_calibration_log`  : P(win) vs outcome for calibration studies
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Pure helpers (unit-tested) ────────────────────────────────────────────

def summarize_trade_outcome(trade: Dict[str, Any]) -> Dict[str, Any]:
    """Compute the 'what happened' summary from a bot_trades doc.

    Pure function — no DB access. Returns a dict with:
      - verdict          : "win" | "loss" | "scratch" | "unknown"
      - realized_R       : signed R-multiple (None if inputs missing)
      - stop_honored     : bool | None
      - slippage_R       : excess R beyond intended 1R (only when stop failed)
      - pnl_usd          : float | None
      - hold_duration_s  : int | None
    """
    entry = trade.get("entry_price")
    stop = trade.get("stop_price")
    exit_ = trade.get("exit_price")
    direction = (trade.get("direction") or "").lower()
    pnl = trade.get("realized_pnl")
    r = trade.get("r_multiple")

    # Prefer stored r_multiple (set by execution-health audits) — avoids the
    # "imported_from_ib has exit_price=0" pitfall where recompute would fail.
    if r is None and entry and stop and exit_ and direction:
        try:
            e, s, x = float(entry), float(stop), float(exit_)
            if direction in ("long", "buy", "up"):
                risk = e - s
            elif direction in ("short", "sell", "down"):
                risk = s - e
            else:
                risk = 0
            if risk != 0:
                r = (x - e) / risk if direction in ("long", "buy", "up") else (e - x) / risk
        except (TypeError, ValueError):
            r = None

    verdict = "unknown"
    if r is not None:
        if r > 0.1:
            verdict = "win"
        elif r < -0.1:
            verdict = "loss"
        else:
            verdict = "scratch"
    elif pnl is not None:
        # Last-resort: realized_pnl alone gives us at least win/loss
        try:
            p = float(pnl)
            if p > 1:
                verdict = "win"
            elif p < -1:
                verdict = "loss"
            else:
                verdict = "scratch"
        except (TypeError, ValueError):
            pass

    stop_honored = trade.get("stop_honored")
    slippage = None
    if stop_honored is False and r is not None and r < 0:
        slippage = round(abs(r) - 1.0, 3)

    hold_s = None
    try:
        if trade.get("entry_time") and trade.get("closed_at"):
            a = datetime.fromisoformat(str(trade["entry_time"]).replace("Z", "+00:00"))
            b = datetime.fromisoformat(str(trade["closed_at"]).replace("Z", "+00:00"))
            hold_s = int((b - a).total_seconds())
    except Exception:
        hold_s = None

    return {
        "verdict": verdict,
        "realized_R": round(r, 3) if r is not None else None,
        "stop_honored": stop_honored,
        "slippage_R": slippage,
        "pnl_usd": round(float(pnl), 2) if pnl is not None else None,
        "hold_duration_s": hold_s,
    }


# ── Service class ─────────────────────────────────────────────────────────

class TradeAutopsy:
    """Assemble the full forensic view for any closed trade."""

    def __init__(self, db):
        self._db = db

    def autopsy(self, trade_id: str) -> Optional[Dict[str, Any]]:
        """Return full autopsy dict, or None if trade not found."""
        trade = self._db["bot_trades"].find_one(
            {"id": trade_id}, {"_id": 0}
        )
        if not trade:
            return None

        outcome = summarize_trade_outcome(trade)

        gate_snapshot = self._fetch_gate_snapshot(
            trade.get("symbol"), trade.get("setup_type"),
            trade.get("entry_time") or trade.get("created_at"),
        )

        scanner_alert = self._fetch_scanner_alert(
            trade.get("symbol"), trade.get("setup_type"),
            trade.get("entry_time") or trade.get("created_at"),
        )

        return {
            "trade_id": trade_id,
            "symbol": trade.get("symbol"),
            "setup_type": trade.get("setup_type"),
            "direction": trade.get("direction"),
            "status": trade.get("status"),
            "entry_price": trade.get("entry_price"),
            "stop_price": trade.get("stop_price"),
            "exit_price": trade.get("exit_price"),
            "shares": trade.get("shares"),
            "entry_time": trade.get("entry_time") or trade.get("created_at"),
            "closed_at": trade.get("closed_at") or trade.get("last_updated"),
            "outcome": outcome,
            "gate_snapshot": gate_snapshot,
            "scanner_alert": scanner_alert,
            "raw_trade_doc_keys": sorted(trade.keys()),
        }

    def _fetch_gate_snapshot(self, symbol: str, setup_type: str,
                             entry_time: Any) -> Optional[Dict[str, Any]]:
        """Find the closest `gate_decisions` doc within ±60s of entry."""
        if not (symbol and setup_type and entry_time):
            return None
        coll = self._db["gate_decisions"]
        # If collection doesn't exist or is empty, bail
        if coll.estimated_document_count() == 0:
            return None

        try:
            entry_dt = datetime.fromisoformat(str(entry_time).replace("Z", "+00:00"))
        except Exception:
            return None
        low = (entry_dt - timedelta(seconds=60)).isoformat()
        high = (entry_dt + timedelta(seconds=60)).isoformat()

        doc = coll.find_one(
            {
                "symbol": symbol,
                "setup_type": setup_type,
                "timestamp": {"$gte": low, "$lte": high},
            },
            {"_id": 0},
            sort=[("timestamp", -1)],
        )
        return doc

    def _fetch_scanner_alert(self, symbol: str, setup_type: str,
                             entry_time: Any) -> Optional[Dict[str, Any]]:
        """Find the live_alerts doc closest to (but at or before) entry."""
        if not (symbol and setup_type and entry_time):
            return None
        try:
            entry_dt = datetime.fromisoformat(str(entry_time).replace("Z", "+00:00"))
        except Exception:
            return None
        low = (entry_dt - timedelta(minutes=15)).isoformat()

        doc = self._db["live_alerts"].find_one(
            {
                "symbol": symbol,
                "setup_type": {"$regex": setup_type, "$options": "i"},
                "alert_time": {"$gte": low, "$lte": entry_dt.isoformat()},
            },
            {"_id": 0},
            sort=[("alert_time", -1)],
        )
        return doc

    def recent_losses(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List recent losing trades for triage-by-autopsy workflow."""
        cursor = self._db["bot_trades"].find(
            {"status": {"$in": ["closed", "closed_manual"]},
             "r_multiple": {"$ne": None, "$lt": 0}},
            {"_id": 0, "id": 1, "symbol": 1, "setup_type": 1, "direction": 1,
             "r_multiple": 1, "realized_pnl": 1, "stop_honored": 1,
             "closed_at": 1, "entry_time": 1},
        ).sort([("r_multiple", 1)]).limit(limit)
        return list(cursor)
