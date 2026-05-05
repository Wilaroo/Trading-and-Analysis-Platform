"""
Trading Bot API Router
Endpoints for controlling the autonomous trading bot,
managing trades, and viewing trade explanations.
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trading-bot", tags=["trading-bot"])

# Service references (set during init)
_trading_bot = None
_trade_executor = None


class RiskParamsUpdate(BaseModel):
    max_risk_per_trade: Optional[float] = None
    max_daily_loss: Optional[float] = None
    starting_capital: Optional[float] = None
    max_position_pct: Optional[float] = None
    max_open_positions: Optional[int] = None
    min_risk_reward: Optional[float] = None
    max_notional_per_trade: Optional[float] = None  # Hard absolute notional cap per trade ($). 0 = disabled. (added 2026-04-30 v19.4)
    # 2026-05-01 v19.21 — per-setup R:R overrides (mean-reversion plays
    # with bounded targets get a relaxed floor; trend/breakout setups stay
    # strict). Operator can hot-patch via PUT /api/trading-bot/risk-params.
    setup_min_rr: Optional[Dict[str, float]] = None


class BotConfigUpdate(BaseModel):
    mode: Optional[str] = None  # "autonomous", "confirmation", "paused"
    enabled_setups: Optional[List[str]] = None
    scan_interval: Optional[int] = None
    watchlist: Optional[List[str]] = None


class TradeAction(BaseModel):
    action: str  # "confirm", "reject", "close"
    reason: Optional[str] = None


class DemoTradeRequest(BaseModel):
    symbol: str = "NVDA"
    direction: str = "long"
    setup_type: str = "rubber_band"


class TradeSubmitRequest(BaseModel):
    symbol: str
    direction: str = "long"
    setup_type: str = "breakout"
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    target_prices: Optional[List[float]] = None
    half_size: bool = False
    source: str = "manual"


class StrategyConfigUpdate(BaseModel):
    trail_pct: Optional[float] = None
    close_at_eod: Optional[bool] = None
    scale_out_pcts: Optional[List[float]] = None
    timeframe: Optional[str] = None


@router.get("/diag/symbol-state")
async def diag_symbol_state(
    symbol: str = Query(..., description="Symbol to diagnose (case-insensitive)"),
    history_days: int = Query(7, ge=1, le=30),
):
    """v19.34.15 (2026-05-06) — symbol-level forensic diagnostic.

    Operator caught UPS showing 5,304 shares at IB but only 425 in-app.
    This endpoint returns every angle on a symbol so you can see what
    happened end-to-end:

      • `ib_position` — live IB qty/avg_cost/market_value from the
        pusher snapshot.
      • `open_trades_in_memory` — `_trading_bot._open_trades[symbol]`
        array; this is the source of the V5 "Open Positions" panel.
      • `bot_trades_history` — every `bot_trades` Mongo row for this
        symbol over the last `history_days` (open + closed),
        newest-first, with key fields only (no _id).
      • `bracket_lifecycle` — every `bracket_lifecycle_events` row for
        this symbol (so you see scale-outs, re-issues, etc.)
      • `drift` — computed `IB_qty - sum(in_memory.remaining_shares)`.
        +ve = IB has more than tracked (UPS case); -ve = bot thinks
        more than IB has.
    """
    if _trading_bot is None:
        raise HTTPException(503, "Trading bot not initialized")
    sym = (symbol or "").upper().strip()
    if not sym:
        raise HTTPException(400, "symbol required")

    db = getattr(_trading_bot, "_db", None)

    # 1) Live IB position from pusher snapshot.
    ib_position: Optional[Dict[str, Any]] = None
    try:
        from routers.ib import _pushed_ib_data
        positions = (_pushed_ib_data or {}).get("positions") or []
        # `positions` may be a list of dicts or a dict keyed by symbol.
        if isinstance(positions, dict):
            ib_position = positions.get(sym)
        elif isinstance(positions, list):
            for p in positions:
                psym = str((p or {}).get("symbol") or "").upper()
                if psym == sym:
                    ib_position = p
                    break
        live_quote = ((_pushed_ib_data or {}).get("quotes") or {}).get(sym) or {}
    except Exception as e:
        ib_position = {"error": str(e)}
        live_quote = {}

    # 2) In-memory open trades.
    open_trades_mem: List[Dict[str, Any]] = []
    try:
        ot = getattr(_trading_bot, "_open_trades", {}) or {}
        rows = ot.get(sym) or []
        for t in (rows if isinstance(rows, list) else [rows]):
            d = {
                "id": getattr(t, "id", None),
                "symbol": getattr(t, "symbol", None),
                "direction": getattr(t, "direction", None),
                "status": str(getattr(t, "status", "")),
                "entry_price": getattr(t, "entry_price", None),
                "remaining_shares": getattr(t, "remaining_shares", None),
                "original_shares": getattr(t, "original_shares", None),
                "stop_price": getattr(t, "stop_price", None),
                "target_prices": getattr(t, "target_prices", None),
                "scale_outs_executed": getattr(t, "scale_outs_executed", None),
                "setup_type": getattr(t, "setup_type", None),
                "created_at": str(getattr(t, "created_at", "")) or None,
                "ai_context": (getattr(t, "ai_context", "") or "")[:200] or None,
            }
            # Coerce direction enum to value.
            d["direction"] = getattr(d["direction"], "value", d["direction"])
            open_trades_mem.append(d)
    except Exception as e:
        open_trades_mem = [{"error": str(e)}]

    # 3) bot_trades history (Mongo).
    history: List[Dict[str, Any]] = []
    if db is not None:
        try:
            from datetime import datetime, timedelta, timezone
            cutoff = datetime.now(timezone.utc) - timedelta(days=int(history_days))
            cur = db["bot_trades"].find(
                {
                    "symbol": sym,
                    "$or": [
                        {"created_at": {"$gte": cutoff}},
                        {"created_at": {"$gte": cutoff.isoformat()}},
                    ],
                },
                {"_id": 0, "ai_context": 0, "entry_context": 0},
            ).sort("created_at", -1).limit(200)

            def _read():
                return list(cur)
            history = await asyncio.to_thread(_read)
        except Exception as e:
            history = [{"error": str(e)}]

    # 4) Bracket lifecycle (added v19.34.11).
    lifecycle: List[Dict[str, Any]] = []
    if db is not None:
        try:
            from datetime import datetime, timedelta, timezone
            cutoff = datetime.now(timezone.utc) - timedelta(days=int(history_days))
            cur2 = db["bracket_lifecycle_events"].find(
                {"symbol": sym, "created_at": {"$gte": cutoff}},
                {"_id": 0},
            ).sort("created_at", -1).limit(50)

            def _read2():
                return list(cur2)
            lifecycle = await asyncio.to_thread(_read2)
        except Exception:
            pass

    # 5) Drift computation.
    ib_qty_signed: Optional[float] = None
    if isinstance(ib_position, dict):
        ib_qty_signed = (
            ib_position.get("qty")
            or ib_position.get("quantity")
            or ib_position.get("position")
        )
        try:
            ib_qty_signed = float(ib_qty_signed) if ib_qty_signed is not None else None
        except (TypeError, ValueError):
            ib_qty_signed = None

    in_mem_qty_signed: float = 0.0
    for t in open_trades_mem:
        rs = t.get("remaining_shares")
        if rs is None:
            continue
        try:
            rs = float(rs)
        except (TypeError, ValueError):
            continue
        d = (t.get("direction") or "").lower()
        in_mem_qty_signed += rs if d != "short" else -rs

    drift_shares: Optional[float] = None
    if ib_qty_signed is not None:
        drift_shares = round(ib_qty_signed - in_mem_qty_signed, 4)

    return {
        "success": True,
        "symbol": sym,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "ib_position": ib_position,
        "live_quote": live_quote,
        "open_trades_in_memory": open_trades_mem,
        "in_memory_qty_signed": in_mem_qty_signed,
        "bot_trades_history": history,
        "bot_trades_history_count": len(history),
        "bracket_lifecycle": lifecycle,
        "drift_shares": drift_shares,
        "drift_interpretation": (
            None if drift_shares is None
            else "ib_has_more_than_tracked" if drift_shares > 1
            else "bot_thinks_more_than_ib_has" if drift_shares < -1
            else "in_sync"
        ),
        "history_days": history_days,
    }


def init_trading_bot_router(trading_bot, trade_executor):
    """Initialize router with service dependencies"""
    global _trading_bot, _trade_executor
    _trading_bot = trading_bot
    _trade_executor = trade_executor
    logger.info("Trading bot router initialized")


@router.get("/multiplier-analytics")
async def get_multiplier_analytics(
    days_back: int = Query(default=30, ge=1, le=365),
    only_closed: bool = Query(default=True),
):
    """A/B-style analytics for the liquidity-aware execution layers.

    Slices `bot_trades` over the last `days_back` days into "snap fired"
    vs "snap didn't fire" cohorts for the stop-guard, target-snap, and
    VP-path multiplier. Returns mean R-multiple, win rate, and sample
    size per cohort so the operator can tell at a glance whether each
    layer is moving live P&L. Used by the SmartLevelsAnalyticsCard.
    """
    if _trading_bot is None or getattr(_trading_bot, "_db", None) is None:
        raise HTTPException(status_code=503, detail="trading bot not initialized")
    try:
        from services.multiplier_analytics_service import compute_multiplier_analytics
        return compute_multiplier_analytics(
            _trading_bot._db, days_back=days_back, only_closed=only_closed,
        )
    except Exception as e:
        logger.error(f"multiplier analytics failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai-decision-audit")
async def get_ai_decision_audit(
    limit: int = Query(default=30, ge=1, le=200),
):
    """Per-trade AI module audit for the V5 AIDecisionAuditCard.

    For each of the most recent `limit` closed trades, returns what
    each AI module (debate / risk / institutional / time-series) said
    at consultation time, plus whether that module's directional
    verdict aligned with the actual P&L outcome. Aggregates a
    per-module alignment-rate summary so the operator can spot which
    modules are pulling weight vs which are noise.

    Reads `bot_trades.entry_context.ai_modules` — that field is
    populated by `opportunity_evaluator.build_entry_context` whenever
    the consultation pipeline ran.
    """
    if _trading_bot is None or getattr(_trading_bot, "_db", None) is None:
        raise HTTPException(status_code=503, detail="trading bot not initialized")
    try:
        from services.ai_decision_audit_service import compute_ai_decision_audit
        return compute_ai_decision_audit(_trading_bot._db, limit=limit)
    except Exception as e:
        logger.error(f"ai-decision-audit failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/multiplier-thresholds/optimize")
async def run_multiplier_threshold_optimizer(
    days_back: int = Query(default=30, ge=7, le=120),
    dry_run: bool = Query(default=False),
):
    """Run the nightly self-tuning job that adjusts smart-levels
    thresholds (`stop_min_level_strength`, `target_snap_outside_pct`,
    `path_vol_fat_pct`) toward the values that maximise mean-R lift
    in `bot_trades` over the last `days_back` days.

    Returns the full decision payload — proposed thresholds, lifts per
    layer, cohort sizes, and notes. When `dry_run=False`, the result is
    persisted in `multiplier_threshold_history` and live trading picks
    up the new values within ~5 min (cache TTL).
    """
    if _trading_bot is None or getattr(_trading_bot, "_db", None) is None:
        raise HTTPException(status_code=503, detail="trading bot not initialized")
    try:
        from services.multiplier_threshold_optimizer import run_optimization
        return run_optimization(_trading_bot._db, days_back=days_back, dry_run=dry_run)
    except Exception as e:
        logger.error(f"multiplier threshold optimizer failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/multiplier-thresholds/history")
async def get_multiplier_threshold_history(limit: int = Query(default=20, ge=1, le=200)):
    """Return the last N optimizer runs with their proposed/applied
    threshold deltas. Used by the operator to audit the auto-tuning
    loop and roll back if it drifts somewhere unexpected.
    """
    if _trading_bot is None or getattr(_trading_bot, "_db", None) is None:
        raise HTTPException(status_code=503, detail="trading bot not initialized")
    try:
        cursor = _trading_bot._db["multiplier_threshold_history"].find(
            {}, {"_id": 0},
        ).sort("ran_at", -1).limit(int(limit))
        return {"runs": list(cursor)}
    except Exception as e:
        logger.error(f"multiplier threshold history failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/smoke-run-report")
async def post_smoke_run_report(hours_back: int = Query(default=24, ge=1, le=168)):
    """Generate a paper-mode smoke-run go/no-go report covering the
    last `hours_back` of bot activity. Returns a per-phase status
    breakdown (SCAN / EVAL / ORDER / MANAGE / CLOSE / HEALTH) plus a
    rolled-up `verdict ∈ {green, amber, red}` and a one-paragraph
    operator-readable summary. Used by the operator before flipping
    the bot from PAPER → LIVE.
    """
    if _trading_bot is None or getattr(_trading_bot, "_db", None) is None:
        raise HTTPException(status_code=503, detail="trading bot not initialized")
    try:
        from services.smoke_run_report_service import compute_smoke_run_report
        return compute_smoke_run_report(_trading_bot._db, hours_back=hours_back)
    except Exception as e:
        logger.error(f"smoke run report failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== BOT CONTROL ====================

@router.get("/status")
async def get_bot_status():
    """Get trading bot status and statistics"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    status = _trading_bot.get_status()
    
    # Add account info if available — TradeExecutorService.get_account_info()
    # only handles SIMULATED + Alpaca PAPER modes (returns {} for IB users).
    # Fall back to the IB pusher snapshot in routers.ib._pushed_ib_data so
    # operators on IB still see equity/buying_power on the V5 dashboard.
    account: dict = {}
    if _trade_executor:
        try:
            executor_account = await _trade_executor.get_account_info()
            if isinstance(executor_account, dict):
                account = executor_account
        except Exception as e:
            logger.debug(f"trade_executor.get_account_info failed: {e}")
    
    if not account or not (account.get("equity") or account.get("portfolio_value")):
        try:
            from routers.ib import _pushed_ib_data, _extract_account_value, is_pusher_connected
            ib_account = (_pushed_ib_data or {}).get("account") or {}
            # If the push-loop's account_data is empty (which is the
            # screenshot-bug scenario: PUSHER GREEN but no equity), fall
            # back to the on-demand /rpc/account-snapshot RPC. Seeds
            # `_pushed_ib_data` so the next call is fast.
            if not ib_account:
                try:
                    from services.ib_pusher_rpc import get_account_snapshot
                    # v19.30.8 (2026-05-02 evening): wrap in asyncio.to_thread.
                    # `get_account_snapshot()` is a module-level helper that
                    # calls `get_pusher_rpc_client().account_snapshot()` —
                    # which does sync HTTP under the pusher RPC's
                    # threading.Lock. Pre-fix this blocked the event loop
                    # for up to 5s on every /api/trading-bot/status call
                    # when push-data wasn't seeding `_pushed_ib_data.account`
                    # (often during boot / pusher cold-start). Captured by
                    # wedge-watchdog 2026-05-02 evening.
                    snap = await asyncio.to_thread(get_account_snapshot) or {}
                    if snap.get("success") and snap.get("account"):
                        ib_account = snap["account"]
                        _pushed_ib_data["account"] = ib_account
                except Exception as e:
                    logger.debug(f"account RPC fallback failed: {e}")
            if ib_account:
                net_liq = _extract_account_value(ib_account, "NetLiquidation", 0)
                buying_power = _extract_account_value(ib_account, "BuyingPower", 0)
                cash = _extract_account_value(ib_account, "TotalCashBalance", 0)
                available_funds = _extract_account_value(
                    ib_account, "AvailableFunds", buying_power
                )
                if net_liq and net_liq > 0:
                    account = {
                        "equity": float(net_liq),
                        "portfolio_value": float(net_liq),
                        "buying_power": float(buying_power),
                        "cash": float(cash),
                        "available_funds": float(available_funds),
                        "currency": "USD",
                        "source": "ib_pushed",
                        "connected": is_pusher_connected(),
                    }
        except Exception as e:
            logger.debug(f"IB pushed account fallback failed: {e}")
    
    status["account"] = account
    # Surface equity at top-level so the V5 frontend's
    # `status?.account_equity ?? status?.equity` read finds it without
    # forcing a separate `/api/ib/account/summary` round-trip.
    if account.get("equity"):
        status["account_equity"] = account["equity"]
        status.setdefault("equity", account["equity"])
        # 2026-04-30 v19.6 — also surface live buying power at top-level
        # so the V5 HUD can show real-time margin headroom next to equity
        # (replaced the old `Latency` metric per operator request).
        if account.get("buying_power"):
            status["account_buying_power"] = account["buying_power"]

        # 2026-04-29 (operator-flagged pre-RTH): keep
        # `risk_params.starting_capital` in lock-step with the live
        # account equity. Pre-fix the position sizer read
        # `risk_params.starting_capital` (frozen at the $100k default)
        # while the UI showed real $1M+ equity from the same `/status`
        # response — every trade was sized off the wrong baseline.
        try:
            live_equity = float(account["equity"])
            if live_equity > 0 and _trading_bot is not None:
                current = float(getattr(_trading_bot.risk_params, "starting_capital", 0) or 0)
                if abs(current - live_equity) > 1.0:
                    _trading_bot.risk_params.starting_capital = live_equity
                    status["risk_params"] = _trading_bot.risk_params.dict()
                    logger.info(
                        f"💰 Synced risk_params.starting_capital to live equity: "
                        f"${current:,.0f} → ${live_equity:,.0f}"
                    )
        except Exception as e:
            logger.debug(f"starting_capital sync failed: {e}")

    return {"success": True, **status}


# 2026-05-05 v19.34.6 — Risk Parameters Config Drift fix.
# Operator filed bug 2026-05-04: the Morning Prep UI reads from Master
# Safety Guard limits (25 pos, $5k loss) while `/api/trading-bot/status`
# reads legacy per-trade limits (10 pos, $0 loss). Two surfaces show
# different numbers — UX confusion about what the bot actually enforces.
#
# Fix: a single canonical endpoint that returns the AND (most-restrictive
# intersection) of every guard layer — Master Safety Guard, bot
# RiskParameters, PositionSizer, DynamicRisk. Same logic as
# `/api/safety/effective-risk-caps` but mounted on the trading-bot prefix
# so the V5 dashboard's risk card has a co-located endpoint to consume.
@router.get("/effective-limits")
async def get_effective_limits():
    """Return the binding (most-restrictive intersection) of every
    risk-cap source the bot honors.

    Sources (in priority order — strictest wins):
      1. Master Safety Guard (kill switch) — `services.safety_guardrails`
      2. Bot RiskParameters (Mongo bot_state.risk_params)
      3. Position Sizer (`services.position_sizer` defaults)
      4. Dynamic Risk Engine (`services.dynamic_risk_engine` defaults)

    Response shape mirrors `/api/safety/effective-risk-caps`:
      {
        "success": true,
        "sources": { bot, safety, sizer, dynamic_risk },
        "effective": { max_open_positions, max_daily_loss_usd,
                       max_position_pct, max_daily_loss_pct, ... },
        "conflicts": [<human-readable diagnostics>],
        "checked_at": "2026-05-05T...",
      }
    """
    try:
        from services.risk_caps_service import compute_effective_risk_caps
        db = None
        try:
            db = getattr(_trading_bot, "_db", None) if _trading_bot else None
        except Exception:
            db = None
        payload = compute_effective_risk_caps(db)
        return {"success": True, **payload}
    except Exception as e:
        logger.error(f"Error computing effective limits: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "sources": {},
            "effective": {},
            "conflicts": [],
        }


# ─── EOD Order Safety (v19.34.6 — 2026-05-05) ──────────────────────────────
# Operator-filed P1 items: 
#   (g) End-of-RTH validator — sweep all overnight (GTC / outside_rth=true)
#       open orders, confirm each has an active swing/position parent in
#       `bot_trades`; cancel orphans with a CRITICAL warning.
#   (f) EOD pre-cancel guard — explicitly cancel a symbol's open orders
#       before firing the market-close flatten so we don't race the OCA.
#
# Together these close the GTC-zombie loop that v19.34.5 fixed at
# *placement* time, by adding *runtime* and *EOD* sweeps.


def _is_overnight_leg(order_doc: Dict[str, Any]) -> bool:
    """Return True if the order has any leg that would survive overnight
    (TIF=GTC OR outside_rth=True). Checks the parent + stop + target
    sub-docs for bracket orders, plus the top-level fields for flat
    orders. Conservative: any GTC anywhere makes the order overnight."""
    legs = []
    if isinstance(order_doc.get("parent"), dict):
        legs.append(order_doc["parent"])
    if isinstance(order_doc.get("stop"), dict):
        legs.append(order_doc["stop"])
    if isinstance(order_doc.get("target"), dict):
        legs.append(order_doc["target"])
    # Flat order — top-level TIF
    if order_doc.get("time_in_force") or "outside_rth" in order_doc:
        legs.append({
            "time_in_force": order_doc.get("time_in_force"),
            "outside_rth":   order_doc.get("outside_rth"),
        })
    for leg in legs:
        tif = (leg.get("time_in_force") or "").upper()
        if tif == "GTC":
            return True
        if leg.get("outside_rth") is True:
            return True
    return False


@router.post("/eod-validate-overnight-orders")
async def eod_validate_overnight_orders(payload: Optional[Dict[str, Any]] = None):
    """Sweep every active order with an overnight (GTC / outside_rth=True)
    leg and verify a swing/position `bot_trades` parent exists. Orphans
    (no parent OR intraday parent) are flagged for cancellation. With
    `confirm="CANCEL_ORPHANS"` they're actively cancelled in the queue.

    Body (all optional):
      {
        "confirm":  "CANCEL_ORPHANS" | null  // pass to actually cancel
        "dry_run":  true | false             // default true
      }

    Response:
      {
        "success": true,
        "summary": { total_open, overnight_legs, ok, orphans, wrong_tif,
                     cancelled_count, errors },
        "rows":    [ { order_id, symbol, status, classification, ... } ],
        "dry_run": <bool>
      }
    """
    payload = payload or {}
    confirm = (payload.get("confirm") or "").strip()
    dry_run = bool(payload.get("dry_run", True))
    actually_cancel = (confirm == "CANCEL_ORPHANS") and not dry_run

    try:
        from services.order_queue_service import get_order_queue_service
        from services.bracket_tif import is_overnight_trade
        service = get_order_queue_service()
        if not service._initialized:
            service.initialize()

        # Pull all currently-active orders (pending / claimed / executing)
        active = list(service._collection.find(
            {"status": {"$in": ["pending", "claimed", "executing"]}},
            {"_id": 0},
        ))

        # Build a quick lookup of bot_trades by trade_id for parent matching
        bot_trades_by_id: Dict[str, Dict[str, Any]] = {}
        if _trading_bot is not None and getattr(_trading_bot, "_db", None) is not None:
            try:
                for t in _trading_bot._db.bot_trades.find(
                    {"status": {"$in": ["open", "pending", "filled"]}},
                    {"_id": 0, "id": 1, "trade_style": 1, "timeframe": 1,
                     "symbol": 1, "status": 1, "direction": 1},
                ):
                    if t.get("id"):
                        bot_trades_by_id[t["id"]] = t
            except Exception as e:
                logger.debug(f"bot_trades lookup failed (proceeding): {e}")

        rows: List[Dict[str, Any]] = []
        cancelled_count = 0
        errors = 0

        for o in active:
            if not _is_overnight_leg(o):
                continue  # intraday-only leg — skip silently
            order_id = o.get("order_id")
            symbol = o.get("symbol")
            trade_id = o.get("trade_id")
            parent = bot_trades_by_id.get(trade_id) if trade_id else None
            classification = "unknown"
            should_cancel = False
            reason = ""

            if not parent:
                classification = "orphan_no_parent"
                should_cancel = True
                reason = "No active bot_trades row for trade_id"
            elif not is_overnight_trade(parent.get("trade_style"), parent.get("timeframe")):
                classification = "wrong_tif_intraday_parent"
                should_cancel = True
                reason = (
                    f"Parent trade is intraday ("
                    f"trade_style={parent.get('trade_style')}, "
                    f"timeframe={parent.get('timeframe')}) — overnight leg "
                    f"would zombify after EOD flatten"
                )
            else:
                classification = "ok_swing_or_position"

            row = {
                "order_id": order_id,
                "symbol": symbol,
                "status": o.get("status"),
                "order_type": o.get("order_type"),
                "trade_id": trade_id,
                "queued_at": o.get("queued_at"),
                "classification": classification,
                "reason": reason,
                "parent_status": (parent or {}).get("status"),
                "parent_trade_style": (parent or {}).get("trade_style"),
                "parent_timeframe": (parent or {}).get("timeframe"),
                "tif_summary": {
                    "parent": (o.get("parent") or {}).get("time_in_force"),
                    "stop":   (o.get("stop") or {}).get("time_in_force"),
                    "target": (o.get("target") or {}).get("time_in_force"),
                    "flat":   o.get("time_in_force"),
                },
            }

            if should_cancel and actually_cancel:
                try:
                    if service.cancel_order(order_id):
                        cancelled_count += 1
                        row["cancelled"] = True
                        logger.warning(
                            "[v19.34.6 EOD-VALIDATOR] CANCELLED %s (%s) — %s",
                            order_id, symbol, reason,
                        )
                    else:
                        row["cancelled"] = False
                except Exception as e:
                    errors += 1
                    row["cancel_error"] = str(e)

            rows.append(row)

        summary = {
            "total_active": len(active),
            "overnight_legs": len(rows),
            "ok": sum(1 for r in rows if r["classification"] == "ok_swing_or_position"),
            "orphans": sum(1 for r in rows if r["classification"] == "orphan_no_parent"),
            "wrong_tif": sum(1 for r in rows if r["classification"] == "wrong_tif_intraday_parent"),
            "cancelled_count": cancelled_count,
            "errors": errors,
        }

        return {
            "success": True,
            "summary": summary,
            "rows": rows,
            "dry_run": dry_run if not actually_cancel else False,
            "actually_cancelled": actually_cancel,
        }
    except Exception as e:
        logger.error(f"EOD overnight-orders validate error: {e}", exc_info=True)
        return {"success": False, "error": str(e), "summary": {}, "rows": []}


@router.post("/cancel-orders-for-symbol")
async def cancel_orders_for_symbol(payload: Dict[str, Any]):
    """EOD pre-cancel guard. Cancels every active (pending/claimed/
    executing) order in `order_queue` for the given symbol BEFORE the
    market-close flatten fires. Eliminates the race where the EOD
    market-close hits a position that still has a live OCA bracket.

    Body:
      {
        "symbol":  "STX",                       // required
        "confirm": "CANCEL_FOR_SYMBOL",         // required token
        "dry_run": false                        // default false
      }

    Response:
      {
        "success": true,
        "symbol": "STX",
        "matched": <int>,
        "cancelled_count": <int>,
        "rows": [ {order_id, status, classification, ...} ],
        "dry_run": <bool>
      }
    """
    if not isinstance(payload, dict) or not payload.get("symbol"):
        raise HTTPException(status_code=400, detail="symbol is required")
    confirm = (payload.get("confirm") or "").strip()
    if confirm != "CANCEL_FOR_SYMBOL":
        raise HTTPException(
            status_code=400,
            detail='confirm must be "CANCEL_FOR_SYMBOL" (safety token)',
        )
    symbol = str(payload["symbol"]).upper()
    dry_run = bool(payload.get("dry_run", False))

    try:
        from services.order_queue_service import get_order_queue_service
        service = get_order_queue_service()
        if not service._initialized:
            service.initialize()

        active = list(service._collection.find(
            {
                "symbol": symbol,
                "status": {"$in": ["pending", "claimed", "executing"]},
            },
            {"_id": 0},
        ))

        rows: List[Dict[str, Any]] = []
        cancelled_count = 0
        for o in active:
            order_id = o.get("order_id")
            row = {
                "order_id": order_id,
                "status": o.get("status"),
                "order_type": o.get("order_type"),
                "trade_id": o.get("trade_id"),
                "queued_at": o.get("queued_at"),
            }
            if not dry_run:
                try:
                    if service.cancel_order(order_id):
                        cancelled_count += 1
                        row["cancelled"] = True
                        logger.warning(
                            "[v19.34.6 EOD-PRE-CANCEL] %s order %s cancelled "
                            "(symbol pre-cancel before flatten)",
                            symbol, order_id,
                        )
                    else:
                        row["cancelled"] = False
                except Exception as e:
                    row["cancel_error"] = str(e)
            rows.append(row)

        return {
            "success": True,
            "symbol": symbol,
            "matched": len(active),
            "cancelled_count": cancelled_count,
            "rows": rows,
            "dry_run": dry_run,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"cancel-orders-for-symbol error: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "symbol": symbol,
            "matched": 0,
            "cancelled_count": 0,
            "rows": [],
        }


# ─── Bracket re-issue (v19.34.7 — 2026-05-05 PM) ──────────────────────────
# Operator-driven endpoint. Cancels the existing OCA bracket legs for an
# open trade, recomputes stop/target/qty for the post-event position,
# and submits a new OCA pair. Designed for:
#   - scale-in events (when scale-in is wired into the bot it'll call
#     this with `reason="scale_in"` + `new_total_shares`).
#   - manual operator overrides ("bot's stop is too tight, widen it").
#   - bracket TIF promotion (intraday → swing — recomputes with GTC TIF).
# Auto-called from position_manager.check_and_execute_scale_out post-fill.
@router.post("/reissue-bracket")
async def reissue_bracket(payload: Dict[str, Any]):
    """Cancel existing bracket legs + submit a freshly-computed OCA pair.

    Body:
      {
        "trade_id":              "trade-abc",       // required
        "reason":                "scale_in" | "scale_out" | "tif_promotion"
                                 | "manual" | "stop_widen" | ...,
        "new_total_shares":      <int> | null,      // defaults to trade.shares
        "new_avg_entry":         <float> | null,    // defaults to trade.entry_price
        "already_executed_shares": <int> = 0,       // for scale-out math
        "preserve_target_levels": true,             // false → 2R synthesis
        "cancel_ack_timeout_s":  2.0,
        "dry_run":               false              // compute only, no IB calls
      }

    Response: rich dict with cancel_result, submit_result, plan, error
    (mirrors the `bracket_reissue_service.reissue_bracket_for_trade`
    return shape — see that module for full schema).

    Returns 400 if trade_id missing or trade not in `_open_trades`.
    """
    if not isinstance(payload, dict) or not payload.get("trade_id"):
        raise HTTPException(status_code=400, detail="trade_id is required")

    trade_id = str(payload["trade_id"])
    reason = str(payload.get("reason") or "manual")
    new_total = payload.get("new_total_shares")
    if new_total is not None:
        try:
            new_total = int(new_total)
        except Exception:
            raise HTTPException(status_code=400, detail="new_total_shares must be int")
    new_avg = payload.get("new_avg_entry")
    if new_avg is not None:
        try:
            new_avg = float(new_avg)
        except Exception:
            raise HTTPException(status_code=400, detail="new_avg_entry must be number")
    already_executed = int(payload.get("already_executed_shares") or 0)
    preserve = bool(payload.get("preserve_target_levels", True))
    cancel_timeout = float(payload.get("cancel_ack_timeout_s") or 2.0)
    dry_run = bool(payload.get("dry_run", False))

    if _trading_bot is None:
        raise HTTPException(status_code=503, detail="trading bot not initialized")

    trade = (_trading_bot._open_trades or {}).get(trade_id)
    if trade is None:
        raise HTTPException(
            status_code=404,
            detail=f"trade_id {trade_id!r} not found in open trades",
        )

    if dry_run:
        # Compute-only mode. Useful for the V5 "preview re-issue" UX.
        try:
            from services.bracket_reissue_service import compute_reissue_params
            plan = compute_reissue_params(
                trade=trade,
                risk_params=_trading_bot.risk_params,
                reason=reason,
                new_total_shares=new_total,
                new_avg_entry=new_avg,
                already_executed_shares=already_executed,
                preserve_target_levels=preserve,
            )
            return {
                "success": True,
                "phase": "compute",
                "dry_run": True,
                "plan": plan.__dict__,
            }
        except Exception as e:
            return {
                "success": False,
                "phase": "compute",
                "dry_run": True,
                "error": f"{type(e).__name__}: {e}",
            }

    try:
        from services.bracket_reissue_service import reissue_bracket_for_trade
        result = await reissue_bracket_for_trade(
            trade=trade,
            bot=_trading_bot,
            reason=reason,
            new_total_shares=new_total,
            new_avg_entry=new_avg,
            already_executed_shares=already_executed,
            preserve_target_levels=preserve,
            cancel_ack_timeout_s=cancel_timeout,
        )
        return result
    except Exception as e:
        logger.error(f"reissue-bracket error: {e}", exc_info=True)
        return {
            "success": False,
            "phase": "orchestrator",
            "error": f"{type(e).__name__}: {e}",
            "trade_id": trade_id,
            "reason": reason,
        }


# ─── v19.34.8 — Rejection cooldown operator endpoints ─────────────────
@router.get("/rejection-cooldowns")
async def list_rejection_cooldowns():
    """List every active `(symbol, setup_type)` rejection cooldown.

    Operator inspection endpoint added after the 2026-05-05 XLU/UPS
    forensic showed 110+ rejected brackets in 71min on the same setup.
    Returns `{success, cooldowns: [...], stats: {...}}`.
    """
    try:
        from services.rejection_cooldown_service import get_rejection_cooldown
        rc = get_rejection_cooldown()
        return {
            "success": True,
            "cooldowns": rc.list_active(),
            "stats": rc.stats(),
        }
    except Exception as e:
        logger.error(f"list_rejection_cooldowns error: {e}", exc_info=True)
        return {"success": False, "error": str(e), "cooldowns": [], "stats": {}}


@router.post("/clear-rejection-cooldown")
async def clear_rejection_cooldown(payload: Optional[Dict[str, Any]] = None):
    """Manually clear a rejection cooldown.

    Body:
      {
        "symbol":     "XLU"  | null,    // omit + clear_all=true to nuke
        "setup_type": "orb"  | null,    // omit + clear_all=true to nuke
        "clear_all":  false              // require explicit opt-in
      }

    Returns `{success, cleared: <bool|int>, ...}`.
    """
    payload = payload or {}
    try:
        from services.rejection_cooldown_service import get_rejection_cooldown
        rc = get_rejection_cooldown()

        if payload.get("clear_all") is True:
            n = rc.clear_all()
            logger.warning(
                "[v19.34.8] operator cleared ALL rejection cooldowns (n=%d)", n,
            )
            return {"success": True, "cleared_all": True, "cleared_count": n}

        symbol = payload.get("symbol")
        setup_type = payload.get("setup_type")
        if not symbol or not setup_type:
            raise HTTPException(
                status_code=400,
                detail="Either {symbol, setup_type} OR {clear_all: true} required",
            )
        cleared = rc.clear_cooldown(symbol, setup_type)
        return {
            "success": True,
            "cleared": cleared,
            "symbol": str(symbol).upper(),
            "setup_type": str(setup_type).lower(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"clear_rejection_cooldown error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


# ─── v19.34.11 — Bracket lifecycle history ───────────────────────────
@router.get("/bracket-history")
async def get_bracket_history(
    trade_id: Optional[str] = Query(None, description="Filter by trade ID"),
    symbol: Optional[str] = Query(None, description="Filter by symbol (case-insensitive)"),
    days: int = Query(7, ge=1, le=30, description="Lookback window"),
    limit: int = Query(200, ge=1, le=1000),
):
    """Return the bracket-lifecycle event trail.

    Powers the V5 "📜 History" expandable panel inside `OpenPositionsV5.jsx`.
    Operator sees the full lifecycle of each trade: original bracket →
    scale-out trim → re-issue → exit, with `reason` chips per event.

    Filters:
      - `trade_id`: pin to one trade's full history (most common)
      - `symbol`: pin to a symbol's full history across all trades
      - `days`: lookback window (default 7d, matches TTL)

    Returns `{success, events: [...], summary: {total, success_count,
    failure_count, by_reason: {...}}}` sorted newest-first.
    """
    if _trading_bot is None:
        raise HTTPException(503, "Trading bot not initialized")
    try:
        db = getattr(_trading_bot, "_db", None)
        if db is None:
            return {"success": False, "error": "no_database", "events": [], "summary": {}}

        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
        query: Dict[str, Any] = {"created_at": {"$gte": cutoff}}
        if trade_id:
            query["trade_id"] = trade_id
        if symbol:
            query["symbol"] = str(symbol).upper()

        def _read():
            cur = db["bracket_lifecycle_events"].find(
                query, {"_id": 0},
            ).sort("created_at", -1).limit(int(limit))
            return list(cur)

        rows = await asyncio.to_thread(_read)

        # Stamp ISO `created_at_iso` for the frontend; some downstream
        # code prefers strings to BSON datetimes.
        for r in rows:
            ca = r.get("created_at")
            if hasattr(ca, "isoformat"):
                r["created_at_iso"] = ca.isoformat()
                r["created_at"] = ca.isoformat()

        # Summary block.
        success_count = sum(1 for r in rows if r.get("success"))
        failure_count = len(rows) - success_count
        by_reason: Dict[str, int] = {}
        for r in rows:
            k = str(r.get("reason") or "unknown")
            by_reason[k] = by_reason.get(k, 0) + 1

        return {
            "success": True,
            "events": rows,
            "summary": {
                "total": len(rows),
                "success_count": success_count,
                "failure_count": failure_count,
                "by_reason": by_reason,
            },
            "filters": {
                "trade_id": trade_id,
                "symbol": symbol,
                "days": days,
                "limit": limit,
            },
        }
    except Exception as e:
        logger.error(f"bracket-history error: {e}", exc_info=True)
        return {"success": False, "error": str(e), "events": [], "summary": {}}


# ─── v19.34.12 — Rejection events / heatmap ──────────────────────────
@router.get("/rejection-events")
async def get_rejection_events(
    days: int = Query(7, ge=1, le=30),
    symbol: Optional[str] = Query(None),
    setup_type: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
):
    """Return rejection events + aggregations for the V5 Diagnostics
    "Rejections" sub-tab heatmap.

    Response shape:
      {
        success,
        events: [{symbol, setup_type, reason, rejection_count, extended,
                  created_at_iso}, ...],
        heatmap: {
          rows: [{symbol, setup_type, total_rejections, by_reason: {...}}],
          symbols: [...], setups: [...],
          max_rejections: <int>, total_events: <int>,
          top_reasons: [{reason, count}, ...]
        },
        filters: {...}
      }
    """
    if _trading_bot is None:
        raise HTTPException(503, "Trading bot not initialized")
    try:
        db = getattr(_trading_bot, "_db", None)
        if db is None:
            return {
                "success": False, "error": "no_database",
                "events": [], "heatmap": {"rows": []},
            }

        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
        query: Dict[str, Any] = {"created_at": {"$gte": cutoff}}
        if symbol:
            query["symbol"] = str(symbol).upper()
        if setup_type:
            query["setup_type"] = str(setup_type).lower()

        def _read():
            cur = db["rejection_events"].find(
                query, {"_id": 0},
            ).sort("created_at", -1).limit(int(limit))
            return list(cur)

        rows = await asyncio.to_thread(_read)

        # Normalise timestamps for the frontend.
        for r in rows:
            ca = r.get("created_at")
            if hasattr(ca, "isoformat"):
                r["created_at_iso"] = ca.isoformat()
                r["created_at"] = ca.isoformat()

        # Build heatmap aggregation: (symbol, setup_type) → total + by-reason
        agg: Dict[tuple, Dict[str, Any]] = {}
        reason_totals: Dict[str, int] = {}
        for r in rows:
            sym = str(r.get("symbol") or "?").upper()
            stp = str(r.get("setup_type") or "?").lower()
            rsn = str(r.get("reason") or "unknown")
            key = (sym, stp)
            cell = agg.setdefault(key, {
                "symbol": sym,
                "setup_type": stp,
                "total_rejections": 0,
                "by_reason": {},
            })
            cell["total_rejections"] += 1
            cell["by_reason"][rsn] = cell["by_reason"].get(rsn, 0) + 1
            reason_totals[rsn] = reason_totals.get(rsn, 0) + 1

        heatmap_rows = sorted(
            agg.values(),
            key=lambda c: c["total_rejections"],
            reverse=True,
        )
        symbols = sorted({c["symbol"] for c in heatmap_rows})
        setups = sorted({c["setup_type"] for c in heatmap_rows})
        max_rejections = max((c["total_rejections"] for c in heatmap_rows), default=0)
        top_reasons = sorted(
            [{"reason": k, "count": v} for k, v in reason_totals.items()],
            key=lambda x: x["count"], reverse=True,
        )[:10]

        return {
            "success": True,
            "events": rows,
            "heatmap": {
                "rows": heatmap_rows,
                "symbols": symbols,
                "setups": setups,
                "max_rejections": max_rejections,
                "total_events": len(rows),
                "top_reasons": top_reasons,
            },
            "filters": {
                "days": days,
                "symbol": symbol,
                "setup_type": setup_type,
                "limit": limit,
            },
        }
    except Exception as e:
        logger.error(f"rejection-events error: {e}", exc_info=True)
        return {"success": False, "error": str(e), "events": [], "heatmap": {"rows": []}}


# ─── v19.34.10 — State integrity (drift watchdog) endpoints ───────────
@router.get("/integrity-status")
async def get_integrity_status():
    """Return the current drift-watchdog snapshot.

    Surfaces whether the in-memory `risk_params` matches the persisted
    `bot_state.risk_params` in MongoDB, plus a short history of the
    most-recent check (drift count, fields involved, resolution policy).

    Built after the v19.34.9 catastrophic skew where in-memory said
    $236k while Mongo still said $100k, causing 135+ ghost rejection
    brackets on a stale daily-loss cap. v19.34.10 makes that class of
    bug auto-detectable and (by default) auto-resolved.
    """
    try:
        from services.state_integrity_service import get_state_integrity_service
        svc = get_state_integrity_service()
        return {"success": True, **svc.get_status()}
    except Exception as e:
        logger.error(f"integrity-status error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@router.post("/force-resync")
async def force_state_resync(payload: Optional[Dict[str, Any]] = None):
    """Operator-driven on-demand integrity check.

    Body (all optional):
      {
        "auto_resolve": true,    // override env STATE_INTEGRITY_AUTO_RESOLVE
        "dry_run":      false,   // alias of auto_resolve=false
        "rearm_demoted": false   // v19.34.14 — clear loop-demote set first
                                 //              (use after manual fix)
      }

    Returns the same shape as `integrity-status`'s `last_check` plus
    `{resolved: <int>, unresolved: <int>}`.
    """
    if _trading_bot is None:
        raise HTTPException(503, "Trading bot not initialized")
    payload = payload or {}
    try:
        from services.state_integrity_service import get_state_integrity_service
        svc = get_state_integrity_service()
        # v19.34.14 — let operator re-arm a field that the loop
        # detector demoted to detect-only after watchdog oscillation.
        if payload.get("rearm_demoted") is True:
            svc.reset_loop_state()
        auto_resolve = payload.get("auto_resolve")
        if payload.get("dry_run") is True:
            auto_resolve = False
        result = await svc.run_check_once(_trading_bot, auto_resolve=auto_resolve)
        result_dict = result.to_dict()
        resolved = sum(1 for d in result.drifts if d.resolved)
        unresolved = len(result.drifts) - resolved
        return {
            "success": True,
            "resolved": resolved,
            "unresolved": unresolved,
            **result_dict,
        }
    except Exception as e:
        logger.error(f"force-resync error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


# ─── v19.34.18 — Share-drift loop diagnostic ────────────────────────
@router.get("/share-drift-status")
async def share_drift_status(symbols: Optional[str] = None) -> Dict[str, Any]:
    """Read-only diagnostic for the v19.34.15b share-count drift loop.

    Returns:
      • loop_alive: is the background task running + heart-beating?
      • diag: tick count, last_tick_at, last_tick_status, last_result_summary
      • per_symbol: for each tracked symbol (or filtered), shows
          { bot_qty, ib_qty, drift, would_act, threshold }
        — pure read-only snapshot of what the loop would see right now.

    Query: ?symbols=FDX,UPS to filter; omit for all tracked symbols.
    """
    if _trading_bot is None:
        raise HTTPException(503, "Trading bot not initialized")

    # Loop liveness
    task = getattr(_trading_bot, "_share_drift_task", None)
    loop_alive = bool(task) and not (task.done() if task else True)
    task_exception = None
    if task and task.done():
        try:
            task_exception = repr(task.exception()) if task.exception() else None
        except Exception:
            task_exception = "could not read exception"

    diag = getattr(_trading_bot, "_share_drift_diag", None) or {
        "tick_count": 0, "last_tick_at": None, "last_tick_status": "never_ran",
    }

    # Per-symbol live snapshot — same data the loop would read.
    from routers.ib import _pushed_ib_data, is_pusher_connected
    pusher_connected = is_pusher_connected()
    ib_positions = ((_pushed_ib_data or {}).get("positions") or {})

    sym_filter = None
    if symbols:
        sym_filter = {s.strip().upper() for s in symbols.split(",") if s.strip()}

    per_symbol: List[Dict[str, Any]] = []
    open_trades = getattr(_trading_bot, "_open_trades", {}) or {}
    by_sym: Dict[str, list] = {}
    for t in open_trades.values():
        s = (getattr(t, "symbol", None) or "").upper()
        if not s:
            continue
        by_sym.setdefault(s, []).append(t)

    universe = set(by_sym.keys())
    # Also include IB-side symbols even if bot doesn't track (orphans).
    for raw_sym in ib_positions.keys():
        s = (raw_sym or "").upper()
        if s:
            universe.add(s)
    if sym_filter:
        universe = {s for s in universe if s in sym_filter}

    for sym in sorted(universe):
        trades = by_sym.get(sym, [])
        bot_qty_signed = 0
        for t in trades:
            sh = int(abs(getattr(t, "remaining_shares", 0) or 0))
            direction = (getattr(t, "direction", None))
            dir_val = getattr(direction, "value", None) or str(direction or "").lower()
            sign = 1 if dir_val == "long" else (-1 if dir_val == "short" else 0)
            bot_qty_signed += sign * sh

        ib_pos = ib_positions.get(sym) or {}
        ib_qty_signed = int(ib_pos.get("position") or 0)
        drift = ib_qty_signed - bot_qty_signed
        would_act = abs(drift) > 1

        per_symbol.append({
            "symbol": sym,
            "bot_qty_signed": bot_qty_signed,
            "ib_qty_signed": ib_qty_signed,
            "drift": drift,
            "drift_abs": abs(drift),
            "would_act": would_act,
            "tracked_trades": len(trades),
            "verdict": (
                "drift_detected" if would_act else
                "in_sync" if abs(drift) <= 1 else "untracked"
            ),
        })

    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "loop": {
            "alive": loop_alive,
            "task_exception": task_exception,
            "feature_flag": os.environ.get(
                "SHARE_DRIFT_RECONCILE_ENABLED", "true"
            ).lower() in ("true", "1", "yes", "on"),
            "interval_s": int(os.environ.get("SHARE_DRIFT_RECONCILE_INTERVAL_S", "30") or 30),
        },
        "diag": diag,
        "pusher_connected": pusher_connected,
        "drift_threshold": 1,
        "symbol_filter": sorted(sym_filter) if sym_filter else None,
        "per_symbol": per_symbol,
        "summary": {
            "total_symbols": len(per_symbol),
            "drift_detected_count": sum(1 for r in per_symbol if r["would_act"]),
            "drift_symbols": [r["symbol"] for r in per_symbol if r["would_act"]],
        },
    }


# ─── v19.34.15b — Share-count drift reconciler ──────────────────────
@router.post("/reconcile-share-drift")
async def reconcile_share_drift_endpoint(
    payload: Optional[Dict[str, Any]] = None,
):
    """Detect + resolve share-count drift on already-tracked symbols.

    Body (all optional):
      {
        "drift_threshold": 1,        // shares; ignored when |drift| <= this
        "auto_resolve":     true,    // false → detect-only dry run
        "dry_run":          false    // alias for auto_resolve=false
      }

    Returns the full drift report with three classes of drift:
      • excess_unbracketed   IB has more — spawned `reconciled_excess_slice`
      • partial_external_close   IB has fewer — shrunk bot tracking
      • zero_external_close   IB has 0 — closed bot tracking

    Built after v19.34.15b operator-caught UPS drift (IB 5,304 vs bot 425).
    """
    if _trading_bot is None:
        raise HTTPException(503, "Trading bot not initialized")
    payload = payload or {}
    threshold = int(payload.get("drift_threshold") or 1)
    if threshold < 1:
        threshold = 1
    auto_resolve = payload.get("auto_resolve", True)
    if payload.get("dry_run") is True:
        auto_resolve = False

    try:
        # Reuse the position_reconciler instance owned by the bot.
        reconciler = getattr(_trading_bot, "_position_reconciler", None)
        if reconciler is None:
            from services.position_reconciler import PositionReconciler
            reconciler = PositionReconciler(_trading_bot._db)
        result = await reconciler.reconcile_share_drift(
            _trading_bot,
            drift_threshold=threshold,
            auto_resolve=bool(auto_resolve),
        )
        return result
    except Exception as e:
        logger.error(f"reconcile-share-drift error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@router.post("/refresh-account")
async def refresh_account():
    """Force-pull the latest IB account equity and sync it into
    `risk_params.starting_capital`. Operator-flagged 2026-04-29:
    convenience endpoint so the bot's position sizer can be unstuck
    without waiting for the next `/status` poll.
    """
    if _trading_bot is None:
        raise HTTPException(503, "Trading bot not initialized")
    try:
        from routers.ib import _pushed_ib_data, _extract_account_value
        from services.ib_pusher_rpc import get_account_snapshot

        # Try push-loop first, then RPC fallback.
        ib_account = (_pushed_ib_data or {}).get("account") or {}
        if not ib_account:
            # v19.30.8 (2026-05-02 evening): wrap in asyncio.to_thread.
            # Same wedge class as get_bot_status fix earlier in this
            # commit; refresh_account is operator-triggered and
            # tolerant of latency, but still must not block the loop.
            snap = await asyncio.to_thread(get_account_snapshot) or {}
            if snap.get("success") and snap.get("account"):
                ib_account = snap["account"]
                _pushed_ib_data["account"] = ib_account

        if not ib_account:
            return {
                "success": False,
                "error": "no_account_data",
                "message": "Both push-loop and RPC came up empty — "
                           "check Windows pusher + IB Gateway connection",
            }

        net_liq = _extract_account_value(ib_account, "NetLiquidation", 0)
        if not net_liq or net_liq <= 0:
            return {
                "success": False,
                "error": "invalid_net_liq",
                "message": f"NetLiquidation read as {net_liq} — IB session may be unauthenticated",
            }

        old_capital = float(_trading_bot.risk_params.starting_capital or 0)
        _trading_bot.risk_params.starting_capital = float(net_liq)
        # v19.34.9 (2026-05-05 PM) — also recompute the absolute USD
        # daily-loss cap from the new starting_capital. Without this,
        # `max_daily_loss` stays at whatever it was on previous bootup
        # (often $0 or stale) and the bot's gate at line 2536 of
        # trading_bot_service.py won't bind correctly.
        try:
            _trading_bot.risk_params.max_daily_loss = (
                float(net_liq) * float(_trading_bot.risk_params.max_daily_loss_pct or 0) / 100.0
            )
        except Exception:
            pass
        # v19.34.9 — CRITICAL: persist to Mongo `bot_state` so the
        # `risk_caps_service.compute_effective_risk_caps` reader (and
        # any other Mongo-driven consumer) sees the new value. Operator
        # surfaced this 2026-05-05 PM: refresh-account reported success
        # but `effective-limits` kept showing the stale $100k value
        # because risk_caps_service reads from Mongo while refresh
        # was only updating in-memory.
        try:
            await _trading_bot._save_state()
            logger.info(
                "💾 [v19.34.9] refresh-account persisted starting_capital="
                f"${net_liq:,.0f} to Mongo bot_state"
            )
        except Exception as _save_err:
            logger.warning(
                f"refresh-account save_state failed (in-memory updated, "
                f"Mongo NOT updated — re-run on next manage-loop save): {_save_err}"
            )
        logger.info(
            f"💰 Manual refresh: starting_capital ${old_capital:,.0f} → ${net_liq:,.0f}"
        )
        return {
            "success": True,
            "old_starting_capital": old_capital,
            "new_starting_capital": float(net_liq),
            "delta": float(net_liq) - old_capital,
            "max_daily_loss_usd_recomputed": float(_trading_bot.risk_params.max_daily_loss),
            "persisted_to_mongo": True,
            "source": "rpc" if not (_pushed_ib_data or {}).get("account_seeded_by_push") else "push",
        }
    except Exception as e:
        logger.error(f"refresh-account failed: {e}")
        raise HTTPException(500, f"refresh failed: {e}")


@router.get("/rejection-analytics")
async def get_rejection_analytics(
    days: int = Query(7, ge=1, le=90,
                      description="Lookback window in days. Default 7."),
    min_count: int = Query(3, ge=1, le=100,
                           description="Skip reason_codes that fired fewer "
                                       "times than this. Default 3."),
):
    """Aggregate rejection events from `sentcom_thoughts` and join with
    `bot_trades` to surface "which gates are over-tight?"

    Closes the loop on the new rejection-narrative pipeline shipped
    2026-04-29 afternoon-4. Read-only — does NOT modify thresholds.
    Operator reviews and feeds insights into the existing
    `multiplier_threshold_optimizer` / `gate_calibrator` tunings.

    Verdicts:
      - `gate_potentially_overtight` — post-rejection win rate ≥ 65%
      - `gate_borderline`            — 45-65%
      - `gate_calibrated`            — < 45%
      - `insufficient_data`          — fewer than 5 post-rejection trades
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    db = _trading_bot._db
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")

    from services.rejection_analytics import compute_rejection_analytics
    return compute_rejection_analytics(db, days=days, min_count=min_count)



@router.get("/execution-health")
async def get_execution_health(
    hours: int = Query(24, ge=1, le=8760,
                       description="Window size in hours (1 — 8760 = 1 year)."),
    flag_trades: bool = Query(
        False, description="If true, also persist stop_honored flag onto trade docs."),
):
    """Return Trade Execution Health report.

    Scans closed bot_trades in the window and flags stop-execution failures
    (losers that blew past 1.5R = their intended stop wasn't honored at IB).

    Alert levels:
      - `ok`                 : failure rate < 5%
      - `warning`            : 5% — 15% (investigate)
      - `critical`           : > 15% (stop trading, fix stop orders)
      - `insufficient_data`  : < 5 closed trades in window
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    db = _trading_bot._db
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")

    from services.trade_execution_health import TradeExecutionHealth
    health = TradeExecutionHealth(db)
    report = health.audit_recent_trades(hours=hours)
    flagged = health.flag_trade_docs(hours=hours) if flag_trades else 0

    return {
        "success": True,
        "report": report.to_dict(),
        "flagged_docs": flagged,
    }


@router.get("/trade-autopsy/{trade_id}")
async def get_trade_autopsy(trade_id: str):
    """Full forensic view for any closed trade (2026-04-21).

    Assembles bot_trades + gate_decisions + live_alerts into one dict so you
    can see exactly why a losing trade fired: entry/exit, realized R,
    stop-honor status, layer-by-layer gate vote, P(win), and the scanner
    context at entry.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    db = _trading_bot._db
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")

    from services.trade_autopsy import TradeAutopsy
    autopsy = TradeAutopsy(db).autopsy(trade_id)
    if autopsy is None:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
    return {"success": True, "autopsy": autopsy}


@router.get("/recent-losses")
async def get_recent_losses(limit: int = Query(20, ge=1, le=200)):
    """List the worst recent losing trades for triage-by-autopsy workflow."""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    db = _trading_bot._db
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")

    from services.trade_autopsy import TradeAutopsy
    losses = TradeAutopsy(db).recent_losses(limit=limit)
    return {"success": True, "count": len(losses), "losses": losses}


@router.post("/positions/protect-orphans")
async def protect_orphan_positions(
    risk_pct: float = Query(0.01, ge=0.001, le=0.10,
                            description="Emergency stop distance as pct of avg cost when no intended stop is known"),
    dry_run: bool = Query(True, description="Default to dry-run for safety; pass false to actually place stops"),
):
    """Place emergency STP orders on IB positions that have no working stop.

    Phase 4 of the IB bracket migration (see IB_BRACKET_ORDER_MIGRATION.md).
    Invoke at startup or after suspected stop failures to close the naked-
    position gap that caused the PD/GNW imported_from_ib losses.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    if not hasattr(_trading_bot, "_position_reconciler") or not _trading_bot._position_reconciler:
        raise HTTPException(status_code=503, detail="Position reconciler not initialized")

    report = await _trading_bot._position_reconciler.protect_orphan_positions(
        _trading_bot, risk_pct=risk_pct, dry_run=dry_run,
    )
    return {"success": True, "report": report}


@router.post("/start")
async def start_bot():
    """Start the trading bot"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    from services.trading_bot_service import BotMode
    from services.enhanced_scanner import get_enhanced_scanner
    
    await _trading_bot.start()
    
    # Sync scanner auto-execute with bot mode on start
    bot_mode = _trading_bot.get_mode()
    scanner = get_enhanced_scanner()
    if scanner:
        if bot_mode == BotMode.AUTONOMOUS:
            scanner.enable_auto_execute(True, min_win_rate=0.55, min_priority="high")
        else:
            scanner.enable_auto_execute(False)
    
    return {"success": True, "message": "Trading bot started", "mode": bot_mode.value, "scanner_auto_execute": bot_mode == BotMode.AUTONOMOUS}


@router.post("/stop")
async def stop_bot():
    """Stop the trading bot"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    await _trading_bot.stop()
    return {"success": True, "message": "Trading bot stopped"}


@router.get("/executor/status")
def get_executor_status():
    """Get trade executor status and current broker"""
    if not _trade_executor:
        raise HTTPException(status_code=503, detail="Trade executor not initialized")
    
    return {
        "success": True,
        "mode": _trade_executor.get_mode().value,
        "broker": "alpaca" if _trade_executor.get_mode().value == "paper" else "interactive_brokers" if _trade_executor.get_mode().value == "live" else "simulated",
        "description": {
            "paper": "Orders routed to Alpaca paper trading",
            "live": "Orders routed to Interactive Brokers",
            "simulated": "No actual orders placed (simulation only)"
        }.get(_trade_executor.get_mode().value, "Unknown")
    }


@router.post("/executor/mode/{mode}")
def set_executor_mode(mode: str):
    """
    Set trade execution mode/broker.
    
    Modes:
    - paper: Route orders to Alpaca paper trading
    - live: Route orders to Interactive Brokers (requires IB Gateway)
    - simulated: No actual orders, just simulate fills
    """
    if not _trade_executor:
        raise HTTPException(status_code=503, detail="Trade executor not initialized")
    
    from services.trade_executor_service import ExecutorMode
    
    mode_lower = mode.lower()
    if mode_lower not in ["paper", "live", "simulated"]:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}. Use 'paper', 'live', or 'simulated'")
    
    try:
        executor_mode = ExecutorMode(mode_lower)
        _trade_executor.set_mode(executor_mode)
        
        return {
            "success": True,
            "mode": mode_lower,
            "broker": "alpaca" if mode_lower == "paper" else "interactive_brokers" if mode_lower == "live" else "simulated",
            "message": f"Trade execution now using {mode_lower} mode"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mode/{mode}")
def set_bot_mode(mode: str):
    """Set bot operating mode (autonomous, confirmation, paused)"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    from services.trading_bot_service import BotMode
    from services.enhanced_scanner import get_enhanced_scanner
    
    try:
        bot_mode = BotMode(mode.lower())
        _trading_bot.set_mode(bot_mode)
        
        # Sync scanner auto-execute with bot mode
        scanner = get_enhanced_scanner()
        if scanner:
            if bot_mode == BotMode.AUTONOMOUS:
                # Enable scanner auto-execute when bot is autonomous
                scanner.enable_auto_execute(True, min_win_rate=0.55, min_priority="high")
            else:
                # Disable scanner auto-execute for other modes
                scanner.enable_auto_execute(False)
        
        return {"success": True, "mode": bot_mode.value, "scanner_auto_execute": bot_mode == BotMode.AUTONOMOUS}
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}. Use 'autonomous', 'confirmation', or 'paused'")


@router.post("/config")
def update_bot_config(config: BotConfigUpdate):
    """Update bot configuration"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    from services.trading_bot_service import BotMode
    from services.enhanced_scanner import get_enhanced_scanner
    
    if config.mode:
        try:
            bot_mode = BotMode(config.mode.lower())
            _trading_bot.set_mode(bot_mode)
            
            # Sync scanner auto-execute with bot mode
            scanner = get_enhanced_scanner()
            if scanner:
                if bot_mode == BotMode.AUTONOMOUS:
                    scanner.enable_auto_execute(True, min_win_rate=0.55, min_priority="high")
                else:
                    scanner.enable_auto_execute(False)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid mode: {config.mode}")
    
    if config.enabled_setups:
        _trading_bot.set_enabled_setups(config.enabled_setups)
    
    if config.scan_interval:
        _trading_bot._scan_interval = config.scan_interval
    
    if config.watchlist:
        _trading_bot.set_watchlist(config.watchlist)
    
    return {"success": True, "message": "Configuration updated"}


@router.post("/risk-params")
def update_risk_params(params: RiskParamsUpdate):
    """Update risk management parameters"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    updates = params.dict(exclude_none=True)
    _trading_bot.update_risk_params(**updates)
    
    return {"success": True, "risk_params": _trading_bot.get_status()["risk_params"]}


# 2026-05-01 v19.21 — explicit GET so the operator can verify what's
# actually live without parsing the full bot status payload. Also returns
# the per-setup R:R map and which "effective" floor each enabled setup
# resolves to (so a glance at this endpoint shows whether your tuning
# took effect).
@router.get("/risk-params")
def get_risk_params():
    """Return the live risk parameters + effective per-setup R:R floors."""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    risk = _trading_bot.get_status()["risk_params"]
    # Compute the resolved (effective) R:R for every enabled setup so the
    # operator can see e.g. `vwap_fade_long → 1.5 (override)` vs
    # `breakout → 2.0 (override)` vs `accumulation_entry → 1.7 (global)`.
    enabled = list(getattr(_trading_bot, "_enabled_setups", []) or [])
    effective_by_setup: Dict[str, Dict[str, Any]] = {}
    for s in enabled:
        eff = _trading_bot.risk_params.effective_min_rr(s)
        is_override = eff != _trading_bot.risk_params.min_risk_reward
        effective_by_setup[s] = {
            "effective_rr": eff,
            "source": "override" if is_override else "global",
        }
    return {
        "success": True,
        "risk_params": risk,
        "effective_by_setup": effective_by_setup,
    }


# 2026-05-01 v19.21 — One-curl rescue endpoint. Forces global +
# per-setup R:R floors back to the v19.21 ship defaults. Useful when
# Mongo persisted state has drifted from the code defaults (e.g. the
# operator's HOOD-feed bug where saved global was 2.5 even though the
# code default and operator preference said otherwise).
# 2026-05-01 v19.22.2 — converted to `async def` + `await _save_state()`
# so the Mongo write completes BEFORE the response returns. The earlier
# sync-handler version fired-and-forgot the save via
# `asyncio.create_task(...)`; if the operator restarted the backend
# moments later (which the operator did this morning to deploy v19.21),
# the Mongo write was lost and persistence pulled the OLD 2.5 back on
# the next state restore. Operator caught it via:
#   $ curl POST /reset-rr-defaults  # in-memory says 1.7
#   $ curl POST /risk-params {merge}  # response shows 2.5 again
# This change makes the reset durable through restarts.
@router.post("/reset-rr-defaults")
async def reset_rr_defaults():
    """Reset min_risk_reward + setup_min_rr to v19.21 ship defaults.
    Awaits the Mongo persistence write so the value survives restart."""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    from services.trading_bot_service import RiskParameters
    fresh = RiskParameters()
    _trading_bot.risk_params.min_risk_reward = fresh.min_risk_reward
    # Replace the dict wholesale (this endpoint INTENTIONALLY clobbers).
    _trading_bot.risk_params.setup_min_rr = dict(fresh.setup_min_rr)
    persisted = False
    try:
        await _trading_bot._save_state()
        persisted = True
    except Exception as exc:
        # Persistence failure is logged but not fatal — the in-memory
        # state is correct, the next periodic save tick will retry.
        import logging
        logging.getLogger(__name__).warning(
            f"reset-rr-defaults save_state failed: {exc} (in-memory still set)"
        )
    return {
        "success": True,
        "message": "R:R defaults reset to v19.21 ship values.",
        "persisted_to_mongo": persisted,
        "risk_params": _trading_bot.get_status()["risk_params"],
    }


# ==================== EOD AUTO-CLOSE ====================

class EODConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    close_hour: Optional[int] = None  # 0-23 in ET
    close_minute: Optional[int] = None  # 0-59


@router.get("/eod-config")
def get_eod_config():
    """Get EOD auto-close configuration"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    return {
        "success": True,
        "eod_config": {
            "enabled": _trading_bot._eod_close_enabled,
            "close_hour": _trading_bot._eod_close_hour,
            "close_minute": _trading_bot._eod_close_minute,
            "close_time_et": f"{_trading_bot._eod_close_hour}:{_trading_bot._eod_close_minute:02d} PM ET",
            "executed_today": _trading_bot._eod_close_executed_today,
            "last_check_date": _trading_bot._last_eod_check_date
        }
    }


@router.post("/eod-config")
def update_eod_config(config: EODConfigUpdate):
    """Update EOD auto-close configuration"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    if config.enabled is not None:
        _trading_bot._eod_close_enabled = config.enabled
    
    if config.close_hour is not None:
        if not 0 <= config.close_hour <= 23:
            raise HTTPException(status_code=400, detail="close_hour must be 0-23")
        _trading_bot._eod_close_hour = config.close_hour
    
    if config.close_minute is not None:
        if not 0 <= config.close_minute <= 59:
            raise HTTPException(status_code=400, detail="close_minute must be 0-59")
        _trading_bot._eod_close_minute = config.close_minute
    
    # Persist config to database
    if _trading_bot._db:
        _trading_bot._db.bot_config.update_one(
            {"_id": "eod_config"},
            {"$set": {
                "enabled": _trading_bot._eod_close_enabled,
                "close_hour": _trading_bot._eod_close_hour,
                "close_minute": _trading_bot._eod_close_minute,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
    
    return {
        "success": True,
        "eod_config": {
            "enabled": _trading_bot._eod_close_enabled,
            "close_hour": _trading_bot._eod_close_hour,
            "close_minute": _trading_bot._eod_close_minute,
            "close_time_et": f"{_trading_bot._eod_close_hour}:{_trading_bot._eod_close_minute:02d} PM ET"
        },
        "message": "EOD configuration updated"
    }


@router.post("/eod-close-now")
async def trigger_eod_close_now():
    """
    Manually trigger EOD close of all positions.
    Use this to close all positions immediately regardless of time.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    open_count = len(_trading_bot._open_trades)
    if open_count == 0:
        return {"success": True, "message": "No open positions to close", "closed_count": 0}
    
    closed_count = 0
    total_pnl = 0.0
    results = []
    
    # 2026-04-30 v19.14 — close_trade returns a BOOL, not a dict.
    # Was calling `.get("success")` on the bool → silent AttributeError
    # made every manual EOD attempt look like a no-op. Now we treat
    # the bool correctly + read realized_pnl from the trade post-close.
    for trade_id, trade in list(_trading_bot._open_trades.items()):
        try:
            ok = await _trading_bot.close_trade(trade_id, reason="manual_eod_close")
            if ok:
                closed_count += 1
                pnl = float(getattr(trade, "realized_pnl", 0.0) or 0.0)
                total_pnl += pnl
                results.append({
                    "symbol": trade.symbol,
                    "shares": getattr(trade, "remaining_shares", 0),
                    "pnl": pnl,
                    "status": "closed"
                })
            else:
                results.append({
                    "symbol": trade.symbol,
                    "error": "close_trade returned False (broker refused / executor offline)",
                    "status": "failed"
                })
        except Exception as e:
            results.append({
                "symbol": trade.symbol,
                "error": str(e),
                "status": "error"
            })
    
    return {
        "success": True,
        "message": f"Closed {closed_count} of {open_count} positions",
        "closed_count": closed_count,
        "total_pnl": total_pnl,
        "results": results
    }


@router.get("/eod-status")
def get_eod_status():
    """
    EOD lookahead: countdown + intraday-positions-queued summary.

    Drives the V5 EOD countdown banner (v19.14 — 2026-04-30). The
    banner activates 5 min before the close window so the operator
    has a last-minute window to flatten manually or extend a winning
    position before auto-close fires.

    Returns:
      - status: "idle" / "imminent" (≤5 min) / "closing" / "complete" /
                "alarm" (positions still open past 4:00 PM)
      - eta_seconds: seconds until close window opens (negative once past)
      - intraday_positions_queued: count of trades flagged close_at_eod=True
      - swing_positions_holding: count of trades flagged close_at_eod=False
      - close_time_et: human-readable close window
      - is_half_day: env-flagged half-day mode
      - executed_today / fully_done

    Designed to be cheap and pollable every 5-10s during the
    activation window.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")

    import os as _os
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    is_half_day = _os.environ.get("EOD_HALF_DAY_TODAY", "").lower() in ("true", "1", "yes")
    if is_half_day:
        eod_hour, eod_minute, market_close_hour = 12, 55, 13
    else:
        eod_hour = _trading_bot._eod_close_hour
        eod_minute = _trading_bot._eod_close_minute
        market_close_hour = 16

    now_et = datetime.now(ZoneInfo("America/New_York"))
    today_str = now_et.strftime("%Y-%m-%d")
    target = now_et.replace(hour=eod_hour, minute=eod_minute, second=0, microsecond=0)
    eta_seconds = int((target - now_et).total_seconds())

    intraday_queued = 0
    swing_holding = 0
    intraday_symbols = []
    for trade in _trading_bot._open_trades.values():
        if getattr(trade, "close_at_eod", True):
            intraday_queued += 1
            if len(intraday_symbols) < 25:
                intraday_symbols.append(trade.symbol)
        else:
            swing_holding += 1

    is_weekend = now_et.weekday() >= 5
    is_after_close = now_et.hour >= market_close_hour
    executed_today = (
        _trading_bot._eod_close_executed_today
        and _trading_bot._last_eod_check_date == today_str
    )

    if not _trading_bot._eod_close_enabled or is_weekend:
        status = "idle"
    elif executed_today:
        status = "complete"
    elif is_after_close and intraday_queued > 0:
        status = "alarm"
    elif eta_seconds <= 0 and intraday_queued > 0 and not is_after_close:
        # Window has opened, closes are running. Bounded by market_close_hour.
        status = "closing"
    elif 0 < eta_seconds <= 300:  # 5-min imminent window
        status = "imminent"
    else:
        status = "idle"

    return {
        "success": True,
        "status": status,
        "eta_seconds": eta_seconds,
        "intraday_positions_queued": intraday_queued,
        "swing_positions_holding": swing_holding,
        "intraday_symbols": intraday_symbols,
        "close_hour": eod_hour,
        "close_minute": eod_minute,
        "close_time_et": f"{eod_hour}:{eod_minute:02d} ET",
        "market_close_hour_et": market_close_hour,
        "is_half_day": is_half_day,
        "is_weekend": is_weekend,
        "enabled": _trading_bot._eod_close_enabled,
        "executed_today": executed_today,
        "now_et": now_et.strftime("%H:%M:%S"),
    }


# ==================== TRADE MANAGEMENT ====================

@router.get("/trades/pending")
def get_pending_trades():
    """Get all trades awaiting confirmation"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    trades = _trading_bot.get_pending_trades()
    return {"success": True, "count": len(trades), "trades": trades}


@router.get("/trades/open")
def get_open_trades():
    """Get all open positions"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    trades = _trading_bot.get_open_trades()
    return {"success": True, "count": len(trades), "trades": trades}


@router.get("/trades/closed")
def get_closed_trades(limit: int = Query(50, ge=1, le=500)):
    """Get closed trades history"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    trades = _trading_bot.get_closed_trades(limit=limit)
    return {"success": True, "count": len(trades), "trades": trades}


@router.get("/trades/all")
def get_all_trades():
    """Get all bot trades (pending, open, closed) for the AI Command Panel"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    summary = _trading_bot.get_all_trades_summary()
    return {"success": True, **summary}


@router.delete("/trades/{symbol}")
def delete_trade_by_symbol(symbol: str):
    """
    Delete a trade from bot_trades by symbol. 
    Use for removing erroneous or imported trades that should not be in the system.
    Removes from both in-memory tracking and MongoDB.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    symbol = symbol.upper()
    removed = []
    
    # Remove from in-memory open trades
    to_remove = [tid for tid, t in _trading_bot._open_trades.items() if t.symbol.upper() == symbol]
    for tid in to_remove:
        del _trading_bot._open_trades[tid]
        removed.append({"id": tid, "source": "open_trades"})
    
    # Remove from in-memory closed trades
    before = len(_trading_bot._closed_trades)
    _trading_bot._closed_trades = [t for t in _trading_bot._closed_trades if t.symbol.upper() != symbol]
    closed_removed = before - len(_trading_bot._closed_trades)
    if closed_removed > 0:
        removed.append({"count": closed_removed, "source": "closed_trades"})
    
    # Remove from MongoDB bot_trades
    if _trading_bot._db is not None:
        result = _trading_bot._db.bot_trades.delete_many({"symbol": symbol})
        if result.deleted_count > 0:
            removed.append({"count": result.deleted_count, "source": "mongodb_bot_trades"})
        
        # Also remove any confidence gate logs for this symbol (prevent learning)
        cg_result = _trading_bot._db.confidence_gate_log.delete_many({"symbol": symbol})
        if cg_result.deleted_count > 0:
            removed.append({"count": cg_result.deleted_count, "source": "confidence_gate_log"})
    
    if not removed:
        return {"success": True, "message": f"No trades found for {symbol}", "removed": []}
    
    return {"success": True, "message": f"Deleted all {symbol} trade data", "removed": removed}



@router.get("/positions/reconcile")
async def reconcile_positions():
    """
    Compare bot's tracked positions with actual IB positions.
    Returns discrepancies that need attention.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    try:
        report = await _trading_bot.reconcile_positions_with_ib()
        return {
            "success": True,
            **report
        }
    except Exception as e:
        logger.error(f"Reconciliation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/positions/sync/{symbol}")
async def sync_position(symbol: str, auto_create: bool = False):
    """
    Sync a specific position from IB to the bot's tracking.
    
    Args:
        symbol: Stock symbol to sync
        auto_create: If True, create a new trade entry for untracked positions
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    try:
        result = await _trading_bot.sync_position_from_ib(symbol, auto_create_trade=auto_create)
        return result
    except Exception as e:
        logger.error(f"Sync error for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/positions/sync-all")
async def sync_all_positions():
    """
    Full position sync - imports untracked positions, closes phantoms, fixes mismatches.
    This is the comprehensive sync that should be run on startup or when positions drift.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    try:
        report = await _trading_bot.full_position_sync()
        return report
    except Exception as e:
        logger.error(f"Full sync error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/positions/close-phantom/{trade_id}")
async def close_phantom_trade(trade_id: str, reason: str = "manual_close"):
    """
    Close a specific phantom trade (one that bot tracks but IB doesn't have).
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    try:
        result = await _trading_bot.close_phantom_position(trade_id, reason=reason)
        return result
    except Exception as e:
        logger.error(f"Close phantom error for {trade_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== PROPER RECONCILE (v19.24 — 2026-05-01) =====================

class ReconcileRequest(BaseModel):
    """Body for POST /api/trading-bot/reconcile.

    Either `symbols=[...]` must be provided OR `all=True` with
    `confirm="RECONCILE_ALL"` — the `confirm` token prevents accidental
    sweeps when an IB connectivity blip briefly flashes stale positions
    (mirrors the /api/portfolio/flatten-paper?confirm=FLATTEN safety
    pattern). Optional `stop_pct` / `rr` overrides the per-bot defaults
    on `RiskParameters.reconciled_default_{stop_pct,rr}`.
    """
    symbols: Optional[List[str]] = None
    all: bool = False
    confirm: Optional[str] = None
    stop_pct: Optional[float] = None
    rr: Optional[float] = None


@router.post("/reconcile")
async def reconcile_orphan_positions(req: ReconcileRequest):
    """Materialize bot_trades for IB-only (orphan) positions so the bot
    can actively manage them (trail stops, scale-out, EOD close).
    
    v19.23.1 shipped read-only "lazy reconcile" in sentcom_service that
    fixed the V5 UI display only. This endpoint is the proper write-
    through path — after POST, the orphan positions are in the bot's
    in-memory `_open_trades` AND persisted to Mongo `bot_trades`, so the
    manage loop will trail stops / scale out / EOD-close them.
    
    Body:
      - `symbols`: explicit list (recommended, always works)
          POST /reconcile {"symbols": ["SBUX", "SOFI", "OKLO"]}
      - `all` + `confirm`: sweep all orphans (requires confirm token)
          POST /reconcile {"all": true, "confirm": "RECONCILE_ALL"}
      - `stop_pct` / `rr`: per-request overrides for default bracket
    
    Response:
      {
        success: bool,
        reconciled: [{symbol, trade_id, shares, stop_price, target_price, …}],
        skipped: [{symbol, reason: "already_tracked" | "no_ib_position" |
                   "stop_already_breached" | "invalid_avg_cost"}],
        errors: [{symbol, error}]
      }
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    # Safety: `all=true` requires explicit confirm token.
    if req.all and req.confirm != "RECONCILE_ALL":
        raise HTTPException(
            status_code=400,
            detail="all=true requires confirm='RECONCILE_ALL'",
        )
    if not req.all and not req.symbols:
        raise HTTPException(
            status_code=400,
            detail="Provide symbols=[...] or all=true with confirm='RECONCILE_ALL'",
        )
    
    try:
        result = await _trading_bot.reconcile_orphan_positions(
            symbols=req.symbols,
            all_orphans=req.all,
            stop_pct=req.stop_pct,
            rr=req.rr,
        )
        return result
    except Exception as e:
        logger.error(f"Reconcile error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))



# ==================== CANCEL ALL PENDING ORDERS (v19.30.9 — 2026-05-01) ===========

class CancelAllPendingRequest(BaseModel):
    """Body for POST /api/trading-bot/cancel-all-pending-orders.

    Defense-in-depth pre-open safety endpoint. Requires explicit
    `confirm="CANCEL_ALL_PENDING"` token to fire — same pattern as
    /api/portfolio/flatten-paper?confirm=FLATTEN and the
    /reconcile {all:true} sweep.

    Optional `symbols=[...]` filter scopes the cancel to a subset
    (handy when only one symbol is misbehaving). When omitted (and
    confirm is present), every pending+claimed order in the queue
    AND every IB-side open order (when direct IB is connected) is
    cancelled.
    """
    confirm: Optional[str] = None
    symbols: Optional[List[str]] = None
    dry_run: bool = False


@router.post("/cancel-all-pending-orders")
async def cancel_all_pending_orders(req: CancelAllPendingRequest):
    """Cancel every pending bracket / GTC order before the bell.

    Why this matters: the operator manually flattens stuck positions
    via TWS sometimes; the IB-side OCA brackets that were attached
    to those positions don't auto-cancel. If the bot then re-fires a
    new entry, the orphaned stop/target legs from the prior bracket
    can convert into naked shorts when triggered. This endpoint
    nukes everything pre-open so the next session starts with a
    clean book.

    Two layers of cancellation, in order:

    1. **Mongo `order_queue`** (always available) — flips every
       `pending` + `claimed` row to `cancelled`. The Windows pusher
       polls this queue, so anything not yet submitted to IB is
       killed atomically.
    2. **Direct IB Gateway open orders** (when connected) — iterates
       `_ib_service.get_open_orders()` and cancels each. Falls back
       gracefully when direct IB isn't reachable from Spark
       (degraded mode, pusher-only).

    Body:
      - `confirm`: must be `"CANCEL_ALL_PENDING"` to fire (required).
      - `symbols`: optional list to scope the cancel.
      - `dry_run`: optional preview — counts what WOULD be cancelled
        without changing state. Default False.

    Response shape:
      {
        success: bool,
        dry_run: bool,
        queue_cancelled: int,         # Mongo order_queue rows flipped
        queue_skipped: int,           # rows scoped out by `symbols`
        ib_cancelled: int,            # IB-side cancellations sent
        ib_skipped: int,              # rows scoped out by `symbols`
        ib_unavailable: bool,         # True when direct IB unreachable
        ib_error: Optional[str],
        details: {
          queue: [{order_id, symbol, status_before}, ...],
          ib_orders_open_before: [{order_id, symbol, ...}, ...],
        }
      }
    """
    if req.confirm != "CANCEL_ALL_PENDING":
        raise HTTPException(
            status_code=400,
            detail="confirm='CANCEL_ALL_PENDING' is required to fire this endpoint",
        )

    sym_filter: Optional[set] = None
    if req.symbols:
        sym_filter = {s.strip().upper() for s in req.symbols if s and s.strip()}

    # ─── Layer 1: Mongo `order_queue` ────────────────────────────────────
    queue_cancelled = 0
    queue_skipped = 0
    queue_details: List[Dict[str, Any]] = []
    try:
        from services.order_queue_service import get_order_queue_service, OrderStatus
        queue_service = get_order_queue_service()

        def _sync_drain_queue() -> Dict[str, Any]:
            cancelled = 0
            skipped = 0
            details: List[Dict[str, Any]] = []
            # Re-use the service's pending+claimed query rather than touching
            # the collection directly so future schema changes propagate.
            for status_value in (OrderStatus.PENDING.value, OrderStatus.CLAIMED.value):
                rows = queue_service.get_orders_by_status(status_value) or []
                for row in rows:
                    sym = (row.get("symbol") or "").upper()
                    if sym_filter is not None and sym not in sym_filter:
                        skipped += 1
                        continue
                    order_id = row.get("order_id")
                    if not order_id:
                        continue
                    if not req.dry_run:
                        ok = queue_service.cancel_order(order_id)
                        if not ok:
                            # Race — already moved past pending/claimed.
                            continue
                    cancelled += 1
                    details.append({
                        "order_id": order_id,
                        "symbol": sym,
                        "status_before": status_value,
                    })
            return {"cancelled": cancelled, "skipped": skipped, "details": details}

        result = await asyncio.to_thread(_sync_drain_queue)
        queue_cancelled = int(result["cancelled"])
        queue_skipped = int(result["skipped"])
        queue_details = list(result["details"])
    except Exception as e:
        logger.error(f"cancel-all-pending: queue drain error: {e}", exc_info=True)

    # ─── Layer 2: Direct IB Gateway open orders ──────────────────────────
    # The Spark backend frequently runs in "degraded mode" where the only
    # IB pipeline is via the Windows pusher. We attempt the direct cancel
    # path here for completeness — when it fails we surface that fact in
    # the response so the operator knows to flatten via TWS / Workbench.
    ib_cancelled = 0
    ib_skipped = 0
    ib_unavailable = False
    ib_error: Optional[str] = None
    ib_open_before: List[Dict[str, Any]] = []
    try:
        from routers.ib import _ib_service as _direct_ib_service  # type: ignore
    except Exception:
        _direct_ib_service = None  # type: ignore

    if _direct_ib_service is None:
        ib_unavailable = True
        ib_error = "ib_service_not_initialized"
    else:
        try:
            open_orders = await _direct_ib_service.get_open_orders()
            ib_open_before = list(open_orders or [])
            for o in ib_open_before:
                sym = (o.get("symbol") or "").upper()
                if sym_filter is not None and sym not in sym_filter:
                    ib_skipped += 1
                    continue
                ib_order_id = o.get("order_id") or o.get("orderId") or o.get("id")
                if ib_order_id is None:
                    continue
                if not req.dry_run:
                    try:
                        ok = await _direct_ib_service.cancel_order(int(ib_order_id))
                        if ok:
                            ib_cancelled += 1
                    except Exception as cancel_err:
                        logger.warning(
                            f"cancel-all-pending: IB cancel for order {ib_order_id} "
                            f"({sym}) raised: {cancel_err}"
                        )
                else:
                    ib_cancelled += 1  # dry-run: count as if cancelled
        except ConnectionError as e:
            ib_unavailable = True
            ib_error = f"ib_gateway_unavailable: {e}"
        except Exception as e:
            ib_error = f"ib_open_orders_fetch_failed: {e}"
            logger.warning(f"cancel-all-pending: {ib_error}", exc_info=True)

    return {
        "success": True,
        "dry_run": bool(req.dry_run),
        "queue_cancelled": queue_cancelled,
        "queue_skipped": queue_skipped,
        "ib_cancelled": ib_cancelled,
        "ib_skipped": ib_skipped,
        "ib_unavailable": ib_unavailable,
        "ib_error": ib_error,
        "details": {
            "queue": queue_details,
            "ib_orders_open_before": ib_open_before,
        },
    }



@router.get("/trades")
def get_trades_list():
    """
    Get a unified list of all trades (pending, open, closed).
    This is an alias endpoint for /trades/all for API consistency.
    """
    if not _trading_bot:
        return {
            "success": True,
            "pending": [],
            "open": [],
            "closed": [],
            "total": 0,
            "message": "Trading bot not initialized"
        }
    
    try:
        summary = _trading_bot.get_all_trades_summary()
        return {
            "success": True,
            "pending": summary.get("pending_trades", []),
            "open": summary.get("open_trades", []),
            "closed": summary.get("closed_trades", []),
            "total": summary.get("total_trades", 0),
            "daily_stats": summary.get("daily_stats", {})
        }
    except Exception as e:
        logger.error(f"Error getting trades: {e}")
        return {
            "success": False,
            "error": str(e),
            "pending": [],
            "open": [],
            "closed": []
        }



@router.post("/evaluate-trade")
async def ai_evaluate_trade(request: DemoTradeRequest):
    """Ask AI to evaluate a trade opportunity"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    if not hasattr(_trading_bot, '_ai_assistant') or not _trading_bot._ai_assistant:
        raise HTTPException(status_code=503, detail="AI assistant not connected to bot")
    
    trade_data = {
        "symbol": request.symbol.upper(),
        "direction": request.direction,
        "setup_type": request.setup_type,
        "timeframe": "intraday",
        "entry_price": 0,
        "stop_price": 0,
        "target_prices": [],
        "risk_amount": 0,
        "risk_reward_ratio": 0,
        "quality_score": 0,
        "quality_grade": "N/A"
    }
    
    result = await _trading_bot._ai_assistant.evaluate_bot_opportunity(trade_data)
    return result


@router.post("/trades/submit")
async def submit_trade(request: TradeSubmitRequest):
    """Submit a new trade for execution"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    try:
        symbol = request.symbol.upper()
        
        # Calculate position size based on risk params
        risk_params = _trading_bot.risk_params
        
        # Get current price if not provided
        entry_price = request.entry_price
        if not entry_price:
            # Try to get from Alpaca
            try:
                from services.alpaca_service import get_alpaca_service
                alpaca = get_alpaca_service()
                quote = alpaca.get_latest_quote(symbol)
                entry_price = float(quote.get('price', 0)) if quote else 0
            except Exception:
                entry_price = 0
        
        # Calculate shares based on risk
        stop_price = request.stop_price or (entry_price * 0.98 if request.direction == 'long' else entry_price * 1.02)
        risk_per_share = abs(entry_price - stop_price) if entry_price and stop_price else entry_price * 0.02
        
        if risk_per_share > 0:
            max_shares = int(risk_params.max_risk_per_trade / risk_per_share)
        else:
            max_shares = 100
        
        # Apply half size if requested
        if request.half_size:
            max_shares = max(1, max_shares // 2)
        
        # Create trade record
        trade_id = f"trade_{uuid.uuid4().hex[:8]}"
        trade = {
            "id": trade_id,
            "symbol": symbol,
            "direction": request.direction,
            "setup_type": request.setup_type,
            "status": "pending",
            "entry_price": entry_price,
            "stop_price": stop_price,
            "target_prices": request.target_prices or [entry_price * 1.03] if request.direction == 'long' else [entry_price * 0.97],
            "shares": max_shares,
            "risk_amount": risk_per_share * max_shares if risk_per_share else 0,
            "source": request.source,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "half_size": request.half_size
        }
        
        # Add to pending trades (it's a Dict keyed by trade_id)
        if not hasattr(_trading_bot, '_pending_trades') or _trading_bot._pending_trades is None:
            _trading_bot._pending_trades = {}
        
        # Create a BotTrade object if possible, otherwise use dict
        try:
            from services.trading_bot_service import BotTrade
            bot_trade = BotTrade(
                id=trade_id,
                symbol=symbol,
                direction=request.direction,
                setup_type=request.setup_type,
                entry_price=entry_price,
                stop_price=stop_price,
                target_prices=request.target_prices or ([entry_price * 1.03] if request.direction == 'long' else [entry_price * 0.97]),
                shares=max_shares,
                status="pending"
            )
            _trading_bot._pending_trades[trade_id] = bot_trade
        except Exception as e:
            logger.warning(f"Could not create BotTrade object: {e}")
            # Store as dict in a separate structure if needed
        
        # If in autonomous mode, execute immediately
        if _trading_bot._mode.value == "autonomous":
            # Execute the trade
            try:
                if _trade_executor:
                    result = await _trade_executor.execute_trade(trade)
                    trade["status"] = "open" if result.get("success") else "failed"
                    trade["execution_result"] = result
            except Exception as e:
                logger.error(f"Trade execution error: {e}")
                trade["status"] = "pending"
        
        logger.info(f"✅ Trade submitted: {symbol} {request.direction} - {max_shares} shares @ ${entry_price:.2f}")
        
        return {
            "success": True,
            "trade_id": trade_id,
            "trade": trade,
            "message": f"Trade submitted: {symbol} {request.direction.upper()} {max_shares} shares"
        }
        
    except Exception as e:
        logger.error(f"Failed to submit trade: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trades/{trade_id}")
def get_trade(trade_id: str):
    """Get details of a specific trade including explanation"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    trade = _trading_bot.get_trade(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    
    return {"success": True, "trade": trade}


@router.post("/trades/{trade_id}/confirm")
async def confirm_trade(trade_id: str):
    """Confirm a pending trade for execution.

    Returns 200 for any correctly-handled outcome (executed, simulated,
    vetoed by guardrail, paper-phase) with the trade's actual status in
    the response. Returns 404 only when the trade doesn't exist, 400 for
    genuine rejections (stale alert, broker error).
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")

    # Capture existence up-front so we can distinguish 404 vs 400 after the call
    existed_before = trade_id in _trading_bot._pending_trades or _trading_bot.get_trade(trade_id) is not None

    success = await _trading_bot.confirm_trade(trade_id)
    trade = _trading_bot.get_trade(trade_id)

    if success:
        # Trade was legitimately handled — surface the actual outcome so the
        # UI can show "Executed" / "Simulated" / "Paper" / "Vetoed" accurately.
        status = trade.get("status") if isinstance(trade, dict) else getattr(trade, "status", None)
        status_str = getattr(status, "value", status) if status is not None else "unknown"

        messages = {
            "open": "Trade executed — position open",
            "partial": "Trade partially filled",
            "simulated": "Trade skipped — strategy in SIMULATION phase",
            "paper": "Trade logged — strategy in PAPER phase (not sent to broker)",
            "vetoed": "Trade vetoed by pre-trade guardrail",
        }
        return {
            "success": True,
            "status": status_str,
            "message": messages.get(status_str, f"Trade handled: {status_str}"),
            "trade": trade,
        }

    # Not handled — distinguish "never existed" from "existed but rejected"
    if not existed_before:
        raise HTTPException(status_code=404, detail="Trade not found")

    # Trade existed but was rejected (stale alert, broker error, etc.)
    status = trade.get("status") if isinstance(trade, dict) else getattr(trade, "status", None)
    status_str = getattr(status, "value", status) if status is not None else "rejected"
    notes = trade.get("notes") if isinstance(trade, dict) else getattr(trade, "notes", "")
    raise HTTPException(
        status_code=400,
        detail={
            "error": "Trade rejected",
            "status": status_str,
            "reason": notes or "Rejected by execution pipeline",
        },
    )


@router.post("/trades/{trade_id}/reject")
async def reject_trade(trade_id: str, reason: Optional[str] = None):
    """Reject a pending trade"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    success = await _trading_bot.reject_trade(trade_id)
    
    if success:
        return {"success": True, "message": "Trade rejected"}
    else:
        raise HTTPException(status_code=404, detail="Trade not found")


@router.post("/trades/{trade_id}/close")
async def close_trade(trade_id: str, reason: Optional[str] = "manual"):
    """Close an open trade"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    success = await _trading_bot.close_trade(trade_id, reason=reason)
    
    if success:
        trade = _trading_bot.get_trade(trade_id)
        return {"success": True, "message": "Trade closed", "trade": trade}
    else:
        raise HTTPException(status_code=400, detail="Failed to close trade or trade not found")



@router.post("/close-by-symbol")
async def close_by_symbol(request: dict):
    """Close all open trades for a given symbol (used by chat server)."""
    if not _trading_bot:
        return {"success": False, "error": "Trading bot not initialized"}
    
    symbol = request.get("symbol", "").upper()
    reason = request.get("reason", "chat_requested")
    
    if not symbol:
        return {"success": False, "error": "No symbol provided"}
    
    # Find open trades for this symbol
    closed = []
    for trade_id, trade in list(_trading_bot._open_trades.items()):
        if trade.symbol.upper() == symbol:
            try:
                success = await _trading_bot.close_trade(trade_id, reason=reason)
                if success:
                    closed.append(trade_id)
            except Exception as e:
                logger.error(f"Error closing {symbol} trade {trade_id}: {e}")
    
    if closed:
        return {
            "success": True,
            "message": f"Closed {len(closed)} {symbol} position(s)",
            "trade_ids": closed
        }
    else:
        return {
            "success": False, 
            "error": f"No open bot trades found for {symbol}. It may be a manual position — close it in TWS directly."
        }


@router.post("/quick-order")
async def quick_order(request: dict):
    """Place a quick market order (used by chat server)."""
    if not _trading_bot:
        return {"success": False, "error": "Trading bot not initialized"}
    
    symbol = request.get("symbol", "").upper()
    action = request.get("action", "").lower()
    shares = request.get("shares", 0)
    reason = request.get("reason", "chat_requested")
    
    if not symbol or not action:
        return {"success": False, "error": "Symbol and action required"}
    
    # For now, log the intent — full execution through the standard pipeline
    # This prevents the chat from bypassing risk checks
    return {
        "success": True,
        "message": f"Order intent logged: {action} {shares} {symbol}. Use the scanner pipeline for execution with full risk checks."
    }


# ==================== STATISTICS ====================

@router.get("/stats/daily")
def get_daily_stats():
    """Get daily trading statistics"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    stats = _trading_bot.get_daily_stats()
    return {"success": True, "stats": stats}


@router.get("/stats/performance")
def get_performance_stats():
    """Get overall performance statistics"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    # Get all closed trades
    closed = _trading_bot.get_closed_trades(limit=500)
    
    total_pnl = sum(t.get('realized_pnl', 0) for t in closed)
    winners = [t for t in closed if t.get('realized_pnl', 0) > 0]
    losers = [t for t in closed if t.get('realized_pnl', 0) < 0]
    
    return {
        "success": True,
        "stats": {
            "total_trades": len(closed),
            "total_pnl": total_pnl,
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": (len(winners) / len(closed) * 100) if closed else 0,
            "avg_win": sum(t.get('realized_pnl', 0) for t in winners) / len(winners) if winners else 0,
            "avg_loss": sum(t.get('realized_pnl', 0) for t in losers) / len(losers) if losers else 0,
            "largest_win": max((t.get('realized_pnl', 0) for t in winners), default=0),
            "largest_loss": min((t.get('realized_pnl', 0) for t in losers), default=0),
            "profit_factor": abs(sum(t.get('realized_pnl', 0) for t in winners) / sum(t.get('realized_pnl', 0) for t in losers)) if losers else 0
        }
    }


@router.get("/performance/equity-curve")
def get_equity_curve(period: str = Query("today", enum=["today", "week", "month", "ytd", "all"])):
    """
    Get equity curve data for the bot performance chart.
    Returns cumulative P&L over time with trade markers.
    Includes both realized P&L (closed trades) and unrealized P&L (open positions).
    
    Period options:
    - today: Intraday (last 24 hours)
    - week: Last 7 days
    - month: Last 30 days
    - ytd: Year to date
    - all: All time
    """
    if not _trading_bot:
        return {
            "success": True,
            "equity_curve": [],
            "trade_markers": [],
            "summary": {
                "total_pnl": 0,
                "realized_pnl": 0,
                "unrealized_pnl": 0,
                "trades_count": 0,
                "win_rate": 0,
                "avg_r": 0,
                "best_trade": 0,
                "worst_trade": 0,
                "open_positions": 0
            }
        }
    
    try:
        from datetime import timedelta
        
        # Get closed trades
        closed = _trading_bot.get_closed_trades(limit=1000)
        
        # Get open positions for unrealized P&L
        open_trades = _trading_bot.get_all_trades_summary()
        open_positions = open_trades.get('open', [])
        
        # Calculate total unrealized P&L from open positions
        total_unrealized_pnl = sum(pos.get('unrealized_pnl', 0) for pos in open_positions)
        
        # Filter by period
        now = datetime.now(timezone.utc)
        if period == "today":
            cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            cutoff = now - timedelta(days=7)
        elif period == "month":
            cutoff = now - timedelta(days=30)
        elif period == "ytd":
            cutoff = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:  # all
            cutoff = datetime(2020, 1, 1, tzinfo=timezone.utc)
        
        # Filter and sort trades by close time
        filtered_trades = []
        for trade in closed:
            close_time_str = trade.get('closed_at') or trade.get('executed_at')
            if close_time_str:
                try:
                    close_time = datetime.fromisoformat(close_time_str.replace('Z', '+00:00'))
                    if close_time >= cutoff:
                        filtered_trades.append({
                            **trade,
                            '_close_time': close_time
                        })
                except (ValueError, TypeError):
                    pass
        
        # Sort by close time
        filtered_trades.sort(key=lambda t: t['_close_time'])
        
        # Build equity curve from closed trades
        cumulative_pnl = 0
        equity_curve = []
        trade_markers = []
        pnls = []
        
        for trade in filtered_trades:
            pnl = trade.get('realized_pnl', 0)
            cumulative_pnl += pnl
            pnls.append(pnl)
            
            timestamp = int(trade['_close_time'].timestamp() * 1000)  # JS timestamp
            equity_curve.append({
                "time": timestamp,
                "value": cumulative_pnl
            })
            
            trade_markers.append({
                "time": timestamp,
                "pnl": pnl,
                "symbol": trade.get('symbol', ''),
                "setup_type": trade.get('setup_type', ''),
                "is_win": pnl > 0
            })
        
        # Add current point with unrealized P&L if we have open positions
        if open_positions:
            current_timestamp = int(now.timestamp() * 1000)
            current_total = cumulative_pnl + total_unrealized_pnl
            
            equity_curve.append({
                "time": current_timestamp,
                "value": current_total,
                "is_live": True,
                "unrealized": total_unrealized_pnl
            })
            
            # Add markers for open positions (different style)
            for pos in open_positions:
                entry_time_str = pos.get('entry_time')
                if entry_time_str:
                    try:
                        entry_time = datetime.fromisoformat(entry_time_str.replace('Z', '+00:00'))
                        if entry_time >= cutoff:
                            trade_markers.append({
                                "time": int(entry_time.timestamp() * 1000),
                                "pnl": pos.get('unrealized_pnl', 0),
                                "symbol": pos.get('symbol', ''),
                                "setup_type": pos.get('setup_type', ''),
                                "is_open": True,
                                "is_win": pos.get('unrealized_pnl', 0) > 0
                            })
                    except (ValueError, TypeError):
                        pass
        
        # Calculate summary stats
        wins = [p for p in pnls if p > 0]
        
        # Calculate average R-multiple from trades that have it
        r_multiples = [t.get('r_multiple', 0) for t in filtered_trades if t.get('r_multiple')]
        avg_r = sum(r_multiples) / len(r_multiples) if r_multiples else 0
        
        summary = {
            "total_pnl": cumulative_pnl + total_unrealized_pnl,
            "realized_pnl": cumulative_pnl,
            "unrealized_pnl": total_unrealized_pnl,
            "trades_count": len(filtered_trades),
            "win_rate": (len(wins) / len(filtered_trades) * 100) if filtered_trades else 0,
            "avg_r": avg_r,
            "best_trade": max(pnls, default=0),
            "worst_trade": min(pnls, default=0),
            "open_positions": len(open_positions)
        }
        
        return {
            "success": True,
            "period": period,
            "equity_curve": equity_curve,
            "trade_markers": trade_markers,
            "summary": summary
        }
        
    except Exception as e:
        logger.error(f"Error getting equity curve: {e}")
        return {
            "success": False,
            "error": str(e),
            "equity_curve": [],
            "trade_markers": [],
            "summary": {}
        }


@router.get("/thoughts")
async def get_bot_thoughts(limit: int = Query(10, ge=1, le=50)):
    """
    Get the bot's recent thoughts/reasoning in first person.
    Returns a stream of what the bot is "thinking" based on:
    - Recent trade decisions and reasoning
    - Setups being watched
    - Position monitoring updates
    - STOP AUDIT WARNINGS for risky stop placements
    
    Each thought has:
    - text: The thought in first person (e.g., "I detected a breakout on NVDA...")
    - timestamp: When the thought occurred
    - confidence: 0-100 confidence level
    - action_type: entry, exit, watching, monitoring, scanning, alert, stop_warning
    - symbol: Related ticker symbol (if any)
    """
    thoughts = []
    
    if not _trading_bot:
        return {
            "success": True,
            "thoughts": [{
                "text": "I'm currently offline. Start me to begin scanning for opportunities.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "confidence": 0,
                "action_type": "offline",
                "symbol": None
            }]
        }
    
    try:
        now = datetime.now(timezone.utc)
        
        # 0. STOP AUDIT WARNINGS (highest priority - show first)
        stop_audit = await audit_position_stops()
        if stop_audit.get("success") and stop_audit.get("warnings"):
            for warning in stop_audit["warnings"][:3]:  # Max 3 stop warnings
                severity = warning.get("severity", "info")
                symbol = warning.get("symbol", "UNKNOWN")
                message = warning.get("message", "")
                
                # Color-code by severity
                if severity == "critical":
                    emoji = "🚨"
                    confidence = 95
                elif severity == "warning":
                    emoji = "⚠️"
                    confidence = 80
                else:
                    emoji = "💡"
                    confidence = 60
                
                thoughts.append({
                    "text": f'{emoji} "{message}"',
                    "timestamp": now.isoformat(),
                    "confidence": confidence,
                    "action_type": "stop_warning",
                    "symbol": symbol,
                    "severity": severity
                })
        
        # 0.5. SMART STRATEGY FILTER THOUGHTS (High priority - trade filtering reasoning)
        filter_thoughts = _trading_bot.get_filter_thoughts(limit=5)
        for ft in filter_thoughts:
            action = ft.get("action", "PROCEED")
            text = ft.get("text", "")
            symbol = ft.get("symbol", None)
            win_rate = ft.get("win_rate", 0)
            
            # Color-code by action type
            if action == "SKIP":
                confidence = 85
                action_type = "filter_skip"
            elif action == "REDUCE_SIZE":
                confidence = 70
                action_type = "filter_reduce"
            else:
                confidence = 60
                action_type = "filter_proceed"
            
            thoughts.append({
                "text": f'"{text}"',
                "timestamp": ft.get("timestamp", now.isoformat()),
                "confidence": confidence,
                "action_type": action_type,
                "symbol": symbol,
                "win_rate": win_rate,
                "filter_action": action
            })
        
        # 1. Thoughts from pending trades (about to execute)
        for trade in _trading_bot.get_pending_trades()[:3]:
            symbol = trade.get('symbol', 'UNKNOWN')
            setup = trade.get('setup_type', 'trade')
            entry = trade.get('entry_price', 0)
            rr = trade.get('risk_reward_ratio', 0)
            
            thoughts.append({
                "text": f'"We\'re preparing to enter {symbol} on a {setup.replace("_", " ")} setup at ${entry:.2f}. Risk/Reward is {rr:.1f}:1. Awaiting confirmation."',
                "timestamp": trade.get('created_at', now.isoformat()),
                "confidence": 80,
                "action_type": "entry",
                "symbol": symbol
            })
        
        # 2. Thoughts from open trades (monitoring)
        for trade in _trading_bot.get_open_trades()[:3]:
            symbol = trade.get('symbol', 'UNKNOWN')
            pnl = trade.get('unrealized_pnl', 0)
            pnl_pct = trade.get('pnl_pct', 0)
            stop = trade.get('stop_price', 0)
            target = trade.get('target_prices', [0])[0] if trade.get('target_prices') else 0
            direction = 'up' if pnl >= 0 else 'down'
            
            thoughts.append({
                "text": f'"We\'re monitoring our {symbol} position. Currently {direction} {abs(pnl_pct):.1f}%. Our stop at ${stop:.2f} is safe. {f"Target 1 at ${target:.2f}." if target else ""}"',
                "timestamp": trade.get('executed_at', now.isoformat()),
                "confidence": 60,
                "action_type": "monitoring",
                "symbol": symbol
            })
        
        # 3. Thoughts from recent closed trades (lessons learned)
        recent_closed = _trading_bot.get_closed_trades(limit=2)
        for trade in recent_closed:
            symbol = trade.get('symbol', 'UNKNOWN')
            pnl = trade.get('realized_pnl', 0)
            reason = trade.get('close_reason', 'manual')
            
            if pnl > 0:
                text = f'"We closed {symbol} for +${pnl:.2f}. {reason.replace("_", " ").title()} worked well for us."'
            else:
                text = f'"We closed {symbol} for -${abs(pnl):.2f}. {reason.replace("_", " ").title()}. We\'re learning from this."'
            
            thoughts.append({
                "text": text,
                "timestamp": trade.get('closed_at', now.isoformat()),
                "confidence": 50,
                "action_type": "exit",
                "symbol": symbol
            })
        
        # 4. General status thought if bot is running
        if _trading_bot._running:
            mode = _trading_bot._mode.value
            regime = getattr(_trading_bot, '_current_regime', 'UNKNOWN')
            
            if regime == 'RISK_ON':
                regime_comment = "so we're looking for aggressive breakout setups."
            elif regime == 'RISK_OFF':
                regime_comment = "so we're being cautious and reducing position sizes."
            elif regime == 'CONFIRMED_DOWN':
                regime_comment = "so we're favoring short setups and reducing long exposure."
            else:
                regime_comment = "so we're using standard position sizing."
            
            thoughts.append({
                "text": f'"We\'re actively scanning for opportunities in {mode} mode. Market regime is {regime}, {regime_comment}"',
                "timestamp": now.isoformat(),
                "confidence": 50,
                "action_type": "scanning",
                "symbol": None
            })
        
        # Sort by timestamp (most recent first) and limit
        # Handle None timestamps by using epoch as fallback
        thoughts.sort(key=lambda t: t['timestamp'] or '1970-01-01T00:00:00', reverse=True)
        
        return {
            "success": True,
            "thoughts": thoughts[:limit]
        }
        
    except Exception as e:
        logger.error(f"Error getting bot thoughts: {e}")
        return {
            "success": False,
            "error": str(e),
            "thoughts": []
        }


@router.get("/dashboard-data")
async def get_dashboard_data():
    """
    Get all data needed for the new bot-centric dashboard in one call.
    Reduces API calls from the frontend.
    
    Returns:
    - bot_status: Running state, mode, last action
    - today_pnl: Today's realized P&L
    - open_pnl: Unrealized P&L from open positions
    - open_trades: List of open positions
    - watching_setups: Setups the bot is watching
    - recent_thoughts: Bot's recent reasoning (3 most recent)
    - performance_summary: Win rate, avg R, etc.
    """
    if not _trading_bot:
        return {
            "success": True,
            "bot_status": {"running": False, "mode": "paused", "state": "offline"},
            "today_pnl": 0,
            "open_pnl": 0,
            "open_trades": [],
            "watching_setups": [],
            "recent_thoughts": [],
            "performance_summary": {}
        }
    
    try:
        # Bot status
        status = _trading_bot.get_status()
        daily_stats = status.get('daily_stats', {})
        
        # Calculate open P&L
        open_trades = _trading_bot.get_open_trades()
        open_pnl = sum(t.get('unrealized_pnl', 0) for t in open_trades)
        
        # Get pending trades (watching/about to enter)
        pending = _trading_bot.get_pending_trades()
        
        # Build bot status object
        bot_status = {
            "running": status.get('running', False),
            "mode": status.get('mode', 'paused'),
            "state": "hunting" if status.get('running') else "paused",
            "last_action": None  # Could be enhanced later
        }
        
        # Get thoughts (simplified - just 3 most recent)
        thoughts_response = await get_bot_thoughts(limit=3)
        recent_thoughts = thoughts_response.get('thoughts', [])
        
        # Performance summary
        closed = _trading_bot.get_closed_trades(limit=100)
        today_trades = [t for t in closed if _is_today(t.get('closed_at'))]
        
        wins = [t for t in today_trades if t.get('realized_pnl', 0) > 0]
        performance_summary = {
            "trades_today": len(today_trades),
            "win_rate": (len(wins) / len(today_trades) * 100) if today_trades else 0,
            "best_trade": max((t.get('realized_pnl', 0) for t in today_trades), default=0),
            "worst_trade": min((t.get('realized_pnl', 0) for t in today_trades), default=0)
        }
        
        return {
            "success": True,
            "bot_status": bot_status,
            "today_pnl": daily_stats.get('net_pnl', 0),
            "open_pnl": open_pnl,
            "open_trades": open_trades,
            "watching_setups": pending,
            "recent_thoughts": recent_thoughts,
            "performance_summary": performance_summary
        }
        
    except Exception as e:
        logger.error(f"Error getting dashboard data: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def _is_today(timestamp_str: str) -> bool:
    """Helper to check if a timestamp is from today"""
    if not timestamp_str:
        return False
    try:
        ts = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        today = datetime.now(timezone.utc).date()
        return ts.date() == today
    except (ValueError, TypeError):
        return False


# ==================== REAL-TIME STREAMING ====================

@router.get("/stream")
async def stream_bot_updates():
    """
    Server-Sent Events stream for real-time bot updates.
    Streams: new trades, trade executions, P&L updates, status changes
    """
    async def event_generator():
        queue = asyncio.Queue()
        
        async def trade_callback(trade, event_type):
            await queue.put({"type": event_type, "trade": trade.to_dict()})
        
        if _trading_bot:
            _trading_bot.add_trade_callback(trade_callback)
        
        # Send initial connection message
        yield f"data: {json.dumps({'type': 'connected', 'timestamp': str(datetime.now())})}\n\n"
        
        try:
            while True:
                try:
                    # Wait for updates with timeout for heartbeat
                    update = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {json.dumps(update)}\n\n"
                except asyncio.TimeoutError:
                    # Send heartbeat
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        except asyncio.CancelledError:
            pass
    
    from datetime import datetime
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ==================== ACCOUNT INFO ====================

@router.get("/audit-stops")
async def audit_position_stops():
    """
    Audit all open positions for risky stop placements.
    
    Analyzes each open position using the Smart Stop System to detect:
    - Stops that are too tight (will get stopped out easily)
    - Stops near round numbers ($50, $100, etc.) - easy hunting targets
    - Stops below obvious support levels - institutional hunting zones
    - Stops that don't account for current volatility/regime
    
    Returns warnings with severity levels and suggested improvements.
    This is automatically included in the bot's "thoughts" stream.
    """
    if not _trading_bot:
        return {
            "success": True,
            "warnings": [],
            "positions_audited": 0,
            "healthy_positions": 0,
            "message": "Trading bot not initialized"
        }
    
    try:
        from services.smart_stop_service import get_smart_stop_service
        smart_stop = get_smart_stop_service()
        
        open_trades = _trading_bot.get_open_trades()
        warnings = []
        healthy_count = 0
        
        for trade in open_trades:
            symbol = trade.get('symbol', '')
            entry_price = trade.get('fill_price') or trade.get('entry_price', 0)
            current_price = trade.get('current_price', entry_price)
            stop_price = trade.get('stop_price', 0)
            direction = trade.get('direction', 'long')
            setup_type = trade.get('setup_type', 'default')
            
            if not entry_price or not stop_price:
                continue
            
            # Estimate ATR as 2% of price if not available
            atr = entry_price * 0.02
            
            # Analyze using intelligent stop service
            try:
                analysis = await smart_stop.calculate_intelligent_stop(
                    symbol=symbol,
                    entry_price=entry_price,
                    current_price=current_price,
                    direction=direction,
                    setup_type=setup_type,
                    position_size=trade.get('shares', 100),
                    atr=atr
                )
                
                optimal_stop = analysis.stop_price
                hunt_risk = analysis.hunt_risk
                urgency = analysis.urgency.value
                
                # Check for problems
                problems = []
                
                # 1. Check if stop is too tight
                stop_distance = abs(stop_price - entry_price)
                min_distance = atr * 0.75  # Minimum 0.75 ATR
                if stop_distance < min_distance:
                    problems.append({
                        "type": "too_tight",
                        "severity": "critical",
                        "message": f"Stop for {symbol} is too tight (${stop_distance:.2f} vs min ${min_distance:.2f}). High probability of getting stopped out on normal volatility."
                    })
                
                # 2. Check if stop is near round number
                round_numbers = [n for n in [50, 100, 150, 200, 250, 300, 400, 500] if abs(stop_price - n) < n * 0.01]
                if round_numbers:
                    problems.append({
                        "type": "round_number",
                        "severity": "warning",
                        "message": f"{symbol} stop at ${stop_price:.2f} is near ${round_numbers[0]} - a common stop hunting target. Consider moving it."
                    })
                
                # 3. Check hunt risk
                if hunt_risk == "HIGH":
                    problems.append({
                        "type": "hunt_risk",
                        "severity": "warning",
                        "message": f"{symbol} has HIGH stop hunt risk. Your stop at ${stop_price:.2f} may be vulnerable. Optimal: ${optimal_stop:.2f}"
                    })
                
                # 4. Check urgency
                if urgency in ["high_alert", "emergency"]:
                    problems.append({
                        "type": "urgency",
                        "severity": "critical",
                        "message": f"{symbol} position needs attention! Urgency: {urgency.upper()}. Consider tightening or exiting."
                    })
                
                # 5. Check if stop is much worse than optimal
                if direction == 'long' and stop_price > optimal_stop + atr * 0.5:
                    problems.append({
                        "type": "suboptimal",
                        "severity": "info",
                        "message": f"{symbol} stop could be tighter. Current: ${stop_price:.2f}, Suggested: ${optimal_stop:.2f} (+{((optimal_stop - stop_price)/entry_price*100):.1f}% better risk)"
                    })
                elif direction == 'short' and stop_price < optimal_stop - atr * 0.5:
                    problems.append({
                        "type": "suboptimal",
                        "severity": "info",
                        "message": f"{symbol} stop could be tighter. Current: ${stop_price:.2f}, Suggested: ${optimal_stop:.2f}"
                    })
                
                if problems:
                    for problem in problems:
                        warnings.append({
                            "symbol": symbol,
                            "current_stop": stop_price,
                            "optimal_stop": optimal_stop,
                            "entry_price": entry_price,
                            "current_price": current_price,
                            "hunt_risk": hunt_risk,
                            **problem
                        })
                else:
                    healthy_count += 1
                    
            except Exception as e:
                logger.debug(f"Could not analyze stop for {symbol}: {e}")
                healthy_count += 1  # Assume healthy if we can't analyze
        
        # Sort warnings by severity (critical first, then warning, then info)
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        warnings.sort(key=lambda w: severity_order.get(w.get("severity", "info"), 2))
        
        return {
            "success": True,
            "warnings": warnings,
            "positions_audited": len(open_trades),
            "healthy_positions": healthy_count,
            "positions_with_issues": len(open_trades) - healthy_count,
            "summary": {
                "critical": len([w for w in warnings if w.get("severity") == "critical"]),
                "warning": len([w for w in warnings if w.get("severity") == "warning"]),
                "info": len([w for w in warnings if w.get("severity") == "info"])
            }
        }
        
    except Exception as e:
        logger.error(f"Error auditing position stops: {e}")
        return {
            "success": False,
            "error": str(e),
            "warnings": []
        }


@router.post("/fix-stop/{trade_id}")
async def fix_stop_to_recommended(trade_id: str):
    """
    One-Click Stop Fix: Automatically adjust a risky stop to the recommended level.
    
    Uses the Smart Stop System to calculate the optimal stop price and updates
    the trade's stop price. This is the quick fix for stop audit warnings.
    
    Args:
        trade_id: The ID of the trade to fix
    
    Returns:
        Updated trade with new stop price and explanation of the fix
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    try:
        from services.smart_stop_service import get_smart_stop_service
        smart_stop = get_smart_stop_service()
        
        # Find the trade
        trade = None
        for t_id, t in _trading_bot._open_trades.items():
            if t.id == trade_id or t_id == trade_id:
                trade = t
                break
        
        if not trade:
            raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
        
        symbol = trade.symbol
        entry_price = trade.fill_price or trade.entry_price
        current_price = trade.current_price
        stop_price = trade.stop_price
        direction = trade.direction.value if hasattr(trade.direction, 'value') else trade.direction
        setup_type = trade.setup_type
        
        # Estimate ATR as 2% of price if not available
        atr = entry_price * 0.02
        
        # Calculate intelligent stop
        analysis = await smart_stop.calculate_intelligent_stop(
            symbol=symbol,
            entry_price=entry_price,
            current_price=current_price,
            direction=direction,
            setup_type=setup_type,
            position_size=trade.shares,
            atr=atr
        )
        
        new_stop = analysis.stop_price
        old_stop = stop_price
        
        # Update the trade's stop price
        trade.stop_price = new_stop
        
        # Update trailing stop config as well
        if hasattr(trade, 'trailing_stop_config') and trade.trailing_stop_config:
            trade.trailing_stop_config['current_stop'] = new_stop
            trade.trailing_stop_config['stop_adjustments'] = trade.trailing_stop_config.get('stop_adjustments', [])
            trade.trailing_stop_config['stop_adjustments'].append({
                'from': old_stop,
                'to': new_stop,
                'reason': 'one_click_fix',
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
        
        # Persist the updated trade
        _trading_bot._persist_trade(trade)
        
        # Calculate improvement
        if direction == 'long':
            improvement_pct = ((new_stop - old_stop) / entry_price * 100)
            improvement_desc = f"Tightened stop by {abs(improvement_pct):.1f}%" if new_stop > old_stop else f"Loosened stop by {abs(improvement_pct):.1f}%"
        else:
            improvement_pct = ((old_stop - new_stop) / entry_price * 100)
            improvement_desc = f"Tightened stop by {abs(improvement_pct):.1f}%" if new_stop < old_stop else f"Loosened stop by {abs(improvement_pct):.1f}%"
        
        logger.info(f"🔧 One-Click Stop Fix: {symbol} stop adjusted from ${old_stop:.2f} to ${new_stop:.2f} ({improvement_desc})")
        
        return {
            "success": True,
            "trade_id": trade.id,
            "symbol": symbol,
            "old_stop": old_stop,
            "new_stop": new_stop,
            "improvement": improvement_desc,
            "analysis": {
                "hunt_risk": analysis.hunt_risk,
                "urgency": analysis.urgency.value,
                "factors_considered": analysis.factors_considered[:3] if analysis.factors_considered else []
            },
            "message": f"Stop for {symbol} fixed: ${old_stop:.2f} → ${new_stop:.2f}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fixing stop for trade {trade_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fix stop: {str(e)}")


@router.post("/fix-all-risky-stops")
async def fix_all_risky_stops():
    """
    Fix ALL risky stops in one click.
    
    Runs the stop audit, identifies all positions with critical or warning issues,
    and automatically adjusts their stops to optimal levels.
    
    Returns a summary of all fixes applied.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    try:
        # First run the audit to identify issues
        audit_result = await audit_position_stops()
        
        if not audit_result.get("success") or not audit_result.get("warnings"):
            return {
                "success": True,
                "message": "No risky stops to fix",
                "fixes_applied": 0,
                "positions_checked": audit_result.get("positions_audited", 0)
            }
        
        # Filter to critical and warning level issues only
        risky_warnings = [
            w for w in audit_result["warnings"]
            if w.get("severity") in ["critical", "warning"]
        ]
        
        if not risky_warnings:
            return {
                "success": True,
                "message": "No critical or warning-level stop issues to fix",
                "fixes_applied": 0,
                "positions_checked": audit_result.get("positions_audited", 0)
            }
        
        # Group warnings by symbol (one fix per symbol)
        symbols_to_fix = {}
        for warning in risky_warnings:
            symbol = warning.get("symbol")
            if symbol and symbol not in symbols_to_fix:
                symbols_to_fix[symbol] = warning
        
        # Apply fixes
        fixes = []
        errors = []
        
        for symbol, warning in symbols_to_fix.items():
            # Find the trade for this symbol
            trade = None
            for t in _trading_bot._open_trades.values():
                if t.symbol == symbol:
                    trade = t
                    break
            
            if not trade:
                errors.append({"symbol": symbol, "error": "Trade not found"})
                continue
            
            try:
                # Fix this trade's stop
                fix_result = await fix_stop_to_recommended(trade.id)
                if fix_result.get("success"):
                    fixes.append({
                        "symbol": symbol,
                        "old_stop": fix_result["old_stop"],
                        "new_stop": fix_result["new_stop"],
                        "improvement": fix_result["improvement"]
                    })
            except Exception as e:
                errors.append({"symbol": symbol, "error": str(e)})
        
        logger.info(f"🔧 Bulk Stop Fix: Applied {len(fixes)} fixes, {len(errors)} errors")
        
        return {
            "success": True,
            "message": f"Fixed {len(fixes)} risky stops",
            "fixes_applied": len(fixes),
            "fixes": fixes,
            "errors": errors if errors else None,
            "positions_checked": audit_result.get("positions_audited", 0)
        }
        
    except Exception as e:
        logger.error(f"Error fixing all risky stops: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fix stops: {str(e)}")


@router.get("/account")
async def get_account_info():
    """Get broker account information"""
    if not _trade_executor:
        raise HTTPException(status_code=503, detail="Trade executor not initialized")
    
    account = await _trade_executor.get_account_info()
    positions = await _trade_executor.get_positions()
    
    return {
        "success": True,
        "account": account,
        "positions": positions
    }


@router.get("/positions")
async def get_broker_positions():
    """Get current positions from broker"""
    if not _trade_executor:
        raise HTTPException(status_code=503, detail="Trade executor not initialized")
    
    positions = await _trade_executor.get_positions()
    return {"success": True, "positions": positions}


# ==================== MANUAL CONTROLS ====================

@router.post("/scan-now")
async def trigger_manual_scan():
    """Manually trigger a scan for trade opportunities"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    await _trading_bot._scan_for_opportunities()
    
    return {
        "success": True,
        "message": "Scan completed",
        "pending_trades": len(_trading_bot.get_pending_trades()),
        "open_trades": len(_trading_bot.get_open_trades())
    }


@router.get("/strategy-configs")
def get_strategy_configs():
    """Get all strategy configurations"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    configs = _trading_bot.get_strategy_configs()
    return {"success": True, "configs": configs}


@router.put("/strategy-configs/{strategy}")
def update_strategy_config(strategy: str, config: StrategyConfigUpdate):
    """Update a specific strategy configuration"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    updates = config.dict(exclude_none=True)
    success = _trading_bot.update_strategy_config(strategy, updates)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Strategy '{strategy}' not found")
    
    return {"success": True, "message": f"Strategy '{strategy}' updated", "configs": _trading_bot.get_strategy_configs()}


@router.post("/demo-trade")
async def create_demo_trade(request: DemoTradeRequest):
    """
    Create a demo trade for testing purposes.
    This simulates finding a trade opportunity without requiring live market data.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    from services.trading_bot_service import BotTrade, TradeStatus, TradeDirection, TradeExplanation, STRATEGY_CONFIG, DEFAULT_STRATEGY_CONFIG
    import uuid
    from datetime import datetime, timezone
    
    symbol = request.symbol.upper()
    direction = TradeDirection.LONG if request.direction.lower() == "long" else TradeDirection.SHORT
    
    # Get strategy config
    strategy_cfg = STRATEGY_CONFIG.get(request.setup_type, DEFAULT_STRATEGY_CONFIG)
    from services.trading_bot_service import TradeTimeframe
    timeframe_val = strategy_cfg["timeframe"]
    timeframe_str = timeframe_val.value if isinstance(timeframe_val, TradeTimeframe) else timeframe_val
    trail_pct = strategy_cfg.get("trail_pct", 0.02)
    scale_pcts = strategy_cfg.get("scale_out_pcts", [0.33, 0.33, 0.34])
    close_at_eod = strategy_cfg.get("close_at_eod", True)
    
    # Get current price from Alpaca
    current_price = 100.0  # Default
    try:
        from services.alpaca_service import get_alpaca_service
        alpaca = get_alpaca_service()
        quote = await alpaca.get_quote(symbol)
        if quote and quote.get('price'):
            current_price = quote['price']
    except Exception as e:
        logger.warning(f"Could not get quote for {symbol}: {e}")
    
    # Calculate trade parameters - round to 2 decimals
    entry_price = round(current_price, 2)
    atr_estimate = round(current_price * 0.02, 2)  # Estimate 2% ATR
    
    if direction == TradeDirection.LONG:
        stop_price = round(entry_price - atr_estimate, 2)
        target_prices = [
            round(entry_price + atr_estimate * 1.5, 2),
            round(entry_price + atr_estimate * 2.5, 2),
            round(entry_price + atr_estimate * 4, 2)
        ]
    else:
        stop_price = round(entry_price + atr_estimate, 2)
        target_prices = [
            round(entry_price - atr_estimate * 1.5, 2),
            round(entry_price - atr_estimate * 2.5, 2),
            round(entry_price - atr_estimate * 4, 2)
        ]
    
    # Calculate position size
    risk_per_share = abs(entry_price - stop_price)
    max_shares = int(_trading_bot.risk_params.max_risk_per_trade / risk_per_share)
    shares = min(max_shares, int(_trading_bot.risk_params.starting_capital * 0.1 / entry_price))
    shares = max(shares, 1)
    
    risk_amount = shares * risk_per_share
    potential_reward = shares * abs(target_prices[0] - entry_price)
    risk_reward_ratio = potential_reward / risk_amount if risk_amount > 0 else 0
    
    # Generate explanation
    explanation = TradeExplanation(
        summary=f"Demo {request.setup_type.replace('_', ' ').title()} setup on {symbol}. "
                f"{'Buying' if direction == TradeDirection.LONG else 'Shorting'} {shares} shares at ${entry_price:.2f}.",
        setup_identified=f"Demo {request.setup_type} pattern for testing",
        technical_reasons=[
            f"Setup type: {request.setup_type}",
            f"Current price: ${current_price:.2f}",
            "Demo trade for testing - not based on live analysis"
        ],
        fundamental_reasons=[],
        risk_analysis={
            "risk_per_share": f"${risk_per_share:.2f}",
            "total_risk": f"${risk_amount:.2f}",
            "max_risk_allowed": f"${_trading_bot.risk_params.max_risk_per_trade:.2f}",
            "risk_pct_of_capital": f"{(risk_amount / _trading_bot.risk_params.starting_capital * 100):.3f}%"
        },
        entry_logic=f"Demo entry at ${entry_price:.2f}",
        exit_logic=f"Stop at ${stop_price:.2f}, Target at ${target_prices[0]:.2f}",
        position_sizing_logic=f"Position: {shares} shares based on ${_trading_bot.risk_params.max_risk_per_trade:.0f} max risk",
        confidence_factors=["Demo trade for testing"],
        warnings=["This is a DEMO trade for testing purposes only"]
    )
    
    # Create trade
    trade = BotTrade(
        id=str(uuid.uuid4())[:8],
        symbol=symbol,
        direction=direction,
        status=TradeStatus.PENDING,
        setup_type=request.setup_type,
        timeframe=timeframe_str,
        quality_score=75,
        quality_grade="B+",
        entry_price=entry_price,
        current_price=current_price,
        stop_price=stop_price,
        target_prices=target_prices,
        shares=shares,
        risk_amount=risk_amount,
        potential_reward=potential_reward,
        risk_reward_ratio=risk_reward_ratio,
        created_at=datetime.now(timezone.utc).isoformat(),
        estimated_duration=f"{timeframe_str.title()} - 30min-2hr",
        explanation=explanation,
        close_at_eod=close_at_eod,
        scale_out_config={
            "enabled": True,
            "targets_hit": [],
            "scale_out_pcts": scale_pcts,
            "partial_exits": []
        },
        trailing_stop_config={
            "enabled": True,
            "mode": "original",
            "original_stop": stop_price,
            "current_stop": stop_price,
            "trail_pct": trail_pct,
            "trail_atr_mult": 1.5,
            "high_water_mark": 0.0,
            "low_water_mark": 0.0,
            "stop_adjustments": []
        }
    )
    
    # Add to pending trades
    _trading_bot._pending_trades[trade.id] = trade
    
    return {
        "success": True,
        "message": f"Demo trade created for {symbol}",
        "trade": trade.to_dict()
    }


class SimulateClosedRequest(BaseModel):
    symbol: str = "AAPL"
    setup_type: str = "rubber_band"
    direction: str = "long"
    pnl: float = 150.0  # Positive = win, negative = loss
    close_reason: str = "target_hit"


@router.post("/demo/simulate-closed")
async def simulate_closed_trade(request: SimulateClosedRequest):
    """Simulate a fully closed trade for testing the learning loop"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    import random
    from services.trading_bot_service import BotTrade, TradeStatus, TradeDirection, TradeExplanation, STRATEGY_CONFIG, DEFAULT_STRATEGY_CONFIG, TradeTimeframe
    symbol = request.symbol.upper()
    direction = TradeDirection.LONG if request.direction.lower() == "long" else TradeDirection.SHORT
    strategy_cfg = STRATEGY_CONFIG.get(request.setup_type, DEFAULT_STRATEGY_CONFIG)
    timeframe_val = strategy_cfg["timeframe"]
    timeframe_str = timeframe_val.value if isinstance(timeframe_val, TradeTimeframe) else timeframe_val
    trail_pct = strategy_cfg.get("trail_pct", 0.02)
    
    entry_price = round(random.uniform(100, 500), 2)
    pnl = request.pnl
    shares = random.randint(50, 300)
    pnl_per_share = pnl / shares
    exit_price = round(entry_price + pnl_per_share, 2) if direction == TradeDirection.LONG else round(entry_price - pnl_per_share, 2)
    stop_price = round(entry_price - entry_price * 0.02, 2)
    
    trade = BotTrade(
        id=str(uuid.uuid4())[:8],
        symbol=symbol,
        direction=direction,
        status=TradeStatus.CLOSED,
        setup_type=request.setup_type,
        timeframe=timeframe_str,
        quality_score=random.randint(60, 90),
        quality_grade=random.choice(["A", "A-", "B+", "B", "B-"]),
        entry_price=entry_price,
        current_price=exit_price,
        stop_price=stop_price,
        target_prices=[round(entry_price * 1.03, 2), round(entry_price * 1.05, 2)],
        shares=shares,
        risk_amount=round(abs(entry_price - stop_price) * shares, 2),
        potential_reward=round(abs(pnl) * 1.5, 2),
        risk_reward_ratio=1.5,
        fill_price=entry_price,
        exit_price=exit_price,
        realized_pnl=round(pnl, 2),
        pnl_pct=round((pnl / (entry_price * shares)) * 100, 2),
        created_at=datetime.now(timezone.utc).isoformat(),
        executed_at=datetime.now(timezone.utc).isoformat(),
        closed_at=datetime.now(timezone.utc).isoformat(),
        close_reason=request.close_reason,
        close_at_eod=strategy_cfg.get("close_at_eod", True),
        estimated_duration=f"{timeframe_str} demo",
        trailing_stop_config={
            "trail_pct": trail_pct
        }
    )
    
    # Add to closed trades list
    _trading_bot._closed_trades.append(trade)
    
    # Update daily stats
    _trading_bot._daily_stats.trades_executed += 1
    _trading_bot._daily_stats.net_pnl += pnl
    _trading_bot._daily_stats.gross_pnl += pnl
    if pnl > 0:
        _trading_bot._daily_stats.trades_won += 1
    else:
        _trading_bot._daily_stats.trades_lost += 1
    total = _trading_bot._daily_stats.trades_won + _trading_bot._daily_stats.trades_lost
    _trading_bot._daily_stats.win_rate = (_trading_bot._daily_stats.trades_won / total * 100) if total > 0 else 0
    
    # Record performance for learning loop
    if hasattr(_trading_bot, '_perf_service') and _trading_bot._perf_service:
        _trading_bot._perf_service.record_trade(trade.to_dict())
    
    # Save to DB
    await _trading_bot._save_trade(trade)
    
    return {
        "success": True,
        "message": f"Simulated closed trade: {symbol} P&L=${pnl:.2f}",
        "trade": trade.to_dict()
    }



# ==================== POSITION IMPORT ====================

class ImportPositionRequest(BaseModel):
    """Request to import an existing IB position into bot management"""
    symbol: str
    shares: int
    entry_price: float
    stop_price: float
    direction: str = "long"  # "long" or "short"
    setup_type: str = "imported"
    target_prices: Optional[List[float]] = None
    notes: Optional[str] = None


@router.post("/import-position")
async def import_position(request: ImportPositionRequest):
    """
    Import an existing IB position into bot management.
    
    This allows the bot to manage stops for positions that were:
    - Opened manually in IB
    - Opened before the bot was restarted
    - Opened when the bot had connectivity issues
    
    The bot will then monitor the position and execute stop/target orders.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    try:
        from services.trading_bot_service import BotTrade, TradeDirection, TradeStatus
        
        # Validate direction
        direction = TradeDirection.LONG if request.direction.lower() == "long" else TradeDirection.SHORT
        
        # Calculate additional required fields
        risk_per_share = abs(request.entry_price - request.stop_price)
        risk_amount = risk_per_share * request.shares
        target_prices = request.target_prices or [request.entry_price * 1.03, request.entry_price * 1.06]
        reward_per_share = abs(target_prices[0] - request.entry_price)
        potential_reward = reward_per_share * request.shares
        risk_reward_ratio = (reward_per_share / risk_per_share) if risk_per_share > 0 else 2.0
        
        # Create trade object with ALL required fields
        trade = BotTrade(
            id=str(uuid.uuid4()),
            symbol=request.symbol.upper(),
            direction=direction,
            status=TradeStatus.OPEN,
            setup_type=request.setup_type,
            timeframe="imported",
            quality_score=70,
            quality_grade="B",
            entry_price=request.entry_price,
            current_price=request.entry_price,
            stop_price=request.stop_price,
            target_prices=target_prices,
            shares=request.shares,
            risk_amount=risk_amount,
            potential_reward=potential_reward,
            risk_reward_ratio=risk_reward_ratio
        )
        
        # Set additional fields
        trade.fill_price = request.entry_price
        trade.executed_at = datetime.now(timezone.utc).isoformat()
        trade.notes = f"[IMPORTED] Imported from IB - {request.notes or 'manual import'}"
        
        # Initialize trailing stop config
        trade.trailing_stop_config = {
            "mode": "initial",
            "current_stop": request.stop_price,
            "original_stop": request.stop_price,
            "highest_price": request.entry_price,
            "lowest_price": request.entry_price,
            "stop_adjustments": []
        }
        
        # Add to bot's open trades
        _trading_bot._open_trades[trade.id] = trade
        
        # Save to database for persistence
        await _trading_bot._save_trade(trade)
        
        logger.info(f"✅ Imported position: {trade.symbol} {trade.shares} shares {direction.value} @ ${trade.entry_price:.2f}, stop=${trade.stop_price:.2f}")
        
        return {
            "success": True,
            "message": f"Successfully imported {request.symbol} position into bot management",
            "trade": trade.to_dict(),
            "stop_monitoring": True
        }
        
    except Exception as e:
        logger.error(f"Failed to import position: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to import position: {str(e)}")


@router.get("/sync-positions")
def sync_with_ib_positions():
    """
    Sync bot's tracked trades with actual IB positions.
    
    This will:
    1. Update prices/P&L for tracked trades
    2. Identify orphaned trades (in bot but not in IB)
    3. Identify untracked positions (in IB but not in bot)
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    try:
        from routers.ib import get_pushed_positions
        
        ib_positions = get_pushed_positions()
        ib_symbols = {p.get("symbol"): p for p in ib_positions if p.get("position", 0) != 0}
        
        bot_trades = _trading_bot._open_trades
        bot_symbols = {t.symbol: t for t in bot_trades.values()}
        
        # Find discrepancies
        orphaned = []  # In bot but not in IB
        untracked = []  # In IB but not in bot
        synced = []  # Matched positions
        
        # Check bot trades against IB
        for symbol, trade in bot_symbols.items():
            if symbol in ib_symbols:
                ib_pos = ib_symbols[symbol]
                synced.append({
                    "symbol": symbol,
                    "bot_shares": trade.shares,
                    "ib_shares": abs(ib_pos.get("position", 0)),
                    "bot_entry": trade.fill_price,
                    "ib_avg_cost": ib_pos.get("avgCost", 0),
                    "current_price": ib_pos.get("marketPrice", 0),
                    "stop_price": trade.stop_price
                })
            else:
                orphaned.append({
                    "symbol": symbol,
                    "shares": trade.shares,
                    "note": "Position not found in IB - may have been closed"
                })
        
        # Check IB positions not in bot
        for symbol, ib_pos in ib_symbols.items():
            if symbol not in bot_symbols:
                shares = ib_pos.get("position", 0)
                untracked.append({
                    "symbol": symbol,
                    "shares": abs(shares),
                    "direction": "long" if shares > 0 else "short",
                    "avg_cost": ib_pos.get("avgCost", 0),
                    "note": "Position not tracked by bot - no stop protection"
                })
        
        return {
            "success": True,
            "synced_positions": synced,
            "orphaned_trades": orphaned,
            "untracked_positions": untracked,
            "summary": {
                "bot_tracking": len(bot_trades),
                "ib_positions": len(ib_symbols),
                "synced": len(synced),
                "orphaned": len(orphaned),
                "untracked": len(untracked)
            }
        }
        
    except Exception as e:
        logger.error(f"Position sync error: {e}")
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


@router.post("/clear-orphaned")
def clear_orphaned_trades():
    """
    Remove trades from bot tracking that no longer exist in IB.
    
    This is useful after:
    - Manual closes in IB that the bot didn't track
    - App restarts where old phantom trades remain
    - Database sync issues
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    try:
        from routers.ib import get_pushed_positions
        
        ib_positions = get_pushed_positions()
        ib_symbols = {p.get("symbol") for p in ib_positions if p.get("position", 0) != 0}
        
        # Find orphaned trades (in bot but not in IB)
        orphaned_ids = []
        orphaned_symbols = []
        
        for trade_id, trade in list(_trading_bot._open_trades.items()):
            if trade.symbol not in ib_symbols:
                orphaned_ids.append(trade_id)
                orphaned_symbols.append(trade.symbol)
        
        # Remove orphaned trades
        for trade_id in orphaned_ids:
            if trade_id in _trading_bot._open_trades:
                del _trading_bot._open_trades[trade_id]
        
        logger.info(f"🧹 Cleared {len(orphaned_ids)} orphaned trades: {orphaned_symbols[:10]}...")
        
        return {
            "success": True,
            "cleared_count": len(orphaned_ids),
            "cleared_symbols": orphaned_symbols,
            "remaining_trades": len(_trading_bot._open_trades),
            "message": f"Cleared {len(orphaned_ids)} orphaned trades that no longer exist in IB"
        }
        
    except Exception as e:
        logger.error(f"Failed to clear orphaned trades: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear orphaned trades: {str(e)}")


# ==================== SMART STRATEGY FILTERING ENDPOINTS ====================

@router.get("/smart-filter/config")
def get_smart_filter_config():
    """Get the current Smart Strategy Filter configuration"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    return {
        "success": True,
        "config": _trading_bot.get_smart_filter_config()
    }


@router.post("/smart-filter/config")
def update_smart_filter_config(updates: Dict[str, Any]):
    """
    Update Smart Strategy Filter configuration.
    
    Available settings:
    - enabled: bool - Enable/disable smart filtering
    - min_sample_size: int - Minimum trades needed to filter (default: 5)
    - skip_win_rate_threshold: float - Skip if win rate below this (default: 0.35)
    - reduce_size_threshold: float - Reduce size if below this (default: 0.45)
    - require_higher_tqs_threshold: float - Require higher TQS if below (default: 0.50)
    - normal_threshold: float - Normal trading above this (default: 0.55)
    - size_reduction_pct: float - Size reduction percentage (default: 0.5)
    - high_tqs_requirement: int - TQS required for borderline (default: 75)
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    new_config = _trading_bot.update_smart_filter_config(updates)
    
    return {
        "success": True,
        "message": "Smart filter config updated",
        "config": new_config
    }


@router.get("/smart-filter/thoughts")
def get_filter_thoughts(limit: int = Query(10, ge=1, le=50)):
    """
    Get recent strategy filter thoughts/reasoning.
    
    These show when the bot skipped or modified trades based on historical performance.
    Example: "Passing on NVDA breakout - you're only 38% on breakouts historically"
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    thoughts = _trading_bot.get_filter_thoughts(limit=limit)
    
    return {
        "success": True,
        "thoughts": thoughts,
        "count": len(thoughts)
    }


@router.get("/smart-filter/strategy-stats/{setup_type}")
def get_strategy_stats(setup_type: str):
    """
    Get user's historical performance stats for a specific setup type.
    
    Returns win rate, sample size, average R, expected value, etc.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    stats = _trading_bot.get_strategy_historical_stats(setup_type)
    
    return {
        "success": True,
        **stats
    }


@router.get("/smart-filter/all-strategy-stats")
def get_all_strategy_stats():
    """
    Get user's historical performance stats for ALL setup types.
    Useful for the Learning Dashboard to show strategy performance breakdown.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    if not _trading_bot._enhanced_scanner:
        return {
            "success": False,
            "error": "Enhanced scanner not connected",
            "stats": {}
        }
    
    try:
        all_stats = _trading_bot._enhanced_scanner.get_strategy_stats()
        return {
            "success": True,
            "stats": all_stats,
            "count": len(all_stats)
        }
    except Exception as e:
        logger.error(f"Error getting all strategy stats: {e}")
        return {
            "success": False,
            "error": str(e),
            "stats": {}
        }




# ─── v19.31.14 (2026-05-04) — Auto-reconcile-at-boot status pill ───


@router.get("/boot-reconcile-status")
async def get_boot_reconcile_status(pill_visible_seconds: int = 600):
    """v19.31.14 — Read the last `auto_reconcile_at_boot` event so the
    V5 HUD top strip can render a "🔁 Auto-claimed N at boot" pill that
    fades after `pill_visible_seconds` (default 10 min).

    Returns:
        {
          "ran": bool,                  # has the boot reconcile run at all
          "ran_at": iso str | null,     # when it last ran
          "age_seconds": float | null,  # seconds since ran_at
          "reconciled_count": int,
          "skipped_count": int,
          "errors_count": int,
          "symbols": [str],             # up to 32 symbols claimed
          "show_pill": bool,            # age < pill_visible_seconds
          "pill_visible_seconds": int,
        }
    """
    from database import get_database
    from datetime import datetime as _dt, timezone as _tz
    db = get_database()
    if db is None:
        return {
            "ran": False, "ran_at": None, "age_seconds": None,
            "reconciled_count": 0, "skipped_count": 0, "errors_count": 0,
            "symbols": [], "show_pill": False,
            "pill_visible_seconds": pill_visible_seconds,
        }

    try:
        doc = db["bot_state"].find_one(
            {"_id": "last_auto_reconcile_at_boot"}, {"_id": 0},
        )
    except Exception:
        doc = None

    if not doc:
        return {
            "ran": False, "ran_at": None, "age_seconds": None,
            "reconciled_count": 0, "skipped_count": 0, "errors_count": 0,
            "symbols": [], "show_pill": False,
            "pill_visible_seconds": pill_visible_seconds,
        }

    ran_at = doc.get("ran_at")
    age_s: Optional[float] = None
    if ran_at:
        try:
            norm = ran_at.replace("Z", "+00:00") if ran_at.endswith("Z") else ran_at
            dt = _dt.fromisoformat(norm)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_tz.utc)
            age_s = (_dt.now(_tz.utc) - dt).total_seconds()
        except Exception:
            age_s = None

    show_pill = (
        age_s is not None
        and age_s >= 0
        and age_s < pill_visible_seconds
    )

    return {
        "ran": True,
        "ran_at": ran_at,
        "age_seconds": round(age_s, 1) if age_s is not None else None,
        "reconciled_count": int(doc.get("reconciled_count") or 0),
        "skipped_count": int(doc.get("skipped_count") or 0),
        "errors_count": int(doc.get("errors_count") or 0),
        "symbols": list(doc.get("symbols") or [])[:32],
        # v19.34.13 — surface skip reasons so operator can diagnose
        # "why was 1 orphan left behind" without grepping logs.
        "skipped": list(doc.get("skipped") or [])[:32],
        "retry_pass": bool(doc.get("retry_pass", False)),
        "show_pill": bool(show_pill),
        "pill_visible_seconds": pill_visible_seconds,
    }

