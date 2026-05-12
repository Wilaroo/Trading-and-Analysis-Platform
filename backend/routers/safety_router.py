"""
Safety guardrails router — exposes the kill-switch, config, and emergency
flatten-all endpoints used by the V5 Command-Center safety banner.

Routes:
    GET  /api/safety/status                — config + state + recent check log
    PUT  /api/safety/config                — hot-patch config (risk caps)
    POST /api/safety/reset-kill-switch     — manual unlock after acknowledgement
    POST /api/safety/flatten-all           — cancel all pending + close all open
    POST /api/safety/kill-switch/trip      — test/manual trip (rare — debugging)

No auth here — same model as the rest of the trading-bot routes. This is a
single-user system behind a LAN; if that ever changes, gate these behind the
same admin check used by `/api/admin/*`.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.safety_guardrails import get_safety_guardrails
from services.risk_caps_service import compute_effective_risk_caps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/safety", tags=["Safety Guardrails"])


# ─── schemas ─────────────────────────────────────────────────────────────

class SafetyConfigPatch(BaseModel):
    """All fields optional — only the ones provided are updated."""
    max_daily_loss_usd:      Optional[float] = Field(default=None, gt=0)
    max_daily_loss_pct:      Optional[float] = Field(default=None, gt=0, lt=100)
    max_positions:           Optional[int]   = Field(default=None, ge=1, le=100)
    max_symbol_exposure_usd: Optional[float] = Field(default=None, gt=0)
    # 2026-04-30 v19.5 — ceiling raised 100 → 1000 for margin accounts.
    # max_total_exposure_pct is "% of cash equity"; on a 4× margin
    # account, 80% of buying power == 320% of equity. Cash-only operators
    # naturally stay under 100; margin operators need the headroom.
    max_total_exposure_pct:  Optional[float] = Field(default=None, gt=0, le=1000)
    max_quote_age_seconds:   Optional[float] = Field(default=None, gt=0, lt=300)
    enabled:                 Optional[bool]  = None


class KillSwitchTripRequest(BaseModel):
    reason: str = Field(default="manual", min_length=1, max_length=200)


# ─── endpoints ────────────────────────────────────────────────────────────

@router.get("/status")
async def safety_status() -> Dict[str, Any]:
    """Full safety surface: current config + state + last 20 check decisions.

    Also includes a `live` block computed on-demand from the trading bot so
    the V5 UI can show an "Awaiting IB Quotes" pill while any open position
    is still waiting for its first quote (and the live unrealized-PnL math
    is therefore suppressed from the kill-switch).
    """
    resp: Dict[str, Any] = {"success": True, **get_safety_guardrails().status()}

    # Live awaiting-quotes signal — best-effort, never fails the endpoint.
    try:
        from services.trading_bot_service import get_trading_bot
        bot = get_trading_bot()
        awaiting_quotes = False
        missing: List[str] = []
        open_count = 0
        if bot and hasattr(bot, "_open_trades"):
            open_trades = list(bot._open_trades.values())
            open_count = len(open_trades)
            for t in open_trades:
                fill = float(getattr(t, "fill_price", 0) or 0)
                cur = float(getattr(t, "current_price", 0) or 0)
                if fill <= 0 or cur <= 0:
                    awaiting_quotes = True
                    sym = getattr(t, "symbol", None)
                    if sym and sym not in missing:
                        missing.append(sym)
        resp["live"] = {
            "open_positions_count": open_count,
            "awaiting_quotes": awaiting_quotes,
            "positions_missing_quotes": missing,
        }
    except Exception as e:
        logger.debug("safety.status live-block error: %s", e)
        resp["live"] = {
            "open_positions_count": 0,
            "awaiting_quotes": False,
            "positions_missing_quotes": [],
        }

    # Account guard — surface paper/live config + match status to UI.
    try:
        from services.account_guard import summarize_for_ui
        current = None
        ib_connected = None
        # Mirror the exact extraction used by /api/ib/account/summary so the
        # guard reads the pusher's live account id (see routers/ib.py:735-739).
        try:
            from routers.ib import get_pushed_account_id, is_pusher_connected
            current = get_pushed_account_id()
            # is_pusher_connected reflects the pusher process; a true pusher
            # connection without an account id means IB Gateway itself is
            # offline (weekend), which is the case that should soften
            # account-mismatch from RED to PENDING.
            ib_connected = bool(is_pusher_connected()) and bool(current)
        except Exception:
            current = None
        # Fallback: direct-connected IB service (when pusher is offline).
        if not current:
            try:
                from services.ib_service import get_ib_service
                ib = get_ib_service()
                status_obj = ib.get_status() if ib else None
                current = (status_obj or {}).get("account_id")
                if current and ib_connected is None:
                    ib_connected = True
            except Exception:
                pass
        resp["account_guard"] = summarize_for_ui(current, ib_connected=ib_connected)
    except Exception as e:
        logger.debug("safety.status account_guard error: %s", e)
        resp["account_guard"] = {"match": True, "reason": "unavailable"}

    return resp


@router.get("/effective-risk-caps")
async def effective_risk_caps() -> Dict[str, Any]:
    """Resolve overlapping risk caps to the effective (most-restrictive)
    binding values across bot config, kill switch, position sizer, and
    dynamic risk engine.

    Single read-only operation — never mutates any source. Returns:

      - `sources`    — raw per-source values for inspection / audit
      - `effective`  — the resolved cap that actually binds live trades
      - `conflicts`  — human-readable diagnostics when sources disagree

    Used by the V5 dashboard's risk-card to surface the truth behind
    the freshness inspector's "Risk params WARN" pill.
    """
    db = None
    try:
        from services.trading_bot_service import get_trading_bot
        bot = get_trading_bot()
        db = getattr(bot, "_db", None) if bot else None
    except Exception:
        db = None

    payload = compute_effective_risk_caps(db)
    return {"success": True, **payload}


@router.put("/config")
async def update_safety_config(patch: SafetyConfigPatch) -> Dict[str, Any]:
    """Hot-patch any subset of the safety config. Returns effective config."""
    guard = get_safety_guardrails()
    provided = {k: v for k, v in patch.model_dump().items() if v is not None}
    if not provided:
        raise HTTPException(status_code=400, detail="no fields provided")
    effective = guard.update_config(provided)
    logger.info("[SAFETY] Config updated: %s", provided)
    return {"success": True, "config": effective, "updated_keys": list(provided.keys())}


@router.post("/reset-kill-switch")
async def reset_kill_switch() -> Dict[str, Any]:
    """Manual unlock after operator acknowledgement. Trading resumes on next scan."""
    guard = get_safety_guardrails()
    was_active = guard.state.kill_switch_active
    guard.reset_kill_switch()
    return {
        "success": True,
        "was_active": was_active,
        "state": guard.status()["state"],
    }


@router.post("/kill-switch/trip")
async def trip_kill_switch(request: KillSwitchTripRequest) -> Dict[str, Any]:
    """Manual trip — useful for testing or an operator-initiated halt."""
    guard = get_safety_guardrails()
    guard.trip_kill_switch(reason=request.reason)
    return {"success": True, "state": guard.status()["state"]}


# ── v19.34.26 — Scanner power toggle (soft brake) ───────────────────────────
#
# Pauses NEW alert intake without disturbing in-flight evals or open-position
# management. Operator's "water pump off" semantic — quieter than the
# kill-switch, intended for "I'm done finding new ideas for today" use cases.

class ScannerPauseRequest(BaseModel):
    reason: str = Field(default="manual_pause",
                        description="Why the scanner is being paused")


@router.post("/scanner/pause")
async def pause_scanner(request: ScannerPauseRequest) -> Dict[str, Any]:
    """v19.34.26 — Soft brake: stop the scanner from pulling new alerts
    into the eval pipeline. In-flight evals + position management
    continue normally. Persists to Mongo so the latch survives restarts.
    """
    guard = get_safety_guardrails()
    guard.pause_scanner(reason=request.reason)
    return {"success": True, "state": guard.status()["state"]}


@router.post("/scanner/resume")
async def resume_scanner() -> Dict[str, Any]:
    """v19.34.26 — Resume the scanner. Idempotent."""
    guard = get_safety_guardrails()
    was_paused = guard.is_scanner_paused()
    guard.resume_scanner()
    return {
        "success": True,
        "was_paused": was_paused,
        "state": guard.status()["state"],
    }


@router.get("/scanner/status")
async def scanner_status() -> Dict[str, Any]:
    """v19.34.26 — Compact scanner-only status for the UI toggle button."""
    guard = get_safety_guardrails()
    s = guard.status()["state"]
    return {
        "paused": s["scanner_paused"],
        "paused_at": s.get("scanner_paused_at"),
        "reason": s.get("scanner_paused_reason"),
    }
# ──────────────────────────────────────────────────────────────────────────


@router.post("/flatten-all")
async def flatten_all(confirm: str = "") -> Dict[str, Any]:
    """
    Emergency: cancel every pending order and close every open position via
    market orders. Requires `?confirm=FLATTEN` to prevent accidental fires.

    Execution:
      1. Trip the kill-switch (so the bot stops placing new entries even if
         closes take a few seconds).
      2. Fetch every open trade from trading_bot_service and request market
         close via the bot's own close_trade() path — which already knows
         how to route paper vs live.
      3. Attempt to cancel pending (unfilled) order-queue rows in Mongo.

    Returns a summary of actions taken.
    """
    if confirm != "FLATTEN":
        raise HTTPException(
            status_code=400,
            detail="flatten-all requires `?confirm=FLATTEN` query param (safety).",
        )

    guard = get_safety_guardrails()
    # v19.34.32 — "Close/Cancel All" semantic decoupling.
    #
    # Pre-v19.34.32 this endpoint ALSO tripped the kill-switch as a side
    # effect ("flatten = panic stop"). That conflated two distinct
    # operator intents:
    #   1. "clean my books" (close positions + cancel pending) ← flatten
    #   2. "halt trading"  (refuse new entries permanently)    ← kill switch
    # The UI label "Flatten all" implied only #1 but the endpoint also did
    # #2 — so clicking it locked the operator out of new trades until a
    # separate manual reset.
    #
    # Post-fix: this endpoint does EXACTLY #1. Operators who want #2
    # should click the kill-switch separately (or opt in via the
    # "Also halt bot?" checkbox in the confirm modal, which fires a
    # second `/api/safety/kill-switch/trip` call from the frontend).
    #
    # Race guard: we still need to prevent the scan loop from firing a
    # NEW entry while we're iterating through the close list (a race
    # would leave a half-flipped position — close ran, new entry also
    # ran, net-long a symbol the operator thought they flattened). The
    # fix is a SHORT-LIVED (30s TTL, auto-expires) `flatten_in_progress`
    # flag — NOT a sticky kill-switch.
    guard.set_flatten_in_progress(reason="close_cancel_all")

    summary: Dict[str, Any] = {
        "positions_requested_close": 0,
        "positions_succeeded": 0,
        "positions_failed": 0,
        "close_errors": [],
        "orders_cancelled": 0,
        "orders_cancel_errors": [],
    }

    # 1. Close every open trade via the bot's position_manager
    #
    # v19.34.43 (2026-02-XX) — Parallelize the close loop.
    # v19.34.44 (2026-02-XX) — Two further hardening steps after the
    # operator-caught BMNR "Failed: 19/19 close returned False" event.
    # IB pusher logs showed every close was rejected with
    # `Error 201: minimum of 15 orders working on either the buy or
    # sell side for this contract`. Two compounding causes:
    #
    #   (a) The 19 BMNR fragments each had an OCA stop+target bracket
    #       at IB (~38 working SELL orders). The consolidator
    #       collapsed the DB-side rows but those zombie children kept
    #       sitting at IB because their order_ids weren't on the
    #       canonical trade. Result: IB's 15-order-per-side cap was
    #       saturated and every new close MKT got rejected.
    #
    #   (b) Even if (a) were solved, submitting 19 separate close MKTs
    #       for ONE aggregated IB position is wrong — it can only
    #       partially fill (IB has 4,443 sh, can't sell 4,443+more)
    #       and creates spurious overshoot risk.
    #
    # Fix:
    #   1. GROUP open bot_trades by (symbol, direction). One IB position
    #      per group → one close needed.
    #   2. PRE-CANCEL all working orders for the symbol on the close-side
    #      via `ib_direct_service.cancel_all_open_orders_for_symbol`.
    #      Best-effort; if direct IB isn't connected we proceed anyway
    #      (the close MKT may still get rejected — operator will see it
    #      in the close_errors list and can manually cancel via TWS).
    #   3. SUBMIT exactly ONE close MKT per group sized to the SUM of
    #      tracked shares (clamped to IB's authoritative position by
    #      the existing `_clamp_shares_to_ib_position` inside
    #      `close_trade`).
    #   4. Mark every OTHER bot_trade in the group as CLOSED locally
    #      with PnL=0 and reason='consolidated_in_flatten_v19_34_44'
    #      since the canonical close absorbs the entire group's
    #      exposure.
    try:
        from services.trading_bot_service import get_trading_bot_service
        bot = get_trading_bot_service()
        open_trades: List[Any] = list(getattr(bot, "_open_trades", {}).values()) if bot else []
        summary["positions_requested_close"] = len(open_trades)

        # Group by (symbol, direction)
        groups: Dict[tuple, List[Any]] = {}
        for t in open_trades:
            # Defensive: support both BotTrade-like namespaces and legacy
            # dict shapes from older code paths.
            if isinstance(t, dict):
                sym = (t.get("symbol") or "").upper()
                d_raw = t.get("direction")
                d_val = (
                    d_raw.get("value") if isinstance(d_raw, dict)
                    else getattr(d_raw, "value", None) or str(d_raw or "long")
                ).lower()
            else:
                sym = (getattr(t, "symbol", "") or "").upper()
                d = getattr(t, "direction", None)
                d_val = getattr(d, "value", str(d) if d else "long").lower()
            if not sym:
                summary["positions_failed"] += 1
                summary["close_errors"].append({"trade": str(t)[:120], "err": "no symbol"})
                continue
            groups.setdefault((sym, d_val), []).append(t)

        # Pre-cancel zombie working orders on the close-side for each symbol.
        # Best-effort: failures here don't abort the close burst.
        try:
            from services.ib_direct_service import get_ib_direct_service
            ib_direct = get_ib_direct_service()
            # 2s budget for the connect attempt — if direct IB isn't
            # reachable we proceed without zombie cleanup. Ramping the
            # default 15s connect timeout would block flatten-all behind
            # an unreachable IB Gateway.
            try:
                connected = await asyncio.wait_for(
                    ib_direct.ensure_connected(), timeout=2.0,
                )
            except (asyncio.TimeoutError, Exception):
                connected = False
            if connected:
                summary["zombie_cancel_results"] = []
                for (sym, d_val) in groups.keys():
                    close_side = "SELL" if d_val == "long" else "BUY"
                    try:
                        rep = await ib_direct.cancel_all_open_orders_for_symbol(
                            sym, side=close_side,
                        )
                        summary["zombie_cancel_results"].append({
                            "symbol": sym,
                            "side": close_side,
                            "cancelled_count": len(rep.get("cancelled", [])),
                            "errors_count": len(rep.get("errors", [])),
                        })
                    except Exception as e:
                        summary["zombie_cancel_results"].append({
                            "symbol": sym, "side": close_side, "err": str(e)[:200],
                        })
                # Brief settle so IB's order book reflects the cancels
                # before we slam new MKTs in.
                await asyncio.sleep(1.0)
            else:
                summary["zombie_cancel_results"] = [{"err": "ib_direct_not_connected"}]
        except Exception as e:
            summary["zombie_cancel_results"] = [{"err": f"pre_cancel_step_failed: {str(e)[:200]}"}]

        # Helper: close one (symbol, direction) group via canonical pick.
        async def _close_one_group(group_trades):
            # Defensive: dict-shaped legacy trades — close each by id without
            # mutation (no share mutation possible on a dict).
            if any(isinstance(t, dict) for t in group_trades):
                succeeded = 0
                failed_errs: List[Dict[str, Any]] = []
                for t in group_trades:
                    if isinstance(t, dict):
                        tid = t.get("id") or t.get("trade_id")
                    else:
                        tid = getattr(t, "id", None) or getattr(t, "trade_id", None)
                    if not tid:
                        failed_errs.append({"trade": str(t)[:120], "err": "no trade_id"})
                        continue
                    try:
                        ok = await bot.close_trade(tid, reason="emergency_flatten_all")
                        if ok:
                            succeeded += 1
                        else:
                            failed_errs.append({"trade_id": tid, "err": "close returned False"})
                    except Exception as e:
                        failed_errs.append({"trade_id": tid, "err": str(e)[:200]})
                return {
                    "group_status": "legacy_dict_path",
                    "succeeded": succeeded > 0,
                    "succeeded_count": succeeded,
                    "failed_errs": failed_errs,
                    "siblings_marked_closed": [],
                }

            # Canonical = oldest non-reconciled (matches consolidator
            # logic). Falls back to oldest period if all reconciled.
            def _ts_key(t):
                for attr in ("entry_time", "executed_at", "created_at"):
                    v = getattr(t, attr, None)
                    if v:
                        return str(v)
                return ""

            def _is_reconciled(t):
                eb = (getattr(t, "entered_by", "") or "")
                st = (getattr(t, "setup_type", "") or "")
                return (
                    eb.startswith("reconciled_excess")
                    or eb == "reconciled_external"
                    or st in ("reconciled_excess_slice", "reconciled_orphan", "imported_from_ib")
                )

            non_recon = [t for t in group_trades if not _is_reconciled(t)]
            pool = non_recon or group_trades
            canonical = sorted(pool, key=_ts_key)[0]
            siblings = [t for t in group_trades if t is not canonical]

            # Roll the SUM of all sibling shares onto canonical so the
            # close MKT is sized correctly for the aggregated IB position.
            total_shares = sum(
                int(abs(getattr(t, "remaining_shares", 0) or 0))
                for t in group_trades
            )
            old_canonical_shares = int(abs(getattr(canonical, "remaining_shares", 0) or 0))
            canonical.remaining_shares = total_shares
            try:
                canonical.shares = total_shares
            except Exception:
                pass

            canonical_id = getattr(canonical, "id", None) or getattr(canonical, "trade_id", None)
            if not canonical_id:
                return {
                    "group_status": "no_canonical_id",
                    "siblings_marked_closed": [],
                    "succeeded": False,
                }

            try:
                ok = await bot.close_trade(canonical_id, reason="emergency_flatten_all")
            except Exception as e:
                # Restore canonical shares so the manage loop can retry
                # cleanly.
                try:
                    canonical.remaining_shares = old_canonical_shares
                    canonical.shares = old_canonical_shares
                except Exception:
                    pass
                return {
                    "group_status": "close_raised",
                    "canonical_id": canonical_id,
                    "err": str(e)[:200],
                    "siblings_marked_closed": [],
                    "succeeded": False,
                }

            if not ok:
                # Canonical didn't close. Restore canonical shares so
                # the manage loop / next flatten attempt can retry.
                try:
                    canonical.remaining_shares = old_canonical_shares
                    canonical.shares = old_canonical_shares
                except Exception:
                    pass
                # v19.34.119 — Surface the actual broker error so the
                # operator's "Close all" failure list isn't an opaque
                # `close_returned_false`. Read the transient stash
                # position_manager.close_trade set before returning False.
                broker_err = (
                    getattr(canonical, "_last_close_error", None)
                    or "close_trade returned False (no broker error stashed)"
                )
                return {
                    "group_status": "close_returned_false",
                    "canonical_id": canonical_id,
                    "broker_err": broker_err,
                    "siblings_marked_closed": [],
                    "succeeded": False,
                }

            # Canonical closed successfully → siblings absorbed. Mark
            # them closed with PnL=0 + reason for audit.
            from services.trading_bot_service import TradeStatus
            now_iso = datetime.now(timezone.utc).isoformat()
            sibs_closed: List[str] = []
            for s in siblings:
                try:
                    s.status = TradeStatus.CLOSED
                    s.remaining_shares = 0
                    s.realized_pnl = 0.0
                    s.unrealized_pnl = 0.0
                    s.close_reason = "consolidated_in_flatten_v19_34_44"
                    s.closed_at = now_iso
                    s.exit_time = datetime.now(timezone.utc)
                    s.exit_reason = "consolidated_in_flatten_v19_34_44"
                    s.exit_price = float(getattr(s, "fill_price", 0) or 0)
                    s.stop_order_id = None
                    s.target_order_id = None
                    try:
                        s.target_order_ids = []
                    except Exception:
                        pass
                    s.oca_group = None
                    s.notes = (getattr(s, "notes", "") or "") + (
                        f" [v19.34.44: rolled into canonical {canonical_id} during flatten]"
                    )
                    sib_id = getattr(s, "id", None)
                    if sib_id:
                        sibs_closed.append(sib_id)
                        if hasattr(bot, "_open_trades"):
                            bot._open_trades.pop(sib_id, None)
                        if hasattr(bot, "_closed_trades"):
                            try:
                                bot._closed_trades.append(s)
                            except Exception:
                                pass
                    save_fn = getattr(bot, "_save_trade", None) or getattr(bot, "_persist_trade", None)
                    if save_fn:
                        try:
                            res = save_fn(s)
                            if asyncio.iscoroutine(res):
                                await res
                        except Exception:
                            pass
                except Exception as ex:
                    logger.warning(
                        "[v19.34.44 flatten-group] sibling close mutate failed for %s: %s",
                        getattr(s, "id", "?"), ex,
                    )
            return {
                "group_status": "ok",
                "canonical_id": canonical_id,
                "siblings_marked_closed": sibs_closed,
                "old_canonical_shares": old_canonical_shares,
                "total_closed_shares": total_shares,
                "succeeded": True,
            }

        # Run groups concurrently across DIFFERENT symbols (cap=8 still
        # safe; same-symbol parallelism is no longer an issue since each
        # symbol gets exactly ONE close MKT).
        sem = asyncio.Semaphore(8)

        async def _bounded_group(group_trades):
            async with sem:
                return await _close_one_group(group_trades)

        if groups:
            group_results = await asyncio.gather(
                *[_bounded_group(g) for g in groups.values()],
                return_exceptions=False,
            )
            summary["group_results"] = group_results
            for gres in group_results:
                # Legacy dict-path returns a different shape.
                if gres.get("group_status") == "legacy_dict_path":
                    summary["positions_succeeded"] += int(gres.get("succeeded_count", 0))
                    for e in gres.get("failed_errs", []):
                        summary["positions_failed"] += 1
                        summary["close_errors"].append(e)
                    continue
                if gres.get("succeeded"):
                    sib_count = len(gres.get("siblings_marked_closed", []))
                    summary["positions_succeeded"] += 1 + sib_count
                else:
                    grp_size = next(
                        (len(g) for g in groups.values()
                         if any(getattr(t, "id", None) == gres.get("canonical_id") for t in g)),
                        1,
                    )
                    summary["positions_failed"] += grp_size
                    summary["close_errors"].append({
                        "trade_id": gres.get("canonical_id"),
                        "err": (
                            f"{gres.get('group_status', 'unknown')}: "
                            f"{gres.get('err', 'close returned False')}"
                        ),
                    })
    except Exception as e:
        logger.error("[SAFETY] flatten-all: close-positions step crashed: %s", e)
        summary["close_errors"].append({"stage": "close-positions", "err": str(e)[:200]})

    # ── v19.34.119 (Feb 2026) — Auto-chain to nuclear + pusher fallback ──
    # Pre-v119, if the primary `bot.close_trade()` path returned False
    # for every group (the BMNR/ONON pattern: IB Error 201 working-order
    # cap, "managedAccounts" stripped after a TWS login kicked the
    # session, or pusher RPC timeout), the endpoint surfaced 26 ×
    # `close_returned_false` and the operator was stranded — the
    # secondary `/emergency-flatten-ib` endpoint required `ib_direct`
    # connected, but the same condition that broke the primary path
    # often also degraded clientId=11.
    #
    # Post-v119: when the primary loop finishes with zero closes
    # succeeded AND positions were requested, this block runs two
    # additional attempts BEFORE returning to the operator:
    #
    #   1. NUCLEAR (clientId=11 direct path)
    #      `_attempt_emergency_flatten_ib_inline()` — same logic as
    #      `/api/safety/emergency-flatten-ib` but inlined here so the
    #      caller doesn't need to know about two endpoints.
    #
    #   2. PUSHER-FALLBACK (clientId=15 cancel-queue path)
    #      `_pusher_fallback_close_groups()` — enumerates every
    #      pusher-placed working order via MongoDB `order_queue`,
    #      enqueues cancellations via `queue_cancellation`, waits for
    #      the cap to clear, then retries `bot.close_trade()` per
    #      group. This path works even when `ib_direct` is fully
    #      offline (heartbeat failure, login conflict, etc.).
    #
    # Order matters: nuclear is faster + atomic when available; pusher
    # fallback is universally available but slower (~10s wait for IB to
    # process the cancel-queue burst).
    if (
        summary["positions_requested_close"] > 0
        and summary["positions_succeeded"] == 0
    ):
        logger.error(
            "[SAFETY v19.34.119] Primary flatten returned 0/%d successes — "
            "auto-chaining nuclear (ib_direct) + pusher-fallback paths",
            summary["positions_requested_close"],
        )
        summary["auto_chain_v19_34_119"] = {"attempted": [], "succeeded": []}

        # Attempt 1: Nuclear (ib_direct clientId=11)
        try:
            nuclear_result = await _attempt_emergency_flatten_ib_inline(
                target_symbols=None,
            )
            summary["auto_chain_v19_34_119"]["attempted"].append("nuclear")
            summary["auto_chain_v19_34_119"]["nuclear_result"] = nuclear_result
            if nuclear_result.get("success"):
                # Re-count successes from per-symbol close outcomes.
                closes = (nuclear_result.get("summary") or {}).get("closes") or []
                n_ok = sum(1 for c in closes if c.get("close_success"))
                if n_ok > 0:
                    summary["positions_succeeded"] += n_ok
                    summary["positions_failed"] = max(
                        0, summary["positions_failed"] - n_ok,
                    )
                    summary["auto_chain_v19_34_119"]["succeeded"].append("nuclear")
                    logger.warning(
                        "[SAFETY v19.34.119] Nuclear path closed %d positions",
                        n_ok,
                    )
        except Exception as nuc_err:
            logger.error("[SAFETY v19.34.119] Nuclear auto-chain crashed: %s", nuc_err)
            summary["auto_chain_v19_34_119"]["nuclear_error"] = str(nuc_err)[:300]

        # Attempt 2: Pusher fallback — only if nuclear didn't fully resolve
        if summary["positions_succeeded"] < summary["positions_requested_close"]:
            try:
                pusher_result = await _pusher_fallback_close_groups(
                    bot=bot, groups=groups,
                )
                summary["auto_chain_v19_34_119"]["attempted"].append("pusher_fallback")
                summary["auto_chain_v19_34_119"]["pusher_fallback_result"] = pusher_result
                n_ok = pusher_result.get("succeeded_count", 0)
                if n_ok > 0:
                    summary["positions_succeeded"] += n_ok
                    summary["positions_failed"] = max(
                        0, summary["positions_failed"] - n_ok,
                    )
                    summary["auto_chain_v19_34_119"]["succeeded"].append("pusher_fallback")
                    logger.warning(
                        "[SAFETY v19.34.119] Pusher-fallback closed %d positions",
                        n_ok,
                    )
            except Exception as pf_err:
                logger.error("[SAFETY v19.34.119] Pusher-fallback crashed: %s", pf_err)
                summary["auto_chain_v19_34_119"]["pusher_fallback_error"] = str(pf_err)[:300]

    # 2. Cancel every pending (unfilled) bracket in Mongo's order_queue
    try:
        import motor.motor_asyncio
        import os
        client = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ.get("DB_NAME", "tradecommand")]
        res = await db.order_queue.update_many(
            {"status": {"$in": ["pending", "queued", "submitted"]}},
            {"$set": {"status": "cancelled", "cancel_reason": "emergency_flatten_all"}},
        )
        summary["orders_cancelled"] = int(getattr(res, "modified_count", 0) or 0)
    except Exception as e:
        logger.error("[SAFETY] flatten-all: cancel-queue step crashed: %s", e)
        summary["orders_cancel_errors"].append(str(e)[:200])

    # v19.34.25 (2026-02-XX) — Envelope honesty. Pre-fix the response
    # was hardcoded `success: True`, so the v19.34.24b import bug (which
    # caused `positions_requested_close: 0` + a `stage: "close-positions"`
    # error) returned a green-checkmark envelope to the operator while
    # the bot did literally nothing. The frontend banner keys off
    # `success` for its colour, so a `True` here paints "flatten-all
    # initiated" green and the operator reasonably assumes flatten ran.
    #
    # Rules: success is False if EITHER
    #   (a) the close-positions step itself crashed (a `stage` entry in
    #       close_errors) — flatten never even iterated, or
    #   (b) at least one position was requested AND zero succeeded — the
    #       loop ran but every close failed.
    # In both cases the operator must know flatten didn't do its job.
    closure_step_crashed = any(
        e.get("stage") == "close-positions" for e in summary["close_errors"]
    )
    every_close_failed = (
        summary["positions_requested_close"] > 0
        and summary["positions_succeeded"] == 0
    )
    success = not (closure_step_crashed or every_close_failed)

    if not success:
        logger.error(
            "[SAFETY] FLATTEN-ALL FAILED: requested=%d succeeded=%d failed=%d "
            "close_errors=%s",
            summary["positions_requested_close"],
            summary["positions_succeeded"],
            summary["positions_failed"],
            summary["close_errors"][:3],   # cap for log readability
        )
    else:
        logger.warning("[SAFETY] FLATTEN-ALL complete: %s", summary)

    # v19.34.32 — Release the race guard as soon as iteration finishes.
    # The TTL is a failsafe (for a crashed endpoint / network-dropped
    # client); on the happy path we drop it immediately so the operator's
    # bot can re-enter on its very next scan tick.
    guard.clear_flatten_in_progress()

    return {"success": success, "summary": summary, "state": guard.status()["state"]}



# ── v19.34.119 (Feb 2026) — Auto-chain helpers + diagnose-close-readiness ──
#
# Shipped after the live "26 / 26 close_returned_false" incident where
# the operator clicked "Close all" with 26 day_2_continuation shorts open
# and every group failed silently. Both the primary path (bot.close_trade
# via pusher) AND the secondary path (`/emergency-flatten-ib` via
# ib_direct) returned no successes because:
#   • Working-order cap (IB Error 201) had saturated → pusher rejected
#     every close MKT, AND
#   • clientId=11 socket was flapping → nuclear endpoint couldn't run.
# The operator had to flatten manually in TWS. These helpers are the
# resilience layer: PRE-FLIGHT diagnostic + AUTO-CHAIN nuclear + pusher
# fallback that bypasses ib_direct entirely.

async def _attempt_emergency_flatten_ib_inline(
    target_symbols: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """v19.34.119 — Same logic as the `/emergency-flatten-ib` endpoint,
    callable directly from `/flatten-all` so the operator doesn't need
    to know about two endpoints. Returns the endpoint's response dict
    verbatim. Failure (ib_direct not connected, no IB positions, etc.)
    is non-fatal — the caller falls back to pusher-fallback."""
    summary: Dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ib_snapshot": [], "closes": [], "errors": [],
    }
    try:
        from services.ib_direct_service import get_ib_direct_service
        ib_direct = get_ib_direct_service()
        try:
            connected = await asyncio.wait_for(
                ib_direct.ensure_connected(), timeout=3.0,
            )
        except (asyncio.TimeoutError, Exception):
            connected = False
        if not connected:
            return {
                "success": False,
                "error": "ib_direct_service not connected (clientId=11 down)",
                "summary": summary,
            }
        if not ib_direct.is_authorized_to_trade():
            return {
                "success": False,
                "error": "ib_direct connected but NOT authorized to trade — managedAccounts empty (likely TWS login conflict)",
                "summary": summary,
            }
        positions = await ib_direct.get_positions()
        filter_set = (
            {s.upper() for s in target_symbols} if target_symbols else None
        )
        positions = [
            p for p in positions
            if abs(float(p.get("position") or 0)) > 0
            and (filter_set is None or (p.get("symbol") or "").upper() in filter_set)
        ]
        summary["ib_snapshot"] = positions
        if not positions:
            return {"success": True, "message": "no IB positions", "summary": summary}
        for p in positions:
            sym = (p.get("symbol") or "").upper()
            qty = abs(int(round(float(p.get("position") or 0))))
            side_long = float(p.get("position") or 0) > 0
            close_action = "SELL" if side_long else "BUY"
            entry: Dict[str, Any] = {
                "symbol": sym, "qty": qty, "close_action": close_action,
            }
            try:
                cancel_rep = await ib_direct.cancel_all_open_orders_for_symbol(
                    sym, side=close_action,
                )
                entry["zombie_cancelled"] = len(cancel_rep.get("cancelled", []))
                await asyncio.sleep(0.5)
                mkt_rep = await ib_direct.place_market_order(sym, close_action, qty)
                entry["close_status"] = mkt_rep.get("status")
                entry["close_success"] = bool(mkt_rep.get("success"))
                if not mkt_rep.get("success"):
                    entry["close_error"] = mkt_rep.get("error")
            except Exception as e:
                entry["close_success"] = False
                entry["close_error"] = str(e)[:200]
            summary["closes"].append(entry)
        any_success = any(c.get("close_success") for c in summary["closes"])
        return {"success": any_success, "summary": summary}
    except Exception as e:
        logger.error("[v19.34.119] inline-nuclear crashed: %s", e, exc_info=True)
        return {"success": False, "error": str(e)[:200], "summary": summary}


async def _pusher_fallback_close_groups(
    bot, groups: Dict[tuple, List[Any]],
) -> Dict[str, Any]:
    """v19.34.119 — Pusher-only fallback that doesn't need ib_direct.

    Strategy:
      1. Enumerate every pusher-placed order for the affected symbols
         from MongoDB `order_queue` (the pusher records `ib_order_id`
         on every successful submit). Find still-working bracket
         children on the close-side.
      2. Enqueue cancellations via `queue_cancellation(ib_order_id)`.
         The pusher polls `/api/ib/cancellations/pending` every ~5s
         and cancels each via `self.ib.cancelOrder(...)`.
      3. Wait ~10s for cancellations to land at IB and free up the
         15-orders-per-side cap.
      4. Retry `bot.close_trade()` per group.

    Returns: {succeeded_count, failed_count, attempts: [...]}
    """
    import os
    import motor.motor_asyncio
    from routers.ib import queue_cancellation

    result: Dict[str, Any] = {
        "succeeded_count": 0, "failed_count": 0,
        "cancellations_queued": 0, "groups": [],
    }

    affected_syms = {sym.upper() for (sym, _d) in groups.keys() if sym}
    if not affected_syms:
        return result

    # Step 1+2 — enumerate + queue cancels
    try:
        mongo_url = os.environ.get("MONGO_URL")
        if not mongo_url:
            raise RuntimeError("MONGO_URL not set")
        client = motor.motor_asyncio.AsyncIOMotorClient(mongo_url)
        db = client[os.environ.get("DB_NAME", "tradecommand")]
        cur = db.order_queue.find(
            {
                "symbol": {"$in": list(affected_syms)},
                "ib_order_id": {"$ne": None},
                "status": {"$in": ["filled", "pending", "submitted", "queued"]},
            },
            {"_id": 0, "ib_order_id": 1, "symbol": 1, "action": 1, "status": 1},
        )
        async for row in cur:
            try:
                queue_cancellation(
                    ib_order_id=int(row["ib_order_id"]),
                    reason="v19_34_119_pusher_fallback_precancel",
                    requested_by="safety_router_auto_chain",
                )
                result["cancellations_queued"] += 1
            except Exception as q_err:
                logger.debug(
                    "[v19.34.119 pusher_fallback] cancel-queue failed for "
                    "ib_order_id=%s: %s", row.get("ib_order_id"), q_err,
                )
    except Exception as enum_err:
        logger.error(
            "[v19.34.119 pusher_fallback] enumerate working orders failed: %s",
            enum_err,
        )

    # Step 3 — let pusher chew through the cancellations (5s poll cadence
    # so 10s is enough for one poll + one cancel round trip per order).
    if result["cancellations_queued"] > 0:
        await asyncio.sleep(10.0)

    # Step 4 — retry closes per group
    for (sym, _d_val), trades in groups.items():
        if not trades:
            continue
        # Pick canonical = oldest non-reconciled, same as primary path.
        def _ts(t):
            for attr in ("entry_time", "executed_at", "created_at"):
                v = getattr(t, attr, None)
                if v:
                    return str(v)
            return ""
        non_recon = [
            t for t in trades
            if not (getattr(t, "entered_by", "") or "").startswith("reconciled_excess")
        ]
        pool = non_recon or trades
        canonical = sorted(pool, key=_ts)[0]
        tid = getattr(canonical, "id", None) or getattr(canonical, "trade_id", None)
        if not tid:
            continue
        attempt: Dict[str, Any] = {"symbol": sym, "trade_id": tid}
        try:
            # Reset the stashed last_close_error so we get fresh signal
            try:
                canonical._last_close_error = None
            except Exception:
                pass
            ok = await bot.close_trade(tid, reason="v19_34_119_pusher_fallback")
            attempt["ok"] = bool(ok)
            if ok:
                result["succeeded_count"] += 1
            else:
                result["failed_count"] += 1
                attempt["err"] = getattr(canonical, "_last_close_error", None) or "close returned False"
        except Exception as e:
            attempt["ok"] = False
            attempt["err"] = str(e)[:200]
            result["failed_count"] += 1
        result["groups"].append(attempt)

    return result


@router.get("/diagnose-close-readiness")
@router.post("/diagnose-close-readiness")
async def diagnose_close_readiness() -> Dict[str, Any]:
    """v19.34.119 — Pre-flight before clicking 'Close all'.

    Shipped after the 26/26 incident — the operator needs to know
    BEFORE clicking the button whether the close paths will actually
    work, and which one will run. Surfaces every signal that gates the
    flatten-all auto-chain:

      • pusher_connected         (clientId=15 close path)
      • ib_direct_connected      (clientId=11 nuclear path)
      • ib_direct_authorized     (managedAccounts non-empty)
      • per-symbol working-order count + close-side count (IB Error 201)
      • bot._open_trades vs IB-actual position divergence
      • close-readiness verdict: green / yellow / red

    Returns:
      {
        "verdict": "green" | "yellow" | "red",
        "summary": "...",
        "pusher": {connected, ...},
        "ib_direct": {connected, authorized, ...},
        "open_positions": {bot_count, ib_count, ...},
        "working_orders_by_symbol": [
          {"symbol": "ONON", "close_side": "BUY", "working_count": 18,
           "near_cap": true, "over_cap": true},
          ...
        ],
        "expected_path": "primary | nuclear | pusher_fallback",
      }
    """
    out: Dict[str, Any] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "pusher": {}, "ib_direct": {},
        "open_positions": {}, "working_orders_by_symbol": [],
    }
    issues: List[str] = []

    # Pusher health
    try:
        from routers.ib import is_pusher_connected, _pushed_ib_data
        out["pusher"]["connected"] = bool(is_pusher_connected())
        if not out["pusher"]["connected"]:
            issues.append("pusher (clientId=15) NOT connected")
    except Exception as e:
        out["pusher"]["error"] = str(e)[:200]
        issues.append(f"pusher health check failed: {str(e)[:80]}")

    # IB-direct health
    try:
        from services.ib_direct_service import get_ib_direct_service
        ibd = get_ib_direct_service()
        ibd_connected = ibd.is_connected()
        ibd_authorized = ibd.is_authorized_to_trade()
        out["ib_direct"] = {
            "connected": ibd_connected,
            "authorized_to_trade": ibd_authorized,
            "status": ibd.status(),
        }
        if not ibd_connected:
            issues.append("ib_direct (clientId=11) NOT connected — nuclear path unavailable")
        elif not ibd_authorized:
            issues.append("ib_direct connected but NOT authorized (managedAccounts empty — TWS login conflict?)")
    except Exception as e:
        out["ib_direct"]["error"] = str(e)[:200]
        issues.append(f"ib_direct probe failed: {str(e)[:80]}")

    # Bot open-trades vs IB positions
    bot = None
    open_trades: List[Any] = []
    try:
        from services.trading_bot_service import get_trading_bot_service
        bot = get_trading_bot_service()
        open_trades = list(getattr(bot, "_open_trades", {}).values()) if bot else []
        out["open_positions"]["bot_open_count"] = len(open_trades)
    except Exception as e:
        out["open_positions"]["bot_error"] = str(e)[:200]

    try:
        if out["ib_direct"].get("connected"):
            from services.ib_direct_service import get_ib_direct_service
            ibd_positions = await get_ib_direct_service().get_positions()
            ibd_positions = [
                p for p in ibd_positions if abs(float(p.get("position") or 0)) > 0
            ]
            out["open_positions"]["ib_direct_count"] = len(ibd_positions)
            out["open_positions"]["ib_direct_symbols"] = [
                p.get("symbol") for p in ibd_positions
            ]
    except Exception as e:
        out["open_positions"]["ib_direct_error"] = str(e)[:200]

    # Working orders per symbol per close-side — the Error 201 trigger
    try:
        import os
        import motor.motor_asyncio
        mongo_url = os.environ.get("MONGO_URL")
        if not mongo_url:
            raise RuntimeError("MONGO_URL not set")
        client = motor.motor_asyncio.AsyncIOMotorClient(mongo_url)
        db = client[os.environ.get("DB_NAME", "tradecommand")]

        # Build symbol → expected close-side from bot._open_trades
        symbol_close_side: Dict[str, str] = {}
        for t in open_trades:
            sym = (getattr(t, "symbol", "") or "").upper()
            d = getattr(t, "direction", None)
            dv = getattr(d, "value", str(d) if d else "long").lower()
            if sym:
                symbol_close_side[sym] = "SELL" if dv == "long" else "BUY"
        if not symbol_close_side:
            out["working_orders_by_symbol"] = []
        else:
            for sym, close_side in symbol_close_side.items():
                # All working (filled-bracket-children or pending) orders
                # on the close-side for this symbol. `filled` is the
                # parent fill that spawned the OCA children which then
                # sit WORKING — that's what counts toward Error 201.
                count = await db.order_queue.count_documents({
                    "symbol": sym,
                    "ib_order_id": {"$ne": None},
                    "status": {"$in": ["filled", "pending", "submitted", "queued"]},
                })
                row = {
                    "symbol": sym,
                    "close_side": close_side,
                    "working_count": int(count),
                    "near_cap": count >= 12,
                    "over_cap": count >= 15,
                }
                out["working_orders_by_symbol"].append(row)
                if row["over_cap"]:
                    issues.append(
                        f"{sym}: {count} working orders ≥ 15-cap — IB Error 201 imminent"
                    )
                elif row["near_cap"]:
                    issues.append(
                        f"{sym}: {count} working orders (close to 15-cap)"
                    )
    except Exception as e:
        out["working_orders_error"] = str(e)[:200]

    # Verdict + expected path
    over_cap_count = sum(
        1 for r in out["working_orders_by_symbol"] if r.get("over_cap")
    )
    if over_cap_count > 0 or not out["pusher"].get("connected"):
        verdict = "red"
        if not out["pusher"].get("connected") and not out["ib_direct"].get("connected"):
            expected_path = "none — both paths down"
        elif over_cap_count > 0:
            expected_path = "pusher_fallback (auto-cancel working orders first)"
        else:
            expected_path = "nuclear (ib_direct)" if out["ib_direct"].get("connected") else "pusher_fallback"
    elif issues:
        verdict = "yellow"
        expected_path = "primary (with auto-chain ready)"
    else:
        verdict = "green"
        expected_path = "primary"

    out["verdict"] = verdict
    out["expected_path"] = expected_path
    out["issues"] = issues
    out["summary"] = (
        f"{verdict.upper()}: {len(issues)} issue(s). "
        f"Expected close path: {expected_path}."
    )
    return out




# ─── v19.34.45 — Nuclear emergency-flatten via direct IB ────────────
@router.post("/emergency-flatten-ib")
async def emergency_flatten_ib(payload: Optional[Dict[str, Any]] = None):
    """**Nuclear option.** Flattens whatever IB *actually shows* via the
    direct IB API, bypassing the bot's `_open_trades` bookkeeping
    entirely. Use when:
      • Regular flatten reports success but IB still has positions
        (bot's view diverged from IB reality), OR
      • A symbol exists at IB that the bot never tracked, OR
      • Operator just wants brute-force "close every position".

    Steps per held symbol at IB:
      1. cancel_all_open_orders_for_symbol(sym, close-side)
      2. place_market_order(sym, close-action, abs(position))

    Body:
      {
        "confirm": "FLATTEN_IB",          // required
        "symbols": ["BMNR", "PG"],        // optional whitelist
        "include_kill_switch": false      // optional
      }

    Requires `ib_direct_service` connected. If not, returns a clear
    error and does nothing — operator must close manually via TWS.
    """
    payload = payload or {}
    if payload.get("confirm") != "FLATTEN_IB":
        raise HTTPException(400, "confirm='FLATTEN_IB' required")

    target_syms_filter: Optional[set] = None
    if isinstance(payload.get("symbols"), list) and payload["symbols"]:
        target_syms_filter = {s.upper() for s in payload["symbols"]}

    summary: Dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ib_snapshot": [], "closes": [], "errors": [],
    }

    try:
        from services.ib_direct_service import get_ib_direct_service
        ib_direct = get_ib_direct_service()
        try:
            connected = await asyncio.wait_for(
                ib_direct.ensure_connected(), timeout=3.0,
            )
        except (asyncio.TimeoutError, Exception):
            connected = False
        if not connected:
            return {
                "success": False,
                "error": (
                    "ib_direct_service not connected — cannot run "
                    "nuclear flatten. Enable direct IB "
                    "(IB_DIRECT_ENABLED=true + clientId=11) or close "
                    "manually via TWS."
                ),
                "summary": summary,
            }

        positions = await ib_direct.get_positions()
        positions = [
            p for p in positions
            if abs(float(p.get("position") or 0)) > 0
            and (target_syms_filter is None
                 or (p.get("symbol") or "").upper() in target_syms_filter)
        ]
        summary["ib_snapshot"] = positions
        if not positions:
            return {
                "success": True,
                "message": "no IB positions matching criteria — nothing to flatten",
                "summary": summary,
            }

        for p in positions:
            sym = (p.get("symbol") or "").upper()
            qty = abs(int(round(float(p.get("position") or 0))))
            side_long = float(p.get("position") or 0) > 0
            close_action = "SELL" if side_long else "BUY"
            entry: Dict[str, Any] = {
                "symbol": sym, "qty": qty,
                "side": "long" if side_long else "short",
                "close_action": close_action,
            }
            try:
                cancel_rep = await ib_direct.cancel_all_open_orders_for_symbol(
                    sym, side=close_action,
                )
                entry["zombie_cancelled"] = len(cancel_rep.get("cancelled", []))
                entry["zombie_errors"] = cancel_rep.get("errors", [])
                await asyncio.sleep(0.5)
                mkt_rep = await ib_direct.place_market_order(
                    sym, close_action, qty,
                )
                entry["close_order_id"] = mkt_rep.get("order_id")
                entry["close_status"] = mkt_rep.get("status")
                entry["close_success"] = bool(mkt_rep.get("success"))
                if not mkt_rep.get("success"):
                    entry["close_error"] = mkt_rep.get("error")
                    summary["errors"].append({
                        "symbol": sym, "stage": "place_market_order",
                        "err": mkt_rep.get("error"),
                    })
            except Exception as e:
                entry["close_success"] = False
                entry["close_error"] = str(e)[:200]
                summary["errors"].append({
                    "symbol": sym, "stage": "exception", "err": str(e)[:200],
                })
            summary["closes"].append(entry)

        if payload.get("include_kill_switch"):
            try:
                guard = get_safety_guardrails()
                guard.trip_kill_switch(reason="emergency_flatten_ib_v19_34_45")
            except Exception as e:
                summary["errors"].append({
                    "symbol": "—", "stage": "kill_switch_trip",
                    "err": str(e)[:200],
                })

        any_success = any(c.get("close_success") for c in summary["closes"])
        return {
            "success": any_success,
            "summary": summary,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error("[SAFETY] emergency-flatten-ib crashed: %s", e, exc_info=True)
        summary["errors"].append({"stage": "top-level", "err": str(e)[:300]})
        return {"success": False, "summary": summary, "error": str(e)[:300]}


# ─── v19.34.66 — Orphan GTC reconciler ────────────────────────────────────
#
# Long-missing audit pass on the bot's order management surface. Triggered
# by 2026-02-09 forensic: the user had 10 GTC sell-side bracket legs from
# 5/4 sitting at IB after multiple bot restarts. The bot had completely
# lost track of them; their only remaining footprint was at IB. If any
# stop had triggered, IB would have shorted the user without protection.
#
# This pair of endpoints surfaces the audit (read-only) and provides a
# safe one-shot cleanup (acts only on `naked_no_position` and
# `orphan_no_trade` verdicts — the two unambiguously-dangerous classes).


class CancelOrphanGtcRequest(BaseModel):
    """Cancel orphan/naked GTC orders by IB order_id.

    The endpoint re-runs classification before cancelling each id, so
    the verdict is always fresh — protects against a stale UI sending
    a cancel request after a position has been re-opened.
    """
    ib_order_ids: List[int] = Field(
        ..., min_length=1,
        description="IB order_ids to cancel. Each must classify as "
                    "`naked_no_position` or `orphan_no_trade` at the "
                    "moment of the request.",
    )
    confirm: str = Field(
        ..., description="Must equal 'CANCEL_ORPHANS' to fire.",
    )


@router.get("/orphan-gtc-orders")
async def orphan_gtc_orders():
    """v19.34.66 — Read-only audit of every working GTC at IB.

    Joins IB open orders × IB positions × `bot_trades` and classifies
    each working GTC into:

        tracked              — order matches a bot trade with a real position (OK)
        naked_no_position    — IB has no position; order would short on trigger (DANGEROUS)
        orphan_no_trade      — bot has no trade row referencing this order_id
        mismatched_size      — order qty exceeds the IB position size (over-protection)

    Returns the full verdict table + a summary count per class. Never
    raises; failure modes return success=False with the data-source
    diagnostic populated.

    Use case: V5 HUD pill shows red if `summary.naked_no_position > 0
    or summary.orphan_no_trade > 0`. One-click "Cancel all confirmed
    orphans" button calls `POST /api/safety/cancel-orphan-gtc` with
    the matching `ib_order_id`s.
    """
    try:
        from services.orphan_gtc_reconciler import audit_orphan_gtc_orders
        from services.trading_bot_service import get_trading_bot_service
        bot = None
        try:
            bot = get_trading_bot_service()
        except Exception:
            pass
        result = await audit_orphan_gtc_orders(bot=bot)
        return result
    except Exception as e:
        logger.error("[v19.34.66] orphan-gtc-orders endpoint crashed: %s", e, exc_info=True)
        return {
            "success": False,
            "reason": f"{type(e).__name__}: {str(e)[:200]}",
            "verdicts": [],
            "summary": {},
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }


@router.post("/cancel-orphan-gtc")
async def cancel_orphan_gtc(req: CancelOrphanGtcRequest):
    """v19.34.66 — Cancel a list of pre-classified orphan/naked GTCs.

    Re-classifies before cancelling — the verdict at request time is
    re-validated at action time so a stale UI can't fire cancels on
    orders that have since become tracked.

    Refuses anything that classifies as `tracked` or `mismatched_size`
    — those need operator review. Returns a per-order outcome list.
    """
    if req.confirm != "CANCEL_ORPHANS":
        raise HTTPException(
            status_code=400,
            detail="confirm field must equal 'CANCEL_ORPHANS' (safety).",
        )

    from services.orphan_gtc_reconciler import (
        OrderVerdict,
        SAFE_TO_AUTO_CANCEL,
        audit_orphan_gtc_orders,
        cancel_orphan_gtc_orders,
    )
    from services.trading_bot_service import get_trading_bot_service
    bot = None
    try:
        bot = get_trading_bot_service()
    except Exception:
        pass

    audit = await audit_orphan_gtc_orders(bot=bot)
    if not audit.get("success"):
        raise HTTPException(
            status_code=503,
            detail=f"audit failed: {audit.get('reason', 'unknown')}",
        )

    requested_ids = {int(x) for x in req.ib_order_ids}
    matched_verdicts: List[OrderVerdict] = []
    not_found: List[int] = []
    not_safe: List[Dict[str, Any]] = []

    for v_dict in audit.get("verdicts", []):
        if int(v_dict.get("ib_order_id", 0)) not in requested_ids:
            continue
        # Reconstruct OrderVerdict from dict for the cancellation helper.
        ov = OrderVerdict(
            ib_order_id=int(v_dict["ib_order_id"]),
            perm_id=v_dict.get("perm_id"),
            symbol=v_dict.get("symbol", ""),
            action=v_dict.get("action", ""),
            quantity=int(v_dict.get("quantity", 0)),
            order_type=v_dict.get("order_type", ""),
            limit_price=v_dict.get("limit_price"),
            stop_price=v_dict.get("stop_price"),
            time_in_force=v_dict.get("time_in_force", ""),
            status=v_dict.get("status", ""),
            verdict=v_dict.get("verdict", ""),
            reasons=v_dict.get("reasons", []) or [],
            bot_trade_id=v_dict.get("bot_trade_id"),
            ib_position_size=v_dict.get("ib_position_size"),
            submitted_at=v_dict.get("submitted_at"),
        )
        if ov.verdict in SAFE_TO_AUTO_CANCEL:
            matched_verdicts.append(ov)
        else:
            not_safe.append({
                "ib_order_id": ov.ib_order_id,
                "verdict": ov.verdict,
                "reason": "verdict not in SAFE_TO_AUTO_CANCEL",
            })

    matched_ids = {v.ib_order_id for v in matched_verdicts} | {
        s["ib_order_id"] for s in not_safe
    }
    for rid in requested_ids:
        if rid not in matched_ids:
            not_found.append(rid)

    cancel_summary = await cancel_orphan_gtc_orders(
        verdicts_to_cancel=matched_verdicts,
    )

    return {
        "success": len(cancel_summary.get("errors", [])) == 0
                   and len(not_safe) == 0
                   and len(not_found) == 0,
        "cancel_summary": cancel_summary,
        "not_safe": not_safe,
        "not_found": not_found,
        "audited_at": audit.get("checked_at"),
    }


# ── v19.34.72 — Operator-flatten suppression endpoints ───────────────

@router.get("/operator-flatten-suppression")
async def list_operator_flatten_suppression():
    """List symbols currently suppressed by the operator-flatten detector.

    A symbol lands here when the position reconciler observes an
    external close (IB=0 while bot was tracking, confirmed across two
    consecutive scans per v19.34.71) — by construction the close was
    not bot-initiated, so we assume the operator manually flattened
    and block re-entries on the symbol until UTC midnight.
    """
    from services.operator_flatten_suppression import get_operator_flatten_suppression
    supp = get_operator_flatten_suppression()
    snapshot = supp.list_all()
    return {
        "success": True,
        "count": len(snapshot),
        "suppressed": snapshot,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/clear-operator-flatten-suppression")
async def clear_operator_flatten_suppression(payload: Optional[dict] = None):
    """Clear one or all symbols from the operator-flatten suppression set.

    Body (optional):
      `{"symbol": "NBIS"}` — clear a specific symbol.
      `{}` or omitted     — clear ALL suppressed symbols.

    Returns count of symbols removed.
    """
    from services.operator_flatten_suppression import get_operator_flatten_suppression
    supp = get_operator_flatten_suppression()
    target = (payload or {}).get("symbol")
    removed = supp.clear(symbol=target)
    return {
        "success": True,
        "removed": removed,
        "target": target or "ALL",
        "cleared_at": datetime.now(timezone.utc).isoformat(),
    }

