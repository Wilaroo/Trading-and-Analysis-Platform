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
import time
from datetime import datetime, timezone
from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from services.trading_bot_service import BotTrade, TradingBotService

logger = logging.getLogger(__name__)


class PositionManager:
    """Manages open position updates, scale-outs, closes, and EOD."""

    async def update_open_positions(self, bot: 'TradingBotService'):
        """Update P&L for open positions - uses IB data first, then Alpaca"""
        from services.trading_bot_service import TradeDirection, TradeStatus

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
            try:
                from routers.ib import _pushed_ib_data, is_pusher_connected
                if is_pusher_connected():
                    for _ip in (_pushed_ib_data.get("positions") or []):
                        _sym = (_ip.get("symbol") or "").upper()
                        _qty = float(_ip.get("position", 0) or 0)
                        if not _sym or abs(_qty) < 0.001:
                            continue
                        _key = (_sym, "long" if _qty > 0 else "short")
                        ib_pos_map[_key] = abs(_qty)
                else:
                    # If pusher is down we can't trust the map — skip
                    # the sweep this cycle. Better to leave the phantom
                    # in place than auto-close based on stale data.
                    raise RuntimeError("pusher_not_connected")
            except Exception:
                ib_pos_map = None  # disable sweep this cycle

            if ib_pos_map is not None:
                from services.trading_bot_service import TradeStatus as _TS
                # Snapshot keys so we don't mutate while iterating.
                for _tid, _trade in list(bot._open_trades.items()):
                    try:
                        if _trade.status == _TS.CLOSED:
                            continue
                        _rem = getattr(_trade, "remaining_shares", None)
                        # Only sweep when remaining shares is FIRMLY
                        # zero. `_rem == 0` because we explicitly set
                        # it after a successful close — skip None /
                        # uninitialised states (line 119 below
                        # initialises remaining_shares from shares for
                        # brand-new fills that haven't been managed yet).
                        if _rem is None or _rem != 0:
                            continue
                        # Must have been managed at least once — skip
                        # brand-new fills where remaining_shares is 0
                        # because we haven't initialised it yet. Use
                        # `executed_at` age to gate this.
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
                                    continue  # too fresh, IB may not have caught up
                            except Exception:
                                pass  # age parsing failed → fall through
                        _sym_u = (_trade.symbol or "").upper()
                        _dir = (
                            _trade.direction.value
                            if hasattr(_trade.direction, "value")
                            else str(_trade.direction)
                        ).lower()
                        if ib_pos_map.get((_sym_u, _dir), 0) > 0:
                            continue  # IB still has shares — not a phantom
                        # All clear — sweep.
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
                        # Move from _open_trades → _closed_trades so the
                        # V5 panel stops rendering the ghost row.
                        bot._open_trades.pop(_tid, None)
                        try:
                            bot._closed_trades.append(_trade)
                        except Exception:
                            pass
                        try:
                            from services.sentcom_service import emit_stream_event
                            await emit_stream_event({
                                "kind": "info",
                                "event": "phantom_auto_swept",
                                "symbol": _trade.symbol,
                                "text": (
                                    f"🧹 Auto-swept phantom {_trade.symbol} "
                                    f"{_dir.upper()} (0sh leftover) — IB "
                                    f"shows no shares, marking closed."
                                ),
                                "metadata": {
                                    "trade_id": _trade.id,
                                    "reason": "phantom_auto_swept_v19_27",
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
                if quote_age_s is not None and quote_age_s > STALE_QUOTE_S:
                    if not getattr(trade, "_stale_quote_warned_at", None) \
                       or (time.time() - float(getattr(trade, "_stale_quote_warned_at", 0))) > 60:
                        logger.warning(
                            f"manage: SKIP stop-check for {trade.symbol} — quote "
                            f"is {quote_age_s:.1f}s old (cap {STALE_QUOTE_S}s). "
                            f"Server-side IB bracket still active."
                        )
                        trade._stale_quote_warned_at = time.time()
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
        """
        from services.trading_bot_service import TradeDirection, TradeStatus

        if trade_id not in bot._open_trades:
            return False

        trade = bot._open_trades[trade_id]

        # Use remaining shares if we've done partial exits, otherwise use original shares
        shares_to_close = trade.remaining_shares if trade.remaining_shares > 0 else trade.shares

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
                from services.trade_snapshot_service import TradeSnapshotService
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
