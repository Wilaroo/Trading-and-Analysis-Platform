"""
Trade Execution — Extracted from trading_bot_service.py

Handles:
- Trade execution (strategy phase check → broker execution)
- Trade confirmation (stale alert check, price recalculation)
- Trade rejection
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from services.trading_bot_service import BotTrade, TradingBotService

logger = logging.getLogger(__name__)


# ── v19.34.15a (2026-05-06) ── Naked-position safety net helper.
async def _poll_ib_for_silent_fill_v19_34_15a(
    trade: 'BotTrade',
    pre_qty: float,
    rejected_error: str,
    poll_interval_s: float = 1.0,
    total_duration_s: float = 15.0,
) -> None:
    """Post-rejection IB position poll-back.

    After a broker rejection, poll the IB-pushed position snapshot for
    ``total_duration_s`` seconds. If the position quantity for
    ``trade.symbol`` changes by ≥1 share vs ``pre_qty``, the broker
    actually filled the order despite returning a rejection (well-known
    race in IB Gateway under load — parent leg fills, child bracket
    confirm gets dropped). Emit a high-priority stream event so:

    1. The operator sees the event in the V5 unified stream.
    2. The v19.34.15b drift loop picks it up on the next 30s tick and
       spawns a bracketed `reconciled_excess_slice` for the orphan
       fill, restoring stop/target coverage.

    Fires-and-forgets — wrapped in try/except so a poll failure never
    propagates back into execute_trade.
    """
    try:
        from datetime import datetime as _dt, timezone as _tz
        sym_u = (trade.symbol or "").upper()
        elapsed = 0.0
        detected = False
        last_qty = pre_qty
        while elapsed < total_duration_s:
            await asyncio.sleep(poll_interval_s)
            elapsed += poll_interval_s
            try:
                from routers.ib import _pushed_ib_data
                positions = (_pushed_ib_data or {}).get("positions") or []
                cur_qty: Optional[float] = None
                for p in positions:
                    if (p.get("symbol") or "").upper() == sym_u:
                        cur_qty = float(p.get("position") or 0)
                        break
                if cur_qty is None:
                    continue
                last_qty = cur_qty
                if abs(cur_qty - pre_qty) >= 1:
                    detected = True
                    delta = cur_qty - pre_qty
                    try:
                        from services.sentcom_service import emit_stream_event
                        await emit_stream_event({
                            "kind": "warning",
                            "event": "unbracketed_fill_detected_v19_34_15",
                            "symbol": trade.symbol,
                            "text": (
                                f"⚠ {trade.symbol} silent fill detected after "
                                f"rejected order (trade_id={trade.id}, "
                                f"qty={int(trade.shares or 0)}, "
                                f"err={rejected_error[:60]}): IB pos "
                                f"{pre_qty:+.0f} → {cur_qty:+.0f} "
                                f"(Δ {delta:+.0f}). v19.34.15b drift loop "
                                f"will spawn a bracketed slice within ~30s."
                            ),
                            "metadata": {
                                "trade_id": trade.id,
                                "rejected_error": rejected_error,
                                "rejected_qty": int(trade.shares or 0),
                                "rejected_direction": (
                                    trade.direction.value
                                    if hasattr(trade.direction, "value")
                                    else str(trade.direction)
                                ),
                                "ib_qty_before": pre_qty,
                                "ib_qty_after": cur_qty,
                                "delta": delta,
                                "detected_after_seconds": round(elapsed, 1),
                                "detected_at": _dt.now(_tz.utc).isoformat(),
                            },
                        })
                    except Exception as emit_err:  # pragma: no cover
                        logger.warning(
                            "[v19.34.15a] silent-fill stream emit failed "
                            "for %s: %s", trade.symbol, emit_err,
                        )
                    logger.warning(
                        "[v19.34.15a] silent fill detected after rejection "
                        "of %s (trade_id=%s, err=%r): IB pos %+.0f→%+.0f "
                        "(Δ %+.0f) after %.1fs",
                        trade.symbol, trade.id, rejected_error,
                        pre_qty, cur_qty, delta, elapsed,
                    )
                    return
            except Exception as inner_err:
                logger.debug(
                    "[v19.34.15a] poll-back inner error for %s: %s",
                    trade.symbol, inner_err,
                )
        if not detected:
            logger.info(
                "[v19.34.15a] %s rejection clean — no silent fill "
                "detected after %.0fs (pre=%+.0f, last=%+.0f)",
                trade.symbol, total_duration_s, pre_qty, last_qty,
            )
    except Exception as outer_err:  # pragma: no cover
        logger.warning(
            "[v19.34.15a] poll-back task crashed for %s: %s",
            getattr(trade, "symbol", "?"), outer_err,
        )


class TradeExecution:
    """Manages trade execution, confirmation, and rejection logic."""

    async def execute_trade(self, trade: 'BotTrade', bot: 'TradingBotService'):
        """
        Execute a trade via the trade executor.

        Strategy Phase Check (SIM → PAPER → LIVE):
        - LIVE: Execute real trade via broker
        - PAPER: Record paper trade, do not execute
        - SIMULATION: Skip entirely (not ready for real-time)

        In AUTONOMOUS mode with IB data:
        - Uses live IB prices for decision-making
        - Currently executes in SIMULATED mode (orders tracked but not sent to broker)
        - Full IB order execution requires local IB Gateway order routing (future enhancement)
        """
        from services.trading_bot_service import TradeStatus, TradeDirection

        print(f"   📤 [_execute_trade] Starting execution for {trade.symbol}")

        # === STRATEGY PHASE CHECK ===
        # This is the gate that controls which strategies execute real trades
        if bot._strategy_promotion_service:
            should_execute, phase_reason, should_paper = bot._strategy_promotion_service.should_execute_trade(trade.setup_type)

            if not should_execute:
                if should_paper:
                    # PAPER PHASE: Record the trade without executing
                    logger.info(f"📝 [PAPER TRADE] {trade.symbol} {trade.direction.value.upper()} - {phase_reason}")
                    trade.notes = (trade.notes or "") + f" [PAPER: {phase_reason}]"

                    # Forensic breadcrumb — PAPER trades DO save to
                    # bot_trades (with status="paper") but operator
                    # asked for visibility on every silent-execute exit
                    # so we can verify the funnel is healthy.
                    try:
                        from services.trade_drop_recorder import record_trade_drop
                        record_trade_drop(
                            getattr(bot, "_db", None),
                            gate="strategy_paper_phase",
                            symbol=trade.symbol,
                            setup_type=trade.setup_type,
                            direction=trade.direction.value,
                            reason=phase_reason,
                            context={"phase": "paper", "trade_id": trade.id},
                        )
                    except Exception:
                        pass

                    # Record paper trade for tracking
                    try:
                        paper_trade_id = await bot._strategy_promotion_service.record_paper_trade(
                            strategy_name=trade.setup_type,
                            symbol=trade.symbol,
                            direction=trade.direction.value,
                            entry_price=trade.entry_price,
                            stop_price=trade.stop_price,
                            target_price=trade.target_prices[0] if trade.target_prices else trade.entry_price * 1.02,
                            notes=f"Would have traded: {trade.shares} shares | R:R={trade.risk_reward_ratio:.1f}"
                        )
                        logger.info(f"📝 Paper trade recorded: {paper_trade_id}")

                        # Add to filter thoughts for visibility
                        bot._add_filter_thought({
                            "text": f"📝 PAPER: {trade.symbol} {trade.setup_type} ({trade.direction.value}) - Strategy not yet LIVE",
                            "symbol": trade.symbol,
                            "setup_type": trade.setup_type,
                            "action": "PAPER_TRACKED",
                            "phase": "paper"
                        })
                    except Exception as e:
                        logger.warning(
                            "Failed to record paper trade (%s): %s",
                            type(e).__name__, e, exc_info=True,
                        )

                    # Mark trade as not executed (for UI feedback)
                    trade.status = TradeStatus.PAPER
                    trade.close_reason = "paper_phase"
                    await bot._save_trade(trade)
                    return
                else:
                    # SIMULATION PHASE: Skip entirely
                    logger.info(f"⏭️ [SKIPPED] {trade.symbol} {trade.direction.value.upper()} - {phase_reason}")
                    trade.notes = (trade.notes or "") + f" [SKIPPED: {phase_reason}]"
                    trade.status = TradeStatus.SIMULATED
                    trade.close_reason = "simulation_phase"
                    try:
                        from services.trade_drop_recorder import record_trade_drop
                        record_trade_drop(
                            getattr(bot, "_db", None),
                            gate="strategy_simulation_phase",
                            symbol=trade.symbol,
                            setup_type=trade.setup_type,
                            direction=trade.direction.value,
                            reason=phase_reason,
                            context={"phase": "simulation", "trade_id": trade.id},
                        )
                    except Exception:
                        pass
                    await bot._save_trade(trade)
                    return
            else:
                # LIVE PHASE: Proceed with execution
                logger.info(f"🚀 [LIVE STRATEGY] {trade.symbol} {trade.setup_type} - Executing real trade")

        if not bot._trade_executor:
            print("   ❌ Trade executor not configured")
            logger.error("Trade executor not configured")
            try:
                from services.trade_drop_recorder import record_trade_drop
                record_trade_drop(
                    getattr(bot, "_db", None),
                    gate="no_trade_executor",
                    symbol=trade.symbol,
                    setup_type=trade.setup_type,
                    direction=(
                        trade.direction.value if hasattr(trade.direction, "value")
                        else str(trade.direction)
                    ),
                    reason="bot._trade_executor is None — trade dropped before broker call",
                    context={"trade_id": trade.id},
                )
            except Exception:
                pass
            return

        try:
            # Log execution mode
            executor_mode = bot._trade_executor.get_mode() if bot._trade_executor else "unknown"
            print(f"   📤 [_execute_trade] Executor mode: {executor_mode.value if hasattr(executor_mode, 'value') else executor_mode}")
            logger.info(f"[TradingBot] Executing {trade.symbol} {trade.direction.value.upper()} | Mode: {executor_mode.value}")

            # Start execution tracking (Phase 1 Learning)
            if hasattr(bot, '_learning_loop') and bot._learning_loop:
                try:
                    # Use target_prices instead of targets
                    planned_r = (trade.target_prices[0] / trade.entry_price - 1) if trade.target_prices else 2.0
                    bot._learning_loop.start_execution_tracking(
                        trade_id=trade.id,
                        alert_id=getattr(trade, 'alert_id', trade.id),
                        intended_entry=trade.entry_price,
                        intended_size=trade.shares,
                        planned_r=planned_r
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to start execution tracking (%s): %s",
                        type(e).__name__, e, exc_info=True,
                    )

            # === v19.34.8 REJECTION-COOLDOWN GATE ===
            # Operator-driven (2026-05-05 PM): after the XLU/UPS forensic
            # showed 110+ rejected brackets in 71 min on the same setup
            # (caused by structural rejections re-firing every 30s), we
            # short-circuit any (symbol, setup_type) that just got
            # structurally rejected. Cooldown defaults to 5 min and
            # extends on repeat rejections within the window.
            try:
                from services.rejection_cooldown_service import get_rejection_cooldown
                _cooldown = get_rejection_cooldown().is_in_cooldown(
                    symbol=trade.symbol,
                    setup_type=getattr(trade, "setup_type", None) or "unknown",
                )
                if _cooldown is not None:
                    logger.warning(
                        "🧊 [v19.34.8 REJECTION-COOLDOWN] Skipping %s/%s — "
                        "in cooldown (rejection #%d, reason=%s, %ds left). "
                        "Cooldown started at %s.",
                        trade.symbol, _cooldown.setup_type,
                        _cooldown.rejection_count, _cooldown.reason,
                        int(_cooldown.remaining_seconds()),
                        _cooldown.started_at.isoformat(),
                    )
                    trade.status = TradeStatus.VETOED
                    trade.notes = (
                        (trade.notes or "")
                        + f" [REJECTION-COOLDOWN: {_cooldown.reason} "
                        f"({int(_cooldown.remaining_seconds())}s left)]"
                    )
                    trade.close_reason = "rejection_cooldown_active"
                    if trade.id in bot._pending_trades:
                        del bot._pending_trades[trade.id]
                    try:
                        from services.trade_drop_recorder import record_trade_drop
                        record_trade_drop(
                            getattr(bot, "_db", None),
                            gate="rejection_cooldown",
                            symbol=trade.symbol,
                            setup_type=trade.setup_type,
                            direction=(
                                trade.direction.value if hasattr(trade.direction, "value")
                                else str(trade.direction)
                            ),
                            reason=f"cooldown_active_{_cooldown.reason}",
                            context={
                                "trade_id": trade.id,
                                "cooldown_started_at": _cooldown.started_at.isoformat(),
                                "cooldown_expires_at": _cooldown.expires_at.isoformat(),
                                "rejection_count": _cooldown.rejection_count,
                            },
                        )
                    except Exception:
                        pass
                    await bot._save_trade(trade)
                    return
            except Exception as e:
                # Fail-OPEN on cooldown infrastructure failure — better
                # to allow than to silently block all trading on a bug
                # in the cooldown service.
                logger.warning(
                    "Rejection cooldown check failed (allowing trade) (%s): %s",
                    type(e).__name__, e,
                )

            # === PRE-EXECUTION GUARD RAILS (2026-04-21) ===
            # Block pathologically tight stops and oversized positions BEFORE
            # any order hits the broker. See services/execution_guardrails.py
            # and memory/IB_BRACKET_ORDER_MIGRATION.md for the audit that
            # motivated these (USO $0.03 stop on a $108 stock = -261R bleed).
            try:
                from services.execution_guardrails import run_all_guardrails
                # Best-effort ATR lookup — fall back to None if unavailable
                atr_14 = getattr(trade, "atr_14", None)
                if atr_14 is None and hasattr(bot, "_atr_cache"):
                    atr_14 = bot._atr_cache.get(trade.symbol)

                account_equity = None
                try:
                    if bot._trade_executor and hasattr(bot._trade_executor, "get_account_info"):
                        acct = await bot._trade_executor.get_account_info()
                        if isinstance(acct, dict):
                            account_equity = acct.get("equity") or acct.get("portfolio_value")
                except Exception:
                    account_equity = None

                veto = run_all_guardrails(
                    entry_price=trade.entry_price,
                    stop_price=trade.stop_price,
                    shares=trade.shares,
                    atr_14=atr_14,
                    account_equity=account_equity,
                )
                if veto.skip:
                    logger.warning(f"🛡️ [Guardrail VETO] {trade.symbol}: {veto.reason}")
                    print(f"   🛡️ [Guardrail VETO] {trade.symbol}: {veto.reason}")
                    trade.status = TradeStatus.VETOED
                    trade.notes = (trade.notes or "") + f" [GUARDRAIL: {veto.reason}]"
                    trade.close_reason = "guardrail_veto"
                    # v19.34.8 — guardrail vetoes that are structural in
                    # nature (capital, exposure, etc.) feed the cooldown.
                    # Transient vetoes (stop-too-tight, etc.) do NOT.
                    try:
                        from services.rejection_cooldown_service import get_rejection_cooldown
                        get_rejection_cooldown().mark_rejection(
                            symbol=trade.symbol,
                            setup_type=getattr(trade, "setup_type", None) or "unknown",
                            reason=str(veto.reason),
                        )
                    except Exception:
                        pass
                    if trade.id in bot._pending_trades:
                        del bot._pending_trades[trade.id]
                    try:
                        from services.trade_drop_recorder import record_trade_drop
                        record_trade_drop(
                            getattr(bot, "_db", None),
                            gate="pre_exec_guardrail_veto",
                            symbol=trade.symbol,
                            setup_type=trade.setup_type,
                            direction=(
                                trade.direction.value if hasattr(trade.direction, "value")
                                else str(trade.direction)
                            ),
                            reason=str(veto.reason),
                            context={
                                "trade_id": trade.id,
                                "entry_price": float(trade.entry_price or 0),
                                "stop_price": float(trade.stop_price or 0),
                                "shares": int(trade.shares or 0),
                            },
                        )
                    except Exception:
                        pass
                    await bot._save_trade(trade)
                    return
            except Exception as e:
                # CRITICAL fail-OPEN path: a swallowed AttributeError here
                # would let an undersized/oversized trade reach the broker.
                # Surface type + traceback (lesson from the 2026-04-30 v13
                # `BotTrade.quantity` typo regression).
                logger.warning(
                    "Guardrail check failed (allowing trade) (%s): %s",
                    type(e).__name__, e, exc_info=True,
                )

            # Execute entry order — Phase 3 (2026-04-22): prefer atomic bracket
            # over the legacy two-step entry→stop flow so stops can't die on
            # bot restart. Falls back automatically if pusher hasn't been
            # upgraded yet (Phase 2 pusher contract in PUSHER_BRACKET_SPEC.md).
            #
            # v19.29 (2026-05-01) — Order-level intent dedup. Operator caught
            # 300+ duplicate cancelled orders 2:17pm-3:55pm because the bot
            # re-fired the same `(symbol, side, qty±5%, price±0.5%)` intent
            # every scanner cycle while the previous one was still pending
            # in IB. We block that here BEFORE placing — symbol-level
            # cooldown is too coarse for this pattern.
            try:
                from services.order_intent_dedup import get_order_intent_dedup
                _dedup = get_order_intent_dedup()
                _intent_side = "buy" if trade.direction == TradeDirection.LONG else "sell"
                _intent_price = float(trade.entry_price or 0)
                _intent_qty = int(trade.shares or 0)
                _existing = _dedup.is_already_pending(
                    symbol=trade.symbol,
                    side=_intent_side,
                    qty=_intent_qty,
                    price=_intent_price,
                )
                if _existing is not None:
                    logger.warning(
                        "🛑 [v19.29 INTENT-DEDUP] Skipping %s %s %dsh @ $%.2f — "
                        "matching intent already pending in IB (submitted %s, "
                        "trade_id=%s). Will retry once it fills or expires.",
                        trade.symbol, _intent_side.upper(), _intent_qty,
                        _intent_price,
                        _existing.submitted_at.isoformat(),
                        _existing.trade_id,
                    )
                    trade.status = TradeStatus.VETOED
                    trade.notes = (trade.notes or "") + " [INTENT-DEDUP-SKIP]"
                    trade.close_reason = "intent_already_pending"
                    if trade.id in bot._pending_trades:
                        del bot._pending_trades[trade.id]
                    try:
                        from services.trade_drop_recorder import record_trade_drop
                        record_trade_drop(
                            getattr(bot, "_db", None),
                            gate="intent_dedup",
                            symbol=trade.symbol,
                            setup_type=trade.setup_type,
                            direction=(
                                trade.direction.value if hasattr(trade.direction, "value")
                                else str(trade.direction)
                            ),
                            reason="intent_already_pending",
                            context={
                                "existing_trade_id": _existing.trade_id,
                                "submitted_at": _existing.submitted_at.isoformat(),
                                "qty": _intent_qty,
                                "price": _intent_price,
                            },
                        )
                    except Exception:
                        pass
                    await bot._save_trade(trade)
                    return
                # Stamp the intent BEFORE submitting so a fast loop can't
                # squeak through. clear_filled() is called from the fill /
                # cancel paths below.
                _dedup.mark_pending(
                    symbol=trade.symbol,
                    side=_intent_side,
                    qty=_intent_qty,
                    price=_intent_price,
                    trade_id=trade.id,
                )
            except Exception as _dedup_err:
                # NEVER fail-closed on dedup — better to risk a duplicate
                # order than block a legitimate trade. Log and proceed.
                logger.warning(
                    "v19.29 intent-dedup error (allowing trade): %s: %s",
                    type(_dedup_err).__name__, _dedup_err,
                )

            print("   📤 [_execute_trade] Calling trade_executor.place_bracket_order...")

            # v19.34.6 (2026-05-05) — Pre-execution Mongo-first sanity
            # gate. Operator-driven: stamp `bot_trades` with status=PENDING
            # + `pre_submit_at` BEFORE we hand the order to IB. Eliminates
            # the "IB fill but no Mongo row" class of bug — if the bot
            # crashes between submit and fill confirmation, the row is
            # already on disk and the orphan-recovery loop can adopt it.
            # Post-fill `_save_trade` calls below upsert by trade.id, so
            # this row is overwritten with the final OPEN/REJECTED state.
            try:
                from services.trading_bot_service import TradeStatus as _TS
                trade.pre_submit_at = datetime.now(timezone.utc).isoformat()
                # Only flip status if we haven't already flipped it (e.g.
                # the strategy-phase / guardrail / dedup branches above
                # set PAPER / VETOED and returned). Real broker-bound
                # trades are still in their initial PENDING state.
                if trade.status not in (_TS.PAPER, _TS.SIMULATED, _TS.VETOED, _TS.REJECTED):
                    trade.status = _TS.PENDING
                trade.notes = (trade.notes or "") + " [PRE-SUBMIT-v19.34.6]"
                await bot._save_trade(trade)
                logger.info(
                    "[v19.34.6 PRE-SUBMIT] %s %s %dsh @ $%.2f — Mongo row "
                    "written before broker call (trade_id=%s)",
                    trade.symbol,
                    trade.direction.value if hasattr(trade.direction, "value") else trade.direction,
                    int(trade.shares or 0),
                    float(trade.entry_price or 0),
                    trade.id,
                )
            except Exception as _pre_save_err:
                # NEVER fail-closed on the pre-submit save — better to
                # risk a missing audit row than block a real entry. Log
                # loudly so the operator sees the gap.
                logger.warning(
                    "[v19.34.6 PRE-SUBMIT] save failed for %s (%s): %s — "
                    "proceeding to broker anyway",
                    getattr(trade, "symbol", "?"),
                    type(_pre_save_err).__name__, _pre_save_err,
                )

            # ── v19.34.15a (2026-05-06) — capture IB position snapshot
            # BEFORE the broker call so the post-rejection poll-back
            # has a baseline. If the broker rejects but the parent leg
            # actually fills (race), we'll see the IB position move from
            # `pre_position_qty` to a non-trivial delta within ~15s.
            pre_position_qty: Optional[float] = None
            try:
                from routers.ib import _pushed_ib_data
                _positions = (_pushed_ib_data or {}).get("positions") or []
                _sym_u = (trade.symbol or "").upper()
                for _p in _positions:
                    if (_p.get("symbol") or "").upper() == _sym_u:
                        pre_position_qty = float(_p.get("position") or 0)
                        break
                if pre_position_qty is None:
                    pre_position_qty = 0.0
            except Exception as _snap_err:
                logger.debug(
                    f"[v19.34.15a] pre-submit position snap failed for "
                    f"{trade.symbol}: {_snap_err}"
                )

            bracket_result = await bot._trade_executor.place_bracket_order(trade)
            use_legacy = (
                not bracket_result.get('success') and
                bracket_result.get('fallback') == 'legacy' or
                bracket_result.get('error') in ('bracket_not_supported',
                                                'alpaca_bracket_not_implemented',
                                                'bracket_missing_stop_or_target')
            )
            if use_legacy:
                logger.info("Bracket unavailable → legacy entry+stop path")
                print("   ↩️ [_execute_trade] Falling back to legacy execute_entry+place_stop_order")
                result = await bot._trade_executor.execute_entry(trade)
            else:
                # Translate bracket result into the legacy `result` dict shape
                # so downstream code doesn't have to change.
                result = {
                    "success": bracket_result.get("success"),
                    "order_id": bracket_result.get("entry_order_id"),
                    "fill_price": bracket_result.get("fill_price", trade.entry_price),
                    "filled_qty": bracket_result.get("filled_qty", 0),
                    "status": bracket_result.get("status"),
                    "broker": bracket_result.get("broker", "interactive_brokers"),
                    "simulated": bracket_result.get("simulated", False),
                    "error": bracket_result.get("error"),
                    "bracket": True,  # flag so we skip the separate stop placement
                    "stop_order_id": bracket_result.get("stop_order_id"),
                    "target_order_id": bracket_result.get("target_order_id"),
                    "oca_group": bracket_result.get("oca_group"),
                }
            print(f"   📤 [_execute_trade] Result: {result}")

            if result.get('success'):
                trade.status = TradeStatus.OPEN
                trade.fill_price = result.get('fill_price', trade.entry_price)
                trade.executed_at = datetime.now(timezone.utc).isoformat()
                trade.entry_order_id = result.get('order_id')

                # v19.29 — clear the pending-intent stamp so the next
                # legitimate same-symbol entry isn't blocked by the
                # dedup. We use the symbol+side+qty+price tuple we
                # registered above.
                try:
                    from services.order_intent_dedup import get_order_intent_dedup
                    get_order_intent_dedup().clear_filled(
                        symbol=trade.symbol,
                        side=("buy" if trade.direction == TradeDirection.LONG else "sell"),
                        qty=int(trade.shares or 0),
                        price=float(trade.entry_price or 0),
                    )
                except Exception:
                    pass

                # Initialize MFE/MAE at fill price (starting point)
                trade.mfe_price = trade.fill_price
                trade.mae_price = trade.fill_price

                # Track entry commission
                entry_commission = bot._apply_commission(trade, trade.shares)

                # Mark if simulated
                if result.get('simulated'):
                    trade.notes = (trade.notes or "") + " [SIMULATED]"
                else:
                    broker = result.get('broker', 'unknown')
                    tag = "BRACKET" if result.get('bracket') else "LIVE"
                    trade.notes = (trade.notes or "") + f" [{tag}-{broker.upper()}]"

                print(f"   💰 Entry commission: ${entry_commission:.2f} ({trade.shares} shares @ ${trade.commission_per_share}/share)")

                # v19.31.13 — stamp trade_type from the IB account that
                # actually filled this order. We grab the current account
                # ID from the pusher snapshot at fill time and classify
                # via account_guard. Stamping AT FILL preserves historical
                # truth: if the operator flips IB_ACCOUNT_ACTIVE between
                # paper and live tomorrow, today's rows still know they
                # were paper.
                try:
                    from routers.ib import _pushed_ib_data, is_pusher_connected
                    from services.account_guard import classify_account_id
                    current_acct = None
                    if is_pusher_connected():
                        # Account id is per-position in the snapshot;
                        # any non-empty value tells us who filled.
                        for _ip in (_pushed_ib_data.get("positions") or []):
                            _a = (_ip.get("account") or "").strip()
                            if _a:
                                current_acct = _a
                                break
                        # Fallback: top-level account_summary if pusher
                        # publishes it.
                        if not current_acct:
                            current_acct = (
                                (_pushed_ib_data.get("account_summary") or {}).get("account")
                                or _pushed_ib_data.get("account")
                            )
                    if current_acct:
                        trade.account_id_at_fill = current_acct
                        trade.trade_type = classify_account_id(current_acct)
                    else:
                        # Pusher offline at fill → fall back to env.
                        from services.account_guard import load_account_expectation
                        trade.trade_type = load_account_expectation().active_mode
                except Exception as e:
                    logger.debug(f"trade_type classification failed (non-fatal): {e}")
                    trade.trade_type = "unknown"

                # v19.34.3 (2026-05-04) — provenance stamp. The bot's
                # own evaluation + execution path opened this trade
                # via real setup math + R:R check. Distinct from
                # `reconciled_external` which the position_reconciler
                # uses when adopting an IB orphan.
                trade.entered_by = "bot_fired"

                # Record actual entry (Phase 1 Learning)
                if hasattr(bot, '_learning_loop') and bot._learning_loop:
                    try:
                        bot._learning_loop.record_trade_entry(
                            trade_id=trade.id,
                            actual_entry=trade.fill_price,
                            actual_size=trade.shares
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to record entry (%s): %s",
                            type(e).__name__, e, exc_info=True,
                        )

                # Stop handling — bracket already placed the stop atomically,
                # otherwise place it sequentially (legacy path)
                if result.get('bracket'):
                    trade.stop_order_id = result.get('stop_order_id')
                    trade.target_order_id = result.get('target_order_id')
                    if result.get('oca_group'):
                        trade.notes = (trade.notes or "") + f" [OCA:{result['oca_group']}]"
                else:
                    stop_result = await bot._trade_executor.place_stop_order(trade)
                    if stop_result.get('success'):
                        trade.stop_order_id = stop_result.get('order_id')

                # Move to open trades
                if trade.id in bot._pending_trades:
                    del bot._pending_trades[trade.id]
                bot._open_trades[trade.id] = trade

                # Update stats
                bot._daily_stats.trades_executed += 1

                await bot._notify_trade_update(trade, "executed")
                await bot._save_trade(trade)

                # Auto-record to Trade Journal
                await bot._log_trade_to_journal(trade, "entry")

                sim_tag = " (SIMULATED)" if result.get('simulated') else ""
                logger.info(f"✅ Trade executed{sim_tag}: {trade.symbol} {trade.shares} @ ${trade.fill_price:.2f}")

                # Surface to V5 Unified Stream so operators see fills land
                # in the same place they see scanner / safety events.
                try:
                    from services.sentcom_service import emit_stream_event
                    direction_label = (
                        str(trade.direction.value).upper()
                        if hasattr(trade.direction, "value")
                        else str(trade.direction).upper()
                    )
                    await emit_stream_event({
                        "kind": "fill",
                        "event": "trade_filled",
                        "symbol": trade.symbol,
                        "text": (
                            f"✅ Filled {direction_label} {trade.shares} {trade.symbol} "
                            f"@ ${trade.fill_price:.2f}{sim_tag}"
                        ),
                        "metadata": {
                            "trade_id": trade.id,
                            "setup_type": getattr(trade, "setup_type", None),
                            "shares": trade.shares,
                            "fill_price": trade.fill_price,
                        },
                    })
                except Exception:
                    pass

                # ── v19.25: invalidate chart response cache so the new
                # entry/exit marker shows up on the next chart render
                # without waiting for the 30s/180s TTL.
                try:
                    from services.chart_response_cache import (
                        get_chart_response_cache,
                    )
                    await get_chart_response_cache().invalidate(trade.symbol)
                except Exception:
                    pass

            elif result.get('status') == 'timeout':
                # TIMEOUT HANDLING: Order may still execute - save as pending for sync
                trade.status = TradeStatus.OPEN  # Assume it went through
                trade.fill_price = trade.entry_price  # Use intended price
                trade.executed_at = datetime.now(timezone.utc).isoformat()
                trade.entry_order_id = result.get('order_id')
                trade.notes = (trade.notes or "") + " [TIMEOUT-NEEDS-SYNC]"

                # ── v19.34.20 (2026-05-06) — Initialize share-tracking on
                # timeout. Pre-fix the BotTrade dataclass defaults
                # (`remaining_shares=0`, `original_shares=0` —
                # trading_bot_service.py L617-618) stayed at 0 because the
                # TIMEOUT block stamped `status=OPEN` and persisted without
                # ever overwriting these. The manage-loop self-heal at
                # position_manager.py L494-496 only fires when a fresh
                # quote arrives — TIMEOUT-NEEDS-SYNC trades typically go
                # quote-stale before that, so they rotted as zombies
                # (status=OPEN, rs=0, os=0). Forensic 2026-05-06 found
                # 905 sh stuck across two zombies (3f369929 FDX 20sh +
                # 95144a8d UPS 885sh) — both with this exact fingerprint.
                # See /app/memory/forensics/zombie_root_cause_v19_34_19.md.
                trade.remaining_shares = int(trade.shares)
                trade.original_shares = int(trade.shares)

                # Initialize MFE/MAE
                trade.mfe_price = trade.fill_price
                trade.mae_price = trade.fill_price

                # Move to open trades so bot tracks it
                if trade.id in bot._pending_trades:
                    del bot._pending_trades[trade.id]
                bot._open_trades[trade.id] = trade

                # Update stats
                bot._daily_stats.trades_executed += 1

                await bot._save_trade(trade)

                logger.warning(f"⚠️ Trade timeout but saved for sync: {trade.symbol} {trade.shares} shares - will verify with IB")

            else:
                trade.status = TradeStatus.REJECTED
                logger.warning(f"Trade rejected: {result.get('error')}")
                # v19.29 — clear pending-intent stamp on rejection so
                # the symbol can be re-attempted on the next cycle
                # (the dedup is "pending in IB", not "previously failed").
                try:
                    from services.order_intent_dedup import get_order_intent_dedup
                    get_order_intent_dedup().clear_filled(
                        symbol=trade.symbol,
                        side=("buy" if trade.direction == TradeDirection.LONG else "sell"),
                        qty=int(trade.shares or 0),
                        price=float(trade.entry_price or 0),
                    )
                except Exception:
                    pass
                # v19.34.8 (2026-05-05 PM) — Mark structural rejections so
                # the next eval of the same (symbol, setup_type) is short-
                # circuited at the cooldown gate (see top of execute_trade).
                # Operator-driven after XLU 110-bracket loop forensic.
                try:
                    from services.rejection_cooldown_service import get_rejection_cooldown
                    _reason = str(result.get("error") or result.get("status") or "unknown")
                    get_rejection_cooldown().mark_rejection(
                        symbol=trade.symbol,
                        setup_type=getattr(trade, "setup_type", None) or "unknown",
                        reason=_reason,
                    )
                except Exception as _cd_err:
                    logger.debug(f"rejection_cooldown.mark_rejection failed: {_cd_err}")
                # ──────────────────────────────────────────────────────
                # Forensic instrumentation (2026-04-30) — root-cause of
                # the April 16 silent regression. The legacy code path
                # never wrote a row to `bot_trades` here, so a 13-day
                # spike in broker rejections appeared as "0 trades since
                # April 16" with no rejection breadcrumb anywhere.
                #
                # Two fixes:
                #   1. Drop a record into `trade_drops` with the broker
                #      error so the diagnostic endpoint surfaces it.
                #   2. Persist the REJECTED trade to `bot_trades` so the
                #      analytics pipeline (and future post-mortems) can
                #      see attempted-but-failed executions, not just
                #      successes.
                # ──────────────────────────────────────────────────────
                try:
                    from services.trade_drop_recorder import record_trade_drop
                    record_trade_drop(
                        getattr(bot, "_db", None),
                        gate="broker_rejected",
                        symbol=trade.symbol,
                        setup_type=trade.setup_type,
                        direction=(
                            trade.direction.value if hasattr(trade.direction, "value")
                            else str(trade.direction)
                        ),
                        reason=str(result.get("error") or result.get("status") or "unknown"),
                        context={
                            "trade_id": trade.id,
                            "broker": result.get("broker"),
                            "status": result.get("status"),
                            "simulated": result.get("simulated"),
                            "bracket": result.get("bracket"),
                        },
                    )
                except Exception:
                    pass
                trade.close_reason = "broker_rejected"
                trade.notes = (trade.notes or "") + f" [REJECTED: {str(result.get('error') or result.get('status') or 'unknown')[:120]}]"
                if trade.id in bot._pending_trades:
                    del bot._pending_trades[trade.id]
                try:
                    await bot._save_trade(trade)
                except Exception as save_err:
                    logger.warning(
                        "Could not persist REJECTED trade %s (%s): %s",
                        trade.id, type(save_err).__name__, save_err, exc_info=True,
                    )

                # ── v19.34.15a (2026-05-06) — Post-rejection IB poll-back.
                # Pre-fix: every rejection was final. If the broker actually
                # filled despite returning a rejection (well-known race in
                # IB Gateway under load — parent leg fills, child bracket
                # confirm gets dropped), the position sat orphaned at IB
                # with no stop/target until the next orphan reconciler tick
                # (~30-60s). The 4879-naked-share UPS event 2026-05-06 was
                # this exact pattern. Now: kick a fire-and-forget task that
                # polls IB position every 1s for 15s post-rejection and
                # emits `unbracketed_fill_detected_v19_34_15` if a fill is
                # detected, so v19.34.15b drift loop catches it within 30s
                # AND so the operator sees the event in the V5 stream.
                if pre_position_qty is not None and not result.get("simulated"):
                    try:
                        asyncio.create_task(
                            _poll_ib_for_silent_fill_v19_34_15a(
                                trade=trade,
                                pre_qty=pre_position_qty,
                                rejected_error=str(
                                    result.get("error")
                                    or result.get("status")
                                    or "unknown"
                                ),
                                poll_interval_s=1.0,
                                total_duration_s=15.0,
                            )
                        )
                    except Exception as _poll_err:
                        logger.warning(
                            "[v19.34.15a] could not schedule poll-back for "
                            "%s (%s): %s",
                            trade.symbol, type(_poll_err).__name__, _poll_err,
                        )

        except Exception as e:
            # 2026-04-30 v14: `logger.exception` so the traceback is in
            # the log line itself, not buried in a separate
            # `traceback.print_exc()` call. This is the gate that hid
            # the 13-day `BotTrade.quantity` regression — keep loud.
            logger.exception(
                "Trade execution error (%s): %s",
                type(e).__name__, e,
            )
            trade.status = TradeStatus.REJECTED
            try:
                from services.trade_drop_recorder import record_trade_drop
                record_trade_drop(
                    getattr(bot, "_db", None),
                    gate="execution_exception",
                    symbol=getattr(trade, "symbol", None),
                    setup_type=getattr(trade, "setup_type", None),
                    direction=(
                        trade.direction.value if hasattr(trade.direction, "value")
                        else str(getattr(trade, "direction", ""))
                    ),
                    reason=f"{type(e).__name__}: {e}",
                    context={"trade_id": getattr(trade, "id", None)},
                )
            except Exception:
                pass
            try:
                trade.close_reason = "execution_exception"
                trade.notes = (trade.notes or "") + f" [EXC: {str(e)[:120]}]"
                if trade.id in bot._pending_trades:
                    del bot._pending_trades[trade.id]
                await bot._save_trade(trade)
            except Exception as save_err:
                logger.warning(
                    "Could not persist exception-rejected trade (%s): %s",
                    type(save_err).__name__, save_err, exc_info=True,
                )

    async def confirm_trade(self, trade_id: str, bot: 'TradingBotService') -> bool:
        """
        Confirm a pending trade for execution.

        Before executing:
        1. Check if the alert is stale (expired based on timeframe)
        2. Recalculate entry price, shares, and risk based on current market price
        """
        from services.trading_bot_service import TradeStatus

        if trade_id not in bot._pending_trades:
            return False

        trade = bot._pending_trades[trade_id]

        # === STALE ALERT CHECK ===
        # Scalps/intraday: 5 min timeout. Swings: 15 min. Investment: 60 min.
        stale_thresholds = {
            "scalp": 300,      # 5 min
            "day": 600,        # 10 min
            "swing": 900,      # 15 min
            "investment": 3600, # 60 min
        }
        max_age_seconds = stale_thresholds.get(trade.timeframe, 600)  # Default 10 min

        if trade.created_at:
            try:
                created = datetime.fromisoformat(trade.created_at.replace('Z', '+00:00'))
                age = (datetime.now(timezone.utc) - created).total_seconds()
                if age > max_age_seconds:
                    logger.info(f"Stale alert: {trade.symbol} {trade.setup_type} is {age:.0f}s old (max {max_age_seconds}s for {trade.timeframe})")
                    trade.status = TradeStatus.REJECTED
                    trade.notes = (trade.notes or "") + f" [EXPIRED: {age:.0f}s old]"
                    del bot._pending_trades[trade_id]
                    await bot._notify_trade_update(trade, "expired")
                    return False
            except Exception as e:
                logger.warning(
                    "Could not check alert age (%s): %s",
                    type(e).__name__, e, exc_info=True,
                )

        # === PRICE RECALCULATION ===
        # Get current market price and recalculate position
        current_price = None
        try:
            from routers.ib import get_pushed_quotes, is_pusher_connected
            if is_pusher_connected():
                quotes = get_pushed_quotes()
                if trade.symbol in quotes:
                    q = quotes[trade.symbol]
                    current_price = q.get('last') or q.get('close')
        except Exception:
            pass

        if not current_price and bot._alpaca_service:
            try:
                quote = await bot._alpaca_service.get_quote(trade.symbol)
                current_price = quote.get('price') if quote else None
            except Exception:
                pass

        if current_price and current_price != trade.entry_price:
            old_entry = trade.entry_price
            old_shares = trade.shares
            trade.entry_price = current_price

            # Recalculate shares based on new entry and original stop
            if trade.stop_price and trade.stop_price != trade.entry_price:
                risk_per_share = abs(trade.entry_price - trade.stop_price)
                if risk_per_share > 0:
                    risk_amount = bot.risk_params.max_risk_per_trade
                    new_shares = max(1, int(risk_amount / risk_per_share))
                    trade.shares = new_shares
                    trade.remaining_shares = new_shares
                    trade.original_shares = new_shares

            # Recalculate targets proportionally
            if hasattr(trade, 'scale_out_config') and trade.scale_out_config.get('target_prices'):
                old_targets = trade.scale_out_config['target_prices']
                if old_entry and old_entry != 0:
                    ratio = current_price / old_entry
                    trade.scale_out_config['target_prices'] = [round(t * ratio, 2) for t in old_targets]

            logger.info(
                f"Price recalc on confirm: {trade.symbol} entry ${old_entry:.2f}→${current_price:.2f}, "
                f"shares {old_shares}→{trade.shares}"
            )
            print(f"   🔄 [CONFIRM] Price adjusted: ${old_entry:.2f}→${current_price:.2f}, shares {old_shares}→{trade.shares}")

        await self.execute_trade(trade, bot)

        # Treat every terminal status the pre-trade pipeline can *legitimately*
        # assign as a success. Previously only OPEN counted, so correctly-filtered
        # trades (phase gate → SIMULATED/PAPER, guardrail → VETOED) were
        # reported as API failures (400). The router distinguishes these from
        # a genuine REJECTED via the trade's status field in the response.
        HANDLED_STATUSES = {
            TradeStatus.OPEN,
            TradeStatus.PARTIAL,
            TradeStatus.SIMULATED,
            TradeStatus.VETOED,
            TradeStatus.PAPER,
        }
        return trade.status in HANDLED_STATUSES

    async def reject_trade(self, trade_id: str, bot: 'TradingBotService') -> bool:
        """Reject a pending trade"""
        from services.trading_bot_service import TradeStatus

        if trade_id not in bot._pending_trades:
            return False

        trade = bot._pending_trades[trade_id]
        trade.status = TradeStatus.REJECTED
        del bot._pending_trades[trade_id]
        await bot._notify_trade_update(trade, "rejected")
        return True
