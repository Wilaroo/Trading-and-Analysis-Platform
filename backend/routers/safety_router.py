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

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.safety_guardrails import get_safety_guardrails

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/safety", tags=["Safety Guardrails"])


# ─── schemas ─────────────────────────────────────────────────────────────

class SafetyConfigPatch(BaseModel):
    """All fields optional — only the ones provided are updated."""
    max_daily_loss_usd:      Optional[float] = Field(default=None, gt=0)
    max_daily_loss_pct:      Optional[float] = Field(default=None, gt=0, lt=100)
    max_positions:           Optional[int]   = Field(default=None, ge=1, le=100)
    max_symbol_exposure_usd: Optional[float] = Field(default=None, gt=0)
    max_total_exposure_pct:  Optional[float] = Field(default=None, gt=0, le=100)
    max_quote_age_seconds:   Optional[float] = Field(default=None, gt=0, lt=300)
    enabled:                 Optional[bool]  = None


class KillSwitchTripRequest(BaseModel):
    reason: str = Field(default="manual", min_length=1, max_length=200)


# ─── endpoints ────────────────────────────────────────────────────────────

@router.get("/status")
async def safety_status() -> Dict[str, Any]:
    """Full safety surface: current config + state + last 20 check decisions."""
    return {"success": True, **get_safety_guardrails().status()}


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
    guard.trip_kill_switch(reason="flatten-all initiated")

    summary: Dict[str, Any] = {
        "positions_requested_close": 0,
        "positions_succeeded": 0,
        "positions_failed": 0,
        "close_errors": [],
        "orders_cancelled": 0,
        "orders_cancel_errors": [],
    }

    # 1. Close every open trade via the bot's position_manager
    try:
        from services.trading_bot_service import get_trading_bot
        bot = get_trading_bot()
        open_trades: List[Any] = list(getattr(bot, "_open_trades", {}).values()) if bot else []
        summary["positions_requested_close"] = len(open_trades)

        for t in open_trades:
            trade_id = getattr(t, "trade_id", None) or (t.get("trade_id") if isinstance(t, dict) else None)
            if not trade_id:
                summary["positions_failed"] += 1
                summary["close_errors"].append({"trade": str(t)[:120], "err": "no trade_id"})
                continue
            try:
                ok = await bot.close_trade(trade_id, reason="emergency_flatten_all")
                if ok:
                    summary["positions_succeeded"] += 1
                else:
                    summary["positions_failed"] += 1
                    summary["close_errors"].append({"trade_id": trade_id, "err": "close returned False"})
            except Exception as e:
                summary["positions_failed"] += 1
                summary["close_errors"].append({"trade_id": trade_id, "err": str(e)[:200]})
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

    logger.warning("[SAFETY] FLATTEN-ALL complete: %s", summary)
    return {"success": True, "summary": summary, "state": guard.status()["state"]}
