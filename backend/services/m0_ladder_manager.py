"""
m0_ladder_manager.py — M0 laddered scale-out: live management (2026-06)
========================================================================
The ladder itself lives AT IB (per-leg OCA pairs placed by
ib_direct_service._m0_place_oca_ladder). This manager runs inside the
bot's manage loop (position_manager calls `manage_m0_trade` per open
trade) and closes the loop the autopsy proved was open: IB-side leg
fills were invisible to the bot's stop logic, so the IB stop NEVER
moved off its original price.

Two jobs, both throttled and fail-safe:

1. LEG-FILL DETECTION
   Compare the bot's expected working-leg quantity against IB's live
   position; corroborate against the authoritative open-orders snapshot
   (which target/stop order ids are still working). When a target leg
   fills: stamp `scale_out_config['targets_hit']` (which the EXISTING
   StopManager keys BE-move / trail activation off), update
   remaining_shares / realized_pnl / partial_exits, and emit a stream
   event. Disambiguates TP-fill vs stop-fill via the trade's MFE.

2. IB STOP-SYNC
   StopManager keeps computing `trailing_stop_config['current_stop']`
   (BE after leg 1, HVN-snapped trail after leg 2) — internal-only
   before M0. When that ratchets ≥ M0_STOP_SYNC_MIN_R (default 0.1R)
   past the last price we pushed to IB, modify every surviving leg's
   stop IN PLACE (ib_direct.modify_stop_price — no cancel/replace, OCA
   group preserved). Ratchet-only: long stops only move up, short
   stops only move down. Throttled to M0_STOP_SYNC_INTERVAL_S (30s).

Safety rails:
  • No IB connection / empty order snapshot → skip the cycle entirely
    (a blank snapshot must never read as "everything filled").
  • Position-decrease corroboration required before any leg is marked
    filled.
  • All state lives in trade.scale_out_config (already persisted).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Module-level open-orders snapshot cache — one IB round-trip per cycle
# shared across ALL m0 trades, not one per trade.
_SNAPSHOT: Dict[str, Any] = {"at": 0.0, "ids": None}
_SNAPSHOT_TTL_S = 10.0

# Per-trade stop-sync timestamps (throttle).
_LAST_SYNC_AT: Dict[str, float] = {}


def _envf(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key) or default)
    except (TypeError, ValueError):
        return default


async def _open_order_ids(ib_direct) -> Optional[set]:
    """Cached set of working order ids at IB. None = unavailable (skip)."""
    now = time.monotonic()
    if _SNAPSHOT["ids"] is not None and (now - _SNAPSHOT["at"]) < _SNAPSHOT_TTL_S:
        return _SNAPSHOT["ids"]
    try:
        orders = await ib_direct.get_open_orders()
    except Exception as e:
        logger.debug("[M0] open-orders snapshot failed: %s", e)
        return None
    if not orders:
        # Empty could be real (nothing working) or a degraded read.
        # Treat as unavailable for FILL DETECTION — a blank snapshot
        # must never mass-mark legs as filled.
        _SNAPSHOT["ids"] = None
        _SNAPSHOT["at"] = now
        return None
    ids = {int(o.get("order_id")) for o in orders if o.get("order_id") is not None}
    _SNAPSHOT["ids"] = ids
    _SNAPSHOT["at"] = now
    return ids


def _direction(trade) -> str:
    return (getattr(trade.direction, "value", None) or str(trade.direction)).lower()


async def manage_m0_trade(trade, bot) -> None:
    """Single manage-loop tick for one M0-laddered open trade. No-op for
    trades without `scale_out_config['m0_legs']`."""
    cfg = getattr(trade, "scale_out_config", None) or {}
    legs: List[Dict[str, Any]] = cfg.get("m0_legs") or []
    if not legs:
        return
    working = [l for l in legs if l.get("status") == "working"]
    if not working:
        return

    try:
        from services.ib_direct_service import get_ib_direct_service
        ib_direct = get_ib_direct_service()
    except Exception:
        return

    await _detect_leg_fills(trade, bot, ib_direct, legs, working)
    await _sync_stops_to_ib(trade, ib_direct)


async def _detect_leg_fills(trade, bot, ib_direct, legs, working) -> None:
    symbol = str(trade.symbol).upper()
    open_ids = await _open_order_ids(ib_direct)
    if open_ids is None:
        return  # degraded read — never infer fills from a blank snapshot

    # Corroboration: how many shares does IB actually still hold?
    try:
        live_abs = await ib_direct.live_position_abs(symbol)
    except Exception:
        return
    expected = sum(int(l["qty"]) for l in working)
    deficit = expected - int(live_abs)
    if deficit <= 0:
        return  # nothing filled since last tick

    direction = _direction(trade)
    fill_px_base = float(getattr(trade, "fill_price", 0) or 0) or float(
        getattr(trade, "entry_price", 0) or 0)
    mfe = float(getattr(trade, "mfe_price", 0) or 0)

    changed = False
    for leg in sorted(working, key=lambda l: l.get("idx", 0)):
        if deficit < int(leg["qty"]):
            break
        tgt_id = leg.get("target_order_id")
        stop_id = leg.get("stop_order_id")
        tgt_gone = (tgt_id is None) or (int(tgt_id) not in open_ids)
        stop_gone = (stop_id is None) or (int(stop_id) not in open_ids)
        if not (tgt_gone and stop_gone):
            continue  # leg still (partially) working — not this one

        # Leg is terminal AND position decreased — attribute it.
        # TP vs stop disambiguation: did price ever reach the target?
        tpx = float(leg.get("target_px") or 0)
        if direction == "long":
            was_tp = tpx > 0 and mfe > 0 and mfe >= tpx * 0.999
        else:
            was_tp = tpx > 0 and mfe > 0 and mfe <= tpx * 1.001
        exit_px = tpx if was_tp else float(leg.get("stop_px") or trade.stop_price or 0)
        leg["status"] = "filled_tp" if was_tp else "filled_stop"
        leg["filled_at"] = datetime.now(timezone.utc).isoformat()
        deficit -= int(leg["qty"])
        changed = True

        qty = int(leg["qty"])
        if fill_px_base > 0 and exit_px > 0:
            pnl = ((exit_px - fill_px_base) if direction == "long"
                   else (fill_px_base - exit_px)) * qty
        else:
            pnl = 0.0
        trade.remaining_shares = max(0, int(trade.remaining_shares) - qty)
        trade.realized_pnl = float(getattr(trade, "realized_pnl", 0) or 0) + pnl

        if was_tp:
            hits = trade.scale_out_config.setdefault("targets_hit", [])
            if leg["idx"] not in hits:
                hits.append(leg["idx"])
            trade.scale_out_config.setdefault("partial_exits", []).append({
                "target_idx": leg["idx"] + 1,
                "target_price": tpx,
                "shares_sold": qty,
                "fill_price": exit_px,
                "pnl": pnl,
                "source": "m0_ib_leg_fill",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        logger.warning(
            "[M0 LEG-FILL] %s L%d %s — %dsh @ ~%.4f pnl≈%+.2f remaining=%d "
            "(deficit corroborated: IB live=%d)",
            symbol, leg["idx"] + 1, "TP" if was_tp else "STOP",
            qty, exit_px, pnl, trade.remaining_shares, live_abs,
        )
        try:
            from services.sentcom_service import emit_stream_event
            await emit_stream_event({
                "kind": "info",
                "event": "target_hit" if was_tp else "info",
                "symbol": symbol,
                "text": (
                    f"🎯 {symbol} M0 leg {leg['idx'] + 1} "
                    f"{'TP filled' if was_tp else 'stopped'} @ ~${exit_px:.2f} — "
                    f"{qty}sh, P&L ${pnl:+.2f}, {trade.remaining_shares}sh left"
                ),
                "metadata": {"source": "m0_ladder_manager",
                             "leg_idx": leg["idx"] + 1,
                             "was_tp": was_tp, "pnl": pnl},
            })
        except Exception:
            pass

    if changed:
        try:
            await bot._notify_trade_update(trade, "m0_leg_fill")
        except Exception:
            pass


async def _sync_stops_to_ib(trade, ib_direct) -> None:
    """Push StopManager's internal `current_stop` to the surviving IB leg
    stops when it has ratcheted meaningfully. Ratchet-only + throttled."""
    cfg = trade.scale_out_config or {}
    legs = [l for l in (cfg.get("m0_legs") or []) if l.get("status") == "working"]
    if not legs:
        return
    tcfg = getattr(trade, "trailing_stop_config", None) or {}
    if tcfg.get("mode", "original") == "original":
        return  # StopManager hasn't moved anything yet
    cur_stop = float(tcfg.get("current_stop", 0) or 0)
    if cur_stop <= 0:
        return
    last_pushed = float(cfg.get("m0_ib_stop_px", 0) or 0) or float(
        getattr(trade, "stop_price", 0) or 0)
    direction = _direction(trade)

    # Ratchet-only.
    if direction == "long" and cur_stop <= last_pushed:
        return
    if direction == "short" and cur_stop >= last_pushed:
        return

    # Min meaningful move: M0_STOP_SYNC_MIN_R of the original risk.
    entry = float(getattr(trade, "fill_price", 0) or 0) or float(
        getattr(trade, "entry_price", 0) or 0)
    orig_stop = float(tcfg.get("original_stop", 0) or 0) or float(
        getattr(trade, "stop_price", 0) or 0)
    risk = abs(entry - orig_stop) if entry > 0 and orig_stop > 0 else 0.0
    min_delta = max(_envf("M0_STOP_SYNC_MIN_R", 0.1) * risk, 0.01)
    if abs(cur_stop - last_pushed) < min_delta:
        return

    # Throttle per trade.
    now = time.monotonic()
    interval = _envf("M0_STOP_SYNC_INTERVAL_S", 30.0)
    if (now - _LAST_SYNC_AT.get(trade.id, 0.0)) < interval:
        return
    _LAST_SYNC_AT[trade.id] = now

    ok, fail = 0, 0
    for leg in legs:
        try:
            res = await ib_direct.modify_stop_price(leg["stop_order_id"], cur_stop)
            if res.get("success"):
                leg["stop_px"] = res.get("stop_price", cur_stop)
                ok += 1
            else:
                fail += 1
                logger.warning("[M0 STOP-SYNC] %s L%d modify failed: %s",
                               trade.symbol, leg["idx"] + 1, res.get("error"))
        except Exception as e:
            fail += 1
            logger.warning("[M0 STOP-SYNC] %s L%d modify raised: %s",
                           trade.symbol, leg["idx"] + 1, e)
    if ok:
        cfg["m0_ib_stop_px"] = cur_stop
        cfg["m0_stop_synced_at"] = datetime.now(timezone.utc).isoformat()
        mode = tcfg.get("mode")
        logger.warning(
            "[M0 STOP-SYNC] %s %d/%d leg stops moved to %.4f (mode=%s)",
            trade.symbol, ok, ok + fail, cur_stop, mode,
        )
        try:
            from services.sentcom_service import emit_stream_event
            await emit_stream_event({
                "kind": "info",
                "event": "info",
                "symbol": str(trade.symbol).upper(),
                "text": (
                    f"🛡️ {trade.symbol} M0 {mode} — IB stops on {ok} leg(s) "
                    f"moved to ${cur_stop:.2f}"
                ),
                "metadata": {"source": "m0_ladder_manager", "mode": mode,
                             "new_stop": cur_stop},
            })
        except Exception:
            pass


def forget_trade(trade_id: str) -> None:
    """Drop per-trade throttle state when a trade closes."""
    _LAST_SYNC_AT.pop(trade_id, None)
