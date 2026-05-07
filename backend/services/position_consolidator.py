"""
Position Consolidator — v19.34.42 (2026-05-08)
====================================================

Operator-discovered 2026-05-08: BMNR position showed **19 underlying
bot trades** for ONE actual IB position of 4,443 shares. LIN had 3,
DDOG had 2. The 19 BMNR slices each owned their own OCA bracket at IB
which collide on a single aggregated position — IB silently dropped
all but one, leaving thousands of shares effectively unprotected (last
price 21.82 was already $0.41 below the $22.23 stops, yet none had
fired because the brackets were ghosts).

ROOT-CAUSE INVARIANT VIOLATION
------------------------------
The bot maintained an N:1 mapping between bot_trades and IB positions
when the correct invariant is **1:1 per (account, symbol, direction)**.
Multiple bot_trades for the same aggregated IB position is always wrong.

CONSOLIDATION CONTRACT
----------------------
For each (symbol, direction) with N>1 open bot_trades:

  1. Pick **canonical**: the OLDEST trade that is NOT
     `setup_type=reconciled_excess_slice` (or that lacks the
     `reconciled_excess_*` provenance). Falls back to oldest period.
  2. **Cancel** all open OCA brackets at IB across canonical AND
     siblings (clear the slate so IB has no leftover children).
  3. **Place** ONE new OCA bracket on canonical sized to the SUM of
     all sibling shares + canonical shares (= IB position size).
     Uses canonical's *original* SL/PT (not synthetic 1% bracket).
  4. **Close** sibling bot_trades in DB:
       status         = closed
       remaining_shares = 0
       realized_pnl   = 0       (PnL is folded into canonical)
       close_reason   = "consolidated_v19_34_42"
       closed_at      = now
       notes          += " [v19.34.42: rolled into canonical {id}]"
  5. **Update** canonical: shares = remaining_shares = total_qty.
  6. **In-memory**: pop siblings from `_open_trades`.

The unprotected window between step 2 and step 3 is sub-second; safe
when kill-switch is ON.

DRY-RUN
-------
`dry_run_consolidation(bot)` returns the per-symbol diff WITHOUT
mutating anything. Use for operator review before `apply_consolidation`.

API
---
- `await consolidator.dry_run_consolidation(bot)`
- `await consolidator.apply_consolidation(bot, symbols=[...], confirm=True)`
- `await consolidator.auto_consolidate_if_safe(bot)`  ← used by reconcile loop
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from services.trading_bot_service import TradingBotService

logger = logging.getLogger(__name__)


# Provenance markers that identify a trade as a "reconciled" auto-spawned
# slice rather than a bot-originated entry. Canonical-trade resolution
# prefers non-reconciled trades.
_RECONCILED_PROVENANCE = {
    "reconciled_excess_v19_34_15b",
    "reconciled_external",  # v19.24 orphan-reconcile path
}
_RECONCILED_SETUP_TYPES = {
    "reconciled_excess_slice",
    "reconciled_orphan",
    "imported_from_ib",
}


class PositionConsolidator:
    """Collapse fragmented (symbol, direction) groups into one canonical trade."""

    def __init__(self, db=None):
        self._db = db

    @property
    def db(self):
        if self._db is None:
            try:
                from database import get_database
                self._db = get_database()
            except Exception:
                return None
        return self._db

    # ─────────────────────────── Detection ───────────────────────────

    def _group_open_trades(self, bot: "TradingBotService") -> Dict[tuple, list]:
        """Return {(symbol, direction): [trade, ...]} for currently OPEN trades."""
        groups: Dict[tuple, list] = {}
        for t in list(bot._open_trades.values()):
            sym = (getattr(t, "symbol", "") or "").upper()
            d = getattr(t, "direction", None)
            d_val = getattr(d, "value", str(d) if d else "long").lower()
            if not sym:
                continue
            # Skip rows that already have zero shares — those are
            # zombies; the v19.34.19 zombie-handler owns them.
            rs = int(abs(getattr(t, "remaining_shares", 0) or 0))
            if rs <= 0:
                continue
            groups.setdefault((sym, d_val), []).append(t)
        return groups

    def _pick_canonical(self, trades: list):
        """Oldest non-reconciled wins; fallback oldest overall."""
        def _ts_key(t):
            for attr in ("entry_time", "executed_at", "created_at"):
                v = getattr(t, attr, None)
                if v:
                    return str(v)
            return ""

        def _is_reconciled(t) -> bool:
            return (
                (getattr(t, "entered_by", "") or "") in _RECONCILED_PROVENANCE
                or (getattr(t, "setup_type", "") or "") in _RECONCILED_SETUP_TYPES
            )

        non_reconciled = [t for t in trades if not _is_reconciled(t)]
        pool = non_reconciled or trades
        return sorted(pool, key=_ts_key)[0]

    def _summarize_trade(self, t) -> Dict[str, Any]:
        return {
            "trade_id": getattr(t, "id", None),
            "shares": int(abs(getattr(t, "remaining_shares", 0) or 0)),
            "entry_price": float(getattr(t, "fill_price", 0) or getattr(t, "entry_price", 0) or 0),
            "stop_price": float(getattr(t, "stop_price", 0) or 0),
            "target_price": float(((getattr(t, "target_prices", []) or [0])[0]) or 0),
            "setup_type": getattr(t, "setup_type", None),
            "entered_by": getattr(t, "entered_by", None),
            "entry_time": getattr(t, "entry_time", None) and str(t.entry_time),
            "unrealized_pnl": float(getattr(t, "unrealized_pnl", 0) or 0),
        }

    def _build_diff(self, bot: "TradingBotService") -> Dict[str, Any]:
        """Build per-symbol diff for fragmented groups (N>1 open trades)."""
        groups = self._group_open_trades(bot)
        diffs: List[Dict[str, Any]] = []
        for (sym, direction), trades in sorted(groups.items()):
            if len(trades) <= 1:
                continue
            canonical = self._pick_canonical(trades)
            siblings = [t for t in trades if getattr(t, "id", None) != getattr(canonical, "id", None)]
            total_shares = sum(int(abs(getattr(t, "remaining_shares", 0) or 0)) for t in trades)
            diffs.append({
                "symbol": sym,
                "direction": direction,
                "fragment_count": len(trades),
                "current_total_shares": total_shares,
                "proposed_canonical": self._summarize_trade(canonical),
                "proposed_total_shares": total_shares,
                "proposed_stop": float(getattr(canonical, "stop_price", 0) or 0),
                "proposed_target": float(((getattr(canonical, "target_prices", []) or [0])[0]) or 0),
                "siblings_to_close": [self._summarize_trade(t) for t in siblings],
                "expected_pnl_impact": 0.0,  # PnL is folded, not realized
            })
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fragmented_groups": len(diffs),
            "groups": diffs,
        }

    # ─────────────────────────── Public API ───────────────────────────

    async def dry_run_consolidation(self, bot: "TradingBotService") -> Dict[str, Any]:
        """Return diff report — NO mutations."""
        try:
            return {"success": True, **self._build_diff(bot)}
        except Exception as e:
            logger.exception(f"dry_run_consolidation failed: {e}")
            return {"success": False, "error": str(e), "fragmented_groups": 0, "groups": []}

    async def apply_consolidation(
        self,
        bot: "TradingBotService",
        symbols: Optional[List[str]] = None,
        confirm: bool = False,
    ) -> Dict[str, Any]:
        """Consolidate the fragmented groups for `symbols` (or ALL fragmented if None).

        Requires `confirm=True` to actually mutate. Returns per-symbol result.
        """
        if not confirm:
            return {"success": False, "error": "confirm=True required to apply consolidation"}

        diff = self._build_diff(bot)
        groups = diff["groups"]
        target_syms = {s.upper() for s in (symbols or [])} if symbols else None
        if target_syms is not None:
            groups = [g for g in groups if g["symbol"] in target_syms]

        report: Dict[str, Any] = {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "consolidated": [],
            "skipped": [],
            "errors": [],
        }

        for g in groups:
            sym = g["symbol"]
            try:
                result = await self._consolidate_one_group(bot, g)
                report["consolidated"].append(result)
            except Exception as e:
                logger.exception(f"consolidate {sym} failed: {e}")
                report["errors"].append({"symbol": sym, "error": str(e)})

        return report

    async def auto_consolidate_if_safe(self, bot: "TradingBotService") -> Dict[str, Any]:
        """Per-tick fast-path with safety rail.

        Rail: only auto-runs when kill-switch is ACTIVE OR when fragment
        count is <=2 per group. Avoids ripping live brackets while
        operator hasn't acknowledged a fresh fragmentation event.
        """
        try:
            groups = self._group_open_trades(bot)
            fragmented = {k: v for k, v in groups.items() if len(v) > 1}
            if not fragmented:
                return {"success": True, "ran": False, "reason": "no_fragments"}

            # Safety rail
            kill_active = self._is_kill_switch_active()
            small_only = all(len(v) <= 2 for v in fragmented.values())
            if not kill_active and not small_only:
                return {
                    "success": True,
                    "ran": False,
                    "reason": "rail_blocked_large_fragmentation_with_live_trading",
                    "fragmented_groups": len(fragmented),
                    "max_fragment_count": max(len(v) for v in fragmented.values()),
                }

            symbols = sorted({sym for (sym, _d) in fragmented.keys()})
            return await self.apply_consolidation(bot, symbols=symbols, confirm=True)
        except Exception as e:
            logger.exception(f"auto_consolidate_if_safe error: {e}")
            return {"success": False, "error": str(e), "ran": False}

    # ───────────────────────── Implementation ──────────────────────────

    @staticmethod
    def _is_kill_switch_active() -> bool:
        try:
            from services.safety_guardrails import get_safety_guardrails
            guard = get_safety_guardrails()
            return bool(getattr(guard, "state", None) and guard.state.kill_switch_active)
        except Exception:
            return False

    async def _consolidate_one_group(
        self, bot: "TradingBotService", g: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute the 6-step consolidation for one (symbol, direction) group."""
        from services.trading_bot_service import TradeStatus

        sym = g["symbol"]
        direction = g["direction"]
        total_shares = int(g["proposed_total_shares"])
        canonical_id = g["proposed_canonical"]["trade_id"]

        # Reload the actual trade objects from in-memory by id (the diff carries summaries).
        all_open = list(bot._open_trades.values())
        trades = [
            t for t in all_open
            if (getattr(t, "symbol", "") or "").upper() == sym
            and (getattr(t.direction, "value", str(t.direction)).lower() == direction)
            and int(abs(getattr(t, "remaining_shares", 0) or 0)) > 0
        ]
        canonical = next((t for t in trades if getattr(t, "id", None) == canonical_id), None)
        if canonical is None:
            return {
                "symbol": sym, "direction": direction,
                "skipped": True, "reason": "canonical_no_longer_open",
            }
        siblings = [t for t in trades if getattr(t, "id", None) != canonical_id]

        action_log: List[str] = []

        # ── Step 2: cancel ALL existing OCA brackets at IB (canonical + siblings).
        executor = getattr(bot, "_trade_executor", None)
        cancel_errors: List[str] = []
        for t in [canonical, *siblings]:
            try:
                if executor and hasattr(executor, "_cancel_ib_bracket_orders"):
                    await executor._cancel_ib_bracket_orders(t)
                    action_log.append(f"cancelled brackets for {getattr(t, 'id', '?')}")
            except Exception as e:
                cancel_errors.append(f"{getattr(t, 'id', '?')}: {e}")
                logger.warning(f"[v19.34.42] {sym} cancel sibling {getattr(t, 'id', '?')} failed: {e}")

        # Clear order IDs from canonical (they're cancelled now).
        canonical.stop_order_id = None
        canonical.target_order_id = None
        try:
            canonical.target_order_ids = []
        except Exception:
            pass
        canonical.oca_group = None

        # ── Step 5 (DB-side): grow canonical to the total share count BEFORE
        # placing new bracket so the bracket size matches reality.
        old_canonical_shares = int(abs(getattr(canonical, "remaining_shares", 0) or 0))
        canonical.remaining_shares = total_shares
        try:
            canonical.shares = total_shares
        except Exception:
            pass
        try:
            canonical.original_shares = max(int(getattr(canonical, "original_shares", 0) or 0), total_shares)
        except Exception:
            pass

        # Adjust risk_amount to the new total so trail-stop math stays sane.
        try:
            stop_dist = abs(float(getattr(canonical, "fill_price", 0) or canonical.entry_price)
                            - float(getattr(canonical, "stop_price", 0) or 0))
            if stop_dist > 0:
                canonical.risk_amount = stop_dist * total_shares
        except Exception:
            pass

        canonical.notes = (getattr(canonical, "notes", "") or "") + (
            f" [v19.34.42 CONSOLIDATE: grew {old_canonical_shares}→{total_shares} sh, "
            f"absorbed {len(siblings)} sibling slice(s)]"
        )

        # ── Step 3: place ONE new OCA bracket on canonical sized to total_shares.
        oca_attached = False
        oca_error: Optional[str] = None
        if executor and hasattr(executor, "attach_oca_stop_target"):
            try:
                oca_result = await executor.attach_oca_stop_target(canonical)
                if oca_result and oca_result.get("success"):
                    canonical.stop_order_id = oca_result.get("stop_order_id")
                    tgt_id = oca_result.get("target_order_id")
                    if tgt_id:
                        canonical.target_order_id = tgt_id
                    canonical.oca_group = oca_result.get("oca_group")
                    oca_attached = True
                    action_log.append(
                        f"placed canonical OCA: stop={canonical.stop_order_id} "
                        f"target={tgt_id} oca={canonical.oca_group}"
                    )
                else:
                    oca_error = (oca_result or {}).get("error", "no result")
            except Exception as e:
                oca_error = f"{type(e).__name__}: {e}"
        else:
            oca_error = "no executor.attach_oca_stop_target"

        if not oca_attached:
            logger.error(
                f"[v19.34.42 NAKED-CANONICAL] {sym} consolidation placed canonical "
                f"{canonical.id} for {total_shares}sh but OCA bracket FAILED: "
                f"{oca_error}. Position is naked at IB — operator must place "
                f"manual stop ${getattr(canonical, 'stop_price', 0):.2f} + "
                f"target ${(canonical.target_prices or [0])[0]:.2f}."
            )

        # ── Step 4 + 6: close siblings, drop from in-memory.
        now_iso = datetime.now(timezone.utc).isoformat()
        sibling_ids_closed: List[str] = []
        for s in siblings:
            try:
                old_sh = int(abs(getattr(s, "remaining_shares", 0) or 0))
                s.status = TradeStatus.CLOSED
                s.remaining_shares = 0
                # PnL=0 because canonical absorbs ALL the open exposure;
                # the unrealized loss/gain remains on canonical's books.
                s.realized_pnl = 0.0
                s.unrealized_pnl = 0.0
                s.close_reason = "consolidated_v19_34_42"
                s.closed_at = now_iso
                s.exit_time = datetime.now(timezone.utc)
                s.exit_reason = "consolidated_v19_34_42"
                s.exit_price = float(getattr(s, "fill_price", 0) or 0)  # neutral marker
                s.stop_order_id = None
                s.target_order_id = None
                try:
                    s.target_order_ids = []
                except Exception:
                    pass
                s.oca_group = None
                s.notes = (getattr(s, "notes", "") or "") + (
                    f" [v19.34.42: rolled {old_sh}sh into canonical {canonical.id}]"
                )
                sibling_ids_closed.append(getattr(s, "id", ""))
            except Exception as e:
                logger.warning(f"[v19.34.42] sibling close mutate failed for {getattr(s, 'id', '?')}: {e}")

        # Persist canonical + siblings.
        save_fn = getattr(bot, "_save_trade", None) or getattr(bot, "_persist_trade", None)
        for t in [canonical, *siblings]:
            try:
                if save_fn:
                    res = save_fn(t)
                    if asyncio.iscoroutine(res):
                        await res
            except Exception as e:
                logger.warning(f"[v19.34.42] persist {getattr(t, 'id', '?')} failed: {e}")

        # Mongo-direct fallback for siblings (mirrors v19.34.21 zombie-close hardening).
        try:
            db_handle = getattr(bot, "_db", None) or self.db
            if db_handle is not None:
                for s in siblings:
                    try:
                        await asyncio.to_thread(
                            db_handle["bot_trades"].update_one,
                            {"id": s.id},
                            {"$set": {
                                "status": "closed",
                                "remaining_shares": 0,
                                "realized_pnl": 0.0,
                                "unrealized_pnl": 0.0,
                                "close_reason": "consolidated_v19_34_42",
                                "closed_at": s.closed_at,
                                "exit_reason": "consolidated_v19_34_42",
                                "stop_order_id": None,
                                "target_order_id": None,
                                "oca_group": None,
                                "notes": s.notes,
                            }},
                        )
                    except Exception as direct_e:
                        logger.warning(f"[v19.34.42] direct mongo close {s.id}: {direct_e}")
                # Update canonical too.
                try:
                    await asyncio.to_thread(
                        db_handle["bot_trades"].update_one,
                        {"id": canonical.id},
                        {"$set": {
                            "remaining_shares": canonical.remaining_shares,
                            "shares": getattr(canonical, "shares", canonical.remaining_shares),
                            "original_shares": getattr(canonical, "original_shares", canonical.remaining_shares),
                            "stop_order_id": canonical.stop_order_id,
                            "target_order_id": canonical.target_order_id,
                            "oca_group": canonical.oca_group,
                            "notes": canonical.notes,
                            "risk_amount": getattr(canonical, "risk_amount", 0),
                        }},
                    )
                except Exception as direct_e:
                    logger.warning(f"[v19.34.42] direct mongo update canonical {canonical.id}: {direct_e}")
        except Exception:
            pass

        # Drop siblings from in-memory; release stop-manager state.
        for s in siblings:
            try:
                if hasattr(bot, "_open_trades"):
                    bot._open_trades.pop(getattr(s, "id", ""), None)
                if hasattr(bot, "_closed_trades"):
                    try:
                        bot._closed_trades.append(s)
                    except Exception:
                        pass
                sm = getattr(bot, "_stop_manager", None)
                if sm and hasattr(sm, "forget_trade"):
                    sm.forget_trade(getattr(s, "id", ""))
            except Exception as e:
                logger.warning(f"[v19.34.42] in-memory cleanup {getattr(s, 'id', '?')}: {e}")

        # Audit trail to share_drift_events.
        try:
            db_handle = getattr(bot, "_db", None) or self.db
            if db_handle is not None:
                await asyncio.to_thread(
                    db_handle["share_drift_events"].insert_one,
                    {
                        "created_at": datetime.now(timezone.utc),
                        "event": "consolidated_v19_34_42",
                        "symbol": sym,
                        "direction": direction,
                        "fragment_count": len(trades),
                        "canonical_id": canonical.id,
                        "siblings_closed": sibling_ids_closed,
                        "total_shares": total_shares,
                        "oca_attached": oca_attached,
                        "oca_error": oca_error,
                    },
                )
        except Exception:
            pass

        # Stream emit.
        try:
            from services.sentcom_service import emit_stream_event
            await emit_stream_event({
                "kind": "warning" if oca_attached else "alert",
                "event": "consolidated_v19_34_42",
                "symbol": sym,
                "text": (
                    f"🧹 {sym} consolidated {len(trades)} fragments → 1. "
                    f"Canonical {canonical.id} now holds {total_shares}sh. "
                    + ("OCA bracket attached." if oca_attached
                       else f"⚠ NAKED at IB — manual stop needed: {oca_error}")
                ),
                "metadata": {
                    "canonical_id": canonical.id,
                    "siblings_closed": sibling_ids_closed,
                    "total_shares": total_shares,
                    "oca_attached": oca_attached,
                },
            })
        except Exception:
            pass

        return {
            "symbol": sym,
            "direction": direction,
            "canonical_id": canonical.id,
            "siblings_closed": sibling_ids_closed,
            "total_shares": total_shares,
            "old_canonical_shares": old_canonical_shares,
            "oca_attached": oca_attached,
            "oca_error": oca_error,
            "actions": action_log,
            "cancel_errors": cancel_errors,
        }
