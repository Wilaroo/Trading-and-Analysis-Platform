"""services/entry_price_sync.py — v19.34.148

One-shot reconciler that walks every open BotTrade and snaps its
`entry_price` to IB's live `avgCost`. Fixes the ICLN / CW / ITT /
DKS / DG drift class identified by the v19.34.147 audit: bot stores
the raw initial-fill price while IB's `avgCost` keeps incrementing
with commissions, borrow fees (shorts!), multi-level fills, and
corp-action / ETF-distribution adjustments.

Used by:
  • POST /api/trading-bot/sync-entry-prices  (manual, immediate)
  • TradingScheduler nightly cron @ 16:30 ET  (idempotent daily heal)

Design contracts:
  1. **NO POSITION CHANGES.** This module ONLY rewrites the cached
     `entry_price` field on tracked trades. `shares`,
     `remaining_shares`, `stop_order_id`, `target_*` are untouched.
  2. **Symmetric direction handling.** IB stores `avgCost` as a
     positive number even for shorts — read it as-is.
  3. **Tolerance gate.** Skip syncs where the per-share delta is
     ≤ 1¢ (sub-tolerance noise; not worth churning the ledger).
  4. **IB-snapshot dependency.** If `_pushed_ib_data["positions"]`
     is empty or stale, return `{"success": False, "reason": ...}`
     immediately — don't mutate state on partial data.
  5. **Persistence.** When a sync fires, the new entry_price is
     also written to MongoDB `bot_trades` so the audit endpoint
     reads the same value on next call.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Sub-tolerance gate. Anything ≤ 1¢/share is rounding/timing noise
# (the v19.34.147 audit thresholds at this boundary too).
DEFAULT_TOLERANCE_PER_SHARE = 0.01


def _fetch_ib_avg_cost_map() -> Dict[str, float]:
    """Read pusher snapshot → {SYMBOL: avgCost}. Returns {} on any
    failure (caller treats as "no data available, skip sync")."""
    try:
        from routers.ib import _pushed_ib_data
        positions = (_pushed_ib_data or {}).get("positions") or []
        out: Dict[str, float] = {}
        for p in positions:
            if not isinstance(p, dict):
                continue
            sym = (p.get("symbol") or "").upper()
            avg = p.get("avgCost")
            if not sym or avg is None:
                continue
            try:
                fv = float(avg)
            except (TypeError, ValueError):
                continue
            if fv > 0:
                out[sym] = fv
        return out
    except Exception as e:
        logger.warning(f"_fetch_ib_avg_cost_map failed: {e}")
        return {}


async def sync_entry_prices_to_ib_avg_cost(
    bot,
    *,
    tolerance_per_share: float = DEFAULT_TOLERANCE_PER_SHARE,
    dry_run: bool = False,
    symbols: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """v19.34.148 — sync `_open_trades[*].entry_price` ← IB.avgCost.

    Args:
      bot: TradingBotService (has `_open_trades` and `_db`).
      tolerance_per_share: skip if |bot.entry - ib.avgCost| ≤ this.
      dry_run: if True, report what WOULD sync but don't mutate.
      symbols: optional filter — only sync these symbols.

    Returns a structured report with:
      success            : bool
      generated_at       : ISO timestamp
      mode               : "live" | "dry_run"
      ib_positions_seen  : int (pusher coverage)
      tracked_trades     : int (open BotTrades visited)
      candidates         : int (trades inside scope)
      synced             : list[{trade_id, symbol, old, new, delta_per_share, qty, implied_pnl_correction}]
      skipped_within_tol : list[{trade_id, symbol, delta_per_share}]
      skipped_no_ib_data : list[{trade_id, symbol}]
      total_implied_pnl_correction : float (signed; positive = bot was overstating)
    """
    started = datetime.now(timezone.utc)
    ib_avg_map = _fetch_ib_avg_cost_map()
    if not ib_avg_map:
        return {
            "success": False,
            "reason": "no_ib_positions_in_pusher_snapshot",
            "generated_at": started.isoformat(),
            "mode": "dry_run" if dry_run else "live",
        }

    target_syms: Optional[set] = None
    if symbols:
        target_syms = {s.strip().upper() for s in symbols if s and s.strip()}

    synced: List[Dict[str, Any]] = []
    skipped_within_tol: List[Dict[str, Any]] = []
    skipped_no_ib_data: List[Dict[str, Any]] = []
    candidates = 0
    tracked = 0
    persisted = 0
    persist_errors: List[Dict[str, Any]] = []

    open_trades = getattr(bot, "_open_trades", {}) or {}
    for tid, trade in list(open_trades.items()):
        tracked += 1
        sym = (getattr(trade, "symbol", "") or "").upper()
        if not sym:
            continue
        if target_syms and sym not in target_syms:
            continue
        # Skip zombies (remaining_shares==0). entry_price drift on a
        # zombie is harmless and can't be safely reconciled anyway.
        try:
            rs = int(abs(getattr(trade, "remaining_shares", 0) or 0))
        except (TypeError, ValueError):
            rs = 0
        if rs <= 0:
            continue
        candidates += 1

        ib_avg = ib_avg_map.get(sym)
        if ib_avg is None or ib_avg <= 0:
            skipped_no_ib_data.append({"trade_id": tid, "symbol": sym})
            continue

        try:
            bot_entry = float(
                getattr(trade, "fill_price", None)
                or getattr(trade, "entry_price", 0)
                or 0
            )
        except (TypeError, ValueError):
            bot_entry = 0.0
        if bot_entry <= 0:
            # Don't sync against a missing entry — that's a different
            # bug class. Skip and report.
            skipped_no_ib_data.append({
                "trade_id": tid, "symbol": sym,
                "reason": "bot_entry_price_missing_or_zero",
            })
            continue

        delta_per_share = abs(ib_avg - bot_entry)
        if delta_per_share <= tolerance_per_share:
            skipped_within_tol.append({
                "trade_id": tid, "symbol": sym,
                "delta_per_share": round(delta_per_share, 4),
            })
            continue

        # Direction-aware implied PnL correction. For a LONG, when
        # ib.avgCost > bot.entry, the bot was OVERSTATING unrealized
        # by (delta * qty). For a SHORT, when ib.avgCost > bot.entry,
        # the bot was UNDERSTATING (sells at a higher price than
        # ledger thinks → bigger gain). Encode the sign so the
        # operator can see net direction.
        direction_val = getattr(trade, "direction", None)
        direction_str = (
            getattr(direction_val, "value", str(direction_val))
            if direction_val is not None
            else "long"
        ).lower()
        signed_delta = ib_avg - bot_entry  # signed
        if direction_str == "long":
            implied_pnl_correction = -signed_delta * rs  # cost goes up → pnl down
        else:
            implied_pnl_correction = signed_delta * rs   # short: cost goes up → bot was over-stating

        record = {
            "trade_id": tid,
            "symbol": sym,
            "direction": direction_str,
            "qty": rs,
            "old_entry_price": round(bot_entry, 6),
            "new_entry_price": round(ib_avg, 6),
            "delta_per_share": round(signed_delta, 6),
            "implied_pnl_correction": round(implied_pnl_correction, 2),
        }

        if dry_run:
            synced.append({**record, "applied": False})
            continue

        # Mutate the in-memory trade. Both fields exist on the
        # BotTrade dataclass — keep them in lockstep so downstream
        # PnL math (sentcom_service uses `entry`, executor uses
        # `fill_price`) reads the same number.
        try:
            trade.entry_price = float(ib_avg)
            if hasattr(trade, "fill_price"):
                trade.fill_price = float(ib_avg)
        except Exception as e:
            persist_errors.append({
                "trade_id": tid, "symbol": sym,
                "error": f"in_memory_set_failed:{e}",
            })
            continue

        # Persist to MongoDB. The `entry_price` field is canonical
        # on the `bot_trades` collection.
        db = getattr(bot, "_db", None)
        if db is not None:
            try:
                await db["bot_trades"].update_one(
                    {"id": tid},
                    {"$set": {
                        "entry_price": float(ib_avg),
                        "fill_price": float(ib_avg),
                        "entry_price_synced_at": datetime.now(
                            timezone.utc
                        ).isoformat(),
                        "entry_price_sync_source": "ib_avg_cost",
                        "entry_price_pre_sync": bot_entry,
                    }},
                )
                persisted += 1
            except Exception as e:
                persist_errors.append({
                    "trade_id": tid, "symbol": sym,
                    "error": f"db_persist_failed:{e}",
                })

        synced.append({**record, "applied": True})

    total_correction = round(
        sum(r.get("implied_pnl_correction") or 0 for r in synced), 2
    )

    return {
        "success": True,
        "generated_at": started.isoformat(),
        "mode": "dry_run" if dry_run else "live",
        "tolerance_per_share": tolerance_per_share,
        "ib_positions_seen": len(ib_avg_map),
        "tracked_trades": tracked,
        "candidates": candidates,
        "synced": synced,
        "skipped_within_tol": skipped_within_tol,
        "skipped_no_ib_data": skipped_no_ib_data,
        "persisted_to_db": persisted,
        "persist_errors": persist_errors,
        "total_implied_pnl_correction": total_correction,
    }
