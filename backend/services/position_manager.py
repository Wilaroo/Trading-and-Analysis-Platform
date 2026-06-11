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
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from services.trading_bot_service import BotTrade, TradingBotService

logger = logging.getLogger(__name__)


# ── v19.34.301 — pusher-independent EOD naked-flatten guard helpers ──
_PROTECTIVE_STOP_TYPES = {"STP", "STP LMT", "STOP", "STOP LIMIT", "TRAIL", "TRAIL LIMIT"}


def _ib_position_is_naked(position: float, symbol: str, open_orders: list) -> bool:
    """True when an IB position has NO working PROTECTIVE STOP at IB.

    Protective = a STOP-family order on the EXIT side (SELL for a long, BUY for
    a short). A plain limit target is NOT protection against adverse moves, so
    it does not count. Pure / no I/O — unit-testable. (v19.34.301)
    """
    qty = float(position or 0)
    if qty == 0:
        return False  # flat — nothing to protect
    sym = (symbol or "").upper()
    exit_action = "SELL" if qty > 0 else "BUY"
    for o in (open_orders or []):
        if (o.get("symbol") or "").upper() != sym:
            continue
        if (o.get("action") or "").upper() != exit_action:
            continue
        otype = (o.get("order_type") or "").upper()
        if otype in _PROTECTIVE_STOP_TYPES or (o.get("stop_price") or 0):
            return False  # a protective stop exists
    return True


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
                # v19.34.124 — Signed-position-sign-mismatch audit.
                # The ARGX class incident (Feb 2026): bot entered LONG
                # 118+4sh; by EOD the same symbol was SHORT 118 at IB
                # (sibling-bracket roll-flipped direction without the
                # v19.29 sweep catching it because the sweep only fires
                # when `ib_qty_my_dir == 0 AND ib_qty_opp_dir > 0`. If
                # BOTH directions had shares momentarily during the roll,
                # the sweep missed.
                #
                # v124 audit: compute signed-net IB position and bot's
                # tracked signed net. If they disagree by >1 share for
                # a symbol, emit a P0 stream warning (we don't auto-heal
                # to avoid bracket conflicts — operator decides). This
                # gives the operator real-time visibility into
                # sign-drift, which the share-drift reconciler doesn't
                # flag because it only checks abs(net).
                try:
                    by_sym_bot_signed: Dict[str, int] = {}
                    for _t in bot._open_trades.values():
                        if getattr(_t, "status", None) == _TS.CLOSED:
                            continue
                        _s = (getattr(_t, "symbol", "") or "").upper()
                        if not _s:
                            continue
                        _d = (
                            _t.direction.value
                            if hasattr(_t.direction, "value")
                            else str(_t.direction)
                        ).lower()
                        sign = 1 if _d == "long" else -1
                        try:
                            qty = int(abs(int(getattr(_t, "shares", 0) or 0)))
                        except Exception:
                            qty = 0
                        by_sym_bot_signed[_s] = by_sym_bot_signed.get(_s, 0) + sign * qty

                    by_sym_ib_signed: Dict[str, int] = {}
                    for (sym, d), q in (ib_pos_map or {}).items():
                        sign = 1 if d == "long" else -1
                        try:
                            by_sym_ib_signed[sym] = by_sym_ib_signed.get(sym, 0) + sign * int(q or 0)
                        except Exception:
                            continue

                    all_syms = set(by_sym_bot_signed) | set(by_sym_ib_signed)
                    for s in all_syms:
                        bot_net = by_sym_bot_signed.get(s, 0)
                        ib_net = by_sym_ib_signed.get(s, 0)
                        # Sign mismatch only flagged when BOTH non-zero
                        # and signs disagree, OR delta is large.
                        if bot_net == 0 and ib_net == 0:
                            continue
                        signs_disagree = (bot_net > 0 and ib_net < 0) or (bot_net < 0 and ib_net > 0)
                        if signs_disagree:
                            logger.error(
                                "🚨 [v124 sign-mismatch] %s: bot=%+d IB=%+d "
                                "— DIRECTION FLIP at broker. Manual reconcile "
                                "or flatten required.", s, bot_net, ib_net,
                            )
                            try:
                                from services.sentcom_service import emit_stream_event
                                await emit_stream_event({
                                    "kind": "warning",
                                    "severity": "P0",
                                    "title": f"{s}: direction sign mismatch",
                                    "body": (
                                        f"bot tracks {bot_net:+d}sh; IB has {ib_net:+d}sh "
                                        f"(opposite direction). Likely sibling-bracket roll-flip "
                                        f"(ARGX-class). Manual reconcile or flatten recommended."
                                    ),
                                    "trade_symbol": s,
                                    "source": "v19_34_124_sign_audit",
                                })
                            except Exception:
                                pass
                except Exception as _audit_err:
                    logger.debug(
                        "[v124 sign-mismatch] audit crashed (non-fatal): %s",
                        _audit_err,
                    )

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
                            # v19.34.123 — compute realized PnL using
                            # current_price as best-effort exit (the
                            # bot's recorded direction was wrong, so
                            # the original entry math is meaningless;
                            # but at least we mark the trade with a
                            # consistent close value rather than $0).
                            from services.pnl_compute import apply_close_pnl
                            apply_close_pnl(
                                _trade,
                                reason="wrong_direction_phantom_swept_v19_29",
                                exit_price=getattr(_trade, "current_price", None),
                            )
                            _trade.status = _TS.CLOSED
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
                                # v19.34.153 — Upgrade to CRITICAL with
                                # a clear remediation directive. The
                                # 2026-05-13 incident: 10 of these
                                # alarms fired in one minute when
                                # orphan brackets created reverse
                                # positions. The pre-fix WARNING-level
                                # alarm was too quiet for an event
                                # this severe.
                                await emit_stream_event({
                                    "kind": "alarm",
                                    "event": "wrong_direction_phantom_swept",
                                    "symbol": _trade.symbol,
                                    "text": (
                                        f"🚨 [CRITICAL] REVERSE POSITION at IB: "
                                        f"{_trade.symbol} bot tracked {_dir.upper()} "
                                        f"but IB has {opp.upper()} {int(ib_qty_opp_dir)}sh. "
                                        "Likely cause: orphan bracket fired after "
                                        "external close. Bot record closed — "
                                        "IB position is STILL HELD and will roll "
                                        "overnight unless you flatten manually OR "
                                        "via POST /api/trading-bot/flatten-symbol."
                                    ),
                                    "metadata": {
                                        "trade_id": _trade.id,
                                        "bot_direction": _dir,
                                        "ib_direction": opp,
                                        "ib_qty": ib_qty_opp_dir,
                                        "reason": "wrong_direction_phantom",
                                        "severity": "CRITICAL",
                                        "remediation": "flatten_symbol",
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
                    # v19.34.227 — a held position with NO quote at all (fell
                    # entirely out of the pusher's quote universe, e.g. CRM
                    # after a scan-universe rotation) never reached the stale
                    # branch below, so it was never re-subscribed and went
                    # mark-less (current_price stuck → fake -$18,897 kill-switch
                    # trip, v226). Flag it so the held name gets re-pinned into
                    # the quote feed by the resub drain + quote_resub_watchdog.
                    try:
                        if not hasattr(self, "_stale_resub_set"):
                            self._stale_resub_set = set()
                        self._stale_resub_set.add(trade.symbol.upper())
                    except Exception:
                        pass
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

                # ── v19.34.61 (2026-02-09) — Conditional rs/original self-heal ──
                # OLD (pre-fix): unconditionally `rs = trade.shares` whenever
                # rs == 0. This was defensive code from pre-v19.34.21 days
                # when persistence didn't hydrate `remaining_shares`
                # correctly. Now that v19.34.21 round-trips rs through
                # Mongo AND every entry path (`opportunity_evaluator.py`,
                # `_spawn_excess_slice`, orphan-reconciler, imported-position
                # endpoint) explicitly initializes rs at create time, the
                # unconditional self-heal does more harm than good: it
                # RE-ANIMATES zombie BotTrades (rs=0, status=OPEN,
                # original_shares > 0) on the first fresh quote, inflating
                # tracked share count beyond what's actually at IB.
                # Symptom (2026-02-09 EFA): tracked 1923sh phantom across
                # 3 fragments while IB only had 963.
                #
                # NEW: only self-heal in the narrow window the heal was
                # originally written for — a freshly-created trade whose
                # entry path forgot to mirror `shares -> remaining_shares`
                # AND whose status is OPEN AND has no close_reason set
                # AND was executed within the last RS_HEAL_WINDOW_S
                # seconds. Outside that window, leave rs=0 alone — it's
                # either a real zombie (drift loop / v19.34.59 cleanup
                # will heal) or a genuine close-in-progress (don't fight
                # the close). One-shot ERROR log so operator can hunt
                # the upstream creator.
                RS_HEAL_WINDOW_S = 60
                if trade.remaining_shares == 0 and int(getattr(trade, "shares", 0) or 0) > 0:
                    if getattr(trade, "close_reason", None):
                        # Trade is being closed — respect close intent.
                        pass
                    elif getattr(trade, "_loaded_as_zombie_v19_34_59", False):
                        # Boot-time zombie tagged by v19.34.59 tripwire —
                        # let drift loop clean it.
                        pass
                    else:
                        executed_at = getattr(trade, "executed_at", None) \
                            or getattr(trade, "entry_time", None)
                        age_s = None
                        if executed_at:
                            try:
                                if isinstance(executed_at, str):
                                    ts = datetime.fromisoformat(
                                        executed_at.replace("Z", "+00:00")
                                    )
                                else:
                                    ts = executed_at
                                if ts.tzinfo is None:
                                    ts = ts.replace(tzinfo=timezone.utc)
                                age_s = (datetime.now(timezone.utc) - ts).total_seconds()
                            except Exception:
                                age_s = None
                        if age_s is not None and 0 <= age_s <= RS_HEAL_WINDOW_S:
                            logger.warning(
                                "v19.34.61 [HEAL-FRESH] %s id=%s rs=0->%d "
                                "(executed_at=%s, age=%.1fs). Within %ss "
                                "fresh-fill window.",
                                trade.symbol, trade.id, int(trade.shares),
                                executed_at, age_s, RS_HEAL_WINDOW_S,
                            )
                            trade.remaining_shares = trade.shares
                            trade.original_shares = trade.shares
                        else:
                            # Outside fresh-fill window → suspected zombie.
                            # Log once per trade and skip the heal.
                            if not getattr(trade, "_v19_34_61_skip_warned", False):
                                logger.error(
                                    "v19.34.61 [SKIP-HEAL-ZOMBIE] %s id=%s "
                                    "rs=0 outside %ss fresh-fill window "
                                    "(executed_at=%s, age=%s, shares=%d, "
                                    "original=%d, entered_by=%s). NOT "
                                    "re-animating; drift loop / v19.34.19 "
                                    "zombie cleanup should handle. Hunt "
                                    "upstream creator: grep '%s' /tmp/backend.log",
                                    trade.symbol, trade.id, RS_HEAL_WINDOW_S,
                                    executed_at,
                                    f"{age_s:.1f}s" if age_s is not None else "?",
                                    int(getattr(trade, "shares", 0) or 0),
                                    int(getattr(trade, "original_shares", 0) or 0),
                                    getattr(trade, "entered_by", "?"),
                                    trade.id,
                                )
                                trade._v19_34_61_skip_warned = True
                            # Skip the rest of the manage tick for this
                            # zombie — there's nothing to manage with rs=0.
                            continue

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

                # Calculate unrealized P&L on remaining shares.
                # v19.34.226 — NEVER mark off a missing/zero price. A stale
                # current_price <= 0 (symbol dropped from the quote push or a
                # freshly-restored/adopted trade) would yield
                # (0 - fill) * shares = a catastrophic FAKE loss (CRM 95sh @
                # $198.92 → -$18,897) that repeatedly tripped the v123
                # daily-loss kill-switch. Leave unrealized at its last good
                # value until a valid mark arrives.
                _cp = trade.current_price
                if not _cp or _cp <= 0:
                    pass
                elif trade.direction == TradeDirection.LONG:
                    trade.unrealized_pnl = (_cp - trade.fill_price) * trade.remaining_shares
                else:
                    trade.unrealized_pnl = (trade.fill_price - _cp) * trade.remaining_shares

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

                # M0 (2026-06) — laddered scale-out live management. Detects
                # IB-side leg fills (stamps targets_hit so StopManager's
                # BE/trail activates) and pushes the ratcheted internal
                # current_stop to the surviving IB leg stops in place.
                # No-op for trades without m0_legs.
                try:
                    from services.m0_ladder_manager import manage_m0_trade
                    await manage_m0_trade(trade, bot)
                except Exception as _m0_err:
                    logger.debug(f"[M0] manage tick skipped for {trade.symbol}: {_m0_err}")

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

    async def check_scalp_decay(self, bot: 'TradingBotService'):
        """v19.34.171 — Scalp Time Decay.

        Auto-close any SCALP-timeframe position open longer than
        ``SCALP_DECAY_MINUTES`` (default 60). Sequence: cancel OCA →
        wait 2s → MKT flatten. Skips if entry is <``SCALP_DECAY_MIN_TIME_TO_CLOSE``
        minutes (default 60) from market close — EOD will handle.

        Env tunables:
          SCALP_DECAY_ENABLED        — "1" (default) / "0" to disable
          SCALP_DECAY_MINUTES        — 60
          SCALP_DECAY_MIN_TIME_TO_CLOSE — 60
        """
        import os
        if os.environ.get("SCALP_DECAY_ENABLED", "1") != "1":
            return
        try:
            decay_minutes = float(os.environ.get("SCALP_DECAY_MINUTES", "60") or "60")
        except (TypeError, ValueError):
            decay_minutes = 60.0
        try:
            min_to_close = float(os.environ.get("SCALP_DECAY_MIN_TIME_TO_CLOSE", "60") or "60")
        except (TypeError, ValueError):
            min_to_close = 60.0

        try:
            from zoneinfo import ZoneInfo
            et = ZoneInfo("US/Eastern")
            now_et = datetime.now(et)
            close_et = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
            mins_to_close = (close_et - now_et).total_seconds() / 60.0
        except Exception:
            mins_to_close = 999.0

        if mins_to_close <= min_to_close:
            return

        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc - timedelta(minutes=decay_minutes)

        try:
            scalp_candidates = []
            for trade in list(bot._open_trades.values()):
                # v19.34.171.4 — use string compare to avoid the
                # import dance (TradeTimeframe / TradeStatus are
                # str Enums; "scalp" == TradeTimeframe.SCALP holds).
                _tf = getattr(trade, "timeframe", "")
                if hasattr(_tf, "value"):
                    _tf = _tf.value
                # v322u — style-aware selection (probe 2026-06-11 found
                # style/timeframe drift on persisted rows):
                #   1. a scalp-STYLE trade stamped tf="intraday" by the
                #      drifted STRATEGY_CONFIG table escaped decay forever;
                #   2. (defensive) a swing-style trade stamped tf="scalp"
                #      would be wrongly flattened at 60 min.
                # trade_style is the policy-bearing axis — it wins both
                # ways. Covers legacy rows already in Mongo, not just
                # new trades stamped by the v322u evaluator reconciler.
                _style = str(getattr(trade, "trade_style", "") or "").strip().lower()
                if _style in ("swing", "multi_day", "position", "investment"):
                    continue
                if str(_tf).lower() != "scalp" and _style != "scalp":
                    continue
                _st = getattr(trade, "status", "")
                if hasattr(_st, "value"):
                    _st = _st.value
                if str(_st).lower() != "open":
                    continue
                ex = (
                    getattr(trade, "executed_at", None)
                    or getattr(trade, "entry_time", None)
                )
                if not ex:
                    continue
                if isinstance(ex, str):
                    try:
                        ex_dt = datetime.fromisoformat(ex.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                elif isinstance(ex, datetime):
                    ex_dt = ex if ex.tzinfo else ex.replace(tzinfo=timezone.utc)
                else:
                    continue
                if ex_dt < cutoff:
                    age_min = (now_utc - ex_dt).total_seconds() / 60.0
                    scalp_candidates.append((trade, age_min))

            if not scalp_candidates:
                return

            logger.info(
                f"[v19.34.171 SCALP-DECAY] {len(scalp_candidates)} scalp "
                f"position(s) past {decay_minutes:.0f}-min decay; flattening."
            )

            async def _decay_one(trade, age_min):
                symbol = getattr(trade, "symbol", "?")
                # v19.34.171.1 — close_trade takes (trade_id, reason),
                # NOT (trade_obj, reason). v171 shipped with the wrong
                # signature → every flatten attempt raised silently.
                trade_id = (
                    getattr(trade, "id", None)
                    or getattr(trade, "trade_id", None)
                )
                if not trade_id:
                    logger.warning(
                        f"[v19.34.171 SCALP-DECAY] no trade_id resolvable "
                        f"for {symbol}; skipping"
                    )
                    return
                try:
                    if hasattr(bot, "_cancel_oca_for_trade"):
                        try:
                            await bot._cancel_oca_for_trade(trade)
                        except Exception as ce:
                            logger.debug(
                                f"[v19.34.171] OCA cancel failed for {symbol}: {ce}"
                            )
                    await asyncio.sleep(2.0)
                    if hasattr(bot, "close_trade"):
                        ok = await bot.close_trade(trade_id, reason="scalp_time_decay")
                        if ok:
                            logger.info(
                                f"[v19.34.171 SCALP-DECAY] flattened {symbol} "
                                f"(age={age_min:.1f}min)"
                            )
                        else:
                            logger.warning(
                                f"[v19.34.171 SCALP-DECAY] close_trade returned "
                                f"False for {symbol}"
                            )
                except Exception as e:
                    logger.warning(
                        f"[v19.34.171 SCALP-DECAY] flatten failed for "
                        f"{symbol}: {e}"
                    )

            await asyncio.gather(
                *(_decay_one(t, a) for t, a in scalp_candidates),
                return_exceptions=True,
            )
        except Exception as e:
            logger.error(f"[v19.34.171 SCALP-DECAY] sweep failed: {e}")

    async def missed_eod_boot_sweep(self, bot: 'TradingBotService',
                                    now_et: Optional[datetime] = None) -> dict:
        """v322s — boot-time catch-up for a MISSED EOD window.

        The ACMR 2026-05-29 carry: a close_at_eod position filled at 15:38
        ET, the backend went down before the 15:45 flatten pass, and the
        position survived the weekend on its GTC stop — gapping through it
        at Monday's open. Every in-session guard (decay, EOD close pass,
        v301/302 naked/force-flatten) requires the process to be RUNNING in
        the window; none can catch a missed window after the fact.

        This sweep runs once at boot (scheduled by TradingBotService):
          • tracked OPEN trade + policy says close_at_eod=True + fill date
            (ET) is BEFORE today → "missed-EOD carryover".
          • market open  → flatten NOW via the canonical close path.
          • market closed → CRITICAL alarm + state_integrity_event, then
            report waiting_for_open=True so the caller re-runs until the
            bell (flatten happens at the open auction — the position should
            not exist, same discipline the missed EOD pass would have
            enforced).
        Alarms dedupe per trade per boot via bot._missed_eod_alarmed_ids.
        Kill switch: MISSED_EOD_BOOT_SWEEP_ENABLED=0.
        """
        result = {"checked": 0, "stale": 0, "flattened": 0, "alarmed": 0,
                  "waiting_for_open": False, "skipped_reason": None}
        if os.environ.get("MISSED_EOD_BOOT_SWEEP_ENABLED", "1") != "1":
            result["skipped_reason"] = "disabled"
            return result
        if now_et is None:
            try:
                from zoneinfo import ZoneInfo
                now_et = datetime.now(ZoneInfo("America/New_York"))
            except Exception:
                result["skipped_reason"] = "tz_unavailable"
                return result
        today_et = now_et.date()
        in_rth = (
            now_et.weekday() < 5
            and (now_et.hour, now_et.minute) >= (9, 30)
            and now_et.hour < 16
        )
        try:
            from services.order_policy_registry import should_close_at_eod
        except ImportError:
            result["skipped_reason"] = "policy_unavailable"
            return result

        alarmed_ids = getattr(bot, "_missed_eod_alarmed_ids", None)
        if alarmed_ids is None:
            alarmed_ids = set()
            try:
                bot._missed_eod_alarmed_ids = alarmed_ids
            except Exception:
                pass

        for trade in list((getattr(bot, "_open_trades", {}) or {}).values()):
            _st = getattr(trade, "status", "")
            if str(getattr(_st, "value", _st)).lower() != "open":
                continue
            result["checked"] += 1
            try:
                if not should_close_at_eod(trade):
                    continue  # genuine overnight hold — not ours to touch
            except Exception:
                continue
            ex = (getattr(trade, "executed_at", None)
                  or getattr(trade, "entry_time", None))
            if isinstance(ex, str):
                try:
                    ex_dt = datetime.fromisoformat(ex.replace("Z", "+00:00"))
                except ValueError:
                    continue
            elif isinstance(ex, datetime):
                ex_dt = ex
            else:
                continue
            if ex_dt.tzinfo is None:
                ex_dt = ex_dt.replace(tzinfo=timezone.utc)
            ex_et_date = (ex_dt.astimezone(now_et.tzinfo).date()
                          if now_et.tzinfo else ex_dt.date())
            if ex_et_date >= today_et:
                continue  # filled today — the normal EOD pass owns it
            result["stale"] += 1
            tid = getattr(trade, "id", None) or getattr(trade, "trade_id", None)
            sym = getattr(trade, "symbol", "?")

            if tid not in alarmed_ids:
                alarmed_ids.add(tid)
                result["alarmed"] += 1
                logger.critical(
                    "[v322s MISSED-EOD] %s %s filled %s but is still OPEN on "
                    "%s — the EOD flatten window was MISSED (backend down in "
                    "the window?). %s.",
                    sym, tid, ex_et_date, today_et,
                    "Flattening NOW" if in_rth else "Will flatten at the next open",
                )
                try:
                    _db = getattr(bot, "_db", None)
                    if _db is None:
                        _db = getattr(bot, "db", None)
                    if _db is not None:
                        _db["state_integrity_events"].insert_one({
                            "event": "missed_eod_carryover",
                            "severity": "critical",
                            "symbol": sym,
                            "trade_id": tid,
                            "fill_date_et": str(ex_et_date),
                            "detected_date_et": str(today_et),
                            "action": "flatten_now" if in_rth else "flatten_at_open",
                            "detail": (
                                "close_at_eod position survived a missed EOD "
                                "window (process not running 15:45-16:00 ET; "
                                "ACMR-class weekend carry)."
                            ),
                            "ts": datetime.now(timezone.utc).isoformat(),
                        })
                except Exception:
                    pass

            if not in_rth:
                result["waiting_for_open"] = True
                continue
            if not tid:
                continue
            try:
                ok = await self.close_trade(tid, bot, reason="missed_eod_boot_flatten")
                if ok:
                    result["flattened"] += 1
                    logger.info("[v322s MISSED-EOD] flattened %s (%s)", sym, tid)
                else:
                    logger.error(
                        "[v322s MISSED-EOD] close_trade returned False for %s (%s)",
                        sym, tid)
            except Exception as fe:
                logger.error("[v322s MISSED-EOD] flatten %s raised: %s", sym, fe)
        return result


    async def _eod_naked_flatten_guard(self, bot: 'TradingBotService') -> dict:
        """v19.34.301 — pusher-INDEPENDENT EOD safety net.

        From the RegT bracket cutoff (15:45 ET, when brackets can no longer be
        (re)attached) until market close (16:00 ET), flatten any IB position that
        has NO protective stop at IB — reading positions + working orders
        **straight from ib_direct** (clientId=11), so it works even when the
        Windows pusher is dead (exactly when `_naked_position_sweep` skips out via
        PATCH E/F). Closes the overnight-naked gap and covers UNTRACKED orphans
        that the tracked-only EOD close would miss (the MA 2026-06-08 class).

        Policy per position:
          • untracked orphan        → FLATTEN (stray, EOD would miss it)
          • tracked close_at_eod=True (intraday) → FLATTEN (closing anyway)
          • tracked close_at_eod=False (swing/position) → DO NOT flatten; if naked,
            raise a HIGH-severity `naked_overnight_hold` alarm (needs a GTC stop,
            not a forced exit); if protected, leave it on its stop.

        v19.34.302 — FORCE-FLATTEN BRACKETED SWEEP-MISSES.
        Past the final cutoff (default 15:56 ET, after the 15:55 EOD close sweep
        has run), an intraday/orphan position that is STILL open at IB — even WITH
        a working bracket — is a sweep-miss (the MRSH/CEG 2026-06-04 class, where
        an early-adopted orphan kept its synthetic bracket and rode to the 16:00+
        auction). Force-flatten it: CANCEL the working bracket first (so a stop/
        target leg can't fill naked or trip IB's oversell guard), re-read the
        position (a leg may fill during the cancel → already flat), then MKT close
        the remainder. Genuine swing/position holds (close_at_eod=False) stay
        exempt. Reversible via env EOD_FORCE_FLATTEN_BRACKETED (default ON);
        window minute tunable via EOD_FORCE_FLATTEN_MINUTE (default 56).

        Reversible via env EOD_NAKED_FLATTEN_GUARD (default ON). Throttled to
        ~20s so it doesn't hammer IB every manage tick inside the window.
        """
        result = {"checked": 0, "naked": 0, "flattened": 0, "alarmed": 0, "force_flattened_attempts": 0, "skipped_reason": None}
        import os as _os
        if _os.environ.get("EOD_NAKED_FLATTEN_GUARD", "true").strip().lower() not in ("1", "true", "yes", "on"):
            result["skipped_reason"] = "disabled"
            return result
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo("America/New_York"))
        if now_et.weekday() >= 5:
            result["skipped_reason"] = "weekend"
            return result
        # Window: past the RegT bracket cutoff (15:45) and before close (16:00).
        if (now_et.hour, now_et.minute) < (15, 45) or now_et.hour >= 16:
            result["skipped_reason"] = "outside_window"
            return result
        # Throttle — at most once per ~20s.
        import time as _time
        _last = getattr(bot, "_last_naked_guard_ts", 0.0)
        if (_time.time() - _last) < 20.0:
            result["skipped_reason"] = "throttled"
            return result
        bot._last_naked_guard_ts = _time.time()

        # ── v19.34.302 — final-window force-flatten of BRACKETED sweep-misses ──
        # After the EOD close sweep has run (default 15:56 ET), any intraday/orphan
        # position still open — even WITH a working bracket — is a sweep-miss and
        # gets force-flattened below (bracket cancelled first). Swing holds exempt.
        _force_bracketed = _os.environ.get(
            "EOD_FORCE_FLATTEN_BRACKETED", "true"
        ).strip().lower() in ("1", "true", "yes", "on")
        try:
            _ff_min = int(_os.environ.get("EOD_FORCE_FLATTEN_MINUTE", "56"))
        except (TypeError, ValueError):
            _ff_min = 56
        _in_final_window = _force_bracketed and (
            (now_et.hour, now_et.minute) >= (15, _ff_min)
        )

        try:
            from services.ib_direct_service import get_ib_direct_service
            svc = get_ib_direct_service()
            if svc is None or not getattr(svc, "_connected", False):
                result["skipped_reason"] = "ib_direct_unavailable"
                return result
            positions = await svc.get_positions() or []
            open_orders = await svc.get_open_orders() or []
        except Exception as e:
            result["skipped_reason"] = f"ib_fetch_failed:{e}"
            return result

        # Map of bot-tracked open positions by symbol (for orphan + close_at_eod).
        bot_open = {}
        for t in (getattr(bot, "_open_trades", {}) or {}).values():
            bot_open[(getattr(t, "symbol", "") or "").upper()] = t

        for p in positions:
            qty = float(p.get("position") or 0)
            if qty == 0 or (p.get("sec_type") and p.get("sec_type") != "STK"):
                continue
            result["checked"] += 1
            sym = (p.get("symbol") or "").upper()
            tracked = bot_open.get(sym)
            close_at_eod = bool(getattr(tracked, "close_at_eod", True)) if tracked else True
            is_swing_hold = (tracked is not None and not close_at_eod)
            naked = _ib_position_is_naked(qty, sym, open_orders)

            # ── Genuine swing/position hold (intentional overnight) ──
            if is_swing_hold:
                if naked:
                    # Overnight hold gone naked — alarm, do NOT flatten.
                    result["naked"] += 1
                    result["alarmed"] += 1
                    try:
                        bot._db["state_integrity_events"].insert_one({
                            "event": "naked_overnight_hold", "severity": "high",
                            "symbol": sym, "position": qty,
                            "detail": ("swing/position hold is NAKED past the RegT cutoff and "
                                       "cannot be re-bracketed today — operator must add a stop."),
                            "ts": datetime.now(timezone.utc).isoformat(),
                        })
                    except Exception:
                        pass
                    logger.error("[v19.34.301] NAKED overnight hold %s (%+.0f) — alarmed, not flattened.", sym, qty)
                continue

            # ── Intraday or untracked orphan ──
            # v301: naked → flatten now (cheap MKT, no bracket to cancel).
            # v302: bracketed but still open in the final window → sweep-miss;
            #       cancel its working bracket first, then flatten.
            if naked:
                result["naked"] += 1
                reason, cancel_first = "eod_naked_flatten", False
            elif _in_final_window:
                result["force_flattened_attempts"] += 1
                reason, cancel_first = "eod_v302_force_flatten", True
            else:
                # Bracketed and not yet the final window — let the EOD MKT sweep /
                # the bracket itself work. Re-checked on the next manage tick.
                continue

            kind = "untracked orphan" if tracked is None else "intraday"

            # v302 — cancel the working bracket BEFORE the MKT so a stop/target
            # leg can't fill naked or trip IB's oversell guard. Then re-read the
            # position: if a leg filled during the cancel, we're already flat.
            if cancel_first:
                try:
                    await svc.cancel_all_open_orders_for_symbol(sym)
                    await asyncio.sleep(0.4)
                    _fresh = await svc.get_positions() or []
                    _now_qty = 0.0
                    for _fp in _fresh:
                        if (_fp.get("symbol") or "").upper() == sym:
                            _now_qty += float(_fp.get("position") or 0)
                    if int(abs(round(_now_qty))) == 0:
                        logger.warning(
                            "[v19.34.302] %s flat after bracket-cancel (a leg filled "
                            "during cancel) — no MKT needed.", sym,
                        )
                        result["flattened"] += 1
                        try:
                            bot._db["state_integrity_events"].insert_one({
                                "event": "eod_v302_force_flatten", "severity": "high",
                                "symbol": sym, "position": qty, "kind": kind,
                                "flatten_ok": True, "note": "closed_by_leg_during_cancel",
                                "ts": datetime.now(timezone.utc).isoformat(),
                            })
                        except Exception:
                            pass
                        continue
                    qty = _now_qty  # flatten the actual remaining
                except Exception as ce:
                    logger.error("[v19.34.302] %s bracket-cancel raised: %s — proceeding to MKT.", sym, ce)

            action = "SELL" if qty > 0 else "BUY"
            try:
                res = await svc.place_market_order(sym, action, int(abs(qty)))
                ok = bool(res.get("success"))
            except Exception as fe:
                ok = False
                logger.error("[v19.34.301/302] flatten %s raised: %s", sym, fe)
            if ok:
                result["flattened"] += 1
            logger.error(
                "[%s] %s %s position %s (%+.0f) past cutoff → FLATTEN %s (%s)",
                "v19.34.302" if cancel_first else "v19.34.301",
                "BRACKETED sweep-miss" if cancel_first else "NAKED",
                kind, sym, qty, "OK" if ok else "FAILED", action,
            )
            try:
                bot._db["state_integrity_events"].insert_one({
                    "event": reason, "severity": "high",
                    "symbol": sym, "position": qty, "kind": kind,
                    "flatten_ok": ok, "ts": datetime.now(timezone.utc).isoformat(),
                })
            except Exception:
                pass
        if result["naked"] or result["force_flattened_attempts"]:
            logger.warning("[v19.34.301/302 naked-guard] %s", result)
        return result

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

        # Only run on weekdays during market hours
        if now_et.weekday() >= 5:
            return

        # v19.34.152 — check for position-memory disagreements on
        # every manage tick during market hours. The alarm dedupes
        # per-day-per-symbol so the stream isn't flooded.
        try:
            await self.check_position_memory_disagreement(bot)
        except Exception as mem_err:
            logger.debug(f"v19.34.152 disagreement check failed: {mem_err}")

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

        # ── v19.34.301 — pusher-independent naked-flatten guard. Runs from the
        # RegT bracket cutoff (15:45 ET) — BEFORE the 15:55 EOD close — so a
        # position that goes naked in the no-bracket window (incl. untracked
        # orphans the tracked-only EOD close would miss) gets flattened rather
        # than carried overnight unprotected. Has its own time/throttle gates.
        try:
            await self._eod_naked_flatten_guard(bot)
        except Exception as _ng_err:
            logger.error(f"v19.34.301 naked-flatten guard failed: {_ng_err}")

        # Not yet time to close
        if now_et.hour < eod_hour or (now_et.hour == eod_hour and now_et.minute < eod_minute):
            return

        # ── v19.34.169 — EOD HEARTBEAT (observability) ────────────────
        # Emit a sentcom_thought once per minute while inside the EOD
        # window so the operator can SEE the scheduler firing from the
        # UI. Prior to v169 the EOD code ran silently when there were
        # no positions to close, which looked identical to "scheduler
        # never fired". Dedupes per HH:MM stamp via in-process attr.
        try:
            hb_stamp = now_et.strftime("%Y-%m-%d %H:%M")
            last_hb = getattr(bot, "_eod_last_heartbeat_stamp", None)
            if last_hb != hb_stamp:
                bot._eod_last_heartbeat_stamp = hb_stamp
                db = (getattr(bot, "_db", None) if getattr(bot, "_db", None) is not None else getattr(bot, "db", None))
                if db is not None:
                    # Count open close_at_eod=True positions on the fly
                    eod_eligible_count = db["bot_trades"].count_documents({
                        "closed_at": None,
                        "exit_price": None,
                        "fill_price": {"$ne": None},
                        "close_at_eod": True,
                    })
                    # v19.34.170 — normalize sentcom_thoughts schema:
                    #   * created_at as BSON datetime (matches TTL index +
                    #     _persist_thought convention; v169 wrote ISO string
                    #     here which the TTL would never expire)
                    #   * timestamp as ISO string (matches diagnostics.py
                    #     `{"timestamp": {"$gte": cutoff_iso}}` queries)
                    #   * kind + content (canonical schema fields)
                    #   * top-level `category` kept for the operator's
                    #     existing `db.sentcom_thoughts.find({category:
                    #     'eod_heartbeat'})` query shipped in v169
                    from utils.timestamps import now_bson, now_iso
                    _eod_thought_text = (
                        f"EOD window tick {hb_stamp} ET — eligible "
                        f"close_at_eod positions: {eod_eligible_count}, "
                        f"executed_today={bot._eod_close_executed_today}, "
                        f"half_day={is_half_day}, "
                        f"window={eod_hour:02d}:{eod_minute:02d}-{market_close_hour:02d}:00 ET"
                    )
                    db["sentcom_thoughts"].insert_one({
                        "kind": "system",
                        "content": _eod_thought_text,
                        "thought": _eod_thought_text,  # legacy alias
                        "category": "eod_heartbeat",
                        "symbol": None,
                        "timestamp": now_iso(),
                        "created_at": now_bson(),
                        "metadata": {
                            "category": "eod_heartbeat",
                            "eligible_positions": eod_eligible_count,
                            "executed_today": bot._eod_close_executed_today,
                            "is_half_day": is_half_day,
                            "eod_hour": eod_hour,
                            "eod_minute": eod_minute,
                            "hb_stamp": hb_stamp,
                        },
                    })
        except Exception as hb_err:
            logger.debug(f"v19.34.169: EOD heartbeat write failed: {hb_err}")

        # ── v19.34.153 P0 EOD ghost-flatten + T-2/T-1 fallbacks ──────
        # Operator choice 2B: ghost-flatten ALWAYS runs while in the
        # EOD window, even if `_eod_close_executed_today=True`, so a
        # late-arriving ghost (e.g. a bracket parent that fills at
        # 3:57 ET after the main close pass ran at 3:55 ET) still
        # gets flatted before 4:00 ET.
        if now_et.hour < market_close_hour:
            try:
                await self._flatten_ghost_positions(
                    bot, reason=f"eod_window_{now_et.strftime('%H%M')}",
                )
            except Exception as gf_err:
                logger.error(
                    f"v19.34.153: ghost-flatten failed inside check_eod_close: {gf_err}"
                )

            # ── v19.34.154 — T-offsets are now RELATIVE to eod_minute ──
            # Pre-v154 these were hardcoded to `>= 58 / >= 59` (assuming
            # market_close_hour-1). With EOD shifted from 3:55→3:45 to
            # beat IBKR's 3:50 Reg-T calc, we need the escalation to
            # also shift. Anchor everything to `eod_minute` so the
            # cascade scales with whatever close time is configured:
            #   eod_minute + 2  → T-2 force-MKT on tracked stragglers
            #   eod_minute + 3  → T-1 operator alert
            # For the v154 default (eod_minute=45), this fires at:
            #   3:47 ET — force MKT
            #   3:48 ET — operator alert
            # → 2 full minutes of headroom before IBKR's 3:50 Reg-T calc.
            # Half-day fallback still uses market_close_hour-1 minute 58/59
            # because half-days don't have the Reg-T deadline issue
            # (closes at 1:00 with no overnight rollover concern).
            if is_half_day:
                # Half-day path unchanged (pre-v154 behaviour).
                t2_h = market_close_hour - 1
                fire_t2 = (now_et.hour == t2_h and now_et.minute >= 58)
                fire_t1 = (now_et.hour == t2_h and now_et.minute >= 59)
            else:
                # Regular-day: relative to eod_minute.
                t2_minute = eod_minute + 2
                t1_minute = eod_minute + 3
                fire_t2 = (now_et.hour == eod_hour and now_et.minute >= t2_minute)
                fire_t1 = (now_et.hour == eod_hour and now_et.minute >= t1_minute)

            if fire_t2:
                try:
                    await self._eod_t_minus_2_escalate(bot)
                except Exception as t2_err:
                    logger.error(f"v19.34.153: T-2 escalate failed: {t2_err}")

            if fire_t1:
                try:
                    await self._eod_t_minus_1_alert(bot)
                except Exception as t1_err:
                    logger.error(f"v19.34.153: T-1 alert failed: {t1_err}")

        # v19.34.153 — moved AFTER ghost-flatten/T-2/T-1 (was at top of
        # function) so a successful main close pass does NOT short-
        # circuit late-arriving-ghost recovery (operator choice 2B).
        # Skip the main intraday close pass if already executed today.
        if bot._eod_close_executed_today:
            # ── v19.34.261 — EOD re-sweep safety net ──────────────────
            # The main close pass already ran today, but a `close_at_eod`
            # position can ARRIVE AFTER it (late orphan adoption, a bracket
            # parent that fills post-pass, a manual add). Without this, the
            # flag permanently short-circuits the close pass and the new
            # position carries overnight (the 2026-06-03 class of bug).
            # If residual close_at_eod trades are still open and we're still
            # before the bell, fall THROUGH to re-run the close pass on them
            # (throttled so in-flight closes aren't double-fired).
            try:
                from services.order_policy_registry import should_close_at_eod as _scae
                _residual = [t for t in bot._open_trades.values() if _scae(t)]
            except Exception:
                _residual = []
            _last_rs = getattr(bot, "_eod_resweep_last_ts", 0.0)
            _now_ts = time.time()
            if (
                _residual
                and now_et.hour < market_close_hour
                and (_now_ts - _last_rs) >= 30.0
            ):
                bot._eod_resweep_last_ts = _now_ts
                logger.critical(
                    "[v19.34.261 EOD-RESWEEP] %d close_at_eod position(s) still "
                    "OPEN after the main EOD pass already ran today (%s) — "
                    "re-running close pass on: %s",
                    len(_residual), today_str,
                    [getattr(t, "symbol", "?") for t in _residual],
                )
                # fall through (do NOT return) to the main close pass below.
            else:
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
            # v19.34.152 — persist the event even on this early-return
            # path so postmortem can distinguish "loop didn't run" from
            # "loop ran but bot's _open_trades was empty" (exactly the
            # 2026-05-13 incident pattern).
            await self._persist_eod_event(
                bot, today_str, now_et,
                closed=0, failed=[], total_pnl=0.0,
                is_half_day=is_half_day,
                early_exit_reason="open_trades_empty",
                ib_position_count=len(self._ib_position_snapshot_safe()),
            )
            # v19.34.151 — still run the sweep even with no positions
            # to close; stale DAY entries and orphan GTC brackets can
            # exist independently of `_open_trades`. Fire-and-forget.
            asyncio.create_task(self._run_eod_orphan_sweep(bot))
            return

        # Only close trades marked for EOD close (intraday/scalp/day trades)
        # Swing and position trades are held overnight.
        # v19.34.245 — resolve close_at_eod from the trade-style POLICY
        # (authoritative) instead of the per-trade attribute, which was set at
        # entry with a default-True fallback and wrongly flagged position/swing
        # setups missing the config key (they were swept at EOD, skewing the
        # learning loop). Policy resolution holds long-horizon styles overnight.
        from services.order_policy_registry import should_close_at_eod
        eod_trades = {
            tid: t for tid, t in bot._open_trades.items()
            if should_close_at_eod(t)
        }

        if not eod_trades:
            logger.info(f"🔔 EOD CHECK: {open_count} open trades, all are swing/position — no EOD close needed")
            bot._eod_close_executed_today = True
            # v19.34.152 — persist event on the all-swing path too.
            await self._persist_eod_event(
                bot, today_str, now_et,
                closed=0, failed=[], total_pnl=0.0,
                is_half_day=is_half_day,
                early_exit_reason="all_swing_or_position",
                ib_position_count=len(self._ib_position_snapshot_safe()),
            )
            # v19.34.151 — same as above: sweep runs even when all open
            # trades are swing/position. Fire-and-forget.
            asyncio.create_task(self._run_eod_orphan_sweep(bot))
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
        # ── v19.34.162 EOD fast-path opt-in ─────────────────────────────
        # When BOT_EOD_PATH=v162, EOD closes use `_eod_close_one_fast`
        # which SKIPS the v19.34.31 Patch B pre-close cancellation.
        # That patch queued 2 cancels per position (stop + target)
        # before firing the MKT close — at 10s timeout each on a
        # single-worker queue, 24 positions = up to 480s of cancel
        # work that completely blocked today's (2026-05-26) EOD pass
        # with 24 open positions.
        #
        # The pre-cancel is redundant for OCA-attached children: when
        # the MKT close fills, IB auto-cancels the survivor child
        # (that's what OCA *is*). The Patch B comment cites "OCA
        # bracket-stacking on 2026-05-14" but the v19.34.31 stacking
        # bug was rooted in adoption duplicate-attaches, not in
        # OCA-cancel timing on close. Skipping the pre-cancel is
        # safe; the orphan sweep at the end of EOD picks up anything
        # IB doesn't auto-cancel (extremely rare).
        #
        # Rollback: unset BOT_EOD_PATH (or set to anything other than
        # "v162") to revert to the legacy `close_trade` path.
        eod_path = _os.environ.get("BOT_EOD_PATH", "").lower().strip()
        use_fast_path = (eod_path == "v162")

        async def _close_one(tid_trade):
            tid, trade = tid_trade
            try:
                if use_fast_path:
                    logger.info(
                        f"  📤 EOD CLOSE [v162]: {trade.symbol} - "
                        f"{trade.direction.value} {trade.remaining_shares} shares"
                    )
                    ok, pnl = await self._eod_close_one_fast(tid, trade, bot)
                    return ("ok", pnl) if ok else ("fail", trade.symbol)
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

        # v19.34.154 — Sort by InitMarginReq proxy DESC (largest first).
        # Operator choice 3:43 ET defensive flatten 2a: close the largest-
        # margin positions first so each successful close maximally
        # restores Reg-T headroom before IBKR's 3:50 ET calc. For Reg-T
        # on stocks, InitMargin ≈ 50% of notional, so `shares × entry_px`
        # is a reliable proxy without needing a fresh IB account query.
        # Ties broken by symbol for deterministic test behaviour.
        def _margin_proxy(tt):
            _tid, _trade = tt
            try:
                shares = abs(int(getattr(_trade, "remaining_shares", 0)
                                  or getattr(_trade, "shares", 0)))
                px = float(getattr(_trade, "entry_price", 0)
                           or getattr(_trade, "entry_avg", 0)
                           or 0.0)
                return shares * px
            except Exception:
                return 0.0
        eod_items_sorted = sorted(
            eod_trades.items(),
            key=lambda kv: (-_margin_proxy(kv), kv[1].symbol),
        )
        results = await asyncio.gather(*(_close_one(p) for p in eod_items_sorted))
        closed_count = sum(1 for r in results if r[0] == "ok")
        total_pnl = sum(r[1] for r in results if r[0] == "ok")
        failed_symbols = [r[1] for r in results if r[0] == "fail"]

        # v19.34.162 — Post-flatten orphan-bracket sweep (fast-path only).
        # IB's OCA mechanism normally auto-cancels survivor children when
        # the MKT close fills, but a race / manual TWS edit can leave
        # orphans. The sweep queues cancels for any still-live child
        # orders — non-blocking, never blocks the close path.
        if use_fast_path:
            try:
                await self._eod_orphan_cancel_sweep(bot)
            except Exception as e:
                logger.warning(f"[v162 sweep] non-fatal: {e}")

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
        if bot._db is not None:
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
                # v19.34.152 — symmetric with the early-return paths.
                "early_exit_reason": None,
                "ib_position_count": len(self._ib_position_snapshot_safe()),
            }
            await asyncio.to_thread(bot._db.bot_events.insert_one, eod_event)

        if failed_symbols:
            logger.warning(f"⚠️ EOD AUTO-CLOSE PARTIAL: Closed {closed_count}, FAILED {len(failed_symbols)} ({', '.join(failed_symbols)}), Total P&L: ${total_pnl:+,.2f}")
        else:
            logger.info(f"✅ EOD AUTO-CLOSE COMPLETE: Closed {closed_count} positions, Total P&L: ${total_pnl:+,.2f}")

        # v19.34.151 — sweep runs unconditionally (not gated on
        # closed_count) because stale DAY LMT entries and naked
        # GTC brackets can exist EVEN when the EOD close path
        # closed zero positions. The pre-fix `if closed_count > 0`
        # guard left intraday LMT entries alive at 3:59 PM, which
        # could fill in the final minute and force a manual TWS
        # flatten (operator hit this 2026-05-13).
        # Fired as a background task: it has an 8s pusher-refresh
        # wait that shouldn't block the manage loop. Idempotent via
        # `_eod_sweep_executed_today` so re-entry is safe.
        asyncio.create_task(self._run_eod_orphan_sweep(bot))

    def _ib_position_snapshot_safe(self):
        """v19.34.152 — defensive read of IB live positions list.
        Returns [] on any failure. Used by the EOD-event recorder and
        the position-memory disagreement alarm."""
        try:
            from routers.ib import _pushed_ib_data
            return [
                p for p in (_pushed_ib_data.get("positions") or [])
                if isinstance(p, dict) and abs(float(p.get("position") or 0)) > 0
            ]
        except Exception:
            return []

    async def _persist_eod_event(
        self, bot: 'TradingBotService', today_str: str, now_et,
        *, closed: int, failed: list, total_pnl: float,
        is_half_day: bool, early_exit_reason,
        ib_position_count: int,
    ):
        """v19.34.152 — single helper for inserting the
        `bot_events.eod_auto_close` row. Used by both the main close
        path AND the early-return paths so postmortem ALWAYS finds an
        event for the day."""
        if bot._db is None:
            return
        try:
            await asyncio.to_thread(
                bot._db.bot_events.insert_one,
                {
                    "event_type": "eod_auto_close",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "date": today_str,
                    "positions_closed": closed,
                    "positions_failed": len(failed),
                    "failed_symbols": failed,
                    "total_pnl": total_pnl,
                    "is_half_day": is_half_day,
                    "close_time_et": now_et.strftime("%H:%M:%S"),
                    "early_exit_reason": early_exit_reason,
                    "ib_position_count": ib_position_count,
                },
            )
        except Exception as e:
            logger.warning(f"v19.34.152: failed to persist eod event: {e}")

    async def check_position_memory_disagreement(self, bot: 'TradingBotService'):
        """v19.34.152 — fires when IB has open positions the bot's
        `_open_trades` dict doesn't know about. This was the 2026-05-13
        incident root cause: bot's memory wiped (restart, persistence
        glitch, etc.) → EOD logic saw `_open_trades` empty → returned
        early → 14 IB positions held overnight.

        Algorithm:
          1. Snapshot live IB positions (abs(qty) > 0).
          2. For each, look it up in `bot._open_trades` by symbol.
          3. If absent, check `bot_trades` Mongo for a recent
             OPEN/PARTIAL row with `close_at_eod=False` — that's a
             legitimately-untracked SWING position (the bot might have
             dumped the in-memory cache but the DB row exists).
          4. Otherwise, this symbol is a TRUE disagreement → alarm.

        Dedup by date+symbol: each disagreement alarms ONCE per day
        per symbol so we don't spam the stream on every manage tick.
        """
        if not hasattr(bot, "_position_memory_alarmed"):
            bot._position_memory_alarmed = {}

        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        today_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")

        ib_positions = self._ib_position_snapshot_safe()
        if not ib_positions:
            return

        # Index bot in-memory open trades by symbol.
        bot_symbols = {
            (getattr(t, "symbol", "") or "").upper()
            for t in bot._open_trades.values()
        }

        # Pull bot_trades rows with status OPEN/PARTIAL for symbols
        # we don't have in memory — could be swing trades the bot is
        # legitimately holding without an in-memory entry.
        unknown = []
        for p in ib_positions:
            sym = (p.get("symbol") or "").upper()
            if not sym or sym in bot_symbols:
                continue
            try:
                qty = float(p.get("position") or 0)
            except (TypeError, ValueError):
                qty = 0.0
            unknown.append({"symbol": sym, "qty": qty})

        if not unknown:
            return

        # Cross-check Mongo for swing rows on those symbols.
        swing_known: set = set()
        if bot._db is not None:
            try:
                cursor = await asyncio.to_thread(
                    lambda: list(bot._db.bot_trades.find(
                        {
                            "symbol": {"$in": [u["symbol"] for u in unknown]},
                            "status": {"$in": ["open", "partial", "OPEN", "PARTIAL"]},
                            "close_at_eod": False,
                        },
                        {"_id": 0, "symbol": 1, "close_at_eod": 1},
                    ))
                )
                swing_known = {(r.get("symbol") or "").upper() for r in cursor}
            except Exception as e:
                logger.debug(f"v19.34.152: bot_trades swing lookup failed: {e}")

        true_disagreements = [u for u in unknown if u["symbol"] not in swing_known]
        if not true_disagreements:
            return

        # Per-day dedup so the alarm doesn't spam the stream.
        today_alarmed = bot._position_memory_alarmed.get(today_str, set())
        new_symbols = [
            u for u in true_disagreements if u["symbol"] not in today_alarmed
        ]
        if not new_symbols:
            return

        for u in new_symbols:
            today_alarmed.add(u["symbol"])
        bot._position_memory_alarmed[today_str] = today_alarmed

        # Clean old day-entries to bound memory.
        for old_date in list(bot._position_memory_alarmed.keys()):
            if old_date != today_str:
                bot._position_memory_alarmed.pop(old_date, None)

        logger.error(
            "🚨 [v19.34.152] POSITION-MEMORY DISAGREEMENT: %d IB position(s) "
            "NOT in bot._open_trades and NOT a known swing/position trade. "
            "These will NOT auto-close at EOD. Symbols: %s",
            len(new_symbols),
            [(u["symbol"], u["qty"]) for u in new_symbols],
        )

        # Stream alarm — CRITICAL severity always (auto-close miss).
        try:
            from services.sentcom_service import emit_stream_event
            await emit_stream_event({
                "kind": "alarm",
                "event": "position_memory_disagreement",
                "symbol": new_symbols[0]["symbol"] if len(new_symbols) == 1 else None,
                "text": (
                    f"🚨 [CRITICAL] IB has {len(new_symbols)} position(s) the "
                    f"bot doesn't know about: "
                    f"{', '.join(u['symbol'] for u in new_symbols[:5])}"
                    f"{'…' if len(new_symbols) > 5 else ''}. "
                    "EOD AUTO-CLOSE WILL MISS THESE. Adopt via "
                    "POST /api/trading-bot/adopt-ib-positions OR "
                    "manually flatten in TWS before close."
                ),
                "metadata": {
                    "symbols": [u["symbol"] for u in new_symbols],
                    "qtys": {u["symbol"]: u["qty"] for u in new_symbols},
                    "severity": "CRITICAL",
                },
            })
        except Exception as alarm_err:
            logger.warning(f"v19.34.152 alarm emit failed: {alarm_err}")

    # ── v19.34.153 (P0 EOD ghost-flatten) ────────────────────────────────
    # The 2026-05-XX incident: EOD auto-close fired at 3:55 ET, closed
    # 3 of 23 IB-side positions, then stalled. The remaining 20 stayed
    # open because they were "ghosts" — filled at IB but missing from
    # `bot._open_trades` (broken bracket plumbing dropped them). The
    # existing `check_position_memory_disagreement` flagged this but
    # only alarmed — it never actually closed the positions.
    #
    # These three helpers fix that:
    #   * `_recent_swing_symbols_safe`  — tight swing exception (today/
    #     yesterday entry only, per operator choice 3B).
    #   * `_flatten_ghost_positions`    — finds ghosts + fires emergency
    #     MKT closes via the new `place_emergency_mkt_close` path.
    #   * `_eod_t_minus_2_escalate`     — at T-2 min (3:58 ET / 12:58 ET
    #     on half-days), forces a MKT close on any tracked intraday
    #     trade still open.
    #   * `_eod_t_minus_1_alert`        — at T-1 min, persistent operator
    #     alert if anything remains open.

    async def _recent_swing_symbols_safe(
        self, bot: 'TradingBotService',
        symbols: list,
    ) -> set:
        """v19.34.153 — Return set of symbols that legitimately should
        be held overnight as swing/position trades. Tighter than the
        v19.34.152 disagreement-checker: requires `close_at_eod=False`
        AND an `executed_at` within the last ~48h. This prevents stale
        / abandoned swing rows from masking a genuine ghost.
        """
        if not bot._db or not symbols:
            return set()
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        try:
            cursor = await asyncio.to_thread(
                lambda: list(bot._db.bot_trades.find(
                    {
                        "symbol": {"$in": [s.upper() for s in symbols]},
                        "status": {"$in": ["open", "partial", "OPEN", "PARTIAL"]},
                        "close_at_eod": False,
                        "executed_at": {"$gte": cutoff},
                    },
                    {"_id": 0, "symbol": 1},
                ))
            )
            return {(r.get("symbol") or "").upper() for r in cursor}
        except Exception as e:
            logger.debug(f"v19.34.153: recent_swing lookup failed: {e}")
            return set()

    async def _flatten_ghost_positions(
        self, bot: 'TradingBotService',
        *,
        reason: str = "eod_ghost_flatten",
    ) -> dict:
        """v19.34.153 — Snapshot IB ground truth, find symbols held at
        IB but missing from `bot._open_trades` AND not a recent swing,
        then fire an emergency MKT close for each. Returns a summary
        dict for logging / persistence.

        ALWAYS-RUN (operator choice 2B): not gated by
        `_eod_close_executed_today` — retries every manage tick until
        IB shows flat. Per-symbol-per-day dedup via
        `_ghost_flatten_fired` keeps the order rate sane.
        """
        if not hasattr(bot, "_ghost_flatten_fired"):
            bot._ghost_flatten_fired = {}

        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        today_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")

        # Clean stale day-buckets to bound memory.
        for old_date in list(bot._ghost_flatten_fired.keys()):
            if old_date != today_str:
                bot._ghost_flatten_fired.pop(old_date, None)
        fired_today = bot._ghost_flatten_fired.setdefault(today_str, {})

        ib_positions = self._ib_position_snapshot_safe()
        if not ib_positions:
            return {"ghosts_found": 0, "flattened": [], "skipped": [], "errors": []}

        bot_symbols = {
            (getattr(t, "symbol", "") or "").upper()
            for t in bot._open_trades.values()
        }

        # Unknown candidates = IB positions not in bot memory.
        candidates = []
        for p in ib_positions:
            sym = (p.get("symbol") or "").upper()
            if not sym or sym in bot_symbols:
                continue
            try:
                qty = float(p.get("position") or 0)
            except (TypeError, ValueError):
                qty = 0.0
            if abs(qty) < 1:
                continue
            candidates.append({"symbol": sym, "qty": qty})

        if not candidates:
            return {"ghosts_found": 0, "flattened": [], "skipped": [], "errors": []}

        # Tight swing exception — today/yesterday entries only.
        swing_safe = await self._recent_swing_symbols_safe(
            bot, [c["symbol"] for c in candidates]
        )

        ghosts = [c for c in candidates if c["symbol"] not in swing_safe]
        skipped = [c for c in candidates if c["symbol"] in swing_safe]

        if not ghosts:
            return {"ghosts_found": 0, "flattened": [], "skipped": skipped, "errors": []}

        logger.error(
            "🚨 [v19.34.153 GHOST-FLATTEN] %d ghost(s) detected: %s — firing "
            "emergency MKT closes (reason=%s).",
            len(ghosts),
            [(g["symbol"], int(g["qty"])) for g in ghosts],
            reason,
        )

        # Lazy import the direct service.
        try:
            from services.ib_direct_service import get_ib_direct_service
        except Exception as e:
            logger.error(f"v19.34.153: ib_direct_service import failed: {e}")
            return {
                "ghosts_found": len(ghosts), "flattened": [],
                "skipped": skipped,
                "errors": [{"symbol": "*", "error": "ib_direct_import_failed"}],
            }
        svc = get_ib_direct_service()
        if not (svc.is_available() and svc.is_connected()):
            logger.error(
                "v19.34.153: ib_direct not connected — cannot flatten %d "
                "ghost(s).", len(ghosts),
            )
            try:
                await bot._broadcast_event({
                    "type": "eod_ghost_flatten_blocked",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "ghosts": [(g["symbol"], int(g["qty"])) for g in ghosts],
                    "reason": "ib_direct_not_connected",
                })
            except Exception:
                pass
            return {
                "ghosts_found": len(ghosts), "flattened": [],
                "skipped": skipped,
                "errors": [{"symbol": "*", "error": "ib_direct_not_connected"}],
            }

        flattened: list = []
        errors: list = []

        async def _flatten_one(ghost):
            sym = ghost["symbol"]
            qty = ghost["qty"]
            # Per-symbol-per-day fire cap: if we already fired AND it
            # was filled, skip; otherwise retry up to 3x.
            prev = fired_today.get(sym, {"fires": 0, "filled": False})
            if prev.get("filled"):
                return None
            if prev.get("fires", 0) >= 3:
                return {"symbol": sym, "error": "max_retries_exceeded",
                        "fires": prev.get("fires")}
            action = "SELL" if qty > 0 else "BUY"
            try:
                result = await svc.place_emergency_mkt_close(
                    symbol=sym,
                    qty=int(abs(round(qty))),
                    action=action,
                    wait_for_fill_s=8.0,
                )
            except Exception as fe:
                result = {"success": False, "error": f"flatten_exception: {fe}"}
            prev["fires"] = prev.get("fires", 0) + 1
            prev["last_status"] = result.get("status")
            prev["last_order_id"] = result.get("order_id")
            prev["filled"] = bool(result.get("success") and
                                  result.get("status") == "filled")
            fired_today[sym] = prev
            return {
                "symbol": sym,
                "qty": qty,
                "action": action,
                "result": result,
            }

        outcomes = await asyncio.gather(
            *[_flatten_one(g) for g in ghosts],
            return_exceptions=False,
        )
        for o in outcomes:
            if o is None:
                continue
            if o.get("error"):
                errors.append(o)
            elif o.get("result", {}).get("success"):
                flattened.append(o)
            else:
                errors.append({
                    "symbol": o["symbol"],
                    "error": o.get("result", {}).get("error", "unknown"),
                    "status": o.get("result", {}).get("status"),
                })

        # Persist a bot_event row for postmortem.
        if bot._db is not None:
            try:
                await asyncio.to_thread(
                    bot._db.bot_events.insert_one,
                    {
                        "event_type": "eod_ghost_flatten",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "date": today_str,
                        "reason": reason,
                        "ghosts_found": len(ghosts),
                        "flattened_count": len(flattened),
                        "error_count": len(errors),
                        "flattened": [
                            {
                                "symbol": f["symbol"],
                                "qty": f["qty"],
                                "action": f["action"],
                                "order_id": f.get("result", {}).get("order_id"),
                                "status": f.get("result", {}).get("status"),
                            }
                            for f in flattened
                        ],
                        "errors": errors,
                        "skipped_swing": [s["symbol"] for s in skipped],
                    },
                )
            except Exception as pe:
                logger.warning(f"v19.34.153: ghost_flatten persist failed: {pe}")

        # Stream alarm.
        try:
            await bot._broadcast_event({
                "type": "eod_ghost_flatten",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
                "ghosts_found": len(ghosts),
                "flattened": [(f["symbol"], int(f["qty"])) for f in flattened],
                "errors": errors,
                "skipped_swing": [s["symbol"] for s in skipped],
            })
        except Exception:
            pass

        return {
            "ghosts_found": len(ghosts),
            "flattened": flattened,
            "skipped": skipped,
            "errors": errors,
        }

    async def _eod_t_minus_2_escalate(
        self, bot: 'TradingBotService',
    ) -> dict:
        """v19.34.153 — At T-2 min before market close, force MKT close
        on any tracked intraday trade still open. Idempotent via
        `_eod_t_minus_2_fired_today`.
        """
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        today_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        if getattr(bot, "_eod_t_minus_2_fired_today", None) == today_str:
            return {"escalated": [], "errors": [], "noop": True}

        still_open = [
            (tid, t) for tid, t in list(bot._open_trades.items())
            if getattr(t, "close_at_eod", True)
        ]
        if not still_open:
            bot._eod_t_minus_2_fired_today = today_str
            return {"escalated": [], "errors": [], "noop": True}

        logger.error(
            "🚨 [v19.34.153 T-2 ESCALATE] %d intraday trade(s) still open at "
            "T-2 min — forcing MKT closes: %s",
            len(still_open),
            [t.symbol for _tid, t in still_open],
        )

        escalated: list = []
        errors: list = []
        async def _force_close(tid_trade):
            tid, trade = tid_trade
            try:
                ok = await self.close_trade(tid, bot, reason="eod_t_minus_2_force_mkt")
                if ok:
                    escalated.append(trade.symbol)
                else:
                    errors.append({"symbol": trade.symbol, "error": "close_trade_returned_false"})
            except Exception as e:
                errors.append({"symbol": getattr(trade, "symbol", "?"),
                               "error": f"close_exception: {str(e)[:160]}"})

        await asyncio.gather(*[_force_close(tt) for tt in still_open],
                             return_exceptions=False)
        bot._eod_t_minus_2_fired_today = today_str

        if bot._db is not None:
            try:
                await asyncio.to_thread(
                    bot._db.bot_events.insert_one,
                    {
                        "event_type": "eod_t_minus_2_escalate",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "date": today_str,
                        "escalated": escalated,
                        "errors": errors,
                    },
                )
            except Exception as pe:
                logger.warning(f"v19.34.153: t-2 persist failed: {pe}")
        try:
            await bot._broadcast_event({
                "type": "eod_t_minus_2_escalate",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "escalated": escalated,
                "errors": errors,
            })
        except Exception:
            pass
        return {"escalated": escalated, "errors": errors}

    async def _eod_t_minus_1_alert(
        self, bot: 'TradingBotService',
    ) -> None:
        """v19.34.153 — Loud operator alert at T-1 min if ANY position
        (tracked or ghost) is still open. Idempotent per day."""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        today_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        if getattr(bot, "_eod_t_minus_1_alerted_today", None) == today_str:
            return

        ib_positions = self._ib_position_snapshot_safe()
        tracked_open = [
            t for t in bot._open_trades.values()
            if getattr(t, "close_at_eod", True)
        ]
        ib_open = [
            (p.get("symbol"), float(p.get("position") or 0))
            for p in ib_positions
            if abs(float(p.get("position") or 0)) > 0
        ]
        if not tracked_open and not ib_open:
            bot._eod_t_minus_1_alerted_today = today_str
            return

        logger.error(
            "🚨 [v19.34.153 T-1 ALERT] Market closes in ~60s. tracked_open=%d "
            "ib_open=%d  tracked=%s  ib=%s",
            len(tracked_open), len(ib_open),
            [t.symbol for t in tracked_open],
            ib_open,
        )
        bot._eod_t_minus_1_alerted_today = today_str
        if bot._db is not None:
            try:
                await asyncio.to_thread(
                    bot._db.bot_events.insert_one,
                    {
                        "event_type": "eod_t_minus_1_alert",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "date": today_str,
                        "tracked_open": [t.symbol for t in tracked_open],
                        "ib_open": ib_open,
                    },
                )
            except Exception as pe:
                logger.warning(f"v19.34.153: t-1 persist failed: {pe}")
        try:
            await bot._broadcast_event({
                "type": "eod_t_minus_1_alert",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tracked_open": [t.symbol for t in tracked_open],
                "ib_open": ib_open,
                "severity": "CRITICAL",
            })
        except Exception:
            pass
        try:
            from services.sentcom_service import emit_stream_event
            await emit_stream_event({
                "kind": "alarm",
                "event": "eod_t_minus_1_alert",
                "text": (
                    f"🚨 [CRITICAL T-1] {len(tracked_open)} tracked + "
                    f"{len(ib_open)} IB position(s) still open with <60s to "
                    "close. CHECK TWS NOW."
                ),
                "metadata": {
                    "tracked": [t.symbol for t in tracked_open],
                    "ib": ib_open,
                    "severity": "CRITICAL",
                },
            })
        except Exception:
            pass

    async def _run_eod_orphan_sweep(self, bot: 'TradingBotService'):
        """v19.34.151 — runs the orphan-order + pending-intraday-entry
        sweep ONCE per trading day, regardless of whether any positions
        actually closed in `check_eod_close`.

        Covers two categories:
          1. **Orphan GTC brackets** — protective legs whose underlying
             position vanished (already handled pre-v19.34.151 via the
             existing `audit_orphan_gtc_orders` flow; preserved here).
          2. **Pending DAY LMT entries for intraday trades** (NEW) —
             unfilled entry orders for setups flagged
             `close_at_eod=True`. Pre-fix these would sit at IB until
             4:00 PM and could fill in the final 5 minutes of session
             with no time to manage. Swing / position trades
             (`close_at_eod=False`) are EXPLICITLY EXCLUDED from the
             sweep — they're meant to fill overnight / next-session.

        Idempotent: once per UTC date via `_eod_sweep_executed_today`.
        Failures are logged at WARNING, never raised — the manage loop
        must stay alive.
        """
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo

        now_et = datetime.now(ZoneInfo("America/New_York"))
        today_str = now_et.strftime("%Y-%m-%d")

        # Per-day flag — initialise on first call (older bots persisted
        # via `bot_persistence.py` may not have this attr yet).
        if not hasattr(bot, "_eod_sweep_executed_today"):
            bot._eod_sweep_executed_today = False
            bot._last_eod_sweep_date = None

        if getattr(bot, "_last_eod_sweep_date", None) != today_str:
            bot._eod_sweep_executed_today = False
            bot._last_eod_sweep_date = today_str

        if bot._eod_sweep_executed_today:
            return

        # Honour the same kill-switch as the auto-sweep loop.
        auto_sweep_enabled = os.environ.get(
            "AUTO_SWEEP_ORPHAN_GTC", "true",
        ).strip().lower() in ("1", "true", "yes", "on")
        if not auto_sweep_enabled:
            return

        try:
            # Give pusher ~8s to publish a fresh orders snapshot
            # reflecting the closes we just fired (push interval = 10s
            # + IB roundtrip).
            await asyncio.sleep(8)

            from services.orphan_gtc_reconciler import (
                SAFE_TO_AUTO_CANCEL,
                OrderVerdict,
                audit_orphan_gtc_orders,
                cancel_orphan_gtc_orders,
                classify_intraday_entries_for_eod_sweep,
                _fetch_ib_open_orders,
                _fetch_bot_trades,
            )

            # Path A: existing orphan-GTC audit (naked brackets, etc.).
            audit = await audit_orphan_gtc_orders(bot=bot, only_gtc=False)
            safe_to_cancel: list = []
            if audit.get("success"):
                for raw in audit.get("verdicts") or []:
                    if not isinstance(raw, dict):
                        continue
                    if raw.get("verdict") not in SAFE_TO_AUTO_CANCEL:
                        continue
                    try:
                        safe_to_cancel.append(OrderVerdict(
                            ib_order_id=int(raw.get("ib_order_id") or 0),
                            perm_id=raw.get("perm_id"),
                            symbol=raw.get("symbol") or "",
                            action=raw.get("action") or "",
                            quantity=int(raw.get("quantity") or 0),
                            order_type=raw.get("order_type") or "",
                            limit_price=raw.get("limit_price"),
                            stop_price=raw.get("stop_price"),
                            time_in_force=raw.get("time_in_force") or "",
                            status=raw.get("status") or "",
                            verdict=raw.get("verdict") or "",
                            reasons=list(raw.get("reasons") or []),
                            bot_trade_id=raw.get("bot_trade_id"),
                            ib_position_size=raw.get("ib_position_size"),
                            submitted_at=raw.get("submitted_at"),
                        ))
                    except Exception:
                        continue

            # Path B (v19.34.151): pending intraday DAY entry orders.
            try:
                ib_orders_for_eod, _src = await _fetch_ib_open_orders()
                bot_trades_for_eod, _bt_src = _fetch_bot_trades(bot)
                intraday_verdicts = classify_intraday_entries_for_eod_sweep(
                    ib_open_orders=ib_orders_for_eod or [],
                    bot_trades=bot_trades_for_eod or [],
                )
                if intraday_verdicts:
                    logger.warning(
                        "[v19.34.151 EOD-SWEEP] %d pending intraday entry "
                        "order(s) flagged for cancel: %s",
                        len(intraday_verdicts),
                        [(v.symbol, v.ib_order_id) for v in intraday_verdicts[:10]],
                    )
                # Dedupe by ib_order_id — defensive against any path
                # overlap with the GTC audit above.
                existing_oids = {v.ib_order_id for v in safe_to_cancel}
                for v in intraday_verdicts:
                    if v.ib_order_id not in existing_oids:
                        safe_to_cancel.append(v)
                        existing_oids.add(v.ib_order_id)
            except Exception as ie:
                logger.warning(
                    "[v19.34.151 EOD-SWEEP] intraday-entry classify failed "
                    "(non-fatal): %s", ie,
                )

            if not safe_to_cancel:
                logger.info(
                    "[v19.34.151 EOD-SWEEP] no safe-to-cancel orders "
                    "(orphan GTCs or pending intraday entries) — clean EOD."
                )
                bot._eod_sweep_executed_today = True
                return

            logger.warning(
                "[v19.34.151 EOD-SWEEP] firing sweep for %d "
                "order(s): %s",
                len(safe_to_cancel),
                [(v.symbol, v.ib_order_id, v.verdict)
                 for v in safe_to_cancel[:10]],
            )
            sweep = await cancel_orphan_gtc_orders(
                verdicts_to_cancel=safe_to_cancel,
            )
            n_ok = len(sweep.get("cancelled") or [])
            n_err = len(sweep.get("errors") or [])
            logger.warning(
                "[v19.34.151 EOD-SWEEP] queued=%d errors=%d", n_ok, n_err,
            )

            # WS notify so V5 HUD can confirm sweep ran.
            try:
                await bot._broadcast_event({
                    "type": "eod_orphan_sweep",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "queued": n_ok,
                    "errors": n_err,
                    "details": sweep.get("cancelled") or [],
                })
            except Exception:
                pass

            # Persist for the postmortem endpoint.
            if bot._db is not None:
                try:
                    await asyncio.to_thread(
                        bot._db.bot_events.insert_one,
                        {
                            "event_type": "eod_orphan_sweep",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "date": today_str,
                            "queued": n_ok,
                            "errors": n_err,
                            "details": sweep.get("cancelled") or [],
                            "verdicts_summary": {
                                v.verdict: sum(
                                    1 for x in safe_to_cancel
                                    if x.verdict == v.verdict
                                )
                                for v in safe_to_cancel
                            },
                        },
                    )
                except Exception:
                    pass

            bot._eod_sweep_executed_today = True
        except Exception as sweep_err:
            logger.warning(
                "[v19.34.151 EOD-SWEEP] failed (non-fatal): %s", sweep_err,
            )

    async def check_and_execute_scale_out(self, trade: 'BotTrade', bot: 'TradingBotService'):
        """
        Check if any target prices are hit and execute scale-out sells.
        Sells 1/3 at Target 1, 1/3 at Target 2, keeps 1/3 for Target 3 (runner).
        """
        from services.trading_bot_service import TradeDirection, TradeStatus

        if not trade.target_prices or trade.remaining_shares <= 0:
            return

        # M0 (2026-06) — trades with an IB-resident leg ladder must NEVER
        # fire bot-side scale-out sells: the exits already live AT IB as
        # per-leg OCA pairs, and a duplicate LMT here recreates the
        # v19.34.7 STX double-sell/flip bug class. m0_ladder_manager owns
        # the lifecycle for these trades.
        if (getattr(trade, "scale_out_config", None) or {}).get("m0_legs"):
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

                    # v19.34.184 — surface scale-out / target hits to Mission
                    # Control's Position lane (kind=info so the classifier keeps
                    # it in Position, not Execution; success severity derives
                    # from the `target_hit` action_type).
                    try:
                        from services.sentcom_service import emit_stream_event
                        await emit_stream_event({
                            "kind": "info",
                            "event": "target_hit",
                            "symbol": trade.symbol,
                            "text": (
                                f"🎯 {trade.symbol} T{i+1} hit @ ${fill_price:.2f} — "
                                f"sold {shares_to_sell}sh, P&L ${partial_pnl:+.2f}, "
                                f"{trade.remaining_shares}sh left"
                            ),
                            "metadata": {"source": "position_manager",
                                         "target_idx": i + 1,
                                         "fill_price": fill_price,
                                         "partial_pnl": partial_pnl},
                        })
                    except Exception:
                        pass

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

        v19.34.49 (2026-02-XX) — REQUIRE POSITIVE MULTI-SOURCE
        CONFIRMATION before phantom-recovering. Operator-discovered
        2026-05-07: bot reported "FLATTEN COMPLETE 20/20" while IB
        still had 4,436 BMNR + 555 PG. Every close was rejected with
        IB Error 201 but the bot saw direct-IB `get_positions()`
        returning `[]` (empty — direct IB clientId=11 had just
        connected and hadn't received position events yet) and
        misinterpreted that as "position is 0" → phantom-recovered
        every trade locally without sending real close MKTs. EBAY had
        the same divergence (276 shares falsely phantom-recovered
        while IB held all 901).

        Decision tree for the "ib_abs == 0" branch:
          1. If direct positions list is EMPTY → snapshot unreliable,
             fall back to intended_shares (let close MKT fire for real).
          2. If pusher is alive AND pusher's snapshot shows shares for
             this symbol → disagreement, prefer pusher's authoritative
             ledger, fall back to intended_shares.
          3. Only when direct list is non-empty (proving direct IB is
             responding with real data) AND symbol not present → that's
             positive confirmation of zero. Phantom-recover.

        For the BMNR-style partial-clamp (ib_abs < intended), same
        logic applies: cross-check pusher; if pusher shows MORE shares
        than direct, trust pusher (likely direct IB is mid-update).
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

        # Find the symbol's signed position via direct IB (sum across
        # accounts is fine — operator runs single-account so this is
        # always 1 row).
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

        # ── v19.34.49 — Cross-check pusher (authoritative for this user). ─
        pusher_signed: Optional[float] = None
        pusher_alive = False
        try:
            from routers.ib import _pushed_ib_data, is_pusher_connected
            pusher_alive = bool(is_pusher_connected())
            if pusher_alive:
                ps = 0.0
                for p in (_pushed_ib_data.get("positions") or []):
                    if (p.get("symbol") or "").upper() == trade.symbol.upper():
                        ps += float(p.get("position") or 0)
                pusher_signed = ps
        except Exception:
            pass

        if ib_abs == 0:
            # ── v19.34.49 — confirmation gates ────────────────────────
            #   Gate 1: direct list must be non-empty (proves direct IB
            #     is responding with real data; `[]` could mean stale).
            #   Gate 2: if pusher alive and disagrees (shows shares),
            #     trust pusher and DON'T phantom-recover.
            direct_snapshot_reliable = bool(positions)
            pusher_confirms_zero = (
                pusher_signed is None or abs(pusher_signed) < 0.5
            )
            if not direct_snapshot_reliable:
                logger.warning(
                    f"[v19.34.49 PHANTOM-GUARD] {trade.symbol} close_trade("
                    f"reason={reason}) direct IB returned EMPTY positions list "
                    f"— refusing to phantom-recover. Falling back to "
                    f"intended {intended_shares}sh; close MKT will fire."
                )
                return intended_shares
            if pusher_alive and not pusher_confirms_zero:
                logger.warning(
                    f"[v19.34.49 PHANTOM-GUARD] {trade.symbol} close_trade("
                    f"reason={reason}) direct IB shows ZERO but pusher shows "
                    f"{pusher_signed:+.0f} sh — disagreement, refusing to "
                    f"phantom-recover. Falling back to intended {intended_shares}sh; "
                    f"close MKT will fire."
                )
                return intended_shares
            logger.warning(
                f"[v19.34.27 PHANTOM] {trade.symbol} close_trade(reason={reason}) "
                f"clamped {intended_shares}→0: IB shows ZERO position "
                f"(direct positions={len(positions)} rows, pusher_signed="
                f"{pusher_signed}, pusher_alive={pusher_alive}). Trade "
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
        # v19.34.49: if pusher alive and shows MORE shares than direct,
        # trust pusher (direct IB may be mid-update).
        if pusher_alive and pusher_signed is not None:
            pusher_abs = int(abs(round(pusher_signed)))
            if pusher_abs > ib_abs:
                logger.warning(
                    f"[v19.34.49 PHANTOM-GUARD] {trade.symbol} close_trade("
                    f"reason={reason}) direct IB={ib_abs} but pusher={pusher_abs} "
                    f"— trusting pusher (direct may be mid-update). "
                    f"Returning min(intended={intended_shares}, pusher_abs={pusher_abs})."
                )
                return min(intended_shares, pusher_abs)
        logger.warning(
            f"[v19.34.27 PHANTOM] {trade.symbol} close_trade(reason={reason}) "
            f"clamped {intended_shares}→{ib_abs}: bot tracked "
            f"{intended_shares}sh, IB authoritative position is {ib_abs}sh "
            f"({ib_signed:+.0f} signed). Closing only what IB actually holds."
        )
        return ib_abs

    # ── v19.34.298 — Audit Phase 6 (L1+L2): learning-store hygiene + coverage ──
    # L1: the `trade_outcomes` store (AI confidence-gate calibration + tilt) must
    #     learn ONLY from GENUINE strategy closes (target/stop/trail/EOD/time-
    #     decay) — NOT phantom/reconciled/operator-flatten/external-unwind
    #     artifacts (Phase 6 finding). Same `classify_close` hygiene the
    #     alert_outcomes EV feed already applies.
    # L2: route v162 fast-EOD closes (which bypassed BOTH stores) into the
    #     learning loop so EOD + time-decay closes still teach target/stop/decay.
    # Reversible: LEARNING_HYGIENE_FILTER=false → record every close (legacy).
    def _is_genuine_close_for_learning(self, trade, reason: str):
        """Return (genuine: bool, tag: str). GENUINE = real strategy exit worth
        teaching the ML gate. Fail-OPEN (genuine) on any error so a hygiene bug
        never silently starves the learning loop."""
        try:
            import os as _os
            if _os.environ.get("LEARNING_HYGIENE_FILTER", "true").lower() != "true":
                return True, "hygiene_disabled"
            from services.trade_outcome_hygiene import classify_close
            from services.pnl_compute import _hold_seconds
            d_obj = getattr(trade, "direction", None)
            d = getattr(d_obj, "value", str(d_obj) if d_obj else "long").lower()
            tps = getattr(trade, "target_prices", None)
            if not tps:
                _t1 = getattr(trade, "tp_price", None) or getattr(trade, "target", None)
                tps = [_t1] if _t1 else []
            return classify_close(
                close_reason=reason,
                entered_by=str(getattr(trade, "entered_by", "") or ""),
                entry_price=float(getattr(trade, "fill_price", 0) or 0),
                exit_price=float(getattr(trade, "exit_price", 0) or 0),
                net_pnl=float(getattr(trade, "net_pnl", 0) or 0),
                hold_seconds=_hold_seconds(trade),
                setup_type=str(getattr(trade, "setup_type", "") or ""),
                direction=d,
                stop_price=float(getattr(trade, "stop_price", 0) or getattr(trade, "stop_loss", 0) or 0),
                target_prices=tps,
                realized_pnl=float(getattr(trade, "realized_pnl", 0) or 0),
                shares=getattr(trade, "shares", None),
            )
        except Exception:
            return True, "genuine_fail_open"

    def _record_learning_outcome(self, bot, trade, reason: str):
        """Feed the ML learning store (`trade_outcomes` → AI confidence-gate
        calibration + tilt) for a GENUINE close ONLY (L1). Shared by close_trade
        and the v162 fast-EOD path (L2) so EOD + time-decay closes still teach the
        model while phantom/reconciled artifacts are kept out. Fire-and-forget;
        never blocks the close."""
        if not (hasattr(bot, "_learning_loop") and bot._learning_loop):
            return
        genuine, tag = self._is_genuine_close_for_learning(trade, reason)
        if not genuine:
            logger.debug(
                "[v298 Phase6 L1] learning outcome SKIPPED for %s (reason=%s, %s)",
                getattr(trade, "symbol", "?"), reason, tag,
            )
            return
        try:
            outcome = "won" if trade.realized_pnl > 0 else ("lost" if trade.realized_pnl < 0 else "breakeven")
            _ec = getattr(trade, "entry_context", None)
            _ec = _ec if isinstance(_ec, dict) else {}
            _gate_ctx = _ec.get("confidence_gate") if isinstance(_ec.get("confidence_gate"), dict) else {}
            _decision_id = _gate_ctx.get("decision_id")  # v19.34.311b: exact gate attribution
            asyncio.create_task(bot._learning_loop.record_trade_outcome(
                trade_id=trade.id,
                alert_id=trade.alert_id or trade.id,
                symbol=trade.symbol,
                setup_type=trade.setup_type,
                strategy_name=trade.setup_type,
                direction=trade.direction.value if hasattr(trade.direction, 'value') else str(trade.direction),
                trade_style=getattr(trade, 'trade_style', 'move_2_move'),
                entry_price=trade.fill_price,
                exit_price=trade.exit_price,
                stop_price=trade.stop_price,
                target_price=trade.target_prices[0] if trade.target_prices else trade.fill_price * 1.02,
                outcome=outcome,
                pnl=trade.realized_pnl,
                entry_time=getattr(trade, 'executed_at', None) or getattr(trade, 'created_at', None),
                exit_time=trade.closed_at,
                confirmation_signals=getattr(trade, 'confirmation_signals', []),
                catalyst_tag=_ec.get("catalyst_tag", ""),
                gap_pct=_ec.get("gap_pct", 0.0),
                gate_decision_id=_decision_id,
            ))
        except Exception as e:
            logger.warning(f"[v298] Failed to record trade to learning loop: {e}")


    # ── v19.34.162 EOD fast-path ────────────────────────────────────────
    async def _eod_close_one_fast(
        self, trade_id: str, trade, bot: 'TradingBotService'
    ):
        """Skinny EOD close that fires MKT immediately, no pre-cancel.

        Rationale: today's (2026-05-26) EOD pass froze with 24 positions
        still open. Root cause was the v19.34.31 Patch B pre-close
        cancellation: it queued 2 IB cancels per position on a
        1-worker, 10s-timeout queue. With 24 positions = 48 cancels ×
        10s = up to 480s of cancel work blocking the actual flatten.

        IB's OCA mechanism auto-cancels surviving child orders when
        the parent fills. We don't pre-cancel — the broker does it for
        us as soon as our MKT close fills.

        Returns ``(ok: bool, realized_pnl: float)``.
        """
        from services.trading_bot_service import TradeDirection, TradeStatus

        if trade_id not in bot._open_trades:
            return False, 0.0

        shares_to_close = (
            trade.remaining_shares
            if trade.remaining_shares > 0
            else trade.shares
        )

        # v19.34.27 phantom-share clamp — preserved verbatim.
        try:
            shares_to_close = await self._clamp_shares_to_ib_position(
                trade, shares_to_close, reason="eod_auto_close_v162"
            )
        except Exception as clamp_err:
            logger.debug(
                f"_eod_close_one_fast: phantom-share clamp errored for "
                f"{trade.symbol} ({clamp_err}); using bot-tracked count "
                f"{shares_to_close}"
            )

        if shares_to_close == 0:
            logger.warning(
                f"[v162 EOD] {trade.symbol}: clamped to 0 shares (phantom), "
                f"marking trade {trade_id} CLOSED locally."
            )
            from services.pnl_compute import apply_close_pnl
            apply_close_pnl(
                trade,
                reason="eod_auto_close_v162_phantom_recovery",
                exit_price=getattr(trade, "current_price", None),
            )
            trade.status = TradeStatus.CLOSED
            del bot._open_trades[trade_id]
            bot._closed_trades.append(trade)
            try:
                await bot._save_trade(trade)
            except Exception:
                pass
            return True, getattr(trade, "realized_pnl", 0.0)

        try:
            original_shares = trade.shares
            trade.shares = shares_to_close

            if not bot._trade_executor:
                logger.error(
                    f"[v162 EOD] {trade.symbol}: bot._trade_executor is None — "
                    f"cannot place MKT close. Operator must flatten in TWS."
                )
                trade.shares = original_shares
                return False, 0.0

            result = await bot._trade_executor.close_position(trade)
            trade.shares = original_shares

            if not result.get("success"):
                err = result.get("error", "unknown")
                logger.error(
                    f"[v162 EOD] {trade.symbol}: executor refused MKT close "
                    f"({shares_to_close}sh): {err}"
                )
                try:
                    trade._last_close_error = str(err)[:300]
                    trade._last_close_error_at = datetime.now(timezone.utc).isoformat()
                except Exception:
                    pass
                return False, 0.0

            trade.exit_price = result.get("fill_price", trade.current_price)

            if trade.direction == TradeDirection.LONG:
                final_pnl = (trade.exit_price - trade.fill_price) * shares_to_close
            else:
                final_pnl = (trade.fill_price - trade.exit_price) * shares_to_close
            trade.realized_pnl += final_pnl
            try:
                bot._apply_commission(trade, shares_to_close)
            except Exception:
                pass

            trade.status = TradeStatus.CLOSED
            trade.closed_at = datetime.now(timezone.utc).isoformat()
            trade.close_reason = "eod_auto_close_v162"
            trade.unrealized_pnl = 0
            trade.remaining_shares = 0

            bot._daily_stats.net_pnl += trade.net_pnl
            if trade.realized_pnl > 0:
                bot._daily_stats.trades_won += 1
                bot._daily_stats.largest_win = max(
                    bot._daily_stats.largest_win, trade.realized_pnl
                )
            else:
                bot._daily_stats.trades_lost += 1
                bot._daily_stats.largest_loss = min(
                    bot._daily_stats.largest_loss, trade.realized_pnl
                )
            total = bot._daily_stats.trades_won + bot._daily_stats.trades_lost
            bot._daily_stats.win_rate = (
                bot._daily_stats.trades_won / total * 100
            ) if total > 0 else 0

            del bot._open_trades[trade_id]
            bot._closed_trades.append(trade)

            try:
                await bot._save_trade(trade)
            except Exception as e:
                logger.warning(f"[v162 EOD] {trade.symbol} save failed: {e}")
            try:
                if bot._db is not None:
                    bot._db.bracket_lifecycle_events.insert_one({
                        "phase": "eod_flatten_v162",
                        "success": True,
                        "trade_id": trade_id,
                        "symbol": trade.symbol,
                        "shares_closed": shares_to_close,
                        "exit_price": trade.exit_price,
                        "realized_pnl": trade.realized_pnl,
                        "created_at": datetime.now(timezone.utc),
                    })
            except Exception:
                pass

            # v19.34.298 (Audit Phase 6 L2) — v162 fast-EOD previously fed NEITHER
            # outcome store, so EOD closes taught the bot nothing under this path.
            # Now mirror close_trade: write the alert_outcomes row (→ strategy_stats
            # EV / TQS Setup pillar — itself genuine-gated inside) AND feed the ML
            # learning store (hygiene-gated). EOD is a GENUINE strategy exit.
            try:
                from services.pnl_compute import _record_alert_outcome_bestEffort
                _record_alert_outcome_bestEffort(
                    trade,
                    "eod_auto_close_v162",
                    {"realized_pnl": float(getattr(trade, "realized_pnl", 0) or 0),
                     "net_pnl":      float(getattr(trade, "net_pnl", 0) or 0),
                     "shares":       int(shares_to_close or 0)},
                    float(getattr(trade, "exit_price", 0) or 0),
                    "eod_close_v162",
                )
            except Exception as _ao_err:
                logger.debug(f"[v298 L2] v162 EOD alert_outcomes write skipped: {_ao_err}")
            self._record_learning_outcome(bot, trade, "eod_auto_close_v162")

            return True, getattr(trade, "realized_pnl", 0.0)

        except Exception as e:
            logger.exception(
                f"[v162 EOD] {trade.symbol}: unexpected error during fast "
                f"close ({type(e).__name__}: {e})"
            )
            return False, 0.0

    async def _eod_orphan_cancel_sweep(self, bot: 'TradingBotService'):
        """Post-flatten orphan-bracket sweep — v19.34.162.

        Runs AFTER all EOD MKT closes have fired. In the common case
        IB's OCA auto-cancels the survivor children when the MKT fills,
        so this sweep finds nothing to do. The rare orphans (race
        conditions, manual TWS edits) get queued for cancellation
        without blocking the flatten path.
        """
        try:
            from routers.ib import _pushed_ib_data, queue_cancellation
        except Exception as e:
            logger.debug(f"[v162 sweep] import failed: {e}")
            return

        orders = (_pushed_ib_data or {}).get("orders") or []
        if isinstance(orders, dict):
            orders = orders.get("orders", [])
        if not orders:
            return

        queued = 0
        for ob in orders:
            try:
                status = (ob.get("status") or "").strip()
                if status not in ("PreSubmitted", "Submitted"):
                    continue
                oid = ob.get("order_id") or ob.get("orderId")
                if oid is None:
                    continue
                sym = (ob.get("symbol") or "").upper()
                queue_cancellation(
                    ib_order_id=int(oid),
                    reason=f"v162 EOD orphan sweep ({sym or 'unknown'})",
                    requested_by="position_manager_eod_v162",
                )
                queued += 1
            except Exception:
                continue
        if queued:
            logger.info(f"[v162 sweep] queued {queued} orphan cancel(s)")


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
            # v19.34.123 — Compute realized PnL on phantom-recovery
            # close. Pre-v123 only `exit_price` was set; realized_pnl
            # stayed at 0 even when the position actually moved. Fixed.
            from services.pnl_compute import apply_close_pnl
            apply_close_pnl(
                trade,
                reason=f"{reason}_phantom_recovery_v19_34_27",
                exit_price=getattr(trade, "current_price", None),
            )
            trade.status = TradeStatus.CLOSED
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

# ─────────── v19.34.31 PATCH B ─────────── # v19_34_31_PATCH_B_pre_close_cancel
                # Cancel any live IB bracket legs for this symbol BEFORE
                # the close order goes out, so we never close on top of
                # a live OCA leg (2026-05-14 bracket-stacking root cause).
                try:
                    from routers.ib import _pushed_ib_data, queue_cancellation
                    _sym_b = (getattr(trade, "symbol", "") or "").upper()
                    _orders_b = (_pushed_ib_data or {}).get("orders") or []
                    if isinstance(_orders_b, dict):
                        _orders_b = _orders_b.get("orders", [])
                    for _ob in _orders_b:
                        try:
                            if str(_ob.get("symbol") or "").upper() != _sym_b:
                                continue
                            if (_ob.get("status") or "") not in ("PreSubmitted", "Submitted"):
                                continue
                            _oid = _ob.get("order_id") or _ob.get("orderId")
                            if _oid is None:
                                continue
                            queue_cancellation(
                                ib_order_id=int(_oid),
                                reason=f"v19.34.31 Patch B: pre-close ({reason})",
                                requested_by="position_manager_close_trade_v19_34_31",
                            )
                        except Exception:
                            continue
                except Exception as _pb:
                    logger.warning(f"[v19.34.31 Patch B] pre-close (non-fatal): {_pb}")
                # ─────────── /PATCH B ───────────
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
                    # v19.34.119 — surface the IB error so callers
                    # (safety_router, retry loops) can branch on the
                    # specific failure mode instead of seeing an
                    # opaque False. Stashed on the trade object as a
                    # transient attribute so the next manage-loop
                    # close-attempt can clear it cleanly without DB
                    # schema churn.
                    try:
                        trade._last_close_error = str(err)[:300]
                        trade._last_close_error_at = datetime.now(timezone.utc).isoformat()
                    except Exception:
                        pass
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

            # v19.34.134 — stamp recently-closed-symbol cooldown.
            # Reconciler reads this to skip re-adopting symbols closed
            # within 30 min. Fixes the AJG/FLEX duplicate-close loop:
            # IB carries a position the bot didn't open → reconciler
            # adopts it → manage loop fires `stop_loss` close → IB
            # position survives → 5 min later reconciler re-adopts →
            # re-closes → fresh fake -$80 / -$694 row each cycle.
            try:
                rcs = getattr(bot, "_recently_closed_symbols", None)
                if rcs is None:
                    bot._recently_closed_symbols = {}
                    rcs = bot._recently_closed_symbols
                rcs[trade.symbol] = datetime.now(timezone.utc)
                # Lazy cleanup: prune entries older than 1h
                stale = [
                    k for k, v in rcs.items()
                    if (datetime.now(timezone.utc) - v).total_seconds() > 3600
                ]
                for k in stale:
                    rcs.pop(k, None)
            except Exception as _rcs_err:
                logger.debug(f"[v134] recently_closed_symbols stamp failed: {_rcs_err}")

            # v19.34.130 — Feed alert_outcomes for grading + learning loop.
            # This close path (operator-flatten / EOD-close / stop hit)
            # computes net_pnl inline via _apply_commission but pre-v130
            # skipped the alert_outcomes write. Result: setup-winrate-
            # breakdown never saw these closes. Fire-and-forget.
            try:
                from services.pnl_compute import _record_alert_outcome_bestEffort
                _record_alert_outcome_bestEffort(
                    trade,
                    reason,
                    {"realized_pnl": float(getattr(trade, "realized_pnl", 0) or 0),
                     "net_pnl":      float(getattr(trade, "net_pnl",      0) or 0),
                     "shares":       int(getattr(trade, "shares", 0) or 0)},
                    float(getattr(trade, "exit_price", 0) or 0),
                    "executor_close_v19_34_130",
                )
            except Exception as _ao_err:
                logger.debug(f"[v130] alert_outcomes write skipped: {_ao_err}")

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
            # v19.34.298 (Audit Phase 6 L1) — now hygiene-gated: only GENUINE
            # strategy closes (target/stop/trail/EOD/time-decay) calibrate the ML
            # confidence gate + tilt; phantom/reconciled/operator-flatten/external-
            # unwind artifacts are excluded (see _record_learning_outcome).
            self._record_learning_outcome(bot, trade, reason)

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

    async def close_trade_custom(
        self,
        trade_id: str,
        bot: 'TradingBotService',
        *,
        percentage: float = 100.0,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        reason: str = "manual_panel_close",
    ) -> Dict:
        """v19.34.72 — Operator-driven Close with order_type + partial qty.

        Distinct from `close_trade` so the bot's safety-critical
        100%-MKT close path (EOD, stop-loss, scale-out engine) is
        completely untouched.

        Args:
            percentage: 1.0..100.0 — share of remaining_shares to close.
            order_type: "market" or "limit".
            limit_price: required when order_type=="limit".
            reason: stamped on the trade record for the audit trail.

        Returns:
            {
              "success": bool,
              "trade_id": str,
              "symbol": str,
              "shares_closed": int,
              "shares_remaining": int,
              "order_type": str,
              "limit_price": Optional[float],
              "fill_price": Optional[float],
              "order_id": Optional[int],
              "status": str,
              "partial": bool,
              "error": Optional[str],
            }
        """
        from services.trading_bot_service import TradeDirection, TradeStatus

        if trade_id not in bot._open_trades:
            return {"success": False, "error": "trade_not_open", "trade_id": trade_id}

        trade = bot._open_trades[trade_id]

        # ── Validate percentage ──────────────────────────────────
        try:
            pct = float(percentage)
        except Exception:
            return {"success": False, "error": f"bad percentage: {percentage}"}
        if pct <= 0 or pct > 100:
            return {"success": False,
                    "error": f"percentage must be in (0, 100]; got {pct}"}

        # ── Validate order_type / limit_price ───────────────────
        ot = (order_type or "market").lower()
        if ot not in ("market", "limit"):
            return {"success": False, "error": f"bad order_type: {order_type}"}
        if ot == "limit":
            try:
                if limit_price is None or float(limit_price) <= 0:
                    return {"success": False,
                            "error": "limit_price required when order_type=limit"}
            except Exception:
                return {"success": False,
                        "error": f"bad limit_price: {limit_price}"}

        # ── Compute base qty (bot-tracked remaining) ────────────
        base_qty = int(trade.remaining_shares
                       if trade.remaining_shares > 0 else trade.shares)
        if base_qty <= 0:
            return {"success": False, "error": "no_shares_to_close",
                    "trade_id": trade_id, "symbol": trade.symbol}

        # ── Clamp against IB authoritative position (phantom-share guard) ──
        try:
            base_qty = await self._clamp_shares_to_ib_position(
                trade, base_qty, reason=reason
            )
        except Exception as clamp_err:
            logger.debug(
                f"close_trade_custom: phantom-share clamp errored for "
                f"{trade.symbol} ({clamp_err}); using bot-tracked count {base_qty}"
            )

        if base_qty <= 0:
            # IB shows zero — phantom recovery. Mirror close_trade.
            logger.warning(
                f"close_trade_custom: {trade.symbol} clamped to 0 shares — "
                f"IB shows no position. Marking trade {trade_id} CLOSED locally."
            )
            from services.pnl_compute import apply_close_pnl
            apply_close_pnl(
                trade,
                reason=f"{reason}_phantom_recovery_v19_34_72",
                exit_price=getattr(trade, "current_price", None),
            )
            trade.status = TradeStatus.CLOSED
            del bot._open_trades[trade_id]
            bot._closed_trades.append(trade)
            try:
                await bot._save_trade(trade)
            except Exception as e:
                logger.warning(f"close_trade_custom phantom-recovery save failed: {e}")
            return {
                "success": True, "trade_id": trade_id, "symbol": trade.symbol,
                "shares_closed": 0, "shares_remaining": 0,
                "order_type": ot, "limit_price": limit_price,
                "fill_price": None, "order_id": None,
                "status": "phantom_recovery", "partial": False,
            }

        # ── Compute shares to close from percentage ─────────────
        shares_to_close = max(1, int(round(base_qty * pct / 100.0)))
        shares_to_close = min(shares_to_close, base_qty)
        is_full_close = (shares_to_close >= base_qty) or (pct >= 100.0)

        # ── Dispatch to executor ────────────────────────────────
        if not bot._trade_executor:
            return {"success": False, "error": "trade_executor_not_available"}

        original_shares_field = trade.shares
        trade.shares = shares_to_close  # executor reads this

        try:
            result = await bot._trade_executor.close_position_custom(
                trade,
                order_type=ot,
                limit_price=(float(limit_price) if ot == "limit" else None),
            )
        except Exception as exec_err:
            trade.shares = original_shares_field
            logger.error(
                f"close_trade_custom executor exception for {trade.symbol}: {exec_err}"
            )
            return {"success": False, "error": f"executor_exception: {exec_err}",
                    "trade_id": trade_id, "symbol": trade.symbol}

        trade.shares = original_shares_field  # restore canonical field

        if not result.get("success"):
            # Stamp error for operator visibility & let manage loop continue.
            try:
                trade._last_close_error = str(result.get("error") or "executor failed")[:300]
                trade._last_close_error_at = datetime.now(timezone.utc).isoformat()
            except Exception:
                pass
            return {
                "success": False,
                "trade_id": trade_id, "symbol": trade.symbol,
                "shares_closed": 0,
                "shares_remaining": int(trade.remaining_shares or trade.shares),
                "order_type": ot, "limit_price": limit_price,
                "status": result.get("status", "rejected"),
                "error": result.get("error", "executor_failed"),
                "partial": False,
            }

        # ── Success path: book the filled slice ─────────────────
        fill_price = result.get("fill_price")
        filled_qty = int(result.get("filled_qty") or shares_to_close)
        if fill_price is None:
            # LMT may report success with no fill yet (status=working).
            # Defer booking until executor confirms a fill. Treat as
            # "submitted" — trade stays OPEN, no PnL booked.
            return {
                "success": True,
                "trade_id": trade_id, "symbol": trade.symbol,
                "shares_closed": 0,
                "shares_remaining": int(trade.remaining_shares or trade.shares),
                "order_type": ot, "limit_price": limit_price,
                "fill_price": None,
                "order_id": result.get("order_id"),
                "status": result.get("status", "working"),
                "partial": False,
                "note": "limit_order_resting_at_ib",
            }

        # Book realized PnL on the filled slice.
        if trade.direction == TradeDirection.LONG:
            slice_pnl = (float(fill_price) - trade.fill_price) * filled_qty
        else:
            slice_pnl = (trade.fill_price - float(fill_price)) * filled_qty
        trade.realized_pnl += slice_pnl
        bot._apply_commission(trade, filled_qty)

        # Decrement remaining_shares; if we set it from `shares`
        # earlier (initial size) preserve that base for arithmetic.
        if trade.remaining_shares <= 0:
            trade.remaining_shares = trade.shares
        trade.remaining_shares = max(0, trade.remaining_shares - filled_qty)

        is_now_flat = (trade.remaining_shares <= 0) or is_full_close

        if is_now_flat:
            # Full close — mirror close_trade's terminal flow.
            trade.status = TradeStatus.CLOSED
            trade.exit_price = float(fill_price)
            trade.closed_at = datetime.now(timezone.utc).isoformat()
            trade.close_reason = reason
            trade.unrealized_pnl = 0
            trade.remaining_shares = 0

            bot._daily_stats.net_pnl += trade.net_pnl
            if trade.realized_pnl > 0:
                bot._daily_stats.trades_won += 1
                bot._daily_stats.largest_win = max(
                    bot._daily_stats.largest_win, trade.realized_pnl)
            else:
                bot._daily_stats.trades_lost += 1
                bot._daily_stats.largest_loss = min(
                    bot._daily_stats.largest_loss, trade.realized_pnl)
            total = bot._daily_stats.trades_won + bot._daily_stats.trades_lost
            bot._daily_stats.win_rate = (
                bot._daily_stats.trades_won / total * 100) if total > 0 else 0

            del bot._open_trades[trade_id]
            bot._closed_trades.append(trade)

            try:
                rcs = getattr(bot, "_recently_closed_symbols", None)
                if rcs is None:
                    bot._recently_closed_symbols = {}
                    rcs = bot._recently_closed_symbols
                rcs[trade.symbol] = datetime.now(timezone.utc)
            except Exception:
                pass

            try:
                if hasattr(bot, '_stop_manager') and bot._stop_manager \
                        and hasattr(bot._stop_manager, 'forget_trade'):
                    bot._stop_manager.forget_trade(trade_id)
            except Exception as e:
                logger.warning(f"close_trade_custom: forget_trade failed: {e}")

            await bot._notify_trade_update(trade, "closed")
            await bot._save_trade(trade)
            try:
                await bot._log_trade_to_journal(trade, "exit")
            except Exception as e:
                logger.warning(f"close_trade_custom journal exit failed: {e}")
            try:
                await bot._log_trade_to_regime_performance(trade)
            except Exception:
                pass
        else:
            # Partial close — keep trade open with reduced size.
            # Append to partial_exits ledger for auditability.
            try:
                so_cfg = trade.scale_out_config or {}
                partial_exits = so_cfg.setdefault("partial_exits", [])
                partial_exits.append({
                    "source": "v19_34_72_operator_panel",
                    "order_type": ot,
                    "limit_price": (float(limit_price) if ot == "limit" else None),
                    "shares_sold": filled_qty,
                    "price": float(fill_price),
                    "pnl": round(slice_pnl, 2),
                    "reason": reason,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                logger.warning(f"close_trade_custom partial_exits append failed: {e}")

            await bot._notify_trade_update(trade, "partial_close")
            await bot._save_trade(trade)

            # NOTE: bracket children were cancelled before the close.
            # The periodic Bracket-State Reconciler (v19.34.70d) will
            # re-attach a fresh bracket to the remaining shares on its
            # next 120s tick. Operator can also fire
            # /attach-brackets-to-unprotected manually.

        return {
            "success": True,
            "trade_id": trade_id, "symbol": trade.symbol,
            "shares_closed": filled_qty,
            "shares_remaining": int(trade.remaining_shares),
            "order_type": ot, "limit_price": limit_price,
            "fill_price": float(fill_price),
            "order_id": result.get("order_id"),
            "status": result.get("status", "filled"),
            "partial": (not is_now_flat),
            "slice_pnl": round(slice_pnl, 2),
        }
