"""Thesis-Invalidation Exit detector (P5, ARC-3) — OBSERVE-first.

Watches OPEN positions for a dying *reason* and LOGS a thesis-invalidation
event so we can measure (shadow) whether exiting on invalidation would have
beaten holding to the mechanical stop/target — BEFORE any live close.

Trigger types (both regime-based; mid-trade negative-catalyst and setup-
premise-broken are DEFERRED until a live catalyst feed exists):
  • regime_hostile_cell — the position's (canon setup x dir x CURRENT regime
    band) is now statistically hostile per the SAME T6 setup_regime_expectancy
    table that P4/regime_fit use (decide_suppression -> SKIP), AND the entry
    band was NOT hostile (a genuine flip, not hostile-from-the-start).
  • hard_regime_flip — the regime band flipped to the opposite extreme against
    the position (long: entry BULL>60 -> now BEAR<=45; short: BEAR -> BULL).

MODE = off | observe | active  (THESIS_INVALIDATION_MODE, default "observe").
- observe (default): records would-be exits, NEVER closes/trims. Pure data collection.
- active: after a trigger PERSISTS for THESIS_INVALIDATION_HYSTERESIS_SECONDS
  (default 180s, whipsaw guard) and is still firing, ACTS by severity:
    HARD (hard_regime_flip) -> full close via close_trade().
    SOFT (regime_hostile_cell) -> partial TRIM (THESIS_INVALIDATION_TRIM_PCT,
      default 0.5) + tighten the runner's internal stop, leaving it a chance to
      recover. Natural escalation: a later hard flip then closes the runner.
  Only trigger types in THESIS_INVALIDATION_ACT_TRIGGERS (default both) may act;
  capped at THESIS_INVALIDATION_MAX_ACTIONS_PER_CYCLE (default 5). Default MODE is
  observe, so everything stays DORMANT until the operator reviews the report.
This NEVER raises into the manage loop. Deduped: one action per (trade, trigger).
"""
import os
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

COLLECTION = "thesis_invalidation_signals"


def mode() -> str:
    return os.environ.get("THESIS_INVALIDATION_MODE", "observe").strip().lower()


def _hysteresis_seconds() -> int:
    """A trigger must KEEP firing this long after first-seen before ACTIVE acts."""
    try:
        return max(0, int(float(os.environ.get("THESIS_INVALIDATION_HYSTERESIS_SECONDS", "180"))))
    except (TypeError, ValueError):
        return 180


def _act_triggers() -> set:
    """Which trigger types may ACT in active mode. Default = both (MODE gates everything)."""
    raw = os.environ.get("THESIS_INVALIDATION_ACT_TRIGGERS", "hard_regime_flip,regime_hostile_cell")
    return {s.strip() for s in str(raw).split(",") if s.strip()}


# Severity -> action. HARD = full close; SOFT = partial trim + tighten the runner's
# internal stop (gives the position a chance to recover instead of all-or-nothing).
TRIGGER_SEVERITY = {"hard_regime_flip": "hard", "regime_hostile_cell": "soft"}


def _action_for(ttype) -> str:
    return "trim" if TRIGGER_SEVERITY.get(ttype, "hard") == "soft" else "close"


def _trim_fraction() -> float:
    try:
        return min(0.95, max(0.05, float(os.environ.get("THESIS_INVALIDATION_TRIM_PCT", "0.5"))))
    except (TypeError, ValueError):
        return 0.5


def _max_actions() -> int:
    try:
        return max(1, int(float(os.environ.get("THESIS_INVALIDATION_MAX_ACTIONS_PER_CYCLE", "5"))))
    except (TypeError, ValueError):
        return 5


def _age_seconds(iso) -> float:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:
        return 0.0


async def _act_close(bot, tid, ttype) -> bool:
    """ACTIVE-mode live close — reuses the bot's canonical single-trade close path."""
    try:
        pm = getattr(bot, "_position_manager", None)
        if pm is None or not hasattr(pm, "close_trade"):
            return False
        ok = await pm.close_trade(tid, bot, reason=f"thesis_invalidation:{ttype}")
        logger.warning("[thesis-invalidation] ACTIVE close fired: %s trade=%s ok=%s",
                       ttype, tid, ok)
        return bool(ok)
    except Exception as e:
        logger.warning("[thesis-invalidation] active close FAILED trade=%s: %s", tid, e)
        return False


async def _act_trim(bot, trade, ttype) -> bool:
    """ACTIVE-mode SOFT exit — partial trim + tighten the runner's internal stop."""
    try:
        pm = getattr(bot, "_position_manager", None)
        if pm is None or not hasattr(pm, "trim_position"):
            return False
        res = await pm.trim_position(trade, _trim_fraction(), bot,
                                     reason=f"thesis_invalidation:{ttype}")
        logger.warning("[thesis-invalidation] ACTIVE trim fired: %s trade=%s res=%s",
                       ttype, getattr(trade, "id", "?"), res)
        return bool(res.get("success"))
    except Exception as e:
        logger.warning("[thesis-invalidation] active trim FAILED trade=%s: %s",
                       getattr(trade, "id", "?"), e)
        return False


def _dir(trade) -> str:
    d = getattr(trade, "direction", "long")
    return (d.value if hasattr(d, "value") else str(d)).lower()


def _clean_r(pnl, risk):
    try:
        ra = float(risk)
        if ra > 0:
            return max(-10.0, min(10.0, float(pnl) / ra))
    except (TypeError, ValueError):
        pass
    return None


def _unrealized_r(trade):
    """Best-effort unrealized R at signal time (upl/risk, then mark-derived)."""
    r = _clean_r(getattr(trade, "unrealized_pnl", None), getattr(trade, "risk_amount", None))
    if r is not None:
        return round(r, 3)
    try:
        fill = float(getattr(trade, "fill_price", 0) or 0)
        stop = float(getattr(trade, "stop_price", 0) or 0)
        cur = float(getattr(trade, "current_price", 0) or 0)
        risk = abs(fill - stop)
        if fill and cur and risk > 0:
            v = (cur - fill) / risk if _dir(trade) == "long" else (fill - cur) / risk
            return round(v, 3)
    except (TypeError, ValueError):
        pass
    return None


def _hard_flip(entry_band, cur_band, direction) -> bool:
    if not entry_band or not cur_band:
        return False
    if direction == "long":
        return entry_band == "BULL>60" and cur_band == "BEAR<=45"
    return entry_band == "BEAR<=45" and cur_band == "BULL>60"


async def observe_open_positions(bot) -> dict:
    """Per-cycle scan of open positions. Best-effort; NEVER raises."""
    m = mode()
    if m == "off":
        return {"mode": "off", "new_signals": 0}
    try:
        db = getattr(bot, "_db", None)
        if db is None:
            return {"mode": m, "new_signals": 0, "skipped": "no_db"}
        open_trades = [
            t for t in getattr(bot, "_open_trades", {}).values()
            if "closed" not in str(getattr(t, "status", "")).lower()
        ]
        if not open_trades:
            return {"mode": m, "new_signals": 0}

        from services.ai_modules.regime_expectancy_calibrator import (
            band_of, decide_suppression,
        )

        # Current regime band — once per cycle (regime engine is cached).
        cur_score = None
        re = getattr(bot, "_market_regime_engine", None)
        if re is not None:
            try:
                rd = await re.get_current_regime()
                cur_score = (rd or {}).get("composite_score")
            except Exception:
                cur_score = None
        cur_band = band_of(cur_score)
        if not cur_band:
            return {"mode": m, "new_signals": 0, "skipped": "no_regime"}

        # T6 expectancy table — once per cycle.
        exp = db["setup_regime_expectancy"].find_one({"_id": "current"}) or {}
        cells = exp.get("cells") or {}
        params = exp.get("params") or {}

        from services.setup_taxonomy import canonicalize
        col = db[COLLECTION]

        # Dedup + hysteresis state in ONE query: existing signal docs for the
        # currently-open trades, keyed by (trade_id, trigger_type).
        open_ids = [getattr(t, "id", "") for t in open_trades if getattr(t, "id", "")]
        existing = {}
        if open_ids:
            for d in col.find({"trade_id": {"$in": open_ids}}):
                existing[(d.get("trade_id"), d.get("trigger_type"))] = d

        act_triggers = _act_triggers()
        hysteresis = _hysteresis_seconds()
        max_actions = _max_actions()
        new = 0
        acted = 0
        for t in open_trades:
            try:
                setup = getattr(t, "setup_type", "") or ""
                if not setup:
                    continue
                direction = _dir(t)
                canon = canonicalize(setup)
                ec = getattr(t, "entry_context", None)
                ec = ec if isinstance(ec, dict) else {}
                entry_band = band_of(ec.get("regime_score"))

                triggers = []
                # 1) table hostile-cell at the CURRENT band (genuine flip only)
                if cells:
                    sup = decide_suppression(cells, canon, direction, cur_band, params)
                    if sup.get("action") == "SKIP":
                        entry_sup = (
                            decide_suppression(cells, canon, direction, entry_band, params)
                            if entry_band else {"action": "NONE"}
                        )
                        if entry_sup.get("action") != "SKIP":  # wasn't hostile at entry
                            triggers.append((
                                "regime_hostile_cell",
                                f"{canon} {direction} now hostile in {cur_band}: {sup.get('reason')}",
                            ))
                # 2) hard regime flip against the position
                if _hard_flip(entry_band, cur_band, direction):
                    triggers.append((
                        "hard_regime_flip",
                        f"regime flipped {entry_band} -> {cur_band} against {direction}",
                    ))

                tid = getattr(t, "id", "") or ""
                for ttype, reason in triggers:
                    key = (tid, ttype)
                    prior = existing.get(key)

                    if prior is None:
                        # First sight — record an OBSERVE signal. Never acts on
                        # first sight (hysteresis: trigger must persist).
                        col.insert_one({
                            "trade_id": tid,
                            "alert_id": getattr(t, "alert_id", "") or "",
                            "symbol": getattr(t, "symbol", "") or "",
                            "setup_type": setup,
                            "canonical_setup": canon,
                            "direction": direction,
                            "trigger_type": ttype,
                            "reason": reason,
                            "entry_band": entry_band,
                            "current_band": cur_band,
                            "entry_regime_score": ec.get("regime_score"),
                            "current_regime_score": cur_score,
                            "unrealized_r_at_signal": _unrealized_r(t),
                            "unrealized_pnl_at_signal": float(getattr(t, "unrealized_pnl", 0) or 0),
                            "mode": m,
                            "acted": False,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        })
                        existing[key] = {"acted": False}
                        new += 1
                        continue

                    # Already recorded — consider ACTING (active mode only). The
                    # trigger must still be firing (we are here) AND have persisted
                    # >= hysteresis since first-seen. HARD -> close; SOFT -> trim.
                    if (m == "active" and not prior.get("acted")
                            and ttype in act_triggers and acted < max_actions
                            and prior.get("_id") is not None
                            and _age_seconds(prior.get("created_at")) >= hysteresis):
                        action = _action_for(ttype)
                        ok = (await _act_trim(bot, t, ttype) if action == "trim"
                              else await _act_close(bot, tid, ttype))
                        if ok:
                            col.update_one(
                                {"_id": prior["_id"]},
                                {"$set": {
                                    "acted": True,
                                    "action": action,
                                    "acted_at": datetime.now(timezone.utc).isoformat(),
                                    "close_reason": f"thesis_invalidation:{ttype}",
                                }},
                            )
                            prior["acted"] = True
                            acted += 1
            except Exception as e:
                logger.debug("thesis-invalidation per-trade skip (%s): %s",
                             type(e).__name__, e)

        return {"mode": m, "new_signals": new, "acted": acted,
                "open_positions": len(open_trades), "current_band": cur_band}
    except Exception as e:
        logger.debug("thesis-invalidation observe skipped (%s): %s", type(e).__name__, e)
        return {"mode": m, "new_signals": 0, "error": type(e).__name__}


async def generate_report(db, days: int = 30) -> dict:
    """Compare 'exit at invalidation' (unrealized_r_at_signal) vs 'held to close'
    (realized clean_R) for signals whose trade has since closed.

    avg_r_delta > 0 => exiting at the invalidation signal beat holding.
    """
    out = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "report_period_days": days,
        "mode": mode(),
        "total_signals": 0,
        "scored": 0,
        "would_have_helped": 0,
        "would_have_hurt": 0,
        "avg_r_delta": None,
        "by_trigger": [],
    }
    if db is None:
        return out

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    sigs = list(db[COLLECTION].find({"created_at": {"$gte": cutoff}}))
    out["total_signals"] = len(sigs)

    by_t = {}
    deltas = []
    for s in sigs:
        ttype = s.get("trigger_type", "?")
        bt = by_t.setdefault(ttype, {
            "trigger_type": ttype, "signals": 0, "scored": 0,
            "helped": 0, "hurt": 0, "_sum": 0.0,
        })
        bt["signals"] += 1
        tid = s.get("trade_id")
        if not tid:
            continue
        tr = db.bot_trades.find_one({"id": tid, "status": "closed"})
        if not tr:
            continue
        held_r = _clean_r(tr.get("realized_pnl"), tr.get("risk_amount"))
        exit_r = s.get("unrealized_r_at_signal")
        if held_r is None or exit_r is None:
            continue
        delta = exit_r - held_r  # +ve => exiting at the signal beat holding
        deltas.append(delta)
        bt["scored"] += 1
        bt["_sum"] += delta
        out["scored"] += 1
        if delta > 0:
            bt["helped"] += 1
            out["would_have_helped"] += 1
        elif delta < 0:
            bt["hurt"] += 1
            out["would_have_hurt"] += 1

    for bt in by_t.values():
        bt["avg_r_delta"] = round(bt["_sum"] / bt["scored"], 3) if bt["scored"] else None
        del bt["_sum"]
    out["by_trigger"] = sorted(by_t.values(), key=lambda x: x["trigger_type"])
    out["avg_r_delta"] = round(sum(deltas) / len(deltas), 3) if deltas else None
    return out
