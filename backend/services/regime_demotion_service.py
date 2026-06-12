"""v332 — Regime demotion policy.

Operator decision (2026-06-12): when the market regime flips against open
positions, do NOT flatten immediately (whipsaw pays the spread twice).
Policy:
  1. NEW entries respond instantly — `bot._current_regime` is kept live
     here (it was frozen at "RISK_ON" since boot: `_update_market_regime`
     was never wired into any loop, so the sizing multiplier
     `_regime_position_multipliers` NEVER engaged).
  2. EXISTING positions are only demoted after the flip PERSISTS for
     REGIME_DEMOTION_CONFIRM_MIN minutes (default 20). A revert during
     the window cancels the pending demotion (whipsaw guard).
  3. Demotion is SOFTWARE-STOP ONLY — zero IB order surgery, therefore
     zero orphan-order risk:
       • profitable (≥ REGIME_DEMOTION_BE_R of initial risk, default
         0.25R) and still in `original` stop mode → stop to breakeven
         via StopManager (same proven path as a T0 hit);
       • otherwise → ratchet `current_stop` to halfway between stop and
         entry (cuts remaining risk ~50%), but never so close that it
         would trigger instantly, and never LOOSER than the current
         stop. M0 ladder legs pick the new stop up in-place on the next
         manage tick (`manage_m0_trade` → `modify_stop_price`); classic
         brackets keep their IB hard stop as the disaster backstop.
  4. Scope: trade_style in {intraday, swing}. Scalps ride their HSBG
     brackets (minutes-horizon); multi_day/position/investment theses
     are not invalidated by an intraday regime flip.

Adverse mapping (states from MarketRegimeEngine):
  → RISK_OFF / CONFIRMED_DOWN confirmed  ⇒ demote LONGs
  → RISK_ON confirmed after RISK_OFF/CONFIRMED_DOWN ⇒ demote SHORTs
  → CAUTION ⇒ sizing multiplier only, no demotion (soft state).

Env knobs: REGIME_DEMOTION_ENABLED (default on),
REGIME_DEMOTION_CONFIRM_MIN (default 20), REGIME_DEMOTION_BE_R (0.25).
"""
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)

DEMOTABLE_STYLES = {"intraday", "swing"}
ADVERSE_FOR_LONG = {"RISK_OFF", "CONFIRMED_DOWN"}
_TICK_INTERVAL_S = 30.0


def _enabled() -> bool:
    return os.environ.get("REGIME_DEMOTION_ENABLED", "true").strip().lower() in (
        "1", "true", "yes", "on")


def _confirm_minutes() -> int:
    try:
        return max(1, int(os.environ.get("REGIME_DEMOTION_CONFIRM_MIN", "20")))
    except (TypeError, ValueError):
        return 20


def _be_r() -> float:
    try:
        return float(os.environ.get("REGIME_DEMOTION_BE_R", "0.25"))
    except (TypeError, ValueError):
        return 0.25


class RegimeDemotionService:
    def __init__(self):
        self._last_tick = 0.0
        self._last_regime: Optional[str] = None
        self._pending: Optional[Dict] = None  # {"from", "to", "at_ts"}

    async def tick(self, bot) -> None:
        """Called from the bot's manage loop. Cheap; self-throttled."""
        if not _enabled():
            return
        now = time.time()
        if now - self._last_tick < _TICK_INTERVAL_S:
            return
        self._last_tick = now

        engine = getattr(bot, "_market_regime_engine", None)
        if engine is None:
            return
        try:
            data = await engine.get_current_regime()
            regime = (data or {}).get("state") or "RISK_ON"
        except Exception as e:
            logger.debug(f"regime fetch failed: {e}")
            return

        # 1. Keep the bot's sizing multiplier LIVE (instant — new entries
        #    should size for the regime we're in right now).
        if regime != getattr(bot, "_current_regime", None):
            old = getattr(bot, "_current_regime", None)
            bot._current_regime = regime
            mult = getattr(bot, "_regime_position_multipliers", {}).get(regime, 1.0)
            logger.info(
                f"🌡️ [v332] regime {old} → {regime} "
                f"(sizing multiplier now {mult}x for new entries)")

        if self._last_regime is None:
            self._last_regime = regime
            return

        # 2. Flip observed → (re)arm the confirmation timer.
        if regime != self._last_regime:
            if not self._pending or self._pending["to"] != regime:
                self._pending = {"from": self._last_regime, "to": regime,
                                 "at_ts": now}
                logger.info(
                    f"[v332] regime flip {self._last_regime} → {regime} "
                    f"observed — demotion in {_confirm_minutes()}min if it holds")
                await self._emit(bot, "info", "regime_flip_observed",
                                 f"🌡️ Regime flip {self._last_regime} → {regime} — "
                                 f"holding fire {_confirm_minutes()}min before "
                                 f"demoting conflicting positions (whipsaw guard).")
            self._last_regime = regime
            return

        # 3. Stable regime — resolve a pending flip.
        if self._pending:
            if self._pending["to"] != regime:
                logger.info(f"[v332] pending demotion to {self._pending['to']} "
                            f"cancelled — regime reverted to {regime}")
                self._pending = None
            elif (now - self._pending["at_ts"]) >= _confirm_minutes() * 60:
                pend, self._pending = self._pending, None
                await self._demote_pass(bot, pend)

    async def _demote_pass(self, bot, pend: Dict) -> None:
        to, frm = pend["to"], pend["from"]
        demote_long = to in ADVERSE_FOR_LONG
        demote_short = (to == "RISK_ON" and frm in ADVERSE_FOR_LONG)
        if not (demote_long or demote_short):
            return  # CAUTION etc. — sizing only.

        stats: Dict[str, int] = {}
        details = []
        for t in list((getattr(bot, "_open_trades", {}) or {}).values()):
            try:
                outcome = self._demote_one(bot, t, demote_long, demote_short, to)
            except Exception as e:
                outcome = "error"
                logger.warning(f"[v332] demote {getattr(t,'symbol','?')} raised: {e}")
            stats[outcome] = stats.get(outcome, 0) + 1
            if outcome in ("be", "tightened"):
                details.append(f"{t.symbol}:{outcome}")

        acted = stats.get("be", 0) + stats.get("tightened", 0)
        summary = (f"🌡️ Regime {frm} → {to} CONFIRMED "
                   f"({_confirm_minutes()}min) — demoted {acted} position(s): "
                   f"{stats.get('be', 0)} to breakeven, "
                   f"{stats.get('tightened', 0)} tightened"
                   + (f" [{', '.join(details)}]" if details else "")
                   + ". Scalps ride their brackets; long-horizon holds exempt.")
        logger.warning(f"[v332] {summary} (full stats: {stats})")
        await self._emit(bot, "decision", "regime_demotion", summary)
        try:
            db = getattr(bot, "_db", None)
            if db is not None:
                db["state_integrity_events"].insert_one({
                    "event": "regime_demotion", "severity": "medium",
                    "from_regime": frm, "to_regime": to,
                    "stats": stats, "details": details,
                    "ts": datetime.now(timezone.utc).isoformat(),
                })
        except Exception:
            pass

    def _demote_one(self, bot, t, demote_long: bool, demote_short: bool,
                    to: str) -> str:
        style = (getattr(t, "trade_style", "") or "").lower()
        if style not in DEMOTABLE_STYLES:
            return "style_exempt"
        tcfg = getattr(t, "trailing_stop_config", {}) or {}
        if tcfg.get("regime_demoted"):
            return "already_demoted"

        from services.trading_bot_service import TradeDirection
        is_long = t.direction == TradeDirection.LONG
        if is_long and not demote_long:
            return "direction_ok"
        if (not is_long) and not demote_short:
            return "direction_ok"

        entry = float(getattr(t, "fill_price", 0) or getattr(t, "entry_price", 0) or 0)
        cur_stop = float(tcfg.get("current_stop") or getattr(t, "stop_price", 0) or 0)
        px = float(getattr(t, "current_price", 0) or 0)
        if entry <= 0 or cur_stop <= 0 or px <= 0:
            return "no_data"
        risk = abs(entry - cur_stop)
        if risk <= 0:
            return "no_risk"

        sm = getattr(bot, "_stop_manager", None)
        if sm is None:
            return "no_stop_manager"

        mode = tcfg.get("mode", "original")
        stamp = {"to": to, "at": datetime.now(timezone.utc).isoformat()}

        # Already in a protective mode (BE/trailing) — nothing to add.
        if mode in ("breakeven", "trailing"):
            tcfg["regime_demoted"] = {**stamp, "action": "already_protective"}
            return "already_protective"

        pnl_r = ((px - entry) if is_long else (entry - px)) / risk

        # Profitable enough → breakeven via the proven StopManager path.
        if pnl_r >= _be_r():
            sm._move_stop_to_breakeven(t)
            tcfg["regime_demoted"] = {**stamp, "action": "be"}
            return "be"

        # Losing/flat → ratchet the software stop halfway to entry.
        halfway = (entry + cur_stop) / 2.0
        if is_long:
            new_stop = max(cur_stop, halfway)            # never loosen
            if px <= new_stop * 1.001:                   # would trigger now
                tcfg["regime_demoted"] = {**stamp, "action": "too_close"}
                return "too_close"
            tighter = new_stop > cur_stop
        else:
            new_stop = min(cur_stop, halfway)
            if px >= new_stop * 0.999:
                tcfg["regime_demoted"] = {**stamp, "action": "too_close"}
                return "too_close"
            tighter = new_stop < cur_stop
        if not tighter:
            tcfg["regime_demoted"] = {**stamp, "action": "already_tighter"}
            return "already_tighter"

        new_stop = round(new_stop, 4)
        tcfg["current_stop"] = new_stop
        sm._record_stop_adjustment(
            t, cur_stop, new_stop, f"regime_demotion_{to.lower()}")
        tcfg["regime_demoted"] = {**stamp, "action": "tightened",
                                  "old_stop": cur_stop, "new_stop": new_stop}
        return "tightened"

    async def _emit(self, bot, kind: str, event: str, text: str) -> None:
        try:
            from services.sentcom_service import emit_stream_event
            await emit_stream_event({
                "kind": kind, "event": event, "symbol": None, "text": text,
                "metadata": {"source": "regime_demotion_service"},
            })
        except Exception:
            pass


_service: Optional[RegimeDemotionService] = None


def get_regime_demotion_service() -> RegimeDemotionService:
    global _service
    if _service is None:
        _service = RegimeDemotionService()
    return _service
