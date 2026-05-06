"""
Position Manager — Extracted from trading_bot_service.py

Handles open position lifecycle:
- P&L updates with IB/Alpaca price feeds
- MFE/MAE tracking
- Stop-loss monitoring (original + trailing)
- Scale-out target execution
- Partial exits
- Full trade close with commission, stats, and journal logging
- EOD auto-close
"""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from services.trading_bot_service import BotTrade, TradingBotService

logger = logging.getLogger(__name__)


class PositionManager:
    """Manages open position updates, scale-outs, closes, and EOD."""

    async def update_open_positions(self, bot: 'TradingBotService'):
        """Update P&L for open positions - uses IB data first, then Alpaca"""
        from services.trading_bot_service import TradeDirection

        # 2026-04-30 v19.13 — quote-staleness guard. If the pusher hangs
        # (we just had 120s timeouts mid-session), an old tick can fire
        # a "ghost" local stop. Reject any quote older than this many
        # seconds; let server-side IB brackets handle the stop instead.
        # Env-tunable so operators on slower / OTC universes can tune.
        import os as _os
        try:
            STALE_QUOTE_S = float(_os.environ.get("MANAGE_STALE_QUOTE_SECONDS", "30"))
        except (TypeError, ValueError):
            STALE_QUOTE_S = 30.0

        # ── v19.27 (2026-05-01) Auto-sweep 0sh phantoms ────────────
        # Operator caught OKLO SHORT 0sh ghost rows in the V5 panel —
        # `BotTrade` records that fully scaled out / stopped out but
        # whose `status` never transitioned `open → closed`. They
        # render as zero-share rows in Open Positions and confuse
        # share-count reconciliation in `sentcom_service.get_our_positions`.
        # 
        # Rule: if a trade has `remaining_shares == 0` AND IB has no
        # matching shares for (symbol, direction), AND the trade has
        # been around for >30s (avoid sweeping a brand-new fill that
        # IB just hasn't reported yet), then transition `status →
        # closed`, emit a thoughts event, and let the persistence
        # layer remove it from `_open_trades` on the next cycle.
        try:
            ib_pos_map: dict = {}
            # v19.31.12 — also collect IB realizedPNL per (symbol, direction)
            # so the sweep paths can stamp realized_pnl onto the bot's
            # closed rows. Without this every OCA-closed trade ended up
            # at $0 realized → Trade Forensics flagged it as drift.
            ib_pos_map_realized: dict = {}
            try:
                from routers.ib import _pushed_ib_data, is_pusher_connected
                if is_pusher_connected():
                    for _ip in (_pushed_ib_data.get("positions") or []):
                        _sym = (_ip.get("symbol") or "").upper()
                        _qty = float(_ip.get("position", 0) or 0)
                        if not _sym:
                            continue
                        # Capture realizedPNL even when position == 0
                        # (those are exactly the OCA-closed cases we
                        # want to credit back to the bot's closed row).
                        _real = float(_ip.get("realizedPNL") or _ip.get("realized_pnl") or 0)
                        if _real:
                            # Index by both directions — at sweep time
                            # we look up by the bot's tracked direction.
                            ib_pos_map_realized[(_sym, "long")] = _real
                            ib_pos_map_realized[(_sym, "short")] = _real
                        if abs(_qty) < 0.001:
                            continue
                        _key = (_sym, "long" if _qty > 0 else "short")
                        ib_pos_map[_key] = abs(_qty)
                        # v19.29 — record direction observation for
                        # the reconcile direction-stability gate.
                        try:
                            from services.position_reconciler import (
                                record_ib_direction_observation,
                            )
                            record_ib_direction_observation(
                                _sym, "long" if _qty > 0 else "short"
                            )
                        except Exception:
                            pass
                else:
                    raise RuntimeError("pusher_not_connected")
            except Exception:
                ib_pos_map = None

            if ib_pos_map is not None:
                from services.trading_bot_service import TradeStatus as _TS
                # v19.29 — extend phantom sweep to catch DIRECTION-MISMATCH
                # phantoms (operator hit this 2026-05-01 with SOFI
                # tracked SHORT while IB had it LONG). If the bot
                # tracks `(symbol, direction)` but IB only has the
                # OPPOSITE direction for that symbol, the bot's row
                # is fully phantom — close-state it without firing
                # any IB action so the bot doesn't try to "manage"
                # a position that doesn't exist.
                for _tid, _trade in list(bot._open_trades.items()):
                    try:
                        if _trade.status == _TS.CLOSED:
                            continue
                        _sym_u = (_trade.symbol or "").upper()
                        _dir = (
                            _trade.direction.value
                            if hasattr(_trade.direction, "value")
                            else str(_trade.direction)
                        ).lower()
                        # Direction-mismatch phantom: bot has direction X,
                        # IB only has direction Y (opposite) for same symbol.
                        opp = "short" if _dir == "long" else "long"
                        ib_qty_my_dir = ib_pos_map.get((_sym_u, _dir), 0)
                        ib_qty_opp_dir = ib_pos_map.get((_sym_u, opp), 0)
                        if ib_qty_my_dir == 0 and ib_qty_opp_dir > 0:
                            # IB has the opposite direction — bot's row
                            # is wrong-direction phantom (today's SOFI
                            # bug exactly). Sweep it.
                            _trade.status = _TS.CLOSED
                            _trade.close_reason = "wrong_direction_phantom_swept_v19_29"
                            from datetime import datetime as _dt3, timezone as _tz3
                            if not getattr(_trade, "closed_at", None):
                                _trade.closed_at = _dt3.now(_tz3.utc).isoformat()
                            try:
                                await asyncio.to_thread(bot._persist_trade, _trade)
                            except Exception:
                                pass
                            bot._open_trades.pop(_tid, None)
                            try:
                                bot._closed_trades.append(_trade)
                            except Exception:
                                pass
                            try:
                                from services.sentcom_service import emit_stream_event
                                await emit_stream_event({
                                    "kind": "warning",
                                    "event": "wrong_direction_phantom_swept",
                                    "symbol": _trade.symbol,
                                    "text": (
                                        f"⚠️ Wrong-direction phantom swept: "
                                        f"{_trade.symbol} tracked {_dir.upper()} "
                                        f"but IB has {opp.upper()} {int(ib_qty_opp_dir)}sh. "
                                        f"Bot's record closed (no IB action) — "
                                        f"v19.29 critical fix."
                                    ),
                                    "metadata": {
                                        "trade_id": _trade.id,
                                        "bot_direction": _dir,
                                        "ib_direction": opp,
                                        "ib_qty": ib_qty_opp_dir,
                                        "reason": "wrong_direction_phantom",
                                    },
                                })
                            except Exception:
                                pass
                            logger.critical(
                                "[v19.29 WRONG-DIR-SWEEP] %s tracked %s but IB has %s %dsh — "
                                "swept bot record, no IB action, trade_id=%s",
                                _trade.symbol, _dir.upper(), opp.upper(),
                                int(ib_qty_opp_dir), _trade.id,
                            )
                            continue  # done with this trade

                        # ── v19.31 (2026-05-04) Externally-closed phantom sweep ──
                        # Operator hit this with LITE on 2026-05-04: OCA
                        # target hit on IB ($961.26), IB closed the position
                        # via the bracket, but `_open_trades` still tracked
                        # 62 sh short. The 0sh-leftover branch below didn't
                        # fire because remaining_shares was 62, not 0. The
                        # wrong-direction branch above didn't fire because
                        # IB has zero shares in BOTH directions. Result: bot
                        # kept "managing" a position that no longer existed
                        # and the dashboard kept drawing it.
                        #
                        # Rule: if bot tracks shares > 0 AND IB has zero
                        # shares in BOTH directions for the symbol AND the
                        # trade is older than 30s (so we don't sweep a
                        # brand-new fill IB hasn't reported yet), the
                        # position was closed externally (OCA target hit,
                        # OCA stop hit, or manual TWS close). Mark CLOSED
                        # with `oca_closed_externally` reason and let the
                        # P&L/journal pipeline catch up on the next tick.
                        _rem_external = getattr(_trade, "remaining_shares", None)
                        if (
                            _rem_external is not None
                            and _rem_external > 0
                            and ib_qty_my_dir == 0
                            and ib_qty_opp_dir == 0
                        ):
                            _executed_at_e = getattr(_trade, "executed_at", None)
                            age_ok_e = True
                            if _executed_at_e:
                                try:
                                    if isinstance(_executed_at_e, str):
                                        from datetime import datetime as _dt_e
                                        _ea_e = _dt_e.fromisoformat(
                                            _executed_at_e.replace("Z", "+00:00")
                                        )
                                    else:
                                        _ea_e = _executed_at_e
                                    if _ea_e.tzinfo is None:
                                        from datetime import timezone as _tz_e
                                        _ea_e = _ea_e.replace(tzinfo=_tz_e.utc)
                                    from datetime import datetime as _dt_e2, timezone as _tz_e2
                                    age_s_e = (_dt_e2.now(_tz_e2.utc) - _ea_e).total_seconds()
                                    age_ok_e = age_s_e >= 30
                                except Exception:
                                    age_ok_e = True
                            if age_ok_e:
                                # v19.31.12 — claim IB realizedPNL onto
                                # the bot's record before marking closed.
                                # Pre-fix: trade.realized_pnl stayed at $0
                                # so Trade Forensics flagged every OCA-
                                # closed trade as "unexplained_drift". Now
                                # we apportion the symbol's IB realizedPNL
                                # across all open bot_trades for that
                                # (symbol, direction) by share count.
                                try:
                                    ib_realized_for_sym = float(
                                        ib_pos_map_realized.get(
                                            ((_trade.symbol or "").upper(), _dir),
                                            0,
                                        ) or 0
                                    )
                                except Exception:
                                    ib_realized_for_sym = 0.0
                                # Apportion: this trade's share of the
                                # symbol's open bot shares × IB realized.
                                # Keeps the math correct even when the
                                # bot has multiple stacked scaled-down
                                # trades for the same symbol.
                                bot_open_shares_same_dir = sum(
                                    int(getattr(t2, "remaining_shares", 0) or 0)
                                    for t2 in bot._open_trades.values()
                                    if (t2.symbol or "").upper() == (_trade.symbol or "").upper()
                                    and (t2.direction.value if hasattr(t2.direction, "value") else str(t2.direction)).lower() == _dir
                                )
                                share_fraction = (
                                    int(_rem_external) / bot_open_shares_same_dir
                                    if bot_open_shares_same_dir > 0 else 1.0
                                )
                                claimed_pnl = round(ib_realized_for_sym * share_fraction, 2)

                                _trade.status = _TS.CLOSED
                                _trade.close_reason = "oca_closed_externally_v19_31"
                                # v19.31.12 — only claim if non-zero AND
                                # bot's existing realized_pnl is zero
                                # (don't double-count if scale-outs already
                                # recorded gains).
                                if claimed_pnl != 0 and not getattr(_trade, "realized_pnl", 0):
                                    _trade.realized_pnl = claimed_pnl
                                from datetime import datetime as _dt_e3, timezone as _tz_e3
                                if not getattr(_trade, "closed_at", None):
                                    _trade.closed_at = _dt_e3.now(_tz_e3.utc).isoformat()
                                # Set remaining_shares to 0 so any downstream
                                # consumer reading the trade dict stops
                                # treating it as live.
                                try:
                                    _trade.remaining_shares = 0
                                except Exception:
                                    pass
                                try:
                                    await asyncio.to_thread(bot._persist_trade, _trade)
                                except Exception:
                                    pass
                                bot._open_trades.pop(_tid, None)
                                try:
                                    bot._closed_trades.append(_trade)
                                except Exception:
                                    pass
                                try:
                                    from services.sentcom_service import emit_stream_event
                                    await emit_stream_event({
                                        "kind": "warning",
                                        "event": "phantom_v19_31_oca_closed_swept",
                                        "symbol": _trade.symbol,
                                        "text": (
                                            f"🧹 v19.31 OCA-closed sweep: "
                                            f"{_trade.symbol} {_dir.upper()} bot tracked "
                                            f"{int(_rem_external)}sh but IB has 0 in both "
                                            f"directions. OCA bracket closed it externally; "
                                            f"bot record closed."
                                        ),
                                        "metadata": {
                                            "trade_id": _trade.id,
                                            "bot_direction": _dir,
                                            "bot_remaining_shares": int(_rem_external),
                                            "reason": "oca_closed_externally_v19_31",
                                            "sweep_path": "v19_31_oca_closed",
                                        },
                                    })
                                except Exception:
                                    pass
                                logger.warning(
                                    "[v19.31 EXTERNAL-CLOSE-SWEEP] %s %s tracked %dsh but "
                                    "IB has 0 in both directions — OCA likely closed it. "
                                    "Marking trade CLOSED, trade_id=%s",
                                    _trade.symbol, _dir.upper(),
                                    int(_rem_external), _trade.id,
                                )
                                continue  # done with this trade

                        # Original v19.27 phantom sweep: 0sh leftover
                        _rem = getattr(_trade, "remaining_shares", None)
                        if _rem is None or _rem != 0:
                            continue
                        _executed_at = getattr(_trade, "executed_at", None)
                        if _executed_at:
                            try:
                                if isinstance(_executed_at, str):
                                    from datetime import datetime as _dt
                                    _ea = _dt.fromisoformat(
                                        _executed_at.replace("Z", "+00:00")
                                    )
                                else:
                                    _ea = _executed_at
                                if _ea.tzinfo is None:
                                    from datetime import timezone as _tz
                                    _ea = _ea.replace(tzinfo=_tz.utc)
                                from datetime import datetime as _dt2, timezone as _tz2
                                age_s = (_dt2.now(_tz2.utc) - _ea).total_seconds()
                                if age_s < 30:
                                    continue
                            except Exception:
                                pass
                        if ib_pos_map.get((_sym_u, _dir), 0) > 0:
                            continue  # IB still has shares
                        # v19.31.12 — same fix as the v19.31 branch above:
                        # claim the IB realizedPNL onto the bot's row
                        # before marking closed. The 0sh-leftover case
                        # also frequently has bot.realized_pnl == $0
                        # because the scale-out path didn't accumulate
                        # for some legacy trades, and IB's realized is
                        # the only ground truth we have.
                        try:
                            ib_realized_for_sym_v27 = float(
                                ib_pos_map_realized.get((_sym_u, _dir), 0) or 0
                            )
                        except Exception:
                            ib_realized_for_sym_v27 = 0.0
                        # 0sh-leftover means no apportion needed —
                        # this trade is the only one being closed by
                        # this branch. Just claim whatever's there
                        # (only if bot's realized_pnl is still 0).
                        if (
                            ib_realized_for_sym_v27 != 0
                            and not getattr(_trade, "realized_pnl", 0)
                        ):
                            _trade.realized_pnl = round(ib_realized_for_sym_v27, 2)
                        _trade.status = _TS.CLOSED
                        _trade.close_reason = (
                            getattr(_trade, "close_reason", None)
                            or "phantom_auto_swept_v19_27"
                        )
                        if not getattr(_trade, "closed_at", None):
                            from datetime import datetime as _dt3, timezone as _tz3
                            _trade.closed_at = _dt3.now(_tz3.utc).isoformat()
                        try:
                            await asyncio.to_thread(bot._persist_trade, _trade)
                        except Exception:
                            pass
                        bot._open_trades.pop(_tid, None)
                        try:
                            bot._closed_trades.append(_trade)
                        except Exception:
                            pass
                        try:
                            from services.sentcom_service import emit_stream_event
                            await emit_stream_event({
                                "kind": "info",
                                "event": "phantom_v19_27_leftover_swept",
                                "symbol": _trade.symbol,
                                "text": (
                                    f"🧹 v19.27 leftover sweep: {_trade.symbol} "
                                    f"{_dir.upper()} (0sh leftover after scale-out) "
                                    f"— IB shows no shares, marking closed."
                                ),
                                "metadata": {
                                    "trade_id": _trade.id,
                                    "reason": "phantom_auto_swept_v19_27",
                                    "sweep_path": "v19_27_leftover",
                                },
                            })
                        except Exception:
                            pass
                        logger.info(
                            f"[v19.27 SWEEP] {_trade.symbol} {_dir.upper()} "
                            f"phantom (0sh, IB has 0) → status: closed, "
                            f"trade_id={_trade.id}"
                        )
                    except Exception as _sweep_err:
                        logger.debug(
                            f"v19.27 phantom-sweep error on {_tid}: {_sweep_err}"
                        )
        except Exception as _outer_sweep:
            logger.debug(f"v19.27 phantom-sweep block failed: {_outer_sweep}")

        for trade_id, trade in list(bot._open_trades.items()):
            try:
                quote = None
                quote_age_s = None

                # Try IB pushed data first
                try:
                    from routers.ib import get_pushed_quotes, is_pusher_connected
                    if is_pusher_connected():
                        quotes = get_pushed_quotes()
                        if trade.symbol in quotes:
                            q = quotes[trade.symbol]
                            # Compute quote age. `_pushed_at` (epoch
                            # seconds) is set by the pusher hook; if
                            # absent, treat as fresh (legacy quotes).
                            try:
                                pushed_at = q.get("_pushed_at") or q.get("ts") or q.get("timestamp")
                                if pushed_at:
                                    if isinstance(pushed_at, (int, float)):
                                        quote_age_s = max(0.0, time.time() - float(pushed_at))
                                    elif isinstance(pushed_at, str):
                                        from datetime import datetime as _dt, timezone as _tz
                                        # ISO fmt → epoch
                                        dt = _dt.fromisoformat(pushed_at.replace("Z", "+00:00"))
                                        if dt.tzinfo is None:
                                            dt = dt.replace(tzinfo=_tz.utc)
                                        quote_age_s = max(0.0, (_dt.now(_tz.utc) - dt).total_seconds())
                            except Exception:
                                quote_age_s = None  # treat as fresh on parse error

                            quote = {
                                'price': q.get('last') or q.get('close') or 0,
                                # 2026-04-30 v19.13 — capture bid/ask too so the
                                # stop-trigger logic can use the tradable side
                                # (long-exit fills at bid; short-exit at ask).
                                # Last-trade alone can be MISLEADING when spread
                                # is wide on thin stocks — last tick at $50.00
                                # but bid is $49.85 → a sale fills at the worse
                                # price than the trigger suggested.
                                'bid': q.get('bid'),
                                'ask': q.get('ask'),
                            }
                except Exception as e:
                    # v19.13 — was bare `except: pass`; that hid pusher
                    # outages silently. Log + carry on (Alpaca fallback
                    # still runs below).
                    logger.warning(
                        f"manage: pushed-quote lookup failed for {trade.symbol}: "
                        f"{type(e).__name__}: {e}",
                        exc_info=False,  # too noisy with full trace per tick
                    )

                # Fallback to Alpaca
                if not quote and bot._alpaca_service:
                    quote = await bot._alpaca_service.get_quote(trade.symbol)

                if not quote:
                    continue

                # v19.13 — staleness guard. Skip stop checks when quote
                # is stale; the IB-side bracket is still active server-
                # side and will fire on REAL-TIME prices.
                # v19.34.2 (2026-05-04) — also schedule a pusher re-
                # subscribe for the symbol so the bot recovers from the
                # blind spot on its own. Without this, a position whose
                # quote subscription rotates out can sit STALE forever
                # while the manage-loop logs the same warning every 60s.
                if quote_age_s is not None and quote_age_s > STALE_QUOTE_S:
                    if not getattr(trade, "_stale_quote_warned_at", None) \
                       or (time.time() - float(getattr(trade, "_stale_quote_warned_at", 0))) > 60:
                        logger.warning(
                            f"manage: SKIP stop-check for {trade.symbol} — quote "
                            f"is {quote_age_s:.1f}s old (cap {STALE_QUOTE_S}s). "
                            f"Server-side IB bracket still active. "
                            f"Requesting pusher re-subscribe to recover."
                        )
                        trade._stale_quote_warned_at = time.time()
                    if not hasattr(self, "_stale_resub_set"):
                        self._stale_resub_set = set()
                    self._stale_resub_set.add(trade.symbol.upper())
                    continue

                trade.current_price = quote.get('price', trade.current_price)

                # Initialize remaining_shares if not set
                if trade.remaining_shares == 0:
                    trade.remaining_shares = trade.shares
                    trade.original_shares = trade.shares

                # Initialize trailing stop config if not set
                if trade.trailing_stop_config.get('original_stop', 0) == 0:
                    trade.trailing_stop_config['original_stop'] = trade.stop_price
                    trade.trailing_stop_config['current_stop'] = trade.stop_price
                    trade.trailing_stop_config['mode'] = 'original'

                # 2026-04-30 v19.13 — UNSTOPPED-POSITION alarm. A trade
                # with `stop_price` falsy (None / 0) means our local
                # stop-hit check `current_price <= 0` is unreachable
                # for longs (and the symmetric path for shorts), so
                # the position is silently unstopped. Surface this
                # loudly — once per trade per 5 min — so the operator
                # can intervene. The IB bracket should still cover it
                # server-side, but we don't want this to pass quietly.
                if not trade.stop_price or trade.stop_price <= 0:
                    last_warn = getattr(trade, "_unstopped_warned_at", 0) or 0
                    if (time.time() - float(last_warn)) > 300:
                        logger.error(
                            f"manage: UNSTOPPED POSITION {trade.symbol} "
                            f"({trade.shares} sh, dir={trade.direction.value}, "
                            f"entry=${trade.fill_price:.2f}) — stop_price is "
                            f"{trade.stop_price!r}; local stop checks DISABLED. "
                            f"Verify the IB-side bracket is active or close manually."
                        )
                        trade._unstopped_warned_at = time.time()

                # Calculate unrealized P&L on remaining shares
                if trade.direction == TradeDirection.LONG:
                    trade.unrealized_pnl = (trade.current_price - trade.fill_price) * trade.remaining_shares
                else:
                    trade.unrealized_pnl = (trade.fill_price - trade.current_price) * trade.remaining_shares

                # === MFE/MAE TRACKING ===
                # Track from moment of fill for the full trade lifecycle
                if trade.fill_price and trade.fill_price > 0:
                    risk_per_share = abs(trade.fill_price - trade.stop_price) if trade.stop_price else trade.fill_price * 0.02
                    if risk_per_share == 0:
                        # 2026-04-30 v19.13 — fallback distorts R-multiples.
                        # Was silent; now warns ONCE per trade so the
                        # operator knows the R-track is approximate.
                        risk_per_share = trade.fill_price * 0.02  # Fallback: 2% of entry
                        if not getattr(trade, "_risk_fallback_warned", False):
                            logger.warning(
                                f"manage: {trade.symbol} fill_price={trade.fill_price} "
                                f"== stop_price={trade.stop_price}; using 2% fallback "
                                f"for R-multiple math (will distort R-tracking)."
                            )
                            trade._risk_fallback_warned = True

                    if trade.direction == TradeDirection.LONG:
                        # MFE: highest price since fill
                        if trade.current_price > trade.mfe_price or trade.mfe_price == 0:
                            trade.mfe_price = trade.current_price
                            trade.mfe_pct = ((trade.mfe_price - trade.fill_price) / trade.fill_price) * 100
                            trade.mfe_r = (trade.mfe_price - trade.fill_price) / risk_per_share
                        # MAE: lowest price since fill
                        if trade.current_price < trade.mae_price or trade.mae_price == 0:
                            trade.mae_price = trade.current_price
                            trade.mae_pct = ((trade.mae_price - trade.fill_price) / trade.fill_price) * 100
                            trade.mae_r = (trade.mae_price - trade.fill_price) / risk_per_share
                    else:  # SHORT
                        # MFE: lowest price since fill (favorable for shorts)
                        if trade.current_price < trade.mfe_price or trade.mfe_price == 0:
                            trade.mfe_price = trade.current_price
                            trade.mfe_pct = ((trade.fill_price - trade.mfe_price) / trade.fill_price) * 100
                            trade.mfe_r = (trade.fill_price - trade.mfe_price) / risk_per_share
                        # MAE: highest price since fill (adverse for shorts)
                        if trade.current_price > trade.mae_price or trade.mae_price == 0:
                            trade.mae_price = trade.current_price
                            trade.mae_pct = -((trade.mae_price - trade.fill_price) / trade.fill_price) * 100
                            trade.mae_r = -(trade.mae_price - trade.fill_price) / risk_per_share

                # Include realized P&L from partial exits
                total_value = trade.remaining_shares * trade.fill_price
                if total_value > 0:
                    trade.pnl_pct = ((trade.unrealized_pnl + trade.realized_pnl) / (trade.original_shares * trade.fill_price)) * 100

                # Update trailing stop if enabled
                if trade.trailing_stop_config.get('enabled', True):
                    await bot._update_trailing_stop(trade)

                # 2026-04-30 v19.13 — bid/ask-aware stop trigger.
                # Long position exits at the BID; short exits at the ASK.
                # Triggering on `last` can fire prematurely (last printed
                # below stop but bid actually still above) OR fire LATE
                # (last above stop but bid already deep below). Either
                # case mis-prices the operator's exit. Use the tradable
                # side; fall back to last if bid/ask not in feed.
                effective_stop = trade.trailing_stop_config.get('current_stop', trade.stop_price)
                trigger_price = trade.current_price  # last-trade default
                _bid = quote.get('bid')
                _ask = quote.get('ask')
                stop_hit = False
                if trade.direction == TradeDirection.LONG:
                    # Long exit fills at bid → that's the price we'd ACTUALLY
                    # get. Use it for the trigger when available + sane.
                    if _bid and _bid > 0:
                        trigger_price = float(_bid)
                    if trigger_price <= effective_stop:
                        stop_hit = True
                        logger.warning(
                            f"STOP HIT: {trade.symbol} {('bid' if _bid and _bid > 0 else 'last')} "
                            f"${trigger_price:.4f} <= stop ${effective_stop:.4f} "
                            f"(mode: {trade.trailing_stop_config.get('mode')})"
                        )
                else:  # SHORT
                    # Short exit fills at ask.
                    if _ask and _ask > 0:
                        trigger_price = float(_ask)
                    if trigger_price >= effective_stop:
                        stop_hit = True
                        logger.warning(
                            f"STOP HIT: {trade.symbol} {('ask' if _ask and _ask > 0 else 'last')} "
                            f"${trigger_price:.4f} >= stop ${effective_stop:.4f} "
                            f"(mode: {trade.trailing_stop_config.get('mode')})"
                        )

                if stop_hit:
                    stop_mode = trade.trailing_stop_config.get('mode', 'original')
                    reason = f"stop_loss_{stop_mode}" if stop_mode != 'original' else "stop_loss"
                    logger.info(f"Auto-closing {trade.symbol} due to {stop_mode} stop trigger")
                    await self.close_trade(trade_id, bot, reason=reason)
                    continue

                # v19.34.2 (2026-05-04) — Near-stop diagnostic. When a
                # position sits within 5c (or 0.25%) of its stop and
                # we're NOT firing the close, log a one-shot warning so
                # the operator can spot stuck-near-stop trades (the
                # VALE-at-1R class of issue) without scrolling the UI.
                # Throttled to once per 60s per trade so we don't spam.
                try:
                    distance_abs = abs(trigger_price - effective_stop)
                    distance_pct = (
                        (distance_abs / max(0.01, abs(trigger_price))) * 100.0
                    )
                    near_stop = distance_abs <= 0.05 or distance_pct <= 0.25
                    if near_stop:
                        last_warn = float(getattr(trade, "_near_stop_warned_at", 0) or 0)
                        if (time.time() - last_warn) >= 60.0:
                            trade._near_stop_warned_at = time.time()
                            side = "bid" if trade.direction == TradeDirection.LONG else "ask"
                            cmp_op = "<=" if trade.direction == TradeDirection.LONG else ">="
                            logger.warning(
                                f"[v19.34.2 NEAR-STOP] {trade.symbol} "
                                f"{trade.direction.value} {side}=${trigger_price:.4f} "
                                f"is {distance_abs:.4f} ({distance_pct:.3f}%) from stop "
                                f"${effective_stop:.4f}. Trigger condition "
                                f"`{side} {cmp_op} stop` not yet met — if this row "
                                f"stays open while distance stays ≤5c, investigate."
                            )
                except Exception:
                    pass

                # Automatic target profit-taking with scale-out
                if trade.target_prices and trade.scale_out_config.get('enabled', True):
                    await self.check_and_execute_scale_out(trade, bot)

                # 2026-04-30 v19.13 — throttle per-tick WS notifications.
                # With 25 open positions × ~1-2s loop = 12-25 WS msgs/sec
                # was overwhelming the V5 HUD. Now we only emit when:
                #   • first tick after open (no _last_notified_at yet)
                #   • >= 2s since last emit (heartbeat)
                #   • |unrealized P&L| moved by > 5% of entry-side risk
                #     (so the operator sees meaningful shifts in real-time)
                # State-change paths (scale_out, closed) emit unconditionally
                # via separate notify calls below.
                _now = time.time()
                _last_at = float(getattr(trade, "_last_notified_at", 0) or 0)
                _last_pnl = float(getattr(trade, "_last_notified_pnl", 0) or 0)
                _cur_pnl = float(getattr(trade, "unrealized_pnl", 0) or 0)
                _risk = max(1.0, abs(float(trade.risk_amount or 0)))
                _pnl_delta_pct = abs(_cur_pnl - _last_pnl) / _risk
                _due = (
                    _last_at == 0  # first tick
                    or (_now - _last_at) >= 2.0  # heartbeat
                    or _pnl_delta_pct >= 0.05  # 5% of risk
                )
                if _due:
                    trade._last_notified_at = _now
                    trade._last_notified_pnl = _cur_pnl
                    await bot._notify_trade_update(trade, "updated")

            except Exception as e:
                logger.exception(f"Error updating position {trade_id}: {type(e).__name__}: {e}")

        # v19.34.2 (2026-05-04) — End-of-loop: if any open trades had
        # stale quotes, ask the pusher to (re-)subscribe to those
        # symbols so the next manage cycle has fresh data. Throttled
        # to one RPC per 60s to avoid hammering the pusher when many
        # symbols go stale in lockstep (e.g. pusher reconnect storm).
        try:
            stale_set = getattr(self, "_stale_resub_set", None)
            if stale_set:
                last_resub = float(getattr(self, "_last_stale_resub_at", 0) or 0)
                if (time.time() - last_resub) >= 60.0:
                    self._last_stale_resub_at = time.time()
                    self._stale_resub_set = set()  # consume
                    try:
                        from services.ib_pusher_rpc import get_pusher_rpc_client
                        rpc = get_pusher_rpc_client()
                        if rpc.is_configured():
                            # v19.34.8 (2026-05-05) — wrap sync pusher RPC in
                            # asyncio.to_thread to prevent event-loop wedge.
                            # `subscribe_symbols` blocks on socket I/O until
                            # the pusher acks; called inline from async on
                            # every manage-loop tick = compounded stall risk.
                            res = await asyncio.to_thread(rpc.subscribe_symbols, stale_set)
                            logger.info(
                                f"[v19.34.2 STALE-RESUB] requested re-subscribe for "
                                f"{len(stale_set)} symbol(s): "
                                f"{sorted(stale_set)[:8]}"
                                f"{'…' if len(stale_set) > 8 else ''} "
                                f"→ added={(res or {}).get('added')!r}"
                            )
                        else:
                            logger.debug("[v19.34.2 STALE-RESUB] pusher RPC not configured")
                    except Exception as e:
                        logger.warning(f"[v19.34.2 STALE-RESUB] dispatch failed: {e}")
                else:
                    # Throttled — keep accumulating; next eligible cycle
                    # will resub the union.
                    pass
        except Exception as _e:
            logger.debug(f"[v19.34.2 STALE-RESUB] post-loop handler swallowed: {_e}")


    # ─── v19.34 (2026-05-04) — Mid-bar tick stop-eval ─────────────────
    async def evaluate_single_trade_against_quote(
        self, trade: 'BotTrade', bot: 'TradingBotService',
        quote: Dict,
    ) -> Optional[str]:
        """v19.34 — Re-evaluate a single trade's stop trigger against a
        fresh L1 tick. Called by the per-trade quote_tick_bus subscriber
        (see `_subscribe_trade_to_tick_bus` below). Mirrors the stop
        logic in `update_open_positions` but operates on ONE trade with
        a SINGLE quote so it can run per-tick (50ms cadence) instead
        of per manage-loop cycle (~5-15s cadence).

        Returns the close reason if the close was actually executed,
        `None` if no action was needed. Defensive: any exception is
        logged and swallowed so a malformed tick can't kill the
        subscriber task.

        IMPORTANT: this method intentionally does NOT trail stops or
        scale out. Both decisions need broader context (recent bars,
        ATR) and should stay on the per-cycle path. We ONLY check the
        existing stop level against the new quote — that's the cheapest
        and highest-value mid-bar action.
        """
        from services.trading_bot_service import TradeDirection, TradeStatus
        try:
            if trade is None or trade.status != TradeStatus.OPEN:
                return None
            if not getattr(trade, "stop_price", None) or trade.stop_price <= 0:
                # No local stop level → server-side bracket is the only
                # protection; nothing to do mid-bar.
                return None

            effective_stop = (
                getattr(trade, "trailing_stop_config", {}).get("current_stop")
                or trade.stop_price
            )

            # Mirror the bid/ask-aware trigger logic in update_open_positions.
            _bid = quote.get("bid")
            _ask = quote.get("ask")
            _last = quote.get("last") or quote.get("price")

            stop_hit = False
            trigger_price: Optional[float] = None
            if trade.direction == TradeDirection.LONG:
                if _bid and float(_bid) > 0:
                    trigger_price = float(_bid)
                elif _last and float(_last) > 0:
                    trigger_price = float(_last)
                if trigger_price is not None and trigger_price <= effective_stop:
                    stop_hit = True
            else:  # SHORT
                if _ask and float(_ask) > 0:
                    trigger_price = float(_ask)
                elif _last and float(_last) > 0:
                    trigger_price = float(_last)
                if trigger_price is not None and trigger_price >= effective_stop:
                    stop_hit = True

            if not stop_hit:
                return None

            mode = getattr(trade, "trailing_stop_config", {}).get("mode", "original")
            reason = (
                f"stop_loss_{mode}_mid_bar_v19_34"
                if mode != "original"
                else "stop_loss_mid_bar_v19_34"
            )

            logger.warning(
                f"[v19.34 MID-BAR STOP] {trade.symbol} {trade.direction.value} "
                f"trigger=${trigger_price:.4f} <= stop=${effective_stop:.4f} "
                f"(mode={mode}); firing close NOW (saved ~next-cycle latency)"
            )
            ok = await self.close_trade(trade.id, bot, reason=reason)
            return reason if ok else None
        except Exception as e:
            # Log but never propagate — the subscriber task must keep
            # running so subsequent ticks still get evaluated.
            logger.warning(
                f"[v19.34 MID-BAR STOP] eval failed for "
                f"{getattr(trade, 'symbol', '?')}: {e}"
            )
            return None

    async def check_eod_close(self, bot: 'TradingBotService'):
        """
        Close ALL open positions near market close (default: 3:55 PM ET).
        This is a critical risk management feature to avoid overnight exposure.

        ONLY closes intraday trades (those flagged `close_at_eod=True`).
        Swing and position trades are explicitly held overnight.

        2026-04-30 v19.14 — multiple hardenings:
          P0 #1 — `close_trade` returns a bool, not a dict. The legacy
                  `result.get("success")` call was silently AttributeError-ing
                  every iteration → all EOD closes counted as failures even
                  on success. Now we treat the bool correctly.
          P0 #2 — closes run in PARALLEL via `asyncio.gather`. With 25 open
                  intraday positions and ~2s/close (IB roundtrip + snapshot),
                  serial took ~50s — risked spilling past market close. Now
                  ~3-5s regardless of position count.
          P0 #3 — `_eod_close_executed_today` only sets True when ALL closes
                  succeed. If any failed, we leave it False so the next
                  manage-loop tick (every ~1-2s) retries.
          P0 #4 — Loud ERROR alarm + WS notify if positions are still open
                  at/after 4:00 PM ET.
          P1 #5 — Half-trading-day detection via env `EOD_HALF_DAY_TODAY=true`
                  shifts the close window to 12:55 PM ET. A future contributor
                  can wire this to a real exchange calendar; for now it's
                  operator-flagged the morning of (cheap, explicit, safe).
          P1 #6 — WS-broadcast EOD start + completion so the V5 HUD can
                  surface a banner during the close window.
        """
        if not bot._eod_close_enabled:
            return

        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo

        now_et = datetime.now(ZoneInfo("America/New_York"))
        today_str = now_et.strftime("%Y-%m-%d")

        # Reset the executed flag if it's a new day
        if bot._last_eod_check_date != today_str:
            bot._eod_close_executed_today = False
            bot._last_eod_check_date = today_str

        # Skip if already executed today (and ALL closes succeeded — see P0 #3)
        if bot._eod_close_executed_today:
            return

        # Only run on weekdays during market hours
        if now_et.weekday() >= 5:
            return

        # P1 #5 — half-trading-day detection. Operator sets
        # `EOD_HALF_DAY_TODAY=true` in env on the morning of half-days
        # (Black Friday, Christmas Eve, day after Thanksgiving). Default
        # close window stays 3:55 PM. On half-days we flip to 12:55 PM
        # (5 min before 1:00 PM half-day close). NYSE half-day calendar
        # is rare enough that operator-flagging is acceptable for now.
        import os as _os
        is_half_day = _os.environ.get("EOD_HALF_DAY_TODAY", "").lower() in ("true", "1", "yes")
        if is_half_day:
            eod_hour, eod_minute, market_close_hour = 12, 55, 13
        else:
            eod_hour = bot._eod_close_hour
            eod_minute = bot._eod_close_minute
            market_close_hour = 16

        # Not yet time to close
        if now_et.hour < eod_hour or (now_et.hour == eod_hour and now_et.minute < eod_minute):
            return

        # P0 #4 — past market close with positions still open is an EMERGENCY.
        # Surface loudly via log + WS notify; do NOT silently skip.
        if now_et.hour >= market_close_hour:
            open_count = len(bot._open_trades)
            if open_count > 0 and not bot._eod_close_executed_today:
                last_alarm = getattr(bot, "_eod_after_close_alarmed_at", None)
                if not last_alarm or last_alarm != today_str:
                    logger.error(
                        f"🚨 EOD ALARM: market closed at {market_close_hour}:00 ET but "
                        f"{open_count} positions still OPEN locally. Verify IB-side "
                        f"position state — they may have been auto-flat'd by IB or "
                        f"may be carrying overnight."
                    )
                    bot._eod_after_close_alarmed_at = today_str
                    try:
                        await bot._broadcast_event({
                            "type": "eod_after_close_alarm",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "open_positions": open_count,
                            "et_clock": now_et.strftime("%H:%M:%S"),
                        })
                    except Exception:
                        pass
            return

        # Time to close intraday positions!
        open_count = len(bot._open_trades)
        if open_count == 0:
            bot._eod_close_executed_today = True
            return

        # Only close trades marked for EOD close (intraday/scalp/day trades)
        # Swing and position trades are held overnight
        eod_trades = {
            tid: t for tid, t in bot._open_trades.items()
            if getattr(t, 'close_at_eod', True)  # Default True for safety
        }

        if not eod_trades:
            logger.info(f"🔔 EOD CHECK: {open_count} open trades, all are swing/position — no EOD close needed")
            bot._eod_close_executed_today = True
            return

        logger.info(
            f"🔔 EOD AUTO-CLOSE: Closing {len(eod_trades)} intraday trades at "
            f"{now_et.strftime('%H:%M:%S')} ET (keeping {open_count - len(eod_trades)} "
            f"swing/position trades){'  [HALF-DAY MODE]' if is_half_day else ''}"
        )

        # P1 #6 — WS notify: EOD start. V5 HUD can render a banner.
        try:
            await bot._broadcast_event({
                "type": "eod_close_started",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "positions_to_close": len(eod_trades),
                "is_half_day": is_half_day,
                "eod_window_et": f"{eod_hour:02d}:{eod_minute:02d}",
            })
        except Exception as e:
            logger.warning(f"EOD WS notify (start) failed: {e}")

        # P0 #2 — close all eligible trades CONCURRENTLY. Caps at 25 in flight
        # (matches max_open_positions); even with IB-side serialization on
        # the order queue, the AWAITS happen in parallel so the total
        # latency stays bounded by single-trade latency, not N × latency.
        async def _close_one(tid_trade):
            tid, trade = tid_trade
            try:
                logger.info(f"  📤 EOD CLOSE: {trade.symbol} - {trade.direction.value} {trade.remaining_shares} shares")
                # P0 #1 — close_trade returns a BOOL, not a dict. Treat the
                # bool correctly; capture realized_pnl from the trade object
                # post-close (close_trade mutates trade.realized_pnl).
                ok = await self.close_trade(tid, bot, reason="eod_auto_close")
                if ok:
                    return ("ok", trade.realized_pnl)
                return ("fail", trade.symbol)
            except Exception as e:
                logger.exception(
                    f"  ❌ EOD close raised for {trade.symbol}: {type(e).__name__}: {e}"
                )
                return ("fail", trade.symbol)

        results = await asyncio.gather(*(_close_one(p) for p in eod_trades.items()))
        closed_count = sum(1 for r in results if r[0] == "ok")
        total_pnl = sum(r[1] for r in results if r[0] == "ok")
        failed_symbols = [r[1] for r in results if r[0] == "fail"]

        # P0 #3 — only mark executed if EVERY close succeeded. If any
        # failed, leave the flag False so next tick retries — manage loop
        # ticks ~every 1-2s, plenty of time before market close.
        if not failed_symbols:
            bot._eod_close_executed_today = True
        else:
            logger.error(
                f"⚠️ EOD: {len(failed_symbols)} of {len(eod_trades)} closes "
                f"FAILED ({', '.join(failed_symbols)}). Will retry on next "
                f"manage-loop tick. Symbols still open at IB until success."
            )
            # ── v19.29 (2026-05-01) — EOD flatten escalation alarm ───
            # Operator caught 3:59pm flatten cancellations on
            # 2026-05-01 (SOFI 1636 / BP 450 / BP 315 all cancelled,
            # left raw long overnight). Surface a CRITICAL Unified
            # Stream event so operator sees the failure in real time
            # in the V5 banner — the existing logger.error went to
            # backend logs only.
            try:
                from services.sentcom_service import emit_stream_event
                # Compute minutes remaining to RTH close so the alarm
                # severity reflects urgency.
                from datetime import datetime as _dt_eod
                try:
                    from zoneinfo import ZoneInfo as _ZI
                    et_now = _dt_eod.now(_ZI("America/New_York"))
                    et_minutes = et_now.hour * 60 + et_now.minute
                    minutes_to_close = max(0, (16 * 60) - et_minutes)
                except Exception:
                    minutes_to_close = -1
                severity = (
                    "CRITICAL" if minutes_to_close <= 2
                    else "HIGH" if minutes_to_close <= 5
                    else "WARNING"
                )
                await emit_stream_event({
                    "kind": "alarm",
                    "event": "eod_flatten_failed",
                    "symbol": failed_symbols[0] if len(failed_symbols) == 1 else None,
                    "text": (
                        f"🚨 [{severity}] EOD FLATTEN FAILED — "
                        f"{len(failed_symbols)} of {len(eod_trades)} closes "
                        f"didn't fill ({', '.join(failed_symbols[:5])}"
                        f"{'…' if len(failed_symbols) > 5 else ''}). "
                        f"{minutes_to_close}min to close. "
                        f"USE 'CLOSE ALL NOW' BUTTON OR FLATTEN IN TWS."
                    ),
                    "metadata": {
                        "failed_symbols": failed_symbols,
                        "total_attempted": len(eod_trades),
                        "minutes_to_close": minutes_to_close,
                        "severity": severity,
                        "retry_will_continue": True,
                    },
                })
            except Exception as alarm_err:
                logger.warning(f"v19.29 EOD alarm emit failed: {alarm_err}")

        # P1 #6 — WS notify: EOD complete (or partial)
        try:
            await bot._broadcast_event({
                "type": "eod_close_completed",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "closed": closed_count,
                "failed": len(failed_symbols),
                "failed_symbols": failed_symbols,
                "total_pnl": total_pnl,
                "fully_done": not failed_symbols,
            })
        except Exception as e:
            logger.warning(f"EOD WS notify (complete) failed: {e}")

        # Persist the EOD close event
        if bot._db:
            eod_event = {
                "event_type": "eod_auto_close",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "date": today_str,
                "positions_closed": closed_count,
                "positions_failed": len(failed_symbols),
                "failed_symbols": failed_symbols,
                "total_pnl": total_pnl,
                "is_half_day": is_half_day,
                "close_time_et": now_et.strftime("%H:%M:%S"),
            }
            await asyncio.to_thread(bot._db.bot_events.insert_one, eod_event)

        if failed_symbols:
            logger.warning(f"⚠️ EOD AUTO-CLOSE PARTIAL: Closed {closed_count}, FAILED {len(failed_symbols)} ({', '.join(failed_symbols)}), Total P&L: ${total_pnl:+,.2f}")
        else:
            logger.info(f"✅ EOD AUTO-CLOSE COMPLETE: Closed {closed_count} positions, Total P&L: ${total_pnl:+,.2f}")

    async def check_and_execute_scale_out(self, trade: 'BotTrade', bot: 'TradingBotService'):
        """
        Check if any target prices are hit and execute scale-out sells.
        Sells 1/3 at Target 1, 1/3 at Target 2, keeps 1/3 for Target 3 (runner).
        """
        from services.trading_bot_service import TradeDirection, TradeStatus

        if not trade.target_prices or trade.remaining_shares <= 0:
            return

        targets_hit = trade.scale_out_config.get('targets_hit', [])
        scale_out_pcts = trade.scale_out_config.get('scale_out_pcts', [0.33, 0.33, 0.34])

        for i, target in enumerate(trade.target_prices):
            if i in targets_hit:
                continue  # Already sold at this target

            # Check if target is hit
            target_hit = False
            if trade.direction == TradeDirection.LONG:
                if trade.current_price >= target:
                    target_hit = True
            else:  # SHORT
                if trade.current_price <= target:
                    target_hit = True

            if target_hit:
                # Calculate shares to sell at this target
                pct_to_sell = scale_out_pcts[i] if i < len(scale_out_pcts) else 0.34

                # For last target, sell all remaining
                if i == len(trade.target_prices) - 1:
                    shares_to_sell = trade.remaining_shares
                else:
                    shares_to_sell = max(1, int(trade.original_shares * pct_to_sell))
                    shares_to_sell = min(shares_to_sell, trade.remaining_shares)

                if shares_to_sell <= 0:
                    continue

                logger.info(f"TARGET {i+1} HIT: {trade.symbol} - Scaling out {shares_to_sell} shares at ${trade.current_price:.2f}")

                # Execute partial exit
                exit_result = await self.execute_partial_exit(trade, shares_to_sell, target, i, bot)

                if exit_result.get('success'):
                    fill_price = exit_result.get('fill_price', trade.current_price)

                    # Calculate P&L for this scale-out
                    if trade.direction == TradeDirection.LONG:
                        partial_pnl = (fill_price - trade.fill_price) * shares_to_sell
                    else:
                        partial_pnl = (trade.fill_price - fill_price) * shares_to_sell

                    # Update trade state
                    trade.remaining_shares -= shares_to_sell
                    trade.realized_pnl += partial_pnl

                    # Track commission for partial exit
                    scale_commission = bot._apply_commission(trade, shares_to_sell)

                    targets_hit.append(i)
                    trade.scale_out_config['targets_hit'] = targets_hit

                    # Record the partial exit
                    partial_exit_record = {
                        'target_idx': i + 1,
                        'target_price': target,
                        'shares_sold': shares_to_sell,
                        'fill_price': fill_price,
                        'pnl': partial_pnl,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }
                    trade.scale_out_config.setdefault('partial_exits', []).append(partial_exit_record)

                    logger.info(f"Scale-out complete: {trade.symbol} T{i+1} - Sold {shares_to_sell} @ ${fill_price:.2f}, P&L: ${partial_pnl:.2f}, Remaining: {trade.remaining_shares}")

                    await bot._notify_trade_update(trade, f"scale_out_t{i+1}")

                    # 2026-05-05 v19.34.7 — Bracket re-issue after scale-out.
                    # Operator-filed bug: bot was firing a SEPARATE LMT to
                    # exit `shares_to_sell` shares, but the original OCA
                    # bracket's stop was still sized for the FULL position.
                    # If price reversed and the stop fired, IB sold the
                    # original qty, taking the position to a negative
                    # (short) qty. Forensic evidence: 2026-05-04 STX -17sh
                    # phantom from this exact pattern. Cancel the old
                    # stale legs and re-issue with the reduced qty so the
                    # protective stop covers ONLY the remaining shares.
                    # Skipped when fully closing — re-issue is pointless.
                    if (
                        trade.remaining_shares > 0
                        and os.environ.get("BRACKET_REISSUE_AUTO_ENABLED", "true").lower()
                        in ("true", "1", "yes", "on")
                    ):
                        try:
                            from services.bracket_reissue_service import (
                                reissue_bracket_for_trade,
                            )
                            reissue_result = await reissue_bracket_for_trade(
                                trade=trade,
                                bot=bot,
                                reason=f"scale_out_t{i + 1}",
                                new_total_shares=trade.shares,
                                already_executed_shares=int(trade.shares - trade.remaining_shares),
                                new_avg_entry=trade.fill_price,
                                preserve_target_levels=True,
                            )
                            if not reissue_result.get("success"):
                                logger.warning(
                                    "[v19.34.7] post-scale-out bracket re-issue "
                                    "failed for %s (phase=%s, error=%s) — old "
                                    "legs may still be active at IB",
                                    trade.symbol,
                                    reissue_result.get("phase"),
                                    reissue_result.get("error"),
                                )
                        except Exception as _reissue_err:
                            logger.exception(
                                "[v19.34.7] bracket re-issue raised after scale-out "
                                "for %s — manage-loop will retry on next tick: %s",
                                trade.symbol, _reissue_err,
                            )

                    # If all shares sold, close the trade
                    if trade.remaining_shares <= 0:
                        trade.status = TradeStatus.CLOSED
                        trade.closed_at = datetime.now(timezone.utc).isoformat()
                        trade.close_reason = f"target_{i+1}_complete"
                        trade.exit_price = fill_price
                        trade.unrealized_pnl = 0

                        # Update daily stats with net P&L (after commissions)
                        if trade.net_pnl > 0:
                            bot._daily_stats.trades_won += 1
                            bot._daily_stats.largest_win = max(bot._daily_stats.largest_win, trade.net_pnl)
                        else:
                            bot._daily_stats.trades_lost += 1
                            bot._daily_stats.largest_loss = min(bot._daily_stats.largest_loss, trade.net_pnl)

                        bot._daily_stats.net_pnl += trade.net_pnl
                        total = bot._daily_stats.trades_won + bot._daily_stats.trades_lost
                        bot._daily_stats.win_rate = (bot._daily_stats.trades_won / total * 100) if total > 0 else 0

                        # Move to closed trades
                        del bot._open_trades[trade.id]
                        bot._closed_trades.append(trade)

                        # v19.13 — release stop-manager per-trade state
                        try:
                            if hasattr(bot, '_stop_manager') and bot._stop_manager \
                                    and hasattr(bot._stop_manager, 'forget_trade'):
                                bot._stop_manager.forget_trade(trade.id)
                        except Exception as e:
                            logger.warning(f"scale-out: stop_manager.forget_trade failed: {e}")

                        await bot._notify_trade_update(trade, "closed")
                        await bot._save_trade(trade)

                        # Log to regime performance tracking
                        await bot._log_trade_to_regime_performance(trade)

                        logger.info(f"Trade fully closed at Target {i+1}: {trade.symbol} Total P&L: ${trade.realized_pnl:.2f}")
                        return
                else:
                    # 2026-04-30 v19.13 — partial exit explicitly failed
                    # at the broker. Local state has NOT been mutated
                    # (per the new contract); log loudly + record a
                    # trade-drop so the operator sees it. Manage loop
                    # will retry on the next pass when target is still
                    # hit.
                    err = exit_result.get('error', 'unknown partial-exit failure')
                    logger.error(
                        f"Scale-out FAILED for {trade.symbol} T{i+1}: {err}. "
                        f"Position state unchanged; will retry next manage cycle."
                    )
                    try:
                        from services.trade_drop_recorder import record_trade_drop
                        record_trade_drop(
                            trade,
                            gate="execution_exception",
                            context={
                                "phase": "scale_out",
                                "target_idx": i + 1,
                                "target_price": target,
                                "shares_to_sell": shares_to_sell,
                                "error": str(err),
                            },
                        )
                    except Exception as drop_err:
                        logger.warning(f"scale-out: failed to record drop: {drop_err}")

    async def execute_partial_exit(self, trade: 'BotTrade', shares: int, target_price: float, target_idx: int, bot: 'TradingBotService') -> Dict:
        """Execute a partial position exit (scale-out).

        2026-04-30 v19.13 — was silently faking `simulated: True` on
        broker exceptions, which decremented `remaining_shares` locally
        but left those shares OPEN at the broker → silent position
        drift. Now exceptions / executor failures propagate as
        `{success: False, error: ...}` so the caller can skip the local
        state mutation. Simulated paths (no executor configured) still
        return `simulated: True` cleanly because that IS legitimate
        paper-trading behaviour.
        """
        if not bot._trade_executor:
            # Legitimate simulated exit — no executor wired (paper-paper mode).
            return {
                'success': True,
                'fill_price': trade.current_price,
                'shares': shares,
                'simulated': True
            }

        try:
            result = await bot._trade_executor.execute_partial_exit(trade, shares)
            # Trust the executor's own success flag — don't paper over a
            # `success: False` from the broker.
            return result
        except Exception as e:
            logger.exception(
                f"Partial exit raised for {trade.symbol} (target {target_idx + 1}, "
                f"{shares} shares): {type(e).__name__}: {e}"
            )
            # PROPAGATE failure. Caller (check_and_execute_scale_out) must
            # not decrement remaining_shares or mark the target as hit.
            return {
                'success': False,
                'error': f'{type(e).__name__}: {e}',
                'fill_price': None,
                'shares': 0,
                'symbol': trade.symbol,
                'target_idx': target_idx,
            }

    async def _clamp_shares_to_ib_position(
        self,
        trade,
        intended_shares: int,
        *,
        reason: str = "manual",
    ) -> int:
        """v19.34.27 — return min(intended_shares, |IB position for symbol|).

        Queries the direct IB API service for the live, authoritative
        position on `trade.symbol`. If IB shows fewer shares than the
        bot's tracked count (phantom shares), returns the IB number so
        the close MKT can't oversell.

        Behaviour matrix:
          - Direct IB unavailable / not connected   → return intended (no clamp)
          - Symbol not in IB positions               → return 0 (entire position is phantom)
          - IB shares ≥ intended                     → return intended (no clamp needed)
          - IB shares <  intended                    → return IB shares (CLAMPED)
          - Direction mismatch (long bot vs short IB)→ return 0 (refuse, log loud)

        The "fewer shares than tracked" case is the BMNR scenario; the
        "direction mismatch" case is the v19.34.15a `[REJECTED: Bracket
        unknown]` race fingerprint where the bot believes it's long
        but IB has flipped or zeroed the position.

        Direction is signed in IB's API: positive = long, negative =
        short. We compare on absolute value but log if the sign
        disagrees with the bot's tracked direction so the operator can
        see the divergence.
        """
        try:
            from services.ib_direct_service import get_ib_direct_service
        except Exception:
            return intended_shares

        svc = get_ib_direct_service()
        if not (svc.is_available() and svc.is_connected()):
            # Direct socket isn't up — can't clamp. Caller falls back
            # to the bot's tracked count, which is the pre-v19.34.27
            # behaviour.
            return intended_shares

        try:
            positions = await svc.get_positions()
        except Exception as e:
            logger.debug(
                f"_clamp_shares_to_ib_position: get_positions failed for "
                f"{trade.symbol} ({e}); returning intended {intended_shares}"
            )
            return intended_shares

        # Find the symbol's signed position (sum across accounts is fine
        # — operator runs single-account so this is always 1 row).
        ib_signed = 0.0
        for p in positions or []:
            if (p.get("symbol") or "").upper() == trade.symbol.upper():
                ib_signed += float(p.get("position") or 0)

        ib_abs = int(abs(round(ib_signed)))
        # Direction sign check: -1 short, +1 long, 0 flat.
        ib_sign = 0 if ib_abs == 0 else (1 if ib_signed > 0 else -1)
        try:
            from services.trading_bot_service import TradeDirection
            bot_sign = 1 if trade.direction == TradeDirection.LONG else -1
        except Exception:
            bot_sign = 1 if str(getattr(trade.direction, "value", trade.direction)).lower() == "long" else -1

        if ib_abs == 0:
            logger.warning(
                f"[v19.34.27 PHANTOM] {trade.symbol} close_trade(reason={reason}) "
                f"clamped {intended_shares}→0: IB shows ZERO position. Trade "
                f"{trade.id} will be marked CLOSED locally without broker call."
            )
            return 0

        if ib_sign != bot_sign:
            # Direction mismatch — bot thinks long, IB has short (or
            # vice versa). Refuse the close: firing a market sell on a
            # short position would actually OPEN more short. Operator
            # must reconcile manually.
            logger.error(
                f"[v19.34.27 PHANTOM] {trade.symbol} close_trade(reason={reason}) "
                f"REFUSING to fire — direction mismatch: bot tracks "
                f"{('long' if bot_sign > 0 else 'short')} {intended_shares}sh, "
                f"IB has {('long' if ib_sign > 0 else 'short')} {ib_abs}sh. "
                f"Trade {trade.id} will be marked CLOSED locally; operator "
                f"must reconcile the IB-side residual manually."
            )
            return 0

        if ib_abs >= intended_shares:
            return intended_shares

        # IB has fewer shares than tracked — clamp.
        logger.warning(
            f"[v19.34.27 PHANTOM] {trade.symbol} close_trade(reason={reason}) "
            f"clamped {intended_shares}→{ib_abs}: bot tracked "
            f"{intended_shares}sh, IB authoritative position is {ib_abs}sh "
            f"({ib_signed:+.0f} signed). Closing only what IB actually holds."
        )
        return ib_abs


    async def close_trade(self, trade_id: str, bot: 'TradingBotService', reason: str = "manual"):
        """Close an open trade (sells remaining shares).

        2026-04-30 v19.13 — pre-fix, an executor failure (broker
        rejection, IB pusher offline, timeout, etc.) was silently
        ignored: we'd still mark the trade CLOSED locally with
        `exit_price = current_price`. Books say closed; broker still
        has the position open. Now an executor `success: False` causes
        a hard return — the trade stays OPEN locally so the manage
        loop can retry on the next pass and the operator can see the
        failure in the trade-drops feed.

        2026-02-XX v19.34.27 — Phantom-share-aware close. Pre-fix this
        method fired a market close blindly using the bot's tracked
        share count. When the bot's `remaining_shares` was inflated
        relative to IB's authoritative position (e.g., the operator
        manually closed a partial in TWS, or the v19.34.15a/b
        reconciler spawned a phantom excess slice that didn't exist on
        IB), the close MKT would oversell — flipping a long → short
        (or short → long) by the phantom amount. Today's BMNR scenario
        (bot 5,472 vs IB 1,905) would have netted -3,567 shares short
        on the operator's account if any position-manager close path
        had triggered before reconciliation caught up.

        Fix: query the direct IB API for the live position before
        firing the close MKT and cap `shares_to_close` at
        `min(internal_remaining, ib_actual_abs)`. If the direct socket
        isn't connected we fall back to the bot's tracked count (safer
        than blocking — the manage loop must always be able to close).
        Same-symbol multi-trade fan-out is conservative: the cap is
        applied per close call, so two trades trying to close the same
        ticker can't oversell IB's actual position even if invoked
        back-to-back.
        """
        from services.trading_bot_service import TradeDirection, TradeStatus

        if trade_id not in bot._open_trades:
            return False

        trade = bot._open_trades[trade_id]

        # Use remaining shares if we've done partial exits, otherwise use original shares
        shares_to_close = trade.remaining_shares if trade.remaining_shares > 0 else trade.shares

        # ── v19.34.27 phantom-share clamp ─────────────────────────
        # Best-effort cross-check against IB's authoritative position.
        # Failures here NEVER block the close — they just leave the
        # bot's tracked count as the cap, which is the pre-v19.34.27
        # behavior.
        try:
            shares_to_close = await self._clamp_shares_to_ib_position(
                trade, shares_to_close, reason=reason
            )
        except Exception as clamp_err:
            logger.debug(
                f"close_trade: phantom-share clamp errored for {trade.symbol} "
                f"({clamp_err}); using bot-tracked count {shares_to_close}"
            )

        # If the clamp dropped the close to zero (IB shows zero
        # position for this symbol — i.e., the entire position is a
        # phantom), there's nothing to close at the broker. Mark the
        # trade closed locally at current_price and return True so the
        # manage loop stops retrying. This is the "phantom recovery"
        # path the operator hit during the BMNR reconciliation today.
        if shares_to_close == 0:
            logger.warning(
                f"close_trade: {trade.symbol} clamped to 0 shares — IB shows "
                f"no position. Marking trade {trade_id} CLOSED locally "
                f"(reason={reason}) without broker call."
            )
            trade.exit_price = trade.current_price
            trade.status = TradeStatus.CLOSED
            trade.closed_at = datetime.now(timezone.utc).isoformat()
            trade.close_reason = f"{reason}_phantom_recovery_v19_34_27"
            trade.unrealized_pnl = 0
            trade.remaining_shares = 0
            del bot._open_trades[trade_id]
            bot._closed_trades.append(trade)
            try:
                await bot._save_trade(trade)
            except Exception as e:
                logger.warning(f"close_trade phantom-recovery save failed: {e}")
            return True

        try:
            executor_failed = False
            if bot._trade_executor and shares_to_close > 0:
                # Update trade.shares temporarily for the executor
                original_shares = trade.shares
                trade.shares = shares_to_close

                result = await bot._trade_executor.close_position(trade)

                trade.shares = original_shares  # Restore

                if result.get('success'):
                    trade.exit_price = result.get('fill_price', trade.current_price)
                else:
                    # v19.13 — broker rejected / timed out the close.
                    # Do NOT mark CLOSED. Log + record a trade-drop so
                    # the operator sees this in the diagnostic feed,
                    # then return False so the caller knows nothing
                    # changed at the broker.
                    err = result.get('error', 'unknown executor failure')
                    logger.error(
                        f"close_trade: executor refused close for {trade.symbol} "
                        f"({shares_to_close} shares, reason={reason}): {err}"
                    )
                    try:
                        from services.trade_drop_recorder import record_trade_drop
                        record_trade_drop(
                            trade,
                            gate="execution_exception",
                            context={
                                "phase": "close",
                                "reason": reason,
                                "error": str(err),
                                "shares_to_close": shares_to_close,
                            },
                        )
                    except Exception as drop_err:
                        logger.warning(f"close_trade: failed to record drop: {drop_err}")
                    executor_failed = True
            else:
                trade.exit_price = trade.current_price

            if executor_failed:
                # Trade stays OPEN. Manage loop will retry on next pass.
                return False

            # Calculate realized P&L for remaining shares and add to cumulative
            if shares_to_close > 0:
                if trade.direction == TradeDirection.LONG:
                    final_pnl = (trade.exit_price - trade.fill_price) * shares_to_close
                else:
                    final_pnl = (trade.fill_price - trade.exit_price) * shares_to_close
                trade.realized_pnl += final_pnl

                # Track exit commission
                exit_commission = bot._apply_commission(trade, shares_to_close)
                logger.info(f"Exit commission: ${exit_commission:.2f} | Total commissions: ${trade.total_commissions:.2f} | Net P&L: ${trade.net_pnl:.2f}")

            trade.status = TradeStatus.CLOSED
            trade.closed_at = datetime.now(timezone.utc).isoformat()
            trade.close_reason = reason
            trade.unrealized_pnl = 0
            trade.remaining_shares = 0

            # Update daily stats with net P&L (after commissions)
            bot._daily_stats.net_pnl += trade.net_pnl
            if trade.realized_pnl > 0:
                bot._daily_stats.trades_won += 1
                bot._daily_stats.largest_win = max(bot._daily_stats.largest_win, trade.realized_pnl)
            else:
                bot._daily_stats.trades_lost += 1
                bot._daily_stats.largest_loss = min(bot._daily_stats.largest_loss, trade.realized_pnl)

            # Calculate win rate
            total = bot._daily_stats.trades_won + bot._daily_stats.trades_lost
            bot._daily_stats.win_rate = (bot._daily_stats.trades_won / total * 100) if total > 0 else 0

            # Move to closed trades
            del bot._open_trades[trade_id]
            bot._closed_trades.append(trade)

            # 2026-04-30 v19.13 — release internal stop-manager state
            # for this trade id (small mem-leak fix; was accumulating
            # closed-trade ids in `_last_resnap_at` indefinitely).
            try:
                if hasattr(bot, '_stop_manager') and bot._stop_manager \
                        and hasattr(bot._stop_manager, 'forget_trade'):
                    bot._stop_manager.forget_trade(trade_id)
            except Exception as e:
                logger.warning(f"close_trade: stop_manager.forget_trade failed: {e}")

            await bot._notify_trade_update(trade, "closed")
            await bot._save_trade(trade)

            # Auto-record exit to Trade Journal
            await bot._log_trade_to_journal(trade, "exit")

            # Record performance for learning loop
            if hasattr(bot, '_perf_service') and bot._perf_service:
                try:
                    bot._perf_service.record_trade(trade.to_dict())
                except Exception as e:
                    logger.warning(f"Failed to record trade performance: {e}")

            # NEW: Record to Learning Loop (Phase 1)
            if hasattr(bot, '_learning_loop') and bot._learning_loop:
                try:
                    outcome = "won" if trade.realized_pnl > 0 else ("lost" if trade.realized_pnl < 0 else "breakeven")
                    asyncio.create_task(bot._learning_loop.record_trade_outcome(
                        trade_id=trade.id,
                        alert_id=getattr(trade, 'alert_id', trade.id),
                        symbol=trade.symbol,
                        setup_type=trade.setup_type,
                        strategy_name=trade.setup_type,
                        direction=trade.direction.value if hasattr(trade.direction, 'value') else str(trade.direction),
                        trade_style=getattr(trade, 'trade_style', 'move_2_move'),
                        entry_price=trade.fill_price,
                        exit_price=trade.exit_price,
                        stop_price=trade.stop_loss,
                        target_price=trade.targets[0] if trade.targets else trade.fill_price * 1.02,
                        outcome=outcome,
                        pnl=trade.realized_pnl,
                        entry_time=trade.opened_at,
                        exit_time=trade.closed_at,
                        confirmation_signals=getattr(trade, 'confirmation_signals', [])
                    ))
                except Exception as e:
                    logger.warning(f"Failed to record trade to learning loop: {e}")

            # Log to regime performance tracking
            await bot._log_trade_to_regime_performance(trade)

            # Auto-generate chart snapshot with AI annotations
            try:
                snapshot_svc = getattr(bot, '_snapshot_service', None)
                if snapshot_svc:
                    asyncio.create_task(snapshot_svc.generate_snapshot(trade.id, "bot"))
                    logger.info(f"Snapshot generation triggered for {trade.symbol} ({trade.id})")
            except Exception as e:
                logger.warning(f"Failed to trigger snapshot generation: {e}")

            logger.info(f"Trade closed ({reason}): {trade.symbol} P&L: ${trade.realized_pnl:.2f}")
            return True

        except Exception as e:
            logger.error(f"Error closing trade: {e}")
            return False
