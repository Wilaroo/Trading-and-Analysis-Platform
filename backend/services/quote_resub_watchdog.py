"""
v19.34.80 — Quote-Resubscribe Watchdog.

Background loop that VERIFIES every pusher re-subscribe RPC actually
landed in the pusher's live subscription set. The pusher's existing
`/rpc/subscribe` endpoint returns 200 OK whether or not the underlying
`reqMktData` succeeded at IB, so quotes can stay stale for hours
(operator-observed 4.9hr incident) while the bot keeps thinking it
already issued a fix.

Algorithm (runs every 60s):
  1. Read `position_manager._stale_resub_set` (the symbols position_manager
     flagged as stale during the last manage loop).
  2. For each tracked symbol, ask the pusher RPC what's actually
     subscribed via `subscriptions(force_refresh=True)`.
  3. If a symbol that was supposed to be subscribed is MISSING from the
     live set:
        - Log a loud WARN
        - Fire `unsubscribe_symbols` + `subscribe_symbols` to force a
          fresh `reqMktData` at IB
        - Bump that symbol's `_attempts` counter
  4. After 3 failed cycles for the same symbol → write a
     `state_integrity_events` row with `severity="high"` and
     `event="quote_resub_watchdog_escalated"`. UI pills can pick it up.
  5. When a symbol's quote is fresh again (no longer in
     `_stale_resub_set`), clear its watchdog state.

Env gates:
  QUOTE_RESUB_WATCHDOG_ENABLED   true|false       default true
  QUOTE_RESUB_WATCHDOG_INTERVAL  seconds (float)  default 60
  QUOTE_RESUB_WATCHDOG_ESCALATE_AFTER  int        default 3
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return os.environ.get(
        "QUOTE_RESUB_WATCHDOG_ENABLED", "true"
    ).lower() == "true"


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
    """Per-symbol watchdog state — mutable across loop ticks."""

    def __init__(self) -> None:
        # symbol -> {"attempts": int, "first_seen_ms": int, "last_action_ms": int}
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


async def _record_escalation_event(
    db: Any, symbol: str, attempts: int, *,
    pusher_subs_count: Optional[int] = None,
) -> None:
    """Write a state_integrity_events row so the V5 UI / DriftGuardPill
    can surface the escalation."""
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
                "ts": datetime.now(timezone.utc).isoformat(),
            })
        )
    except Exception as e:
        logger.debug(
            "[v19.34.80 quote-resub-watchdog] failed to write event "
            "for %s: %s: %s",
            symbol, type(e).__name__, e,
        )


async def _tick(state: _State, position_manager: Any, db: Any,
                open_position_symbols: Optional[set] = None) -> Dict[str, Any]:
    """One watchdog tick. Returns a summary dict for tests + telemetry."""
    summary: Dict[str, Any] = {
        "checked": 0,
        "missing": 0,
        "resubscribed": 0,
        "escalated": 0,
        "cleared": 0,
        "pinned": 0,
    }

    # v19.34.227 — held positions to PIN into the pusher quote universe so an
    # open name can never go mark-less (separate from the stale set, which only
    # catches names that still have a — stale — quote).
    open_syms = {str(s).upper().strip() for s in (open_position_symbols or set()) if s}

    # Pull the current stale set from position_manager.
    stale_set = getattr(position_manager, "_stale_resub_set", None)
    tracked = sorted({str(s).upper().strip() for s in (stale_set or set()) if s})

    # Nothing to verify AND nothing to pin → clear recovered attempts + exit.
    if not tracked and not open_syms:
        for sym in list(state.snapshot().keys()):
            state.clear(sym)
            summary["cleared"] += 1
        return summary

    summary["checked"] = len(tracked)

    try:
        from services.ib_pusher_rpc import get_pusher_rpc_client
        rpc = get_pusher_rpc_client()
    except Exception as e:
        logger.debug(
            "[v19.34.80 quote-resub-watchdog] pusher RPC unavailable: %s: %s",
            type(e).__name__, e,
        )
        return summary

    if not rpc.is_configured():
        return summary

    # Force-refresh so we don't read a 30s-stale subscription cache.
    pusher_subs = await asyncio.to_thread(rpc.subscriptions, True)
    if pusher_subs is None:
        # Pusher unreachable — don't penalize symbols, just skip tick.
        return summary

    pusher_subs_count = len(pusher_subs)
    missing = [sym for sym in tracked if sym not in pusher_subs]

    for sym in missing:
        summary["missing"] += 1
        rec = state.note_missing(sym)
        attempts = rec["attempts"]

        logger.warning(
            "[v19.34.80 quote-resub-watchdog] %s NOT subscribed at "
            "pusher despite manage-loop request (attempt %d). "
            "pusher_subs_count=%d. Forcing unsub+resub.",
            sym, attempts, pusher_subs_count,
        )

        # Force a fresh reqMktData cycle: unsubscribe (clears any
        # half-registered IB ticker handle) then subscribe again.
        try:
            await asyncio.to_thread(rpc.unsubscribe_symbols, {sym})
            await asyncio.sleep(0.5)  # let pusher process the unsub
            await asyncio.to_thread(rpc.subscribe_symbols, {sym})
            summary["resubscribed"] += 1
        except Exception as e:
            logger.warning(
                "[v19.34.80 quote-resub-watchdog] unsub+resub for %s "
                "failed: %s: %s",
                sym, type(e).__name__, e,
            )

        if attempts >= _escalate_after():
            summary["escalated"] += 1
            await _record_escalation_event(
                db, sym, attempts,
                pusher_subs_count=pusher_subs_count,
            )

    # ── v19.34.227 — proactive PIN of held positions ──────────────────
    # Any open-position symbol missing from the pusher's live quote set is
    # subscribed NOW so the position always has a live mark (also needed for
    # local stop checks). This catches names that fell entirely out of the
    # quote universe — which the stale set above can't, since a mark-less
    # position has no (stale) quote to flag.
    held_missing = [s for s in sorted(open_syms) if s not in pusher_subs]
    if held_missing:
        logger.warning(
            "[v19.34.227 quote-resub-watchdog] PINNING %d held position(s) "
            "missing from the pusher quote universe: %s%s",
            len(held_missing), held_missing[:8],
            "…" if len(held_missing) > 8 else "",
        )
        try:
            await asyncio.to_thread(rpc.subscribe_symbols, set(held_missing))
            summary["pinned"] = len(held_missing)
        except Exception as e:
            logger.warning(
                "[v19.34.227 quote-resub-watchdog] pin subscribe failed: "
                "%s: %s", type(e).__name__, e,
            )

    # Any symbol that was missing-tracked but is now confirmed in the
    # live subscription set has effectively recovered — clear its state
    # so future drops start the attempt counter from 0.
    for sym in list(state.snapshot().keys()):
        if sym in pusher_subs and sym in tracked:
            state.clear(sym)
            summary["cleared"] += 1

    return summary


async def quote_resub_watchdog_loop(
    bot: Any, *, _state: Optional[_State] = None,
) -> None:
    """Main loop. Spawned from TradingBotService.start()."""
    if not _enabled():
        logger.warning(
            "[v19.34.80 quote-resub-watchdog] DISABLED via env "
            "(QUOTE_RESUB_WATCHDOG_ENABLED=false)"
        )
        return

    interval = _interval()
    logger.warning(
        "[v19.34.80 quote-resub-watchdog] ENABLED (interval=%.0fs, "
        "escalate_after=%d failed cycles)",
        interval, _escalate_after(),
    )

    state = _state if _state is not None else _State()

    # Wait one full interval before first sweep — let the bot's startup
    # restore + first manage-loop tick complete so the stale set is
    # meaningful.
    await asyncio.sleep(interval)

    while getattr(bot, "_running", True):
        try:
            # v19.34.227 — the bot stores these as `_position_manager` / `_db`
            # (the non-underscore lookups returned None, so `_tick` NEVER ran
            # and the stale-mark watchdog was a silent no-op in production).
            position_manager = (
                getattr(bot, "_position_manager", None)
                or getattr(bot, "position_manager", None)
            )
            db = getattr(bot, "_db", None)
            if db is None:
                db = getattr(bot, "db", None)
            # v19.34.227 — proactively PIN every held position into the pusher
            # quote universe so an open name never goes mark-less (root cause of
            # the CRM current_price=0 → fake kill-switch trip).
            open_syms = set()
            try:
                for _t in (getattr(bot, "_open_trades", {}) or {}).values():
                    _s = (getattr(_t, "symbol", "") or "").upper().strip()
                    _rs = abs(float(getattr(_t, "remaining_shares", 0) or 0))
                    if _s and _rs > 0:
                        open_syms.add(_s)
            except Exception:
                open_syms = set()
            if position_manager is not None:
                await _tick(state, position_manager, db,
                            open_position_symbols=open_syms)
        except Exception as e:
            logger.debug(
                "[v19.34.80 quote-resub-watchdog] tick error "
                "(non-fatal): %s: %s",
                type(e).__name__, e,
            )
        await asyncio.sleep(interval)
