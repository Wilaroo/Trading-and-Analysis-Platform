"""
v19.34.249 (F1) — Learning-loop COVERAGE RECONCILER.

The audit (v248/v248b) proved the learning loop only saw ~17% of closed trades:
`record_trade_outcome` lives only inside `close_trade`, and `alert_outcomes` is
fed by `apply_close_pnl` — but the OCA-external sweep, EOD auto-close, operator
close-panel and consolidation paths set status INLINE and skip both, so 238
genuine wins/losses (mostly bracket target/stop fills) never reached
`trade_outcomes` / `alert_outcomes` / `strategy_stats`.

This reconciler closes that gap WITHOUT touching any close path (zero risk to the
safety-critical cancel/close handshake). It scans closed `bot_trades` missing
from the sinks and ingests them idempotently using each trade's STORED entry-time
`entry_context` / `market_regime` (NOT a stale recapture), honoring the existing
hygiene `genuine` tag:

  • alert_outcomes  ← every missing close (genuine + tagged-artifact), via the
                      canonical `_record_alert_outcome_bestEffort` (which also
                      drives the F3 genuine strategy_stats recompute).
  • trade_outcomes  ← GENUINE missing closes only (phantom/wrong-direction sweeps
                      are execution artifacts, not strategy outcomes — kept out of
                      the learning_stats win-rate/EV exactly like strategy_stats).

It deliberately does NOT call `LearningLoopService.record_trade_outcome`, because
that has LIVE side-effects (tilt state, confidence-gate, session counters, context
recapture) that would be corrupted by replaying historical trades.

Used by: scripts/backfill_v19_34_249_learning_coverage.py (one-time backlog) and
the scheduled reconcile hook in trading_scheduler.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _f(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _dir_str(d) -> str:
    return str(getattr(d, "value", d) or "long").lower()


def _resolve_exit(bt: Dict[str, Any], entry: Optional[float], direction: str) -> Optional[float]:
    """Exit price for R/outcome. OCA-external/EOD sweeps set realized_pnl from the
    IB fill but never persist exit_price — reconstruct it from realized_pnl/shares
    so those (the bulk of bracket target/stop fills) aren't lost to no-price skip."""
    xp = _f(bt.get("exit_price"))
    if xp:
        return xp
    realized = _f(bt.get("realized_pnl"))
    shares = _f(bt.get("shares"))
    if entry and realized is not None and shares and shares > 0:
        pps = realized / shares
        return round(entry + pps, 4) if direction == "long" else round(entry - pps, 4)
    return None


def _time_of_day_et(entry_time: Optional[str]) -> str:
    """Coarse ET session bucket from an ISO entry timestamp (best-effort)."""
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(str(entry_time).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        et = dt.astimezone(ZoneInfo("America/New_York"))
        m = et.hour * 60 + et.minute
        if m < 10 * 60:
            return "open"
        if m < 12 * 60:
            return "morning"
        if m < 14 * 60:
            return "midday"
        if m < 15 * 60 + 30:
            return "afternoon"
        return "close"
    except Exception:
        return ""


class _TradeView:
    """Minimal trade-like adapter over a persisted bot_trades dict, exposing the
    attribute surface `_record_alert_outcome_bestEffort` + hygiene read."""

    def __init__(self, bt: Dict[str, Any]):
        self.id = bt.get("id") or bt.get("trade_id")
        self.alert_id = bt.get("alert_id")
        self.symbol = bt.get("symbol")
        self.setup_type = bt.get("setup_type")
        self.direction = _dir_str(bt.get("direction"))  # plain str → getattr(.,'value',str) ok
        self.fill_price = _f(bt.get("fill_price"))
        self.stop_price = _f(bt.get("stop_price")) or _f(bt.get("stop_loss"))
        self.stop_loss = self.stop_price
        tps = bt.get("target_prices") or []
        self.tp_price = _f(tps[0]) if tps else _f(bt.get("tp_price")) or _f(bt.get("target"))
        self.target = self.tp_price
        self.shares = bt.get("shares")
        self.trade_grade = bt.get("trade_grade")
        self.smb_grade = bt.get("smb_grade")
        self.entered_by = bt.get("entered_by", "")
        self.closed_at = bt.get("closed_at")
        self.executed_at = bt.get("executed_at")
        self.created_at = bt.get("created_at")


def _build_trade_outcome_doc(bt: Dict[str, Any], genuine: bool) -> Optional[dict]:
    """Construct a trade_outcomes doc directly from the stored bot_trade, using
    its entry-time context. Returns None if it lacks the prices to compute R."""
    entry = _f(bt.get("fill_price"))
    direction = _dir_str(bt.get("direction"))
    exit_p = _resolve_exit(bt, entry, direction)
    stop = _f(bt.get("stop_price")) or _f(bt.get("stop_loss"))
    if not (entry and exit_p and stop):
        return None
    risk = abs(entry - stop)
    pps = (exit_p - entry) if direction == "long" else (entry - exit_p)
    actual_r = round(pps / risk, 4) if risk > 0 else 0.0
    tps = bt.get("target_prices") or []
    target = _f(tps[0]) if tps else (_f(bt.get("tp_price")) or _f(bt.get("target")))
    if not target:
        target = entry * (1.02 if direction == "long" else 0.98)
    planned_r = round(abs(target - entry) / risk, 4) if risk > 0 else 2.0
    realized = _f(bt.get("realized_pnl")) or 0.0
    outcome = "won" if realized > 0 else ("lost" if realized < 0 else "breakeven")

    entry_ctx = dict(bt.get("entry_context") or {})
    entry_time = bt.get("executed_at") or bt.get("created_at")
    context = {
        **entry_ctx,
        "market_regime": bt.get("market_regime") or entry_ctx.get("market_regime") or "UNKNOWN",
        "time_of_day": entry_ctx.get("time_of_day") or _time_of_day_et(entry_time),
        "reconciled": True,
    }
    return {
        "id": str(uuid.uuid4()),
        "alert_id": bt.get("alert_id") or bt.get("id") or bt.get("trade_id"),
        "bot_trade_id": bt.get("id") or bt.get("trade_id"),
        "symbol": bt.get("symbol"),
        "setup_type": bt.get("setup_type"),
        "strategy_name": bt.get("setup_type"),
        "direction": direction,
        "trade_style": bt.get("trade_style") or bt.get("trade_type") or "move_2_move",
        "entry_price": entry,
        "exit_price": exit_p,
        "stop_price": stop,
        "target_price": target,
        "outcome": outcome,
        "pnl": realized,
        "pnl_percent": round((realized / (entry * (bt.get("shares") or 1))) * 100, 4)
        if entry and (bt.get("shares") or 0) else 0.0,
        "actual_r": actual_r,
        "planned_r": planned_r,
        "context": context,
        "execution": {},  # live execution metrics unavailable for backfilled closes
        "confirmation_signals": bt.get("confirmation_signals") or [],
        "entry_time": entry_time,
        "exit_time": bt.get("closed_at"),
        "catalyst_tag": bt.get("catalyst_tag") or entry_ctx.get("catalyst_tag") or "",
        "gap_pct": _f(bt.get("gap_pct")) or _f(entry_ctx.get("gap_pct")) or 0.0,
        "genuine": genuine,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "learning_reconciler_v19_34_249",
        "backfilled": True,
    }


def reconcile(db, *, days: Optional[int] = None, commit: bool = False,
              verbose: bool = True) -> dict:
    """Scan closed bot_trades and ingest any missing into alert_outcomes (all) and
    trade_outcomes (genuine only). Idempotent. Returns a report dict.

    days=None → all-time (historical backfill). commit=False → dry run."""
    from services.trade_outcome_hygiene import classify_close
    from services import pnl_compute

    # v19.34.249b — ensure the canonical alert_outcomes/strategy_stats writers
    # use THIS db. Standalone scripts run without MONGO_URL in-env, so
    # pnl_compute's lazy _AO_DB would be None and every write/recompute would
    # silently no-op (the first --commit run wrote 0 alert_outcomes for exactly
    # this reason). In-server _AO_DB is already set → this is a no-op there.
    if getattr(pnl_compute, "_AO_DB", None) is None:
        pnl_compute._AO_DB = db

    q: Dict[str, Any] = {"status": {"$in": ["closed", "CLOSED"]}}
    if days:
        from datetime import timedelta
        q["closed_at"] = {"$gte": (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()}

    closed = list(db["bot_trades"].find(q))
    existing_to = {d.get("bot_trade_id") for d in db["trade_outcomes"].find({}, {"_id": 0, "bot_trade_id": 1})}
    existing_ao = set()
    for d in db["alert_outcomes"].find({}, {"_id": 0, "trade_id": 1}):
        existing_ao.add(d.get("trade_id"))

    rep = {"closed_scanned": len(closed), "ao_written": 0, "to_written": 0,
           "to_skipped_nongenuine": 0, "skipped_no_prices": 0, "affected_setups": set()}

    for bt in closed:
        tid = bt.get("id") or bt.get("trade_id")
        if not tid:
            continue
        entry = _f(bt.get("fill_price"))
        direction = _dir_str(bt.get("direction"))
        exit_p = _resolve_exit(bt, entry, direction)
        genuine, _tag = classify_close(
            close_reason=bt.get("close_reason"),
            entered_by=str(bt.get("entered_by") or ""),
            entry_price=entry, exit_price=exit_p,
            net_pnl=_f(bt.get("net_pnl")) or _f(bt.get("realized_pnl")) or 0.0,
            hold_seconds=None,
            setup_type=str(bt.get("setup_type") or ""),
        )

        # ── alert_outcomes (every missing close) ──────────────────────
        if tid not in existing_ao and exit_p is not None:
            rep["affected_setups"].add(pnl_compute._base_setup(bt.get("setup_type")))
            if commit:
                try:
                    pnl_compute._record_alert_outcome_bestEffort(
                        _TradeView(bt), bt.get("close_reason") or "reconciled_v249",
                        {"realized_pnl": _f(bt.get("realized_pnl")) or 0.0,
                         "net_pnl": _f(bt.get("net_pnl")) or _f(bt.get("realized_pnl")) or 0.0,
                         "shares": bt.get("shares")},
                        exit_p, "learning_reconciler_v19_34_249",
                    )
                except Exception as e:
                    logger.debug("[reconciler] alert_outcomes write failed %s: %s", tid, e)
            rep["ao_written"] += 1

        # ── trade_outcomes (GENUINE only) ─────────────────────────────
        if tid not in existing_to:
            if not genuine:
                rep["to_skipped_nongenuine"] += 1
            else:
                doc = _build_trade_outcome_doc(bt, genuine)
                if doc is None:
                    rep["skipped_no_prices"] += 1
                else:
                    if commit:
                        try:
                            db["trade_outcomes"].update_one(
                                {"bot_trade_id": tid}, {"$setOnInsert": doc}, upsert=True)
                        except Exception as e:
                            logger.debug("[reconciler] trade_outcomes write failed %s: %s", tid, e)
                    rep["to_written"] += 1

    # ── final canonical recompute for affected setups (F3) ────────────
    if commit and rep["affected_setups"]:
        from services import pnl_compute as _pc
        _pc._get_outcomes_collection()  # init _AO_DB
        for bs in rep["affected_setups"]:
            if bs:
                _pc.recompute_strategy_stats_for_setup(bs, genuine_only=True)

    rep["affected_setups"] = sorted(x for x in rep["affected_setups"] if x)
    if verbose:
        mode = "COMMIT" if commit else "DRY-RUN"
        logger.info(
            "[reconciler v249 %s] scanned=%d  alert_outcomes+=%d  trade_outcomes+=%d  "
            "skipped(non-genuine TO)=%d  skipped(no prices)=%d  setups=%d",
            mode, rep["closed_scanned"], rep["ao_written"], rep["to_written"],
            rep["to_skipped_nongenuine"], rep["skipped_no_prices"], len(rep["affected_setups"]),
        )
    return rep
