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
                return {
                    "group_status": "close_returned_false",
                    "canonical_id": canonical_id,
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
