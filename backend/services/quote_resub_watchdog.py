"""
v19.34.82 — Quote-Resubscribe Watchdog (REDESIGNED).

Independent verifier: every symbol in bot._open_trades MUST be present
in /rpc/subscriptions AND /rpc/quote-snapshot must return success:true.
Pre-v82 read position_manager._stale_resub_set which was cleared every
60s → race → blind. v82 removes that dependency.

Divergence kinds:
  missing_from_subs : tracked symbol absent from /rpc/subscriptions
  snapshot_failed   : in subs registry, but /rpc/quote-snapshot says
                      success:false (pusher split-brain; observed live
                      with UAL on 2026-05-22)

Both → unsub+resub force a fresh reqMktData. After N attempts → write
quote_resub_watchdog_events row severity=high.

Env:
  QUOTE_RESUB_WATCHDOG_ENABLED         true|false  default true
  QUOTE_RESUB_WATCHDOG_INTERVAL        seconds     default 60
  QUOTE_RESUB_WATCHDOG_ESCALATE_AFTER  int         default 3
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return os.environ.get("QUOTE_RESUB_WATCHDOG_ENABLED", "true").lower() == "true"


def _interval() -> float:
    try:
        return float(os.environ.get("QUOTE_RESUB_WATCHDOG_INTERVAL", "60"))
    except (TypeError, ValueError):
        return 60.0


def _escalate_after() -> int:
    try:
        return int(os.environ.get("QUOTE_RESUB_WATCHDOG_ESCALATE_AFTER", "3"))
    except (TypeError, ValueError):
        return 3


class _State:
    def __init__(self) -> None:
        self._attempts: Dict[str, Dict[str, Any]] = {}

    def note_missing(self, symbol: str) -> Dict[str, Any]:
        sym = symbol.upper()
        rec = self._attempts.get(sym)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        if rec is None:
            rec = {"attempts": 0, "first_seen_ms": now_ms, "last_action_ms": 0}
            self._attempts[sym] = rec
        rec["attempts"] += 1
        rec["last_action_ms"] = now_ms
        return rec

    def clear(self, symbol: str) -> None:
        self._attempts.pop(symbol.upper(), None)

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._attempts)


def _open_trade_symbols(bot: Any) -> Set[str]:
    out: Set[str] = set()
    open_trades = getattr(bot, "_open_trades", None)
    if not open_trades:
        return out
    try:
        for _tid, trade in list(open_trades.items()):
            sym = getattr(trade, "symbol", None)
            if sym:
                out.add(str(sym).upper().strip())
    except Exception as e:
        logger.debug(
            "[v19.34.82] _open_trade_symbols err: %s: %s",
            type(e).__name__, e,
        )
    return out


async def _record_escalation_event(
    db: Any, symbol: str, attempts: int, *,
    pusher_subs_count: Optional[int] = None,
    divergence_kind: str = "missing_from_subs",
) -> None:
    if db is None:
        return
    try:
        await asyncio.to_thread(
            lambda: db["quote_resub_watchdog_events"].insert_one({
                "event": "quote_resub_watchdog_escalated",
                "symbol": symbol.upper(),
                "attempts": attempts,
                "severity": "high",
                "pusher_subs_count": pusher_subs_count,
                "divergence_kind": divergence_kind,
                "version": "v19.34.82",
                "ts": datetime.now(timezone.utc).isoformat(),
            })
        )
    except Exception as e:
        logger.debug(
            "[v19.34.82] event write failed %s: %s: %s",
            symbol, type(e).__name__, e,
        )


async def _force_resub(rpc: Any, sym: str) -> bool:
    try:
        await asyncio.to_thread(rpc.unsubscribe_symbols, {sym})
        await asyncio.sleep(0.5)
        await asyncio.to_thread(rpc.subscribe_symbols, {sym})
        return True
    except Exception as e:
        logger.warning(
            "[v19.34.82] unsub+resub %s failed: %s: %s",
            sym, type(e).__name__, e,
        )
        return False


async def _tick(state: _State, bot: Any, db: Any) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "checked": 0, "missing_from_subs": 0, "snapshot_failed": 0,
        "resubscribed": 0, "escalated": 0, "cleared": 0,
    }
    tracked = _open_trade_symbols(bot)
    summary["checked"] = len(tracked)

    if not tracked:
        for sym in list(state.snapshot().keys()):
            state.clear(sym)
            summary["cleared"] += 1
        return summary

    try:
        from services.ib_pusher_rpc import get_pusher_rpc_client
        rpc = get_pusher_rpc_client()
    except Exception as e:
        logger.debug(
            "[v19.34.82] rpc unavailable: %s: %s",
            type(e).__name__, e,
        )
        return summary

    if not rpc.is_configured():
        return summary

    pusher_subs = await asyncio.to_thread(rpc.subscriptions, True)
    if pusher_subs is None:
        return summary

    pusher_subs_count = len(pusher_subs)
    missing_from_subs = [s for s in tracked if s not in pusher_subs]

    snapshot_failed = []
    for sym in tracked:
        if sym in missing_from_subs:
            continue
        try:
            snap = await asyncio.to_thread(rpc.quote_snapshot, sym)
        except Exception:
            snap = None
        if isinstance(snap, dict) and snap.get("success") is False:
            snapshot_failed.append(sym)

    to_force = list({*missing_from_subs, *snapshot_failed})
    summary["missing_from_subs"] = len(missing_from_subs)
    summary["snapshot_failed"] = len(snapshot_failed)

    for sym in to_force:
        rec = state.note_missing(sym)
        attempts = rec["attempts"]
        kind = "missing_from_subs" if sym in missing_from_subs else "snapshot_failed"
        logger.warning(
            "[v19.34.82] %s divergence=%s (attempt %d). "
            "pusher_subs_count=%d. Forcing unsub+resub.",
            sym, kind, attempts, pusher_subs_count,
        )
        if await _force_resub(rpc, sym):
            summary["resubscribed"] += 1
        if attempts >= _escalate_after():
            summary["escalated"] += 1
            await _record_escalation_event(
                db, sym, attempts,
                pusher_subs_count=pusher_subs_count,
                divergence_kind=kind,
            )

    recovered = {s for s in tracked if s in pusher_subs and s not in snapshot_failed}
    for sym in list(state.snapshot().keys()):
        if sym in recovered:
            state.clear(sym)
            summary["cleared"] += 1
    return summary


async def quote_resub_watchdog_loop(
    bot: Any, *, _state: Optional[_State] = None,
) -> None:
    if not _enabled():
        logger.warning("[v19.34.82] DISABLED via env")
        return
    interval = _interval()
    logger.warning(
        "[v19.34.82] ENABLED (interval=%.0fs, escalate_after=%d). "
        "Source: bot._open_trades vs /rpc/subscriptions + /rpc/quote-snapshot.",
        interval, _escalate_after(),
    )
    state = _state if _state is not None else _State()
    await asyncio.sleep(interval)
    while getattr(bot, "_running", True):
        try:
            db = getattr(bot, "db", None)
            await _tick(state, bot, db)
        except Exception as e:
            logger.debug("[v19.34.82] tick err: %s: %s", type(e).__name__, e)
        await asyncio.sleep(interval)


